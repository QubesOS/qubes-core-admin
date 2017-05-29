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

import hashlib
import logging
import multiprocessing

import os
import shutil

import sys
import qubes
import qubes.backup
import qubes.exc
import qubes.storage.lvm
import qubes.tests
import qubes.tests.storage_lvm
import qubes.vm
import qubes.vm.appvm
import qubes.vm.templatevm
import qubes.vm.qubesvm

# noinspection PyAttributeOutsideInit
class BackupTestsMixin(qubes.tests.SystemTestsMixin):
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
        backup_log = logging.getLogger('qubes.backup')
        backup_log.addHandler(self.error_handler)

    def tearDown(self):
        super(BackupTestsMixin, self).tearDown()
        shutil.rmtree(self.backupdir)

        backup_log = logging.getLogger('qubes.backup')
        backup_log.removeHandler(self.error_handler)

    def fill_image(self, path, size=None, sparse=False):
        block_size = 4096

        self.log.debug("Filling %s" % path)
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

    # NOTE: this was create_basic_vms
    def create_backup_vms(self, pool=None):
        template = self.app.default_template

        vms = []
        vmname = self.make_vm_name('test-net')
        self.log.debug("Creating %s" % vmname)
        testnet = self.app.add_new_vm(qubes.vm.appvm.AppVM,
            name=vmname, template=template, provides_network=True,
            label='red')
        testnet.create_on_disk(pool=pool)
        testnet.features['services/ntpd'] = True
        vms.append(testnet)
        self.fill_image(testnet.storage.export('private'), 20*1024*1024)

        vmname = self.make_vm_name('test1')
        self.log.debug("Creating %s" % vmname)
        testvm1 = self.app.add_new_vm(qubes.vm.appvm.AppVM,
            name=vmname, template=template, label='red')
        testvm1.uses_default_netvm = False
        testvm1.netvm = testnet
        testvm1.create_on_disk(pool=pool)
        vms.append(testvm1)
        self.fill_image(testvm1.storage.export('private'), 100 * 1024 * 1024)

        vmname = self.make_vm_name('testhvm1')
        self.log.debug("Creating %s" % vmname)
        testvm2 = self.app.add_new_vm(qubes.vm.standalonevm.StandaloneVM,
                                      name=vmname,
                                      hvm=True,
                                      label='red')
        testvm2.create_on_disk(pool=pool)
        self.fill_image(testvm2.storage.export('root'), 1024 * 1024 * 1024, \
            True)
        vms.append(testvm2)

        vmname = self.make_vm_name('template')
        self.log.debug("Creating %s" % vmname)
        testvm3 = self.app.add_new_vm(qubes.vm.templatevm.TemplateVM,
            name=vmname, label='red')
        testvm3.create_on_disk(pool=pool)
        self.fill_image(testvm3.storage.export('root'), 100 * 1024 * 1024, True)
        vms.append(testvm3)

        vmname = self.make_vm_name('custom')
        self.log.debug("Creating %s" % vmname)
        testvm4 = self.app.add_new_vm(qubes.vm.appvm.AppVM,
            name=vmname, template=testvm3, label='red')
        testvm4.create_on_disk(pool=pool)
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
            backup.backup_do()
        except qubes.exc.QubesException as e:
            if not expect_failure:
                self.fail("QubesException during backup_do: %s" % str(e))
            else:
                raise

        # FIXME why?
        #self.reload_db()

    def restore_backup(self, source=None, appvm=None, options=None,
                       expect_errors=None, manipulate_restore_info=None,
                       passphrase='qubes'):
        if source is None:
            backupfile = os.path.join(self.backupdir,
                                      sorted(os.listdir(self.backupdir))[-1])
        else:
            backupfile = source

        with self.assertNotRaises(qubes.exc.QubesException):
            restore_op = qubes.backup.BackupRestore(
                self.app, backupfile, appvm, passphrase)
            if options:
                for key, value in options.items():
                    setattr(restore_op.options, key, value)
            restore_info = restore_op.get_restore_info()
        if callable(manipulate_restore_info):
            restore_info = manipulate_restore_info(restore_info)
        self.log.debug(restore_op.get_restore_summary(restore_info))

        with self.assertNotRaises(qubes.exc.QubesException):
            restore_op.restore_do(restore_info)

        # maybe someone forgot to call .save()
        self.reload_db()

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
                vol_path = vm.storage.get_pool(volume).export(volume)
                hasher = hashlib.sha1()
                with open(vol_path, 'rb') as afile:
                    for buf in iter(lambda: afile.read(4096000), b''):
                        hasher.update(buf)
                hashes[vm.name][name] = hasher.hexdigest()
        return hashes

    def assertCorrectlyRestored(self, orig_vms, orig_hashes):
        ''' Verify if restored VMs are identical to those before backup.

        :param orig_vms: collection of original QubesVM objects
        :param orig_hashes: result of :py:meth:`vm_checksum` on original VMs,
            before backup
        :return:
        '''
        for vm in orig_vms:
            self.assertIn(vm.name, self.app.domains)
            restored_vm = self.app.domains[vm.name]
            for prop in ('name', 'kernel',
                    'memory', 'maxmem', 'kernelopts',
                    'services', 'vcpus', 'features'
                    'include_in_backups', 'default_user', 'qrexec_timeout',
                    'autostart', 'pci_strictreset', 'debug',
                    'internal'):
                if not hasattr(vm, prop):
                    continue
                self.assertEqual(
                    getattr(vm, prop), getattr(restored_vm, prop),
                    "VM {} - property {} not properly restored".format(
                        vm.name, prop))
            for prop in ('netvm', 'template', 'label'):
                if not hasattr(vm, prop):
                    continue
                orig_value = getattr(vm, prop)
                restored_value = getattr(restored_vm, prop)
                if orig_value and restored_value:
                    self.assertEqual(orig_value.name, restored_value.name,
                        "VM {} - property {} not properly restored".format(
                            vm.name, prop))
                else:
                    self.assertEqual(orig_value, restored_value,
                        "VM {} - property {} not properly restored".format(
                            vm.name, prop))
            for dev_class in vm.devices.keys():
                for dev in vm.devices[dev_class]:
                    self.assertIn(dev, restored_vm.devices[dev_class],
                        "VM {} - {} device not restored".format(
                            vm.name, dev_class))

            if orig_hashes:
                hashes = self.vm_checksum([restored_vm])[restored_vm.name]
                self.assertEqual(orig_hashes[vm.name], hashes,
                    "VM {} - disk images are not properly restored".format(
                        vm.name))


