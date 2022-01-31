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
        super().__init__('/tmp/qubes-test.xml', load=False,
                         offline_mode=True, **kwargs)
        self.load_initial_values()


class ReflinkMixin:
    @classmethod
    def setUpClass(cls, *, fs_type, ficlone_supported):
        super().setUpClass()
        cls.ficlone_supported = ficlone_supported
        cls.fs_dir = '/var/tmp/test-reflink-units-on-' + fs_type
        mkdir_fs(cls.fs_dir, fs_type)

    @classmethod
    def tearDownClass(cls):
        rmtree_fs(cls.fs_dir)
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        self.test_dir = os.path.join(self.fs_dir, 'test')
        os.mkdir(self.test_dir)
        self.addCleanup(shutil.rmtree, self.test_dir)

    def _test_copy_file(self, *, src_size, **kwargs_for_func):
        src = os.path.join(self.test_dir, 'src-file')
        dst = os.path.join(self.test_dir, 'new-directory', 'dst-file')
        src_content = os.urandom(src_size)
        dst_size = kwargs_for_func.get('dst_size', None)
        copy_mtime = kwargs_for_func.get('copy_mtime', None)

        with open(src, 'wb') as src_io:
            src_io.write(src_content)

        ficlone_succeeded = reflink._copy_file(src, dst, **kwargs_for_func)
        if dst_size == 0:
            self.assertIsNone(ficlone_succeeded)
        else:
            self.assertEqual(ficlone_succeeded, self.ficlone_supported)

        src_stat = os.stat(src)
        dst_stat = os.stat(dst)
        self.assertNotEqual(
            (src_stat.st_ino, src_stat.st_dev),
            (dst_stat.st_ino, dst_stat.st_dev))
        (self.assertEqual if copy_mtime else self.assertNotEqual)(
            src_stat.st_mtime_ns,
            dst_stat.st_mtime_ns)

        with open(src, 'rb') as src_io:
            self.assertEqual(src_io.read(), src_content)
        with open(dst, 'rb') as dst_io:
            if dst_size in (None, src_size):
                self.assertEqual(dst_io.read(), src_content)
            elif dst_size == 0:
                self.assertEqual(dst_io.read(), b'')
            elif dst_size < src_size:
                self.assertEqual(dst_io.read(), src_content[:dst_size])
            elif dst_size > src_size:
                self.assertEqual(dst_io.read(src_size), src_content)
                self.assertEqual(dst_io.read(), bytes(dst_size - src_size))

    def test_000_copy_file(self):
        self._test_copy_file(src_size=222222)

    def test_001_copy_file_extend(self):
        self._test_copy_file(src_size=222222, dst_size=333333)

    def test_002_copy_file_shrink(self):
        self._test_copy_file(src_size=222222, dst_size=111111)

    def test_003_copy_file_shrink0(self):
        self._test_copy_file(src_size=222222, dst_size=0)

    def test_010_copy_file_mtime(self):
        self._test_copy_file(src_size=222222, copy_mtime=True)

    def test_011_copy_file_mtime_extend(self):
        self._test_copy_file(src_size=222222, copy_mtime=True, dst_size=333333)

    def test_012_copy_file_mtime_shrink(self):
        self._test_copy_file(src_size=222222, copy_mtime=True, dst_size=111111)

    def test_013_copy_file_mtime_shrink0(self):
        self._test_copy_file(src_size=222222, copy_mtime=True, dst_size=0)

    def test_100_create_and_resize_files_and_update_loopdevs(self):
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

    def test_200_eq_files_true(self):
        file1 = os.path.join(self.test_dir, 'file1')
        file2 = os.path.join(self.test_dir, 'file2')

        with open(file1, 'wb'):
            pass
        os.link(file1, file2)

        stat1 = os.stat(file1)
        stat2 = os.stat(file2)
        self.assertTrue(reflink._eq_files(stat1, stat2))
        self.assertTrue(reflink._eq_files(stat1, stat1))
        self.assertTrue(reflink._eq_files(stat2, stat2))

    def test_201_eq_files_false(self):
        file1 = os.path.join(self.test_dir, 'file1')
        file2 = os.path.join(self.test_dir, 'file2')

        with open(file1, 'wb'), open(file2, 'wb'):
            pass

        stat1 = os.stat(file1)
        stat2 = os.stat(file2)
        self.assertFalse(reflink._eq_files(stat1, stat2))
        os.utime(file2, ns=(stat1.st_atime_ns, stat1.st_mtime_ns))
        stat2 = os.stat(file2)
        self.assertEqual(stat1.st_mtime_ns, stat2.st_mtime_ns)
        self.assertEqual(stat1.st_size, stat2.st_size)
        self.assertFalse(reflink._eq_files(stat1, stat2))

    def test_210_eq_files_by_attrs(self):
        file1 = os.path.join(self.test_dir, 'file1')
        file2 = os.path.join(self.test_dir, 'file2')

        with open(file1, 'wb') as file1_io:
            file1_io.write(b'foo')
        with open(file2, 'wb') as file2_io:
            file2_io.write(b'bar')

        stat1 = os.stat(file1)
        os.utime(file2, ns=(0, 0))
        stat2 = os.stat(file2)
        self.assertFalse(reflink._eq_files(
            stat1, stat2))
        self.assertTrue(reflink._eq_files(
            stat1, stat2, by_attrs=[]))
        self.assertTrue(reflink._eq_files(
            stat1, stat2, by_attrs=['st_size']))
        self.assertFalse(reflink._eq_files(
            stat1, stat2, by_attrs=['st_mtime_ns', 'st_size']))

        stat1 = os.stat(file1)
        os.utime(file2, ns=(0, stat1.st_mtime_ns))
        stat2 = os.stat(file2)
        self.assertTrue(reflink._eq_files(
            stat1, stat2, by_attrs=['st_mtime_ns', 'st_size']))

        stat1 = os.stat(file1)
        os.truncate(file2, 222)
        os.utime(file2, ns=(0, stat1.st_mtime_ns))
        stat2 = os.stat(file2)
        self.assertFalse(reflink._eq_files(
            stat1, stat2, by_attrs=['st_mtime_ns', 'st_size']))


