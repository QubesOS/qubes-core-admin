#!/usr/bin/env python3

#
# Copyright 2017 Wojtek Porczyk <woju@invisiblethingslab.com>
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

'''libvirtaio -- libvirt event loop implementation using asyncio

Register the implementation of default loop:

    >>> import libvirtaio
    >>> impl = libvirtaio.LibvirtAsyncIOEventImpl()
    >>> impl.register()

Register the implementation on specific loop:

    >>> import asyncio
    >>> import libvirtaio
    >>> impl = libvirtaio.LibvirtAsyncIOEventImpl(loop=asyncio.get_event_loop())
    >>> impl.register()

This module also contains an execute_ff_callback function to be used from other
implementation, which parses the opaque object and executes the ff callback.

.. seealso::
    https://libvirt.org/html/libvirt-libvirt-event.html
'''

__version__ = '1.0'
__author__ = 'Wojtek Porczyk'
__all__ = ['LibvirtAsyncIOEventImpl', 'execute_ff_callback']

import asyncio
import ctypes
import itertools
import logging
import warnings

import libvirt

try:
    asyncio.ensure_future
except AttributeError:
    # python < 3.4.4 (Debian < stretch, Fedora < 24)
    asyncio.ensure_future = asyncio.async

ctypes.pythonapi.PyCapsule_GetPointer.restype = ctypes.c_void_p
ctypes.pythonapi.PyCapsule_GetPointer.argtypes = (
        ctypes.py_object, ctypes.c_char_p)

virFreeCallback = ctypes.CFUNCTYPE(None, ctypes.c_void_p)

def execute_ff_callback(opaque):
    '''Execute callback which frees the opaque buffer

    .. warning::
        This function should not be called from any called by libvirt's core.
        It will most probably cause deadlock in C-level libvirt code. Instead it
        should be scheduled and called from our stack.

        See https://libvirt.org/html/libvirt-libvirt-event.html#virEventAddHandleFunc
        for more information.

    This function is not dependent on any event loop implementation and can be
    freely stolen. Also be vary that it introspects theoretically opaque objects
    and can break when upgrading libvirt.
    '''

    # Now this is cheating but we have no better option. The opaque object is
    # really a 3-tuple, which contains a the real opaque pointer and the ff
    # callback, both of which are inside PyCapsules. If not specified, the ff
    # may be None.
    dummy, caps_opaque, caps_ff = opaque
    ff = virFreeCallback(ctypes.pythonapi.PyCapsule_GetPointer(
        caps_ff, b'virFreeCallback'))
    if ff:
        real_opaque = ctypes.pythonapi.PyCapsule_GetPointer(
            caps_opaque, b'void*')
        ff(real_opaque)


class Callback(object):
    '''Base class for holding callback

    :param LibvirtAsyncIOEventImpl impl: the implementation in which we run
    :param cb: the callback itself
    :param opaque: the opaque tuple passed by libvirt
    '''
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

    def __repr__(self):
        return '<{} iden={}>'.format(self.__clas__.__name__, self.iden)

    def close(self):
        '''Schedule *ff* callback'''
        self.impl.log.debug('callback %d close(), scheduling ff', self.iden)
        self.impl.schedule_ff_callback(self.opaque)

#
# file descriptors
#

