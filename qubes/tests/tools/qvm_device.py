# pylint: disable=protected-access

#
# The Qubes OS Project, https://www.qubes-os.org/
#
# Copyright (C) 2015  Marek Marczykowski-Górecki
#                                       <marmarek@invisiblethingslab.com>
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

''' Tests for the `qvm-device` tool. '''

import qubes
import qubes.devices
import qubes.tools.qvm_device

import qubes.tests
import qubes.tests.devices
import qubes.tests.tools

class TestNamespace(object):
    ''' A mock object for `argparse.Namespace`.
    '''  # pylint: disable=too-few-public-methods

    def __init__(self, app, domains=None, device=None):
        super(TestNamespace, self).__init__()
        self.app = app
        self.devclass = 'testclass'
        self.persistent = True
        if domains:
            self.domains = domains
        if device:
            self.device = device
            self.device_assignment = qubes.devices.DeviceAssignment(
                backend_domain=self.device.backend_domain,
                ident=self.device.ident, persistent=self.persistent)


class TC_00_Actions(qubes.tests.QubesTestCase):
    ''' Tests the output logic of the qvm-device tool '''
    def setUp(self):
        super(TC_00_Actions, self).setUp()
        self.app = qubes.tests.devices.TestApp()
        def save():
            ''' A mock method for simulating a successful save '''
            return True
        self.app.save = save
        self.vm1 = qubes.tests.devices.TestVM(self.app, 'vm1')
        self.vm2 = qubes.tests.devices.TestVM(self.app, 'vm2')
        self.device = self.vm2.device

    def test_000_list_all(self):
        ''' List all exposed vm devices. No devices are attached to other
            domains.
        '''
        args = TestNamespace(self.app)
        with qubes.tests.tools.StdoutBuffer() as buf:
            qubes.tools.qvm_device.list_devices(args)
            self.assertEqual(
                [x.rstrip() for x in buf.getvalue().splitlines()],
                ['vm1:testdev  Description',
                 'vm2:testdev  Description']
            )

    def test_001_list_persistent_attach(self):
        ''' Attach the device exposed by the `vm2` to the `vm1` persistently.
        '''
        args = TestNamespace(self.app, [self.vm1])
        # simulate attach
        assignment = qubes.devices.DeviceAssignment(backend_domain=self.vm2,
            ident=self.device.ident, persistent=True, frontend_domain=self.vm1)

        self.vm2.device.frontend_domain = self.vm1
        self.vm1.devices['testclass']._set.add(assignment)
        with qubes.tests.tools.StdoutBuffer() as buf:
            qubes.tools.qvm_device.list_devices(args)
            self.assertEqual(
                buf.getvalue(),
                'vm1:testdev  Description\n'
                'vm2:testdev  Description  vm1  vm1\n'
            )

    def test_002_list_list_temp_attach(self):
        ''' Attach the device exposed by the `vm2` to the `vm1`
            non-persistently.
        '''
        args = TestNamespace(self.app, [self.vm1])
        # simulate attach
        assignment = qubes.devices.DeviceAssignment(backend_domain=self.vm2,
            ident=self.device.ident, persistent=True, frontend_domain=self.vm1)

        self.vm2.device.frontend_domain = self.vm1
        self.vm1.devices['testclass']._set.add(assignment)
        with qubes.tests.tools.StdoutBuffer() as buf:
            qubes.tools.qvm_device.list_devices(args)
            self.assertEqual(buf.getvalue(),
                            'vm1:testdev  Description\n'
                            'vm2:testdev  Description  vm1  vm1\n')

    def test_010_attach(self):
        ''' Test attach action '''
        args = TestNamespace(
            self.app,
            [self.vm1],
            self.device
        )
        qubes.tools.qvm_device.attach_device(args)
        self.assertEventFired(self.vm1,
            'device-attach:testclass', kwargs={'device': self.device})
        self.assertEventNotFired(self.vm2,
            'device-attach:testclass', kwargs={'device': self.device})

    def test_011_double_attach(self):
        ''' Double attach should not be possible '''
        args = TestNamespace(
            self.app,
            [self.vm1],
            self.device
        )
        qubes.tools.qvm_device.attach_device(args)
        with self.assertRaises(qubes.exc.QubesException):
            qubes.tools.qvm_device.attach_device(args)

    def test_020_detach(self):
        ''' Test detach action '''
        args = TestNamespace(
            self.app,
            [self.vm1],
            self.device
        )
        # simulate attach
        self.vm2.device.frontend_domain = self.vm1
        args.device_assignment.frontend_domain = self.vm1
        self.vm1.devices['testclass']._set.add(args.device_assignment)
        qubes.tools.qvm_device.detach_device(args)

    def test_021_detach_not_attached(self):
        ''' Invalid detach action should not be possible '''
        args = TestNamespace(
            self.app,
            [self.vm1],
            self.device
        )
        with self.assertRaises(qubes.exc.QubesException):
            qubes.tools.qvm_device.detach_device(args)
