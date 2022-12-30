#
# The Qubes OS Project, https://www.qubes-os.org/
#
# Copyright (C) 2014-2015
#                   Marek Marczykowski-Górecki <marmarek@invisiblethingslab.com>
# Copyright (C) 2015  Wojtek Porczyk <woju@invisiblethingslab.com>
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

import qubes
import qubes.backup
import qubes.exc
import qubes.storage.lvm
import qubes.tests
import qubes.tests.storage_lvm
import qubes.utils
import qubes.vm
import qubes.vm.appvm
import qubes.vm.templatevm
import qubes.vm.qubesvm

try:
    import qubesadmin.backup.restore
    import qubesadmin.exc
    restore_available = True
except ImportError:
    restore_available = False


# noinspection PyAttributeOutsideInit
class BackupTestsMixin(object):
    class BackupErrorHandler(logging.Handler):
        def __init__(self, errors_queue, level=logging.NOTSET):
            super(BackupTestsMixin.BackupErrorHandler, self).__init__(level)
            self.errors_queue = errors_queue

        def emit(self, record):
            self.errors_queue.put(record.getMessage())

    def setUp(self):
        super(BackupTestsMixin, self).setUp()
        try:
            self.init_default_template(self.template)
        except AttributeError:
            self.init_default_template()
        self.error_detected = multiprocessing.Queue()

        self.log.debug("Creating backupvm")

        self.backupdir = os.path.join(os.environ["HOME"], "test-backup")
        if os.path.exists(self.backupdir):
            shutil.rmtree(self.backupdir)
        os.mkdir(self.backupdir)

        self.error_handler = self.BackupErrorHandler(self.error_detected,
            level=logging.WARNING)
        backup_log = logging.getLogger('qubesadmin.backup')
        backup_log.addHandler(self.error_handler)

    def tearDown(self):
        shutil.rmtree(self.backupdir)

        backup_log = logging.getLogger('qubes.backup')
        backup_log.removeHandler(self.error_handler)
        super(BackupTestsMixin, self).tearDown()

    def fill_image(self, path, size=None, sparse=False):
        block_size = 4096

        self.log.debug("Filling %s" % path)
        try:
            f = open(path, 'rb+')
        except FileNotFoundError:
            f = open(path, 'wb+')
        if size is None:
            f.seek(0, 2)
            size = f.tell()
        f.seek(0)

        for block_num in range(int(size/block_size)):
            if sparse:
                f.seek(block_size, 1)
            f.write(b'a' * block_size)

        f.close()

    def fill_image_vm(self, vm, volume, size=None, sparse=False):
        path = self.loop.run_until_complete(vm.storage.export(volume))
        try:
            self.fill_image(path, size=size, sparse=sparse)
        finally:
            self.loop.run_until_complete(vm.storage.export_end(volume, path))

    # NOTE: this was create_basic_vms
    def create_backup_vms(self, pool=None):
        template = self.app.default_template

        vms = []
        vmname = self.make_vm_name('test-net')
        self.log.debug("Creating %s" % vmname)
        testnet = self.app.add_new_vm(qubes.vm.appvm.AppVM,
            name=vmname, template=template, provides_network=True,
            label='red')
        self.loop.run_until_complete(
            testnet.create_on_disk(pool=pool))
        testnet.features['service.ntpd'] = True
        vms.append(testnet)
        self.fill_image_vm(testnet, 'private', 20*1024*1024)

        vmname = self.make_vm_name('test1')
        self.log.debug("Creating %s" % vmname)
        testvm1 = self.app.add_new_vm(qubes.vm.appvm.AppVM,
            name=vmname, template=template, label='red')
        testvm1.netvm = testnet
        self.loop.run_until_complete(
            testvm1.create_on_disk(pool=pool))
        vms.append(testvm1)
        self.fill_image_vm(testvm1, 'private', 100 * 1024 * 1024)

        vmname = self.make_vm_name('testhvm1')
        self.log.debug("Creating %s" % vmname)
        testvm2 = self.app.add_new_vm(qubes.vm.standalonevm.StandaloneVM,
                                      name=vmname,
                                      virt_mode='hvm',
                                      label='red')
        self.loop.run_until_complete(
            testvm2.create_on_disk(pool=pool))
        self.fill_image_vm(testvm2, 'root', 1024 * 1024 * 1024, True)
        vms.append(testvm2)

        vmname = self.make_vm_name('template')
        self.log.debug("Creating %s" % vmname)
        testvm3 = self.app.add_new_vm(qubes.vm.templatevm.TemplateVM,
            name=vmname, label='red')
        self.loop.run_until_complete(
            testvm3.create_on_disk(pool=pool))
        self.fill_image_vm(testvm3, 'root', 100 * 1024 * 1024, True)
        vms.append(testvm3)

        vmname = self.make_vm_name('custom')
        self.log.debug("Creating %s" % vmname)
        testvm4 = self.app.add_new_vm(qubes.vm.appvm.AppVM,
            name=vmname, template=testvm3, label='red')
        self.loop.run_until_complete(
            testvm4.create_on_disk(pool=pool))
        vms.append(testvm4)

        self.app.save()

        return vms

    def make_backup(self, vms, target=None, expect_failure=False, **kwargs):
        if target is None:
            target = self.backupdir
        try:
            backup = qubes.backup.Backup(self.app, vms, **kwargs)
        except qubes.exc.QubesException as e:
            if not expect_failure:
                self.fail("QubesException during backup_prepare: %s" % str(e))
            else:
                raise

        if 'passphrase' not in kwargs:
            backup.passphrase = 'qubes'
        backup.target_dir = target

        try:
            self.loop.run_until_complete(backup.backup_do())
        except qubes.exc.QubesException as e:
            if not expect_failure:
                self.fail("QubesException during backup_do: %s" % str(e))
            else:
                raise

    def remove_vms(self, vms):
        vms = list(vms)
        for vm in vms:
            vm.netvm = None
            vm.default_dispvm = None
        super(BackupTestsMixin, self).remove_vms(vms)

    def restore_backup(self, source=None, appvm=None, options=None,
                       expect_errors=None, manipulate_restore_info=None,
                       passphrase='qubes'):
        if not restore_available:
            self.skipTest('qubesadmin module not available')

        if source is None:
            backupfile = os.path.join(self.backupdir,
                                      sorted(os.listdir(self.backupdir))[-1])
        else:
            backupfile = source

        client_app = qubesadmin.Qubes()
        if appvm:
            appvm = self.loop.run_until_complete(
                self.loop.run_in_executor(None,
                    client_app.domains.__getitem__, appvm.name))
        with self.assertNotRaises(qubesadmin.exc.QubesException):
            restore_op = self.loop.run_until_complete(
                self.loop.run_in_executor(None,
                    qubesadmin.backup.restore.BackupRestore,
                    client_app, backupfile, appvm, passphrase))
            if options:
                for key, value in options.items():
                    setattr(restore_op.options, key, value)
            restore_info = self.loop.run_until_complete(
                self.loop.run_in_executor(None,
                    restore_op.get_restore_info))
        if callable(manipulate_restore_info):
            restore_info = manipulate_restore_info(restore_info)
        self.log.debug(restore_op.get_restore_summary(restore_info))

        with self.assertNotRaises(qubesadmin.exc.QubesException):
            self.loop.run_until_complete(
                self.loop.run_in_executor(None,
                    restore_op.restore_do, restore_info))

        errors = []
        if expect_errors is None:
            expect_errors = []
        else:
            self.assertFalse(self.error_detected.empty(),
                "Restore errors expected, but none detected")
        while not self.error_detected.empty():
            current_error = self.error_detected.get()
            if any(map(current_error.startswith, expect_errors)):
                continue
            errors.append(current_error)
        self.assertTrue(len(errors) == 0,
                         "Error(s) detected during backup_restore_do: %s" %
                         '\n'.join(errors))
        if not appvm and not os.path.isdir(backupfile):
            os.unlink(backupfile)

    def create_sparse(self, path, size):
        f = open(path, "w")
        f.truncate(size)
        f.close()

    def vm_checksum(self, vms):
        hashes = {}
        for vm in vms:
            assert isinstance(vm, qubes.vm.qubesvm.QubesVM)
            hashes[vm.name] = {}
            for name, volume in vm.volumes.items():
                if not volume.rw or not volume.save_on_stop:
                    continue
                vol_path = self.loop.run_until_complete(
                    qubes.utils.coro_maybe(volume.export()))
                hasher = hashlib.sha1()
                with open(vol_path, 'rb') as afile:
                    for buf in iter(lambda: afile.read(4096000), b''):
                        hasher.update(buf)
                self.loop.run_until_complete(
                    qubes.utils.coro_maybe(volume.export_end(vol_path)))
                hashes[vm.name][name] = hasher.hexdigest()
        return hashes

    def get_vms_info(self, vms):
        ''' Get VM metadata, for comparing VM later without holding actual
        reference to the old object.'''

        vms_info = {}
        for vm in vms:
            vm_info = {
                'properties': {},
                'default': {},
                'devices': {},
            }
            for prop in ('name', 'kernel',
                    'memory', 'maxmem', 'kernelopts',
                    'services', 'vcpus', 'features'
                    'include_in_backups', 'default_user', 'qrexec_timeout',
                    'autostart', 'pci_strictreset', 'debug',
                    'internal', 'netvm', 'template', 'label'):
                if not hasattr(vm, prop):
                    continue
                vm_info['properties'][prop] = str(getattr(vm, prop))
                vm_info['default'][prop] = vm.property_is_default(prop)
            for dev_class in vm.devices.keys():
                vm_info['devices'][dev_class] = {}
                for dev_ass in vm.devices[dev_class].assignments():
                    vm_info['devices'][dev_class][str(dev_ass.device)] = \
                        dev_ass.options
            vms_info[vm.name] = vm_info

        return vms_info

    def assertCorrectlyRestored(self, vms_info, orig_hashes):
        ''' Verify if restored VMs are identical to those before backup.

        :param orig_vms: collection of original QubesVM objects
        :param orig_hashes: result of :py:meth:`vm_checksum` on original VMs,
            before backup
        :return:
        '''
        for vm_name in vms_info:
            vm_info = vms_info[vm_name]
            self.assertIn(vm_name, self.app.domains)
            restored_vm = self.app.domains[vm_name]
            for prop in vm_info['properties']:
                self.assertEqual(
                    vm_info['default'][prop],
                    restored_vm.property_is_default(prop),
                    "VM {} - property {} differs in being default".format(
                        vm_name, prop))
                if not vm_info['default'][prop]:
                    self.assertEqual(
                        vm_info['properties'][prop],
                        str(getattr(restored_vm, prop)),
                        "VM {} - property {} not properly restored".format(
                            vm_name, prop))
            for dev_class in vm_info['devices']:
                for dev in vm_info['devices'][dev_class]:
                    found = False
                    for restored_dev_ass in restored_vm.devices[
                            dev_class].assignments():
                        if str(restored_dev_ass.device) == dev:
                            found = True
                            self.assertEqual(vm_info['devices'][dev_class][dev],
                                restored_dev_ass.options,
                                'VM {} - {} device {} options mismatch'.format(
                                    vm_name, dev_class, str(dev)))
                    self.assertTrue(found,
                        'VM {} - {} device {} not restored'.format(
                            vm_name, dev_class, dev))

            if orig_hashes:
                hashes = self.vm_checksum([restored_vm])[restored_vm.name]
                self.assertEqual(orig_hashes[vm_name], hashes,
                    "VM {} - disk images are not properly restored".format(
                        vm_name))