class Descriptor(object):
    '''Manager of one file descriptor

    :param LibvirtAsyncIOEventImpl impl: the implementation in which we run
    :param int fd: the file descriptor
    '''
    def __init__(self, impl, fd):
        self.impl = impl
        self.fd = fd
        self.callbacks = {}

    def _handle(self, event):
        '''Dispatch the event to the descriptors

        :param int event: The event (from libvirt's constants) being dispatched
        '''
        for callback in self.callbacks.values():
            if callback.event is not None and callback.event & event:
                callback.cb(callback.iden, self.fd, event, callback.opaque)

    def update(self):
        '''Register or unregister callbacks at event loop

        This should be called after change of any ``.event`` in callbacks.
        '''
        # It seems like loop.add_{reader,writer} can be run multiple times
        # and will still register the callback only once. Likewise,
        # remove_{reader,writer} may be run even if the reader/writer
        # is not registered (and will just return False).

        # For the edge case of empty callbacks, any() returns False.
        if any(callback.event & ~(
                    libvirt.VIR_EVENT_HANDLE_READABLE |
                    libvirt.VIR_EVENT_HANDLE_WRITABLE)
                for callback in self.callbacks.values()):
            warnings.warn(
                'The only event supported are VIR_EVENT_HANDLE_READABLE '
                'and VIR_EVENT_HANDLE_WRITABLE',
                UserWarning)

        if any(callback.event & libvirt.VIR_EVENT_HANDLE_READABLE
                for callback in self.callbacks.values()):
            self.impl.loop.add_reader(
                self.fd, self._handle, libvirt.VIR_EVENT_HANDLE_READABLE)
        else:
            self.impl.loop.remove_reader(self.fd)

        if any(callback.event & libvirt.VIR_EVENT_HANDLE_WRITABLE
                for callback in self.callbacks.values()):
            self.impl.loop.add_writer(
                self.fd, self._handle, libvirt.VIR_EVENT_HANDLE_WRITABLE)
        else:
            self.impl.loop.remove_writer(self.fd)

    def add_handle(self, callback):
        '''Add a callback to the descriptor

        :param FDCallback callback: the callback to add
        :rtype: None

        After adding the callback, it is immediately watched.
        '''
        self.callbacks[callback.iden] = callback
        self.update()

    def remove_handle(self, iden):
        '''Remove a callback from the descriptor

        :param int iden: the identifier of the callback
        :returns: the callback
        :rtype: FDCallback

        After removing the callback, the descriptor may be unwatched, if there
        are no more handles for it.
        '''
        callback = self.callbacks.pop(iden)
        self.update()
        return callback

    def close(self):
        ''''''
        self.callbacks.clear()
        self.update()

class DescriptorDict(dict):
    '''Descriptors collection

    This is used internally by LibvirtAsyncIOEventImpl to hold descriptors.
    '''
    def __init__(self, impl):
        super().__init__()
        self.impl = impl

    def __missing__(self, fd):
        descriptor = Descriptor(self.impl, fd)
        self[fd] = descriptor
        return descriptor

class FDCallback(Callback):
    '''Callback for file descriptor (watcher)

    :param Descriptor descriptor: the descriptor manager
    :param int event: bitset of events on which to fire the callback
    '''
    # pylint: disable=too-few-public-methods

    def __init__(self, *args, descriptor, event, **kwargs):
        super().__init__(*args, **kwargs)
        self.descriptor = descriptor
        self.event = event

    def __repr__(self):
        return '<{} iden={} fd={} event={}>'.format(
            self.__class__.__name__, self.iden, self.descriptor.fd, self.event)

    def update(self, *, event):
        '''Update the callback and fix descriptor's watchers'''
        self.event = event
        self.descriptor.update()

#
# timeouts
#

class TimeoutCallback(Callback):
    '''Callback for timer'''
    def __init__(self, *args, timeout, **kwargs):
        super().__init__(*args, **kwargs)
        self.timeout = timeout
        self._task = None

    def __repr__(self):
        return '<{} iden={} timeout={}>'.format(
            self.__class__.__name__, self.iden, self.timeout)

    @asyncio.coroutine
    def _timer(self):
        '''An actual timer running on the event loop.

        This is a coroutine.
        '''
        while True:
            assert self.timeout >= 0, \
                'invalid timeout {} for running timer'.format(self.timeout)

            try:
                if self.timeout > 0:
                    timeout = self.timeout * 1e-3
                    self.impl.log.debug('sleeping %r', timeout)
                    yield from asyncio.sleep(timeout)
                else:
                    # scheduling timeout for next loop iteration
                    yield

            except asyncio.CancelledError:
                self.impl.log.debug('timer %d cancelled', self.iden)
                break

            self.cb(self.iden, self.opaque)
            self.impl.log.debug('timer %r callback ended', self.iden)

    def update(self, *, timeout=None):
        '''Start or the timer, possibly updating timeout'''
        if timeout is not None:
            self.timeout = timeout

        if self.timeout >= 0 and self._task is None:
            self.impl.log.debug('timer %r start', self.iden)
            self._task = asyncio.ensure_future(self._timer(),
                loop=self.impl.loop)

        elif self.timeout < 0 and self._task is not None:
            self.impl.log.debug('timer %r stop', self.iden)
            self._task.cancel()  # pylint: disable=no-member
            self._task = None

    def close(self):
        '''Stop the timer and call ff callback'''
        self.timeout = -1
        self.update()
        super().close()

#
# main implementation
#

