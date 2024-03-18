# pylint: disable=protected-access,pointless-statement

#
# The Qubes OS Project, https://www.qubes-os.org/
#
# Copyright (C) 2015-2016  Joanna Rutkowska <joanna@invisiblethingslab.com>
# Copyright (C) 2015-2016  Wojtek Porczyk <woju@invisiblethingslab.com>
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
import subprocess
import time
import unittest

import qubes.devices
import qubes.ext.pci
import qubes.tests


@qubes.tests.skipUnlessEnv('QUBES_TEST_PCIDEV')
class TC_00_Devices_PCI(qubes.tests.SystemTestCase):
    def setUp(self):
        super(TC_00_Devices_PCI, self).setUp()
        if self._testMethodName not in ['test_000_list']:
            pcidev = os.environ['QUBES_TEST_PCIDEV']
            self.dev = self.app.domains[0].devices['pci'][pcidev]
            self.assignment = qubes.devices.DeviceAssignment(
                backend_domain=self.dev.backend_domain,
                ident=self.dev.ident,
                attach_automatically=True,
            )
            self.required_assignment = qubes.devices.DeviceAssignment(
                backend_domain=self.dev.backend_domain,
                ident=self.dev.ident,
                attach_automatically=True,
                required=True,
            )
            if isinstance(self.dev, qubes.devices.UnknownDevice):
                self.skipTest('Specified device {} does not exists'.format(pcidev))
            self.init_default_template()
            self.vm = self.app.add_new_vm(qubes.vm.appvm.AppVM,
                name=self.make_vm_name('vm'),
                label='red',
            )
            self.vm.virt_mode = 'hvm'
            self.loop.run_until_complete(
                self.vm.create_on_disk())
            self.vm.features['pci-no-strict-reset/' + pcidev] = True
            self.app.save()

    @unittest.expectedFailure
    def test_000_list(self):
        p = subprocess.Popen(['lspci'], stdout=subprocess.PIPE)
        # get a dict: BDF -> description
        actual_devices = dict(
            l.split(' (')[0].split(' ', 1)
                for l in p.communicate()[0].decode().splitlines())
        for dev in self.app.domains[0].devices['pci']:
            lspci_ident = dev.ident.replace('_', ':')
            self.assertIsInstance(dev, qubes.ext.pci.PCIDevice)
            self.assertEqual(dev.backend_domain, self.app.domains[0])
            self.assertIn(lspci_ident, actual_devices)
            self.assertEqual(dev.description, actual_devices[lspci_ident])
            actual_devices.pop(lspci_ident)

        if actual_devices:
            self.fail('Not all devices listed, missing: {}'.format(
                actual_devices))

    def assertDeviceIs(
            self, device, *, attached: bool, assigned: bool, required: bool
    ):
        dev_col = self.vm.devices['pci']
        if required:
            assert assigned
        self.assertTrue(attached == device in dev_col.get_attached_devices())
        self.assertTrue(assigned == device in dev_col.get_assigned_devices())
        self.assertTrue(
            required == device in dev_col.get_assigned_devices(
                required_only=True)
        )
        dedicated = assigned or attached
        self.assertTrue(dedicated == device in dev_col.get_dedicated_devices())

    def test_010_assign_offline(self):  # TODO required
        dev_col = self.vm.devices['pci']
        self.assertDeviceIs(
            self.dev, attached=False, assigned=False, required=False)

        self.loop.run_until_complete(dev_col.assign(self.assignment))
        self.app.save()
        self.assertDeviceIs(
            self.dev, attached=False, assigned=True, required=False)

        self.loop.run_until_complete(self.vm.start())
        self.assertDeviceIs(
            self.dev, attached=True, assigned=False, required=False)

        (stdout, _) = self.loop.run_until_complete(
            self.vm.run_for_stdio('lspci'))
        self.assertIn(self.dev.description, stdout.decode())


    def test_011_attach_offline_temp_fail(self):
        dev_col = self.vm.devices['pci']
        self.assertDeviceIs(
            self.dev, attached=False, assigned=False, required=False)
        self.assignment.persistent = False
        with self.assertRaises(qubes.exc.QubesVMNotRunningError):
            self.loop.run_until_complete(
                dev_col.attach(self.assignment))

    def test_020_attach_online_persistent(self):  # TODO: required
        self.loop.run_until_complete(
            self.vm.start())
        dev_col = self.vm.devices['pci']
        self.assertDeviceIs(
            self.dev, attached=False, assigned=False, required=False)

        self.loop.run_until_complete(
            dev_col.attach(self.assignment))
        self.assertDeviceIs(
            self.dev, attached=True, assigned=True, required=False)

        # give VM kernel some time to discover new device
        time.sleep(1)
        (stdout, _) = self.loop.run_until_complete(
            self.vm.run_for_stdio('lspci'))
        self.assertIn(self.dev.description, stdout.decode())


    def test_021_persist_detach_online_fail(self):
        dev_col = self.vm.devices['pci']
        self.assertDeviceIs(
            self.dev, attached=False, assigned=False, required=False)
        self.loop.run_until_complete(
            dev_col.attach(self.assignment))
        self.app.save()
        self.loop.run_until_complete(
            self.vm.start())
        with self.assertRaises(qubes.exc.QubesVMNotHaltedError):
            self.loop.run_until_complete(
                self.vm.devices['pci'].detach(self.assignment))

    def test_030_persist_attach_detach_offline(self):  # TODO: required
        dev_col = self.vm.devices['pci']
        self.assertDeviceIs(
            self.dev, attached=False, assigned=False, required=False)

        self.loop.run_until_complete(
            dev_col.attach(self.assignment))
        self.app.save()
        self.assertDeviceIs(
            self.dev, attached=False, assigned=True, required=False)

        self.loop.run_until_complete(
            dev_col.detach(self.assignment))
        self.assertDeviceIs(
            self.dev, attached=False, assigned=False, required=False)

    def test_031_attach_detach_online_temp(self):  # TODO: requiured
        dev_col = self.vm.devices['pci']
        self.loop.run_until_complete(
            self.vm.start())
        self.assignment.assigned = False
        self.assertDeviceIs(
            self.dev, attached=False, assigned=False, required=False)

        self.loop.run_until_complete(
            dev_col.attach(self.assignment))
        self.assertDeviceIs(
            self.dev, attached=True, assigned=False, required=False)

        # give VM kernel some time to discover new device
        time.sleep(1)
        (stdout, _) = self.loop.run_until_complete(
            self.vm.run_for_stdio('lspci'))

        self.assertIn(self.dev.description, stdout.decode())
        self.loop.run_until_complete(
            dev_col.detach(self.assignment))
        self.assertDeviceIs(
            self.dev, attached=False, assigned=False, required=False)

        (stdout, _) = self.loop.run_until_complete(
            self.vm.run_for_stdio('lspci'))
        self.assertNotIn(self.dev.description, stdout.decode())
