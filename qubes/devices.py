#
# The Qubes OS Project, https://www.qubes-os.org/
#
# Copyright (C) 2010-2016  Joanna Rutkowska <joanna@invisiblethingslab.com>
# Copyright (C) 2015-2016  Wojtek Porczyk <woju@invisiblethingslab.com>
# Copyright (C) 2016       Bahtiar `kalkin-` Gadimov <bahtiar@gadimov.de>
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

'''API for various types of devices.

Main concept is that some domain main
expose (potentially multiple) devices, which can be attached to other domains.
Devices can be of different classes (like 'pci', 'usb', etc). Each device
class is implemented by an extension.

Devices are identified by pair of (backend domain, `ident`), where `ident` is
:py:class:`str` and can contain only characters from `[a-zA-Z0-9._-]` set.

Such extension should provide:
 - `qubes.devices` endpoint - a class descendant from
 :py:class:`qubes.devices.DeviceInfo`, designed to hold device description (
 including class-specific properties)
 - handle `device-attach:class` and `device-detach:class` events for
 performing the attach/detach action; events are fired even when domain isn't
 running and extension should be prepared for this
 - handle `device-list:class` event - list devices exposed by particular
 domain; it should return list of appropriate DeviceInfo objects
 - handle `device-get:class` event - get one device object exposed by this
 domain of given identifier
 - handle `device-list-attached:class` event - list currently attached
 devices to this domain
'''

import qubes.utils

class DeviceNotAttached(qubes.exc.QubesException, KeyError):
    '''Trying to detach not attached device'''
    pass

class DeviceAlreadyAttached(qubes.exc.QubesException, KeyError):
    '''Trying to attach already attached device'''
    pass


class DeviceAssignment(object): # pylint: disable=too-few-public-methods
    ''' Maps a device to a frontend_domain. '''

    def __init__(self, backend_domain, ident, options=None, persistent=False,
            frontend_domain=None, devclass=None):
        self.backend_domain = backend_domain
        self.ident = ident
        self.options = options or {}
        self.persistent = persistent
        self.frontend_domain = frontend_domain
        self.devclass = devclass

    def __repr__(self):
        return "[%s]:%s" % (self.backend_domain, self.ident)

    def __hash__(self):
        # it's important to use the same hash as DeviceInfo
        return hash((self.backend_domain, self.ident))

    def __eq__(self, other):
        if not isinstance(self, other.__class__):
            return NotImplemented

        return self.backend_domain == other.backend_domain \
           and self.ident == other.ident

    def clone(self):
        '''Clone object instance'''
        return self.__class__(
            self.backend_domain,
            self.ident,
            self.options,
            self.persistent,
            self.frontend_domain,
            self.devclass,
        )

    @property
    def device(self):
        '''Get DeviceInfo object corresponding to this DeviceAssignment'''
        return self.backend_domain.devices[self.devclass][self.ident]


