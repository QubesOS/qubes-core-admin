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

Devices are identified by pair of (backend domain, `port_id`), where `port_id`
is :py:class:`str` and can contain only characters from `[a-zA-Z0-9._-]` set.

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
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

import qubes.exc
import qubes.utils
from qubes.device_protocol import (
    Port,
    DeviceInfo,
    UnknownDevice,
    DeviceAssignment,
    VirtualDevice,
    AssignmentMode,
    qbool,
)
from qubes.exc import (
    ProtocolError,
    QubesValueError,
    DeviceNotAssigned,
    DeviceAlreadyAttached,
    DeviceAlreadyAssigned,
)

# QubesDB key a backend writes while it support ``used`` markers.
USAGE_TRACKING_QDB_KEY = "/qubes-device-usage-tracking"
# A malicious backend could block qubesd by infinite searching.
MAX_TREE_DEPTH = 8


def qbool_untrusted_used(untrusted_used, log=None) -> bool:
    """
    Parse the untrusted ``used`` marker read from a backend VM's QubesDB.

    A missing value (:py:obj:`None`) or a boolean-false literal
    (``False``/``0``/``no``/``off``) means the device is not in use there.
    A boolean-true literal (``True``/``1``/``yes``/``on``) means it is.

    Any other, unparsable value is treated as **in use**: it is safer to
    refuse such a device. Such a case is logged as a warning.
    """
    if untrusted_used is None:
        return False
    if isinstance(untrusted_used, bytes):
        untrusted_used = untrusted_used.decode("ascii", errors="replace")
    try:
        return qbool(untrusted_used.strip())
    except QubesValueError:
        if log is not None:
            log.warning(
                "Invalid 'used' marker %r, assuming the device is in use",
                untrusted_used,
            )
        return True


def _children_by_parent(backend_domain) -> Dict[Tuple[str, str], List]:
    index: Dict[Tuple[str, str], List] = {}
    for devclass in list(backend_domain.devices.keys()):
        for dev in backend_domain.devices[devclass]:
            parent = dev.parent_device
            if parent is None:
                continue
            key = (parent.port.devclass, parent.port.port_id)
            index.setdefault(key, []).append(dev)
    return index