class TC_00_Backup(BackupTestsMixin, qubes.tests.SystemTestCase):
    def test_000_basic_backup(self):
        vms = self.create_backup_vms()
        try:
            orig_hashes = self.vm_checksum(vms)
            vms_info = self.get_vms_info(vms)
            self.make_backup(vms)
            self.remove_vms(reversed(vms))
        finally:
            del vms
        self.restore_backup()
        self.assertCorrectlyRestored(vms_info, orig_hashes)

    def test_001_compressed_backup(self):
        vms = self.create_backup_vms()
        try:
            orig_hashes = self.vm_checksum(vms)
            vms_info = self.get_vms_info(vms)
            self.make_backup(vms, compressed=True)
            self.remove_vms(reversed(vms))
        finally:
            del vms
        self.restore_backup()
        self.assertCorrectlyRestored(vms_info, orig_hashes)

    def test_004_sparse_multipart(self):
        vms = []
        try:
            vmname = self.make_vm_name('testhvm2')
            self.log.debug("Creating %s" % vmname)

            self.hvmtemplate = self.app.add_new_vm(
                qubes.vm.templatevm.TemplateVM, name=vmname, virt_mode='hvm', label='red')
            self.loop.run_until_complete(self.hvmtemplate.create_on_disk())
            self.fill_image(
                os.path.join(self.hvmtemplate.dir_path, '00file'),
                195 * 1024 * 1024 - 4096 * 3)
            self.fill_image_vm(self.hvmtemplate, 'private',
                            195 * 1024 * 1024 - 4096 * 3)
            self.fill_image_vm(self.hvmtemplate, 'root', 1024 * 1024 * 1024,
                            sparse=True)
            vms.append(self.hvmtemplate)
            self.app.save()
            orig_hashes = self.vm_checksum(vms)
            vms_info = self.get_vms_info(vms)

            self.make_backup(vms)
            self.remove_vms(reversed(vms))
            self.restore_backup()
            self.assertCorrectlyRestored(vms_info, orig_hashes)
            # TODO check vm.backup_timestamp
        finally:
            del vms

    def test_005_compressed_custom(self):
        vms = self.create_backup_vms()
        try:
            orig_hashes = self.vm_checksum(vms)
            vms_info = self.get_vms_info(vms)
            self.make_backup(vms, compression_filter="bzip2")
            self.remove_vms(reversed(vms))
            self.restore_backup()
            self.assertCorrectlyRestored(vms_info, orig_hashes)
        finally:
            del vms

    def test_010_selective_restore(self):
        # create backup with internal dependencies (template, netvm etc)
        # try restoring only AppVMs (but not templates, netvms) - should
        # handle according to options set
        exclude = [
            self.make_vm_name('test-net'),
            self.make_vm_name('template')
        ]
        def exclude_some(restore_info):
            for name in exclude:
                restore_info.pop(name)
            return restore_info
        vms = self.create_backup_vms()
        try:
            orig_hashes = self.vm_checksum(vms)
            vms_info = self.get_vms_info(vms)
            self.make_backup(vms, compression_filter="bzip2")
            self.remove_vms(reversed(vms))
            self.restore_backup(manipulate_restore_info=exclude_some)
            for vm_name in vms_info:
                if vm_name == self.make_vm_name('test1'):
                    # netvm was set to 'test-inst-test-net' - excluded
                    vms_info[vm_name]['properties']['netvm'] = \
                        str(self.app.default_netvm)
                    vms_info[vm_name]['default']['netvm'] = True
                elif vm_name == self.make_vm_name('custom'):
                    # template was set to 'test-inst-template' - excluded
                    vms_info[vm_name]['properties']['template'] = \
                        str(self.app.default_template)
            for excluded in exclude:
                vms_info.pop(excluded, None)
            self.assertCorrectlyRestored(vms_info, orig_hashes)
        finally:
            del vms

    def test_020_encrypted_backup_non_ascii(self):
        vms = self.create_backup_vms()
        try:
            orig_hashes = self.vm_checksum(vms)
            vms_info = self.get_vms_info(vms)
            self.make_backup(vms, passphrase=u'zażółć gęślą jaźń')
            self.remove_vms(reversed(vms))
            self.restore_backup(passphrase=u'zażółć gęślą jaźń')
            self.assertCorrectlyRestored(vms_info, orig_hashes)
        finally:
            del vms

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
        try:
            orig_hashes = self.vm_checksum(vms)
            vms_info = self.get_vms_info(vms)
            self.make_backup(vms)
            test_dir = vms[0].dir_path
            self.remove_vms(reversed(vms))
            os.mkdir(test_dir)
            with open(os.path.join(test_dir, 'some-file.txt'), 'w') as f:
                f.write('test file\n')
            self.restore_backup()
            self.assertCorrectlyRestored(vms_info, orig_hashes)
        finally:
            del vms

    def test_210_auto_rename(self):
        """
        Test for #869
        :return:
        """
        vms = self.create_backup_vms()
        vms_info = self.get_vms_info(vms)
        try:
            self.make_backup(vms)
            self.restore_backup(options={
                'rename_conflicting': True
            })
            for vm_name in vms_info:
                with self.assertNotRaises(
                        (qubes.exc.QubesVMNotFoundError, KeyError)):
                    restored_vm = self.app.domains[vm_name + '1']
                if vms_info[vm_name]['properties']['netvm'] and \
                        not vms_info[vm_name]['default']['netvm']:
                    self.assertEqual(restored_vm.netvm.name,
                        vms_info[vm_name]['properties']['netvm'] + '1')
        finally:
            del vms

    def _find_pool(self, volume_group, thin_pool):
        ''' Returns the pool matching the specified ``volume_group`` &
            ``thin_pool``, or None.
        '''
        pools = [p for p in self.app.pools
                 if issubclass(p.__class__, qubes.storage.lvm.ThinPool)]
        for pool in pools:
            if pool.volume_group == volume_group \
                    and pool.thin_pool == thin_pool:
                return pool
        return None

    @qubes.tests.storage_lvm.skipUnlessLvmPoolExists
    def test_300_backup_lvm(self):
        volume_group, thin_pool = \
            qubes.tests.storage_lvm.DEFAULT_LVM_POOL.split('/', 1)
        self.pool = self._find_pool(volume_group, thin_pool)
        if not self.pool:
            self.pool = self.loop.run_until_complete(
                self.app.add_pool(
                    **qubes.tests.storage_lvm.POOL_CONF))
            self.created_pool = True
        vms = self.create_backup_vms(pool=self.pool)
        try:
            orig_hashes = self.vm_checksum(vms)
            vms_info = self.get_vms_info(vms)
            self.make_backup(vms)
            self.remove_vms(reversed(vms))
            self.restore_backup()
            self.assertCorrectlyRestored(vms_info, orig_hashes)
        finally:
            del vms

    @qubes.tests.storage_lvm.skipUnlessLvmPoolExists
    def test_301_restore_to_lvm(self):
        volume_group, thin_pool = \
            qubes.tests.storage_lvm.DEFAULT_LVM_POOL.split('/', 1)
        self.pool = self._find_pool(volume_group, thin_pool)
        if not self.pool:
            self.pool = self.loop.run_until_complete(
                self.app.add_pool(
                    **qubes.tests.storage_lvm.POOL_CONF))
            self.created_pool = True
        vms = self.create_backup_vms()
        try:
            orig_hashes = self.vm_checksum(vms)
            vms_info = self.get_vms_info(vms)
            self.make_backup(vms)
            self.remove_vms(reversed(vms))
            self.restore_backup(options={'override_pool': self.pool.name})
            self.assertCorrectlyRestored(vms_info, orig_hashes)
            for vm_name in vms_info:
                vm = self.app.domains[vm_name]
                for volume in vm.volumes.values():
                    if volume.save_on_stop:
                        self.assertEqual(volume.pool, self.pool.name)
        finally:
            del vms


