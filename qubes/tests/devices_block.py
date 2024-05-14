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
import asyncio
from unittest import mock

import jinja2

import qubes.tests
import qubes.ext.block
from qubes.device_protocol import DeviceInterface, Device, DeviceInfo, \
    DeviceAssignment

modules_disk = '''
    <disk type='block' device='disk'>
      <driver name='phy'/>
      <source dev='/var/lib/qubes/vm-kernels/4.4.55-11/modules.img'/>
      <backingStore/>
      <target dev='xvdd' bus='xen'/>
      <readonly/>
    </disk>
'''

domain_xml_template = '''
<domain type='xen' id='9'>
  <name>test-vm</name>
  <uuid>00000000-0000-0000-0000-0000000000ae</uuid>
  <memory unit='KiB'>4096000</memory>
  <currentMemory unit='KiB'>409600</currentMemory>
  <vcpu placement='static'>8</vcpu>
  <os>
    <type arch='x86_64' machine='xenpv'>linux</type>
    <kernel>/var/lib/qubes/vm-kernels/4.4.55-11/vmlinuz</kernel>
    <initrd>/var/lib/qubes/vm-kernels/4.4.55-11/initramfs</initrd>
    <cmdline>root=/dev/mapper/dmroot ro nomodeset console=hvc0 rd_NO_PLYMOUTH rd.plymouth.enable=0 plymouth.enable=0 dyndbg=&quot;file drivers/xen/gntdev.c +p&quot; printk=8</cmdline>
  </os>
  <clock offset='utc' adjustment='reset'>
    <timer name='tsc' mode='native'/>
  </clock>
  <on_poweroff>destroy</on_poweroff>
  <on_reboot>destroy</on_reboot>
  <on_crash>destroy</on_crash>
  <devices>
    <disk type='block' device='disk'>
      <driver name='phy'/>
      <source dev='/var/lib/qubes/vm-templates/fedora-25/root.img:/var/lib/qubes/vm-templates/fedora-25/root-cow.img'/>
      <backingStore/>
      <target dev='xvda' bus='xen'/>
      <readonly/>
    </disk>
    <disk type='block' device='disk'>
      <driver name='phy'/>
      <source dev='/var/lib/qubes/appvms/test-vm/private.img'/>
      <backingStore/>
      <target dev='xvdb' bus='xen'/>
    </disk>
    <disk type='block' device='disk'>
      <driver name='phy'/>
      <source dev='/var/lib/qubes/appvms/test-vm/volatile.img'/>
      <backingStore/>
      <target dev='xvdc' bus='xen'/>
    </disk>
    {}
    <interface type='ethernet'>
      <mac address='00:16:3e:5e:6c:06'/>
      <ip address='10.137.1.8' family='ipv4'/>
      <script path='vif-route-qubes'/>
      <backenddomain name='sys-firewall'/>
    </interface>
    <console type='pty' tty='/dev/pts/0'>
      <source path='/dev/pts/0'/>
      <target type='xen' port='0'/>
    </console>
  </devices>
</domain>
'''


class TestQubesDB(object):
    def __init__(self, data):
        self._data = data

    def read(self, key):
        return self._data.get(key, None)

    def list(self, prefix):
        return [key for key in self._data if key.startswith(prefix)]


class TestApp(object):
    class Domains(dict):
        def __init__(self):
            super().__init__()

        def __iter__(self):
            return iter(self.values())

    def __init__(self):
        #: jinja2 environment for libvirt XML templates
        self.env = jinja2.Environment(
            loader=jinja2.FileSystemLoader([
                'templates',
                '/etc/qubes/templates',
                '/usr/share/qubes/templates',
            ]),
            undefined=jinja2.StrictUndefined,
            autoescape=True)
        self.domains = TestApp.Domains()
        self.vmm = mock.Mock()


class TestDeviceCollection(object):
    def __init__(self, backend_vm, devclass):
        self._exposed = []
        self._assigned = []
        self.backend_vm = backend_vm
        self.devclass = devclass

    def get_assigned_devices(self):
        return self._assigned

    def __getitem__(self, ident):
        for dev in self._exposed:
            if dev.ident == ident:
                return dev


class TestVM(qubes.tests.TestEmitter):
    def __init__(
            self, qdb, domain_xml=None, running=True, name='test-vm',
            *args, **kwargs):
        super(TestVM, self).__init__(*args, **kwargs)
        self.name = name
        self.untrusted_qdb = TestQubesDB(qdb)
        self.libvirt_domain = mock.Mock()
        self.features = mock.Mock()
        self.features.check_with_template.side_effect = (
                lambda name, default:
                    '4.2' if name == 'qubes-agent-version'
                    else None)
        self.is_running = lambda: running
        self.log = mock.Mock()
        self.app = TestApp()
        if domain_xml:
            self.libvirt_domain.configure_mock(**{
                'XMLDesc.return_value': domain_xml
            })
        self.devices = {
            'testclass': TestDeviceCollection(self, 'testclass')
        }

    def __eq__(self, other):
        if isinstance(other, TestVM):
            return self.name == other.name

    def __str__(self):
        return self.name


