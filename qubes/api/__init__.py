# -*- encoding: utf8 -*-
#
# The Qubes OS Project, http://www.qubes-os.org
#
# Copyright (C) 2017  Wojtek Porczyk <woju@invisiblethingslab.com>
# Copyright (C) 2017  Marek Marczykowski-Górecki
#                               <marmarek@invisiblethingslab.com>
#
# This library is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 2.1 of the License, or (at your option) any later version.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with this library; if not, see <https://www.gnu.org/licenses/>.

import asyncio
import errno
import functools
import io
import os
import re
import shutil
import socket
import struct
import traceback
from typing import Union, Any
import uuid

import qubes.exc
from qubes.exc import ProtocolError, PermissionDenied


def method(name, *, no_payload=False, endpoints=None, **classifiers):
    """Decorator factory for methods intended to appear in API.

    The decorated method can be called from public API using a child of
    :py:class:`AbstractQubesMgmt` class. The method becomes "public", and can be
    called using remote management interface.

    :param str name: qrexec rpc method name
    :param bool no_payload: if :py:obj:`True`, will barf on non-empty payload; \
        also will not pass payload at all to the method
    :param iterable endpoints: if specified, method serve multiple API calls
        generated by replacing `{endpoint}` with each value in this iterable

    The expected function method should have one argument (other than usual
    *self*), ``untrusted_payload``, which will contain the payload.

    .. warning::
        This argument has to be named such, to remind the programmer that the
        content of this variable is indeed untrusted.

    If *no_payload* is true, then the method is called with no arguments.
    """

    def decorator(func):
        if no_payload:
            # the following assignment is needed for how closures work in Python
            _func = func

            @functools.wraps(_func)
            def wrapper(self, untrusted_payload, **kwargs):
                if untrusted_payload != b"":
                    raise ProtocolError("unexpected payload")
                return _func(self, **kwargs)

            func = wrapper

        # pylint: disable=protected-access
        if endpoints is None:
            func.rpcnames = ((name, None),)
        else:
            func.rpcnames = tuple(
                (name.format(endpoint=endpoint), endpoint)
                for endpoint in endpoints
            )

        func.classifiers = classifiers

        return func

    return decorator


def apply_filters(iterable, filters):
    """Apply filters returned by admin-permission:... event"""
    for selector in filters:
        iterable = filter(selector, iterable)
    return iterable


# This regex allows incorrect-length UUIDs,
# but there is an explicit length check to catch that.
_uuid_regex = re.compile(rb"\Auuid:[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]*")


def decode_vm(
    untrusted_input: bytes, domains: qubes.app.VMCollection
) -> qubes.vm.qubesvm.QubesVM:
    lookup: Union[uuid.UUID, str]
    vm = untrusted_input.decode("ascii", "strict")
    if untrusted_input.startswith(b"uuid:"):
        if len(untrusted_input) != 41 or not _uuid_regex.match(untrusted_input):
            raise qubes.exc.QubesVMInvalidUUIDError(vm[5:])
        lookup = uuid.UUID(vm[5:])
    else:
        # throws if name is invalid
        qubes.vm.validate_name(None, None, vm)
        lookup = vm
    try:
        return domains[lookup]
    except KeyError:
        # normally this should filtered out by qrexec policy, but there are
        # two cases it might not be:
        # 1. The call comes from dom0, which bypasses qrexec policy
        # 2. Domain was removed between checking the policy and here
        # we inform the client accordingly
        raise qubes.exc.QubesVMNotFoundError(vm)


