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
import functools
import string

import pkg_resources

import qubes.vm
import qubes.vm.qubesvm
import qubes.storage
import qubes.utils

class ProtocolError(AssertionError):
    '''Raised when something is wrong with data received'''
    pass

class PermissionDenied(Exception):
    '''Raised deliberately by handlers when we decide not to cooperate'''
    pass


def api(name, *, no_payload=False, endpoints=None):
    '''Decorator factory for methods intended to appear in API.

    The decorated method can be called from public API using a child of
    :py:class:`AbstractQubesMgmt` class. The method becomes "public", and can be
    called using remote management interface.

    :param str name: qrexec rpc method name
    :param bool no_payload: if :py:obj:`True`, will barf on non-empty payload; \
        also will not pass payload at all to the method

    The expected function method should have one argument (other than usual
    *self*), ``untrusted_payload``, which will contain the payload.

    .. warning::
        This argument has to be named such, to remind the programmer that the
        content of this variable is indeed untrusted.

    If *no_payload* is true, then the method is called with no arguments.
    '''

    def decorator(func):
        if no_payload:
            # the following assignment is needed for how closures work in Python
            _func = func
            @functools.wraps(_func)
            def wrapper(self, untrusted_payload, **kwargs):
                if untrusted_payload != b'':
                    raise ProtocolError('unexpected payload')
                return _func(self, **kwargs)
            func = wrapper

        # pylint: disable=protected-access
        if endpoints is None:
            func._rpcname = ((name, None),)
        else:
            func._rpcname = tuple(
                (name.format(endpoint=endpoint), endpoint)
                for endpoint in endpoints)
        return func

    return decorator


def apply_filters(iterable, filters):
    '''Apply filters returned by mgmt-permission:... event'''
    for selector in filters:
        iterable = filter(selector, iterable)
    return iterable


class AbstractQubesMgmt(object):
    '''Common code for Qubes Management Protocol handling

    Different interfaces can expose different API call sets, however they share
    common protocol and common implementation framework. This class is the
    latter.

    To implement a new interface, inherit from this class and write at least one
    method and decorate it with :py:func:`api` decorator. It will have access to
    pre-defined attributes: :py:attr:`app`, :py:attr:`src`, :py:attr:`dest`,
    :py:attr:`arg` and :py:attr:`method`.

    There are also two helper functions for firing events associated with API
    calls.
    '''
    def __init__(self, app, src, method, dest, arg, send_event=None):
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

        #: callback for sending events if applicable
        self.send_event = send_event

        #: is this operation cancellable?
        self.cancellable = False

        untrusted_candidates = []
        for attr in dir(self):
            func = getattr(self, attr)

            if not callable(func):
                continue

            try:
                # pylint: disable=protected-access
                for method_name, endpoint in func._rpcname:
                    if method_name != self.method:
                        continue
                    untrusted_candidates.append((func, endpoint))
            except AttributeError:
                continue

        if not untrusted_candidates:
            raise ProtocolError('no such method: {!r}'.format(self.method))

        assert len(untrusted_candidates) == 1, \
            'multiple candidates for method {!r}'.format(self.method)

        #: the method to execute
        self._handler = untrusted_candidates[0]
        self._running_handler = None
        del untrusted_candidates

    def execute(self, *, untrusted_payload):
        '''Execute management operation.

        This method is a coroutine.
        '''
        handler, endpoint = self._handler
        kwargs = {}
        if endpoint is not None:
            kwargs['endpoint'] = endpoint
        self._running_handler = asyncio.ensure_future(handler(
            untrusted_payload=untrusted_payload, **kwargs))
        return self._running_handler

    def cancel(self):
        '''If operation is cancellable, interrupt it'''
        if self.cancellable and self._running_handler is not None:
            self._running_handler.cancel()


    def fire_event_for_permission(self, **kwargs):
        '''Fire an event on the source qube to check for permission'''
        return self.src.fire_event_pre('mgmt-permission:{}'.format(self.method),
            dest=self.dest, arg=self.arg, **kwargs)

    def fire_event_for_filter(self, iterable, **kwargs):
        '''Fire an event on the source qube to filter for permission'''
        return apply_filters(iterable,
            self.fire_event_for_permission(**kwargs))


