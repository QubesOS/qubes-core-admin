# pylint: disable=protected-access

#
# The Qubes OS Project, https://www.qubes-os.org/
#
# Copyright (C) 2014-2015  Joanna Rutkowska <joanna@invisiblethingslab.com>
# Copyright (C) 2014-2015  Wojtek Porczyk <woju@invisiblethingslab.com>
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

import os

import unittest
import uuid
import datetime
import lxml.etree
import unittest.mock

import qubes
import qubes.exc
import qubes.config
import qubes.vm
import qubes.vm.qubesvm

import qubes.tests
import qubes.tests.vm

class TestApp(object):
    labels = {1: qubes.Label(1, '0xcc0000', 'red')}

    def __init__(self):
        self.domains = {}

class TestProp(object):
    # pylint: disable=too-few-public-methods
    __name__ = 'testprop'

class TestVM(object):
    # pylint: disable=too-few-public-methods
    app = TestApp()

    def __init__(self, **kwargs):
        self.running = False
        self.installed_by_rpm = False
        for k, v in kwargs.items():
            setattr(self, k, v)

    def is_running(self):
        return self.running


class TC_00_setters(qubes.tests.QubesTestCase):
    def setUp(self):
        super().setUp()
        self.vm = TestVM()
        self.prop = TestProp()


    def test_000_setter_qid(self):
        self.assertEqual(
            qubes.vm._setter_qid(self.vm, self.prop, 5), 5)

    def test_001_setter_qid_lt_0(self):
        with self.assertRaises(ValueError):
            qubes.vm._setter_qid(self.vm, self.prop, -1)

    def test_002_setter_qid_gt_max(self):
        with self.assertRaises(ValueError):
            qubes.vm._setter_qid(self.vm,
                self.prop, qubes.config.max_qid + 5)

    @unittest.skip('test not implemented')
    def test_020_setter_kernel(self):
        pass


    def test_030_setter_label_object(self):
        label = TestApp.labels[1]
        self.assertIs(label,
            qubes.vm.setter_label(self.vm, self.prop, label))

    def test_031_setter_label_getitem(self):
        label = TestApp.labels[1]
        self.assertIs(label,
            qubes.vm.setter_label(self.vm, self.prop, 'label-1'))

    # there is no check for self.app.get_label()

    def test_040_setter_virt_mode(self):
        self.assertEqual(
            qubes.vm.qubesvm._setter_virt_mode(self.vm, self.prop, 'hvm'),
            'hvm')
        self.assertEqual(
            qubes.vm.qubesvm._setter_virt_mode(self.vm, self.prop, 'HVM'),
            'hvm')
        self.assertEqual(
            qubes.vm.qubesvm._setter_virt_mode(self.vm, self.prop, 'PV'),
            'pv')
        with self.assertRaises(ValueError):
            qubes.vm.qubesvm._setter_virt_mode(self.vm, self.prop, 'True')


