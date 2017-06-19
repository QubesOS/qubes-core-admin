# -*- encoding: utf8 -*-
#
# The Qubes OS Project, http://www.qubes-os.org
#
# Copyright (C) 2017  Wojtek Porczyk <woju@invisiblethingslab.com>
# Copyright (C) 2017  Marek Marczykowski-Górecki
#                               <marmarek@invisiblethingslab.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, see <http://www.gnu.org/licenses/>.

import asyncio
import errno
import functools
import io
import os
import shutil
import socket
import struct
import traceback

import qubes.exc

class ProtocolError(AssertionError):
    '''Raised when something is wrong with data received'''
    pass


class PermissionDenied(Exception):
    '''Raised deliberately by handlers when we decide not to cooperate'''
    pass


def method(name, *, no_payload=False, endpoints=None, **classifiers):
    '''Decorator factory for methods intended to appear in API.

    The decorated method can be called from public API using a child of
    :py:class:`AbstractQubesMgmt` class. The method becomes "public", and can be
    called using remote management interface.

    :param str name: qrexec rpc method name
    :param bool no_payload: if :py:obj:`True`, will barf on non-empty payload; \
        also will not pass payload at all to the method

    The expected function method should have one argument (other than usual
    *self*), ``untrusted_payload``, which will contain the payload.

    .. warning::
        This argument has to be named such, to remind the programmer that the
        content of this variable is indeed untrusted.

    If *no_payload* is true, then the method is called with no arguments.
    '''

    def decorator(func):
        if no_payload:
            # the following assignment is needed for how closures work in Python
            _func = func
            @functools.wraps(_func)
            def wrapper(self, untrusted_payload, **kwargs):
                if untrusted_payload != b'':
                    raise ProtocolError('unexpected payload')
                return _func(self, **kwargs)
            func = wrapper

        # pylint: disable=protected-access
        if endpoints is None:
            func.rpcnames = ((name, None),)
        else:
            func.rpcnames = tuple(
                (name.format(endpoint=endpoint), endpoint)
                for endpoint in endpoints)

        func.classifiers = classifiers

        return func

    return decorator


def apply_filters(iterable, filters):
    '''Apply filters returned by mgmt-permission:... event'''
    for selector in filters:
        iterable = filter(selector, iterable)
    return iterable


class AbstractQubesAPI(object):
    '''Common code for Qubes Management Protocol handling

    Different interfaces can expose different API call sets, however they share
    common protocol and common implementation framework. This class is the
    latter.

    To implement a new interface, inherit from this class and write at least one
    method and decorate it with :py:func:`api` decorator. It will have access to
    pre-defined attributes: :py:attr:`app`, :py:attr:`src`, :py:attr:`dest`,
    :py:attr:`arg` and :py:attr:`method`.

    There are also two helper functions for firing events associated with API
    calls.
    '''

    #: the preferred socket location (to be overridden in child's class)
    SOCKNAME = None

    def __init__(self, app, src, method_name, dest, arg, send_event=None):
        #: :py:class:`qubes.Qubes` object
        self.app = app

        #: source qube
        self.src = self.app.domains[src.decode('ascii')]

        #: destination qube
        self.dest = self.app.domains[dest.decode('ascii')]

        #: argument
        self.arg = arg.decode('ascii')

        #: name of the method
        self.method = method_name.decode('ascii')

        #: callback for sending events if applicable
        self.send_event = send_event

        #: is this operation cancellable?
        self.cancellable = False

        candidates = list(self.list_methods(self.method))

        if not candidates:
            raise ProtocolError('no such method: {!r}'.format(self.method))

        assert len(candidates) == 1, \
            'multiple candidates for method {!r}'.format(self.method)

        #: the method to execute
        self._handler = candidates[0]
        self._running_handler = None

    @classmethod
    def list_methods(cls, select_method=None):
        for attr in dir(cls):
            func = getattr(cls, attr)
            if not callable(func):
                continue

            try:
                # pylint: disable=protected-access
                rpcnames = func.rpcnames
            except AttributeError:
                continue

            for mname, endpoint in rpcnames:
                if select_method is None or mname == select_method:
                    yield (func, mname, endpoint)

    def execute(self, *, untrusted_payload):
        '''Execute management operation.

        This method is a coroutine.
        '''
        handler, _, endpoint = self._handler
        kwargs = {}
        if endpoint is not None:
            kwargs['endpoint'] = endpoint
        self._running_handler = asyncio.ensure_future(handler(self,
            untrusted_payload=untrusted_payload, **kwargs))
        return self._running_handler

    def cancel(self):
        '''If operation is cancellable, interrupt it'''
        if self.cancellable and self._running_handler is not None:
            self._running_handler.cancel()


    def fire_event_for_permission(self, **kwargs):
        '''Fire an event on the source qube to check for permission'''
        return self.src.fire_event_pre('mgmt-permission:' + self.method,
            dest=self.dest, arg=self.arg, **kwargs)

    def fire_event_for_filter(self, iterable, **kwargs):
        '''Fire an event on the source qube to filter for permission'''
        return apply_filters(iterable,
            self.fire_event_for_permission(**kwargs))


