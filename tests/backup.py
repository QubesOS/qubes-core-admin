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


import os

import unittest
import sys

import qubes.tests

class TC_00_Backup(qubes.tests.BackupTestsMixin, qubes.tests.QubesTestCase):
    def test_000_basic_backup(self):
        vms = self.create_backup_vms()
        self.make_backup(vms)
        self.remove_vms(vms)
        self.restore_backup()
        self.remove_vms(vms)

    def test_001_compressed_backup(self):
        vms = self.create_backup_vms()
        self.make_backup(vms, do_kwargs={'compressed': True})
        self.remove_vms(vms)
        self.restore_backup()
        self.remove_vms(vms)

    def test_002_encrypted_backup(self):
        vms = self.create_backup_vms()
        self.make_backup(vms, do_kwargs={'encrypted': True})
        self.remove_vms(vms)
        self.restore_backup()
        self.remove_vms(vms)

    def test_003_compressed_encrypted_backup(self):
        vms = self.create_backup_vms()
        self.make_backup(vms,
                         do_kwargs={
                             'compressed': True,
                             'encrypted': True})
        self.remove_vms(vms)
        self.restore_backup()
        self.remove_vms(vms)


    def test_004_sparse_multipart(self):
        vms = []

        vmname = self.make_vm_name('testhvm2')
        if self.verbose:
            print >>sys.stderr, "-> Creating %s" % vmname

        hvmtemplate = self.qc.add_new_vm("QubesTemplateHVm", name=vmname)
        hvmtemplate.create_on_disk(verbose=self.verbose)
        self.fill_image(os.path.join(hvmtemplate.dir_path, '00file'),
                        195*1024*1024-4096*3)
        self.fill_image(hvmtemplate.private_img, 195*1024*1024-4096*3)
        self.fill_image(hvmtemplate.root_img, 1024*1024*1024, sparse=True)
        vms.append(hvmtemplate)

        self.make_backup(vms)
        self.remove_vms(vms)
        self.restore_backup()
        self.remove_vms(vms)


    def test_100_send_to_vm(self):
        vms = self.create_backup_vms()
        self.backupvm.start()
        self.make_backup(vms,
                         do_kwargs={
                             'appvm': self.backupvm,
                             'compressed': True,
                             'encrypted': True},
                         target='dd of=/var/tmp/backup-test')
        self.remove_vms(vms)
        self.restore_backup(source='dd if=/var/tmp/backup-test',
                            appvm=self.backupvm)
        self.remove_vms(vms)
