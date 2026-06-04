# -*- encoding: utf8 -*-
#
# The Qubes OS Project, http://www.qubes-os.org
#
# Copyright (C) 2023 Marek Marczykowski-Górecki
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

import functools
import os.path
from unittest import mock

from qubes.vm.adminvm import AdminVM
from qubes.vm.appvm import AppVM

import qubes.tests
import qubes.tests.vm
import qubes.ext.pci
import qubes.devices
from qubes.device_protocol import (
    DeviceInterface,
    DeviceAssignment,
    VirtualDevice,
)
from qubes.utils import sbdf_to_path, path_to_sbdf, is_pci_path

orig_open = open


class TestApp(qubes.tests.vm.TestApp):
    def __init__(self, offline_mode=True):
        super().__init__()
        self.qid_counter = 0
        self.vmm.offline_mode = offline_mode

    def save(self):
        pass

    def add_new_vm(self, cls, **kwargs):
        qid = self.qid_counter
        if self.qid_counter == 0:
            vm = cls(self, None, **kwargs)
        else:
            vm = cls(self, None, qid=qid, **kwargs)
        self.domains[vm.name] = vm
        self.domains[vm] = vm
        self.domains[qid] = vm
        self.qid_counter += 1
        return vm


PCI_XML = """<device>
  <name>pci_{address}_00_14_0</name>
  <path>/sys/devices/pci{address}:00/{address}:00:14.0</path>
  <parent>computer</parent>
  <driver>
    <name>pciback</name>
  </driver>
  <capability type='pci'>
    <class>0x0c0330</class>
    <domain>0</domain>
    <bus>0</bus>
    <slot>20</slot>
    <function>0</function>
    <product id='0x8cb1'>9 Series Chipset Family USB xHCI Controller</product>
    <vendor id='0x8086'>Intel Corporation</vendor>
  </capability>
</device>
"""


def mock_file_open(filename: str, *_args, **_kwargs):
    if filename == "/usr/share/hwdata/pci.ids":
        # short version of pci.ids
        content = """
#
#       List of PCI ID's
#
#       (...)
#
0001  SafeNet (wrong ID)
0010  Allied Telesis, Inc (Wrong ID)
# This is a relabelled RTL-8139
        8139  AT-2500TX V3 Ethernet
# List of known device classes, subclasses and programming interfaces

# Syntax:
# C class       class_name
#       subclass        subclass_name           <-- single tab
#               prog-if  prog-if_name   <-- two tabs

C 00  Unclassified device
\t00  Non-VGA unclassified device
C 01  Mass storage controller
\t01  IDE interface
\t\t00  ISA Compatibility mode-only controller
C 0c  Serial bus controller
\t00  FireWire (IEEE 1394)
\t\t00  Generic
\t\t10  OHCI
\t01  ACCESS Bus
\t02  SSA
\t03  USB controller
\t\t00  UHCI
\t\t10  OHCI
\t\t20  EHCI
\t\t30  XHCI
\t\t40  USB4 Host Interface
\t\t80  Unspecified
\t\tfe  USB Device
\t04  Fibre Channel
\t05  SMBus
\t06  InfiniBand
\t07  IPMI Interface
\t\t00  SMIC
\t\t01  KCS
\t\t02  BT (Block Transfer)
\t08  SERCOS interface
\t09  CANBUS
\t80  Serial bus controller
"""
    else:
        return orig_open(filename, *_args, **_kwargs)

    file_object = mock.mock_open(read_data=content).return_value
    file_object.__iter__.return_value = content
    return file_object


# prefer location in git checkout
tests_sysfs_path = os.path.dirname(__file__) + "/../../tests-data/sysfs/sys"
if not os.path.exists(tests_sysfs_path):
    # but if not there, look for package installed one
    tests_sysfs_path = "/usr/share/qubes/tests-data/sysfs/sys"


@mock.patch("qubes.utils.SYSFS_BASE", tests_sysfs_path)
class TC_00_helpers(qubes.tests.QubesTestCase):
    def test_000_sbdf_to_path1(self):
        path = sbdf_to_path("0000:c6:00.0")
        self.assertEqual(path, "c0_03.5-00_00.0-00_00.0")

    def test_001_sbdf_to_path2(self):
        path = sbdf_to_path("0000:00:18.4")
        self.assertEqual(path, "00_18.4")

    def test_002_sbdf_to_path_libvirt(self):
        path = sbdf_to_path("pci_0000_00_18_4")
        self.assertEqual(path, "00_18.4")

    def test_003_sbdf_to_path_default_segment1(self):
        path = sbdf_to_path("00:18.4")
        self.assertEqual(path, "00_18.4")

    def test_004_sbdf_to_path_default_segment2(self):
        path = sbdf_to_path("0000:00:18.4")
        self.assertEqual(path, "00_18.4")

    def test_010_path_to_sbdf1(self):
        path = path_to_sbdf("0000_c0_03.5-00_00.0-00_00.0")
        self.assertEqual(path, "0000:c6:00.0")

    def test_011_path_to_sbdf2(self):
        path = path_to_sbdf("0000_00_18.4")
        self.assertEqual(path, "0000:00:18.4")

    def test_012_path_to_sbdf_missing(self):
        path = path_to_sbdf("0000_c0_03.7-00_00.0-00_00.0")
        self.assertEqual(path, None)

    def test_020_is_pci_path(self):
        self.assertTrue(is_pci_path("0000_00_18.4"))

    def test_021_is_pci_path_false(self):
        self.assertFalse(is_pci_path("0000_c6_00.0"))

    def test_022_is_pci_path_non_00_bus(self):
        self.assertTrue(is_pci_path("0000_c0_00.0"))


