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
import base64
import itertools
import sys
from enum import Enum
from typing import Optional, List, Type, Dict, Any, Iterable

import qubes.utils


class DeviceNotAttached(qubes.exc.QubesException, KeyError):
    """
    Trying to detach not attached device.
    """


class DeviceNotAssigned(qubes.exc.QubesException, KeyError):
    """
    Trying to unassign not assigned device.
    """


class DeviceAlreadyAttached(qubes.exc.QubesException, KeyError):
    """
    Trying to attach already attached device.
    """


class DeviceAlreadyAssigned(qubes.exc.QubesException, KeyError):
    """
    Trying to assign already assigned device.
    """


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
            return (self.backend_domain.name, self.ident) < \
                   (other.backend_domain.name, other.ident)
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
    def backend_domain(self) -> 'qubes.vm.BaseVM':
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


class DeviceCategory(Enum):
    """
    Category of peripheral device.

    Arbitrarily selected interfaces that are important to users,
    thus deserving special recognition such as a custom icon, etc.
    """
    Other = "*******"

    Communication = ("u02****", "p07****")  # eg. modems
    Input = ("u03****", "p09****")  # HID etc.
    Keyboard = ("u03**01", "p0900**")
    Mouse = ("u03**02", "p0902**")
    Printer = ("u07****",)
    Scanner = ("p0903**",)
    # Multimedia = Audio, Video, Displays etc.
    Microphone = ("m******",)
    Multimedia = ("u01****", "u0e****", "u06****", "u10****", "p03****",
                  "p04****")
    Wireless = ("ue0****", "p0d****")
    Bluetooth = ("ue00101", "p0d11**")
    Mass_Data = ("b******", "u08****", "p01****")
    Network = ("p02****",)
    Memory = ("p05****",)
    PCI_Bridge = ("p06****",)
    Docking_Station = ("p0a****",)
    Processor = ("p0b****", "p40****")
    PCI_Serial_Bus = ("p0c****",)
    PCI_USB = ("p0c03**",)

    @staticmethod
    def from_str(interface_encoding: str) -> 'DeviceCategory':
        result = DeviceCategory.Other
        if len(interface_encoding) != len(DeviceCategory.Other.value):
            return result
        best_score = 0

        for interface in DeviceCategory:
            for pattern in interface.value:
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


class DeviceInterface:
    """
    Peripheral device interface wrapper.
    """

    def __init__(self, interface_encoding: str, devclass: Optional[str] = None):
        ifc_padded = interface_encoding.ljust(6, '*')
        if devclass:
            if len(ifc_padded) > 6:
                print(
                    f"{interface_encoding=} is too long "
                    f"(is {len(interface_encoding)}, expected max. 6) "
                    f"for given {devclass=}",
                    file=sys.stderr
                )
            ifc_full = devclass[0] + ifc_padded
        else:
            known_devclasses = {
                'p': 'pci', 'u': 'usb', 'b': 'block', 'm': 'mic'}
            devclass = known_devclasses.get(interface_encoding[0], None)
            if len(ifc_padded) > 7:
                print(
                    f"{interface_encoding=} is too long "
                    f"(is {len(interface_encoding)}, expected max. 7)",
                    file=sys.stderr
                )
                ifc_full = ifc_padded
            elif len(ifc_padded) == 6:
                ifc_full = ' ' + ifc_padded
            else:
                ifc_full = ifc_padded

        self._devclass = devclass
        self._interface_encoding = ifc_full
        self._category = DeviceCategory.from_str(self._interface_encoding)

    @property
    def devclass(self) -> Optional[str]:
        """ Immutable Device class such like: 'usb', 'pci' etc. """
        return self._devclass

    @property
    def category(self) -> DeviceCategory:
        """ Immutable Device category such like: 'Mouse', 'Mass_Data' etc. """
        return self._category

    @classmethod
    def unknown(cls) -> 'DeviceInterface':
        """ Value for unknown device interface. """
        return cls(" ******")

    def __repr__(self):
        return self._interface_encoding

    def __str__(self):
        if self.devclass == "block":
            return "Block device"
        if self.devclass in ("usb", "pci"):
            result = self._load_classes(self.devclass).get(
                self._interface_encoding[1:], None)
            if result is None:
                result = self._load_classes(self.devclass).get(
                    self._interface_encoding[1:-2] + '**', None)
            if result is None:
                result = self._load_classes(self.devclass).get(
                    self._interface_encoding[1:-4] + '****', None)
            if result is None:
                result = f"Unclassified {self.devclass} device"
            return result
        if self.devclass == 'mic':
            return "Microphone"
        return repr(self)

    @staticmethod
    def _load_classes(bus: str):
        """
        List of known device classes, subclasses and programming interfaces.
        """
        # Syntax:
        # C class       class_name
        #       subclass        subclass_name           <-- single tab
        #               prog-if  prog-if_name   <-- two tabs
        result = {}
        with open(f'/usr/share/hwdata/{bus}.ids',
                  encoding='utf-8', errors='ignore') as pciids:
            class_id = None
            subclass_id = None
            for line in pciids.readlines():
                line = line.rstrip()
                if line.startswith('\t\t') and class_id and subclass_id:
                    (progif_id, _, progif_name) = line[2:].split(' ', 2)
                    result[class_id + subclass_id + progif_id] = \
                        f"{class_name}: {subclass_name} ({progif_name})"
                elif line.startswith('\t') and class_id:
                    (subclass_id, _, subclass_name) = line[1:].split(' ', 2)
                    # store both prog-if specific entry and generic one
                    result[class_id + subclass_id + '**'] = \
                        f"{class_name}: {subclass_name}"
                elif line.startswith('C '):
                    (_, class_id, _, class_name) = line.split(' ', 3)
                    result[class_id + '****'] = class_name
                    subclass_id = None

        return result


