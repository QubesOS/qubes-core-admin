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
from unittest import mock

import qubes.tests
import qubes.ext.pci
from qubes.device_protocol import DeviceInterface


class TestVM(object):
    def __init__(self, running=True, name='dom0', qid=0):
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
    elif filename.startswith("/sys/devices/pci"):
        content = "0x0c0330"
    else:
        raise OSError()

    file_object = mock.mock_open(read_data=content).return_value
    file_object.__iter__.return_value = content
    return file_object


class TC_00_Block(qubes.tests.QubesTestCase):
    def setUp(self):
        super().setUp()
        self.ext = qubes.ext.pci.PCIDeviceExtension()

    @mock.patch('builtins.open', new=mock_file_open)
    def test_000_unsupported_device(self):
        vm = TestVM()
        vm.app.configure_mock(**{
            'vmm.libvirt_conn.nodeDeviceLookupByName.return_value':
                mock.Mock(**{"XMLDesc.return_value":
                                 PCI_XML.format(*["0000"] * 3)
                             }),
            'vmm.libvirt_conn.listAllDevices.return_value':
                [mock.Mock(**{"XMLDesc.return_value":
                                  PCI_XML.format(*["0000"] * 3),
                              "listCaps.return_value": ["pci"]
                              }),
                 mock.Mock(**{"XMLDesc.return_value":
                                  PCI_XML.format(*["1000"] * 3),
                              "listCaps.return_value": ["pci"]
                              }),
                 ]
        })
        devices = list(self.ext.on_device_list_pci(vm, 'device-list:pci'))
        self.assertEqual(len(devices), 1)
        self.assertEqual(devices[0].port_id, "00_14.0")
        self.assertEqual(devices[0].vendor, "Intel Corporation")
        self.assertEqual(devices[0].product,
                         "9 Series Chipset Family USB xHCI Controller")
        self.assertEqual(devices[0].interfaces, [DeviceInterface("p0c0330")])
        self.assertEqual(devices[0].parent_device, None)
        self.assertEqual(devices[0].libvirt_name, "pci_0000_00_14_0")
        self.assertEqual(devices[0].description,
                         "USB controller: Intel Corporation 9 Series "
                         "Chipset Family USB xHCI Controller")
        self.assertEqual(devices[0].device_id, "0x8086:0x8cb1::p0c0330")