class DeviceCollection(object):
    '''Bag for devices.

    Used as default value for :py:meth:`DeviceManager.__missing__` factory.

    :param vm: VM for which we manage devices
    :param class_: device class

    This class emits following events on VM object:

        .. event:: device-attach:<class> (device)

            Fired when device is attached to a VM.

            :param device: :py:class:`DeviceInfo` object to be attached

        .. event:: device-pre-attach:<class> (device)

            Fired before device is attached to a VM

            :param device: :py:class:`DeviceInfo` object to be attached

        .. event:: device-detach:<class> (device)

            Fired when device is detached from a VM.

            :param device: :py:class:`DeviceInfo` object to be attached

        .. event:: device-pre-detach:<class> (device)

            Fired before device is detached from a VM

            :param device: :py:class:`DeviceInfo` object to be attached

        .. event:: device-list:<class>

            Fired to get list of devices exposed by a VM. Handlers of this
            event should return a list of py:class:`DeviceInfo` objects (or
            appropriate class specific descendant)

        .. event:: device-get:<class> (ident)

            Fired to get a single device, given by the `ident` parameter.
            Handlers of this event should either return appropriate object of
            :py:class:`DeviceInfo`, or :py:obj:`None`. Especially should not
            raise :py:class:`exceptions.KeyError`.

        .. event:: device-list-attached:<class> (persistent)

            Fired to get list of currently attached devices to a VM. Handlers
            of this event should return list of devices actually attached to
            a domain, regardless of its settings.

    '''

    def __init__(self, vm, class_):
        self._vm = vm
        self._class = class_
        self._set = PersistentCollection()

        self.devclass = qubes.utils.get_entry_point_one(
            'qubes.devices', self._class)

    def attach(self, device_assignment: DeviceAssignment):
        '''Attach (add) device to domain.

        :param DeviceInfo device: device object
        '''

        if not device_assignment.frontend_domain:
            device_assignment.frontend_domain = self._vm
        else:
            assert device_assignment.frontend_domain == self._vm, \
                "Trying to attach DeviceAssignment belonging to other domain"

        if device_assignment.devclass is None:
            device_assignment.devclass = self._class
        else:
            assert device_assignment.devclass == self._class, \
                "Trying to attach DeviceAssignment of a different device class"

        if not device_assignment.persistent and self._vm.is_halted():
            raise qubes.exc.QubesVMNotRunningError(self._vm,
                "Devices can only be attached  non-persistent to a running vm")
        device = device_assignment.device
        if device in self.assignments():
            raise DeviceAlreadyAttached(
                'device {!s} of class {} already attached to {!s}'.format(
                    device, self._class, self._vm))
        self._vm.fire_event_pre('device-pre-attach:'+self._class,
            device=device, options=device_assignment.options)
        if device_assignment.persistent:
            self._set.add(device_assignment)
        self._vm.fire_event('device-attach:' + self._class,
            device=device, options=device_assignment.options)

    def detach(self, device_assignment: DeviceAssignment):
        '''Detach (remove) device from domain.

        :param DeviceInfo device: device object
        '''

        if not device_assignment.frontend_domain:
            device_assignment.frontend_domain = self._vm

        if device_assignment.devclass is None:
            device_assignment.devclass = self._class
        else:
            assert device_assignment.devclass == self._class, \
                "Trying to attach DeviceAssignment of a different device class"

        if device_assignment in self._set and not self._vm.is_halted():
            raise qubes.exc.QubesVMNotHaltedError(self._vm,
                "Can not remove a persistent attachment from a non halted vm")
        if device_assignment not in self.assignments():
            raise DeviceNotAttached(
                'device {!s} of class {} not attached to {!s}'.format(
                    device_assignment.ident, self._class, self._vm))

        device = device_assignment.device
        self._vm.fire_event_pre('device-pre-detach:'+self._class, device=device)
        if device in self._set:
            device_assignment.persistent = True
            self._set.discard(device_assignment)

        self._vm.fire_event('device-detach:' + self._class, device=device)

    def attached(self):
        '''List devices which are (or may be) attached to this vm '''
        attached = self._vm.fire_event('device-list-attached:' + self._class)
        if attached:
            return [dev for dev, _ in attached]

        return []

    def persistent(self):
        ''' Devices persistently attached and safe to access before libvirt
            bootstrap.
        '''
        return [a.device for a in self._set]

    def assignments(self, persistent=None):
        '''List assignments for devices which are (or may be) attached to the
           vm.

        Devices may be attached persistently (so they are included in
        :file:`qubes.xml`) or not. Device can also be in :file:`qubes.xml`,
        but be temporarily detached.

        :param bool persistent: only include devices which are or are not
        attached persistently.
        '''

        devices = self._vm.fire_event('device-list-attached:' + self._class,
            persistent=persistent)
        result = set()
        for dev, options in devices:
            if dev in self._set and not persistent:
                continue
            elif dev in self._set:
                result.add(self._set.get(dev))
            elif dev not in self._set and persistent:
                continue
            else:
                result.add(
                    DeviceAssignment(
                        backend_domain=dev.backend_domain,
                        ident=dev.ident, options=options,
                        devclass=self._class,
                        frontend_domain=self._vm))
        if persistent is not False:
            result.update(self._set)
        return result

    def available(self):
        '''List devices exposed by this vm'''
        devices = self._vm.fire_event('device-list:' + self._class)
        return devices

    def __iter__(self):
        return iter(self.available())

    def __getitem__(self, ident):
        '''Get device object with given ident.

        :returns: py:class:`DeviceInfo`

        If domain isn't running, it is impossible to check device validity,
        so return UnknownDevice object. Also do the same for non-existing
        devices - otherwise it will be impossible to detach already
        disconnected device.

        :raises AssertionError: when multiple devices with the same ident are
        found
        '''
        dev = self._vm.fire_event('device-get:' + self._class, ident=ident)
        if dev:
            assert len(dev) == 1
            return dev[0]

        return UnknownDevice(self._vm, ident)


