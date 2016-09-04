#!/usr/bin/python2 -O
# vim: fileencoding=utf-8
# pylint: disable=protected-access,pointless-statement

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

import qubes
import qubes.devices
import qubes.tools.qvm_device

import qubes.tests
import qubes.tests.devices
import qubes.tests.tools

class TestNamespace(object):
    def __init__(self, app, domains=None, device=None):
        super(TestNamespace, self).__init__()
        self.app = app
        self.devclass = 'testclass'
        if domains:
            self.domains = domains
        if device:
            self.device = device


class TC_00_Actions(qubes.tests.QubesTestCase):
    def setUp(self):
        super(TC_00_Actions, self).setUp()
        self.app = qubes.tests.devices.TestApp()
        self.vm1 = qubes.tests.devices.TestVM(self.app, 'vm1')
        self.vm2 = qubes.tests.devices.TestVM(self.app, 'vm2')
        self.device = self.vm2.device

    def test_000_list_all(self):
        args = TestNamespace(self.app)
        with qubes.tests.tools.StdoutBuffer() as buf:
            qubes.tools.qvm_device.list_devices(args)
            self.assertEventFired(self.vm1,
                'device-list:testclass')
            self.assertEventFired(self.vm2,
                'device-list:testclass')
            self.assertEventNotFired(self.vm1,
                'device-list-attached:testclass')
            self.assertEventNotFired(self.vm2,
                'device-list-attached:testclass')
            self.assertEqual(
                buf.getvalue(),
                'vm1:testdev  Description  \n'
                'vm2:testdev  Description  \n'
            )

    def test_001_list_one(self):
        args = TestNamespace(self.app, [self.vm1])
        # simulate attach
        self.vm2.device.frontend_domain = self.vm1
        self.vm1.devices['testclass']._set.add(self.device)
        with qubes.tests.tools.StdoutBuffer() as buf:
            qubes.tools.qvm_device.list_devices(args)
            self.assertEventFired(self.vm1,
                'device-list-attached:testclass')
            self.assertEventNotFired(self.vm1,
                'device-list:testclass')
            self.assertEventNotFired(self.vm2,
                'device-list:testclass')
            self.assertEventNotFired(self.vm2,
                'device-list-attached:testclass')
            self.assertEqual(
                buf.getvalue(),
                'vm2:testdev  Description  vm1\n'
            )

    def test_002_list_one_non_persistent(self):
        args = TestNamespace(self.app, [self.vm1])
        # simulate attach
        self.vm2.device.frontend_domain = self.vm1
        with qubes.tests.tools.StdoutBuffer() as buf:
            qubes.tools.qvm_device.list_devices(args)
            self.assertEventFired(self.vm1,
                'device-list-attached:testclass')
            self.assertEventNotFired(self.vm1,
                'device-list:testclass')
            self.assertEventNotFired(self.vm2,
                'device-list:testclass')
            self.assertEventNotFired(self.vm2,
                'device-list-attached:testclass')
            self.assertEqual(
                buf.getvalue(),
                'vm2:testdev  Description  vm1\n'
            )

    def test_010_attach(self):
        args = TestNamespace(
            self.app,
            [self.vm1],
            self.device
        )
        qubes.tools.qvm_device.attach_device(args)
        self.assertEventFired(self.vm1,
            'device-attach:testclass', [self.device])
        self.assertEventNotFired(self.vm2,
            'device-attach:testclass', [self.device])

    def test_011_double_attach(self):
        args = TestNamespace(
            self.app,
            [self.vm1],
            self.device
        )
        qubes.tools.qvm_device.attach_device(args)
        with self.assertRaises(qubes.exc.QubesException):
            qubes.tools.qvm_device.attach_device(args)

    def test_020_detach(self):
        args = TestNamespace(
            self.app,
            [self.vm1],
            self.device
        )
        # simulate attach
        self.vm2.device.frontend_domain = self.vm1
        self.vm1.devices['testclass']._set.add(self.device)
        qubes.tools.qvm_device.detach_device(args)

    def test_021_detach_not_attached(self):
        args = TestNamespace(
            self.app,
            [self.vm1],
            self.device
        )
        with self.assertRaises(qubes.exc.QubesException):
            qubes.tools.qvm_device.detach_device(args)
