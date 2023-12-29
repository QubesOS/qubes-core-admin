#
# The Qubes OS Project, https://www.qubes-os.org/
#
# Copyright (C) 2010-2016  Joanna Rutkowska <joanna@invisiblethingslab.com>
# Copyright (C) 2015-2016  Wojtek Porczyk <woju@invisiblethingslab.com>
# Copyright (C) 2016       Bahtiar `kalkin-` Gadimov <bahtiar@gadimov.de>
#
# This library is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 2.1 of the License, or (at your option) any later version.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with this library; if not, see <https://www.gnu.org/licenses/>.
#

"""API for various types of devices.

Main concept is that some domain may
expose (potentially multiple) devices, which can be attached to other domains.
Devices can be of different buses (like 'pci', 'usb', etc.). Each device
bus is implemented by an extension.

Devices are identified by pair of (backend domain, `ident`), where `ident` is
:py:class:`str` and can contain only characters from `[a-zA-Z0-9._-]` set.

Such extension should:
 - provide `qubes.devices` endpoint - a class descendant from
   :py:class:`qubes.devices.DeviceInfo`, designed to hold device description
   (including bus-specific properties)
 - handle `device-attach:bus` and `device-detach:bus` events for
   performing the attach/detach action; events are fired even when domain isn't
   running and extension should be prepared for this; handlers for those events
   can be coroutines
 - handle `device-list:bus` event - list devices exposed by particular
   domain; it should return a list of appropriate DeviceInfo objects
 - handle `device-get:bus` event - get one device object exposed by this
   domain of given identifier
 - handle `device-list-attached:class` event - list devices currently attached
   to this domain
 - fire `device-list-change:class` event when a device list change is detected
   (new/removed device)

Note that device-listing event handlers cannot be asynchronous. This for
example means you cannot call qrexec service there. This is intentional to
keep device listing operation cheap. You need to design the extension to take
this into account (for example by using QubesDB).

Extension may use QubesDB watch API (QubesVM.watch_qdb_path(path), then handle
`domain-qdb-change:path`) to detect changes and fire
`device-list-change:class` event.
"""
import itertools
import base64
import sys
from enum import Enum
from typing import Optional, List, Type

import qubes.utils
from qubes.api import PermissionDenied


class DeviceNotAttached(qubes.exc.QubesException, KeyError):
    """Trying to detach not attached device"""


class DeviceAlreadyAttached(qubes.exc.QubesException, KeyError):
    """Trying to attach already attached device"""


class Device:
    def __init__(self, backend_domain, ident, devclass=None):
        self.__backend_domain = backend_domain
        self.__ident = ident
        self.__bus = devclass

    def __hash__(self):
        return hash((str(self.backend_domain), self.ident))

    def __eq__(self, other):
        return (
            self.backend_domain == other.backend_domain and
            self.ident == other.ident
        )

    def __lt__(self, other):
        if isinstance(other, Device):
            return (self.backend_domain, self.ident) < \
                   (other.backend_domain, other.ident)
        return NotImplemented

    def __repr__(self):
        return "[%s]:%s" % (self.backend_domain, self.ident)

    def __str__(self):
        return '{!s}:{!s}'.format(self.backend_domain, self.ident)

    @property
    def ident(self) -> str:
        """
        Immutable device identifier.

        Unique for given domain and device type.
        """
        return self.__ident

    @property
    def backend_domain(self) -> 'qubesadmin.vm.QubesVM':
        """ Which domain provides this device. (immutable)"""
        return self.__backend_domain

    @property
    def devclass(self) -> Optional[str]:
        """ Immutable* Device class such like: 'usb', 'pci' etc.

        * see `@devclass.setter`
        """
        return self.__bus

    @devclass.setter
    def devclass(self, devclass: str):
        """ Once a value is set, it should not be overridden.

        However, if it has not been set, i.e., the value is `None`,
        we can override it."""
        if self.__bus != None:
            raise TypeError("Attribute devclass is immutable")
        self.__bus = devclass


