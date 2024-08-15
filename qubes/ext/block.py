# -*- encoding: utf8 -*-
#
# The Qubes OS Project, http://www.qubes-os.org
#
# Copyright (C) 2017 Marek Marczykowski-Górecki
#                               <marmarek@invisiblethingslab.com>
# Copyright (C) 2024 Piotr Bartman-Szwarc <prbartman@invisiblethingslab.com>
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

""" Qubes block devices extensions """
import asyncio
import collections
import re
import string
import sys
from typing import Optional, List

import lxml.etree

import qubes.device_protocol
import qubes.devices
import qubes.ext
from qubes.ext.utils import device_list_change, confirm_device_attachment
from qubes.storage import Storage

name_re = re.compile(r"\A[a-z0-9-]{1,12}\Z")
device_re = re.compile(r"\A[a-z0-9/-]{1,64}\Z")
# FIXME: any better idea of desc_re?
desc_re = re.compile(r"\A.{1,255}\Z")
mode_re = re.compile(r"\A[rw]\Z")

SYSTEM_DISKS = ('xvda', 'xvdb', 'xvdc')
# xvdd is considered system disk only if vm.kernel is set
SYSTEM_DISKS_DOM0_KERNEL = SYSTEM_DISKS + ('xvdd',)


class BlockDevice(qubes.device_protocol.DeviceInfo):
    def __init__(self, backend_domain, port_id):
        port = qubes.device_protocol.Port(
            backend_domain=backend_domain, port_id=port_id, devclass="block")
        super().__init__(port)

        # lazy loading
        self._mode = None
        self._size = None
        self._interface_num = None

    @property
    def name(self):
        """
        The name of the device it introduced itself with.

        Could be empty string or "unknown".
        """
        if self._name is None:
            name, _ = self._load_lazily_name_and_serial()
            return name
        return self._name

    @property
    def serial(self) -> str:
        """
        The serial number of the device it introduced itself with.

        Could be empty string or "unknown".

        Override this method to return proper name directly from device itself.
        """
        if self._serial is None:
            _, serial = self._load_lazily_name_and_serial()
            return serial
        return self._serial

    def _load_lazily_name_and_serial(self):
        if not self.backend_domain.is_running():
            return "unknown", "unknown"
        untrusted_desc = self.backend_domain.untrusted_qdb.read(
            f'/qubes-block-devices/{self.port_id}/desc')
        if not untrusted_desc:
            return "unknown", "unknown"
        desc = BlockDevice._sanitize(
            untrusted_desc,
            string.ascii_letters + string.digits + '()+,-.:=_/ ')
        model, _, label = desc.partition(' ')
        if model:
            serial = self._serial = model.replace('_', ' ').strip()
        else:
            serial = "unknown"
        # label: '(EXAMPLE)' or '()'
        if label[1:-1]:
            name = self._name = label.replace('_', ' ')[1:-1].strip()
        else:
            name = "unknown"
        return name, serial

    @property
    def manufacturer(self) -> str:
        if self.parent_device:
            return f"sub-device of {self.parent_device.port}"
        return f"hosted by {self.backend_domain!s}"

    @property
    def mode(self):
        """Device mode, either 'w' for read-write, or 'r' for read-only"""
        if self._mode is None:
            if not self.backend_domain.is_running():
                return 'w'
            untrusted_mode = self.backend_domain.untrusted_qdb.read(
                '/qubes-block-devices/{}/mode'.format(self.port_id))
            if untrusted_mode is None:
                self._mode = 'w'
            elif untrusted_mode not in (b'w', b'r'):
                self.backend_domain.log.warning(
                    'Device {} has invalid mode'.format(self.port_id))
                self._mode = 'w'
            else:
                self._mode = untrusted_mode.decode()
        return self._mode

    @property
    def size(self):
        """Device size in bytes"""
        if self._size is None:
            if not self.backend_domain.is_running():
                return None
            untrusted_size = self.backend_domain.untrusted_qdb.read(
                '/qubes-block-devices/{}/size'.format(self.port_id))
            if untrusted_size is None:
                self._size = 0
            elif not untrusted_size.isdigit():
                self.backend_domain.log.warning(
                    'Device {} has invalid size'.format(self.port_id))
                self._size = 0
            else:
                self._size = int(untrusted_size)
        return self._size

    @property
    def device_node(self):
        """Device node in backend domain"""
        return '/dev/' + self.port_id.replace('_', '/')

    @property
    def interfaces(self) -> List[qubes.device_protocol.DeviceInterface]:
        """
        List of device interfaces.

        Every device should have at least one interface.
        """
        return [qubes.device_protocol.DeviceInterface("******", "block")]

    @property
    def parent_device(self) -> Optional[qubes.device_protocol.Port]:
        """
        The parent device, if any.

        If the device is part of another device (e.g., it's a single
        partition of an usb stick), the parent device id should be here.
        """
        if self._parent is None:
            if not self.backend_domain.is_running():
                return None
            untrusted_parent_info = self.backend_domain.untrusted_qdb.read(
                f'/qubes-block-devices/{self.port_id}/parent')
            if untrusted_parent_info is None:
                return None
            # '4-4.1:1.0' -> parent_ident='4-4.1', interface_num='1.0'
            # 'sda' -> parent_ident='sda', interface_num=''
            parent_ident, sep, interface_num = self._sanitize(
                untrusted_parent_info).partition(":")
            devclass = 'usb' if sep == ':' else 'block'
            if not parent_ident:
                return None
            try:
                self._parent = (
                    self.backend_domain.devices)[devclass][parent_ident]
            except KeyError:
                self._parent = qubes.device_protocol.UnknownDevice(
                    qubes.device_protocol.Port(
                        self.backend_domain, parent_ident, devclass=devclass))
            self._interface_num = interface_num
        return self._parent

    @property
    def attachment(self) -> Optional['qubes.vm.BaseVM']:
        """
        Warning: this property is time-consuming, do not run in loop!
        """
        if not self.backend_domain.is_running():
            return None
        for vm in self.backend_domain.app.domains:
            if not vm.is_running():
                continue
            if self._is_attached_to(vm):
                return vm

        return None

    def _is_attached_to(self, vm):
        xml_desc = lxml.etree.fromstring(vm.libvirt_domain.XMLDesc())

        for disk in xml_desc.findall('devices/disk'):
            info = _try_get_block_device_info(vm.app, disk)
            if not info:
                continue
            backend_domain, port_id = info

            if backend_domain.name != self.backend_domain.name:
                continue

            if self.port_id == port_id:
                return True
        return False

    @property
    def device_id(self) -> str:
        """
        Get identification of a device not related to port.
        """
        parent_identity = ''
        p = self.parent_device
        if p is not None:
            p_info = p.backend_domain.devices[p.devclass][p.port_id]
            parent_identity = p_info.device_id
            if p.devclass == 'usb':
                parent_identity = f'{p.port_id}:{parent_identity}'
        if self._interface_num:
            # device interface number (not partition)
            self_id = self._interface_num
        else:
            self_id = self._get_possible_partition_number()
        return f'{parent_identity}:{self_id}'

    def _get_possible_partition_number(self) -> Optional[int]:
        """
        If the device is partition return partition number.

        The behavior is undefined for the rest block devices.
        """
        # partition number: 'xxxxx12' -> '12' (partition)
        numbers = re.findall(r'\d+$', self.port_id)
        return int(numbers[-1]) if numbers else None

    @staticmethod
    def _sanitize(
            untrusted_parent: bytes,
            safe_chars: str =
            string.ascii_letters + string.digits + string.punctuation
    ) -> str:
        untrusted_device_desc = untrusted_parent.decode(
            'ascii', errors='ignore')
        return ''.join(
            c if c in set(safe_chars) else '_' for c in untrusted_device_desc
        )