class QubesVMTestsMixin(object):
    property_no_default = object()

    def setUp(self):
        super(QubesVMTestsMixin, self).setUp()
        self.app = qubes.tests.vm.TestApp()
        self.app.vmm.offline_mode = True

    def get_vm(self, name='test', **kwargs):
        vm = qubes.vm.qubesvm.QubesVM(self.app, None,
            qid=1, name=qubes.tests.VMPREFIX + name,
            **kwargs)
        self.addCleanup(vm.close)
        return vm

    def assertPropertyValue(self, vm, prop_name, set_value, expected_value,
            expected_xml_content=None):
        # FIXME: any better exception list? or maybe all of that should be a
        # single exception?
        with self.assertNotRaises((ValueError, TypeError, KeyError)):
            setattr(vm, prop_name, set_value)
        self.assertEqual(getattr(vm, prop_name), expected_value)
        if expected_xml_content is not None:
            xml = vm.__xml__()
            prop_xml = xml.xpath(
                './properties/property[@name=\'{}\']'.format(prop_name))
            self.assertEqual(len(prop_xml), 1, "Property not found in XML")
            self.assertEqual(prop_xml[0].text, expected_xml_content)

    def assertPropertyInvalidValue(self, vm, prop_name, set_value):
        orig_value_set = True
        orig_value = None
        try:
            orig_value = getattr(vm, prop_name)
        except AttributeError:
            orig_value_set = False
        # FIXME: any better exception list? or maybe all of that should be a
        # single exception?
        with self.assertRaises((ValueError, TypeError, KeyError)):
            setattr(vm, prop_name, set_value)
        if orig_value_set:
            self.assertEqual(getattr(vm, prop_name), orig_value)
        else:
            with self.assertRaises(AttributeError):
                getattr(vm, prop_name)

    def assertPropertyDefaultValue(self, vm, prop_name,
            expected_default=property_no_default):
        if expected_default is self.property_no_default:
            with self.assertRaises(AttributeError):
                getattr(vm, prop_name)
        else:
            with self.assertNotRaises(AttributeError):
                self.assertEqual(getattr(vm, prop_name), expected_default)
        xml = vm.__xml__()
        prop_xml = xml.xpath(
            './properties/property[@name=\'{}\']'.format(prop_name))
        self.assertEqual(len(prop_xml), 0, "Property still found in XML")

    def _test_generic_bool_property(self, vm, prop_name, default=False):
        self.assertPropertyDefaultValue(vm, prop_name, default)
        self.assertPropertyValue(vm, prop_name, False, False, 'False')
        self.assertPropertyValue(vm, prop_name, True, True, 'True')
        delattr(vm, prop_name)
        self.assertPropertyDefaultValue(vm, prop_name, default)
        self.assertPropertyValue(vm, prop_name, 'True', True, 'True')
        self.assertPropertyValue(vm, prop_name, 'False', False, 'False')
        self.assertPropertyInvalidValue(vm, prop_name, 'xxx')
        self.assertPropertyValue(vm, prop_name, 123, True)
        self.assertPropertyInvalidValue(vm, prop_name, '')