class TC_00_ReflinkOnBtrfs(ReflinkMixin, qubes.tests.QubesTestCase):
    @classmethod
    def setUpClass(cls):  # pylint: disable=arguments-differ
        super().setUpClass(fs_type='btrfs', ficlone_supported=True)


class TC_01_ReflinkOnExt4(ReflinkMixin, qubes.tests.QubesTestCase):
    @classmethod
    def setUpClass(cls):  # pylint: disable=arguments-differ
        super().setUpClass(fs_type='ext4', ficlone_supported=False)


class TC_02_ReflinkOnXfs(ReflinkMixin, qubes.tests.QubesTestCase):
    @classmethod
    def setUpClass(cls):  # pylint: disable=arguments-differ
        super().setUpClass(fs_type='xfs', ficlone_supported=True)


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
        super().tearDown()

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
        volume_exported = self.loop.run_until_complete(volume.export())
        with open(volume_exported, 'w') as volume_file:
            volume_file.write('test data')
        import_path = self.loop.run_until_complete(
            volume.import_data(volume.size))
        self.assertNotEqual(volume.path, import_path)
        with open(import_path, 'w+'):
            pass
        self.loop.run_until_complete(volume.import_data_end(True))
        self.assertFalse(os.path.exists(import_path), import_path)
        volume_exported = self.loop.run_until_complete(volume.export())
        with open(volume_exported) as volume_file:
            volume_data = volume_file.read().strip('\0')
        self.assertNotEqual(volume_data, 'test data')


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
    p = subprocess.run(
        argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if p.returncode != 0:
        raise Exception(str(p))  # this will show stdout and stderr
    return p.stdout