def _try_get_block_device_info(app, disk):
    if disk.get('type') != 'block':
        return None
    dev_path_node = disk.find('source')
    if dev_path_node is None:
        return None

    backend_domain_node = disk.find('backenddomain')
    if backend_domain_node is not None:
        backend_domain = app.domains[
            backend_domain_node.get('name')]
    else:
        backend_domain = app.domains[0]

    dev_path = dev_path_node.get('dev')

    if dev_path.startswith('/dev/'):
        port_id = dev_path[len('/dev/'):]
    else:
        port_id = dev_path

    port_id = port_id.replace('/', '_')

    return backend_domain, port_id


class BlockDeviceExtension(qubes.ext.Extension):
    def __init__(self):
        super().__init__()
        self.devices_cache = collections.defaultdict(dict)

    @qubes.ext.handler('domain-init', 'domain-load')
    def on_domain_init_load(self, vm, event):
        """Initialize watching for changes"""
        # pylint: disable=unused-argument
        vm.watch_qdb_path('/qubes-block-devices')
        if vm.app.vmm.offline_mode:
            self.devices_cache[vm.name] = {}
            return
        if event == 'domain-load':
            # avoid building a cache on domain-init, as it isn't fully set yet,
            # and definitely isn't running yet
            device_attachments = self.get_device_attachments(vm)
            current_devices = dict(
                (dev.port_id, device_attachments.get(dev.port_id, None))
                for dev in self.on_device_list_block(vm, None))
            self.devices_cache[vm.name] = current_devices
        else:
            self.devices_cache[vm.name] = {}

    @qubes.ext.handler('domain-qdb-change:/qubes-block-devices')
    def on_qdb_change(self, vm, event, path):
        """A change in QubesDB means a change in a device list."""
        # pylint: disable=unused-argument
        device_attachments = self.get_device_attachments(vm)
        current_devices = dict(
            (dev.port_id, device_attachments.get(dev.port_id, None))
            for dev in self.on_device_list_block(vm, None))
        device_list_change(self, current_devices, vm, path, BlockDevice)

    @staticmethod
    def get_device_attachments(vm_):
        result = {}
        for vm in vm_.app.domains:
            if not vm.is_running():
                continue

            if vm.app.vmm.offline_mode:
                return result

            xml_desc = lxml.etree.fromstring(vm.libvirt_domain.XMLDesc())

            for disk in xml_desc.findall('devices/disk'):
                info = _try_get_block_device_info(vm.app, disk)
                if not info:
                    continue
                _backend_domain, port_id = info

                result[port_id] = vm
        return result

    @staticmethod
    def device_get(vm, port_id):
        """
        Read information about a device from QubesDB

        :param vm: backend VM object
        :param port_id: port identifier
        :returns BlockDevice
        """

        untrusted_qubes_device_attrs = vm.untrusted_qdb.list(
            '/qubes-block-devices/{}/'.format(port_id))
        if not untrusted_qubes_device_attrs:
            return None
        return BlockDevice(vm, port_id)

    @qubes.ext.handler('device-list:block')
    def on_device_list_block(self, vm, event):
        # pylint: disable=unused-argument

        if not vm.is_running():
            return
        untrusted_qubes_devices = vm.untrusted_qdb.list('/qubes-block-devices/')
        untrusted_idents = set(untrusted_path.split('/', 3)[2]
            for untrusted_path in untrusted_qubes_devices)
        for untrusted_ident in untrusted_idents:
            if not name_re.match(untrusted_ident):
                msg = ("%s vm's device path name contains unsafe characters. "
                       "Skipping it.")
                vm.log.warning(msg % vm.name)
                continue

            port_id = untrusted_ident

            device_info = self.device_get(vm, port_id)
            if device_info:
                yield device_info

    @qubes.ext.handler('device-get:block')
    def on_device_get_block(self, vm, event, port_id):
        # pylint: disable=unused-argument
        if not vm.is_running():
            return
        if not vm.app.vmm.offline_mode:
            device_info = self.device_get(vm, port_id)
            if device_info:
                yield device_info

    @qubes.ext.handler('device-list-attached:block')
    def on_device_list_attached(self, vm, event, **kwargs):
        # pylint: disable=unused-argument
        if not vm.is_running():
            return

        system_disks = SYSTEM_DISKS
        if getattr(vm, 'kernel', None):
            system_disks = SYSTEM_DISKS_DOM0_KERNEL
        xml_desc = lxml.etree.fromstring(vm.libvirt_domain.XMLDesc())

        for disk in xml_desc.findall('devices/disk'):
            if disk.get('type') != 'block':
                continue
            dev_path_node = disk.find('source')
            if dev_path_node is None:
                continue
            dev_path = dev_path_node.get('dev')

            target_node = disk.find('target')
            if target_node is not None:
                frontend_dev = target_node.get('dev')
                if not frontend_dev:
                    continue
                if frontend_dev in system_disks:
                    continue
            else:
                continue

            backend_domain_node = disk.find('backenddomain')
            if backend_domain_node is not None:
                backend_domain = vm.app.domains[backend_domain_node.get('name')]
            else:
                backend_domain = vm.app.domains[0]

            options = {}
            read_only_node = disk.find('readonly')
            if read_only_node is not None:
                options['read-only'] = 'yes'
            else:
                options['read-only'] = 'no'
            options['frontend-dev'] = frontend_dev
            if disk.get('device') != 'disk':
                options['devtype'] = disk.get('device')

            if dev_path.startswith('/dev/'):
                port_id = dev_path[len('/dev/'):]
            else:
                port_id = dev_path

            port_id = port_id.replace('/', '_')

            yield (BlockDevice(backend_domain, port_id), options)

    @staticmethod
    def find_unused_frontend(vm, devtype='disk'):
        """
        Find unused block frontend device node for <target dev=.../> parameter
        """
        assert vm.is_running()

        xml = vm.libvirt_domain.XMLDesc()
        parsed_xml = lxml.etree.fromstring(xml)
        used = [target.get('dev', None) for target in
            parsed_xml.xpath("//domain/devices/disk/target")]
        if devtype == 'cdrom' and 'xvdd' not in used:
            # prefer 'xvdd' for CDROM if available; only first 4 disks are
            # emulated in HVM, which means only those are bootable
            return 'xvdd'
        for dev in Storage.AVAILABLE_FRONTENDS:
            if dev not in used:
                return dev
        return None

    @qubes.ext.handler('device-pre-attach:block')
    def on_device_pre_attached_block(self, vm, event, device, options):
        # pylint: disable=unused-argument
        self.pre_attachment_internal(vm, device, options)

        vm.libvirt_domain.attachDevice(
            vm.app.env.get_template('libvirt/devices/block.xml').render(
                device=device, vm=vm, options=options))

    def pre_attachment_internal(
            self, vm, device, options, expected_attachment=None):
        if isinstance(device, qubes.device_protocol.UnknownDevice):
            print(f'{device.devclass.capitalize()} device {device} '
                  'not available, skipping.', file=sys.stderr)
            raise qubes.devices.UnrecognizedDevice()

        # validate options
        for option, value in options.items():
            if option == 'frontend-dev':
                if not value.startswith('xvd') and not value.startswith('sd'):
                    raise qubes.exc.QubesValueError(
                        'Invalid frontend-dev option value: ' + value)
            elif option == 'read-only':
                options[option] = (
                    'yes' if qubes.property.bool(None, None, value) else 'no')
            elif option == 'devtype':
                if value not in ('disk', 'cdrom'):
                    raise qubes.exc.QubesValueError(
                        'devtype option can only have '
                        '\'disk\' or \'cdrom\' value')
            else:
                raise qubes.exc.QubesValueError(
                    'Unsupported option {}'.format(option))

        if 'read-only' not in options:
            options['read-only'] = 'yes' if device.mode == 'r' else 'no'
        if options.get('read-only', 'no') == 'no' and device.mode == 'r':
            raise qubes.exc.QubesValueError(
                'This device can be attached only read-only')

        if not vm.is_running():
            print(f"Can not attach device, qube {vm.name} is not running."
                  , file=sys.stderr)
            return

        if not isinstance(device, BlockDevice):
            print("The device is not recognized as block device, "
                  f"skipping attachment of {device}",
                  file=sys.stderr)
            return

        if device.attachment and device.attachment != expected_attachment:
            raise qubes.devices.DeviceAlreadyAttached(
                'Device {!s} already attached to {!s}'.format(
                    device, device.attachment)
            )

        if not device.backend_domain.is_running():
            raise qubes.exc.QubesVMNotRunningError(
                device.backend_domain,
                f'Domain {device.backend_domain.name} needs to be running '
                f'to attach device from it')

        self.devices_cache[device.backend_domain.name][device.port_id] = vm

        if 'frontend-dev' not in options:
            options['frontend-dev'] = self.find_unused_frontend(
                vm, options.get('devtype', 'disk'))

    @qubes.ext.handler('domain-start')
    async def on_domain_start(self, vm, _event, **_kwargs):
        # pylint: disable=unused-argument
        for assignment in vm.devices['block'].get_assigned_devices():
            self.notify_auto_attached(vm, assignment)

    def notify_auto_attached(self, vm, assignment):
        identity = assignment.device_id
        device = assignment.device
        if identity not in ('*', device.device_id):
            print("Unrecognized identity, skipping attachment of device "
                  f"from the port {assignment}", file=sys.stderr)
            raise qubes.devices.UnrecognizedDevice(
                f"Device presented identity {device.device_id} "
                f"does not match expected {identity}"
            )

        if assignment.mode.value == "ask-to-attach":
            if vm.name != confirm_device_attachment(device, {vm: assignment}):
                return

        self.pre_attachment_internal(
            vm, device, assignment.options, expected_attachment=vm)

        asyncio.ensure_future(vm.fire_event_async(
            'device-attach:block',
            device=device,
            options=assignment.options,
        ))

    async def attach_and_notify(self, vm, assignment):
        # bypass DeviceCollection logic preventing double attach
        # we expected that these devices are already attached to this vm
        self.notify_auto_attached(vm, assignment)

    @qubes.ext.handler('domain-shutdown')
    async def on_domain_shutdown(self, vm, event, **_kwargs):
        """
        Remove from cache devices attached to or exposed by the vm.
        """
        # pylint: disable=unused-argument

        new_cache = {}
        for domain in vm.app.domains.values():
            new_cache[domain.name] = {}
            if domain == vm:
                for dev_id, front_vm in self.devices_cache[domain.name].items():
                    if front_vm is None:
                        continue
                    dev = BlockDevice(vm, dev_id)
                    await self._detach_and_notify(vm, dev, options=None)
                continue
            for dev_id, front_vm in self.devices_cache[domain.name].items():
                if front_vm == vm:
                    dev = BlockDevice(vm, dev_id)
                    asyncio.ensure_future(front_vm.fire_event_async(
                            'device-detach:block', port=dev))
                else:
                    new_cache[domain.name][dev_id] = front_vm
        self.devices_cache = new_cache.copy()

    async def _detach_and_notify(self, vm, device, options):
        # bypass DeviceCollection logic preventing double attach
        self.on_device_pre_detached_block(
            vm, 'device-pre-detach:block', device.port)
        await vm.fire_event_async(
            'device-detach:block', port=device, options=options)

    @qubes.ext.handler('qubes-close', system=True)
    def on_qubes_close(self, app, event):
        # pylint: disable=unused-argument
        self.devices_cache.clear()

    @qubes.ext.handler('device-pre-detach:block')
    def on_device_pre_detached_block(self, vm, event, port):
        # pylint: disable=unused-argument
        if not vm.is_running():
            return

        # need to enumerate attached devices to find frontend_dev option (at
        # least)
        for attached_device, options in self.on_device_list_attached(vm, event):
            if attached_device.port == port:
                self.devices_cache[port.backend_domain.name][
                    port.port_id] = None
                vm.libvirt_domain.detachDevice(
                    vm.app.env.get_template('libvirt/devices/block.xml').render(
                        device=attached_device, vm=vm, options=options))
                break
