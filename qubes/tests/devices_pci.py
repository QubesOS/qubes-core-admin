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

import jinja2

import qubes.tests
import qubes.ext.pci


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

class TC_00_Block(qubes.tests.QubesTestCase):
    def setUp(self):
        super().setUp()
        self.ext = qubes.ext.pci.PCIDeviceExtension()

    def test_000_unsupported_device(self):
        vm = TestVM()
        vm.app.configure_mock(**{
            'vmm.libvirt_conn.listAllDevices.return_value':
                [mock.Mock(**{"XMLDesc.return_value": """<device>
  <name>pci_0000_00_14_0</name>
  <path>/sys/devices/pci0000:00/0000:00:14.0</path>
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
""",
                             "listCaps.return_value": ["pci"]
                             }),
                 mock.Mock(**{"XMLDesc.return_value": """<device>
  <name>pci_1000_00_14_0</name>
  <path>/sys/devices/pci1000:00/1000:00:14.0</path>
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
""",
                             "listCaps.return_value": ["pci"]
                             }),
                    ]
        })
        devices = list(self.ext.on_device_list_pci(vm, 'device-list:pci'))
        self.assertEqual(len(devices), 1)
        self.assertEqual(devices[0].ident, "00_14.0")
