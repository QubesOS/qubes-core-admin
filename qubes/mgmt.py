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

import qubes.vm.qubesvm


class ProtocolError(AssertionError):
    '''Raised when something is wrong with data received'''
    pass

class PermissionDenied(Exception):
    '''Raised deliberately by handlers when we decide not to cooperate'''
    pass


def not_in_api(func):
    '''Decorator for methods not intended to appear in API.

    The decorated method cannot be called from public API using
    :py:class:`QubesMgmt` class. The method becomes "private", and can be
    called only as a helper for other methods.
    '''
    func.not_in_api = True
    return func

class QubesMgmt(object):
    '''Implementation of Qubes Management API calls

    This class contains all the methods available in the API.
    '''
    def __init__(self, app, src, method, dest, arg):
        #: :py:class:`qubes.Qubes` object
        self.app = app

        #: source qube
        self.src = self.app.domains[src.decode('ascii')]

        #: destination qube
        self.dest = self.app.domains[dest.decode('ascii')]

        #: argument
        self.arg = arg.decode('ascii')

        #: name of the method
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
        '''Fire an event on the source qube to check for permission'''
        return self.src.fire_event_pre('mgmt-permission:{}'.format(self.method),
            dest=self.dest, arg=self.arg, **kwargs)

    @not_in_api
    def fire_event_for_filter(self, iterable, **kwargs):
        '''Fire an event on the source qube to filter for permission'''
        for selector in self.fire_event_for_permission(**kwargs):
            iterable = filter(selector, iterable)
        return iterable

    #
    # ACTUAL RPC CALLS
    #

    @asyncio.coroutine
    def vm_list(self, untrusted_payload):
        '''List all the domains'''
        assert self.dest.name == 'dom0'
        assert not self.arg
        assert not untrusted_payload
        del untrusted_payload

        domains = self.fire_event_for_filter(self.app.domains)

        return ''.join('{} class={} state={}\n'.format(
                vm.name,
                vm.__class__.__name__,
                vm.get_power_state())
            for vm in sorted(domains))

    @asyncio.coroutine
    def vm_property_list(self, untrusted_payload):
        '''List all properties on a qube'''
        assert not self.arg
        assert not untrusted_payload
        del untrusted_payload

        properties = self.fire_event_for_filter(self.dest.property_list())

        return ''.join('{}\n'.format(prop.__name__) for prop in properties)

    @asyncio.coroutine
    def vm_property_get(self, untrusted_payload):
        '''Get a value of one property'''
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
                str(value))

    @asyncio.coroutine
    def vm_property_help(self, untrusted_payload):
        '''Get help for one property'''
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
        '''Reset a property to a default value'''
        assert self.arg in self.dest.property_list()
        assert not untrusted_payload
        del untrusted_payload

        self.fire_event_for_permission()

        delattr(self.dest, self.arg)