class DeviceInterface(Enum):
    # USB interfaces:
    # https://www.usb.org/defined-class-codes#anchor_BaseClass03h
    Other = "******"
    USB_Audio = "01****"
    USB_CDC = "02****"  # Communications Device Class
    USB_HID = "03****"
    USB_HID_Keyboard = "03**01"
    USB_HID_Mouse = "03**02"
    # USB_Physical = "05****"
    # USB_Still_Imaging = "06****"  # Camera
    USB_Printer = "07****"
    USB_Mass_Storage = "08****"
    USB_Hub = "09****"
    USB_CDC_Data = "0a****"
    USB_Smart_Card = "0b****"
    # USB_Content_Security = "0d****"
    USB_Video = "0e****"  # Video Camera
    # USB_Personal_Healthcare = "0f****"
    USB_Audio_Video = "10****"
    # USB_Billboard = "11****"
    # USB_C_Bridge = "12****"
    # and more...

    @staticmethod
    def from_str(interface_encoding: str) -> 'DeviceInterface':
        result = DeviceInterface.Other
        best_score = 0

        for interface in DeviceInterface:
            pattern = interface.value
            score = 0
            for t, p in zip(interface_encoding, pattern):
                if t == p:
                    score += 1
                elif p != "*":
                    score = -1  # inconsistent with pattern
                    break

            if score > best_score:
                best_score = score
                result = interface

        return result