class AbstractQubesAPI:
    """Common code for Qubes Management Protocol handling

    Different interfaces can expose different API call sets, however they share
    common protocol and common implementation framework. This class is the
    latter.

    To implement a new interface, inherit from this class and write at least one
    method and decorate it with :py:func:`api` decorator. It will have access to
    pre-defined attributes: :py:attr:`app`, :py:attr:`src`, :py:attr:`dest`,
    :py:attr:`arg` and :py:attr:`method`.

    There are also two helper functions for firing events associated with API
    calls.
    """

    #: the preferred socket location (to be overridden in child's class)
    SOCKNAME = ""

    app: qubes.Qubes
    src: qubes.vm.qubesvm.QubesVM

    def __init__(
        self,
        app: qubes.Qubes,
        src: bytes,
        method_name: bytes,
        dest: bytes,
        arg: bytes,
        send_event: Any = None,
    ) -> None:
        #: :py:class:`qubes.Qubes` object
        self.app = app

        #: source qube
        self.src = decode_vm(src, app.domains)

        #: destination qube
        self.dest = decode_vm(dest, app.domains)

        #: argument
        self.arg = arg.decode("ascii")

        #: name of the method
        self.method = method_name.decode("ascii")

        #: callback for sending events if applicable
        self.send_event = send_event

        #: is this operation cancellable?
        self.cancellable = False

        candidates = list(self.list_methods(self.method))

        if not candidates:
            raise ProtocolError("no such method: {!r}".format(self.method))

        assert (
            len(candidates) == 1
        ), "multiple candidates for method {!r}".format(self.method)

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
        """Execute management operation.

        This method is a coroutine.
        """
        handler, _, endpoint = self._handler
        kwargs = {}
        if endpoint is not None:
            kwargs["endpoint"] = endpoint
        self._running_handler = asyncio.ensure_future(
            handler(self, untrusted_payload=untrusted_payload, **kwargs)
        )
        return self._running_handler

    def cancel(self):
        """If operation is cancellable, interrupt it"""
        if self.cancellable and self._running_handler is not None:
            self._running_handler.cancel()

    def fire_event_for_permission(self, **kwargs):
        """Fire an event on the source qube to check for permission"""
        return self.src.fire_event(
            "admin-permission:" + self.method,
            pre_event=True,
            dest=self.dest,
            arg=self.arg,
            **kwargs
        )

    def fire_event_for_filter(self, iterable, **kwargs):
        """Fire an event on the source qube to filter for permission"""
        return apply_filters(iterable, self.fire_event_for_permission(**kwargs))

    @staticmethod
    def enforce(predicate):
        """An assert replacement, but works even with optimisations."""
        if not predicate:
            raise PermissionDenied()

    def validate_size(
        self, untrusted_size: bytes, allow_negative: bool = False
    ) -> int:
        self.enforce(isinstance(untrusted_size, bytes))
        coefficient = 1
        if allow_negative and untrusted_size.startswith(b"-"):
            coefficient = -1
            untrusted_size = untrusted_size[1:]
        if not untrusted_size.isdigit():
            raise qubes.exc.ProtocolError("Size must be ASCII digits (only)")
        if len(untrusted_size) >= 20:
            raise qubes.exc.ProtocolError("Sizes limited to 19 decimal digits")
        if untrusted_size[0] == 48 and untrusted_size != b"0":
            raise qubes.exc.ProtocolError("Spurious leading zeros not allowed")
        return int(untrusted_size) * coefficient