class LibvirtAsyncIOEventImpl(object):
    '''Libvirt event adapter to asyncio.

    :param loop: asyncio's event loop

    If *loop* is not specified, the current (or default) event loop is used.
    '''

    def __init__(self, *, loop=None):
        self.loop = loop or asyncio.get_event_loop()
        self.callbacks = {}
        self.descriptors = DescriptorDict(self)
        self.log = logging.getLogger(self.__class__.__name__)

    def register(self):
        '''Register this instance as event loop implementation'''
        # pylint: disable=bad-whitespace
        self.log.debug('register()')
        libvirt.virEventRegisterImpl(
            self.add_handle,  self.update_handle,  self.remove_handle,
            self.add_timeout, self.update_timeout, self.remove_timeout)

    def schedule_ff_callback(self, opaque):
        '''Schedule a ff callback from one of the handles or timers'''
        self.loop.call_soon(execute_ff_callback, opaque)

    def is_idle(self):
        '''Returns False if there are leftovers from a connection

        Those may happen if there are sematical problems while closing
        a connection. For example, not deregistered events before .close().
        '''
        return not self.callbacks

    def add_handle(self, fd, event, cb, opaque):
        '''Register a callback for monitoring file handle events

        :param int fd: file descriptor to listen on
        :param int event: bitset of events on which to fire the callback
        :param cb: the callback to be called when an event occurrs
        :param opaque: user data to pass to the callback
        :rtype: int
        :returns: handle watch number to be used for updating and \
            unregistering for events

        .. seealso::
            https://libvirt.org/html/libvirt-libvirt-event.html#virEventAddHandleFuncFunc
        '''
        self.log.debug('add_handle(fd=%d, event=%d, cb=%r, opaque=%r)',
                fd, event, cb, opaque)
        callback = FDCallback(self, cb, opaque,
                descriptor=self.descriptors[fd], event=event)
        self.callbacks[callback.iden] = callback
        self.descriptors[fd].add_handle(callback)
        return callback.iden

    def update_handle(self, watch, event):
        '''Change event set for a monitored file handle

        :param int watch: file descriptor watch to modify
        :param int event: new events to listen on

        .. seealso::
            https://libvirt.org/html/libvirt-libvirt-event.html#virEventUpdateHandleFunc
        '''
        self.log.debug('update_handle(watch=%d, event=%d)', watch, event)
        return self.callbacks[watch].update(event=event)

    def remove_handle(self, watch):
        '''Unregister a callback from a file handle.

        :param int watch: file descriptor watch to stop listening on
        :returns: None (see source for explanation)

        .. seealso::
            https://libvirt.org/html/libvirt-libvirt-event.html#virEventRemoveHandleFunc
        '''
        self.log.debug('remove_handle(watch=%d)', watch)
        callback = self.callbacks.pop(watch)
        assert callback is self.descriptors.remove_handle(watch)
        callback.close()

        # libvirt-python.git/libvirt-override.c suggests that the opaque value
        # should be returned. This is horribly wrong, because this would cause
        # instant execution of ff callback, which is prohibited by libvirt's
        # C API documentation. We therefore intentionally return None.
        return None

    def add_timeout(self, timeout, cb, opaque):
        '''Register a callback for a timer event

        :param int timeout: the timeout to monitor
        :param cb: the callback to call when timeout has expired
        :param opaque: user data to pass to the callback
        :rtype: int
        :returns: a timer value

        .. seealso::
            https://libvirt.org/html/libvirt-libvirt-event.html#virEventAddTimeoutFunc
        '''
        self.log.debug('add_timeout(timeout=%d, cb=%r, opaque=%r)',
                timeout, cb, opaque)
        callback = TimeoutCallback(self, cb, opaque, timeout=timeout)
        self.callbacks[callback.iden] = callback
        callback.update()
        return callback.iden

    def update_timeout(self, timer, timeout):
        '''Change frequency for a timer

        :param int timer: the timer to modify
        :param int timeout: the new timeout value in ms

        .. seealso::
            https://libvirt.org/html/libvirt-libvirt-event.html#virEventUpdateTimeoutFunc
        '''
        self.log.debug('update_timeout(timer=%d, timeout=%d)', timer, timeout)
        return self.callbacks[timer].update(timeout=timeout)

    def remove_timeout(self, timer):
        '''Unregister a callback for a timer

        :param int timer: the timer to remove
        :returns: None (see source for explanation)

        .. seealso::
            https://libvirt.org/html/libvirt-libvirt-event.html#virEventRemoveTimeoutFunc
        '''
        self.log.debug('remove_timeout(timer=%d)', timer)
        callback = self.callbacks.pop(timer)
        callback.close()

        # See remove_handle()
        return None
