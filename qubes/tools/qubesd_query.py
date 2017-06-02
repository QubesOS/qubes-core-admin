#!/usr/bin/env python3.6

import argparse
import asyncio
import signal
import sys

QUBESD_SOCK = '/var/run/qubesd.sock'

try:
    asyncio.ensure_future
except AttributeError:
    asyncio.ensure_future = asyncio.async

parser = argparse.ArgumentParser(
    description='low-level qubesd interrogation tool')

parser.add_argument('--connect', '-c', metavar='PATH',
    dest='socket',
    default=QUBESD_SOCK,
    help='path to qubesd UNIX socket (default: %(default)s)')

parser.add_argument('--empty', '-e',
    dest='payload',
    action='store_false', default=True,
    help='do not read from stdin and send empty payload')

parser.add_argument('--fail',
    dest='fail',
    action='store_true',
    help='Should non-OK qubesd response result in non-zero exit code')

parser.add_argument('src', metavar='SRC',
    help='source qube')
parser.add_argument('method', metavar='METHOD',
    help='method name')
parser.add_argument('dest', metavar='DEST',
    help='destination qube')
parser.add_argument('arg', metavar='ARGUMENT',
    nargs='?', default='',
    help='argument to method')

def sighandler(loop, signame, coro):
    print('caught {}, exiting'.format(signame))
    coro.cancel()
    loop.stop()

@asyncio.coroutine
def qubesd_client(socket, payload, *args):
    '''
    Connect to qubesd, send request and passthrough response to stdout

    :param socket: path to qubesd socket
    :param payload: payload of the request
    :param args: request to qubesd
    :return:
    '''
    try:
        reader, writer = yield from asyncio.open_unix_connection(socket)
    except asyncio.CancelledError:
        return 1

    for arg in args:
        writer.write(arg.encode('ascii'))
        writer.write(b'\0')
    writer.write(payload)
    writer.write_eof()

    try:
        header_data = yield from reader.read(1)
        returncode = int(header_data)
        sys.stdout.buffer.write(header_data)  # pylint: disable=no-member
        while not reader.at_eof():
            data = yield from reader.read(4096)
            sys.stdout.buffer.write(data)  # pylint: disable=no-member
            sys.stdout.flush()
        return returncode
    except asyncio.CancelledError:
        return 1
    finally:
        writer.close()

def main(args=None):
    args = parser.parse_args(args)
    loop = asyncio.get_event_loop()

    # pylint: disable=no-member
    payload = sys.stdin.buffer.read() if args.payload else b''
    # pylint: enable=no-member

    coro = asyncio.ensure_future(qubesd_client(args.socket, payload,
        args.src, args.method, args.dest, args.arg))

    for signame in ('SIGINT', 'SIGTERM'):
        loop.add_signal_handler(getattr(signal, signame),
            sighandler, loop, signame, coro)

    try:
        returncode = loop.run_until_complete(coro)
    finally:
        loop.close()

    if args.fail:
        return returncode
    return 0

if __name__ == '__main__':
    sys.exit(main())
