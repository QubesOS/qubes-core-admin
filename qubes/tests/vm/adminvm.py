#
# The Qubes OS Project, https://www.qubes-os.org/
#
# Copyright (C) 2014-2015  Joanna Rutkowska <joanna@invisiblethingslab.com>
# Copyright (C) 2014-2015  Wojtek Porczyk <woju@invisiblethingslab.com>
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

import unittest

import qubes
import qubes.exc
import qubes.vm
import qubes.vm.adminvm

import qubes.tests

@qubes.tests.skipUnlessDom0
class TC_00_AdminVM(qubes.tests.QubesTestCase):
    def setUp(self):
        super().setUp()
        try:
            self.app = qubes.tests.vm.TestApp()
            self.vm = qubes.vm.adminvm.AdminVM(self.app,
                xml=None, qid=0, name='dom0')
        except:  # pylint: disable=bare-except
            if self.id().endswith('.test_000_init'):
                raise
            self.skipTest('setup failed')

    def test_000_init(self):
        pass

    def test_100_xid(self):
        self.assertEqual(self.vm.xid, 0)

    def test_101_libvirt_domain(self):
        self.assertIs(self.vm.libvirt_domain, None)

    def test_200_libvirt_netvm(self):
        self.assertIs(self.vm.netvm, None)

    def test_300_is_running(self):
        self.assertTrue(self.vm.is_running())

    def test_301_get_power_state(self):
        self.assertEqual(self.vm.get_power_state(), 'Running')

    def test_302_get_mem(self):
        self.assertGreater(self.vm.get_mem(), 0)

    @unittest.skip('mock object does not support this')
    def test_303_get_mem_static_max(self):
        self.assertGreater(self.vm.get_mem_static_max(), 0)

    def test_304_get_disk_utilization(self):
        self.assertEqual(self.vm.storage.get_disk_utilization(), 0)

    def test_305_has_no_private_volume(self):
        with self.assertRaises(KeyError):
            self.vm.volumes['private']

    def test_306_has_no_root_volume(self):
        with self.assertRaises(KeyError):
            self.vm.volumes['root']

    def test_307_has_no_volatile_volume(self):
        with self.assertRaises(KeyError):
            self.vm.volumes['volatile']

    def test_310_start(self):
        with self.assertRaises(qubes.exc.QubesException):
            self.vm.start()

    @unittest.skip('this functionality is undecided')
    def test_311_suspend(self):
        with self.assertRaises(qubes.exc.QubesException):
            self.vm.suspend()
