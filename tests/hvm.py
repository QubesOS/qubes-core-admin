#!/usr/bin/python
# -*- coding: utf-8 -*-
#
# The Qubes OS Project, http://www.qubes-os.org
#
# Copyright (C) 2016 Marek Marczykowski-Górecki
#                                        <marmarek@invisiblethingslab.com>
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
#

import qubes.tests
from qubes.qubes import QubesException

class TC_10_HVM(qubes.tests.SystemTestsMixin, qubes.tests.QubesTestCase):
    # TODO: test with some OS inside
    # TODO: windows tools tests

    def test_000_create_start(self):
        testvm1 = self.qc.add_new_vm("QubesHVm",
                                     name=self.make_vm_name('vm1'))
        testvm1.create_on_disk(verbose=False)
        self.qc.save()
        self.qc.unlock_db()
        testvm1.start()
        self.assertEquals(testvm1.get_power_state(), "Running")

    def test_010_create_start_template(self):
        templatevm = self.qc.add_new_vm("QubesTemplateHVm",
                                        name=self.make_vm_name('template'))
        templatevm.create_on_disk(verbose=False)
        self.qc.save()
        self.qc.unlock_db()

        templatevm.start()
        self.assertEquals(templatevm.get_power_state(), "Running")

    def test_020_create_start_template_vm(self):
        templatevm = self.qc.add_new_vm("QubesTemplateHVm",
                                        name=self.make_vm_name('template'))
        templatevm.create_on_disk(verbose=False)
        testvm2 = self.qc.add_new_vm("QubesHVm",
                                     name=self.make_vm_name('vm2'),
                                     template=templatevm)
        testvm2.create_on_disk(verbose=False)
        self.qc.save()
        self.qc.unlock_db()

        testvm2.start()
        self.assertEquals(testvm2.get_power_state(), "Running")

    def test_030_prevent_simultaneus_start(self):
        templatevm = self.qc.add_new_vm("QubesTemplateHVm",
                                        name=self.make_vm_name('template'))
        templatevm.create_on_disk(verbose=False)
        testvm2 = self.qc.add_new_vm("QubesHVm",
                                     name=self.make_vm_name('vm2'),
                                     template=templatevm)
        testvm2.create_on_disk(verbose=False)
        self.qc.save()
        self.qc.unlock_db()

        templatevm.start()
        self.assertEquals(templatevm.get_power_state(), "Running")
        self.assertRaises(QubesException, testvm2.start)
        templatevm.force_shutdown()
        testvm2.start()
        self.assertEquals(testvm2.get_power_state(), "Running")
        self.assertRaises(QubesException, templatevm.start)

    def test_100_resize_root_img(self):
        testvm1 = self.qc.add_new_vm("QubesHVm",
                                     name=self.make_vm_name('vm1'))
        testvm1.create_on_disk(verbose=False)
        self.qc.save()
        self.qc.unlock_db()
        testvm1.resize_root_img(30*1024**3)
        self.assertEquals(testvm1.get_root_img_sz(), 30*1024**3)
        testvm1.start()
        self.assertEquals(testvm1.get_power_state(), "Running")
        # TODO: launch some OS there and check the size

    def test_200_start_invalid_drive(self):
        """Regression test for #1619"""
        testvm1 = self.qc.add_new_vm("QubesHVm",
                                     name=self.make_vm_name('vm1'))
        testvm1.create_on_disk(verbose=False)
        testvm1.drive = 'hd:dom0:/invalid'
        self.qc.save()
        self.qc.unlock_db()
        try:
            testvm1.start()
        except Exception as e:
            self.assertIsInstance(e, QubesException)
        else:
            self.fail('No exception raised')

    def test_201_start_invalid_drive_cdrom(self):
        """Regression test for #1619"""
        testvm1 = self.qc.add_new_vm("QubesHVm",
                                     name=self.make_vm_name('vm1'))
        testvm1.create_on_disk(verbose=False)
        testvm1.drive = 'cdrom:dom0:/invalid'
        self.qc.save()
        self.qc.unlock_db()
        try:
            testvm1.start()
        except Exception as e:
            self.assertIsInstance(e, QubesException)
        else:
            self.fail('No exception raised')

