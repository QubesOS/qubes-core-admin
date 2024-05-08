#
# The Qubes OS Project, https://www.qubes-os.org/
#
# Copyright (C) 2010-2016  Joanna Rutkowska <joanna@invisiblethingslab.com>
# Copyright (C) 2015-2016  Wojtek Porczyk <woju@invisiblethingslab.com>
# Copyright (C) 2016       Bahtiar `kalkin-` Gadimov <bahtiar@gadimov.de>
# Copyright (C) 2024       Piotr Bartman-Szwarc
#                                   <prbartman@invisiblethingslab.com>
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
   :py:class:`qubes.device_protocol.DeviceInfo`, designed to hold device
   description (including bus-specific properties)
 - handle `device-attach:bus` and `device-detach:bus` events for
   performing the attach/detach action; events are fired even when domain isn't
   running and extension should be prepared for this; handlers for those events
   can be coroutines
 - handle `device-list:bus` event - list devices exposed by particular
   domain; it should return a list of appropriate DeviceInfo objects
 - handle `device-get:bus` event - get one device object exposed by this
   domain of given identifier
 - handle `device-list-attached:bus` event - list devices currently attached
   to this domain
 - fire `device-list-change:bus` and following `device-added:bus` or
   `device-removed:bus` events when a device list change is detected
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
from typing import Iterable

import qubes.exc
import qubes.utils
from qubes.device_protocol import (Device, DeviceInfo, UnknownDevice,
                                   DeviceAssignment)


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


class UnrecognizedDevice(qubes.exc.QubesException, ValueError):
    """
    Device identity is not as expected.
    """


class DeviceCollection:
    """Bag for devices.

    Used as default value for :py:meth:`DeviceManager.__missing__` factory.

    :param vm: VM for which we manage devices
    :param bus: device bus

    This class emits following events on VM object:

        .. event:: device-added:<class> (device)

            Fired when new device is discovered.

        .. event:: device-removed:<class> (device)

            Fired when device is no longer exposed by a backend VM.

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

        .. event:: device-assign:<class> (device, options)

            Fired when device is assigned to a VM.

            Handler for this event may be asynchronous.

            :param device: :py:class:`DeviceInfo` object to be assigned
            :param options: :py:class:`dict` of assignment options

        .. event:: device-unassign:<class> (device)

            Fired when device is unassigned from a VM.

            Handler for this event can be asynchronous (a coroutine).

            :param device: :py:class:`DeviceInfo` object to be unassigned

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

    async def attach(self, assignment: DeviceAssignment):
        """
        Attach device to domain.
        """

        if not assignment.devclass_is_set:
            assignment.devclass = self._bus
        elif assignment.devclass != self._bus:
            raise ValueError(
                f'Trying to attach {assignment.devclass} device '
                f'when {self._bus} device expected.')

        if self._vm.is_halted():
            raise qubes.exc.QubesVMNotRunningError(
                self._vm,"VM not running, cannot attach device,"
                " do you mean `assign`?")

        device = assignment.device
        if device in self.get_attached_devices():
            raise DeviceAlreadyAttached(
                'device {!s} of class {} already attached to {!s}'.format(
                    device, self._bus, self._vm))

        await self._vm.fire_event_async(
            'device-pre-attach:' + self._bus,
            pre_event=True, device=device, options=assignment.options)

        await self._vm.fire_event_async(
            'device-attach:' + self._bus,
            device=device, options=assignment.options)

    async def assign(self, assignment: DeviceAssignment):
        """
        Assign device to domain.
        """
        if not assignment.devclass_is_set:
            assignment.devclass = self._bus
        elif assignment.devclass != self._bus:
            raise ValueError(
                f'Trying to attach {assignment.devclass} device '
                f'when {self._bus} device expected.')

        device = assignment.device
        if device in self.get_assigned_devices():
            raise DeviceAlreadyAssigned(
                'device {!s} of class {} already assigned to {!s}'.format(
                    device, self._bus, self._vm))

        self._set.add(assignment)

        await self._vm.fire_event_async(
            'device-assign:' + self._bus,
            device=device, options=assignment.options)

    def load_assignment(self, device_assignment: DeviceAssignment):
        """Load DeviceAssignment retrieved from qubes.xml

        This can be used only for loading qubes.xml, when VM events are not
        enabled yet.
        """
        assert not self._vm.events_enabled
        assert device_assignment.attach_automatically
        device_assignment.devclass = self._bus
        self._set.add(device_assignment)

    async def update_required(self, device: Device, required: bool):
        """
        Update `required` flag of an already attached device.

        :param Device device: device for which change required flag
        :param bool required: new assignment:
                              `False` -> device will be auto-attached to qube
                              `True` -> device is required to start qube
        """
        if self._vm.is_halted():
            raise qubes.exc.QubesVMNotStartedError(
                self._vm,
                'VM must be running to modify device assignment'
            )
        assignments = [a for a in self.get_assigned_devices()
                       if a == device]
        if not assignments:
            raise qubes.exc.QubesValueError(
                f'Device {device} not assigned to {self._vm.name}')
        assert len(assignments) == 1
        assignment = assignments[0]

        # be careful to use already present assignment, not the provided one
        # - to not change options as a side effect
        if assignment.required == required:
            return

        assignment.required = required
        await self._vm.fire_event_async(
            'device-assignment-changed:' + self._bus, device=device)

    async def detach(self, device: Device):
        """
        Detach device from domain.
        """
        for assign in self.get_attached_devices():
            if device == assign:
                # load all options
                assignment = assign
                break
        else:
            raise DeviceNotAssigned(
                f'device {device.ident!s} of class {self._bus} not '
                f'attached to {self._vm!s}')

        if assignment.required and not self._vm.is_halted():
            raise qubes.exc.QubesVMNotHaltedError(
                self._vm,
                "Can not detach a required device from a non halted qube. "
                "You need to unassign device first.")

        # use the local object
        device = assignment.device
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

        self._set.discard(assignment)

        device = device_assignment.device
        await self._vm.fire_event_async(
            'device-unassign:' + self._bus, device=device)

    def get_dedicated_devices(self) -> Iterable[DeviceAssignment]:
        """
        List devices which are attached or assigned to this vm.
        """
        yield from itertools.chain(
            self.get_attached_devices(), self.get_assigned_devices())

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
                    frontend_domain=self._vm,
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
        yield from self._vm.fire_event('device-list:' + self._bus)

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
        Discard assignment from a collection.
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