class TC_90_QubesVM(QubesVMTestsMixin, qubes.tests.QubesTestCase):
    def test_000_init(self):
        self.get_vm()

    def test_001_init_no_qid_or_name(self):
        with self.assertRaises(AssertionError):
            qubes.vm.qubesvm.QubesVM(self.app, None,
                name=qubes.tests.VMPREFIX + 'test')
        with self.assertRaises(AssertionError):
            qubes.vm.qubesvm.QubesVM(self.app, None,
                qid=1)

    def test_003_init_fire_domain_init(self):
        class TestVM2(qubes.vm.qubesvm.QubesVM):
            event_fired = False
            @qubes.events.handler('domain-init')
            def on_domain_init(self, event): # pylint: disable=unused-argument
                self.__class__.event_fired = True

        TestVM2(self.app, None, qid=1, name=qubes.tests.VMPREFIX + 'test')
        self.assertTrue(TestVM2.event_fired)

    def test_004_uuid_autogen(self):
        vm = self.get_vm()
        self.assertTrue(hasattr(vm, 'uuid'))

    def test_100_qid(self):
        vm = self.get_vm()
        self.assertIsInstance(vm.qid, int)
        with self.assertRaises(AttributeError):
            vm.qid = 2

    def test_110_name(self):
        vm = self.get_vm()
        self.assertIsInstance(vm.name, str)

    def test_120_uuid(self):
        my_uuid = uuid.uuid4()
        vm = self.get_vm(uuid=my_uuid)
        self.assertIsInstance(vm.uuid, uuid.UUID)
        self.assertIs(vm.uuid, my_uuid)
        with self.assertRaises(AttributeError):
            vm.uuid = uuid.uuid4()

    @unittest.skip('TODO: how to not fail on making an icon symlink here?')
    def test_130_label(self):
        vm = self.get_vm()
        self.assertPropertyDefaultValue(vm, 'label')
        self.assertPropertyValue(vm, 'label', self.app.labels[1],
            self.app.labels[1], 'label-1')
        del vm.label
        self.assertPropertyDefaultValue(vm, 'label')
        self.assertPropertyValue(vm, 'label', 'red',
            self.app.labels[1], 'label-1')
        self.assertPropertyValue(vm, 'label', 'label-1',
            self.app.labels[1], 'label-1')

    def test_131_label_invalid(self):
        vm = self.get_vm()
        self.assertPropertyInvalidValue(vm, 'label', 'invalid')
        self.assertPropertyInvalidValue(vm, 'label', 123)

    def test_160_memory(self):
        vm = self.get_vm()
        self.assertPropertyDefaultValue(vm, 'memory', 400)
        self.assertPropertyValue(vm, 'memory', 500, 500, '500')
        del vm.memory
        self.assertPropertyDefaultValue(vm, 'memory', 400)
        self.assertPropertyValue(vm, 'memory', '500', 500, '500')

    def test_161_memory_invalid(self):
        vm = self.get_vm()
        self.assertPropertyInvalidValue(vm, 'memory', -100)
        self.assertPropertyInvalidValue(vm, 'memory', '-100')
        self.assertPropertyInvalidValue(vm, 'memory', '')
        # TODO: higher than maxmem
        # TODO: human readable setter (500M, 4G)?

    def test_170_maxmem(self):
        vm = self.get_vm()
        self.assertPropertyDefaultValue(vm, 'maxmem',
            self.app.host.memory_total / 1024 / 2)
        self.assertPropertyValue(vm, 'maxmem', 500, 500, '500')
        del vm.maxmem
        self.assertPropertyDefaultValue(vm, 'maxmem',
            self.app.host.memory_total / 1024 / 2)
        self.assertPropertyValue(vm, 'maxmem', '500', 500, '500')

    def test_171_maxmem_invalid(self):
        vm = self.get_vm()
        self.assertPropertyInvalidValue(vm, 'maxmem', -100)
        self.assertPropertyInvalidValue(vm, 'maxmem', '-100')
        self.assertPropertyInvalidValue(vm, 'maxmem', '')
        # TODO: lower than memory
        # TODO: human readable setter (500M, 4G)?

    def test_190_vcpus(self):
        vm = self.get_vm()
        self.assertPropertyDefaultValue(vm, 'vcpus', 2)
        self.assertPropertyValue(vm, 'vcpus', 3, 3, '3')
        del vm.vcpus
        self.assertPropertyDefaultValue(vm, 'vcpus', 2)
        self.assertPropertyValue(vm, 'vcpus', '3', 3, '3')

    def test_191_vcpus_invalid(self):
        vm = self.get_vm()
        self.assertPropertyInvalidValue(vm, 'vcpus', 0)
        self.assertPropertyInvalidValue(vm, 'vcpus', -2)
        self.assertPropertyInvalidValue(vm, 'vcpus', '-2')
        self.assertPropertyInvalidValue(vm, 'vcpus', '')

    def test_200_debug(self):
        vm = self.get_vm()
        self._test_generic_bool_property(vm, 'debug', False)

    def test_210_installed_by_rpm(self):
        vm = self.get_vm()
        self._test_generic_bool_property(vm, 'installed_by_rpm', False)

    def test_220_include_in_backups(self):
        vm = self.get_vm()
        self._test_generic_bool_property(vm, 'include_in_backups', True)

    @qubes.tests.skipUnlessDom0
    def test_250_kernel(self):
        kernels = os.listdir(os.path.join(
            qubes.config.qubes_base_dir,
            qubes.config.system_path['qubes_kernels_base_dir']))
        if not len(kernels):
            self.skipTest('Needs at least one kernel installed')
        self.app.default_kernel = kernels[0]
        vm = self.get_vm()
        self.assertPropertyDefaultValue(vm, 'kernel', kernels[0])
        self.assertPropertyValue(vm, 'kernel', kernels[-1], kernels[-1],
            kernels[-1])
        del vm.kernel
        self.assertPropertyDefaultValue(vm, 'kernel', kernels[0])

    @qubes.tests.skipUnlessDom0
    def test_251_kernel_invalid(self):
        vm = self.get_vm()
        self.assertPropertyInvalidValue(vm, 'kernel', 123)
        self.assertPropertyInvalidValue(vm, 'kernel', 'invalid')

    def test_252_kernel_empty(self):
        vm = self.get_vm()
        self.assertPropertyValue(vm, 'kernel', '', '', '')
        self.assertPropertyValue(vm, 'kernel', None, '', '')

    def test_260_kernelopts(self):
        vm = self.get_vm()
        self.assertPropertyDefaultValue(vm, 'kernelopts',
            qubes.config.defaults['kernelopts'])
        self.assertPropertyValue(vm, 'kernelopts', 'some options',
            'some options', 'some options')
        del vm.kernelopts
        self.assertPropertyDefaultValue(vm, 'kernelopts',
            qubes.config.defaults['kernelopts'])
        self.assertPropertyValue(vm, 'kernelopts', '',
            '', '')
        # TODO?
        # self.assertPropertyInvalidValue(vm, 'kernelopts', None),

    @unittest.skip('test not implemented')
    def test_261_kernelopts_pcidevs(self):
        vm = self.get_vm()
        # how to do that here? use dummy DeviceManager/DeviceCollection?
        # Disable events?
        vm.devices['pci'].attach('something')
        self.assertPropertyDefaultValue(vm, 'kernelopts',
            qubes.config.defaults['kernelopts_pcidevs'])

    def test_270_qrexec_timeout(self):
        vm = self.get_vm()
        self.assertPropertyDefaultValue(vm, 'qrexec_timeout', 60)
        self.assertPropertyValue(vm, 'qrexec_timeout', 3, 3, '3')
        del vm.qrexec_timeout
        self.assertPropertyDefaultValue(vm, 'qrexec_timeout', 60)
        self.assertPropertyValue(vm, 'qrexec_timeout', '3', 3, '3')

    def test_271_qrexec_timeout_invalid(self):
        vm = self.get_vm()
        self.assertPropertyInvalidValue(vm, 'qrexec_timeout', -2)
        self.assertPropertyInvalidValue(vm, 'qrexec_timeout', '-2')
        self.assertPropertyInvalidValue(vm, 'qrexec_timeout', '')

    def test_280_autostart(self):
        vm = self.get_vm()
        # FIXME any better idea to not involve systemctl call at this stage?
        vm.events_enabled = False
        self._test_generic_bool_property(vm, 'autostart', False)

    @qubes.tests.skipUnlessDom0
    def test_281_autostart_systemd(self):
        vm = self.get_vm()
        self.assertFalse(os.path.exists(
            '/etc/systemd/system/multi-user.target.wants/'
            'qubes-vm@{}.service'.format(vm.name)),
            "systemd service enabled before setting autostart")
        vm.autostart = True
        self.assertTrue(os.path.exists(
            '/etc/systemd/system/multi-user.target.wants/'
            'qubes-vm@{}.service'.format(vm.name)),
            "systemd service not enabled by autostart=True")
        vm.autostart = False
        self.assertFalse(os.path.exists(
            '/etc/systemd/system/multi-user.target.wants/'
            'qubes-vm@{}.service'.format(vm.name)),
            "systemd service not disabled by autostart=False")
        vm.autostart = True
        del vm.autostart
        self.assertFalse(os.path.exists(
            '/etc/systemd/system/multi-user.target.wants/'
            'qubes-vm@{}.service'.format(vm.name)),
            "systemd service not disabled by resetting autostart")

    @unittest.skip('TODO')
    def test_320_seamless_gui_mode(self):
        vm = self.get_vm()
        self._test_generic_bool_property(vm, 'seamless_gui_mode')
        # TODO: reject setting to True when guiagent_installed is false

    def test_330_mac(self):
        vm = self.get_vm()
        # TODO: calculate proper default here
        default_mac = vm.mac
        self.assertIsNotNone(default_mac)
        self.assertPropertyDefaultValue(vm, 'mac', default_mac)
        self.assertPropertyValue(vm, 'mac', '00:11:22:33:44:55',
            '00:11:22:33:44:55', '00:11:22:33:44:55')
        del vm.mac
        self.assertPropertyDefaultValue(vm, 'mac', default_mac)

    def test_331_mac_invalid(self):
        vm = self.get_vm()
        self.assertPropertyInvalidValue(vm, 'mac', 123)
        self.assertPropertyInvalidValue(vm, 'mac', 'invalid')
        self.assertPropertyInvalidValue(vm, 'mac', '00:11:22:33:44:55:66')

    def test_340_default_user(self):
        vm = self.get_vm()
        self.assertPropertyDefaultValue(vm, 'default_user', 'user')
        self.assertPropertyValue(vm, 'default_user', 'someuser', 'someuser',
            'someuser')
        del vm.default_user
        self.assertPropertyDefaultValue(vm, 'default_user', 'user')
        self.assertPropertyValue(vm, 'default_user', 123, '123', '123')
        # TODO: check propagation for template-based VMs

    @unittest.skip('TODO')
    def test_350_timezone(self):
        vm = self.get_vm()
        self.assertPropertyDefaultValue(vm, 'timezone', 'localtime')
        self.assertPropertyValue(vm, 'timezone', 0, 0, '0')
        del vm.timezone
        self.assertPropertyDefaultValue(vm, 'timezone', 'localtime')
        self.assertPropertyValue(vm, 'timezone', '0', 0, '0')
        self.assertPropertyValue(vm, 'timezone', -3600, -3600, '-3600')
        self.assertPropertyValue(vm, 'timezone', 7200, 7200, '7200')

    @unittest.skip('TODO')
    def test_350_timezone_invalid(self):
        vm = self.get_vm()
        self.assertPropertyInvalidValue(vm, 'timezone', 'xxx')

    @unittest.skip('TODO')
    def test_360_drive(self):
        vm = self.get_vm()
        self.assertPropertyDefaultValue(vm, 'drive', None)
        # self.execute_tests('drive', [
        #     ('hd:dom0:/tmp/drive.img', 'hd:dom0:/tmp/drive.img', True),
        #     ('hd:/tmp/drive.img', 'hd:dom0:/tmp/drive.img', True),
        #     ('cdrom:dom0:/tmp/drive.img', 'cdrom:dom0:/tmp/drive.img', True),
        #     ('cdrom:/tmp/drive.img', 'cdrom:dom0:/tmp/drive.img', True),
        #     ('/tmp/drive.img', 'cdrom:dom0:/tmp/drive.img', True),
        #     ('hd:drive.img', '', False),
        #     ('drive.img', '', False),
        # ])

    def test_400_backup_timestamp(self):
        vm = self.get_vm()
        timestamp = datetime.datetime(2016, 1, 1, 12, 14, 2)
        timestamp_str = timestamp.strftime('%s')
        self.assertPropertyDefaultValue(vm, 'backup_timestamp', None)
        self.assertPropertyValue(vm, 'backup_timestamp', timestamp,
            timestamp, timestamp_str)
        del vm.backup_timestamp
        self.assertPropertyDefaultValue(vm, 'backup_timestamp', None)
        self.assertPropertyValue(vm, 'backup_timestamp', timestamp_str,
            timestamp)

    def test_401_backup_timestamp_invalid(self):
        vm = self.get_vm()
        self.assertPropertyInvalidValue(vm, 'backup_timestamp', 'xxx')
        self.assertPropertyInvalidValue(vm, 'backup_timestamp', None)

    def test_500_property_migrate_virt_mode(self):
        xml_template = '''
        <domain class="QubesVM" id="domain-1">
            <properties>
                <property name="qid">1</property>
                <property name="name">testvm</property>
                <property name="label" ref="label-1" />
                <property name="hvm">{hvm_value}</property>
            </properties>
        </domain>
        '''
        xml = lxml.etree.XML(xml_template.format(hvm_value='True'))
        vm = qubes.vm.qubesvm.QubesVM(self.app, xml)
        self.assertEqual(vm.virt_mode, 'hvm')
        with self.assertRaises(AttributeError):
            vm.hvm

        xml = lxml.etree.XML(xml_template.format(hvm_value='False'))
        vm = qubes.vm.qubesvm.QubesVM(self.app, xml)
        self.assertEqual(vm.virt_mode, 'pv')
        with self.assertRaises(AttributeError):
            vm.hvm

    def test_600_libvirt_xml_pv(self):
        expected = '''<domain type="xen">
        <name>test-inst-test</name>
        <uuid>7db78950-c467-4863-94d1-af59806384ea</uuid>
        <memory unit="MiB">500</memory>
        <currentMemory unit="MiB">400</currentMemory>
        <vcpu placement="static">2</vcpu>
        <os>
            <type arch="x86_64" machine="xenpv">linux</type>
            <kernel>/tmp/kernel/vmlinuz</kernel>
            <initrd>/tmp/kernel/initramfs</initrd>
            <cmdline>root=/dev/mapper/dmroot ro nomodeset console=hvc0 rd_NO_PLYMOUTH rd.plymouth.enable=0 plymouth.enable=0 nopat</cmdline>
        </os>
        <features>
        </features>
        <clock offset='utc' adjustment='reset'>
            <timer name="tsc" mode="native"/>
        </clock>
        <on_poweroff>destroy</on_poweroff>
        <on_reboot>destroy</on_reboot>
        <on_crash>destroy</on_crash>
        <devices>
            <disk type="block" device="disk">
                <driver name="phy" />
                <source dev="/tmp/kernel/modules.img" />
                <target dev="xvdd" />
                <backenddomain name="dom0" />
            </disk>
            <console type="pty">
                <target type="xen" port="0"/>
            </console>
        </devices>
        </domain>
        '''
        my_uuid = '7db78950-c467-4863-94d1-af59806384ea'
        vm = self.get_vm(uuid=my_uuid)
        vm.netvm = None
        vm.virt_mode = 'pv'
        # tests for storage are later
        vm.volumes['kernel'] = unittest.mock.Mock(**{
            'kernels_dir': '/tmp/kernel',
            'block_device.return_value.domain': 'dom0',
            'block_device.return_value.script': None,
            'block_device.return_value.path': '/tmp/kernel/modules.img',
            'block_device.return_value.devtype': 'disk',
            'block_device.return_value.name': 'kernel',
        })
        libvirt_xml = vm.create_config_file()
        self.assertXMLEqual(lxml.etree.XML(libvirt_xml),
            lxml.etree.XML(expected))

    def test_600_libvirt_xml_hvm(self):
        expected = '''<domain type="xen">
        <name>test-inst-test</name>
        <uuid>7db78950-c467-4863-94d1-af59806384ea</uuid>
        <memory unit="MiB">500</memory>
        <currentMemory unit="MiB">400</currentMemory>
        <vcpu placement="static">2</vcpu>
        <cpu mode='host-passthrough'>
            <!-- disable nested HVM -->
            <feature name='vmx' policy='disable'/>
            <feature name='svm' policy='disable'/>
            <!-- disable SMAP inside VM, because of Linux bug -->
            <feature name='smap' policy='disable'/>
        </cpu>
        <os>
            <type arch="x86_64" machine="xenfv">hvm</type>
                <!--
                     For the libxl backend libvirt switches between OVMF (UEFI)
                     and SeaBIOS based on the loader type. This has nothing to
                     do with the hvmloader binary.
                -->
            <loader type="rom">hvmloader</loader>
            <boot dev="cdrom" />
            <boot dev="hd" />
            <!-- server_ip is the address of stubdomain. It hosts it's own DNS server. -->
        </os>
        <features>
            <pae/>
            <acpi/>
            <apic/>
            <viridian/>
        </features>
        <clock offset="variable" adjustment="0" basis="localtime" />
        <on_poweroff>destroy</on_poweroff>
        <on_reboot>destroy</on_reboot>
        <on_crash>destroy</on_crash>
        <devices>
            <emulator type="stubdom-linux" />
            <input type="tablet" bus="usb"/>
            <video>
                <model type="vga"/>
            </video>
            <graphics type="qubes"/>
        </devices>
        </domain>
        '''
        my_uuid = '7db78950-c467-4863-94d1-af59806384ea'
        vm = self.get_vm(uuid=my_uuid)
        vm.netvm = None
        vm.virt_mode = 'hvm'
        libvirt_xml = vm.create_config_file()
        self.assertXMLEqual(lxml.etree.XML(libvirt_xml),
            lxml.etree.XML(expected))
