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
from qubes.qubes import QubesException, QubesTemplateVm
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
        self.qc.save()

        self.make_backup(vms)
        self.remove_vms(vms)
        self.restore_backup()
        self.remove_vms(vms)

    def test_005_compressed_custom(self):
        vms = self.create_backup_vms()
        self.make_backup(vms, do_kwargs={'compressed': "bzip2"})
        self.remove_vms(vms)
        self.restore_backup()
        self.remove_vms(vms)

    def test_100_backup_dom0_no_restore(self):
        self.make_backup([self.qc[0]])
        # TODO: think of some safe way to test restore...

    def test_200_restore_over_existing_directory(self):
        """
        Regression test for #1386
        :return:
        """
        vms = self.create_backup_vms()
        self.make_backup(vms)
        self.remove_vms(vms)
        test_dir = vms[0].dir_path
        os.mkdir(test_dir)
        with open(os.path.join(test_dir, 'some-file.txt'), 'w') as f:
            f.write('test file\n')
        self.restore_backup(
            expect_errors=[
                '*** Directory {} already exists! It has been moved'.format(
                    test_dir)
            ])
        self.remove_vms(vms)

    def test_210_auto_rename(self):
        """
        Test for #869
        :return:
        """
        vms = self.create_backup_vms()
        self.make_backup(vms)
        self.restore_backup(options={
            'rename-conflicting': True
        })
        for vm in vms:
            self.assertIsNotNone(self.qc.get_vm_by_name(vm.name+'1'))
            restored_vm = self.qc.get_vm_by_name(vm.name+'1')
            if vm.netvm and not vm.uses_default_netvm:
                self.assertEqual(restored_vm.netvm.name, vm.netvm.name+'1')

        self.remove_vms(vms)

class TC_10_BackupVMMixin(qubes.tests.BackupTestsMixin):
    def setUp(self):
        super(TC_10_BackupVMMixin, self).setUp()
        self.backupvm = self.qc.add_new_vm(
            "QubesAppVm",
            name=self.make_vm_name('backupvm'),
            template=self.qc.get_vm_by_name(self.template)
        )
        self.backupvm.create_on_disk(verbose=self.verbose)

    def test_100_send_to_vm_file_with_spaces(self):
        vms = self.create_backup_vms()
        self.backupvm.start()
        self.backupvm.run("mkdir '/var/tmp/backup directory'", wait=True)
        self.make_backup(vms,
                         do_kwargs={
                             'appvm': self.backupvm,
                             'compressed': True,
                             'encrypted': True},
                         target='/var/tmp/backup directory')
        self.remove_vms(vms)
        p = self.backupvm.run("ls /var/tmp/backup*/qubes-backup*",
                              passio_popen=True)
        (backup_path, _) = p.communicate()
        backup_path = backup_path.strip()
        self.restore_backup(source=backup_path,
                            appvm=self.backupvm)
        self.remove_vms(vms)

    def test_110_send_to_vm_command(self):
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

    def test_110_send_to_vm_no_space(self):
        """
        Check whether backup properly report failure when no enough space is
        available
        :return:
        """
        vms = self.create_backup_vms()
        self.backupvm.start()
        retcode = self.backupvm.run(
            "truncate -s 50M /home/user/backup.img && "
            "mkfs.ext4 -F /home/user/backup.img && "
            "mkdir /home/user/backup && "
            "mount /home/user/backup.img /home/user/backup -o loop &&"
            "chmod 777 /home/user/backup",
            user="root", wait=True)
        if retcode != 0:
            raise RuntimeError("Failed to prepare backup directory")
        with self.assertRaises(QubesException):
            self.make_backup(vms,
                             do_kwargs={
                                 'appvm': self.backupvm,
                                 'compressed': False,
                                 'encrypted': True},
                             target='/home/user/backup',
                             expect_failure=True)
        self.qc.lock_db_for_writing()
        self.qc.load()
        self.remove_vms(vms)


def load_tests(loader, tests, pattern):
    try:
        qc = qubes.qubes.QubesVmCollection()
        qc.lock_db_for_reading()
        qc.load()
        qc.unlock_db()
        templates = [vm.name for vm in qc.values() if
                     isinstance(vm, QubesTemplateVm)]
    except OSError:
        templates = []
    for template in templates:
        tests.addTests(loader.loadTestsFromTestCase(
            type(
                'TC_10_BackupVM_' + template,
                (TC_10_BackupVMMixin, qubes.tests.QubesTestCase),
                {'template': template})))

    return tests