@mock.patch("qubes.utils.SYSFS_BASE", tests_sysfs_path)
class TC_10_PCI(qubes.tests.QubesTestCase):
    def setUp(self):
        super().setUp()
        self.app = TestApp()
        self.dom0 = self.app.add_new_vm(AdminVM)
        self.appvm = self.app.add_new_vm(AppVM, name="test-appvm", label="red")
        self.ext = qubes.ext.pci.PCIDeviceExtension()

    def tearDown(self):
        super().tearDown()
        del self.ext
        self.appvm.close()
        self.dom0.close()
        del self.appvm
        del self.dom0
        self.app.close()
        self.app.domains.clear()
        self.app.pools.clear()
        del self.app

    @mock.patch("builtins.open", new=mock_file_open)
    def test_000_unsupported_device(self):
        vm = self.dom0
        vm.app.vmm = mock.Mock()
        vm.app.vmm.configure_mock(
            **{
                "offline_mode": False,
                "libvirt_conn.nodeDeviceLookupByName.return_value": mock.Mock(
                    **{"XMLDesc.return_value": PCI_XML.format(address="0000")}
                ),
                "libvirt_conn.listDevices.return_value": [
                    "pci_0000_00_14_0",
                    "pci_10000_00_14_0",
                ],
            }
        )
        devices = list(self.ext.on_device_list_pci(vm, "device-list:pci"))
        self.assertEqual(len(devices), 1)
        self.assertEqual(devices[0].port_id, "00_14.0")
        self.assertEqual(devices[0].vendor, "Intel Corporation")
        self.assertEqual(
            devices[0].product, "9 Series Chipset Family USB xHCI Controller"
        )
        self.assertEqual(devices[0].interfaces, [DeviceInterface("p0c0330")])
        self.assertEqual(devices[0].parent_device, None)
        self.assertEqual(devices[0].libvirt_name, "pci_0000_00_14_0")
        self.assertEqual(
            devices[0].description,
            "USB controller: Intel Corporation 9 Series "
            "Chipset Family USB xHCI Controller",
        )
        self.assertEqual(devices[0].device_id, "0x8086:0x8cb1::p0c0330")

        not_dom0 = self.appvm
        devices = list(self.ext.on_device_list_pci(not_dom0, "device-list:pci"))
        self.assertEqual(devices, [])

    @mock.patch("builtins.open", new=mock_file_open)
    def test_001_list_attached(self):
        dev0 = {"segment": "0000", "bus": "00", "device": "0d", "function": "0"}
        dev1 = {"segment": "0000", "bus": "00", "device": "0d", "function": "2"}
        dev2 = {"segment": "0000", "bus": "00", "device": "14", "function": "0"}
        usbvm_xml = f"""
<domain type='xen' id='27'>
  <name>sys-usb</name>
  <devices>
    <emulator type='stubdom-linux' cmdline='-qubes-audio:audiovm_xid=0'/>
    <disk type='block' device='disk'>
      <driver name='phy' type='raw'/>
      <source dev='/dev/mapper/qubes_dom0-vm--sys--usb--root--snap'/>
      <script path='/etc/xen/scripts/qubes-block'/>
      <target dev='xvda' bus='xen'/>
    </disk>
    <disk type='block' device='disk'>
      <driver name='phy' type='raw'/>
      <source dev='/dev/mapper/qubes_dom0-vm--sys--usb--private--snap'/>
      <script path='/etc/xen/scripts/qubes-block'/>
      <target dev='xvdb' bus='xen'/>
    </disk>
    <disk type='block' device='disk'>
      <driver name='phy' type='raw'/>
      <source dev='/dev/mapper/qubes_dom0-vm--sys--usb--volatile'/>
      <script path='/etc/xen/scripts/qubes-block'/>
      <target dev='xvdc' bus='xen'/>
    </disk>
    <disk type='block' device='disk'>
      <driver name='phy' type='raw'/>
      <source dev='/var/lib/qubes/vm-kernels/7.1.5-1.18.fc41/modules.img'/>
      <script path='/etc/xen/scripts/qubes-block'/>
      <target dev='xvdd' bus='xen'/>
      <readonly/>
    </disk>
    <controller type='xenbus' index='0'/>
    <console type='pty' tty='/dev/pts/7'>
      <source path='/dev/pts/7'/>
      <target type='xen' port='0'/>
    </console>
    <input type='tablet' bus='usb'/>
    <input type='mouse' bus='ps2'/>
    <input type='keyboard' bus='ps2'/>
    <graphics type='qubes' log_level='0'/>
    <video>
      <model type='vga' vram='16384' heads='1' primary='yes'/>
    </video>
    <hostdev mode='subsystem' type='pci' managed='yes' nostrictreset='yes'>
      <driver name='xen'/>
      <source>
        <address domain='0x{dev0["segment"]}' bus='0x{dev0["bus"]}' slot='0x{dev0["device"]}' function='0x{dev0["function"]}'/>
      </source>
    </hostdev>
    <hostdev mode='subsystem' type='pci' managed='yes' nostrictreset='yes'>
      <driver name='xen'/>
      <source>
        <address domain='0x{dev1["segment"]}' bus='0x{dev1["bus"]}' slot='0x{dev1["device"]}' function='0x{dev1["function"]}'/>
      </source>
    </hostdev>
    <hostdev mode='subsystem' type='pci' managed='yes' nostrictreset='yes'>
      <driver name='xen'/>
      <source>
        <address domain='0x{dev2["segment"]}' bus='0x{dev2["bus"]}' slot='0x{dev2["device"]}' function='0x{dev2["function"]}'/>
      </source>
    </hostdev>
    <memballoon model='xen'/>
  </devices>
</domain>
"""

        with self.subTest(name="dom0"):
            self.dom0._libvirt_domain = mock.Mock()
            self.dom0._libvirt_domain.XMLDesc.return_value = usbvm_xml
            devices = list(
                self.ext.on_device_list_attached(
                    self.dom0, "device-list-attached:pci"
                )
            )
            self.assertEqual(devices, [])

        with self.subTest(name="not-dom0"):
            not_dom0 = self.appvm
            not_dom0._libvirt_domain = mock.Mock()
            not_dom0._libvirt_domain.XMLDesc.return_value = usbvm_xml
            with mock.patch.object(not_dom0, "is_running", return_value=True):
                devices = list(
                    self.ext.on_device_list_attached(
                        not_dom0, "device-list-attached:pci"
                    )
                )
            self.assertEqual(len(devices), 3)
            expected_devices = [dev0, dev1, dev2]
            for device, expected in zip(devices, expected_devices):
                dev = device[0]
                port = f'{expected["bus"]}_{expected["device"]}.{expected["function"]}'
                self.assertEqual(dev.port_id, port)
                sbdf = f'{expected["segment"]}:{port}'.replace(
                    ":", "_"
                ).replace(".", "_")
                self.assertEqual(dev.libvirt_name, "pci_" + sbdf)
            del not_dom0

    def _mock_fire_event(self, vm, event, pre_event=False, **kwargs):
        if event == "device-get:pci":
            return list(self.ext.on_device_get_pci(vm, event, **kwargs))
        elif event.startswith("admin-permission:"):
            pass
        else:
            assert False

    def test_010_unassign_missing(self):
        vm = self.appvm
        vm.events_enabled = False
        vm.fire_event_async = mock.AsyncMock()
        vm.fire_event = functools.partial(self._mock_fire_event, vm)
        pci_devices = qubes.devices.DeviceCollection(vm, "pci")
        vm.devices = {"pci": pci_devices}
        self.dom0.fire_event = functools.partial(
            self._mock_fire_event, self.dom0
        )
        dom0_pci_devices = qubes.devices.DeviceCollection(self.dom0, "pci")
        self.dom0.devices = {"pci": dom0_pci_devices}
        self.app.domains["testvm"] = vm
        self.app.domains[vm] = vm
        missing_port_id = "0000_c0_03.7-00_00.0-00_00.0"
        missing_device_id = "0x8086:0x8cb1::p0c0330"
        device_assignment = qubes.device_protocol.DeviceAssignment(
            qubes.device_protocol.VirtualDevice(
                qubes.device_protocol.Port(
                    backend_domain=self.dom0,
                    port_id=missing_port_id,
                    devclass="pci",
                ),
                device_id=missing_device_id,
            ),
            frontend_domain=vm,
            options={},
            mode=qubes.device_protocol.AssignmentMode.REQUIRED,
        )
        pci_devices.load_assignment(device_assignment)

        vm.events_enabled = True
        mgmt_obj = qubes.api.admin.QubesAdminAPI(
            self.app,
            b"dom0",
            b"admin.vm.device.pci.Unassign",
            b"testvm",
            (
                "dom0+"
                + missing_port_id
                + "+"
                + missing_device_id.replace(":", "+")
            ).encode(),
        )

        response = self.loop.run_until_complete(
            mgmt_obj.execute(untrusted_payload=b"")
        )
        self.assertEqual(response, None)
        self.assertListEqual(list(pci_devices.get_assigned_devices()), [])
