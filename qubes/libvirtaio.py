#!/usr/bin/env python3

import asyncio
import ctypes
import itertools
import logging

import libvirt

ctypes.pythonapi.PyCapsule_GetPointer.restype = ctypes.c_void_p
ctypes.pythonapi.PyCapsule_GetPointer.argtypes = (
        ctypes.py_object, ctypes.c_char_p)

virFreeCallback = ctypes.CFUNCTYPE(None, ctypes.c_void_p)

try:
    asyncio.ensure_future
except AttributeError:
    asyncio.ensure_future = asyncio.async

class LibvirtAsyncIOEventImpl(object):
    class Callback(object):
        # pylint: disable=too-few-public-methods
        _iden_counter = itertools.count()
        def __init__(self, impl, cb, opaque, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.iden = next(self._iden_counter)
            self.impl = impl
            self.cb = cb
            self.opaque = opaque

            assert self.iden not in self.impl.callbacks, \
                'found {} callback: {!r}'.format(
                    self.iden, self.impl.callbacks[self.iden])
            self.impl.callbacks[self.iden] = self

        def close(self):
            self.impl.log.debug('callback %d close(), scheduling ff', self.iden)

            # Now this is cheating but we have no better option.
            dummy, caps_opaque, caps_ff = self.opaque
            ff = virFreeCallback(ctypes.pythonapi.PyCapsule_GetPointer(
                caps_ff, b'virFreeCallback'))

            if ff:
                real_opaque = ctypes.pythonapi.PyCapsule_GetPointer(
                    caps_opaque, b'void*')
                self.impl.loop.call_soon(ff, real_opaque)


    class FDCallback(Callback):
        # pylint: disable=too-few-public-methods
        def __init__(self, *args, descriptor, event, **kwargs):
            super().__init__(*args, **kwargs)
            self.descriptor = descriptor
            self.event = event

            self.descriptor.callbacks[self.iden] = self

        def close(self):
            del self.descriptor.callbacks[self.iden]
            super().close()


    class TimeoutCallback(Callback):
        def __init__(self, *args, timeout=None, **kwargs):
            super().__init__(*args, **kwargs)
            self.timeout = timeout
            self.task = None

        @asyncio.coroutine
        def timer(self):
            while True:
                try:
                    timeout = self.timeout * 1e-3
                    self.impl.log.debug('sleeping %r', timeout)
                    yield from asyncio.sleep(timeout)
                except asyncio.CancelledError:
                    self.impl.log.debug('timer %d cancelled', self.iden)
                    break
                self.cb(self.iden, self.opaque)
                self.impl.log.debug('timer %r callback ended', self.iden)

        def start(self):
            self.impl.log.debug('timer %r start', self.iden)
            if self.task is not None:
                return
            self.task = asyncio.ensure_future(self.timer())

        def stop(self):
            self.impl.log.debug('timer %r stop', self.iden)
            if self.task is None:
                return
            self.task.cancel()  # pylint: disable=no-member
            self.task = None

        def close(self):
            self.stop()
            super().close()


    class DescriptorDict(dict):
        class Descriptor(object):
            def __init__(self, loop, fd):
                self.loop = loop
                self.fd = fd
                self.callbacks = {}

                self.loop.add_reader(
                    self.fd, self.handle, libvirt.VIR_EVENT_HANDLE_READABLE)
                self.loop.add_writer(
                    self.fd, self.handle, libvirt.VIR_EVENT_HANDLE_WRITABLE)

            def close(self):
                self.loop.remove_reader(self.fd)
                self.loop.remove_writer(self.fd)

            def handle(self, event):
                for callback in self.callbacks.values():
                    if callback.event is not None and callback.event & event:
                        callback.cb(
                            callback.iden, self.fd, event, callback.opaque)

        def __init__(self, loop):
            super().__init__()
            self.loop = loop
        def __missing__(self, fd):
            descriptor = self.Descriptor(self.loop, fd)
            self[fd] = descriptor
            return descriptor

    def __init__(self, loop):
        self.loop = loop
        self.callbacks = {}
        self.descriptors = self.DescriptorDict(self.loop)
        self.log = logging.getLogger(self.__class__.__name__)

    def register(self):
        # pylint: disable=bad-whitespace
        libvirt.virEventRegisterImpl(
            self.add_handle,  self.update_handle,  self.remove_handle,
            self.add_timeout, self.update_timeout, self.remove_timeout)

    def add_handle(self, fd, event, cb, opaque):
        self.log.debug('add_handle(fd=%d, event=%d, cb=%r, opaque=%r)',
                fd, event, cb, opaque)
        callback = self.FDCallback(self, cb, opaque,
                descriptor=self.descriptors[fd], event=event)
        return callback.iden

    def update_handle(self, watch, event):
        self.log.debug('update_handle(watch=%d, event=%d)', watch, event)
        self.callbacks[watch].event = event

    def remove_handle(self, watch):
        self.log.debug('remove_handle(watch=%d)', watch)
        callback = self.callbacks.pop(watch)
        callback.close()

        # libvirt-python.git/libvirt-override.c suggests that the opaque value
        # should be returned. This is horribly wrong, because this would cause
        # instant execution of ff callback, which is prohibited by libvirt's
        # C API documentation. We therefore intentionally return None.
        return None

    def add_timeout(self, timeout, cb, opaque):
        self.log.debug('add_timeout(timeout=%d, cb=%r, opaque=%r)',
                timeout, cb, opaque)
        if timeout <= 0:
            # TODO we could think about registering timeouts of -1 as a special
            # case and emulate 0 somehow (60 Hz?)
            self.log.warning('will not add timer with timeout %r', timeout)
            return -1

        callback = self.TimeoutCallback(self, cb, opaque, timeout=timeout)
        callback.start()
        return callback.iden

    def update_timeout(self, timer, timeout):
        self.log.debug('update_timeout(timer=%d, timeout=%d)', timer, timeout)
        callback = self.callbacks[timer]
        callback.timeout = timeout
        if timeout > 0:
            callback.start()
        else:
            callback.stop()

    def remove_timeout(self, timer):
        self.log.debug('remove_timeout(timer=%d)', timer)
        callback = self.callbacks.pop(timer)
        callback.close()

        # See remove_handle()
        return None