class TC_10_BackupVMMixin(BackupTestsMixin):
    def setUp(self):
        super(TC_10_BackupVMMixin, self).setUp()
        self.backupvm = self.app.add_new_vm(
            qubes.vm.appvm.AppVM,
            label='red',
            name=self.make_vm_name('backupvm'),
            template=self.template
        )
        self.loop.run_until_complete(self.backupvm.create_on_disk())

    def test_100_send_to_vm_file_with_spaces(self):
        vms = self.create_backup_vms()
        orig_hashes = self.vm_checksum(vms)
        vms_info = self.get_vms_info(vms)
        try:
            self.loop.run_until_complete(self.backupvm.start())
            self.loop.run_until_complete(self.backupvm.run_for_stdio(
                "mkdir '/var/tmp/backup directory'"))
            self.make_backup(vms, target_vm=self.backupvm,
                compressed=True,
                target='/var/tmp/backup directory')
            self.remove_vms(reversed(vms))
            (backup_path, _) = self.loop.run_until_complete(
                self.backupvm.run_for_stdio("ls /var/tmp/backup*/qubes-backup*"))
            backup_path = backup_path.decode().strip()
            self.restore_backup(source=backup_path,
                                appvm=self.backupvm)
            self.assertCorrectlyRestored(vms_info, orig_hashes)
        finally:
            del vms

    def test_110_send_to_vm_command(self):
        vms = self.create_backup_vms()
        orig_hashes = self.vm_checksum(vms)
        vms_info = self.get_vms_info(vms)
        try:
            self.loop.run_until_complete(self.backupvm.start())
            self.make_backup(vms, target_vm=self.backupvm,
                compressed=True,
                target='dd of=/var/tmp/backup-test')
            self.remove_vms(reversed(vms))
            self.restore_backup(source='dd if=/var/tmp/backup-test',
                                appvm=self.backupvm)
            self.assertCorrectlyRestored(vms_info, orig_hashes)
        finally:
            del vms

    def test_110_send_to_vm_no_space(self):
        """
        Check whether backup properly report failure when no enough space is
        available
        :return:
        """
        vms = self.create_backup_vms()
        try:
            self.loop.run_until_complete(self.backupvm.start())
            self.loop.run_until_complete(self.backupvm.run_for_stdio(
                # Debian 7 has too old losetup to handle loop-control device
                "mknod /dev/loop0 b 7 0;"
                "truncate -s 50M /home/user/backup.img && "
                "mkfs.ext4 -F /home/user/backup.img && "
                "mkdir /home/user/backup && "
                "mount /home/user/backup.img /home/user/backup -o loop &&"
                "chmod 777 /home/user/backup",
                user="root"))
            with self.assertRaises(qubes.exc.QubesException):
                self.make_backup(vms, target_vm=self.backupvm,
                    compressed=False,
                    target='/home/user/backup',
                    expect_failure=True)
        finally:
            del vms


def create_testcases_for_templates():
    return qubes.tests.create_testcases_for_templates('TC_10_BackupVM',
        TC_10_BackupVMMixin, qubes.tests.SystemTestCase,
        module=sys.modules[__name__])

def load_tests(loader, tests, pattern):
    tests.addTests(loader.loadTestsFromNames(
        create_testcases_for_templates()))
    return tests

qubes.tests.maybe_create_testcases_on_import(create_testcases_for_templates)
