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
import string

import functools

import qubes.vm.qubesvm
import qubes.storage


class ProtocolError(AssertionError):
    '''Raised when something is wrong with data received'''
    pass

class PermissionDenied(Exception):
    '''Raised deliberately by handlers when we decide not to cooperate'''
    pass


def not_in_api(func):
    func.not_in_api = True
    return func


def no_payload(func):
    @functools.wraps(func)
    def wrapper(self, untrusted_payload):
        if untrusted_payload != b'':
            raise ProtocolError('unexpected payload')
        return func(self)
    return wrapper


class QubesMgmt(object):
    def __init__(self, app, src, method, dest, arg):
        self.app = app

        self.src = self.app.domains[src.decode('ascii')]
        self.dest = self.app.domains[dest.decode('ascii')]
        self.arg = arg.decode('ascii')

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
            dest=self.dest, arg=self.arg, **kwargs)

    @not_in_api
    def fire_event_for_filter(self, iterable, **kwargs):
        for selector in self.fire_event_for_permission(**kwargs):
            iterable = filter(selector, iterable)
        return iterable


    #
    # ACTUAL RPC CALLS
    #

    @asyncio.coroutine
    @no_payload
    def vm_list(self):
        assert not self.arg

        if self.dest.name == 'dom0':
            domains = self.fire_event_for_filter(self.app.domains)
        else:
            domains = self.fire_event_for_filter([self.dest])

        return ''.join('{} class={} state={}\n'.format(
                vm.name,
                vm.__class__.__name__,
                vm.get_power_state())
            for vm in sorted(domains))

    @asyncio.coroutine
    @no_payload
    def vm_property_list(self):
        assert not self.arg

        properties = self.fire_event_for_filter(self.dest.property_list())

        return ''.join('{}\n'.format(prop.__name__) for prop in properties)

    @asyncio.coroutine
    @no_payload
    def vm_property_get(self):
        assert self.arg in self.dest.property_list()

        self.fire_event_for_permission()

        property_def = self.dest.property_get_def(self.arg)
        # explicit list to be sure that it matches protocol spec
        if isinstance(property_def, qubes.vm.VMProperty):
            property_type = 'vm'
        elif property_def.type is int:
            property_type = 'int'
        elif property_def.type is bool:
            property_type = 'bool'
        elif self.arg == 'label':
            property_type = 'label'
        else:
            property_type = 'str'

        try:
            value = getattr(self.dest, self.arg)
        except AttributeError:
            return 'default=True type={} '.format(property_type)
        else:
            return 'default={} type={} {}'.format(
                str(self.dest.property_is_default(self.arg)),
                property_type,
                str(value) if value is not None else '')

    @asyncio.coroutine
    def vm_property_set(self, untrusted_payload):
        assert self.arg in self.dest.property_list()

        property_def = self.dest.property_get_def(self.arg)
        newvalue = property_def.sanitize(untrusted_newvalue=untrusted_payload)

        self.fire_event_for_permission(newvalue=newvalue)

        setattr(self.dest, self.arg, newvalue)
        self.app.save()

    @asyncio.coroutine
    @no_payload
    def vm_property_help(self):
        assert self.arg in self.dest.property_list()

        self.fire_event_for_permission()

        try:
            doc = self.dest.property_get_def(self.arg).__doc__
        except AttributeError:
            return ''

        return qubes.utils.format_doc(doc)

    @asyncio.coroutine
    @no_payload
    def vm_property_reset(self):
        assert self.arg in self.dest.property_list()

        self.fire_event_for_permission()

        delattr(self.dest, self.arg)
        self.app.save()

    @asyncio.coroutine
    @no_payload
    def vm_volume_list(self):
        assert not self.arg

        volume_names = self.fire_event_for_filter(self.dest.volumes.keys())
        return ''.join('{}\n'.format(name) for name in volume_names)

    @asyncio.coroutine
    @no_payload
    def vm_volume_info(self):
        assert self.arg in self.dest.volumes.keys()

        self.fire_event_for_permission()

        volume = self.dest.volumes[self.arg]
        # properties defined in API
        volume_properties = [
            'pool', 'vid', 'size', 'usage', 'rw', 'internal', 'source',
            'save_on_stop', 'snap_on_start']
        return ''.join('{}={}\n'.format(key, getattr(volume, key)) for key in
            volume_properties)

    @asyncio.coroutine
    @no_payload
    def vm_volume_listsnapshots(self):
        assert self.arg in self.dest.volumes.keys()

        volume = self.dest.volumes[self.arg]
        revisions = [revision for revision in volume.revisions]
        revisions = self.fire_event_for_filter(revisions)

        return ''.join('{}\n'.format(revision) for revision in revisions)

    @asyncio.coroutine
    def vm_volume_revert(self, untrusted_payload):
        assert self.arg in self.dest.volumes.keys()
        untrusted_revision = untrusted_payload.decode('ascii').strip()
        del untrusted_payload

        volume = self.dest.volumes[self.arg]
        snapshots = volume.revisions
        assert untrusted_revision in snapshots
        revision = untrusted_revision

        self.fire_event_for_permission(revision=revision)

        self.dest.storage.get_pool(volume).revert(revision)
        self.app.save()

    @asyncio.coroutine
    def vm_volume_resize(self, untrusted_payload):
        assert self.arg in self.dest.volumes.keys()
        untrusted_size = untrusted_payload.decode('ascii').strip()
        del untrusted_payload
        assert untrusted_size.isdigit()  # only digits, forbid '-' too
        assert len(untrusted_size) <= 20  # limit to about 2^64

        size = int(untrusted_size)

        self.fire_event_for_permission(size=size)

        self.dest.storage.resize(self.arg, size)
        self.app.save()

    @asyncio.coroutine
    @no_payload
    def pool_list(self):
        assert not self.arg
        assert self.dest.name == 'dom0'

        pools = self.fire_event_for_filter(self.app.pools)

        return ''.join('{}\n'.format(pool) for pool in pools)

    @asyncio.coroutine
    @no_payload
    def pool_listdrivers(self):
        assert self.dest.name == 'dom0'
        assert not self.arg

        drivers = self.fire_event_for_filter(qubes.storage.pool_drivers())

        return ''.join('{} {}\n'.format(
            driver,
            ' '.join(qubes.storage.driver_parameters(driver)))
            for driver in drivers)

    @asyncio.coroutine
    @no_payload
    def pool_info(self):
        assert self.dest.name == 'dom0'
        assert self.arg in self.app.pools.keys()

        pool = self.app.pools[self.arg]

        self.fire_event_for_permission(pool=pool)

        return ''.join('{}={}\n'.format(prop, val)
            for prop, val in sorted(pool.config.items()))

    @asyncio.coroutine
    def pool_add(self, untrusted_payload):
        assert self.dest.name == 'dom0'
        drivers = qubes.storage.pool_drivers()
        assert self.arg in drivers
        untrusted_pool_config = untrusted_payload.decode('ascii').splitlines()
        del untrusted_payload
        assert all(('=' in line) for line in untrusted_pool_config)
        # pairs of (option, value)
        untrusted_pool_config = [line.split('=', 1)
            for line in untrusted_pool_config]
        # reject duplicated options
        assert len(set(x[0] for x in untrusted_pool_config)) == \
               len([x[0] for x in untrusted_pool_config])
        # and convert to dict
        untrusted_pool_config = dict(untrusted_pool_config)

        assert 'name' in untrusted_pool_config
        untrusted_pool_name = untrusted_pool_config.pop('name')
        allowed_chars = string.ascii_letters + string.digits + '-_.'
        assert all(c in allowed_chars for c in untrusted_pool_name)
        pool_name = untrusted_pool_name
        assert pool_name not in self.app.pools

        driver_parameters = qubes.storage.driver_parameters(self.arg)
        assert all(key in driver_parameters for key in untrusted_pool_config)
        pool_config = untrusted_pool_config

        self.fire_event_for_permission(name=pool_name,
            pool_config=pool_config)

        self.app.add_pool(name=pool_name, driver=self.arg, **pool_config)
        self.app.save()

    @asyncio.coroutine
    @no_payload
    def pool_remove(self):
        assert self.dest.name == 'dom0'
        assert self.arg in self.app.pools.keys()

        self.fire_event_for_permission()

        self.app.remove_pool(self.arg)
        self.app.save()

    @asyncio.coroutine
    @no_payload
    def label_list(self):
        assert self.dest.name == 'dom0'
        assert not self.arg

        labels = self.fire_event_for_filter(self.app.labels.values())

        return ''.join('{}\n'.format(label.name) for label in labels)

    @asyncio.coroutine
    @no_payload
    def label_get(self):
        assert self.dest.name == 'dom0'

        try:
            label = self.app.get_label(self.arg)
        except KeyError:
            raise qubes.exc.QubesValueError

        self.fire_event_for_permission(label=label)

        return label.color

    @asyncio.coroutine
    def label_create(self, untrusted_payload):
        assert self.dest.name == 'dom0'

        # don't confuse label name with label index
        assert not self.arg.isdigit()
        allowed_chars = string.ascii_letters + string.digits + '-_.'
        assert all(c in allowed_chars for c in self.arg)
        try:
            self.app.get_label(self.arg)
        except KeyError:
            # ok, no such label yet
            pass
        else:
            raise qubes.exc.QubesValueError('label already exists')

        untrusted_payload = untrusted_payload.decode('ascii').strip()
        assert len(untrusted_payload) == 8
        assert untrusted_payload.startswith('0x')
        # besides prefix, only hex digits are allowed
        assert all(x in string.hexdigits for x in untrusted_payload[2:])

        # SEE: #2732
        color = untrusted_payload

        self.fire_event_for_permission(color=color)

        # allocate new index, but make sure it's outside of default labels set
        new_index = max(
            qubes.config.max_default_label, *self.app.labels.keys()) + 1

        label = qubes.Label(new_index, color, self.arg)
        self.app.labels[new_index] = label
        self.app.save()

    @asyncio.coroutine
    @no_payload
    def label_remove(self):
        assert self.dest.name == 'dom0'

        try:
            label = self.app.get_label(self.arg)
        except KeyError:
            raise qubes.exc.QubesValueError
        # don't allow removing default labels
        assert label.index > qubes.config.max_default_label

        # FIXME: this should be in app.add_label()
        for vm in self.app.domains:
            if vm.label == label:
                raise qubes.exc.QubesException('label still in use')

        self.fire_event_for_permission(label=label)

        del self.app.labels[label.index]
        self.app.save()