class DeviceInfo(Device):
    """ Holds all information about a device """

    # pylint: disable=too-few-public-methods
    def __init__(
            self,
            backend_domain: 'qubes.vm.qubesvm.QubesVM',  # TODO
            ident: str,
            devclass: Optional[str] = None,
            vendor: Optional[str] = None,
            product: Optional[str] = None,
            manufacturer: Optional[str] = None,
            name: Optional[str] = None,
            serial: Optional[str] = None,
            interfaces: Optional[List[DeviceInterface]] = None,
            parent: Optional[Device] = None,
            **kwargs
    ):
        super().__init__(backend_domain, ident, devclass)

        self._vendor = vendor
        self._product = product
        self._manufacturer = manufacturer
        self._name = name
        self._serial = serial
        self._interfaces = interfaces
        self._parent = parent

        self.data = kwargs

    @property
    def vendor(self) -> str:
        """
        Device vendor name from local database.

        Could be empty string or "unknown".

        Override this method to return proper name from `/usr/share/hwdata/*`.
        """
        if not self._vendor:
            return "unknown"
        return self._vendor

    @property
    def product(self) -> str:
        """
        Device name from local database.

        Could be empty string or "unknown".

        Override this method to return proper name from `/usr/share/hwdata/*`.
        """
        if not self._product:
            return "unknown"
        return self._product

    @property
    def manufacturer(self) -> str:
        """
        The name of the manufacturer of the device introduced by device itself.

        Could be empty string or "unknown".

        Override this method to return proper name directly from device itself.
        """
        if not self._manufacturer:
            return "unknown"
        return self._manufacturer

    @property
    def name(self) -> str:
        """
        The name of the device it introduced itself with.

        Could be empty string or "unknown".

        Override this method to return proper name directly from device itself.
        """
        if not self._name:
            return "unknown"
        return self._name

    @property
    def serial(self) -> str:
        """
        The serial number of the device it introduced itself with.

        Could be empty string or "unknown".

        Override this method to return proper name directly from device itself.
        """
        if not self._serial:
            return "unknown"
        return self._serial

    @property
    def description(self) -> str:
        """
        Short human-readable description.

        For unknown device returns `unknown device (unknown vendor)`.
        For unknown USB device returns `unknown usb device (unknown vendor)`.
        For unknown USB device with known serial number returns
            `<serial> (unknown vendor)`.
        """
        if self.product and self.product != "unknown":
            prod = self.product
        elif self.name and self.name != "unknown":
            prod = self.name
        elif self.serial and self.serial != "unknown":
            prod = self.serial
        elif self.parent_device is not None:
            return f"partition of {self.parent_device}"
        else:
            prod = f"unknown {self.devclass if self.devclass else ''} device"

        if self.vendor and self.vendor != "unknown":
            vendor = self.vendor
        elif self.manufacturer and self.manufacturer != "unknown":
            vendor = self.manufacturer
        else:
            vendor = "unknown vendor"

        return f"{prod} ({vendor})"

    @property
    def interfaces(self) -> List[DeviceInterface]:
        """
        Non-empty list of device interfaces.

        Every device should have at least one interface.
        """
        if not self._interfaces:
            return [DeviceInterface.Other]
        return self._interfaces

    @property
    def parent_device(self) -> Optional['DeviceInfo']:
        """
        The parent device if any.

        If the device is part of another device (e.g. it's a single
        partition of an usb stick), the parent device id should be here.
        """
        if self._parent is None:
            return None
        return self.backend_domain.devices.get(
            self._parent.devclass, {}).get(self._parent.ident, None)

    @property
    def subdevices(self) -> List['DeviceInfo']:
        """
        The list of children devices if any.

        If the device has subdevices (e.g. partitions of an usb stick),
        the subdevices id should be here.
        """
        return [dev for dev in self.backend_domain.devices[self.devclass]
                if dev.parent_device.ident == self.ident]

    # @property
    # def port_id(self) -> str:
    #     """
    #     Which port the device is connected to.
    #     """
    #     return self.ident  # TODO: ???

    @property
    def attachments(self) -> List['DeviceAssignment']:
        """
        Device attachments
        """
        return []  # TODO

    def serialize(self) -> bytes:
        """
        Serialize object to be transmitted via Qubes API.
        """
        # 'backend_domain', 'interfaces', 'data', 'parent_device'
        # are not string, so they need special treatment
        default_attrs = {
            'ident', 'devclass', 'vendor', 'product', 'manufacturer', 'name',
            'serial'}
        properties = b' '.join(
            base64.b64encode(f'{prop}={value!s}'.encode('ascii'))
            for prop, value in (
                (key, getattr(self, key)) for key in default_attrs)
        )

        backend_domain_name = self.backend_domain.name
        backend_domain_prop = (b'backend_domain=' +
                               backend_domain_name.encode('ascii'))
        properties += b' ' + base64.b64encode(backend_domain_prop)

        interfaces = ''.join(ifc.value for ifc in self.interfaces)
        interfaces_prop = b'interfaces=' + str(interfaces).encode('ascii')
        properties += b' ' + base64.b64encode(interfaces_prop)

        if self.parent_device is not None:
            parent_prop = b'parent=' + self.parent_device.ident.encode('ascii')
            properties += b' ' + base64.b64encode(parent_prop)

        data = b' '.join(
            base64.b64encode(f'_{prop}={value!s}'.encode('ascii'))
            for prop, value in ((key, self.data[key]) for key in self.data)
        )
        if data:
            properties += b' ' + data

        return properties

    @classmethod
    def deserialize(
            cls,
            serialization: bytes,
            expected_backend_domain: 'qubes.vm.qubesvm.QubesVM',
            expected_devclass: Optional[str] = None,
    ) -> 'DeviceInfo':
        try:
            result = DeviceInfo._deserialize(
                cls, serialization, expected_backend_domain, expected_devclass)
        except Exception as exc:
            print(exc, file=sys.stderr)  # TODO
            ident = serialization.split(b' ')[0].decode(
                'ascii', errors='ignore')
            result = UnknownDevice(
                backend_domain=expected_backend_domain,
                ident=ident,
                devclass=expected_devclass,
            )
        return result

    @staticmethod
    def _deserialize(
            cls: Type,
            serialization: bytes,
            expected_backend_domain: 'qubes.vm.qubesvm.QubesVM',
            expected_devclass: Optional[str] = None,
    ) -> 'DeviceInfo':
        properties_str = [
            base64.b64decode(line).decode('ascii', errors='ignore')
            for line in serialization.split(b' ')[1:]]

        properties = dict()
        for line in properties_str:
            key, _, param = line.partition("=")
            if key.startswith("_"):
                properties[key[1:]] = param
            else:
                properties[key] = param

        if properties['backend_domain'] != expected_backend_domain.name:
            raise ValueError("TODO")  # TODO
        properties['backend_domain'] = expected_backend_domain
        # if expected_devclass and properties['devclass'] != expected_devclass:
        #     raise ValueError("TODO")  # TODO

        interfaces = properties['interfaces']
        interfaces = [
            DeviceInterface.from_str(interfaces[i:i + 6])
            for i in range(0, len(interfaces), 6)]
        properties['interfaces'] = interfaces

        if 'parent' in properties:
            properties['parent'] = Device(
                backend_domain=expected_backend_domain,
                ident=properties['parent']
            )

        return cls(**properties)

    @property
    def frontend_domain(self):
        return self.data.get("frontend_domain", None)


