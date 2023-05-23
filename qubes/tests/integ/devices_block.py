# vim: fileencoding=utf-8
#
# The Qubes OS Project, https://www.qubes-os.org/
#
# Copyright (C) 2018
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
import asyncio
import os

import sys

import qubes
import qubes.devices
import qubes.tests
import subprocess

# the same class for both dom0 and VMs
class TC_00_List(qubes.tests.SystemTestCase):
    template = None

    def setUp(self):
        super().setUp()
        self.img_path = '/tmp/test.img'
        self.mount_point = '/tmp/test-dir'
        if self.template is not None:
            self.init_default_template(self.template)
            self.vm = self.app.add_new_vm(
                "AppVM",
                label='red',
                name=self.make_vm_name("vm"))
            self.loop.run_until_complete(
                self.vm.create_on_disk())
            self.app.save()
            self.loop.run_until_complete(self.vm.start())
        else:
            self.vm = self.app.domains[0]

    def tearDown(self):
        super().tearDown()
        if self.template is None:
            if os.path.exists(self.mount_point):
                subprocess.call(['sudo', 'umount', self.mount_point])
                subprocess.call(['sudo', 'rmdir', self.mount_point])
            if os.path.exists('/dev/mapper/test-dm'):
                subprocess.call(['sudo', 'dmsetup', 'remove', 'test-dm'])
            if os.path.exists(self.img_path):
                loopdev = subprocess.check_output(['losetup', '-j',
                    self.img_path])
                for dev in loopdev.decode().splitlines():
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
            self.loop.run_until_complete(
                self.vm.run_for_stdio(script, user=user))

    def test_000_list_loop(self):
        if self.template is None:
            self.skipTest('loop devices excluded in dom0')
        self.run_script(
            "set -e;"
            "truncate -s 128M {path}; "
            "losetup -f {path}; "
            "udevadm settle".format(path=self.img_path), user="root")

        dev_list = list(self.vm.devices['block'])
        found = False
        for dev in dev_list:
            if dev.description == self.img_path:
                self.assertTrue(dev.ident.startswith('loop'))
                self.assertEquals(dev.mode, 'w')
                self.assertEquals(dev.size, 1024 * 1024 * 128)
                found = True

        if not found:
            self.fail("Device {} not found in {!r}".format(
                self.img_path, dev_list))

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

        dev_list = list(self.vm.devices['block'])
        for dev in dev_list:
            if dev.description == self.img_path:
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

        dev_list = list(self.vm.devices['block'])
        found = False
        for dev in dev_list:
            if dev.ident.startswith('loop'):
                self.assertNotEquals(dev.description, self.img_path,
                    "Device {} ({}) should not be listed as it is used in "
                    "device-mapper".format(dev, self.img_path)
                )
            elif dev.description == 'test-dm':
                self.assertEquals(dev.mode, 'w')
                self.assertEquals(dev.size, 1024 * 1024 * 128)
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

        dev_list = list(self.vm.devices['block'])
        for dev in dev_list:
            if dev.ident.startswith('loop'):
                self.assertNotEquals(dev.description, self.img_path,
                    "Device {} ({}) should not be listed as it is used in "
                    "device-mapper".format(dev, self.img_path)
                )
            else:
                self.assertNotEquals(dev.description, 'test-dm',
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

        dev_list = list(self.vm.devices['block'])
        found = False
        for dev in dev_list:
            if dev.ident.startswith('loop'):
                self.assertNotEquals(dev.description, self.img_path,
                    "Device {} ({}) should not be listed as it is used in "
                    "device-mapper".format(dev, self.img_path)
                )
            elif dev.description == 'test-dm':
                self.assertEquals(dev.mode, 'w')
                self.assertEquals(dev.size, 1024 * 1024 * 128)
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

        dev_list = list(self.vm.devices['block'])
        found = False
        for dev in dev_list:
            if dev.description == self.img_path:
                self.assertTrue(dev.ident.startswith('loop'))
                self.assertEquals(dev.mode, 'w')
                self.assertEquals(dev.size, 1024 * 1024 * 128)
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

        dev_list = list(self.vm.devices['block'])
        found = False
        for dev in dev_list:
            if dev.description == self.img_path:
                self.assertTrue(dev.ident.startswith('loop'))
                self.assertEquals(dev.mode, 'w')
                self.assertEquals(dev.size, 1024 * 1024 * 128)
                self.assertIn(dev.ident + 'p1', [d.ident for d in dev_list])
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

        dev_list = list(self.vm.devices['block'])
        for dev in dev_list:
            if dev.description == self.img_path:
                self.fail(
                    'Device {} ({}) should not be listed because its '
                    'partition is mounted'
                    .format(dev, self.img_path))
            elif dev.ident.startswith('loop') and dev.ident.endswith('p1'):
                # FIXME: risky assumption that only tests create partitioned
                # loop devices
                self.fail(
                    'Device {} ({}) should not be listed because is mounted'
                    .format(dev, self.img_path))


class AttachMixin:
    template = None

    def setUp(self):
        super().setUp()
        self.init_default_template(self.template)
        self.img_path = '/tmp/test.img'
        self.backend = self.app.add_new_vm(
            "AppVM",
            label='red',
            name=self.make_vm_name("back"))
        self.loop.run_until_complete(
            self.backend.create_on_disk())
        self.frontend = self.app.add_new_vm(
            "AppVM",
            label='red',
            name=self.make_vm_name("front"))
        self.loop.run_until_complete(
            self.frontend.create_on_disk())
        self.app.save()
        exc = self.loop.run_until_complete(asyncio.gather(
            self.backend.start(),
            self.frontend.start(),
            return_exceptions=True
        ))
        if any(isinstance(e, Exception) for e in exc):
            self.fail('Failed to start some VM: {!r}'.format(exc))
        self.loop.run_until_complete(self.backend.run_for_stdio(
            "set -e;"
            "truncate -s 128M {path}; "
            "losetup -f {path}; "
            "udevadm settle".format(path=self.img_path), user="root"))
        dev_list = list(self.backend.devices['block'])
        for dev in dev_list:
            if dev.description == self.img_path:
                self.device = dev
                self.device_ident = dev.ident
                break
        else:
            self.fail('Device for {} in {} not found'.format(
                self.img_path, self.backend.name))

    def test_000_attach_reattach(self):
        ass = qubes.devices.DeviceAssignment(self.backend, self.device_ident)
        with self.subTest('attach'):
            self.loop.run_until_complete(
                self.frontend.devices['block'].attach(ass))
            self.loop.run_until_complete(asyncio.sleep(2))

            # may raise CalledProcessError
            self.loop.run_until_complete(
                self.frontend.run_for_stdio('ls /dev/xvdi'))

        with self.subTest('detach'):
            self.loop.run_until_complete(
                self.frontend.devices['block'].detach(ass))
            self.loop.run_until_complete(asyncio.sleep(2))

            # may raise CalledProcessError
            self.loop.run_until_complete(
                self.frontend.run_for_stdio('! ls /dev/xvdi'))

            self.assertIsNone(self.device.frontend_domain)

        with self.subTest('reattach'):
            self.loop.run_until_complete(
                self.frontend.devices['block'].attach(ass))
            self.loop.run_until_complete(asyncio.sleep(2))

            # may raise CalledProcessError
            self.loop.run_until_complete(
                self.frontend.run_for_stdio('ls /dev/xvdi'))


def create_testcases_for_templates():
    yield from qubes.tests.create_testcases_for_templates('TC_00_List',
        TC_00_List,
        module=sys.modules[__name__])
    yield from qubes.tests.create_testcases_for_templates('TC_10_Attach',
        AttachMixin, qubes.tests.SystemTestCase,
        module=sys.modules[__name__])

def load_tests(loader, tests, pattern):
    tests.addTests(loader.loadTestsFromNames(
        create_testcases_for_templates()))
    return tests

qubes.tests.maybe_create_testcases_on_import(create_testcases_for_templates)