class TC_00_Block(qubes.tests.QubesTestCase):

    def setUp(self):
        super().setUp()
        self.ext = qubes.ext.block.BlockDeviceExtension()

    def test_000_device_get(self):
        vm = TestVM({
            '/qubes-block-devices/sda': b'',
            '/qubes-block-devices/sda/desc': b'Test_ (device)',
            '/qubes-block-devices/sda/size': b'1024000',
            '/qubes-block-devices/sda/mode': b'w',
            '/qubes-block-devices/sda/parent': b'1-1.1:1.0',
            }, domain_xml=domain_xml_template.format(""))
        parent = DeviceInfo(vm, '1-1.1', devclass='usb')
        vm.devices['usb'] = TestDeviceCollection(backend_vm=vm, devclass='usb')
        vm.devices['usb']._exposed.append(parent)
        vm.is_running = lambda: True

        dom0 = TestVM({}, name='dom0',
                      domain_xml=domain_xml_template.format(""))

        disk = '''
        <disk type="block" device="disk">
            <driver name="phy" />
            <source dev="/dev/sda" />
            <target dev="xvdi" />
            <readonly />
            <backenddomain name="test-vm" />
        </disk>
        '''
        front = TestVM({}, domain_xml=domain_xml_template.format(disk), name='front-vm')

        vm.app.domains[0] = dom0
        vm.app.domains['test-vm'] = vm
        vm.app.domains['front-vm'] = front
        front.app.domains = vm.app.domains
        dom0.app.domains = vm.app.domains

        device_info = self.ext.device_get(vm, 'sda')
        self.assertIsInstance(device_info, qubes.ext.block.BlockDevice)
        self.assertEqual(device_info.backend_domain, vm)
        self.assertEqual(device_info.ident, 'sda')
        self.assertEqual(device_info.name, 'device')
        self.assertEqual(device_info._name, 'device')
        self.assertEqual(device_info.serial, 'Test')
        self.assertEqual(device_info._serial, 'Test')
        self.assertEqual(device_info.size, 1024000)
        self.assertEqual(device_info.mode, 'w')
        self.assertEqual(device_info.manufacturer,
                         'sub-device of test-vm:1-1.1')
        self.assertEqual(device_info.device_node, '/dev/sda')
        self.assertEqual(device_info.interfaces,
                         [DeviceInterface("b******")])
        self.assertEqual(device_info.parent_device,
                         Device(vm, '1-1.1', devclass='usb'))
        self.assertEqual(device_info.attachment, front)
        self.assertEqual(device_info.self_identity,
                         '1-1.1:0000:0000::?******:1.0')
        self.assertEqual(
            device_info.data.get('test_frontend_domain', None), None)
        self.assertEqual(device_info.device_node, '/dev/sda')

    def test_001_device_get_other_node(self):
        vm = TestVM({
            '/qubes-block-devices/mapper_dmroot': b'',
            '/qubes-block-devices/mapper_dmroot/desc': b'Test_device',
            '/qubes-block-devices/mapper_dmroot/size': b'1024000',
            '/qubes-block-devices/mapper_dmroot/mode': b'w',
        })
        device_info = self.ext.device_get(vm, 'mapper_dmroot')
        self.assertIsInstance(device_info, qubes.ext.block.BlockDevice)
        self.assertEqual(device_info.backend_domain, vm)
        self.assertEqual(device_info.ident, 'mapper_dmroot')
        self.assertEqual(device_info._name, None)
        self.assertEqual(device_info.name, 'unknown')
        self.assertEqual(device_info.serial, 'Test device')
        self.assertEqual(device_info._serial, 'Test device')
        self.assertEqual(device_info.size, 1024000)
        self.assertEqual(device_info.mode, 'w')
        self.assertEqual(
            device_info.data.get('test_frontend_domain', None), None)
        self.assertEqual(device_info.device_node, '/dev/mapper/dmroot')

    def test_002_device_get_invalid_desc(self):
        vm = TestVM({
            '/qubes-block-devices/sda': b'',
            '/qubes-block-devices/sda/desc': b'Test (device<>za\xc4\x87abc)',
            '/qubes-block-devices/sda/size': b'1024000',
            '/qubes-block-devices/sda/mode': b'w',
        })
        device_info = self.ext.device_get(vm, 'sda')
        self.assertEqual(device_info.serial, 'Test')
        self.assertEqual(device_info.name, 'device  zaabc')

    def test_003_device_get_invalid_size(self):
        vm = TestVM({
            '/qubes-block-devices/sda': b'',
            '/qubes-block-devices/sda/desc': b'Test device',
            '/qubes-block-devices/sda/size': b'1024000abc',
            '/qubes-block-devices/sda/mode': b'w',
        })
        device_info = self.ext.device_get(vm, 'sda')
        self.assertEqual(device_info.size, 0)
        vm.log.warning.assert_called_once_with('Device sda has invalid size')

    def test_004_device_get_invalid_mode(self):
        vm = TestVM({
            '/qubes-block-devices/sda': b'',
            '/qubes-block-devices/sda/desc': b'Test device',
            '/qubes-block-devices/sda/size': b'1024000',
            '/qubes-block-devices/sda/mode': b'abc',
        })
        device_info = self.ext.device_get(vm, 'sda')
        self.assertEqual(device_info.mode, 'w')
        vm.log.warning.assert_called_once_with('Device sda has invalid mode')

    def test_005_device_get_none(self):
        vm = TestVM({
            '/qubes-block-devices/sda': b'',
            '/qubes-block-devices/sda/desc': b'Test device',
            '/qubes-block-devices/sda/size': b'1024000',
            '/qubes-block-devices/sda/mode': b'w',
        })
        device_info = self.ext.device_get(vm, 'sdb')
        self.assertIsNone(device_info)

    def test_010_devices_list(self):
        vm = TestVM({
            '/qubes-block-devices/sda': b'',
            '/qubes-block-devices/sda/desc': b'Test_device',
            '/qubes-block-devices/sda/size': b'1024000',
            '/qubes-block-devices/sda/mode': b'w',
            '/qubes-block-devices/sdb': b'',
            '/qubes-block-devices/sdb/desc': b'Test_device (2)',
            '/qubes-block-devices/sdb/size': b'2048000',
            '/qubes-block-devices/sdb/mode': b'r',
        })
        devices = sorted(list(self.ext.on_device_list_block(vm, '')))
        self.assertEqual(len(devices), 2)
        self.assertEqual(devices[0].backend_domain, vm)
        self.assertEqual(devices[0].ident, 'sda')
        self.assertEqual(devices[0].serial, 'Test device')
        self.assertEqual(devices[0].name, 'unknown')
        self.assertEqual(devices[0].size, 1024000)
        self.assertEqual(devices[0].mode, 'w')
        self.assertEqual(devices[1].backend_domain, vm)
        self.assertEqual(devices[1].ident, 'sdb')
        self.assertEqual(devices[1].serial, 'Test device')
        self.assertEqual(devices[1].name, '2')
        self.assertEqual(devices[1].size, 2048000)
        self.assertEqual(devices[1].mode, 'r')

    def test_011_devices_list_empty(self):
        vm = TestVM({})
        devices = sorted(list(self.ext.on_device_list_block(vm, '')))
        self.assertEqual(len(devices), 0)

    def test_012_devices_list_invalid_ident(self):
        vm = TestVM({
            '/qubes-block-devices/invalid ident': b'',
            '/qubes-block-devices/invalid+ident': b'',
            '/qubes-block-devices/invalid#': b'',
        })
        devices = sorted(list(self.ext.on_device_list_block(vm, '')))
        self.assertEqual(len(devices), 0)
        msg = 'test-vm vm\'s device path name contains unsafe characters. '\
              'Skipping it.'
        self.assertEqual(vm.log.warning.mock_calls, [
            mock.call(msg),
            mock.call(msg),
            mock.call(msg),
        ])

    def test_020_find_unused_frontend(self):
        vm = TestVM({}, domain_xml=domain_xml_template.format(''))
        frontend = self.ext.find_unused_frontend(vm)
        self.assertEqual(frontend, 'xvdi')

    def test_022_find_unused_frontend2(self):
        disk = '''
        <disk type="block" device="disk">
            <driver name="phy" />
            <source dev="/dev/sda" />
            <target dev="xvdi" />
            <readonly />
            <backenddomain name="sys-usb" />
        </disk>
        '''
        vm = TestVM({}, domain_xml=domain_xml_template.format(disk))
        frontend = self.ext.find_unused_frontend(vm)
        self.assertEqual(frontend, 'xvdj')

    def test_030_list_attached_empty(self):
        vm = TestVM({}, domain_xml=domain_xml_template.format(''))
        devices = sorted(list(self.ext.on_device_list_attached(vm, '')))
        self.assertEqual(len(devices), 0)

    def test_031_list_attached(self):
        disk = '''
        <disk type="block" device="disk">
            <driver name="phy" />
            <source dev="/dev/sda" />
            <target dev="xvdi" />
            <readonly />
            <backenddomain name="sys-usb" />
        </disk>
        '''
        vm = TestVM({}, domain_xml=domain_xml_template.format(disk))
        vm.app.domains['test-vm'] = vm
        vm.app.domains['sys-usb'] = TestVM({}, name='sys-usb')
        devices = sorted(list(self.ext.on_device_list_attached(vm, '')))
        self.assertEqual(len(devices), 1)
        dev = devices[0][0]
        options = devices[0][1]
        self.assertEqual(dev.backend_domain, vm.app.domains['sys-usb'])
        self.assertEqual(dev.ident, 'sda')
        self.assertEqual(dev.attachment, None)
        self.assertEqual(options['frontend-dev'], 'xvdi')
        self.assertEqual(options['read-only'], 'yes')

    def test_032_list_attached_dom0(self):
        disk = '''
        <disk type="block" device="disk">
            <driver name="phy" />
            <source dev="/dev/sda" />
            <target dev="xvdi" />
        </disk>
        '''
        vm = TestVM({}, domain_xml=domain_xml_template.format(disk))
        vm.app.domains['test-vm'] = vm
        vm.app.domains['sys-usb'] = TestVM({}, name='sys-usb')
        vm.app.domains['dom0'] = TestVM({}, name='dom0')
        vm.app.domains[0] = vm.app.domains['dom0']
        devices = sorted(list(self.ext.on_device_list_attached(vm, '')))
        self.assertEqual(len(devices), 1)
        dev = devices[0][0]
        options = devices[0][1]
        self.assertEqual(dev.backend_domain, vm.app.domains['dom0'])
        self.assertEqual(dev.ident, 'sda')
        self.assertEqual(options['frontend-dev'], 'xvdi')
        self.assertEqual(options['read-only'], 'no')

    def test_033_list_attached_cdrom(self):
        disk = '''
        <disk type="block" device="cdrom">
            <driver name="phy" />
            <source dev="/dev/sr0" />
            <target dev="xvdi" />
            <readonly />
            <backenddomain name="sys-usb" />
        </disk>
        '''
        vm = TestVM({}, domain_xml=domain_xml_template.format(disk))
        vm.app.domains['test-vm'] = vm
        vm.app.domains['sys-usb'] = TestVM({}, name='sys-usb')
        devices = sorted(list(self.ext.on_device_list_attached(vm, '')))
        self.assertEqual(len(devices), 1)
        dev = devices[0][0]
        options = devices[0][1]
        self.assertEqual(dev.backend_domain, vm.app.domains['sys-usb'])
        self.assertEqual(dev.ident, 'sr0')
        self.assertEqual(options['frontend-dev'], 'xvdi')
        self.assertEqual(options['read-only'], 'yes')
        self.assertEqual(options['devtype'], 'cdrom')

    def test_040_attach(self):
        back_vm = TestVM(name='sys-usb', qdb={
            '/qubes-block-devices/sda': b'',
            '/qubes-block-devices/sda/desc': b'Test device',
            '/qubes-block-devices/sda/size': b'1024000',
            '/qubes-block-devices/sda/mode': b'w',
        })
        vm = TestVM({}, domain_xml=domain_xml_template.format(''))
        dev = qubes.ext.block.BlockDevice(back_vm, 'sda')
        self.ext.on_device_pre_attached_block(vm, '', dev, {})
        device_xml = (
            '<disk type="block" device="disk">\n'
            '    <driver name="phy" />\n'
            '    <source dev="/dev/sda" />\n'
            '    <target dev="xvdi" />\n'
            '    <backenddomain name="sys-usb" />\n'
            '    <script path="/etc/xen/scripts/qubes-block" />\n'
            '</disk>')
        vm.libvirt_domain.attachDevice.assert_called_once_with(device_xml)

    def test_041_attach_frontend(self):
        back_vm = TestVM(name='sys-usb', qdb={
            '/qubes-block-devices/sda': b'',
            '/qubes-block-devices/sda/desc': b'Test device',
            '/qubes-block-devices/sda/size': b'1024000',
            '/qubes-block-devices/sda/mode': b'w',
        })
        vm = TestVM({}, domain_xml=domain_xml_template.format(''))
        dev = qubes.ext.block.BlockDevice(back_vm, 'sda')
        self.ext.on_device_pre_attached_block(vm, '', dev,
            {'frontend-dev': 'xvdj'})
        device_xml = (
            '<disk type="block" device="disk">\n'
            '    <driver name="phy" />\n'
            '    <source dev="/dev/sda" />\n'
            '    <target dev="xvdj" />\n'
            '    <backenddomain name="sys-usb" />\n'
            '    <script path="/etc/xen/scripts/qubes-block" />\n'
            '</disk>')
        vm.libvirt_domain.attachDevice.assert_called_once_with(device_xml)

    def test_042_attach_read_only(self):
        back_vm = TestVM(name='sys-usb', qdb={
            '/qubes-block-devices/sda': b'',
            '/qubes-block-devices/sda/desc': b'Test device',
            '/qubes-block-devices/sda/size': b'1024000',
            '/qubes-block-devices/sda/mode': b'w',
        })
        vm = TestVM({}, domain_xml=domain_xml_template.format(''))
        dev = qubes.ext.block.BlockDevice(back_vm, 'sda')
        self.ext.on_device_pre_attached_block(vm, '', dev,
            {'read-only': 'yes'})
        device_xml = (
            '<disk type="block" device="disk">\n'
            '    <driver name="phy" />\n'
            '    <source dev="/dev/sda" />\n'
            '    <target dev="xvdi" />\n'
            '    <readonly />\n'
            '    <backenddomain name="sys-usb" />\n'
            '    <script path="/etc/xen/scripts/qubes-block" />\n'
            '</disk>')
        vm.libvirt_domain.attachDevice.assert_called_once_with(device_xml)

    def test_043_attach_invalid_option(self):
        back_vm = TestVM(name='sys-usb', qdb={
            '/qubes-block-devices/sda': b'',
            '/qubes-block-devices/sda/desc': b'Test device',
            '/qubes-block-devices/sda/size': b'1024000',
            '/qubes-block-devices/sda/mode': b'w',
        })
        vm = TestVM({}, domain_xml=domain_xml_template.format(''))
        dev = qubes.ext.block.BlockDevice(back_vm, 'sda')
        with self.assertRaises(qubes.exc.QubesValueError):
            self.ext.on_device_pre_attached_block(vm, '', dev,
                {'no-such-option': '123'})
        self.assertFalse(vm.libvirt_domain.attachDevice.called)

    def test_044_attach_invalid_option2(self):
        back_vm = TestVM(name='sys-usb', qdb={
            '/qubes-block-devices/sda': b'',
            '/qubes-block-devices/sda/desc': b'Test device',
            '/qubes-block-devices/sda/size': b'1024000',
            '/qubes-block-devices/sda/mode': b'w',
        })
        vm = TestVM({}, domain_xml=domain_xml_template.format(''))
        dev = qubes.ext.block.BlockDevice(back_vm, 'sda')
        with self.assertRaises(qubes.exc.QubesValueError):
            self.ext.on_device_pre_attached_block(vm, '', dev,
                {'read-only': 'maybe'})
        self.assertFalse(vm.libvirt_domain.attachDevice.called)

    def test_045_attach_backend_not_running(self):
        back_vm = TestVM(name='sys-usb', running=False, qdb={
            '/qubes-block-devices/sda': b'',
            '/qubes-block-devices/sda/desc': b'Test device',
            '/qubes-block-devices/sda/size': b'1024000',
            '/qubes-block-devices/sda/mode': b'w',
        })
        vm = TestVM({}, domain_xml=domain_xml_template.format(''))
        dev = qubes.ext.block.BlockDevice(back_vm, 'sda')
        with self.assertRaises(qubes.exc.QubesVMNotRunningError):
            self.ext.on_device_pre_attached_block(vm, '', dev, {})
        self.assertFalse(vm.libvirt_domain.attachDevice.called)

    def test_046_attach_ro_dev_rw(self):
        back_vm = TestVM(name='sys-usb', qdb={
            '/qubes-block-devices/sda': b'',
            '/qubes-block-devices/sda/desc': b'Test device',
            '/qubes-block-devices/sda/size': b'1024000',
            '/qubes-block-devices/sda/mode': b'r',
        })
        vm = TestVM({}, domain_xml=domain_xml_template.format(''))
        dev = qubes.ext.block.BlockDevice(back_vm, 'sda')
        with self.assertRaises(qubes.exc.QubesValueError):
            self.ext.on_device_pre_attached_block(vm, '', dev,
                {'read-only': 'no'})
        self.assertFalse(vm.libvirt_domain.attachDevice.called)

    def test_047_attach_read_only_auto(self):
        back_vm = TestVM(name='sys-usb', qdb={
            '/qubes-block-devices/sda': b'',
            '/qubes-block-devices/sda/desc': b'Test device',
            '/qubes-block-devices/sda/size': b'1024000',
            '/qubes-block-devices/sda/mode': b'r',
        })
        vm = TestVM({}, domain_xml=domain_xml_template.format(''))
        dev = qubes.ext.block.BlockDevice(back_vm, 'sda')
        self.ext.on_device_pre_attached_block(vm, '', dev, {})
        device_xml = (
            '<disk type="block" device="disk">\n'
            '    <driver name="phy" />\n'
            '    <source dev="/dev/sda" />\n'
            '    <target dev="xvdi" />\n'
            '    <readonly />\n'
            '    <backenddomain name="sys-usb" />\n'
            '    <script path="/etc/xen/scripts/qubes-block" />\n'
            '</disk>')
        vm.libvirt_domain.attachDevice.assert_called_once_with(device_xml)

    def test_048_attach_cdrom_xvdi(self):
        back_vm = TestVM(name='sys-usb', qdb={
            '/qubes-block-devices/sda': b'',
            '/qubes-block-devices/sda/desc': b'Test device',
            '/qubes-block-devices/sda/size': b'1024000',
            '/qubes-block-devices/sda/mode': b'r',
        })
        vm = TestVM({}, domain_xml=domain_xml_template.format(modules_disk))
        dev = qubes.ext.block.BlockDevice(back_vm, 'sda')
        self.ext.on_device_pre_attached_block(vm, '', dev, {'devtype': 'cdrom'})
        device_xml = (
            '<disk type="block" device="cdrom">\n'
            '    <driver name="phy" />\n'
            '    <source dev="/dev/sda" />\n'
            '    <target dev="xvdi" />\n'
            '    <readonly />\n'
            '    <backenddomain name="sys-usb" />\n'
            '    <script path="/etc/xen/scripts/qubes-block" />\n'
            '</disk>')
        vm.libvirt_domain.attachDevice.assert_called_once_with(device_xml)

    def test_048_attach_cdrom_xvdd(self):
        back_vm = TestVM(name='sys-usb', qdb={
            '/qubes-block-devices/sda': b'',
            '/qubes-block-devices/sda/desc': b'Test device',
            '/qubes-block-devices/sda/size': b'1024000',
            '/qubes-block-devices/sda/mode': b'r',
        })
        vm = TestVM({}, domain_xml=domain_xml_template.format(''))
        dev = qubes.ext.block.BlockDevice(back_vm, 'sda')
        self.ext.on_device_pre_attached_block(vm, '', dev, {'devtype': 'cdrom'})
        device_xml = (
            '<disk type="block" device="cdrom">\n'
            '    <driver name="phy" />\n'
            '    <source dev="/dev/sda" />\n'
            '    <target dev="xvdd" />\n'
            '    <readonly />\n'
            '    <backenddomain name="sys-usb" />\n'
            '    <script path="/etc/xen/scripts/qubes-block" />\n'
            '</disk>')
        vm.libvirt_domain.attachDevice.assert_called_once_with(device_xml)

    def test_050_detach(self):
        back_vm = TestVM(name='sys-usb', qdb={
            '/qubes-block-devices/sda': b'',
            '/qubes-block-devices/sda/desc': b'Test device',
            '/qubes-block-devices/sda/size': b'1024000',
            '/qubes-block-devices/sda/mode': b'r',
        })
        device_xml = (
            '<disk type="block" device="disk">\n'
            '    <driver name="phy" />\n'
            '    <source dev="/dev/sda" />\n'
            '    <target dev="xvdi" />\n'
            '    <readonly />\n'
            '    <backenddomain name="sys-usb" />\n'
            '    <script path="/etc/xen/scripts/qubes-block" />\n'
            '</disk>')
        vm = TestVM({}, domain_xml=domain_xml_template.format(device_xml))
        vm.app.domains['test-vm'] = vm
        vm.app.domains['sys-usb'] = TestVM({}, name='sys-usb')
        dev = qubes.ext.block.BlockDevice(back_vm, 'sda')
        self.ext.on_device_pre_detached_block(vm, '', dev)
        vm.libvirt_domain.detachDevice.assert_called_once_with(device_xml)

    def test_051_detach_not_attached(self):
        back_vm = TestVM(name='sys-usb', qdb={
            '/qubes-block-devices/sda': b'',
            '/qubes-block-devices/sda/desc': b'Test device',
            '/qubes-block-devices/sda/size': b'1024000',
            '/qubes-block-devices/sda/mode': b'r',
        })
        vm = TestVM({}, domain_xml=domain_xml_template.format(''))
        vm.app.domains['test-vm'] = vm
        vm.app.domains['sys-usb'] = TestVM({}, name='sys-usb')
        dev = qubes.ext.block.BlockDevice(back_vm, 'sda')
        self.ext.on_device_pre_detached_block(vm, '', dev)
        self.assertFalse(vm.libvirt_domain.detachDevice.called)

    def test_060_on_qdb_change_added(self):
        back_vm = TestVM(name='sys-usb', qdb={
            '/qubes-block-devices/sda': b'',
            '/qubes-block-devices/sda/desc': b'Test device',
            '/qubes-block-devices/sda/size': b'1024000',
            '/qubes-block-devices/sda/mode': b'r',
        }, domain_xml=domain_xml_template.format(""))
        exp_dev = Device(back_vm, 'sda', 'block')

        self.ext.on_qdb_change(back_vm, None, None)

        self.assertEqual(self.ext.devices_cache, {'sys-usb': {'sda': None}})
        self.assertEqual(
            back_vm.fired_events[
                ('device-added:block', frozenset({('device', exp_dev)}))],1)

    def test_061_on_qdb_change_auto_attached(self):
        back_vm = TestVM(name='sys-usb', qdb={
            '/qubes-block-devices/sda': b'',
            '/qubes-block-devices/sda/desc': b'Test device',
            '/qubes-block-devices/sda/size': b'1024000',
            '/qubes-block-devices/sda/mode': b'r',
        }, domain_xml=domain_xml_template.format(""))
        exp_dev = Device(back_vm, 'sda', 'block')
        front = TestVM({}, domain_xml=domain_xml_template.format(""),
                       name='front-vm')
        dom0 = TestVM({}, name='dom0',
                      domain_xml=domain_xml_template.format(""))
        back_vm.app.domains['sys-usb'] = back_vm
        back_vm.app.domains['front-vm'] = front
        back_vm.app.domains[0] = dom0
        front.app = back_vm.app
        dom0.app = back_vm.app

        back_vm.app.vmm.configure_mock(**{'offline_mode': False})
        fire_event_async = mock.Mock()
        front.fire_event_async = fire_event_async

        back_vm.devices['block'] = TestDeviceCollection(
            backend_vm=back_vm, devclass='block')
        front.devices['block'] = TestDeviceCollection(
            backend_vm=front, devclass='block')
        dom0.devices['block'] = TestDeviceCollection(
            backend_vm=dom0, devclass='block')

        front.devices['block']._assigned.append(
            DeviceAssignment.from_device(exp_dev))
        back_vm.devices['block']._exposed.append(
            qubes.ext.block.BlockDevice(back_vm, 'sda'))

        # In the case of block devices it is the same,
        # but notify_auto_attached is synchronous
        self.ext.attach_and_notify = self.ext.notify_auto_attached
        with mock.patch('asyncio.ensure_future'):
            self.ext.on_qdb_change(back_vm, None, None)
        self.assertEqual(self.ext.devices_cache, {'sys-usb': {'sda': front}})
        fire_event_async.assert_called_once_with(
            'device-attach:block', device=exp_dev,
            options={'read-only': 'yes', 'frontend-dev': 'xvdi'})

    def test_062_on_qdb_change_attached(self):
        # added
        back_vm = TestVM(name='sys-usb', qdb={
            '/qubes-block-devices/sda': b'',
            '/qubes-block-devices/sda/desc': b'Test device',
            '/qubes-block-devices/sda/size': b'1024000',
            '/qubes-block-devices/sda/mode': b'r',
        }, domain_xml=domain_xml_template.format(""))
        exp_dev = Device(back_vm, 'sda', 'block')

        self.ext.devices_cache = {'sys-usb': {'sda': None}}

        # then attached
        disk = '''
                <disk type="block" device="disk">
                    <driver name="phy" />
                    <source dev="/dev/sda" />
                    <target dev="xvdi" />
                    <readonly />
                    <backenddomain name="sys-usb" />
                </disk>
                '''
        front = TestVM({}, domain_xml=domain_xml_template.format(disk),
                       name='front-vm')
        dom0 = TestVM({}, name='dom0',
                      domain_xml=domain_xml_template.format(""))
        back_vm.app.domains['sys-usb'] = back_vm
        back_vm.app.domains['front-vm'] = front
        back_vm.app.domains[0] = dom0
        front.app = back_vm.app
        dom0.app = back_vm.app

        back_vm.app.vmm.configure_mock(**{'offline_mode': False})
        fire_event_async = mock.Mock()
        front.fire_event_async = fire_event_async

        back_vm.devices['block'] = TestDeviceCollection(
            backend_vm=back_vm, devclass='block')
        front.devices['block'] = TestDeviceCollection(
            backend_vm=front, devclass='block')
        dom0.devices['block'] = TestDeviceCollection(
            backend_vm=dom0, devclass='block')

        with mock.patch('asyncio.ensure_future'):
            self.ext.on_qdb_change(back_vm, None, None)
        self.assertEqual(self.ext.devices_cache, {'sys-usb': {'sda': front}})
        fire_event_async.assert_called_once_with(
            'device-attach:block', device=exp_dev, options={})

    def test_063_on_qdb_change_changed(self):
        # attached to front-vm
        back_vm = TestVM(name='sys-usb', qdb={
            '/qubes-block-devices/sda': b'',
            '/qubes-block-devices/sda/desc': b'Test device',
            '/qubes-block-devices/sda/size': b'1024000',
            '/qubes-block-devices/sda/mode': b'r',
        }, domain_xml=domain_xml_template.format(""))
        exp_dev = Device(back_vm, 'sda', 'block')

        front = TestVM({}, name='front-vm')
        dom0 = TestVM({}, name='dom0',
                      domain_xml=domain_xml_template.format(""))

        self.ext.devices_cache = {'sys-usb': {'sda': front}}

        disk = '''
            <disk type="block" device="disk">
                <driver name="phy" />
                <source dev="/dev/sda" />
                <target dev="xvdi" />
                <readonly />
                <backenddomain name="sys-usb" />
            </disk>
            '''
        front_2 = TestVM({}, domain_xml=domain_xml_template.format(disk),
                         name='front-2')

        back_vm.app.vmm.configure_mock(**{'offline_mode': False})
        front.libvirt_domain.configure_mock(**{
            'XMLDesc.return_value': domain_xml_template.format("")
        })

        back_vm.app.domains['sys-usb'] = back_vm
        back_vm.app.domains['front-vm'] = front
        back_vm.app.domains['front-2'] = front_2
        back_vm.app.domains[0] = dom0

        front.app = back_vm.app
        front_2.app = back_vm.app
        dom0.app = back_vm.app

        fire_event_async = mock.Mock()
        front.fire_event_async = fire_event_async
        fire_event_async_2 = mock.Mock()
        front_2.fire_event_async = fire_event_async_2

        back_vm.devices['block'] = TestDeviceCollection(
            backend_vm=back_vm, devclass='block')
        front.devices['block'] = TestDeviceCollection(
            backend_vm=front, devclass='block')
        dom0.devices['block'] = TestDeviceCollection(
            backend_vm=dom0, devclass='block')
        front_2.devices['block'] = TestDeviceCollection(
            backend_vm=front_2, devclass='block')

        with mock.patch('asyncio.ensure_future'):
            self.ext.on_qdb_change(back_vm, None, None)

        self.assertEqual(self.ext.devices_cache, {'sys-usb': {'sda': front_2}})
        fire_event_async.assert_called_with(
            'device-detach:block', device=exp_dev)
        fire_event_async_2.assert_called_once_with(
            'device-attach:block', device=exp_dev, options={})

    def test_064_on_qdb_change_removed_attached(self):
        # attached to front-vm
        back_vm = TestVM(name='sys-usb', qdb={
            '/qubes-block-devices/sda': b'',
            '/qubes-block-devices/sda/desc': b'Test device',
            '/qubes-block-devices/sda/size': b'1024000',
            '/qubes-block-devices/sda/mode': b'r',
        }, domain_xml=domain_xml_template.format(""))
        dom0 = TestVM({}, name='dom0',
                      domain_xml=domain_xml_template.format(""))
        exp_dev = Device(back_vm, 'sda', 'block')

        disk = '''
            <disk type="block" device="disk">
                <driver name="phy" />
                <source dev="/dev/sda" />
                <target dev="xvdi" />
                <readonly />
                <backenddomain name="sys-usb" />
            </disk>
            '''
        front = TestVM({}, domain_xml=domain_xml_template.format(disk),
                         name='front')
        self.ext.devices_cache = {'sys-usb': {'sda': front}}

        back_vm.app.vmm.configure_mock(**{'offline_mode': False})
        front.libvirt_domain.configure_mock(**{
            'XMLDesc.return_value': domain_xml_template.format("")
        })

        back_vm.app.domains['sys-usb'] = back_vm
        back_vm.app.domains['front-vm'] = front
        back_vm.app.domains[0] = dom0

        front.app = back_vm.app
        dom0.app = back_vm.app

        fire_event_async = mock.Mock()
        front.fire_event_async = fire_event_async

        back_vm.devices['block'] = TestDeviceCollection(
            backend_vm=back_vm, devclass='block')
        front.devices['block'] = TestDeviceCollection(
            backend_vm=front, devclass='block')
        dom0.devices['block'] = TestDeviceCollection(
            backend_vm=dom0, devclass='block')

        back_vm.untrusted_qdb = TestQubesDB({})
        with mock.patch('asyncio.ensure_future'):
            self.ext.on_qdb_change(back_vm, None, None)
        self.assertEqual(self.ext.devices_cache, {'sys-usb': {}})
        fire_event_async.assert_called_with(
            'device-detach:block', device=exp_dev)
        self.assertEqual(
            back_vm.fired_events[
                ('device-removed:block', frozenset({('device', exp_dev)}))],
            1)
