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

import qubes
import qubes.vm.qubesvm
import qubes.tests

class TC_00_Basic(qubes.tests.SystemTestsMixin, qubes.tests.QubesTestCase):
    def setUp(self):
        self.app = qubes.Qubes.create_empty_store(qubes.tests.XMLPATH)

    def test_000_qubes_create(self):
        self.assertIsInstance(self.app, qubes.Qubes)

    def test_001_qvm_create_default_template(self):
        self.app.add_new_vm


    def test_100_qvm_create(self):
        app = qubes.Qubes(qubes.tests.XMLPATH)
        vmname = self.make_vm_name('appvm')

        vm = app.add_new_vm(qubes.vm.appvm.AppVM,
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



# vim: ts=4 sw=4 et
