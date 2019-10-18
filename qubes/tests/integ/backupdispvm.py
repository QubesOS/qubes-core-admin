#
# The Qubes OS Project, https://www.qubes-os.org/
#
# Copyright (C) 2019
#                   Marek Marczykowski-Górecki <marmarek@invisiblethingslab.com>
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

import hashlib
import logging
import multiprocessing

import os
import shutil

import sys

import asyncio
import tempfile

import unittest.mock

import qubes
import qubes.backup
import qubes.storage.lvm
import qubes.tests
import qubes.tests.integ.backup
import qubes.tests.storage_lvm
import qubes.vm
import qubes.vm.appvm
import qubes.vm.templatevm
import qubes.vm.qubesvm

try:
    import qubesadmin.exc
    from qubesadmin.backup.dispvm import RestoreInDisposableVM
    restore_available = True
except ImportError:
    restore_available = False


class TC_00_RestoreInDispVM(qubes.tests.integ.backup.BackupTestsMixin):
    def setUp(self):
        if not restore_available:
            self.skipTest('qubesadmin module not installed')
        super(TC_00_RestoreInDispVM, self).setUp()
        self.mgmt_vm = self.app.add_new_vm(
            qubes.vm.appvm.AppVM,
            label='red',
            name=self.make_vm_name('mgmtvm'),
            template=self.template
        )
        self.loop.run_until_complete(self.mgmt_vm.create_on_disk())
        self.mgmt_vm.template_for_dispvms = True
        self.app.management_dispvm = self.mgmt_vm
        self.backupvm = self.app.add_new_vm(
            qubes.vm.appvm.AppVM,
            label='red',
            name=self.make_vm_name('backupvm'),
            template=self.template
        )
        self.loop.run_until_complete(self.backupvm.create_on_disk())

    def restore_backup(self, source=None, appvm=None, options=None,
                       expect_errors=None, manipulate_restore_info=None,
                       passphrase='qubes'):
        args = unittest.mock.Mock(spec=['app', 'appvm', 'backup_location', 'vms'])
        args.app = qubesadmin.Qubes()
        args.appvm = appvm
        args.backup_location = source
        # XXX FIXME
        args.app.blind_mode = True
        args.vms = []
        args.auto_close = True
        with tempfile.NamedTemporaryFile() as pass_file:
            pass_file.file.write(passphrase.encode())
            pass_file.file.flush()
            args.pass_file = pass_file.name
            restore_in_dispvm = RestoreInDisposableVM(args.app, args)
            try:
                backup_log = self.loop.run_until_complete(
                    self.loop.run_in_executor(None, restore_in_dispvm.run))
            except qubesadmin.exc.BackupRestoreError as e:
                self.fail(str(e) + ' backup log: ' + e.backup_log.decode())
            self.app.log.debug(backup_log.decode())

    def test_000_basic_backup(self):
        self.loop.run_until_complete(self.backupvm.start())
        self.loop.run_until_complete(self.backupvm.run_for_stdio(
            "mkdir '/var/tmp/backup directory'"))
        vms = self.create_backup_vms()
        try:
            orig_hashes = self.vm_checksum(vms)
            vms_info = self.get_vms_info(vms)
            self.make_backup(vms,
                target='/var/tmp/backup directory',
                target_vm=self.backupvm)
            self.remove_vms(reversed(vms))
        finally:
            del vms
        (backup_path, _) = self.loop.run_until_complete(
            self.backupvm.run_for_stdio("ls /var/tmp/backup*/qubes-backup*"))
        backup_path = backup_path.decode().strip()
        self.restore_backup(source=backup_path,
                            appvm=self.backupvm.name)
        self.assertCorrectlyRestored(vms_info, orig_hashes)


def create_testcases_for_templates():
    return qubes.tests.create_testcases_for_templates('TC_10_RestoreInDispVM',
        TC_00_RestoreInDispVM, qubes.tests.SystemTestCase,
        module=sys.modules[__name__])

def load_tests(loader, tests, pattern):
    tests.addTests(loader.loadTestsFromNames(
        create_testcases_for_templates()))
    return tests

qubes.tests.maybe_create_testcases_on_import(create_testcases_for_templates)