class TC_00_Backup(BackupTestsMixin, qubes.tests.QubesTestCase):
    def test_000_basic_backup(self):
        vms = self.create_backup_vms()
        orig_hashes = self.vm_checksum(vms)
        self.make_backup(vms)
        self.remove_vms(reversed(vms))
        self.restore_backup()
        self.assertCorrectlyRestored(vms, orig_hashes)
        self.remove_vms(reversed(vms))

    def test_001_compressed_backup(self):
        vms = self.create_backup_vms()
        orig_hashes = self.vm_checksum(vms)
        self.make_backup(vms, compressed=True)
        self.remove_vms(reversed(vms))
        self.restore_backup()
        self.assertCorrectlyRestored(vms, orig_hashes)

    def test_002_encrypted_backup(self):
        vms = self.create_backup_vms()
        orig_hashes = self.vm_checksum(vms)
        self.make_backup(vms, encrypted=True)
        self.remove_vms(reversed(vms))
        self.restore_backup()
        self.assertCorrectlyRestored(vms, orig_hashes)

    def test_003_compressed_encrypted_backup(self):
        vms = self.create_backup_vms()
        orig_hashes = self.vm_checksum(vms)
        self.make_backup(vms, compressed=True, encrypted=True)
        self.remove_vms(reversed(vms))
        self.restore_backup()
        self.assertCorrectlyRestored(vms, orig_hashes)

    def test_004_sparse_multipart(self):
        vms = []

        vmname = self.make_vm_name('testhvm2')
        self.log.debug("Creating %s" % vmname)

        hvmtemplate = self.app.add_new_vm(
            qubes.vm.templatevm.TemplateVM, name=vmname, hvm=True, label='red')
        hvmtemplate.create_on_disk()
        self.fill_image(
            os.path.join(hvmtemplate.dir_path, '00file'),
            195 * 1024 * 1024 - 4096 * 3)
        self.fill_image(hvmtemplate.storage.export('private'),
                        195 * 1024 * 1024 - 4096 * 3)
        self.fill_image(hvmtemplate.storage.export('root'), 1024 * 1024 * 1024,
                        sparse=True)
        vms.append(hvmtemplate)
        self.app.save()
        orig_hashes = self.vm_checksum(vms)

        self.make_backup(vms)
        self.remove_vms(reversed(vms))
        self.restore_backup()
        self.assertCorrectlyRestored(vms, orig_hashes)
        # TODO check vm.backup_timestamp

    def test_005_compressed_custom(self):
        vms = self.create_backup_vms()
        orig_hashes = self.vm_checksum(vms)
        self.make_backup(vms, compression_filter="bzip2")
        self.remove_vms(reversed(vms))
        self.restore_backup()
        self.assertCorrectlyRestored(vms, orig_hashes)

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
        orig_hashes = self.vm_checksum(vms)
        self.make_backup(vms, compression_filter="bzip2")
        self.remove_vms(reversed(vms))
        self.restore_backup(manipulate_restore_info=exclude_some)
        for vm in vms:
            if vm.name == self.make_vm_name('test1'):
                # netvm was set to 'test-inst-test-net' - excluded
                vm.netvm = qubes.property.DEFAULT
            elif vm.name == self.make_vm_name('custom'):
                # template was set to 'test-inst-template' - excluded
                vm.template = self.app.default_template
        vms = [vm for vm in vms if vm.name not in exclude]
        self.assertCorrectlyRestored(vms, orig_hashes)

    def test_020_encrypted_backup_non_ascii(self):
        vms = self.create_backup_vms()
        orig_hashes = self.vm_checksum(vms)
        self.make_backup(vms, encrypted=True, passphrase=u'zażółć gęślą jaźń')
        self.remove_vms(reversed(vms))
        self.restore_backup(passphrase=u'zażółć gęślą jaźń')
        self.assertCorrectlyRestored(vms, orig_hashes)

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
        orig_hashes = self.vm_checksum(vms)
        self.make_backup(vms)
        self.remove_vms(reversed(vms))
        test_dir = vms[0].dir_path
        os.mkdir(test_dir)
        with open(os.path.join(test_dir, 'some-file.txt'), 'w') as f:
            f.write('test file\n')
        self.restore_backup(
            expect_errors=[
                '*** Directory {} already exists! It has been moved'.format(
                    test_dir)
            ])
        self.assertCorrectlyRestored(vms, orig_hashes)

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
            self.pool = self.app.add_pool(
                **qubes.tests.storage_lvm.POOL_CONF)
            self.created_pool = True
        vms = self.create_backup_vms(pool=self.pool)
        orig_hashes = self.vm_checksum(vms)
        self.make_backup(vms)
        self.remove_vms(reversed(vms))
        self.restore_backup()
        self.assertCorrectlyRestored(vms, orig_hashes)
        self.remove_vms(reversed(vms))

    @qubes.tests.storage_lvm.skipUnlessLvmPoolExists
    def test_301_restore_to_lvm(self):
        volume_group, thin_pool = \
            qubes.tests.storage_lvm.DEFAULT_LVM_POOL.split('/', 1)
        self.pool = self._find_pool(volume_group, thin_pool)
        if not self.pool:
            self.pool = self.app.add_pool(
                **qubes.tests.storage_lvm.POOL_CONF)
            self.created_pool = True
        vms = self.create_backup_vms()
        orig_hashes = self.vm_checksum(vms)
        self.make_backup(vms)
        self.remove_vms(reversed(vms))
        self.restore_backup(options={'override_pool': self.pool.name})
        self.assertCorrectlyRestored(vms, orig_hashes)
        for vm in vms:
            vm = self.app.domains[vm.name]
            for volume in vm.volumes.values():
                if volume.save_on_stop:
                    self.assertEqual(volume.pool, self.pool.name)
        self.remove_vms(reversed(vms))


class TC_10_BackupVMMixin(BackupTestsMixin):
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
        self.loop.run_until_complete(self.backupvm.run_for_stdio(
            "mkdir '/var/tmp/backup directory'"))
        self.make_backup(vms, target_vm=self.backupvm,
            compressed=True, encrypted=True,
            target='/var/tmp/backup directory')
        self.remove_vms(reversed(vms))
        (backup_path, _) = self.loop.run_until_complete(
            self.backupvm.run_for_stdio("ls /var/tmp/backup*/qubes-backup*"))
        backup_path = backup_path.decode().strip()
        self.restore_backup(source=backup_path,
                            appvm=self.backupvm)

    def test_110_send_to_vm_command(self):
        vms = self.create_backup_vms()
        self.backupvm.start()
        self.make_backup(vms, target_vm=self.backupvm,
            compressed=True, encrypted=True,
            target='dd of=/var/tmp/backup-test')
        self.remove_vms(reversed(vms))
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