class DeviceInfo(Device):
    """ Holds all information about a device """

    # pylint: disable=too-few-public-methods
    def __init__(
            self,
            backend_domain: 'qubes.vm.BaseVM',
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
            return f"sub-device of {self.parent_device}"
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
            return [DeviceInterface.unknown()]
        return self._interfaces

    @property
    def parent_device(self) -> Optional[Device]:
        """
        The parent device if any.

        If the device is part of another device (e.g. it's a single
        partition of an usb stick), the parent device id should be here.
        """
        return self._parent

    @property
    def subdevices(self) -> List['DeviceInfo']:
        """
        The list of children devices if any.

        If the device has subdevices (e.g. partitions of an usb stick),
        the subdevices id should be here.
        """
        return [dev for dev in self.backend_domain.devices[self.devclass]
                if dev.parent_device.ident == self.ident]

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

        interfaces = ''.join(repr(ifc) for ifc in self.interfaces)
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
            expected_backend_domain: 'qubes.vm.BaseVM',
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
            expected_backend_domain: 'qubes.vm.BaseVM',
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
            DeviceInterface(interfaces[i:i + 7])
            for i in range(0, len(interfaces), 7)]
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

    def __init__(self, backend_domain, ident, *, devclass, **kwargs):
        super().__init__(backend_domain, ident, devclass=devclass, **kwargs)


class DeviceAssignment(Device):
    """ Maps a device to a frontend_domain.

    There are 3 flags `attached`, `automatically_attached` and `required`.
    The meaning of valid combinations is as follows:
    1. (True, False, False) -> domain is running, device is manually attached
                               and could be manually detach any time.
    2. (True, True, False)  -> domain is running, device is attached
                               and could be manually detach any time (see 4.),
                               but in the future will be auto-attached again.
    3. (True, True, True)   -> domain is running, device is attached
                               and couldn't be detached.
    4. (False, Ture, False) -> device is assigned to domain, but not attached
                               because either domain is halted
                               or device manually detached.
    5. (False, True, True)  -> domain is halted, device assigned to domain
                               and required to start domain.
    """

    def __init__(self, backend_domain, ident, options=None,
                 frontend_domain=None, devclass=None,
                 required=False, attach_automatically=False):
        super().__init__(backend_domain, ident, devclass)
        self.__options = options or {}
        self.__required = required
        self.__attach_automatically = attach_automatically
        self.__frontend_domain = frontend_domain

    def clone(self):
        """Clone object instance"""
        return self.__class__(
            backend_domain=self.backend_domain,
            ident=self.ident,
            options=self.options,
            required=self.required,
            attach_automatically=self.attach_automatically,
            frontend_domain=self.frontend_domain,
            devclass=self.devclass,
        )

    @property
    def device(self) -> DeviceInfo:
        """Get DeviceInfo object corresponding to this DeviceAssignment"""
        return self.backend_domain.devices[self.devclass][self.ident]

    @property
    def frontend_domain(self) -> Optional['qubes.vm.qubesvm.QubesVM']:
        """ Which domain the device is attached to. """
        return self.__frontend_domain

    @frontend_domain.setter
    def frontend_domain(
            self, frontend_domain: Optional['qubes.vm.qubesvm.QubesVM']
    ):
        """ Which domain the device is attached to. """
        self.__frontend_domain = frontend_domain

    @property
    def attached(self) -> bool:
        """
        Is the device already attached to the fronted domain?
        """
        return (self.frontend_domain is not None
                and self.frontend_domain.is_running())

    @property
    def required(self) -> bool:
        """
        Is the presence of this device required for the domain to start? If yes,
        it will be attached automatically.
        """
        return self.__required

    @required.setter
    def required(self, required: bool):
        self.__required = required

    @property
    def attach_automatically(self) -> bool:
        """
        Should this device automatically connect to the frontend domain when
        available and not connected to other qubes?
        """
        return self.__attach_automatically

    @attach_automatically.setter
    def attach_automatically(self, attach_automatically: bool):
        self.__attach_automatically = attach_automatically

    @property
    def options(self) -> Dict[str, Any]:
        """ Device options (same as in the legacy API). """
        return self.__options

    @options.setter
    def options(self, options: Optional[Dict[str, Any]]):
        """ Device options (same as in the legacy API). """
        self.__options = options or {}