class UnknownDevice(DeviceInfo):
    # pylint: disable=too-few-public-methods
    """Unknown device - for example exposed by domain not running currently"""

    def __init__(self, backend_domain, devclass, ident, **kwargs):
        super().__init__(backend_domain, ident, devclass=devclass, **kwargs)


class DeviceAssignment(Device):  # pylint: disable=too-few-public-methods
    """ Maps a device to a frontend_domain. """

    def __init__(
        self, backend_domain, ident, options=None, persistent=False, bus=None
    ):
        super().__init__(backend_domain, ident, bus)  # TODO
        self.options = options or {}
        self.persistent = persistent  # TODO

    def clone(self):
        """Clone object instance"""
        return self.__class__(
            self.backend_domain,
            self.ident,
            self.options,
            self.persistent,
            self.devclass,
        )

    @property
    def device(self) -> DeviceInfo:
        """Get DeviceInfo object corresponding to this DeviceAssignment"""
        return self.backend_domain.devices[self.devclass][self.ident]


class DeviceCollection:
    """Bag for devices.

    Used as default value for :py:meth:`DeviceManager.__missing__` factory.

    :param vm: VM for which we manage devices
    :param bus: device bus

    This class emits following events on VM object:

        .. event:: device-added:<class> (device)

            Fired when new device is discovered to a VM.

        .. event:: device-attach:<class> (device, options)

            Fired when device is attached to a VM.

            Handler for this event may be asynchronous.

            :param device: :py:class:`DeviceInfo` object to be attached
            :param options: :py:class:`dict` of attachment options

        .. event:: device-pre-attach:<class> (device)

            Fired before device is attached to a VM

            Handler for this event may be asynchronous.

            :param device: :py:class:`DeviceInfo` object to be attached

        .. event:: device-detach:<class> (device)

            Fired when device is detached from a VM.

            Handler for this event can be asynchronous (a coroutine).

            :param device: :py:class:`DeviceInfo` object to be attached

        .. event:: device-pre-detach:<class> (device)

            Fired before device is detached from a VM

            Handler for this event can be asynchronous (a coroutine).

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

    """

    def __init__(self, vm, bus):
        self._vm = vm
        self._bus = bus
        self._set = PersistentCollection()  # TODO

        self.devclass = qubes.utils.get_entry_point_one(
            'qubes.devices', self._bus)

    async def attach(self, device_assignment: DeviceAssignment):
        '''Attach (add) device to domain.

        :param DeviceInfo device: device object
        '''

        if device_assignment.devclass is None:
            device_assignment.devclass = self._bus
        elif device_assignment.devclass != self._bus:
            raise ValueError(
                'Trying to attach DeviceAssignment of a different device class')

        if not device_assignment.persistent and self._vm.is_halted():  # TODO
            raise qubes.exc.QubesVMNotRunningError(self._vm,
                "VM not running, can only attach device with persistent flag")
        device = device_assignment.device
        if device in self.assignments():
            raise DeviceAlreadyAttached(
                'device {!s} of class {} already attached to {!s}'.format(
                    device, self._bus, self._vm))
        await self._vm.fire_event_async('device-pre-attach:' + self._bus,
            pre_event=True,
            device=device, options=device_assignment.options)
        if device_assignment.persistent:
            self._set.add(device_assignment)
        await self._vm.fire_event_async('device-attach:' + self._bus,
            device=device, options=device_assignment.options)

    def load_persistent(self, device_assignment: DeviceAssignment):
        '''Load DeviceAssignment retrieved from qubes.xml

        This can be used only for loading qubes.xml, when VM events are not
        enabled yet.
        '''
        assert not self._vm.events_enabled
        assert device_assignment.persistent
        device_assignment.devclass = self._bus
        self._set.add(device_assignment)

    def update_persistent(self, device: DeviceInfo, persistent: bool):
        '''Update `persistent` flag of already attached device.
        '''

        if self._vm.is_halted():
            raise qubes.exc.QubesVMNotStartedError(self._vm,
                'VM must be running to modify device persistence flag')
        assignments = [a for a in self.assignments() if a.device == device]
        if not assignments:
            raise qubes.exc.QubesValueError('Device not assigned')
        assert len(assignments) == 1
        assignment = assignments[0]

        # be careful to use already present assignment, not the provided one
        # - to not change options as a side effect
        if persistent and device not in self._set:
            assignment.persistent = True
            self._set.add(assignment)
        elif not persistent and device in self._set:
            self._set.discard(assignment)

    async def detach(self, device_assignment: DeviceAssignment):
        '''Detach (remove) device from domain.

        :param DeviceInfo device: device object
        '''

        if device_assignment.devclass is None:
            device_assignment.devclass = self._bus
        else:
            assert device_assignment.devclass == self._bus, \
                "Trying to attach DeviceAssignment of a different device class"

        if device_assignment in self._set and not self._vm.is_halted():
            raise qubes.exc.QubesVMNotHaltedError(self._vm,
                "Can not remove a persistent attachment from a non halted vm")
        if device_assignment not in self.assignments():
            raise DeviceNotAttached(
                'device {!s} of class {} not attached to {!s}'.format(
                    device_assignment.ident, self._bus, self._vm))

        device = device_assignment.device
        await self._vm.fire_event_async('device-pre-detach:' + self._bus,
            pre_event=True, device=device)
        if device in self._set:
            device_assignment.persistent = True
            self._set.discard(device_assignment)

        await self._vm.fire_event_async('device-detach:' + self._bus,
            device=device)

    def attached(self):
        '''List devices which are (or may be) attached to this vm '''
        attached = self._vm.fire_event('device-list-attached:' + self._bus,
            persistent=None)
        if attached:
            return [dev for dev, _ in attached]

        return []

    def persistent(self):
        ''' Devices persistently attached and safe to access before libvirt
            bootstrap.
        '''
        return [a.device for a in self._set]

    def assignments(self, persistent: Optional[bool]=None):
        '''List assignments for devices which are (or may be) attached to the
           vm.

        Devices may be attached persistently (so they are included in
        :file:`qubes.xml`) or not. Device can also be in :file:`qubes.xml`,
        but be temporarily detached.

        :param Optional[bool] persistent: only include devices which are or are
        not attached persistently.
        '''

        try:
            devices = self._vm.fire_event('device-list-attached:' + self._bus,
                persistent=persistent)
        except Exception:  # pylint: disable=broad-except
            self._vm.log.exception('Failed to list {} devices'.format(
                self._bus))
            if persistent is True:
                # don't break app.save()
                return list(self._set)
            raise
        result = []
        if persistent is not False:  # None or True
            result.extend(self._set)
        if not persistent:  # None or False
            for dev, options in devices:
                if dev not in self._set:
                    result.append(
                        DeviceAssignment(
                            backend_domain=dev.backend_domain,
                            ident=dev.ident, options=options,
                            bus=self._bus))
        return result

    def available(self):
        '''List devices exposed by this vm'''
        devices = self._vm.fire_event('device-list:' + self._bus)
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
        dev = self._vm.fire_event('device-get:' + self._bus, ident=ident)
        if dev:
            assert len(dev) == 1
            return dev[0]

        return UnknownDevice(self._vm, ident)


class DeviceManager(dict):
    '''Device manager that hold all devices by their classes.

    :param vm: VM for which we manage devices
    '''

    def __init__(self, vm):
        super().__init__()
        self._vm = vm

    def __missing__(self, key):
        self[key] = DeviceCollection(self._vm, key)
        return self[key]


class UnknownDevice(DeviceInfo):
    # pylint: disable=too-few-public-methods
    '''Unknown device - for example exposed by domain not running currently'''

    def __init__(self, backend_domain, ident, description=None,
            frontend_domain=None):
        if description is None:
            description = "Unknown device"
        super().__init__(backend_domain, ident, description, frontend_domain)


class PersistentCollection:

    ''' Helper object managing persistent `DeviceAssignment`s.
    '''

    def __init__(self):
        self._dict = {}

    def add(self, assignment: DeviceAssignment):
        ''' Add assignment to collection '''
        assert assignment.persistent
        vm = assignment.backend_domain
        ident = assignment.ident
        key = (vm, ident)
        assert key not in self._dict

        self._dict[key] = assignment

    def discard(self, assignment):
        ''' Discard assignment from collection '''
        assert assignment.persistent
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
