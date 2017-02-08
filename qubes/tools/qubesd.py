#!/usr/bin/env python3.6

import asyncio
import functools
import io
import os
import reprlib
import signal
import types

import qubes
import qubes.libvirtaio
import qubes.utils
import qubes.vm.qubesvm

QUBESD_SOCK = '/var/run/qubesd.sock'


class ProtocolRepr(reprlib.Repr):
    def repr1(self, x, level):
        if isinstance(x, qubes.vm.qubesvm.QubesVM):
            x = x.name
        return super().repr1(x, level)

    # pylint: disable=invalid-name

    def repr_str(self, x, level):
        '''Warning: this is incompatible with python 3 wrt to b'' '''
        return "'{}'".format(''.join(
                chr(c)
                if 0x20 < c < 0x7f and c not in (ord("'"), ord('\\'))
                else '\\x{:02x}'.format(c)
            for c in x.encode()))

    def repr_Label(self, x, level):
        return self.repr1(x.name, level)


class ProtocolError(AssertionError):
    '''Raised when something is wrong with data received'''
    pass

class PermissionDenied(Exception):
    '''Raised deliberately by handlers when we decide not to cooperate'''
    pass


def not_in_api(func):
    func.not_in_api = True
    return func

class QubesMgmt(object):
    def __init__(self, app, src, method, dest, arg):
        self.app = app

        self.src = self.app.domains[src.decode('ascii')]
        self.dest = self.app.domains[dest.decode('ascii')]
        self.arg = arg.decode('ascii')

        self.prepr = ProtocolRepr()

        self.method = method.decode('ascii')

        untrusted_func_name = self.method
        if untrusted_func_name.startswith('mgmt.'):
            untrusted_func_name = untrusted_func_name[5:]
        untrusted_func_name = untrusted_func_name.lower().replace('.', '_')

        if untrusted_func_name.startswith('_') \
                or not '_' in untrusted_func_name:
            raise ProtocolError(
                'possibly malicious function name: {!r}'.format(
                    untrusted_func_name))

        try:
            untrusted_func = getattr(self, untrusted_func_name)
        except AttributeError:
            raise ProtocolError(
                'no such attribute: {!r}'.format(
                    untrusted_func_name))

        if not isinstance(untrusted_func, types.MethodType):
            raise ProtocolError(
                'no such method: {!r}'.format(
                    untrusted_func_name))

        if getattr(untrusted_func, 'not_in_api', False):
            raise ProtocolError(
                'attempt to call private method: {!r}'.format(
                    untrusted_func_name))

        self.execute = untrusted_func
        del untrusted_func_name
        del untrusted_func

    #
    # PRIVATE METHODS, not to be called via RPC
    #

    @not_in_api
    def fire_event_for_permission(self, *args, **kwargs):
        return self.src.fire_event_pre('mgmt-permission:{}'.format(self.method),
            self.dest, self.arg, *args, **kwargs)

    @not_in_api
    def repr(self, *args, **kwargs):
        return self.prepr.repr(*args, **kwargs)

    #
    # ACTUAL RPC CALLS
    #

    def vm_list(self, untrusted_payload):
        assert self.dest.name == 'dom0'
        assert not self.arg
        assert not untrusted_payload
        del untrusted_payload

        domains = self.app.domains
        for selector in self.fire_event_for_permission():
            domains = filter(selector, domains)

        return ''.join('{} class={} state={}\n'.format(
                self.repr(vm),
                vm.__class__.__name__,
                vm.get_power_state())
            for vm in sorted(domains))

    def vm_property_get(self, untrusted_payload):
        assert self.arg in self.dest.property_list()
        assert not untrusted_payload
        del untrusted_payload

        self.fire_event_for_permission()

        try:
            value = getattr(self.dest, self.arg)
        except AttributeError:
            return 'default=True '
        else:
            return 'default={} {}'.format(
                str(self.dest.property_is_default(self.arg)),
                self.repr(value))


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
            print('  request too long')
            self.transport.close()
            return

        self.len_untrusted_buffer += \
            self.untrusted_buffer.write(untrusted_data)

    def eof_received(self):
        print('eof_received()')
        try:
            src, method, dest, arg, untrusted_payload = \
                self.untrusted_buffer.getvalue().split(b'\0', 4)
        except ValueError:
            # TODO logging
            return

        try:
            mgmt = QubesMgmt(self.app, src, method, dest, arg)
            response = mgmt.execute(untrusted_payload=untrusted_payload)
        except PermissionDenied as err:
            # TODO logging
            return
        except ProtocolError as err:
            # TODO logging
            print(repr(err))
            return
        except AssertionError:
            # TODO logging
            print(repr(err))
            return

        self.transport.write(response.encode('ascii'))
        try:
            self.transport.write_eof()
        except NotImplementedError:
            pass


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