class QubesMgmtEventsDispatcher(object):
    def __init__(self, filters, send_event):
        self.filters = filters
        self.send_event = send_event

    def vm_handler(self, subject, event, **kwargs):
        if event.startswith('mgmt-permission:'):
            return
        if not list(apply_filters([(subject, event, kwargs)],
                self.filters)):
            return
        self.send_event(subject, event, **kwargs)

    def app_handler(self, subject, event, **kwargs):
        if not list(apply_filters([(subject, event, kwargs)],
                self.filters)):
            return
        self.send_event(subject, event, **kwargs)

    def on_domain_add(self, subject, event, vm):
        # pylint: disable=unused-argument
        vm.add_handler('*', self.vm_handler)

    def on_domain_delete(self, subject, event, vm):
        # pylint: disable=unused-argument
        vm.remove_handler('*', self.vm_handler)


class QubesMgmt(AbstractQubesMgmt):
    '''Implementation of Qubes Management API calls

    This class contains all the methods available in the main API.

    .. seealso::
        https://www.qubes-os.org/doc/mgmt1/
    '''

    @api('mgmt.vmclass.List', no_payload=True)
    @asyncio.coroutine
    def vmclass_list(self):
        '''List all VM classes'''
        assert not self.arg
        assert self.dest.name == 'dom0'

        entrypoints = self.fire_event_for_filter(
            pkg_resources.iter_entry_points(qubes.vm.VM_ENTRY_POINT))

        return ''.join('{}\n'.format(ep.name)
            for ep in entrypoints)

    @api('mgmt.vm.List', no_payload=True)
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

    @api('mgmt.vm.property.List', no_payload=True)
    @asyncio.coroutine
    def vm_property_list(self):
        '''List all properties on a qube'''
        assert not self.arg

        properties = self.fire_event_for_filter(self.dest.property_list())

        return ''.join('{}\n'.format(prop.__name__) for prop in properties)

    @api('mgmt.vm.property.Get', no_payload=True)
    @asyncio.coroutine
    def vm_property_get(self):
        '''Get a value of one property'''
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

    @api('mgmt.vm.property.Set')
    @asyncio.coroutine
    def vm_property_set(self, untrusted_payload):
        assert self.arg in self.dest.property_list()

        property_def = self.dest.property_get_def(self.arg)
        newvalue = property_def.sanitize(untrusted_newvalue=untrusted_payload)

        self.fire_event_for_permission(newvalue=newvalue)

        setattr(self.dest, self.arg, newvalue)
        self.app.save()

    @api('mgmt.vm.property.Help', no_payload=True)
    @asyncio.coroutine
    def vm_property_help(self):
        '''Get help for one property'''
        assert self.arg in self.dest.property_list()

        self.fire_event_for_permission()

        try:
            doc = self.dest.property_get_def(self.arg).__doc__
        except AttributeError:
            return ''

        return qubes.utils.format_doc(doc)

    @api('mgmt.vm.property.Reset', no_payload=True)
    @asyncio.coroutine
    def vm_property_reset(self):
        '''Reset a property to a default value'''
        assert self.arg in self.dest.property_list()

        self.fire_event_for_permission()

        delattr(self.dest, self.arg)
        self.app.save()

    @api('mgmt.vm.volume.List', no_payload=True)
    @asyncio.coroutine
    def vm_volume_list(self):
        assert not self.arg

        volume_names = self.fire_event_for_filter(self.dest.volumes.keys())
        return ''.join('{}\n'.format(name) for name in volume_names)

    @api('mgmt.vm.volume.Info', no_payload=True)
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

    @api('mgmt.vm.volume.ListSnapshots', no_payload=True)
    @asyncio.coroutine
    def vm_volume_listsnapshots(self):
        assert self.arg in self.dest.volumes.keys()

        volume = self.dest.volumes[self.arg]
        revisions = [revision for revision in volume.revisions]
        revisions = self.fire_event_for_filter(revisions)

        return ''.join('{}\n'.format(revision) for revision in revisions)

    @api('mgmt.vm.volume.Revert')
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

    @api('mgmt.vm.volume.Resize')
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

    @api('mgmt.pool.List', no_payload=True)
    @asyncio.coroutine
    def pool_list(self):
        assert not self.arg
        assert self.dest.name == 'dom0'

        pools = self.fire_event_for_filter(self.app.pools)

        return ''.join('{}\n'.format(pool) for pool in pools)

    @api('mgmt.pool.ListDrivers', no_payload=True)
    @asyncio.coroutine
    def pool_listdrivers(self):
        assert self.dest.name == 'dom0'
        assert not self.arg

        drivers = self.fire_event_for_filter(qubes.storage.pool_drivers())

        return ''.join('{} {}\n'.format(
            driver,
            ' '.join(qubes.storage.driver_parameters(driver)))
            for driver in drivers)

    @api('mgmt.pool.Info', no_payload=True)
    @asyncio.coroutine
    def pool_info(self):
        assert self.dest.name == 'dom0'
        assert self.arg in self.app.pools.keys()

        pool = self.app.pools[self.arg]

        self.fire_event_for_permission(pool=pool)

        return ''.join('{}={}\n'.format(prop, val)
            for prop, val in sorted(pool.config.items()))

    @api('mgmt.pool.Add')
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

    @api('mgmt.pool.Remove', no_payload=True)
    @asyncio.coroutine
    def pool_remove(self):
        assert self.dest.name == 'dom0'
        assert self.arg in self.app.pools.keys()

        self.fire_event_for_permission()

        self.app.remove_pool(self.arg)
        self.app.save()

    @api('mgmt.label.List', no_payload=True)
    @asyncio.coroutine
    def label_list(self):
        assert self.dest.name == 'dom0'
        assert not self.arg

        labels = self.fire_event_for_filter(self.app.labels.values())

        return ''.join('{}\n'.format(label.name) for label in labels)

    @api('mgmt.label.Get', no_payload=True)
    @asyncio.coroutine
    def label_get(self):
        assert self.dest.name == 'dom0'

        try:
            label = self.app.get_label(self.arg)
        except KeyError:
            raise qubes.exc.QubesValueError

        self.fire_event_for_permission(label=label)

        return label.color

    @api('mgmt.label.Index', no_payload=True)
    @asyncio.coroutine
    def label_index(self):
        assert self.dest.name == 'dom0'

        try:
            label = self.app.get_label(self.arg)
        except KeyError:
            raise qubes.exc.QubesValueError

        self.fire_event_for_permission(label=label)

        return str(label.index)

    @api('mgmt.label.Create')
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

    @api('mgmt.label.Remove', no_payload=True)
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

    @api('mgmt.vm.Start', no_payload=True)
    @asyncio.coroutine
    def vm_start(self):
        assert not self.arg
        self.fire_event_for_permission()
        yield from self.dest.start()

    @api('mgmt.vm.Shutdown', no_payload=True)
    @asyncio.coroutine
    def vm_shutdown(self):
        assert not self.arg
        self.fire_event_for_permission()
        yield from self.dest.shutdown()

    @api('mgmt.vm.Pause', no_payload=True)
    @asyncio.coroutine
    def vm_pause(self):
        assert not self.arg
        self.fire_event_for_permission()
        yield from self.dest.pause()

    @api('mgmt.vm.Unpause', no_payload=True)
    @asyncio.coroutine
    def vm_unpause(self):
        assert not self.arg
        self.fire_event_for_permission()
        yield from self.dest.unpause()

    @api('mgmt.vm.Kill', no_payload=True)
    @asyncio.coroutine
    def vm_kill(self):
        assert not self.arg
        self.fire_event_for_permission()
        yield from self.dest.kill()

    @api('mgmt.Events', no_payload=True)
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

    @api('mgmt.vm.feature.List', no_payload=True)
    @asyncio.coroutine
    def vm_feature_list(self):
        assert not self.arg
        features = self.fire_event_for_filter(self.dest.features.keys())
        return ''.join('{}\n'.format(feature) for feature in features)

    @api('mgmt.vm.feature.Get', no_payload=True)
    @asyncio.coroutine
    def vm_feature_get(self):
        # validation of self.arg done by qrexec-policy is enough

        self.fire_event_for_permission()
        try:
            value = self.dest.features[self.arg]
        except KeyError:
            raise qubes.exc.QubesFeatureNotFoundError(self.dest, self.arg)
        return value

    @api('mgmt.vm.feature.CheckWithTemplate', no_payload=True)
    @asyncio.coroutine
    def vm_feature_checkwithtemplate(self):
        # validation of self.arg done by qrexec-policy is enough

        self.fire_event_for_permission()
        try:
            value = self.dest.features.check_with_template(self.arg)
        except KeyError:
            raise qubes.exc.QubesFeatureNotFoundError(self.dest, self.arg)
        return value

    @api('mgmt.vm.feature.Remove', no_payload=True)
    @asyncio.coroutine
    def vm_feature_remove(self):
        # validation of self.arg done by qrexec-policy is enough

        self.fire_event_for_permission()
        try:
            del self.dest.features[self.arg]
        except KeyError:
            raise qubes.exc.QubesFeatureNotFoundError(self.dest, self.arg)
        self.app.save()

    @api('mgmt.vm.feature.Set')
    @asyncio.coroutine
    def vm_feature_set(self, untrusted_payload):
        # validation of self.arg done by qrexec-policy is enough
        value = untrusted_payload.decode('ascii', errors='strict')
        del untrusted_payload

        self.fire_event_for_permission(value=value)
        self.dest.features[self.arg] = value
        self.app.save()

    @api('mgmt.vm.Create.{endpoint}', endpoints=(ep.name
            for ep in pkg_resources.iter_entry_points(qubes.vm.VM_ENTRY_POINT)))
    @asyncio.coroutine
    def vm_create(self, endpoint, untrusted_payload=None):
        return self._vm_create(endpoint, allow_pool=False,
            untrusted_payload=untrusted_payload)

    @api('mgmt.vm.CreateInPool.{endpoint}', endpoints=(ep.name
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
            assert self.arg in self.app.domains
            kwargs['template'] = self.app.domains[self.arg]
        else:
            assert not self.arg

        for untrusted_param in untrusted_payload.decode('ascii',
                errors='strict').split(' '):
            untrusted_key, untrusted_value = untrusted_param.split('=', 1)
            if untrusted_key in kwargs:
                raise ProtocolError('duplicated parameters')

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
                    raise ProtocolError('duplicated pool parameter')
                pool = self.app.get_pool(untrusted_value)
            elif untrusted_key.startswith('pool:') and allow_pool:
                untrusted_volume = untrusted_key.split(':', 1)[1]
                # kind of ugly, but actual list of volumes is available only
                # after creating a VM
                assert untrusted_volume in ['root', 'private', 'volatile',
                    'kernel']
                volume = untrusted_volume
                if volume in pools:
                    raise ProtocolError(
                        'duplicated pool:{} parameter'.format(volume))
                pools[volume] = self.app.get_pool(untrusted_value)

            else:
                raise ProtocolError('Invalid param name')
        del untrusted_payload

        if 'name' not in kwargs or 'label' not in kwargs:
            raise ProtocolError('Missing name or label')

        if pool and pools:
            raise ProtocolError(
                'Only one of \'pool=\' and \'pool:volume=\' can be used')

        if kwargs['name'] in self.app.domains:
            raise qubes.exc.QubesValueError(
                'VM {} already exists'.format(kwargs['name']))

        self.fire_event_for_permission(pool=pool, pools=pools, **kwargs)

        vm = self.app.add_new_vm(vm_class, **kwargs)

        try:
            yield from vm.create_on_disk(pool=pool, pools=pools)
        except:
            del self.app.domains[vm]
            raise
        self.app.save()

    @api('mgmt.vm.Clone')
    @asyncio.coroutine
    def vm_clone(self, untrusted_payload):
        assert not self.arg

        assert untrusted_payload.startswith(b'name=')
        untrusted_name = untrusted_payload[5:].decode('ascii')
        qubes.vm.validate_name(None, None, untrusted_name)
        new_name = untrusted_name

        del untrusted_payload

        if new_name in self.app.domains:
            raise qubes.exc.QubesValueError('Already exists')

        self.fire_event_for_permission(new_name=new_name)

        src_vm = self.dest

        dst_vm = self.app.add_new_vm(src_vm.__class__, name=new_name)
        try:
            dst_vm.clone_properties(src_vm)
            # TODO: tags
            # TODO: features
            # TODO: firewall
            # TODO: persistent devices
            yield from dst_vm.clone_disk_files(src_vm)
        except:
            del self.app.domains[dst_vm]
            raise
        self.app.save()
