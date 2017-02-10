#!/usr/bin/env python3.6

import asyncio
import functools
import io
import os
import signal

import qubes
import qubes.libvirtaio
import qubes.mgmt
import qubes.utils
import qubes.vm.qubesvm

QUBESD_SOCK = '/var/run/qubesd.sock'


class QubesDaemonProtocol(asyncio.Protocol):
    buffer_size = 65536

    def __init__(self, *args, app, **kwargs):
        super().__init__(*args, **kwargs)
        self.app = app
        self.untrusted_buffer = io.BytesIO()
        self.len_untrusted_buffer = 0
        self.transport = None

    def connection_made(self, transport):
        print('connection_made()')
        self.transport = transport

    def connection_lost(self, exc):
        print('connection_lost(exc={!r})'.format(exc))
        self.untrusted_buffer.close()

    def data_received(self, untrusted_data):
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

        try:
            mgmt = qubes.mgmt.QubesMgmt(self.app, src, method, dest, arg)
            response = mgmt.execute(untrusted_payload=untrusted_payload)

        # except clauses will fall through to transport.abort() below

        except qubes.mgmt.PermissionDenied:
            self.app.log.warning(
                'permission denied for call %s+%s (%s → %s) '
                'with payload of %d bytes',
                    method, arg, src, dest, len(untrusted_payload))

        except qubes.mgmt.ProtocolError:
            self.app.log.warning(
                'protocol error for call %s+%s (%s → %s) '
                'with payload of %d bytes',
                    method, arg, src, dest, len(untrusted_payload))

        except Exception:  # pylint: disable=broad-except
            self.app.log.exception(
                'unhandled exception while calling '
                'src=%r method=%r dest=%r arg=%r len(untrusted_payload)=%d',
                    src, method, dest, arg, len(untrusted_payload))

        else:
            self.transport.write(response.encode('ascii'))
            try:
                self.transport.write_eof()
            except NotImplementedError:
                pass
            self.transport.close()
            return

        # this is reached if from except: blocks; do not put it in finally:,
        # because this will prevent the good case from sending the reply
        self.transport.abort()


def sighandler(loop, signame, server):
    print('caught {}, exiting'.format(signame))
    server.close()
    loop.stop()

parser = qubes.tools.QubesArgumentParser(description='Qubes OS daemon')

def main(args=None):
    args = parser.parse_args(args)
    loop = asyncio.get_event_loop()

    qubes.libvirtaio.LibvirtAsyncIOEventImpl(loop).register()

    try:
        os.unlink(QUBESD_SOCK)
    except FileNotFoundError:
        pass
    old_umask = os.umask(0o007)
    server = loop.run_until_complete(loop.create_unix_server(
        functools.partial(QubesDaemonProtocol, app=args.app), QUBESD_SOCK))
    os.umask(old_umask)
    del old_umask

    for signame in ('SIGINT', 'SIGTERM'):
        loop.add_signal_handler(getattr(signal, signame),
            sighandler, loop, signame, server)

    qubes.utils.systemd_notify()

    try:
        loop.run_forever()
        loop.run_until_complete(server.wait_closed())
    finally:
        loop.close()

if __name__ == '__main__':
    main()
