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
import itertools
import pkg_resources
import libvirt

import qubes.api
import qubes.devices
import qubes.storage
import qubes.utils
import qubes.vm
import qubes.vm.qubesvm


class QubesMgmtEventsDispatcher(object):
    def __init__(self, filters, send_event):
        self.filters = filters
        self.send_event = send_event

    def vm_handler(self, subject, event, **kwargs):
        if event.startswith('mgmt-permission:'):
            return
        if not list(qubes.api.apply_filters([(subject, event, kwargs)],
                self.filters)):
            return
        self.send_event(subject, event, **kwargs)

    def app_handler(self, subject, event, **kwargs):
        if not list(qubes.api.apply_filters([(subject, event, kwargs)],
                self.filters)):
            return
        self.send_event(subject, event, **kwargs)

    def on_domain_add(self, subject, event, vm):
        # pylint: disable=unused-argument
        vm.add_handler('*', self.vm_handler)

    def on_domain_delete(self, subject, event, vm):
        # pylint: disable=unused-argument
        vm.remove_handler('*', self.vm_handler)


class QubesAdminAPI(qubes.api.AbstractQubesAPI):
    '''Implementation of Qubes Management API calls

    This class contains all the methods available in the main API.

    .. seealso::
        https://www.qubes-os.org/doc/mgmt1/
    '''

    SOCKNAME = '/var/run/qubesd.sock'

    @qubes.api.method('admin.vmclass.List', no_payload=True)
    @asyncio.coroutine
    def vmclass_list(self):
        '''List all VM classes'''
        assert not self.arg
        assert self.dest.name == 'dom0'

        entrypoints = self.fire_event_for_filter(
            pkg_resources.iter_entry_points(qubes.vm.VM_ENTRY_POINT))

        return ''.join('{}\n'.format(ep.name)
            for ep in entrypoints)

    @qubes.api.method('admin.vm.List', no_payload=True)
    @asyncio.coroutine
    def vm_list(self):
        '''List all the domains'''
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

    @qubes.api.method('admin.vm.property.List', no_payload=True)
    @asyncio.coroutine
    def vm_property_list(self):
        '''List all properties on a qube'''
        return self._property_list(self.dest)

    @qubes.api.method('admin.property.List', no_payload=True)
    @asyncio.coroutine
    def property_list(self):
        '''List all global properties'''
        assert self.dest.name == 'dom0'
        return self._property_list(self.app)

    def _property_list(self, dest):
        assert not self.arg

        properties = self.fire_event_for_filter(dest.property_list())

        return ''.join('{}\n'.format(prop.__name__) for prop in properties)

    @qubes.api.method('admin.vm.property.Get', no_payload=True)
    @asyncio.coroutine
    def vm_property_get(self):
        '''Get a value of one property'''
        return self._property_get(self.dest)

    @qubes.api.method('admin.property.Get', no_payload=True)
    @asyncio.coroutine
    def property_get(self):
        '''Get a value of one global property'''
        assert self.dest.name == 'dom0'
        return self._property_get(self.app)

    def _property_get(self, dest):
        if self.arg not in dest.property_list():
            raise qubes.exc.QubesNoSuchPropertyError(dest, self.arg)

        self.fire_event_for_permission()

        property_def = dest.property_get_def(self.arg)
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
            value = getattr(dest, self.arg)
        except AttributeError:
            return 'default=True type={} '.format(property_type)
        else:
            return 'default={} type={} {}'.format(
                str(dest.property_is_default(self.arg)),
                property_type,
                str(value) if value is not None else '')

    @qubes.api.method('admin.vm.property.Set')
    @asyncio.coroutine
    def vm_property_set(self, untrusted_payload):
        '''Set property value'''
        return self._property_set(self.dest,
            untrusted_payload=untrusted_payload)

    @qubes.api.method('admin.property.Set')
    @asyncio.coroutine
    def property_set(self, untrusted_payload):
        '''Set property value'''
        assert self.dest.name == 'dom0'
        return self._property_set(self.app,
            untrusted_payload=untrusted_payload)

    def _property_set(self, dest, untrusted_payload):
        if self.arg not in dest.property_list():
            raise qubes.exc.QubesNoSuchPropertyError(dest, self.arg)

        property_def = dest.property_get_def(self.arg)
        newvalue = property_def.sanitize(untrusted_newvalue=untrusted_payload)

        self.fire_event_for_permission(newvalue=newvalue)

        setattr(dest, self.arg, newvalue)
        self.app.save()

    @qubes.api.method('admin.vm.property.Help', no_payload=True)
    @asyncio.coroutine
    def vm_property_help(self):
        '''Get help for one property'''
        return self._property_help(self.dest)

    @qubes.api.method('admin.property.Help', no_payload=True)
    @asyncio.coroutine
    def property_help(self):
        '''Get help for one property'''
        assert self.dest.name == 'dom0'
        return self._property_help(self.app)

    def _property_help(self, dest):
        if self.arg not in dest.property_list():
            raise qubes.exc.QubesNoSuchPropertyError(dest, self.arg)

        self.fire_event_for_permission()

        try:
            doc = dest.property_get_def(self.arg).__doc__
        except AttributeError:
            return ''

        return qubes.utils.format_doc(doc)

    @qubes.api.method('admin.vm.property.Reset', no_payload=True)
    @asyncio.coroutine
    def vm_property_reset(self):
        '''Reset a property to a default value'''
        return self._property_reset(self.dest)

    @qubes.api.method('admin.property.Reset', no_payload=True)
    @asyncio.coroutine
    def property_reset(self):
        '''Reset a property to a default value'''
        assert self.dest.name == 'dom0'
        return self._property_reset(self.app)

    def _property_reset(self, dest):
        if self.arg not in dest.property_list():
            raise qubes.exc.QubesNoSuchPropertyError(dest, self.arg)

        self.fire_event_for_permission()

        delattr(dest, self.arg)
        self.app.save()

    @qubes.api.method('admin.vm.volume.List', no_payload=True)
    @asyncio.coroutine
    def vm_volume_list(self):
        assert not self.arg

        volume_names = self.fire_event_for_filter(self.dest.volumes.keys())
        return ''.join('{}\n'.format(name) for name in volume_names)

    @qubes.api.method('admin.vm.volume.Info', no_payload=True)
    @asyncio.coroutine
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

    @qubes.api.method('admin.vm.volume.ListSnapshots', no_payload=True)
    @asyncio.coroutine
    def vm_volume_listsnapshots(self):
        assert self.arg in self.dest.volumes.keys()

        volume = self.dest.volumes[self.arg]
        revisions = [revision for revision in volume.revisions]
        revisions = self.fire_event_for_filter(revisions)

        return ''.join('{}\n'.format(revision) for revision in revisions)

    @qubes.api.method('admin.vm.volume.Revert')
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

    @qubes.api.method('admin.vm.volume.Clone')
    @asyncio.coroutine
    def vm_volume_clone(self, untrusted_payload):
        assert self.arg in self.dest.volumes.keys()
        untrusted_target = untrusted_payload.decode('ascii').strip()
        del untrusted_payload
        qubes.vm.validate_name(None, None, untrusted_target)
        target_vm = self.app.domains[untrusted_target]
        del untrusted_target
        assert self.arg in target_vm.volumes.keys()

        volume = self.dest.volumes[self.arg]

        self.fire_event_for_permission(target_vm=target_vm, volume=volume)

        yield from target_vm.storage.clone_volume(self.dest, self.arg)
        self.app.save()

    @qubes.api.method('admin.vm.volume.Resize')
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

    @qubes.api.method('admin.vm.volume.Import', no_payload=True)
    @asyncio.coroutine
    def vm_volume_import(self):
        '''Import volume data.

        Note that this function only returns a path to where data should be
        written, actual importing is done by a script in /etc/qubes-rpc
        When the script finish importing, it will trigger
        internal.vm.volume.ImportEnd (with either b'ok' or b'fail' as a
        payload) and response from that call will be actually send to the
        caller.
        '''
        assert self.arg in self.dest.volumes.keys()

        self.fire_event_for_permission()

        if not self.dest.is_halted():
            raise qubes.exc.QubesVMNotHaltedError(self.dest)

        path = self.dest.storage.import_data(self.arg)
        assert ' ' not in path
        size = self.dest.volumes[self.arg].size

        # when we know the action is allowed, inform extensions that it will
        # be performed
        self.dest.fire_event('domain-volume-import-begin', volume=self.arg)

        return '{} {}'.format(size, path)

    @qubes.api.method('admin.vm.tag.List', no_payload=True)
    @asyncio.coroutine
    def vm_tag_list(self):
        assert not self.arg

        tags = self.dest.tags

        tags = self.fire_event_for_filter(tags)

        return ''.join('{}\n'.format(tag) for tag in sorted(tags))

    @qubes.api.method('admin.vm.tag.Get', no_payload=True)
    @asyncio.coroutine
    def vm_tag_get(self):
        qubes.vm.Tags.validate_tag(self.arg)

        self.fire_event_for_permission()

        return '1' if self.arg in self.dest.tags else '0'

    @qubes.api.method('admin.vm.tag.Set', no_payload=True)
    @asyncio.coroutine
    def vm_tag_set(self):
        qubes.vm.Tags.validate_tag(self.arg)

        self.fire_event_for_permission()

        self.dest.tags.add(self.arg)
        self.app.save()

    @qubes.api.method('admin.vm.tag.Remove', no_payload=True)
    @asyncio.coroutine
    def vm_tag_remove(self):
        qubes.vm.Tags.validate_tag(self.arg)

        self.fire_event_for_permission()

        try:
            self.dest.tags.remove(self.arg)
        except KeyError:
            raise qubes.exc.QubesTagNotFoundError(self.dest, self.arg)
        self.app.save()

    @qubes.api.method('admin.pool.List', no_payload=True)
    @asyncio.coroutine
    def pool_list(self):
        assert not self.arg
        assert self.dest.name == 'dom0'

        pools = self.fire_event_for_filter(self.app.pools)

        return ''.join('{}\n'.format(pool) for pool in pools)

    @qubes.api.method('admin.pool.ListDrivers', no_payload=True)
    @asyncio.coroutine
    def pool_listdrivers(self):
        assert self.dest.name == 'dom0'
        assert not self.arg

        drivers = self.fire_event_for_filter(qubes.storage.pool_drivers())

        return ''.join('{} {}\n'.format(
            driver,
            ' '.join(qubes.storage.driver_parameters(driver)))
            for driver in drivers)

    @qubes.api.method('admin.pool.Info', no_payload=True)
    @asyncio.coroutine
    def pool_info(self):
        assert self.dest.name == 'dom0'
        assert self.arg in self.app.pools.keys()

        pool = self.app.pools[self.arg]

        self.fire_event_for_permission(pool=pool)

        return ''.join('{}={}\n'.format(prop, val)
            for prop, val in sorted(pool.config.items()))

    @qubes.api.method('admin.pool.Add')
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

    @qubes.api.method('admin.pool.Remove', no_payload=True)
    @asyncio.coroutine
    def pool_remove(self):
        assert self.dest.name == 'dom0'
        assert self.arg in self.app.pools.keys()

        self.fire_event_for_permission()

        self.app.remove_pool(self.arg)
        self.app.save()

    @qubes.api.method('admin.label.List', no_payload=True)
    @asyncio.coroutine
    def label_list(self):
        assert self.dest.name == 'dom0'
        assert not self.arg

        labels = self.fire_event_for_filter(self.app.labels.values())

        return ''.join('{}\n'.format(label.name) for label in labels)

    @qubes.api.method('admin.label.Get', no_payload=True)
    @asyncio.coroutine
    def label_get(self):
        assert self.dest.name == 'dom0'

        try:
            label = self.app.get_label(self.arg)
        except KeyError:
            raise qubes.exc.QubesValueError

        self.fire_event_for_permission(label=label)

        return label.color

    @qubes.api.method('admin.label.Index', no_payload=True)
    @asyncio.coroutine
    def label_index(self):
        assert self.dest.name == 'dom0'

        try:
            label = self.app.get_label(self.arg)
        except KeyError:
            raise qubes.exc.QubesValueError

        self.fire_event_for_permission(label=label)

        return str(label.index)

    @qubes.api.method('admin.label.Create')
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

    @qubes.api.method('admin.label.Remove', no_payload=True)
    @asyncio.coroutine
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

    @qubes.api.method('admin.vm.Start', no_payload=True)
    @asyncio.coroutine
    def vm_start(self):
        assert not self.arg
        self.fire_event_for_permission()
        try:
            yield from self.dest.start()
        except libvirt.libvirtError as e:
            # change to QubesException, so will be reported to the user
            raise qubes.exc.QubesException('Start failed: ' + str(e))


    @qubes.api.method('admin.vm.Shutdown', no_payload=True)
    @asyncio.coroutine
    def vm_shutdown(self):
        assert not self.arg
        self.fire_event_for_permission()
        yield from self.dest.shutdown()

    @qubes.api.method('admin.vm.Pause', no_payload=True)
    @asyncio.coroutine
    def vm_pause(self):
        assert not self.arg
        self.fire_event_for_permission()
        yield from self.dest.pause()

    @qubes.api.method('admin.vm.Unpause', no_payload=True)
    @asyncio.coroutine
    def vm_unpause(self):
        assert not self.arg
        self.fire_event_for_permission()
        yield from self.dest.unpause()

    @qubes.api.method('admin.vm.Kill', no_payload=True)
    @asyncio.coroutine
    def vm_kill(self):
        assert not self.arg
        self.fire_event_for_permission()
        yield from self.dest.kill()

    @qubes.api.method('admin.Events', no_payload=True)
    @asyncio.coroutine
    def events(self):
        assert not self.arg

        # run until client connection is terminated
        self.cancellable = True
        wait_for_cancel = asyncio.get_event_loop().create_future()

        # cache event filters, to not call an event each time an event arrives
        event_filters = self.fire_event_for_permission()

        dispatcher = QubesMgmtEventsDispatcher(event_filters, self.send_event)
        if self.dest.name == 'dom0':
            self.app.add_handler('*', dispatcher.app_handler)
            self.app.add_handler('domain-add', dispatcher.on_domain_add)
            self.app.add_handler('domain-delete', dispatcher.on_domain_delete)
            for vm in self.app.domains:
                vm.add_handler('*', dispatcher.vm_handler)
        else:
            self.dest.add_handler('*', dispatcher.vm_handler)

        # send artificial event as a confirmation that connection is established
        self.send_event(self.app, 'connection-established')

        try:
            yield from wait_for_cancel
        except asyncio.CancelledError:
            # the above waiting was already interrupted, this is all we need
            pass

        if self.dest.name == 'dom0':
            self.app.remove_handler('*', dispatcher.app_handler)
            self.app.remove_handler('domain-add', dispatcher.on_domain_add)
            self.app.remove_handler('domain-delete',
                dispatcher.on_domain_delete)
            for vm in self.app.domains:
                vm.remove_handler('*', dispatcher.vm_handler)
        else:
            self.dest.remove_handler('*', dispatcher.vm_handler)

    @qubes.api.method('admin.vm.feature.List', no_payload=True)
    @asyncio.coroutine
    def vm_feature_list(self):
        assert not self.arg
        features = self.fire_event_for_filter(self.dest.features.keys())
        return ''.join('{}\n'.format(feature) for feature in features)

    @qubes.api.method('admin.vm.feature.Get', no_payload=True)
    @asyncio.coroutine
    def vm_feature_get(self):
        # validation of self.arg done by qrexec-policy is enough

        self.fire_event_for_permission()
        try:
            value = self.dest.features[self.arg]
        except KeyError:
            raise qubes.exc.QubesFeatureNotFoundError(self.dest, self.arg)
        return value

    @qubes.api.method('admin.vm.feature.CheckWithTemplate', no_payload=True)
    @asyncio.coroutine
    def vm_feature_checkwithtemplate(self):
        # validation of self.arg done by qrexec-policy is enough

        self.fire_event_for_permission()
        try:
            value = self.dest.features.check_with_template(self.arg)
        except KeyError:
            raise qubes.exc.QubesFeatureNotFoundError(self.dest, self.arg)
        return value

    @qubes.api.method('admin.vm.feature.Remove', no_payload=True)
    @asyncio.coroutine
    def vm_feature_remove(self):
        # validation of self.arg done by qrexec-policy is enough

        self.fire_event_for_permission()
        try:
            del self.dest.features[self.arg]
        except KeyError:
            raise qubes.exc.QubesFeatureNotFoundError(self.dest, self.arg)
        self.app.save()

    @qubes.api.method('admin.vm.feature.Set')
    @asyncio.coroutine
    def vm_feature_set(self, untrusted_payload):
        # validation of self.arg done by qrexec-policy is enough
        value = untrusted_payload.decode('ascii', errors='strict')
        del untrusted_payload

        self.fire_event_for_permission(value=value)
        self.dest.features[self.arg] = value
        self.app.save()

    @qubes.api.method('admin.vm.Create.{endpoint}', endpoints=(ep.name
            for ep in pkg_resources.iter_entry_points(qubes.vm.VM_ENTRY_POINT)))
    @asyncio.coroutine
    def vm_create(self, endpoint, untrusted_payload=None):
        return self._vm_create(endpoint, allow_pool=False,
            untrusted_payload=untrusted_payload)

    @qubes.api.method('admin.vm.CreateInPool.{endpoint}', endpoints=(ep.name
            for ep in pkg_resources.iter_entry_points(qubes.vm.VM_ENTRY_POINT)))
    @asyncio.coroutine
    def vm_create_in_pool(self, endpoint, untrusted_payload=None):
        return self._vm_create(endpoint, allow_pool=True,
            untrusted_payload=untrusted_payload)

    def _vm_create(self, vm_type, allow_pool=False, untrusted_payload=None):
        assert self.dest.name == 'dom0'

        kwargs = {}
        pool = None
        pools = {}

        # this will raise exception if none is found
        vm_class = qubes.utils.get_entry_point_one(qubes.vm.VM_ENTRY_POINT,
            vm_type)

        # if argument is given, it needs to be a valid template, and only
        # when given VM class do need a template
        if hasattr(vm_class, 'template'):
            if self.arg:
                assert self.arg in self.app.domains
                kwargs['template'] = self.app.domains[self.arg]
        else:
            assert not self.arg

        for untrusted_param in untrusted_payload.decode('ascii',
                errors='strict').split(' '):
            untrusted_key, untrusted_value = untrusted_param.split('=', 1)
            if untrusted_key in kwargs:
                raise qubes.api.ProtocolError('duplicated parameters')

            if untrusted_key == 'name':
                qubes.vm.validate_name(None, None, untrusted_value)
                kwargs['name'] = untrusted_value

            elif untrusted_key == 'label':
                # don't confuse label name with label index
                assert not untrusted_value.isdigit()
                allowed_chars = string.ascii_letters + string.digits + '-_.'
                assert all(c in allowed_chars for c in untrusted_value)
                try:
                    kwargs['label'] = self.app.get_label(untrusted_value)
                except KeyError:
                    raise qubes.exc.QubesValueError

            elif untrusted_key == 'pool' and allow_pool:
                if pool is not None:
                    raise qubes.api.ProtocolError('duplicated pool parameter')
                pool = self.app.get_pool(untrusted_value)
            elif untrusted_key.startswith('pool:') and allow_pool:
                untrusted_volume = untrusted_key.split(':', 1)[1]
                # kind of ugly, but actual list of volumes is available only
                # after creating a VM
                assert untrusted_volume in ['root', 'private', 'volatile',
                    'kernel']
                volume = untrusted_volume
                if volume in pools:
                    raise qubes.api.ProtocolError(
                        'duplicated pool:{} parameter'.format(volume))
                pools[volume] = self.app.get_pool(untrusted_value)

            else:
                raise qubes.api.ProtocolError('Invalid param name')
        del untrusted_payload

        if 'name' not in kwargs or 'label' not in kwargs:
            raise qubes.api.ProtocolError('Missing name or label')

        if pool and pools:
            raise qubes.api.ProtocolError(
                'Only one of \'pool=\' and \'pool:volume=\' can be used')

        if kwargs['name'] in self.app.domains:
            raise qubes.exc.QubesValueError(
                'VM {} already exists'.format(kwargs['name']))

        self.fire_event_for_permission(pool=pool, pools=pools, **kwargs)

        vm = self.app.add_new_vm(vm_class, **kwargs)
        # TODO: move this to extension (in race-free fashion)
        vm.tags.add('created-by-' + str(self.src))

        try:
            yield from vm.create_on_disk(pool=pool, pools=pools)
        except:
            del self.app.domains[vm]
            raise
        self.app.save()

    @qubes.api.method('admin.vm.Remove', no_payload=True)
    @asyncio.coroutine
    def vm_remove(self):
        assert not self.arg

        self.fire_event_for_permission()

        if not self.dest.is_halted():
            raise qubes.exc.QubesVMNotHaltedError(self.dest)

        del self.app.domains[self.dest]
        try:
            yield from self.dest.remove_from_disk()
        except:  # pylint: disable=bare-except
            self.app.log.exception('Error wile removing VM \'%s\' files',
                self.dest.name)

        self.app.save()

    @qubes.api.method('admin.vm.device.{endpoint}.Available', endpoints=(ep.name
            for ep in pkg_resources.iter_entry_points('qubes.devices')),
            no_payload=True)
    @asyncio.coroutine
    def vm_device_available(self, endpoint):
        devclass = endpoint
        devices = self.dest.devices[devclass].available()
        if self.arg:
            devices = [dev for dev in devices if dev.ident == self.arg]
            # no duplicated devices, but device may not exists, in which case
            #  the list is empty
            assert len(devices) <= 1
        devices = self.fire_event_for_filter(devices, devclass=devclass)

        dev_info = {}
        for dev in devices:
            non_default_attrs = set(attr for attr in dir(dev) if
                not attr.startswith('_')).difference((
                    'backend_domain', 'ident', 'frontend_domain',
                    'description', 'options'))
            properties_txt = ' '.join(
                '{}={!s}'.format(prop, value) for prop, value
                in itertools.chain(
                    ((key, getattr(dev, key)) for key in non_default_attrs),
                    # keep description as the last one, according to API
                    # specification
                    (('description', dev.description),)
                ))
            assert '\n' not in properties_txt
            dev_info[dev.ident] = properties_txt

        return ''.join('{} {}\n'.format(ident, dev_info[ident])
            for ident in sorted(dev_info))

    @qubes.api.method('admin.vm.device.{endpoint}.List', endpoints=(ep.name
            for ep in pkg_resources.iter_entry_points('qubes.devices')),
            no_payload=True)
    @asyncio.coroutine
    def vm_device_list(self, endpoint):
        devclass = endpoint
        device_assignments = self.dest.devices[devclass].assignments()
        if self.arg:
            select_backend, select_ident = self.arg.split('+', 1)
            device_assignments = [dev for dev in device_assignments
                if (str(dev.backend_domain), dev.ident)
                   == (select_backend, select_ident)]
            # no duplicated devices, but device may not exists, in which case
            #  the list is empty
            assert len(device_assignments) <= 1
        device_assignments = self.fire_event_for_filter(device_assignments,
            devclass=devclass)

        dev_info = {}
        for dev in device_assignments:
            properties_txt = ' '.join(
                '{}={!s}'.format(opt, value) for opt, value
                in itertools.chain(
                    dev.options.items(),
                    (('persistent', 'yes' if dev.persistent else 'no'),)
                ))
            assert '\n' not in properties_txt
            ident = '{!s}+{!s}'.format(dev.backend_domain, dev.ident)
            dev_info[ident] = properties_txt

        return ''.join('{} {}\n'.format(ident, dev_info[ident])
            for ident in sorted(dev_info))

    @qubes.api.method('admin.vm.device.{endpoint}.Attach', endpoints=(ep.name
            for ep in pkg_resources.iter_entry_points('qubes.devices')))
    @asyncio.coroutine
    def vm_device_attach(self, endpoint, untrusted_payload):
        devclass = endpoint
        options = {}
        persistent = False
        for untrusted_option in untrusted_payload.decode('ascii').split():
            try:
                untrusted_key, untrusted_value = untrusted_option.split('=', 1)
            except ValueError:
                raise qubes.api.ProtocolError('Invalid options format')
            if untrusted_key == 'persistent':
                persistent = qubes.property.bool(None, None, untrusted_value)
            else:
                allowed_chars_key = string.digits + string.ascii_letters + '-_.'
                allowed_chars_value = allowed_chars_key + ',+:'
                if any(x not in allowed_chars_key for x in untrusted_key):
                    raise qubes.api.ProtocolError(
                        'Invalid chars in option name')
                if any(x not in allowed_chars_value for x in untrusted_value):
                    raise qubes.api.ProtocolError(
                        'Invalid chars in option value')
                options[untrusted_key] = untrusted_value

        # qrexec already verified that no strange characters are in self.arg
        backend_domain, ident = self.arg.split('+', 1)
        # may raise KeyError, either on domain or ident
        dev = self.app.domains[backend_domain].devices[devclass][ident]

        self.fire_event_for_permission(device=dev,
            devclass=devclass, persistent=persistent,
            options=options)

        assignment = qubes.devices.DeviceAssignment(
            dev.backend_domain, dev.ident,
            options=options, persistent=persistent)
        self.dest.devices[devclass].attach(assignment)
        self.app.save()

    @qubes.api.method('admin.vm.device.{endpoint}.Detach', endpoints=(ep.name
            for ep in pkg_resources.iter_entry_points('qubes.devices')),
            no_payload=True)
    @asyncio.coroutine
    def vm_device_detach(self, endpoint):
        devclass = endpoint

        # qrexec already verified that no strange characters are in self.arg
        backend_domain, ident = self.arg.split('+', 1)
        # may raise KeyError; if device isn't found, it will be UnknownDevice
        #  instance - but allow it, otherwise it will be impossible to detach
        #  already removed device
        dev = self.app.domains[backend_domain].devices[devclass][ident]

        self.fire_event_for_permission(device=dev,
            devclass=devclass)

        assignment = qubes.devices.DeviceAssignment(
            dev.backend_domain, dev.ident)
        self.dest.devices[devclass].detach(assignment)
        self.app.save()
