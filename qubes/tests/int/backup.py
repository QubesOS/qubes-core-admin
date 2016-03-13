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
import qubes
import qubes.exc
import qubes.tests
import qubes.vm.appvm
import qubes.vm.templatevm

class TC_00_Backup(qubes.tests.BackupTestsMixin, qubes.tests.QubesTestCase):
    def test_000_basic_backup(self):
        vms = self.create_backup_vms()
        self.make_backup(vms)
        self.remove_vms(vms)
        self.restore_backup()
        for vm in vms:
            self.assertIn(vm.name, self.app.domains)

    def test_001_compressed_backup(self):
        vms = self.create_backup_vms()
        self.make_backup(vms, compressed=True)
        self.remove_vms(vms)
        self.restore_backup()
        for vm in vms:
            self.assertIn(vm.name, self.app.domains)

    def test_002_encrypted_backup(self):
        vms = self.create_backup_vms()
        self.make_backup(vms, encrypted=True)
        self.remove_vms(vms)
        self.restore_backup()
        for vm in vms:
            self.assertIn(vm.name, self.app.domains)

    def test_003_compressed_encrypted_backup(self):
        vms = self.create_backup_vms()
        self.make_backup(vms, compressed=True, encrypted=True)
        self.remove_vms(vms)
        self.restore_backup()
        for vm in vms:
            self.assertIn(vm.name, self.app.domains)

    def test_004_sparse_multipart(self):
        vms = []

        vmname = self.make_vm_name('testhvm2')
        if self.verbose:
            print >>sys.stderr, "-> Creating %s" % vmname

        hvmtemplate = self.app.add_new_vm(
            qubes.vm.templatevm.TemplateVM, name=vmname, hvm=True, label='red')
        hvmtemplate.create_on_disk()
        self.fill_image(os.path.join(hvmtemplate.dir_path, '00file'),
                        195*1024*1024-4096*3)
        self.fill_image(hvmtemplate.private_img, 195*1024*1024-4096*3)
        self.fill_image(hvmtemplate.root_img, 1024*1024*1024, sparse=True)
        vms.append(hvmtemplate)
        self.app.save()

        self.make_backup(vms)
        self.remove_vms(vms)
        self.restore_backup()
        for vm in vms:
            self.assertIn(vm.name, self.app.domains)
        # TODO check vm.backup_timestamp

    def test_005_compressed_custom(self):
        vms = self.create_backup_vms()
        self.make_backup(vms, compressed="bzip2")
        self.remove_vms(vms)
        self.restore_backup()
        for vm in vms:
            self.assertIn(vm.name, self.app.domains)

    def test_100_backup_dom0_no_restore(self):
        # do not write it into dom0 home itself...
        os.mkdir('/var/tmp/test-backup')
        self.backupdir = '/var/tmp/test-backup'
        self.make_backup([self.app.domains[0]])
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

    def test_210_auto_rename(self):
        """
        Test for #869
        :return:
        """
        vms = self.create_backup_vms()
        self.make_backup(vms)
        self.restore_backup(options={
            'rename_conflicting': True
        })
        for vm in vms:
            with self.assertNotRaises(
                    (qubes.exc.QubesVMNotFoundError, KeyError)):
                restored_vm = self.app.domains[vm.name + '1']
            if vm.netvm and not vm.property_is_default('netvm'):
                self.assertEqual(restored_vm.netvm.name, vm.netvm.name + '1')


class TC_10_BackupVMMixin(qubes.tests.BackupTestsMixin):
    def setUp(self):
        super(TC_10_BackupVMMixin, self).setUp()
        self.backupvm = self.app.add_new_vm(
            qubes.vm.appvm.AppVM,
            label='red',
            name=self.make_vm_name('backupvm'),
            template=self.template
        )
        self.backupvm.create_on_disk()

    def test_100_send_to_vm_file_with_spaces(self):
        vms = self.create_backup_vms()
        self.backupvm.start()
        self.backupvm.run("mkdir '/var/tmp/backup directory'", wait=True)
        self.make_backup(vms, target_vm=self.backupvm,
            compressed=True, encrypted=True,
            target='/var/tmp/backup directory')
        self.remove_vms(vms)
        p = self.backupvm.run("ls /var/tmp/backup*/qubes-backup*",
                              passio_popen=True)
        (backup_path, _) = p.communicate()
        backup_path = backup_path.strip()
        self.restore_backup(source=backup_path,
                            appvm=self.backupvm)

    def test_110_send_to_vm_command(self):
        vms = self.create_backup_vms()
        self.backupvm.start()
        self.make_backup(vms, target_vm=self.backupvm,
            compressed=True, encrypted=True,
            target='dd of=/var/tmp/backup-test')
        self.remove_vms(vms)
        self.restore_backup(source='dd if=/var/tmp/backup-test',
                            appvm=self.backupvm)

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
        with self.assertRaises(qubes.exc.QubesException):
            self.make_backup(vms, target_vm=self.backupvm,
                compressed=False, encrypted=True,
                target='/home/user/backup',
                expect_failure=True)


def load_tests(loader, tests, pattern):
    try:
        app = qubes.Qubes()
        templates = [vm.name for vm in app.domains if
                     isinstance(vm, qubes.vm.templatevm.TemplateVM)]
    except OSError:
        templates = []
    for template in templates:
        tests.addTests(loader.loadTestsFromTestCase(
            type(
                'TC_10_BackupVM_' + template,
                (TC_10_BackupVMMixin, qubes.tests.QubesTestCase),
                {'template': template})))

    return tests