def _all_subdevices(device) -> Iterable:
    """
    Descendants of *device*, as reported by the backend.

    A "links" are untrusted input, so a backend could describe a cycle;
    ``seen`` is what keeps that from looping forever here.
    """

    def key(dev):
        return dev.port.devclass, dev.port.port_id

    seen = {key(device)}

    children = _children_by_parent(device.backend_domain)
    stack = [(child, 1) for child in children.get(key(device), ())]
    while stack:
        child, depth = stack.pop()
        if key(child) in seen:
            continue
        seen.add(key(child))
        yield child
        if depth < MAX_TREE_DEPTH:
            stack.extend(
                (grandchild, depth + 1)
                for grandchild in children.get(key(child), ())
            )


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

        .. event:: device-check-available:<class> (device, options)

            Asks whether a device is free to be attached.

            Fired for `required` assignment while the qube is starting.

            Handler for this event may be asynchronous.

            :param device: :py:class:`DeviceInfo` object about to be taken
            :param options: :py:class:`dict` of assignment options

        .. event:: device-detach:<class> (port)

            Fired when device is detached from a VM.

            Handler for this event can be asynchronous (a coroutine).

            :param device: :py:class:`DeviceInfo` object to be attached

        .. event:: device-pre-detach:<class> (port)

            Fired before device is detached from a VM

            Handler for this event can be asynchronous (a coroutine).

            :param port: :py:class:`Port` object from which device be detached

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

        .. event:: device-get:<class> (port_id)

            Fired to get a single device, given by the `port_id` parameter.
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
            "qubes.devices", self._bus
        )

    @property
    def supported_assignment_modes(self):
        """
        Assignment modes allowed for this device class.
        """
        return self.devclass.SUPPORTED_ASSIGNMENT_MODES

    async def attach(self, assignment: DeviceAssignment):
        """
        Attach device to domain.
        """

        if assignment.devclass != self._bus:
            raise ProtocolError(
                f"Trying to attach {assignment.devclass} device "
                f"when {self._bus} device expected."
            )

        if AssignmentMode.MANUAL not in self.supported_assignment_modes:
            raise qubes.exc.QubesValueError(
                f"{self._bus} devices cannot be attached manually."
            )

        if self._vm.is_halted():
            raise qubes.exc.QubesVMNotRunningError(
                self._vm,
                "VM not running, cannot attach device,"
                " do you mean `assign`?",
            )

        try:
            device = assignment.device
            if isinstance(device, UnknownDevice):
                # assignment matches no devices
                raise ProtocolError(
                    f"Cannot attach unknown {assignment.devclass} device."
                )
        except ProtocolError:
            # assignment matches too many devices
            raise ProtocolError(
                f"Cannot attach ambiguous {assignment.devclass} device."
            )

        if isinstance(device, UnknownDevice):
            raise ProtocolError(
                f"{device.devclass} device not recognized "
                f"in {device.port_id} port."
            )

        if device in [ass.device for ass in self.get_attached_devices()]:
            raise DeviceAlreadyAttached(
                "device {!s} of class {} already attached to {!s}".format(
                    device, self._bus, self._vm
                )
            )

        await self._vm.fire_event_async(
            "device-pre-attach:" + self._bus,
            pre_event=True,
            device=device,
            options=assignment.options,
        )

        await self._vm.fire_event_async(
            "device-attach:" + self._bus,
            device=device,
            options=assignment.options,
        )

    def _validate_mode_supported(self, mode: AssignmentMode):
        if mode in self.supported_assignment_modes:
            return
        allowed = ", ".join(
            sorted(m.value for m in self.supported_assignment_modes)
        )
        raise qubes.exc.QubesValueError(
            f"{self._bus} devices cannot be assigned in "
            f"'{mode.value}' mode; allowed modes: {allowed}."
        )

    async def assign(self, assignment: DeviceAssignment):
        """
        Assign device to domain.
        """
        if assignment.devclass != self._bus:
            raise ValueError(
                f"Trying to assign {assignment.devclass} device "
                f"when {self._bus} device expected."
            )

        device = assignment.virtual_device
        if assignment in self.get_assigned_devices():
            raise DeviceAlreadyAssigned(
                f"{self._bus} device {device!s} "
                f"already assigned to {self._vm!s}"
            )

        # avoid putting MANUAL assigment to qubes.xml
        if not assignment.attach_automatically:
            raise ValueError("Only auto-attachable devices can be assigned.")

        self._validate_mode_supported(assignment.mode)
        self._set.add(assignment)

        await self._vm.fire_event_async(
            "device-pre-assign:" + self._bus,
            pre_event=True,
            device=device,
            options=assignment.options,
        )

        await self._vm.fire_event_async(
            "device-assign:" + self._bus,
            device=device,
            options=assignment.options,
        )

    def load_assignment(self, device_assignment: DeviceAssignment):
        """Load DeviceAssignment retrieved from qubes.xml

        This can be used only for loading qubes.xml, when VM events are not
        enabled yet.
        """
        assert not self._vm.events_enabled
        assert device_assignment.attach_automatically
        self._set.add(device_assignment)

    async def update_assignment(
        self, device: VirtualDevice, mode: AssignmentMode
    ):
        """
        Update assignment mode of an already assigned device.

        :param VirtualDevice device: device for which change required flag
        :param AssignmentMode mode: new assignment mode
        """
        if mode == AssignmentMode.MANUAL:
            raise qubes.exc.QubesValueError(
                "Cannot change assignment mode to 'manual'"
            )
        self._validate_mode_supported(mode)
        assignments = [
            a for a in self.get_assigned_devices() if a.virtual_device == device
        ]
        if not assignments:
            raise qubes.exc.QubesValueError(
                f"Device {device} not assigned to {self._vm.name}"
            )
        assert len(assignments) == 1
        assignment = assignments[0]

        if assignment.mode == mode:
            return

        # be careful to use already present assignment, not the provided one
        # - to not change options as a side effect
        new_assignment = assignment.clone(mode=mode)

        await self._vm.fire_event_async(
            "device-pre-assign:" + self._bus,
            pre_event=True,
            device=device,
            options=new_assignment.options,
        )

        self._set.discard(assignment)
        self._set.add(new_assignment)
        await self._vm.fire_event_async(
            "device-assignment-changed:" + self._bus, device=device
        )

    async def detach(self, port: Port):
        """
        Detach device from domain.
        """
        for attached in self.get_attached_devices():
            if port.port_id == attached.port_id:
                # load all options
                break
        else:
            raise DeviceNotAssigned(
                f"{self._bus} device {port.port_id!s} not "
                f"attached to {self._vm!s}"
            )

        for assign in self.get_assigned_devices():
            if (
                assign.required
                and not self._vm.is_halted()
                and assign.matches(attached.device)
            ):
                raise qubes.exc.QubesVMNotHaltedError(
                    self._vm,
                    "Can not detach a required device from a non halted qube. "
                    "You need to unassign device first.",
                )

        # use the local object, only one device can match
        port = attached.device.port
        await self._vm.fire_event_async(
            "device-pre-detach:" + self._bus, pre_event=True, port=port
        )

        await self._vm.fire_event_async("device-detach:" + self._bus, port=port)

    async def unassign(self, assignment: DeviceAssignment):
        """
        Unassign device from domain.
        """
        for assign in self.get_assigned_devices():
            if assignment == assign:
                # load all options
                assignment = assign
                break
        else:
            raise DeviceNotAssigned(
                f"{self._bus} device {assignment} not assigned to {self._vm!s}"
            )

        self._set.discard(assignment)

        await self._vm.fire_event_async(
            "device-unassign:" + self._bus, device=assignment.virtual_device
        )

    def get_dedicated_devices(self) -> Iterable[DeviceAssignment]:
        """
        List devices which are attached or assigned to this vm.
        """
        yield from itertools.chain(
            self.get_attached_devices(), self.get_assigned_devices()
        )

    def get_attached_devices(self) -> Iterable[DeviceAssignment]:
        """
        List devices which are attached to this vm.
        """
        attached = self._vm.fire_event("device-list-attached:" + self._bus)
        for dev, options in attached:
            for assignment in self._set:
                if dev == assignment:
                    yield assignment
                    break
            else:
                yield DeviceAssignment(
                    dev,
                    frontend_domain=self._vm,
                    options=options,
                    mode="manual",
                )

    def get_exposed_attachments(self) -> Dict[str, Any]:
        """
        Returns map of exposed devices attached to their frontend VMs.

        It asks every domain; for repeating calls use :py:class:`Attachments`.
        """
        result: Dict[str, Any] = {}
        app = getattr(self._vm, "app", None)
        if app is not None:
            for vm in app.domains:
                if not vm.is_running():
                    continue
                try:
                    assignments = vm.devices[self._bus].get_attached_devices()
                except LookupError:
                    continue
                for assignment in assignments:
                    if assignment.backend_domain == self._vm:
                        result[assignment.port.port_id] = vm

        return result

    def get_assigned_devices(
        self, required_only: bool = False
    ) -> Iterable[DeviceAssignment]:
        """
        Devices assigned to this vm (included in :file:`qubes.xml`).

        Safe to access before libvirt bootstrap.
        """
        for ass in self._set:
            if required_only and not ass.required:
                continue
            yield ass

    def get_exposed_devices(self) -> Iterable[DeviceInfo]:
        """
        List devices exposed by this vm.
        """
        yield from self._vm.fire_event("device-list:" + self._bus)

    __iter__ = get_exposed_devices

    def __getitem__(self, port_id):
        """Get device object with given port id.

        :returns: py:class:`DeviceInfo`

        If domain isn't running, it is impossible to check device validity,
        so return UnknownDevice object. Also do the same for non-existing
        devices - otherwise it will be impossible to detach already
        disconnected device.

        :raises AssertionError: when multiple devices with the same port_id are
        found
        """
        dev = self._vm.fire_event("device-get:" + self._bus, port_id=port_id)
        if dev:
            assert len(dev) == 1
            return dev[0]

        return UnknownDevice(Port(self._vm, port_id, devclass=self._bus))