class DeviceCollection:
    """Bag for devices.

    Used as default value for :py:meth:`DeviceManager.__missing__` factory.

    :param vm: VM for which we manage devices
    :param bus: device bus

    This class emits following events on VM object:  # TODO pre-assign, assign, pre-unassign, unassign

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

        .. event:: device-list-attached:<class>

            Fired to get list of currently attached devices to a VM. Handlers
            of this event should return list of devices actually attached to
            a domain, regardless of its settings.

    """

    def __init__(self, vm, bus):
        self._vm = vm
        self._bus = bus
        self._set = AssignedCollection()

        self.devclass = qubes.utils.get_entry_point_one(
            'qubes.devices', self._bus)

    async def attach(self, device_assignment: DeviceAssignment):
        """
        Attach device to domain.
        """

        if device_assignment.devclass is None:
            device_assignment.devclass = self._bus
        elif device_assignment.devclass != self._bus:
            raise ValueError(
                'Trying to attach DeviceAssignment of a different device class')

        if self._vm.is_halted():
            raise qubes.exc.QubesVMNotRunningError(
                self._vm,"VM not running, cannot attach device,"
                " did you mean `assign`?")
        device = device_assignment.device
        if device in self.get_attached_devices():
            raise DeviceAlreadyAttached(
                'device {!s} of class {} already attached to {!s}'.format(
                    device, self._bus, self._vm))
        await self._vm.fire_event_async(
            'device-pre-attach:' + self._bus,
            pre_event=True, device=device, options=device_assignment.options)

        await self._vm.fire_event_async(
            'device-attach:' + self._bus,
            device=device, options=device_assignment.options)

    async def assign(self, device_assignment: DeviceAssignment):
        """
        Assign device to domain.
        """
        if device_assignment.devclass is None:
            device_assignment.devclass = self._bus
        elif device_assignment.devclass != self._bus:
            raise ValueError(
                'Trying to assign DeviceAssignment of a different device class')

        device = device_assignment.device
        if device in self.get_assigned_devices():
            raise DeviceAlreadyAssigned(
                'device {!s} of class {} already assigned to {!s}'.format(
                    device, self._bus, self._vm))

        # TODO: check if needed
        await self._vm.fire_event_async(
            'device-pre-assign:' + self._bus,
            pre_event=True, device=device, options=device_assignment.options)

        self._set.add(device_assignment)

        await self._vm.fire_event_async(
            'device-assign:' + self._bus,
            device=device, options=device_assignment.options)

    def load_assignment(self, device_assignment: DeviceAssignment):
        """Load DeviceAssignment retrieved from qubes.xml

        This can be used only for loading qubes.xml, when VM events are not
        enabled yet.
        """
        assert not self._vm.events_enabled
        assert device_assignment.attach_automatically
        device_assignment.devclass = self._bus
        self._set.add(device_assignment)

    async def update_assignment(
            self, device: DeviceInfo, required: Optional[bool]):
        """
        Update assignment of already attached device.

        :param DeviceInfo device: device for which change required flag
        :param bool required: new assignment:
                              `None` -> unassign device from qube
                              `False` -> device will be auto-attached to qube
                              `True` -> device is required to start qube
        """
        if self._vm.is_halted():
            raise qubes.exc.QubesVMNotStartedError(
                self._vm,
                'VM must be running to modify device assignment'
            )
        assignments = [a for a in self.get_assigned_devices()
                       if a.device == device]
        if not assignments:
            raise qubes.exc.QubesValueError('Device not assigned')
        assert len(assignments) == 1
        assignment = assignments[0]

        # be careful to use already present assignment, not the provided one
        # - to not change options as a side effect
        if required is not None:
            if assignment.required == required:
                return

            assignment.required = required
            await self._vm.fire_event_async(
                'device-assignment-changed:' + self._bus, device=device)
        else:
            await self.detach(assignment)

    async def detach(self, device_assignment: DeviceAssignment):  # TODO: argument should be just device
        """
        Detach device from domain.
        """
        for assignment in self.get_attached_devices():
            if device_assignment == assignment:
                # load all options
                device_assignment = assignment
                break
        else:
            raise DeviceNotAssigned(
                f'device {device_assignment.ident!s} of class {self._bus} not '
                f'attached to {self._vm!s}')

        if device_assignment.required and not self._vm.is_halted():
            raise qubes.exc.QubesVMNotHaltedError(
                self._vm,
                "Can not detach a required device from a non halted qube. "
                "You need to unassign device first.")

        device = device_assignment.device
        await self._vm.fire_event_async(
            'device-pre-detach:' + self._bus, pre_event=True, device=device)

        await self._vm.fire_event_async(
            'device-detach:' + self._bus, device=device)

    async def unassign(self, device_assignment: DeviceAssignment):
        """
        Unassign device from domain.
        """
        for assignment in self.get_assigned_devices():
            if device_assignment == assignment:
                # load all options
                device_assignment = assignment
                break
        else:
            raise DeviceNotAssigned(
                f'device {device_assignment.ident!s} of class {self._bus} not '
                f'assigned to {self._vm!s}')

        if not self._vm.is_halted():
            raise qubes.exc.QubesVMNotHaltedError(
                self._vm,
                "Can not remove an assignment from a non halted qube.")

        device = device_assignment.device
        # TODO: check if needed
        await self._vm.fire_event_async(
            'device-pre-unassign:' + self._bus, pre_event=True, device=device)

        self._set.discard(device_assignment)

        await self._vm.fire_event_async(
            'device-unassign:' + self._bus, device=device)

    def get_dedicated_devices(self) -> Iterable[DeviceAssignment]:
        """
        List devices which are attached or assigned to this vm.
        """
        dedicated = {dev for dev in itertools.chain(
            self.get_attached_devices(), self.get_assigned_devices())}
        for dev in dedicated:
            yield dev

    def get_attached_devices(self) -> Iterable[DeviceAssignment]:
        """
        List devices which are attached to this vm.
        """
        attached = self._vm.fire_event('device-list-attached:' + self._bus)
        for dev, options in attached:
            for assignment in self._set:
                if dev == assignment:
                    yield assignment
                    break
            else:
                yield DeviceAssignment(
                    backend_domain=dev.backend_domain,
                    ident=dev.ident,
                    options=options,
                    frontend_domain=dev.frontend_domain,
                    devclass=dev.devclass,
                    attach_automatically=False,
                    required=False,
                )

    def get_assigned_devices(
            self, required_only: bool = False
    ) -> Iterable[DeviceAssignment]:
        """
        Devices assigned to this vm (included in :file:`qubes.xml`).

        Safe to access before libvirt bootstrap.
        """
        for dev in self._set:
            if required_only and not dev.required:
                continue
            yield dev

    def get_exposed_devices(self) -> Iterable[DeviceInfo]:
        """
        List devices exposed by this vm.
        """
        devices = self._vm.fire_event('device-list:' + self._bus)
        for device in devices:
            yield device

    __iter__ = get_exposed_devices

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

        return UnknownDevice(self._vm, ident, devclass=self._bus)


