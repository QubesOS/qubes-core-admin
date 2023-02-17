#!/usr/bin/env python3.6

import asyncio
import os
import signal

import libvirtaio

import qubes
import qubes.app
import qubes.api
import qubes.api.admin
import qubes.api.internal
import qubes.api.misc
import qubes.log
import qubes.utils
import qubes.vm.qubesvm

# Wait for the system entropy pool to fill, so we can use “/dev/urandom” with
# confidence.
os.getrandom(1)

def sighandler(loop, signame, servers):
    print('caught {}, exiting'.format(signame))
    for server in servers:
        server.close()
    loop.stop()

parser = qubes.tools.QubesArgumentParser(description='Qubes OS daemon')
parser.add_argument('--debug', action='store_true', default=False,
    help='Enable verbose error logging (all exceptions with full '
         'tracebacks) and also send tracebacks to Admin API clients')

def main(args=None):
    loop = asyncio.get_event_loop()
    libvirtaio.virEventRegisterAsyncIOImpl(loop=loop)
    try:
        args = parser.parse_args(args)
    except:
        loop.close()
        raise

    args.app.register_event_handlers()

    # Stop storage for domains not currently running
    loop.run_until_complete(args.app.stop_storage())

    if args.debug:
        qubes.log.enable_debug()

    servers = loop.run_until_complete(qubes.api.create_servers(
        qubes.api.admin.QubesAdminAPI,
        qubes.api.internal.QubesInternalAPI,
        qubes.api.misc.QubesMiscAPI,
        app=args.app, debug=args.debug))

    socknames = []
    for server in servers:
        for sock in server.sockets:
            socknames.append(sock.getsockname())

    for signame in ('SIGINT', 'SIGTERM'):
        loop.add_signal_handler(getattr(signal, signame),
            sighandler, loop, signame, servers)

    qubes.utils.systemd_notify()
    # make sure children will not inherit this
    os.environ.pop('NOTIFY_SOCKET', None)

    try:
        loop.run_forever()
        loop.run_until_complete(asyncio.wait([
            loop.create_task(server.wait_closed()) for server in servers]))
        for sockname in socknames:
            try:
                os.unlink(sockname)
            except FileNotFoundError:
                args.app.log.warning(
                    'socket {} got unlinked sometime before shutdown'.format(
                        sockname))
    finally:
        loop.close()

if __name__ == '__main__':
    main()