class DeviceManager(dict):
    """
    Device manager that hold all devices by their classes.

    :param vm: VM for which we manage devices
    """

    def __init__(self, vm):
        super().__init__()
        self._vm = vm
        # guards the recursion in `busy_ports()`
        self._computing_busy_ports = False

    def __missing__(self, key):
        self[key] = DeviceCollection(self._vm, key)
        return self[key]

    @property
    def usage_tracking(self) -> bool:
        """
        Does this backend maintain the per-device ``used`` markers?

        The backend manifests it by writing `USAGE_TRACKING_QDB_KEY`.
        """
        if not self._vm or not self._vm.is_running():
            return False
        untrusted_value = self._vm.untrusted_qdb.read(USAGE_TRACKING_QDB_KEY)
        if untrusted_value is None:
            return False
        if isinstance(untrusted_value, bytes):
            # do not rise on decoding errors
            untrusted_value = untrusted_value.decode("ascii", errors="replace")
        try:
            return qbool(untrusted_value.strip())
        except QubesValueError:
            return False

    def attachments(self) -> "Attachments":
        """
        Lazy snapshot set of all device attachments.
        """
        return Attachments(self)

    def busy_ports(
        self, devclasses: Tuple[str, ...] = ("block",)
    ) -> Dict[str, Set[str]]:
        """
        Ports unusable because they (or something below them) are attached.

        Returns ``{devclass: {port_id, ...}}``.  It walks up from the
        exported ports of each class in `devclasses`.

        For now, only block devices are included as starting points, as only
        they can be child devices. *If this changes*, modify the default
        argument or (better) add a handler that will search all device classes.

        WARNING: Finding a class's attached ports lists that class, and an
        extension lists a class by asking `busy_ports`: that creates a loops
        here, it will re-enter `busy_ports` while it runs. So we need a guard.
        The guard turns the nested call into an empty {}, which is ok since
        a nested caller only needs port ids, never their busy state.
        """
        if self._computing_busy_ports:
            return {}
        self._computing_busy_ports = True
        try:
            return self._busy_ports(devclasses)
        finally:
            self._computing_busy_ports = False

    def _busy_ports(self, devclasses) -> Dict[str, Set[str]]:
        result: Dict[str, Set[str]] = {}

        for devclass in devclasses:
            for port_id in self[devclass].get_exposed_attachments():
                try:
                    node = self[devclass][port_id]
                except (LookupError, TypeError):
                    # exported but no longer listed; the port still counts
                    result.setdefault(devclass, set()).add(port_id)
                    continue

                seen: Set[Tuple[str, str]] = set()
                while node is not None and len(seen) <= MAX_TREE_DEPTH:
                    key = (node.port.devclass, node.port.port_id)
                    if key in seen:
                        break
                    seen.add(key)
                    result.setdefault(key[0], set()).add(key[1])
                    node = getattr(node, "parent_device", None)

        return result