class DeviceManager(dict):
    """
    Device manager that hold all devices by their classes.

    :param vm: VM for which we manage devices
    """

    def __init__(self, vm):
        super().__init__()
        self._vm = vm

    def __missing__(self, key):
        self[key] = DeviceCollection(self._vm, key)
        return self[key]


class AssignedCollection:
    """
    Helper object managing assigned devices.
    """

    def __init__(self):
        self._dict = {}

    def add(self, assignment: DeviceAssignment):
        """ Add assignment to collection """
        assert assignment.attach_automatically
        vm = assignment.backend_domain
        ident = assignment.ident
        key = (vm, ident)
        assert key not in self._dict

        self._dict[key] = assignment

    def discard(self, assignment: DeviceAssignment):
        """
        Discard assignment from collection.
        """
        assert assignment.attach_automatically
        vm = assignment.backend_domain
        ident = assignment.ident
        key = (vm, ident)
        if key not in self._dict:
            raise KeyError
        del self._dict[key]

    def __contains__(self, device) -> bool:
        return (device.backend_domain, device.ident) in self._dict

    def get(self, device: DeviceInfo) -> DeviceAssignment:
        """
        Returns the corresponding `DeviceAssignment` for the device.
        """
        return self._dict[(device.backend_domain, device.ident)]

    def __iter__(self):
        return self._dict.values().__iter__()

    def __len__(self) -> int:
        return len(self._dict.keys())