class QubesDaemonProtocol(asyncio.Protocol):
    buffer_size = 65536
    header = struct.Struct("Bx")

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

    # pylint: disable=arguments-differ,arguments-renamed
    def data_received(self, untrusted_data):
        if self.len_untrusted_buffer + len(untrusted_data) > self.buffer_size:
            self.app.log.warning("request too long")
            self.transport.abort()
            self.untrusted_buffer.close()
            return

        self.len_untrusted_buffer += self.untrusted_buffer.write(untrusted_data)

    # pylint: enable=arguments-differ,arguments-renamed

    def eof_received(self):
        try:
            connection_params, untrusted_payload = (
                self.untrusted_buffer.getvalue().split(b"\0", 1)
            )
            meth_arg, src, dest_type, dest = connection_params.split(b" ", 3)
            if dest_type == b"keyword" and dest == b"adminvm":
                dest_type, dest = b"name", b"dom0"
            if dest_type != b"name":
                raise ValueError(
                    "got {} destination type, "
                    "while only explicit name supported".format(dest_type)
                )
            if b"+" in meth_arg:
                meth, arg = meth_arg.split(b"+", 1)
            else:
                meth, arg = meth_arg, b""
        except ValueError:
            self.app.log.warning("framing error")
            self.transport.abort()
            return None
        finally:
            self.untrusted_buffer.close()

        asyncio.ensure_future(
            self.respond(
                src, meth, dest, arg, untrusted_payload=untrusted_payload
            )
        )

        return True

    async def respond(self, src, meth, dest, arg, *, untrusted_payload):
        try:
            self.mgmt = self.handler(
                self.app, src, meth, dest, arg, self.send_event
            )
            response = await self.mgmt.execute(
                untrusted_payload=untrusted_payload
            )
            assert not (self.event_sent and response)
            if self.transport is None:
                return

        # except clauses will fall through to transport.abort() below

        except PermissionDenied:
            self.app.log.warning(
                "permission denied for call %s+%s (%s → %s) "
                "with payload of %d bytes",
                meth,
                arg,
                src,
                dest,
                len(untrusted_payload),
            )

        except ProtocolError:
            self.app.log.warning(
                "protocol error for call %s+%s (%s → %s) "
                "with payload of %d bytes",
                meth,
                arg,
                src,
                dest,
                len(untrusted_payload),
            )

        except qubes.exc.QubesException as err:
            msg = (
                "%r while calling "
                "src=%r meth=%r dest=%r arg=%r len(untrusted_payload)=%d"
            )

            if self.debug:
                self.app.log.debug(
                    msg,
                    err,
                    src,
                    meth,
                    dest,
                    arg,
                    len(untrusted_payload),
                    exc_info=1,
                )
            if self.transport is not None:
                self.send_exception(err)
                self.transport.write_eof()
                self.transport.close()
            return

        except Exception:  # pylint: disable=broad-except
            self.app.log.exception(
                "unhandled exception while calling "
                "src=%r meth=%r dest=%r arg=%r len(untrusted_payload)=%d",
                src,
                meth,
                dest,
                arg,
                len(untrusted_payload),
            )

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
        if self.transport:
            self.transport.abort()

    def send_header(self, *args):
        self.transport.write(self.header.pack(*args))

    def send_response(self, content):
        assert not self.event_sent
        self.send_header(0x30)
        if content is not None:
            self.transport.write(content.encode("utf-8"))

    def send_event(self, subject, event, **kwargs):
        if self.transport is None:
            return
        self.event_sent = True
        self.send_header(0x31)

        if subject is not self.app:
            self.transport.write(str(subject).encode("ascii"))
        self.transport.write(b"\0")

        self.transport.write(event.encode("ascii") + b"\0")

        for k, v in kwargs.items():
            self.transport.write("{}\0{}\0".format(k, str(v)).encode("ascii"))
        self.transport.write(b"\0")

    def send_exception(self, exc):
        self.send_header(0x32)

        self.transport.write(type(exc).__name__.encode() + b"\0")

        if self.debug:
            self.transport.write(
                "".join(
                    traceback.format_exception(
                        type(exc), exc, exc.__traceback__
                    )
                ).encode("utf-8")
            )
        self.transport.write(b"\0")

        self.transport.write(str(exc).encode("utf-8") + b"\0")


def cleanup_socket(sockpath, force):
    """Remove socket if stale, or force=True
    :param sockpath: path to a socket
    :param force: should remove even if still used
    """
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
            raise FileExistsError(
                errno.EEXIST, "socket already exists: {!r}".format(sockpath)
            )


async def create_servers(*args, force=False, loop=None, **kwargs):
    """Create multiple Qubes API servers

    :param qubes.Qubes app: the app that is a backend of the servers
    :param bool force: if :py:obj:`True`, unconditionally remove existing \
        sockets; if :py:obj:`False`, raise an error if there is some process \
        listening to such socket
    :param asyncio.Loop loop: loop

    *args* are supposed to be classes inheriting from
    :py:class:`AbstractQubesAPI`

    *kwargs* (like *app* or *debug* for example) are passed to
    :py:class:`QubesDaemonProtocol` constructor
    """
    loop = loop or asyncio.get_event_loop()

    servers = []
    old_umask = os.umask(0o007)
    try:
        # XXX this can be optimised with asyncio.wait() to start servers in
        # parallel, but I currently don't see the need
        for handler in args:
            sockpath = handler.SOCKNAME
            assert (
                sockpath is not None
            ), "SOCKNAME needs to be overloaded in {}".format(
                type(handler).__name__
            )

            if os.path.exists(sockpath):
                cleanup_socket(sockpath, force)

            server = await loop.create_unix_server(
                functools.partial(QubesDaemonProtocol, handler, **kwargs),
                sockpath,
            )

            for sock in server.sockets:
                shutil.chown(sock.getsockname(), group="qubes")

            servers.append(server)
    except:
        for server in servers:
            for sock in server.sockets:
                try:
                    os.unlink(sock.getsockname())
                except FileNotFoundError:
                    pass
            server.close()
        if servers:
            await asyncio.wait(
                [
                    asyncio.create_task(server.wait_closed())
                    for server in servers
                ]
            )
        raise
    finally:
        os.umask(old_umask)

    return servers