class QubesDaemonProtocol(asyncio.Protocol):
    buffer_size = 65536
    header = struct.Struct('Bx')

    def __init__(self, handler, *args, app, debug=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.handler = handler
        self.app = app
        self.untrusted_buffer = io.BytesIO()
        self.len_untrusted_buffer = 0
        self.transport = None
        self.debug = debug
        self.event_sent = False
        self.mgmt = None

    def connection_made(self, transport):
        self.transport = transport

    def connection_lost(self, exc):
        self.untrusted_buffer.close()
        # for cancellable operation, interrupt it, otherwise it will do nothing
        if self.mgmt is not None:
            self.mgmt.cancel()
        self.transport = None

    def data_received(self, untrusted_data):  # pylint: disable=arguments-differ
        if self.len_untrusted_buffer + len(untrusted_data) > self.buffer_size:
            self.app.log.warning('request too long')
            self.transport.abort()
            self.untrusted_buffer.close()
            return

        self.len_untrusted_buffer += \
            self.untrusted_buffer.write(untrusted_data)

    def eof_received(self):
        try:
            src, meth, dest, arg, untrusted_payload = \
                self.untrusted_buffer.getvalue().split(b'\0', 4)
        except ValueError:
            self.app.log.warning('framing error')
            self.transport.abort()
            return
        finally:
            self.untrusted_buffer.close()

        asyncio.ensure_future(self.respond(
            src, meth, dest, arg, untrusted_payload=untrusted_payload))

        return True

    @asyncio.coroutine
    def respond(self, src, meth, dest, arg, *, untrusted_payload):
        try:
            self.mgmt = self.handler(self.app, src, meth, dest, arg,
                self.send_event)
            response = yield from self.mgmt.execute(
                untrusted_payload=untrusted_payload)
            assert not (self.event_sent and response)
            if self.transport is None:
                return

        # except clauses will fall through to transport.abort() below

        except PermissionDenied:
            self.app.log.warning(
                'permission denied for call %s+%s (%s → %s) '
                'with payload of %d bytes',
                    meth, arg, src, dest, len(untrusted_payload))

        except ProtocolError:
            self.app.log.warning(
                'protocol error for call %s+%s (%s → %s) '
                'with payload of %d bytes',
                    meth, arg, src, dest, len(untrusted_payload))

        except qubes.exc.QubesException as err:
            msg = ('%r while calling '
                'src=%r meth=%r dest=%r arg=%r len(untrusted_payload)=%d')

            if self.debug:
                self.app.log.exception(msg,
                    err, src, meth, dest, arg, len(untrusted_payload))
            else:
                self.app.log.info(msg,
                    err, src, meth, dest, arg, len(untrusted_payload))
            if self.transport is not None:
                self.send_exception(err)
                self.transport.write_eof()
                self.transport.close()
            return

        except Exception:  # pylint: disable=broad-except
            self.app.log.exception(
                'unhandled exception while calling '
                'src=%r meth=%r dest=%r arg=%r len(untrusted_payload)=%d',
                    src, meth, dest, arg, len(untrusted_payload))

        else:
            if not self.event_sent:
                self.send_response(response)
            try:
                self.transport.write_eof()
            except NotImplementedError:
                pass
            self.transport.close()
            return

        # this is reached if from except: blocks; do not put it in finally:,
        # because this will prevent the good case from sending the reply
        self.transport.abort()

    def send_header(self, *args):
        self.transport.write(self.header.pack(*args))

    def send_response(self, content):
        assert not self.event_sent
        self.send_header(0x30)
        if content is not None:
            self.transport.write(content.encode('utf-8'))

    def send_event(self, subject, event, **kwargs):
        self.event_sent = True
        self.send_header(0x31)

        if subject is not self.app:
            self.transport.write(subject.name.encode('ascii'))
        self.transport.write(b'\0')

        self.transport.write(event.encode('ascii') + b'\0')

        for k, v in kwargs.items():
            self.transport.write('{}\0{}\0'.format(k, str(v)).encode('ascii'))
        self.transport.write(b'\0')

    def send_exception(self, exc):
        self.send_header(0x32)

        self.transport.write(type(exc).__name__.encode() + b'\0')

        if self.debug:
            self.transport.write(''.join(traceback.format_exception(
                type(exc), exc, exc.__traceback__)).encode('utf-8'))
        self.transport.write(b'\0')

        self.transport.write(str(exc).encode('utf-8') + b'\0')


@asyncio.coroutine
def create_servers(*args, force=False, loop=None, **kwargs):
    '''Create multiple Qubes API servers

    :param qubes.Qubes app: the app that is a backend of the servers
    :param bool force: if :py:obj:`True`, unconditionaly remove existing \
        sockets; if :py:obj:`False`, raise an error if there is some process \
        listening to such socket
    :param asyncio.Loop loop: loop

    *args* are supposed to be classess inheriting from
    :py:class:`AbstractQubesAPI`

    *kwargs* (like *app* or *debug* for example) are passed to
    :py:class:`QubesDaemonProtocol` constructor
    '''
    loop = loop or asyncio.get_event_loop()

    servers = []
    old_umask = os.umask(0o007)
    try:
        # XXX this can be optimised with asyncio.wait() to start servers in
        # parallel, but I currently don't see the need
        for handler in args:
            sockpath = handler.SOCKNAME
            assert sockpath is not None, \
                'SOCKNAME needs to be overloaded in {}'.format(
                    type(handler).__name__)

            if os.path.exists(sockpath):
                if force:
                    os.unlink(sockpath)
                else:
                    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                    try:
                        sock.connect(sockpath)
                    except ConnectionRefusedError:
                        # dead socket, remove it anyway
                        os.unlink(sockpath)
                    else:
                        # woops, someone is listening
                        sock.close()
                        raise FileExistsError(errno.EEXIST,
                            'socket already exists: {!r}'.format(sockpath))

            server = yield from loop.create_unix_server(
                functools.partial(QubesDaemonProtocol, handler, **kwargs),
                sockpath)

            for sock in server.sockets:
                shutil.chown(sock.getsockname(), group='qubes')

            servers.append(server)

    finally:
        os.umask(old_umask)

    return servers
