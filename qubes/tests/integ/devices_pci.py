# pylint: disable=protected-access,pointless-statement

#
# The Qubes OS Project, https://www.qubes-os.org/
#
# Copyright (C) 2015-2016  Joanna Rutkowska <joanna@invisiblethingslab.com>
# Copyright (C) 2015-2016  Wojtek Porczyk <woju@invisiblethingslab.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
#

import os
import subprocess
import time
import unittest

import qubes.devices
import qubes.ext.pci
import qubes.tests


class TC_00_Devices_PCI(qubes.tests.SystemTestsMixin,
        qubes.tests.QubesTestCase):
    def setUp(self):
        super(TC_00_Devices_PCI, self).setUp()
        if self._testMethodName not in ['test_000_list']:
            pcidev = os.environ.get('QUBES_TEST_PCIDEV', None)
            if pcidev is None:
                self.skipTest('Specify PCI device with QUBES_TEST_PCIDEV '
                              'environment variable')
            self.dev = self.app.domains[0].devices['pci'][pcidev]
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
            self.assertIsInstance(dev.frontend_domain,
                (qubes.vm.BaseVM, None.__class__))
            actual_devices.pop(dev.ident)

        if actual_devices:
            self.fail('Not all devices listed, missing: {}'.format(
                actual_devices))

    def test_010_attach_offline(self):
        self.assertIsNone(self.dev.frontend_domain)
        self.assertNotIn(self.dev, self.vm.devices['pci'].attached())
        self.assertNotIn(self.dev, self.vm.devices['pci'].attached(
            persistent=True))
        self.assertNotIn(self.dev, self.vm.devices['pci'].attached(
            persistent=False))

        self.vm.devices['pci'].attach(self.dev)
        self.app.save()

        # still should be None, as domain is not started yet
        self.assertIsNone(self.dev.frontend_domain)
        self.assertIn(self.dev, self.vm.devices['pci'].attached())
        self.assertIn(self.dev, self.vm.devices['pci'].attached(
            persistent=True))
        self.assertNotIn(self.dev, self.vm.devices['pci'].attached(
            persistent=False))
        self.vm.start()

        self.assertEqual(self.dev.frontend_domain, self.vm)
        self.assertIn(self.dev, self.vm.devices['pci'].attached())
        self.assertIn(self.dev, self.vm.devices['pci'].attached(
            persistent=True))
        self.assertNotIn(self.dev, self.vm.devices['pci'].attached(
            persistent=False))

        p = self.vm.run('lspci', passio_popen=True)
        (stdout, _) = p.communicate()
        self.assertIn(self.dev.description, stdout)

    def test_011_attach_online(self):
        self.vm.start()
        self.vm.devices['pci'].attach(self.dev)

        self.assertEqual(self.dev.frontend_domain, self.vm)
        self.assertIn(self.dev, self.vm.devices['pci'].attached())
        self.assertIn(self.dev, self.vm.devices['pci'].attached(
            persistent=True))
        self.assertNotIn(self.dev, self.vm.devices['pci'].attached(
            persistent=False))

        # give VM kernel some time to discover new device
        time.sleep(1)
        p = self.vm.run('lspci', passio_popen=True)
        (stdout, _) = p.communicate()
        self.assertIn(self.dev.description, stdout)

    def test_012_attach_online_temp(self):
        self.vm.start()
        self.vm.devices['pci'].attach(self.dev, persistent=False)

        self.assertEqual(self.dev.frontend_domain, self.vm)
        self.assertIn(self.dev, self.vm.devices['pci'].attached())
        self.assertNotIn(self.dev, self.vm.devices['pci'].attached(
            persistent=True))
        self.assertIn(self.dev, self.vm.devices['pci'].attached(
            persistent=False))

        # give VM kernel some time to discover new device
        time.sleep(1)
        p = self.vm.run('lspci', passio_popen=True)
        (stdout, _) = p.communicate()
        self.assertIn(self.dev.description, stdout)

    def test_020_detach_online(self):
        self.vm.devices['pci'].attach(self.dev)
        self.app.save()
        self.vm.start()

        self.assertIn(self.dev, self.vm.devices['pci'].attached())
        self.assertIn(self.dev, self.vm.devices['pci'].attached(
            persistent=True))
        self.assertNotIn(self.dev, self.vm.devices['pci'].attached(
            persistent=False))
        self.assertEqual(self.dev.frontend_domain, self.vm)

        self.vm.devices['pci'].detach(self.dev)

        self.assertIsNone(self.dev.frontend_domain)
        self.assertNotIn(self.dev, self.vm.devices['pci'].attached())
        self.assertNotIn(self.dev, self.vm.devices['pci'].attached(
            persistent=True))
        self.assertNotIn(self.dev, self.vm.devices['pci'].attached(
            persistent=False))

        p = self.vm.run('lspci', passio_popen=True)
        (stdout, _) = p.communicate()
        self.assertNotIn(self.dev.description, stdout)

        # can't do this right now because of kernel bug - it cause the whole
        # PCI bus being deregistered, which emit some warning in sysfs
        # handling code (removing non-existing "0000:00" group)
        #
        # p = self.vm.run('dmesg', passio_popen=True)
        # (stdout, _) = p.communicate()
        # # check for potential oops
        # self.assertNotIn('end trace', stdout)

