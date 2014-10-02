#!/usr/bin/python
# -*- coding: utf-8 -*-
#
# The Qubes OS Project, http://www.qubes-os.org
#
# Copyright (C) 2014 Marek Marczykowski-Górecki <marmarek@invisiblethingslab.com>
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.
#
import os
import shutil

import unittest
from qubes.qubes import QubesVmCollection, QubesException, system_path

VM_PREFIX = "test-"

class BasicTests(unittest.TestCase):
    def setUp(self):
        self.qc = QubesVmCollection()
        self.qc.lock_db_for_reading()
        self.qc.load()
        self.qc.unlock_db()

    def remove_vms(self, vms):
        self.qc.lock_db_for_writing()
        self.qc.load()

        for vm in vms:
            if isinstance(vm, str):
                vm = self.qc.get_vm_by_name(vm)
            else:
                vm = self.qc[vm.qid]
            try:
                vm.remove_from_disk()
            except OSError:
                pass
            self.qc.pop(vm.qid)
        self.qc.save()
        self.qc.unlock_db()

    def tearDown(self):
        vmlist = [vm for vm in self.qc.values() if vm.name.startswith(
            VM_PREFIX)]
        self.remove_vms(vmlist)

    def test_create(self):
        self.qc.lock_db_for_writing()
        self.qc.load()

        vmname = VM_PREFIX + "appvm"
        vm = self.qc.add_new_vm("QubesAppVm", name=vmname,
                                template=self.qc.get_default_template())
        self.qc.save()
        self.qc.unlock_db()
        self.assertIsNotNone(vm)
        self.assertEqual(vm.name, vmname)
        self.assertEqual(vm.template, self.qc.get_default_template())
        vm.create_on_disk(verbose=False)
        try:
            vm.verify_files()
        except QubesException:
            self.fail("verify_files() failed")

class VmPropTests(unittest.TestCase):
    def setUp(self):
        self.qc = QubesVmCollection()
        self.qc.lock_db_for_writing()
        self.qc.load()
        self.vmname = VM_PREFIX + "appvm"
        self.vm = self.qc.add_new_vm("QubesAppVm", name=self.vmname,
                                     template=self.qc.get_default_template())
        self.qc.save()
        self.vm.create_on_disk(verbose=False)
        # WARNING: lock remains taken

    def remove_vms(self, vms):
        for vm in vms:
            if isinstance(vm, str):
                vm = self.qc.get_vm_by_name(vm)
            else:
                vm = self.qc[vm.qid]
            vm.remove_from_disk()
            self.qc.pop(vm.qid)

    def tearDown(self):
        # WARNING: lock still taken in setUp()
        vmlist = [vm for vm in self.qc.values() if vm.name.startswith(
            VM_PREFIX)]
        self.remove_vms(vmlist)
        self.qc.save()
        self.qc.unlock_db()

    def test_rename(self):
        self.assertEqual(self.vm.name, self.vmname)
        newname = VM_PREFIX + "newname"
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
