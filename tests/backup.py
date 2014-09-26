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
#
from multiprocessing import Event, Queue

import os
import shutil

import unittest
import sys
from qubes.qubes import QubesVmCollection, QubesException
from qubes import backup

VM_PREFIX = "test-"

class BackupTests(unittest.TestCase):
    def setUp(self):
        self.error_detected = Queue()
        self.verbose = False
        self.qc = QubesVmCollection()
        self.qc.lock_db_for_writing()
        self.qc.load()

        if self.verbose:
            print >>sys.stderr, "-> Creating backupvm"
        backupvm = self.qc.add_new_vm("QubesAppVm",
                           name="%sbackupvm" % VM_PREFIX,
                           template=self.qc.get_default_template())
        backupvm.create_on_disk(verbose=self.verbose)
        self.qc.save()
        self.qc.unlock_db()

        self.backupdir = os.path.join(os.environ["HOME"], "test-backup")
        os.mkdir(self.backupdir)


    def tearDown(self):
        vmlist = [vm for vm in self.qc.values() if vm.name.startswith(
            VM_PREFIX)]
        self.remove_vms(vmlist)
        shutil.rmtree(self.backupdir)

    def print_progress(self, progress):
        if self.verbose:
            print >> sys.stderr, "\r-> Backing up files: {0}%...".format(progress)

    def error_callback(self, message):
        self.error_detected.put(message)
        if self.verbose:
            print >> sys.stderr, "ERROR: {0}".format(message)

    def print_callback(self, msg):
        if self.verbose:
            print msg

    def fill_image(self, path, size=None, sparse=False):
        block_size = 4096

        if self.verbose:
            print >>sys.stderr, "-> Filling %s" % path
        f = open(path, 'w+')
        if size is None:
            f.seek(0, 2)
            size = f.tell()
        f.seek(0)

        for block_num in xrange(size/block_size):
            f.write('a' * block_size)
            if sparse:
                f.seek(block_size, 1)

        f.close()

    def create_basic_vms(self, leave_locked=False):
        template=self.qc.get_default_template()

        vms = []
        self.qc.lock_db_for_writing()
        self.qc.load()
        vmname = "%stest1" % VM_PREFIX
        if self.verbose:
            print >>sys.stderr, "-> Creating %s" % vmname
        testvm1 = self.qc.add_new_vm("QubesAppVm",
                                     name=vmname,
                                     template=template)
        testvm1.create_on_disk(verbose=self.verbose)
        vms.append(testvm1)
        self.fill_image(testvm1.private_img, 100*1024*1024)

        vmname = "%stesthvm1" % VM_PREFIX
        if self.verbose:
            print >>sys.stderr, "-> Creating %s" % vmname
        testvm2 = self.qc.add_new_vm("QubesHVm",
                                     name=vmname)
        testvm2.create_on_disk(verbose=self.verbose)
        self.fill_image(testvm2.root_img, 1024*1024*1024, True)
        vms.append(testvm2)

        if not leave_locked:
            self.qc.save()
            self.qc.unlock_db()

        return vms

    def remove_vms(self, vms):
        self.qc.lock_db_for_writing()
        self.qc.load()

        for vm in vms:
            if isinstance(vm, str):
                vm = self.qc.get_vm_by_name(vm)
            else:
                vm = self.qc[vm.qid]
            if self.verbose:
                print >>sys.stderr, "-> Removing %s" % vm.name
            vm.remove_from_disk()
            self.qc.pop(vm.qid)
        self.qc.save()
        self.qc.unlock_db()

    def make_backup(self, vms, prepare_kwargs=dict(), do_kwargs=dict()):
        try:
            files_to_backup = \
                backup.backup_prepare(vms,
                                      print_callback=self.print_callback,
                                      **prepare_kwargs)
        except QubesException as e:
            self.fail("QubesException during backup_prepare: %s" % str(e))

        try:
            backup.backup_do(self.backupdir, files_to_backup, "qubes",
                             progress_callback=self.print_progress,
                             **do_kwargs)
        except QubesException as e:
            self.fail("QubesException during backup_do: %s" % str(e))

    def restore_backup(self):
        backupfile = os.path.join(self.backupdir,
                                  sorted(os.listdir(self.backupdir))[-1])

        try:
            backup_info = backup.backup_restore_prepare(
                backupfile, "qubes", print_callback=self.print_callback)
        except QubesException as e: self.fail(
                "QubesException during backup_restore_prepare: %s" % str(e))
        if self.verbose:
            backup.backup_restore_print_summary(backup_info)

        try:
            backup.backup_restore_do(
                backup_info,
                print_callback=self.print_callback,
                error_callback=self.error_callback)
                # TODO: print_callback=self.print_callback if self.verbose else None,
        except QubesException as e:
            self.fail("QubesException during backup_restore_do: %s" % str(e))
        errors = []
        while not self.error_detected.empty():
            errors.append(self.error_detected.get())
        self.assertTrue(len(errors) == 0,
                         "Error(s) detected during backup_restore_do: %s" %
                         '\n'.join(errors))
        os.unlink(backupfile)

    def test_basic_backup(self):
        vms = self.create_basic_vms()
        self.make_backup(vms)
        self.remove_vms(vms)
        self.restore_backup()
        self.remove_vms(vms)

    def test_compressed_backup(self):
        vms = self.create_basic_vms()
        self.make_backup(vms, do_kwargs={'compressed': True})
        self.remove_vms(vms)
        self.restore_backup()
        self.remove_vms(vms)

    def test_encrypted_backup(self):
        vms = self.create_basic_vms()
        self.make_backup(vms, do_kwargs={'encrypted': True})
        self.remove_vms(vms)
        self.restore_backup()
        self.remove_vms(vms)

    @unittest.expectedFailure
    def test_compressed_encrypted_backup(self):
        vms = self.create_basic_vms()
        self.make_backup(vms,
                         do_kwargs={
                             'compressed': True,
                             'encrypted': True})
        self.remove_vms(vms)
        self.restore_backup()
        self.remove_vms(vms)

    def test_sparse_multipart(self):
        vms = []
        self.qc.lock_db_for_writing()
        self.qc.load()

        vmname = "%stesthvm2" % VM_PREFIX
        if self.verbose:
            print >>sys.stderr, "-> Creating %s" % vmname

        hvmtemplate = self.qc.add_new_vm("QubesTemplateHVm",
                                         name=vmname)
        hvmtemplate.create_on_disk(verbose=self.verbose)
        self.fill_image(os.path.join(hvmtemplate.dir_path, '00file'),
                        195*1024*1024-4096*3)
        self.fill_image(hvmtemplate.private_img, 195*1024*1024-4096*3)
        self.fill_image(hvmtemplate.root_img, 1024*1024*1024, sparse=True)
        vms.append(hvmtemplate)

        self.qc.save()
        self.qc.unlock_db()

        self.make_backup(vms)
        self.remove_vms(vms)
        self.restore_backup()
        self.remove_vms(vms)




