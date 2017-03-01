#
# The Qubes OS Project, https://www.qubes-os.org/
#
# Copyright (C) 2017  Wojtek Porczyk <woju@invisiblethingslab.com>
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
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
#

'''
Qubes OS Management API
'''

import asyncio
import reprlib

import qubes.vm.qubesvm


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

        if not asyncio.iscoroutinefunction(untrusted_func):
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
    def fire_event_for_permission(self, **kwargs):
        return self.src.fire_event_pre('mgmt-permission:{}'.format(self.method),
            self.dest, self.arg, **kwargs)

    @not_in_api
    def fire_event_for_filter(self, iterable, **kwargs):
        for selector in self.fire_event_for_permission(**kwargs):
            iterable = filter(selector, iterable)
        return iterable

    @not_in_api
    def repr(self, *args, **kwargs):
        return self.prepr.repr(*args, **kwargs)

    #
    # ACTUAL RPC CALLS
    #

    @asyncio.coroutine
    def vm_list(self, untrusted_payload):
        assert self.dest.name == 'dom0'
        assert not self.arg
        assert not untrusted_payload
        del untrusted_payload

        domains = self.fire_event_for_filter(self.app.domains)

        return ''.join('{} class={} state={}\n'.format(
                self.repr(vm),
                vm.__class__.__name__,
                vm.get_power_state())
            for vm in sorted(domains))

    @asyncio.coroutine
    def vm_property_list(self, untrusted_payload):
        assert not self.arg
        assert not untrusted_payload
        del untrusted_payload

        properties = self.fire_event_for_filter(self.dest.property_list())

        return ''.join('{}\n'.format(prop.__name__) for prop in properties)

    @asyncio.coroutine
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

    @asyncio.coroutine
    def vm_property_help(self, untrusted_payload):
        assert self.arg in self.dest.property_list()
        assert not untrusted_payload
        del untrusted_payload

        self.fire_event_for_permission()

        try:
            doc = self.dest.property_get_def(self.arg).__doc__
        except AttributeError:
            return ''

        return qubes.utils.format_doc(doc)

    @asyncio.coroutine
    def vm_property_reset(self, untrusted_payload):
        assert self.arg in self.dest.property_list()
        assert not untrusted_payload
        del untrusted_payload

        self.fire_event_for_permission()

        delattr(self.dest, self.arg)
