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
            self.assignment = qubes.devices.DeviceAssignment(backend_domain=self.dev.backend_domain, ident=self.dev.ident, persistent=True)
            if isinstance(self.dev, qubes.devices.UnknownDevice):
                self.skipTest('Specified device {} does not exists'.format(pcidev))
            self.init_default_template()
            self.vm = self.app.add_new_vm(qubes.vm.appvm.AppVM,
                name=self.make_vm_name('vm'),
                label='red',
            )
            self.vm.create_on_disk()
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
            self.assertIsInstance(dev, qubes.ext.pci.PCIDevice)
            self.assertEqual(dev.backend_domain, self.app.domains[0])
            self.assertIn(dev.ident, actual_devices)
            self.assertEqual(dev.description, actual_devices[dev.ident])
            actual_devices.pop(dev.ident)

        if actual_devices:
            self.fail('Not all devices listed, missing: {}'.format(
                actual_devices))

    def assertDeviceNotInCollection(self, dev, dev_col):
        self.assertNotIn(dev, dev_col.attached())
        self.assertNotIn(dev, dev_col.persistent())
        self.assertNotIn(dev, dev_col.assignments())
        self.assertNotIn(dev, dev_col.assignments(persistent=True))

    def test_010_attach_offline_persistent(self):
        dev_col = self.vm.devices['pci']
        self.assertDeviceNotInCollection(self.dev, dev_col)
        dev_col.attach(self.assignment)
        self.app.save()
        self.assertNotIn(self.dev, dev_col.attached())
        self.assertIn(self.dev, dev_col.persistent())
        self.assertIn(self.dev, dev_col.assignments())
        self.assertIn(self.dev, dev_col.assignments(persistent=True))
        self.assertNotIn(self.dev, dev_col.assignments(persistent=False))


        self.vm.start()

        self.assertIn(self.dev, dev_col.attached())
        p = self.vm.run('lspci', passio_popen=True)
        (stdout, _) = p.communicate()
        self.assertIn(self.dev.description, stdout.decode())


    def test_011_attach_offline_temp_fail(self):
        dev_col = self.vm.devices['pci']
        self.assertDeviceNotInCollection(self.dev, dev_col)
        self.assignment.persistent = False
        with self.assertRaises(qubes.exc.QubesVMNotRunningError):
            dev_col.attach(self.assignment)


    def test_020_attach_online_persistent(self):
        self.vm.start()
        dev_col = self.vm.devices['pci']
        self.assertDeviceNotInCollection(self.dev, dev_col)
        dev_col.attach(self.assignment)

        self.assertIn(self.dev, dev_col.attached())
        self.assertIn(self.dev, dev_col.persistent())
        self.assertIn(self.dev, dev_col.assignments())
        self.assertIn(self.dev, dev_col.assignments(persistent=True))
        self.assertNotIn(self.dev, dev_col.assignments(persistent=False))

        # give VM kernel some time to discover new device
        time.sleep(1)
        p = self.vm.run('lspci', passio_popen=True)
        (stdout, _) = p.communicate()
        self.assertIn(self.dev.description, stdout.decode())


    def test_021_persist_detach_online_fail(self):
        dev_col = self.vm.devices['pci']
        self.assertDeviceNotInCollection(self.dev, dev_col)
        dev_col.attach(self.assignment)
        self.app.save()
        self.vm.start()
        with self.assertRaises(qubes.exc.QubesVMNotHaltedError):
            self.vm.devices['pci'].detach(self.assignment)

    def test_030_persist_attach_detach_offline(self):
        dev_col = self.vm.devices['pci']
        self.assertDeviceNotInCollection(self.dev, dev_col)
        dev_col.attach(self.assignment)
        self.app.save()
        self.assertNotIn(self.dev, dev_col.attached())
        self.assertIn(self.dev, dev_col.persistent())
        self.assertIn(self.dev, dev_col.assignments())
        self.assertIn(self.dev, dev_col.assignments(persistent=True))
        self.assertNotIn(self.dev, dev_col.assignments(persistent=False))
        dev_col.detach(self.assignment)
        self.assertDeviceNotInCollection(self.dev, dev_col)

    def test_031_attach_detach_online_temp(self):
        dev_col = self.vm.devices['pci']
        self.vm.start()
        self.assignment.persistent = False
        self.assertDeviceNotInCollection(self.dev, dev_col)
        dev_col.attach(self.assignment)

        self.assertIn(self.dev, dev_col.attached())
        self.assertNotIn(self.dev, dev_col.persistent())
        self.assertIn(self.dev, dev_col.assignments())
        self.assertIn(self.dev, dev_col.assignments(persistent=False))
        self.assertNotIn(self.dev, dev_col.assignments(persistent=True))
        self.assertIn(self.dev, dev_col.assignments(persistent=False))


        # give VM kernel some time to discover new device
        time.sleep(1)
        p = self.vm.run('lspci', passio_popen=True)
        (stdout, _) = p.communicate()

        self.assertIn(self.dev.description, stdout.decode())
        dev_col.detach(self.assignment)
        self.assertDeviceNotInCollection(self.dev, dev_col)

        p = self.vm.run('lspci', passio_popen=True)
        (stdout, _) = p.communicate()
        self.assertNotIn(self.dev.description, stdout.decode())
