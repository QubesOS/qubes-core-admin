#!/usr/bin/env python3.6

import asyncio
import functools
import io
import os
import shutil
import signal
import struct
import traceback

import libvirtaio

import qubes
import qubes.api
import qubes.api.admin
import qubes.api.internal
import qubes.utils
import qubes.vm.qubesvm

QUBESD_SOCK = '/var/run/qubesd.sock'
QUBESD_INTERNAL_SOCK = '/var/run/qubesd.internal.sock'

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
        print('connection_made()')
        self.transport = transport

    def connection_lost(self, exc):
        print('connection_lost(exc={!r})'.format(exc))
        self.untrusted_buffer.close()
        # for cancellable operation, interrupt it, otherwise it will do nothing
        if self.mgmt is not None:
            self.mgmt.cancel()
        self.transport = None

    def data_received(self, untrusted_data):  # pylint: disable=arguments-differ
        print('data_received(untrusted_data={!r})'.format(untrusted_data))
        if self.len_untrusted_buffer + len(untrusted_data) > self.buffer_size:
            self.app.log.warning('request too long')
            self.transport.abort()
            self.untrusted_buffer.close()
            return

        self.len_untrusted_buffer += \
            self.untrusted_buffer.write(untrusted_data)

    def eof_received(self):
        print('eof_received()')
        try:
            src, method, dest, arg, untrusted_payload = \
                self.untrusted_buffer.getvalue().split(b'\0', 4)
        except ValueError:
            self.app.log.warning('framing error')
            self.transport.abort()
            return
        finally:
            self.untrusted_buffer.close()

        asyncio.ensure_future(self.respond(
            src, method, dest, arg, untrusted_payload=untrusted_payload))

        return True

    @asyncio.coroutine
    def respond(self, src, method, dest, arg, *, untrusted_payload):
        try:
            self.mgmt = self.handler(self.app, src, method, dest, arg,
                self.send_event)
            response = yield from self.mgmt.execute(
                untrusted_payload=untrusted_payload)
            assert not (self.event_sent and response)
            if self.transport is None:
                return

        # except clauses will fall through to transport.abort() below

        except qubes.api.PermissionDenied:
            self.app.log.warning(
                'permission denied for call %s+%s (%s → %s) '
                'with payload of %d bytes',
                    method, arg, src, dest, len(untrusted_payload))

        except qubes.api.ProtocolError:
            self.app.log.warning(
                'protocol error for call %s+%s (%s → %s) '
                'with payload of %d bytes',
                    method, arg, src, dest, len(untrusted_payload))

        except qubes.exc.QubesException as err:
            self.app.log.exception(
                'error while calling '
                'src=%r method=%r dest=%r arg=%r len(untrusted_payload)=%d',
                src, method, dest, arg, len(untrusted_payload))
            if self.transport is not None:
                self.send_exception(err)
                self.transport.write_eof()
                self.transport.close()
            return

        except Exception:  # pylint: disable=broad-except
            self.app.log.exception(
                'unhandled exception while calling '
                'src=%r method=%r dest=%r arg=%r len(untrusted_payload)=%d',
                    src, method, dest, arg, len(untrusted_payload))

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


def sighandler(loop, signame, server, server_internal):
    print('caught {}, exiting'.format(signame))
    server.close()
    server_internal.close()
    loop.stop()

parser = qubes.tools.QubesArgumentParser(description='Qubes OS daemon')


def main(args=None):
    loop = asyncio.get_event_loop()
    libvirtaio.virEventRegisterAsyncIOImpl(loop=loop)
    try:
        args = parser.parse_args(args)
    except:
        loop.close()
        raise

    args.app.vmm.register_event_handlers(args.app)

    try:
        os.unlink(QUBESD_SOCK)
    except FileNotFoundError:
        pass
    old_umask = os.umask(0o007)
    server = loop.run_until_complete(loop.create_unix_server(
        functools.partial(QubesDaemonProtocol, qubes.api.admin.QubesAdminAPI,
            app=args.app), QUBESD_SOCK))
    shutil.chown(QUBESD_SOCK, group='qubes')

    try:
        os.unlink(QUBESD_INTERNAL_SOCK)
    except FileNotFoundError:
        pass
    server_internal = loop.run_until_complete(loop.create_unix_server(
        functools.partial(QubesDaemonProtocol,
            qubes.api.internal.QubesInternalAPI,
            app=args.app), QUBESD_INTERNAL_SOCK))
    shutil.chown(QUBESD_INTERNAL_SOCK, group='qubes')

    os.umask(old_umask)
    del old_umask

    for signame in ('SIGINT', 'SIGTERM'):
        loop.add_signal_handler(getattr(signal, signame),
            sighandler, loop, signame, server, server_internal)

    qubes.utils.systemd_notify()
    # make sure children will not inherit this
    os.environ.pop('NOTIFY_SOCKET', None)

    try:
        loop.run_forever()
        loop.run_until_complete(asyncio.wait([
            server.wait_closed(),
            server_internal.wait_closed(),
        ]))
    finally:
        loop.close()

if __name__ == '__main__':
    main()
