#!/usr/bin/python
# vim: fileencoding=utf-8

#
# The Qubes OS Project, https://www.qubes-os.org/
#
# Copyright (C) 2014-2015
#                   Marek Marczykowski-Górecki <marmarek@invisiblethingslab.com>
# Copyright (C) 2015  Wojtek Porczyk <woju@invisiblethingslab.com>
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

import multiprocessing
import os
import shutil

import unittest
import time
from qubes.qubes import QubesVmCollection, QubesException, system_path

import qubes.qubes
import qubes.tests
from qubes.qubes import QubesVmLabels


class TC_00_Basic(qubes.tests.SystemTestsMixin, qubes.tests.QubesTestCase):
    def test_000_create(self):
        vmname = self.make_vm_name('appvm')
        vm = self.qc.add_new_vm('QubesAppVm',
            name=vmname, template=self.qc.get_default_template())

        self.assertIsNotNone(vm)
        self.assertEqual(vm.name, vmname)
        self.assertEqual(vm.template, self.qc.get_default_template())
        vm.create_on_disk(verbose=False)

        with self.assertNotRaises(qubes.qubes.QubesException):
            vm.verify_files()


class TC_01_Properties(qubes.tests.SystemTestsMixin, qubes.tests.QubesTestCase):
    def setUp(self):
        super(TC_01_Properties, self).setUp()
        self.vmname = self.make_vm_name('appvm')
        self.vm = self.qc.add_new_vm('QubesAppVm',
            name=self.vmname, template=self.qc.get_default_template())
        self.vm.create_on_disk(verbose=False)

    def save_and_reload_db(self):
        super(TC_01_Properties, self).save_and_reload_db()
        if hasattr(self, 'vm'):
            self.vm = self.qc.get(self.vm.qid, None)
        if hasattr(self, 'netvm'):
            self.netvm = self.qc.get(self.netvm.qid, None)

    def test_000_rename(self):
        newname = self.make_vm_name('newname')

        self.assertEqual(self.vm.name, self.vmname)
        self.vm.write_firewall_conf({'allow': False, 'allowDns': False})
        pre_rename_firewall = self.vm.get_firewall_conf()

        #TODO: change to setting property when implemented
        self.vm.set_name(newname)
        self.assertEqual(self.vm.name, newname)
        self.assertEqual(self.vm.dir_path,
            os.path.join(system_path['qubes_appvms_dir'], newname))
        self.assertEqual(self.vm.conf_file,
            os.path.join(self.vm.dir_path, newname + '.conf'))
        self.assertTrue(os.path.exists(
            os.path.join(self.vm.dir_path, "apps", newname + "-vm.directory")))
        # FIXME: set whitelisted-appmenus.list first
        self.assertTrue(os.path.exists(
            os.path.join(self.vm.dir_path, "apps", newname + "-firefox.desktop")))
        self.assertTrue(os.path.exists(
            os.path.join(os.getenv("HOME"), ".local/share/desktop-directories",
                newname + "-vm.directory")))
        self.assertTrue(os.path.exists(
            os.path.join(os.getenv("HOME"), ".local/share/applications",
                newname + "-firefox.desktop")))
        self.assertFalse(os.path.exists(
            os.path.join(os.getenv("HOME"), ".local/share/desktop-directories",
                self.vmname + "-vm.directory")))
        self.assertFalse(os.path.exists(
            os.path.join(os.getenv("HOME"), ".local/share/applications",
                self.vmname + "-firefox.desktop")))
        self.assertEquals(pre_rename_firewall, self.vm.get_firewall_conf())
        with self.assertNotRaises(QubesException, OSError):
            self.vm.write_firewall_conf({'allow': False})

    def test_010_netvm(self):
        if self.qc.get_default_netvm() is None:
            self.skip("Set default NetVM before running this test")
        self.netvm = self.qc.add_new_vm("QubesNetVm",
            name=self.make_vm_name('netvm'),
            template=self.qc.get_default_template())
        self.netvm.create_on_disk(verbose=False)
        # TODO: remove this line after switching to core3
        self.save_and_reload_db()

        self.assertEquals(self.vm.netvm, self.qc.get_default_netvm())
        self.vm.uses_default_netvm = False
        self.vm.netvm = None
        self.assertIsNone(self.vm.netvm)
        self.save_and_reload_db()
        self.assertIsNone(self.vm.netvm)

        self.vm.netvm = self.qc[self.netvm.qid]
        self.assertEquals(self.vm.netvm.qid, self.netvm.qid)
        self.save_and_reload_db()
        self.assertEquals(self.vm.netvm.qid, self.netvm.qid)

        self.vm.uses_default_netvm = True
        # TODO: uncomment when properly implemented
        # self.assertEquals(self.vm.netvm.qid, self.qc.get_default_netvm().qid)
        self.save_and_reload_db()
        self.assertEquals(self.vm.netvm.qid, self.qc.get_default_netvm().qid)

        with self.assertRaises(ValueError):
            self.vm.netvm = self.vm

    def test_020_dispvm_netvm(self):
        if self.qc.get_default_netvm() is None:
            self.skip("Set default NetVM before running this test")
        self.netvm = self.qc.add_new_vm("QubesNetVm",
            name=self.make_vm_name('netvm'),
            template=self.qc.get_default_template())
        self.netvm.create_on_disk(verbose=False)

        self.assertEquals(self.vm.netvm, self.vm.dispvm_netvm)
        self.vm.uses_default_dispvm_netvm = False
        self.vm.dispvm_netvm = None
        self.assertIsNone(self.vm.dispvm_netvm)
        self.save_and_reload_db()
        self.assertIsNone(self.vm.dispvm_netvm)

        self.vm.dispvm_netvm = self.netvm
        self.assertEquals(self.vm.dispvm_netvm, self.netvm)
        self.save_and_reload_db()
        self.assertEquals(self.vm.dispvm_netvm, self.netvm)

        self.vm.uses_default_dispvm_netvm = True
        self.assertEquals(self.vm.dispvm_netvm, self.vm.netvm)
        self.save_and_reload_db()
        self.assertEquals(self.vm.dispvm_netvm, self.vm.netvm)

        with self.assertRaises(ValueError):
            self.vm.dispvm_netvm = self.vm

    def test_030_clone(self):
        testvm1 = self.qc.add_new_vm(
            "QubesAppVm",
            name=self.make_vm_name("vm"),
            template=self.qc.get_default_template())
        testvm1.create_on_disk(verbose=False)
        testvm2 = self.qc.add_new_vm(testvm1.__class__.__name__,
                                     name=self.make_vm_name("clone"),
                                     template=testvm1.template,
                                     )
        testvm2.clone_attrs(src_vm=testvm1)
        testvm2.clone_disk_files(src_vm=testvm1, verbose=False)

        # qubes.xml reload
        self.save_and_reload_db()
        testvm1 = self.qc[testvm1.qid]
        testvm2 = self.qc[testvm2.qid]

        self.assertEquals(testvm1.label, testvm2.label)
        self.assertEquals(testvm1.netvm, testvm2.netvm)
        self.assertEquals(testvm1.uses_default_netvm,
                          testvm2.uses_default_netvm)
        self.assertEquals(testvm1.kernel, testvm2.kernel)
        self.assertEquals(testvm1.kernelopts, testvm2.kernelopts)
        self.assertEquals(testvm1.uses_default_kernel,
                          testvm2.uses_default_kernel)
        self.assertEquals(testvm1.uses_default_kernelopts,
                          testvm2.uses_default_kernelopts)
        self.assertEquals(testvm1.memory, testvm2.memory)
        self.assertEquals(testvm1.maxmem, testvm2.maxmem)
        self.assertEquals(testvm1.pcidevs, testvm2.pcidevs)
        self.assertEquals(testvm1.include_in_backups,
                          testvm2.include_in_backups)
        self.assertEquals(testvm1.default_user, testvm2.default_user)
        self.assertEquals(testvm1.services, testvm2.services)
        self.assertEquals(testvm1.get_firewall_conf(),
                          testvm2.get_firewall_conf())

        # now some non-default values
        testvm1.netvm = None
        testvm1.uses_default_netvm = False
        testvm1.label = QubesVmLabels['orange']
        testvm1.memory = 512
        firewall = testvm1.get_firewall_conf()
        firewall['allowDns'] = False
        firewall['allowYumProxy'] = False
        firewall['rules'] = [{'address': '1.2.3.4',
                              'netmask': 24,
                              'proto': 'tcp',
                              'portBegin': 22,
                              'portEnd': 22,
                              }]
        testvm1.write_firewall_conf(firewall)

        testvm3 = self.qc.add_new_vm(testvm1.__class__.__name__,
                                     name=self.make_vm_name("clone2"),
                                     template=testvm1.template,
                                     )
        testvm3.clone_attrs(src_vm=testvm1)
        testvm3.clone_disk_files(src_vm=testvm1, verbose=False)

        # qubes.xml reload
        self.save_and_reload_db()
        testvm1 = self.qc[testvm1.qid]
        testvm3 = self.qc[testvm3.qid]

        self.assertEquals(testvm1.label, testvm3.label)
        self.assertEquals(testvm1.netvm, testvm3.netvm)
        self.assertEquals(testvm1.uses_default_netvm,
                          testvm3.uses_default_netvm)
        self.assertEquals(testvm1.kernel, testvm3.kernel)
        self.assertEquals(testvm1.kernelopts, testvm3.kernelopts)
        self.assertEquals(testvm1.uses_default_kernel,
                          testvm3.uses_default_kernel)
        self.assertEquals(testvm1.uses_default_kernelopts,
                          testvm3.uses_default_kernelopts)
        self.assertEquals(testvm1.memory, testvm3.memory)
        self.assertEquals(testvm1.maxmem, testvm3.maxmem)
        self.assertEquals(testvm1.pcidevs, testvm3.pcidevs)
        self.assertEquals(testvm1.include_in_backups,
                          testvm3.include_in_backups)
        self.assertEquals(testvm1.default_user, testvm3.default_user)
        self.assertEquals(testvm1.services, testvm3.services)
        self.assertEquals(testvm1.get_firewall_conf(),
                          testvm3.get_firewall_conf())

# vim: ts=4 sw=4 et
