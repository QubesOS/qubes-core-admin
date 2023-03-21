# -*- encoding: utf8 -*-
#
# The Qubes OS Project, http://www.qubes-os.org
#
# Copyright (C) 2017 Marek Marczykowski-Górecki
#                               <marmarek@invisiblethingslab.com>
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

''' Qubes block devices extensions '''
import re
import string
import lxml.etree

import qubes.devices
import qubes.ext

name_re = re.compile(r"\A[a-z0-9-]{1,12}\Z")
device_re = re.compile(r"\A[a-z0-9/-]{1,64}\Z")
# FIXME: any better idea of desc_re?
desc_re = re.compile(r"\A.{1,255}\Z")
mode_re = re.compile(r"\A[rw]\Z")

# all frontends, prefer xvdi
# TODO: get this from libvirt driver?
AVAILABLE_FRONTENDS = ['xvd'+c for c in
                       string.ascii_lowercase[8:]+string.ascii_lowercase[:8]]

SYSTEM_DISKS = ('xvda', 'xvdb', 'xvdc')
# xvdd is considered system disk only if vm.kernel is set
SYSTEM_DISKS_DOM0_KERNEL = SYSTEM_DISKS + ('xvdd',)


class BlockDevice(qubes.devices.DeviceInfo):
    def __init__(self, backend_domain, ident):
        super().__init__(backend_domain=backend_domain,
            ident=ident)
        self._description = None
        self._mode = None
        self._size = None

    @property
    def description(self):
        '''Human readable device description'''
        if self._description is None:
            if not self.backend_domain.is_running():
                return self.ident
            safe_set = {ord(c) for c in
                string.ascii_letters + string.digits + '()+,-.:=_/ '}
            untrusted_desc = self.backend_domain.untrusted_qdb.read(
                '/qubes-block-devices/{}/desc'.format(self.ident))
            if not untrusted_desc:
                return ''
            desc = ''.join((chr(c) if c in safe_set else '_')
                for c in untrusted_desc)
            self._description = desc
        return self._description

    @property
    def mode(self):
        '''Device mode, either 'w' for read-write, or 'r' for read-only'''
        if self._mode is None:
            if not self.backend_domain.is_running():
                return 'w'
            untrusted_mode = self.backend_domain.untrusted_qdb.read(
                '/qubes-block-devices/{}/mode'.format(self.ident))
            if untrusted_mode is None:
                self._mode = 'w'
            elif untrusted_mode not in (b'w', b'r'):
                self.backend_domain.log.warning(
                    'Device {} has invalid mode'.format(self.ident))
                self._mode = 'w'
            else:
                self._mode = untrusted_mode.decode()
        return self._mode

    @property
    def size(self):
        '''Device size in bytes'''
        if self._size is None:
            if not self.backend_domain.is_running():
                return None
            untrusted_size = self.backend_domain.untrusted_qdb.read(
                '/qubes-block-devices/{}/size'.format(self.ident))
            if untrusted_size is None:
                self._size = 0
            elif not untrusted_size.isdigit():
                self.backend_domain.log.warning(
                    'Device {} has invalid size'.format(self.ident))
                self._size = 0
            else:
                self._size = int(untrusted_size)
        return self._size

    @property
    def device_node(self):
        '''Device node in backend domain'''
        return '/dev/' + self.ident.replace('_', '/')


class BlockDeviceExtension(qubes.ext.Extension):
    @qubes.ext.handler('domain-init', 'domain-load')
    def on_domain_init_load(self, vm, event):
        '''Initialize watching for changes'''
        # pylint: disable=unused-argument
        vm.watch_qdb_path('/qubes-block-devices')

    @qubes.ext.handler('domain-qdb-change:/qubes-block-devices')
    def on_qdb_change(self, vm, event, path):
        '''A change in QubesDB means a change in device list'''
        # pylint: disable=unused-argument
        vm.fire_event('device-list-change:block')

    def device_get(self, vm, ident):
        '''Read information about device from QubesDB

        :param vm: backend VM object
        :param ident: device identifier
        :returns BlockDevice'''

        untrusted_qubes_device_attrs = vm.untrusted_qdb.list(
            '/qubes-block-devices/{}/'.format(ident))
        if not untrusted_qubes_device_attrs:
            return None
        return BlockDevice(vm, ident)

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

            ident = untrusted_ident

            device_info = self.device_get(vm, ident)
            if device_info:
                yield device_info

    @qubes.ext.handler('device-get:block')
    def on_device_get_block(self, vm, event, ident):
        # pylint: disable=unused-argument
        if not vm.is_running():
            return
        if not vm.app.vmm.offline_mode:
            device_info = self.device_get(vm, ident)
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
                ident = dev_path[len('/dev/'):]
            else:
                ident = dev_path

            ident = ident.replace('/', '_')

            yield (BlockDevice(backend_domain, ident), options)

    def find_unused_frontend(self, vm, devtype='disk'):
        '''Find unused block frontend device node for <target dev=.../>
        parameter'''
        assert vm.is_running()

        xml = vm.libvirt_domain.XMLDesc()
        parsed_xml = lxml.etree.fromstring(xml)
        used = [target.get('dev', None) for target in
            parsed_xml.xpath("//domain/devices/disk/target")]
        if devtype == 'cdrom' and 'xvdd' not in used:
            # prefer 'xvdd' for CDROM if available; only first 4 disks are
            # emulated in HVM, which means only those are bootable
            return 'xvdd'
        for dev in AVAILABLE_FRONTENDS:
            if dev not in used:
                return dev
        return None

    @qubes.ext.handler('device-pre-attach:block')
    def on_device_pre_attached_block(self, vm, event, device, options):
        # pylint: disable=unused-argument

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
            return

        if not device.backend_domain.is_running():
            raise qubes.exc.QubesVMNotRunningError(device.backend_domain,
                'Domain {} needs to be running to attach device from '
                'it'.format(device.backend_domain.name))

        if 'frontend-dev' not in options:
            options['frontend-dev'] = self.find_unused_frontend(
                vm, options.get('devtype', 'disk'))

        vm.libvirt_domain.attachDevice(
            vm.app.env.get_template('libvirt/devices/block.xml').render(
                device=device, vm=vm, options=options))

    @qubes.ext.handler('device-pre-detach:block')
    def on_device_pre_detached_block(self, vm, event, device):
        # pylint: disable=unused-argument
        if not vm.is_running():
            return

        # need to enumerate attached device to find frontend_dev option (at
        # least)
        for attached_device, options in self.on_device_list_attached(vm, event):
            if attached_device == device:
                vm.libvirt_domain.detachDevice(
                    vm.app.env.get_template('libvirt/devices/block.xml').render(
                        device=device, vm=vm, options=options))
                break
