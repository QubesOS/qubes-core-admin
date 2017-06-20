# vim: fileencoding=utf-8
#
# The Qubes OS Project, https://www.qubes-os.org/
#
# Copyright (C) 2016
#                   Marek Marczykowski-Górecki <marmarek@invisiblethingslab.com>
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

import qubes.tests
import qubes.qubesutils
import subprocess

# the same class for both dom0 and VMs
class TC_00_List(qubes.tests.SystemTestsMixin, qubes.tests.QubesTestCase):
    template = None

    def setUp(self):
        super(TC_00_List, self).setUp()
        self.img_path = '/tmp/test.img'
        self.mount_point = '/tmp/test-dir'
        if self.template is not None:
            self.vm = self.qc.add_new_vm(
                "QubesAppVm",
                name=self.make_vm_name("vm"),
                template=self.qc.get_vm_by_name(self.template))
            self.vm.create_on_disk(verbose=False)
            self.app.save()
            self.qc.unlock_db()
            self.vm.start()
        else:
            self.qc.unlock_db()
            self.vm = self.qc[0]

    def tearDown(self):
        super(TC_00_List, self).tearDown()
        if self.template is None:
            if os.path.exists(self.mount_point):
                subprocess.call(['sudo', 'umount', self.mount_point])
                subprocess.call(['sudo', 'rmdir', self.mount_point])
            subprocess.call(['sudo', 'dmsetup', 'remove', 'test-dm'])
            if os.path.exists(self.img_path):
                loopdev = subprocess.check_output(['losetup', '-j',
                    self.img_path])
                for dev in loopdev.splitlines():
                    subprocess.call(
                        ['sudo', 'losetup', '-d', dev.split(':')[0]])
                subprocess.call(['sudo', 'rm', '-f', self.img_path])

    def run_script(self, script, user="user"):
        if self.template is None:
            if user == "user":
                subprocess.check_call(script, shell=True)
            elif user == "root":
                subprocess.check_call(['sudo', 'sh', '-c', script])
        else:
            retcode = self.vm.run(script, user=user, wait=True)
            if retcode != 0:
                raise subprocess.CalledProcessError

    def test_000_list_loop(self):
        if self.template is None:
            self.skipTest('loop devices excluded in dom0')
        self.run_script(
            "set -e;"
            "truncate -s 128M {path}; "
            "losetup -f {path}; "
            "udevadm settle".format(path=self.img_path), user="root")

        dev_list = qubes.qubesutils.block_list_vm(self.vm)
        found = False
        for dev in dev_list.keys():
            if dev_list[dev]['desc'] == self.img_path:
                self.assertTrue(dev.startswith(self.vm.name + ':loop'))
                self.assertEquals(dev_list[dev]['mode'], 'w')
                self.assertEquals(dev_list[dev]['size'], 1024 * 1024 * 128)
                self.assertEquals(
                    dev_list[dev]['device'], '/dev/' + dev.split(':')[1])
                found = True

        if not found:
            self.fail("Device {} not found in {!r}".format(self.img_path, dev_list))

    def test_001_list_loop_mounted(self):
        if self.template is None:
            self.skipTest('loop devices excluded in dom0')
        self.run_script(
            "set -e;"
            "truncate -s 128M {path}; "
            "mkfs.ext4 -q -F {path}; "
            "mkdir -p {mntdir}; "
            "mount {path} {mntdir} -o loop; "
            "udevadm settle".format(
                path=self.img_path,
                mntdir=self.mount_point),
            user="root")

        dev_list = qubes.qubesutils.block_list_vm(self.vm)
        for dev in dev_list.keys():
            if dev_list[dev]['desc'] == self.img_path:
                self.fail(
                    'Device {} ({}) should not be listed because is mounted'
                    .format(dev, self.img_path))

    def test_010_list_dm(self):
        self.run_script(
            "set -e;"
            "truncate -s 128M {path}; "
            "loopdev=`losetup -f`; "
            "losetup $loopdev {path}; "
            "dmsetup create test-dm --table \"0 262144 linear $(cat "
            "/sys/block/$(basename $loopdev)/dev) 0\";"
            "udevadm settle".format(path=self.img_path), user="root")

        dev_list = qubes.qubesutils.block_list_vm(self.vm)
        found = False
        for dev in dev_list.keys():
            if dev.startswith(self.vm.name + ':loop'):
                self.assertNotEquals(dev_list[dev]['desc'], self.img_path,
                    "Device {} ({}) should not be listed as it is used in "
                    "device-mapper".format(dev, self.img_path)
                )
            elif dev_list[dev]['desc'] == 'test-dm':
                self.assertEquals(dev_list[dev]['mode'], 'w')
                self.assertEquals(dev_list[dev]['size'], 1024 * 1024 * 128)
                self.assertEquals(
                    dev_list[dev]['device'], '/dev/' + dev.split(':')[1])
                found = True

        if not found:
            self.fail("Device {} not found in {!r}".format('test-dm', dev_list))

    def test_011_list_dm_mounted(self):
        self.run_script(
            "set -e;"
            "truncate -s 128M {path}; "
            "loopdev=`losetup -f`; "
            "losetup $loopdev {path}; "
            "dmsetup create test-dm --table \"0 262144 linear $(cat "
            "/sys/block/$(basename $loopdev)/dev) 0\";"
            "mkfs.ext4 -q -F /dev/mapper/test-dm;"
            "mkdir -p {mntdir};"
            "mount /dev/mapper/test-dm {mntdir};"
            "udevadm settle".format(
                path=self.img_path,
                mntdir=self.mount_point),
            user="root")

        dev_list = qubes.qubesutils.block_list_vm(self.vm)
        for dev in dev_list.keys():
            if dev.startswith(self.vm.name + ':loop'):
                self.assertNotEquals(dev_list[dev]['desc'], self.img_path,
                    "Device {} ({}) should not be listed as it is used in "
                    "device-mapper".format(dev, self.img_path)
                )
            else:
                self.assertNotEquals(dev_list[dev]['desc'], 'test-dm',
                    "Device {} ({}) should not be listed as it is "
                    "mounted".format(dev, 'test-dm')
                )

    def test_012_list_dm_delayed(self):
        self.run_script(
            "set -e;"
            "truncate -s 128M {path}; "
            "loopdev=`losetup -f`; "
            "losetup $loopdev {path}; "
            "udevadm settle; "
            "dmsetup create test-dm --table \"0 262144 linear $(cat "
            "/sys/block/$(basename $loopdev)/dev) 0\";"
            "udevadm settle".format(path=self.img_path), user="root")

        dev_list = qubes.qubesutils.block_list_vm(self.vm)
        found = False
        for dev in dev_list.keys():
            if dev.startswith(self.vm.name + ':loop'):
                self.assertNotEquals(dev_list[dev]['desc'], self.img_path,
                    "Device {} ({}) should not be listed as it is used in "
                    "device-mapper".format(dev, self.img_path)
                )
            elif dev_list[dev]['desc'] == 'test-dm':
                self.assertEquals(dev_list[dev]['mode'], 'w')
                self.assertEquals(dev_list[dev]['size'], 1024 * 1024 * 128)
                self.assertEquals(
                    dev_list[dev]['device'], '/dev/' + dev.split(':')[1])
                found = True

        if not found:
            self.fail("Device {} not found in {!r}".format('test-dm', dev_list))

    def test_013_list_dm_removed(self):
        if self.template is None:
            self.skipTest('test not supported in dom0 - loop devices excluded '
                          'in dom0')
        self.run_script(
            "set -e;"
            "truncate -s 128M {path}; "
            "loopdev=`losetup -f`; "
            "losetup $loopdev {path}; "
            "dmsetup create test-dm --table \"0 262144 linear $(cat "
            "/sys/block/$(basename $loopdev)/dev) 0\";"
            "udevadm settle;"
            "dmsetup remove test-dm;"
            "udevadm settle".format(path=self.img_path), user="root")

        dev_list = qubes.qubesutils.block_list_vm(self.vm)
        found = False
        for dev in dev_list.keys():
            if dev_list[dev]['desc'] == self.img_path:
                self.assertTrue(dev.startswith(self.vm.name + ':loop'))
                self.assertEquals(dev_list[dev]['mode'], 'w')
                self.assertEquals(dev_list[dev]['size'], 1024 * 1024 * 128)
                self.assertEquals(
                    dev_list[dev]['device'], '/dev/' + dev.split(':')[1])
                found = True

        if not found:
            self.fail("Device {} not found in {!r}".format(self.img_path, dev_list))

    def test_020_list_loop_partition(self):
        if self.template is None:
            self.skipTest('loop devices excluded in dom0')
        self.run_script(
            "set -e;"
            "truncate -s 128M {path}; "
            "echo ,,L | sfdisk {path};"
            "loopdev=`losetup -f`; "
            "losetup -P $loopdev {path}; "
            "blockdev --rereadpt $loopdev; "
            "udevadm settle".format(path=self.img_path), user="root")

        dev_list = qubes.qubesutils.block_list_vm(self.vm)
        found = False
        for dev in dev_list.keys():
            if dev_list[dev]['desc'] == self.img_path:
                self.assertTrue(dev.startswith(self.vm.name + ':loop'))
                self.assertEquals(dev_list[dev]['mode'], 'w')
                self.assertEquals(dev_list[dev]['size'], 1024 * 1024 * 128)
                self.assertEquals(
                    dev_list[dev]['device'], '/dev/' + dev.split(':')[1])
                self.assertIn(dev + 'p1', dev_list)
                found = True

        if not found:
            self.fail("Device {} not found in {!r}".format(self.img_path, dev_list))

    def test_021_list_loop_partition_mounted(self):
        if self.template is None:
            self.skipTest('loop devices excluded in dom0')
        self.run_script(
            "set -e;"
            "truncate -s 128M {path}; "
            "echo ,,L | sfdisk {path};"
            "loopdev=`losetup -f`; "
            "losetup -P $loopdev {path}; "
            "blockdev --rereadpt $loopdev; "
            "mkfs.ext4 -q -F ${{loopdev}}p1; "
            "mkdir -p {mntdir}; "
            "mount ${{loopdev}}p1 {mntdir}; "
            "udevadm settle".format(
                path=self.img_path, mntdir=self.mount_point),
            user="root")

        dev_list = qubes.qubesutils.block_list_vm(self.vm)
        for dev in dev_list.keys():
            if dev_list[dev]['desc'] == self.img_path:
                self.fail(
                    'Device {} ({}) should not be listed because its '
                    'partition is mounted'
                    .format(dev, self.img_path))
            elif dev.startswith(self.vm.name + ':loop') and dev.endswith('p1'):
                # FIXME: risky assumption that only tests create partitioned
                # loop devices
                self.fail(
                    'Device {} ({}) should not be listed because is mounted'
                    .format(dev, self.img_path))


def load_tests(loader, tests, pattern):
    try:
        qc = qubes.qubes.QubesVmCollection()
        qc.lock_db_for_reading()
        qc.load()
        qc.unlock_db()
        templates = [vm.name for vm in qc.values() if
                     isinstance(vm, qubes.qubes.QubesTemplateVm)]
    except OSError:
        templates = []
    for template in templates:
        tests.addTests(loader.loadTestsFromTestCase(
            type(
                'TC_00_List_' + template,
                (TC_00_List, qubes.tests.QubesTestCase),
                {'template': template})))

    return tests
