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
import os.path
import unittest
from unittest import mock

import qubes.tests
import qubes.ext.pci
from qubes.device_protocol import DeviceInterface
from qubes.utils import sbdf_to_path, path_to_sbdf, is_pci_path

orig_open = open


class TestVM(object):
    def __init__(self, running=True, name="dom0", qid=0):
        self.name = name
        self.qid = qid
        self.is_running = lambda: running
        self.log = mock.Mock()
        self.app = mock.Mock()

    def __eq__(self, other):
        if isinstance(other, TestVM):
            return self.name == other.name


PCI_XML = """<device>
  <name>pci_{}_00_14_0</name>
  <path>/sys/devices/pci{}:00/{}:00:14.0</path>
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
        self.ext = qubes.ext.pci.PCIDeviceExtension()

    @mock.patch("builtins.open", new=mock_file_open)
    def test_000_unsupported_device(self):
        vm = TestVM()
        vm.app.configure_mock(
            **{
                "vmm.offline_mode": False,
                "vmm.libvirt_conn.nodeDeviceLookupByName.return_value": mock.Mock(
                    **{"XMLDesc.return_value": PCI_XML.format(*["0000"] * 3)}
                ),
                "vmm.libvirt_conn.listAllDevices.return_value": [
                    mock.Mock(
                        **{
                            "XMLDesc.return_value": PCI_XML.format(
                                *["0000"] * 3
                            ),
                            "listCaps.return_value": ["pci"],
                        }
                    ),
                    mock.Mock(
                        **{
                            "XMLDesc.return_value": PCI_XML.format(
                                *["10000"] * 3
                            ),
                            "listCaps.return_value": ["pci"],
                        }
                    ),
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