class Attachments:
    """
    Lazy snapshot set of all device attachments.

    Who holds what, from one search over the running domains.
    Meant to live for a single operation: it never refreshes.
    """

    def __init__(self, manager: DeviceManager):
        self._manager = manager
        self._bus_cache: Dict[str, Dict[str, Any]] = {}

    def _bus(self, devclass: str) -> Dict[str, Any]:
        if devclass not in self._bus_cache:
            self._bus_cache[devclass] = self._manager[
                devclass
            ].get_exposed_attachments()
        return self._bus_cache[devclass]

    def frontend(self, port) -> Optional[Any]:
        """
        The frontend domain *port* is attached to, if any.
        """
        return self._bus(port.devclass).get(port.port_id)

    def attached_subdevice(self, device) -> Optional[Tuple[Any, Any]]:
        """
        A subdevice of *device* that is attached to a VM, and that VM.

        Stops at the first one found; the caller has to free it itself.
        """
        for subdevice in _all_subdevices(device):
            frontend = self.frontend(subdevice.port)
            if frontend is not None:
                return subdevice, frontend
        return None


class AssignedCollection:
    """
    Helper object managing assigned devices.
    """

    def __init__(self):
        self._dict = {}

    def add(self, assignment: DeviceAssignment):
        """Add assignment to collection"""
        assert assignment.attach_automatically
        vm = assignment.backend_domain
        port_id = assignment.port_id
        dev_id = assignment.device_id
        key = (vm, port_id, dev_id)
        assert key not in self._dict

        self._dict[key] = assignment

    def discard(self, assignment: DeviceAssignment):
        """
        Discard assignment from a collection.
        """
        assert assignment.attach_automatically
        vm = assignment.backend_domain
        port_id = assignment.port_id
        dev_id = assignment.device_id
        key = (vm, port_id, dev_id)
        if key not in self._dict:
            raise KeyError
        del self._dict[key]

    def __contains__(self, device) -> bool:
        key = (device.backend_domain, device.port_id, device.device_id)
        return key in self._dict

    def get(self, device: DeviceInfo) -> DeviceAssignment:
        """
        Returns the corresponding `DeviceAssignment` for the device.
        """
        key = (device.backend_domain, device.port_id, device.device_id)
        return self._dict[key]

    def __iter__(self):
        return self._dict.values().__iter__()

    def __len__(self) -> int:
        return len(self._dict.keys())