class DeviceManager(dict):
    '''Device manager that hold all devices by their classess.

    :param vm: VM for which we manage devices
    '''

    def __init__(self, vm):
        super(DeviceManager, self).__init__()
        self._vm = vm

    def __missing__(self, key):
        self[key] = DeviceCollection(self._vm, key)
        return self[key]


class DeviceInfo(object):
    ''' Holds all information about a device '''
    # pylint: disable=too-few-public-methods
    def __init__(self, backend_domain, ident, description=None,
                 frontend_domain=None, options=None, **kwargs):
        #: domain providing this device
        self.backend_domain = backend_domain
        #: device identifier (unique for given domain and device type)
        self.ident = ident
        # allow redefining those as dynamic properties in subclasses
        try:
            #: human readable description/name of the device
            self.description = description
        except AttributeError:
            pass
        try:
            #: (running) domain to which device is currently attached
            self.frontend_domain = frontend_domain
        except AttributeError:
            pass
        self.options = options or dict()
        self.data = kwargs

        if hasattr(self, 'regex'):
            # pylint: disable=no-member
            dev_match = self.regex.match(ident)
            if not dev_match:
                raise ValueError('Invalid device identifier: {!r}'.format(
                    ident))

            for group in self.regex.groupindex:
                setattr(self, group, dev_match.group(group))

    def __hash__(self):
        return hash((self.backend_domain, self.ident))

    def __eq__(self, other):
        return (
            self.backend_domain == other.backend_domain and
            self.ident == other.ident
        )

    def __str__(self):
        return '{!s}:{!s}'.format(self.backend_domain, self.ident)


class UnknownDevice(DeviceInfo):
    # pylint: disable=too-few-public-methods
    '''Unknown device - for example exposed by domain not running currently'''

    def __init__(self, backend_domain, ident, description=None,
            frontend_domain=None, **kwargs):
        if description is None:
            description = "Unknown device"
        super(UnknownDevice, self).__init__(backend_domain, ident, description,
            frontend_domain, **kwargs)


class PersistentCollection(object):

    ''' Helper object managing persistent `DeviceAssignment`s.
    '''

    def __init__(self):
        self._dict = {}

    def add(self, assignment: DeviceAssignment):
        ''' Add assignment to collection '''
        assert assignment.persistent and assignment.frontend_domain
        vm = assignment.backend_domain
        ident = assignment.ident
        key = (vm, ident)
        assert key not in self._dict

        self._dict[key] = assignment

    def discard(self, assignment):
        ''' Discard assignment from collection '''
        assert assignment.persistent and assignment.frontend_domain
        vm = assignment.backend_domain
        ident = assignment.ident
        key = (vm, ident)
        if key not in self._dict:
            raise KeyError
        del self._dict[key]

    def __contains__(self, device) -> bool:
        return (device.backend_domain, device.ident) in self._dict

    def get(self, device: DeviceInfo) -> DeviceAssignment:
        ''' Returns the corresponding `qubes.devices.DeviceAssignment` for the
            device. '''
        return self._dict[(device.backend_domain, device.ident)]

    def __iter__(self):
        return self._dict.values().__iter__()

    def __len__(self) -> int:
        return len(self._dict.keys())
