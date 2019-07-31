#
# The Qubes OS Project, https://www.qubes-os.org
#
# Copyright (C) 2018 Rusty Bird <rustybird@net-c.com>
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

''' Tests for the file-reflink storage driver '''

# pylint: disable=protected-access
# pylint: disable=invalid-name

import os
import shutil
import subprocess
import sys

import qubes.tests
import qubes.tests.storage
from qubes.storage import reflink

class TestApp(qubes.Qubes):
    ''' A Mock App object '''
    def __init__(self, *args, **kwargs):  # pylint: disable=unused-argument
        super(TestApp, self).__init__('/tmp/qubes-test.xml', load=False,
                                      offline_mode=True, **kwargs)
        self.load_initial_values()


class ReflinkMixin:
    def setUp(self, fs_type='btrfs'):  # pylint: disable=arguments-differ
        super().setUp()
        self.test_dir = '/var/tmp/test-reflink-units-on-' + fs_type
        mkdir_fs(self.test_dir, fs_type, cleanup_via=self.addCleanup)

    def test_000_copy_file(self):
        source = os.path.join(self.test_dir, 'source-file')
        dest = os.path.join(self.test_dir, 'new-directory', 'dest-file')
        content = os.urandom(1024**2)

        with open(source, 'wb') as source_io:
            source_io.write(content)

        ficlone_succeeded = reflink._copy_file(source, dest)
        self.assertEqual(ficlone_succeeded, self.ficlone_supported)

        self.assertNotEqual(os.stat(source).st_ino, os.stat(dest).st_ino)
        with open(source, 'rb') as source_io:
            self.assertEqual(source_io.read(), content)
        with open(dest, 'rb') as dest_io:
            self.assertEqual(dest_io.read(), content)

    def test_001_create_and_resize_files_and_update_loopdevs(self):
        img_real = os.path.join(self.test_dir, 'img-real')
        img_sym = os.path.join(self.test_dir, 'img-sym')
        size_initial = 111 * 1024**2
        size_resized = 222 * 1024**2

        os.symlink(img_real, img_sym)
        reflink._create_sparse_file(img_real, size_initial)
        stat = os.stat(img_real)
        self.assertEqual(stat.st_blocks, 0)
        self.assertEqual(stat.st_size, size_initial)

        dev_from_real = setup_loopdev(img_real, cleanup_via=self.addCleanup)
        dev_from_sym = setup_loopdev(img_sym, cleanup_via=self.addCleanup)

        reflink._resize_file(img_real, size_resized)
        stat = os.stat(img_real)
        self.assertEqual(stat.st_blocks, 0)
        self.assertEqual(stat.st_size, size_resized)

        reflink_update_loopdev_sizes(os.path.join(self.test_dir, 'unrelated'))

        for dev in (dev_from_real, dev_from_sym):
            self.assertEqual(get_blockdev_size(dev), size_initial)

        reflink_update_loopdev_sizes(img_sym)

        for dev in (dev_from_real, dev_from_sym):
            self.assertEqual(get_blockdev_size(dev), size_resized)


class TC_10_ReflinkPool(qubes.tests.QubesTestCase):
    def setUp(self):
        super().setUp()
        self.test_dir = '/var/tmp/test-reflink-units-on-btrfs'
        pool_conf = {
            'driver': 'file-reflink',
            'dir_path': self.test_dir,
            'name': 'test-btrfs'
        }
        mkdir_fs(self.test_dir, 'btrfs', cleanup_via=self.addCleanup)
        self.app = TestApp()
        self.pool = self.loop.run_until_complete(self.app.add_pool(**pool_conf))
        self.app.default_pool = self.app.get_pool(pool_conf['name'])

    def tearDown(self) -> None:
        self.app.default_pool = 'varlibqubes'
        self.loop.run_until_complete(self.app.remove_pool(self.pool.name))
        del self.pool
        self.app.close()
        del self.app
        super(TC_10_ReflinkPool, self).tearDown()

    def test_012_import_data_empty(self):
        config = {
            'name': 'root',
            'pool': self.pool.name,
            'save_on_stop': True,
            'rw': True,
            'size': 1024 * 1024,
        }
        vm = qubes.tests.storage.TestVM(self)
        volume = self.pool.init_volume(vm, config)
        self.loop.run_until_complete(volume.create())
        with open(volume.export(), 'w') as vol_file:
            vol_file.write('test data')
        import_path = self.loop.run_until_complete(volume.import_data())
        self.assertNotEqual(volume.path, import_path)
        with open(import_path, 'w+'):
            pass
        self.loop.run_until_complete(volume.import_data_end(True))
        self.assertFalse(os.path.exists(import_path), import_path)
        with open(volume.export()) as volume_file:
            volume_data = volume_file.read().strip('\0')
        self.assertNotEqual(volume_data, 'test data')


class TC_00_ReflinkOnBtrfs(ReflinkMixin, qubes.tests.QubesTestCase):
    def setUp(self):  # pylint: disable=arguments-differ
        super().setUp('btrfs')
        self.ficlone_supported = True

class TC_01_ReflinkOnExt4(ReflinkMixin, qubes.tests.QubesTestCase):
    def setUp(self):  # pylint: disable=arguments-differ
        super().setUp('ext4')
        self.ficlone_supported = False


def setup_loopdev(img, cleanup_via=None):
    dev = str.strip(cmd('sudo', 'losetup', '-f', '--show', img).decode())
    if cleanup_via is not None:
        cleanup_via(detach_loopdev, dev)
    return dev

def detach_loopdev(dev):
    cmd('sudo', 'losetup', '-d', dev)

def get_fs_type(directory):
    # 'stat -f -c %T' would identify ext4 as 'ext2/ext3'
    return cmd('df', '--output=fstype', directory).decode().splitlines()[1]

def mkdir_fs(directory, fs_type,
             accessible=True, max_size=100*1024**3, cleanup_via=None):
    os.mkdir(directory)

    if get_fs_type(directory) != fs_type:
        img = os.path.join(directory, 'img')
        with open(img, 'xb') as img_io:
            img_io.truncate(max_size)
        cmd('mkfs.' + fs_type, img)
        dev = setup_loopdev(img)
        os.remove(img)
        cmd('sudo', 'mount', dev, directory)
        detach_loopdev(dev)

    if accessible:
        cmd('sudo', 'chmod', '777', directory)
    else:
        cmd('sudo', 'chmod', '000', directory)
        cmd('sudo', 'chattr', '+i', directory)  # cause EPERM on write as root

    if cleanup_via is not None:
        cleanup_via(rmtree_fs, directory)

def rmtree_fs(directory):
    cmd('sudo', 'chattr', '-i', directory)
    cmd('sudo', 'chmod', '777', directory)
    if os.path.ismount(directory):
        cmd('sudo', 'umount', '-l', directory)
        # loop device and backing file are garbage collected automatically
    shutil.rmtree(directory)

def get_blockdev_size(dev):
    return int(cmd('sudo', 'blockdev', '--getsize64', dev))

def reflink_update_loopdev_sizes(img):
    env = [k + '=' + v for k, v in os.environ.items()  # 'sudo -E' alone would
           if k.startswith('PYTHON')]                  # drop some of these
    code = ('from qubes.storage import reflink\n'
            'reflink._update_loopdev_sizes(%r)' % img)
    cmd('sudo', '-E', 'env', *env, sys.executable, '-c', code)

def cmd(*argv):
    p = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.returncode != 0:
        raise Exception(str(p))  # this will show stdout and stderr
    return p.stdout
