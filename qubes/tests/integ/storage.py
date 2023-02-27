#
# The Qubes OS Project, http://www.qubes-os.org
#
# Copyright (C) 2016 Marek Marczykowski-Górecki
#                               <marmarek@invisiblethingslab.com>
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
import shutil
import subprocess
from contextlib import suppress

import qubes.storage.lvm
import qubes.tests
import qubes.tests.storage_lvm
import qubes.tests.storage_reflink
import qubes.tests.storage_zfs
import qubes.utils
import qubes.vm.appvm


class StorageTestMixin(object):
    def setUp(self):
        super(StorageTestMixin, self).setUp()
        self.init_default_template()
        self.old_default_pool = self.app.default_pool
        self.vm1 = self.app.add_new_vm(qubes.vm.appvm.AppVM,
            name=self.make_vm_name('vm1'),
            label='red')
        self.loop.run_until_complete(self.vm1.create_on_disk())
        self.vm2 = self.app.add_new_vm(qubes.vm.appvm.AppVM,
            name=self.make_vm_name('vm2'),
            label='red')
        self.loop.run_until_complete(self.vm2.create_on_disk())
        self.pool = None
        self.init_pool()
        self.app.save()

    def tearDown(self):
        with suppress(qubes.exc.QubesException):
            self.loop.run_until_complete(self.vm1.kill())
        with suppress(qubes.exc.QubesException):
            self.loop.run_until_complete(self.vm2.kill())
        del self.app.domains[self.vm1]
        del self.app.domains[self.vm2]
        del self.vm1
        del self.vm2
        self.app.default_pool = self.old_default_pool
        self.cleanup_pool()
        del self.pool
        super(StorageTestMixin, self).tearDown()

    def init_pool(self):
        ''' Initialize storage pool to be tested, store it in self.pool'''
        raise NotImplementedError

    def cleanup_pool(self):
        ''' Remove tested storage pool'''
        raise NotImplementedError

    def test_000_volatile(self):
        '''Test if volatile volume is really volatile'''
        return self.loop.run_until_complete(self._test_000_volatile())

    async def _test_000_volatile(self):
        size = 32*1024*1024
        volume_config = {
            'pool': self.pool.name,
            'size': size,
            'save_on_stop': False,
            'rw': True,
        }
        testvol = self.vm1.storage.init_volume('testvol', volume_config)
        await qubes.utils.coro_maybe(testvol.create())
        del testvol
        self.app.save()
        await (self.vm1.start())
        await self.wait_for_session(self.vm1)

        # volatile image not clean
        await (self.vm1.run_for_stdio(
            'cmp -n 16K /dev/xvde /dev/zero',
            user='root'))
        # volatile image not volatile; check two markers: at the very beginning,
        # and at a later offset
        await (
            self.vm1.run_for_stdio('echo test123 > /dev/xvde', user='root'))
        await (self.vm1.run_for_stdio(
            'echo test123 | dd of=/dev/xvde seek=1M bs=1', user='root'))
        await (self.vm1.shutdown(wait=True))
        await (self.vm1.start())
        await (self.vm1.run_for_stdio(
            'cmp -n 16K /dev/xvde /dev/zero',
            user='root'))
        await (self.vm1.run_for_stdio(
            '! dd if=/dev/xvde bs=1 skip=1M count=7 | grep test123',
            user='root'))

    def test_001_non_volatile(self):
        '''Test if non-volatile volume is really non-volatile'''
        return self.loop.run_until_complete(self._test_001_non_volatile())

    async def _test_001_non_volatile(self):
        size = 32*1024*1024
        volume_config = {
            'pool': self.pool.name,
            'size': size,
            'save_on_stop': True,
            'rw': True,
        }
        testvol = self.vm1.storage.init_volume('testvol', volume_config)
        await qubes.utils.coro_maybe(testvol.create())
        del testvol
        self.app.save()
        await self.vm1.start()
        await self.wait_for_session(self.vm1)
        # non-volatile image not clean
        await self.vm1.run_for_stdio(
            'head -c {} /dev/zero 2>&1 | diff -q /dev/xvde - 2>&1'.format(size),
            user='root')

        await self.vm1.run_for_stdio('echo test123 > /dev/xvde',
            user='root')
        await self.vm1.shutdown(wait=True)
        await self.vm1.start()
        # non-volatile image volatile
        with self.assertRaises(subprocess.CalledProcessError):
            await self.vm1.run_for_stdio(
                'head -c {} /dev/zero 2>&1 | diff -q /dev/xvde - 2>&1'.format(
                    size),
                user='root')

    def test_002_read_only(self):
        '''Test read-only volume'''
        self.loop.run_until_complete(self._test_002_read_only())

    async def _test_002_read_only(self):
        size = 32 * 1024 * 1024
        volume_config = {
            'pool': self.pool.name,
            'size': size,
            'save_on_stop': False,
            'rw': False,
        }
        testvol = self.vm1.storage.init_volume('testvol', volume_config)
        await qubes.utils.coro_maybe(testvol.create())
        del testvol
        self.app.save()
        await self.vm1.start()
        # non-volatile image not clean
        await self.vm1.run_for_stdio(
            'head -c {} /dev/zero 2>&1 | diff -q /dev/xvde - 2>&1'.format(size),
            user='root')
        # Write to read-only volume unexpectedly succeeded
        with self.assertRaises(subprocess.CalledProcessError):
            await self.vm1.run_for_stdio('echo test123 > /dev/xvde',
                user='root')
        # read-only volume modified
        await self.vm1.run_for_stdio(
            'head -c {} /dev/zero 2>&1 | diff -q /dev/xvde - 2>&1'.format(size),
            user='root')

    def test_003_snapshot(self):
        '''Test snapshot volume data propagation'''
        self.loop.run_until_complete(self._test_003_snapshot())

    async def _test_003_snapshot(self):
        size = 128 * 1024 * 1024
        volume_config = {
            'pool': self.pool.name,
            'size': size,
            'save_on_stop': True,
            'rw': True,
        }
        testvol = self.vm1.storage.init_volume('testvol', volume_config)
        await qubes.utils.coro_maybe(testvol.create())
        volume_config = {
            'pool': self.pool.name,
            'size': size,
            'snap_on_start': True,
            'source': testvol.vid,
            'rw': True,
        }
        del testvol
        testvol_snap = self.vm2.storage.init_volume('testvol', volume_config)
        await qubes.utils.coro_maybe(testvol_snap.create())
        del testvol_snap
        self.app.save()
        await self.vm1.start()
        await self.vm2.start()
        await asyncio.wait(
            [asyncio.create_task(self.wait_for_session(self.vm1)),
             asyncio.create_task(self.wait_for_session(self.vm2))])

        try:
            await self.vm1.run_for_stdio(
                'head -c {} /dev/zero 2>&1 | diff -q /dev/xvde - 2>&1'.
                    format(size),
                user='root')
        except subprocess.CalledProcessError:
            self.fail('origin image not clean')

        try:
            await self.vm2.run_for_stdio(
                'head -c {} /dev/zero | diff -q /dev/xvde -'.format(size),
                user='root')
        except subprocess.CalledProcessError:
            self.fail('snapshot image not clean')

        try:
            await self.vm1.run_for_stdio(
                'echo test123 > /dev/xvde && sync',
                user='root')
        except subprocess.CalledProcessError:
            self.fail('Write to read-write volume failed')
        try:
            await self.vm2.run_for_stdio(
                'head -c {} /dev/zero 2>&1 | diff -q /dev/xvde - 2>&1'.
                    format(size),
                user='root')
        except subprocess.CalledProcessError:
            self.fail('origin changes propagated to snapshot too early')
        await self.vm1.shutdown(wait=True)

        # after origin shutdown there should be still no change

        try:
            await self.vm2.run_for_stdio(
                'head -c {} /dev/zero 2>&1 | diff -q /dev/xvde - 2>&1'.
                    format(size),
                user='root')
        except subprocess.CalledProcessError:
            self.fail('origin changes propagated to snapshot too early2')

        await self.vm2.shutdown(wait=True)
        await self.start_vm(self.vm2)

        # only after target VM restart changes should be visible

        with self.assertRaises(subprocess.CalledProcessError,
                msg='origin changes not visible in snapshot'):
            await self.vm2.run_for_stdio(
                'head -c {} /dev/zero 2>&1 | diff -q /dev/xvde - 2>&1'.format(
                    size),
                user='root')

        await self.vm2.shutdown(wait=True)

        # change origin again ...

        await self.start_vm(self.vm1)
        try:
            await self.vm1.run_for_stdio(
                'echo test456 > /dev/xvde && sync',
                user='root')
        except subprocess.CalledProcessError:
            self.fail('Write to read-write volume failed2')
        await self.vm1.shutdown(wait=True)

        # ... and check that the snapshot is not stuck

        await self.start_vm(self.vm2)
        try:
            await self.vm2.run_for_stdio(
                'echo test456 | cat - /dev/zero |'
                ' head -c {} | diff -q /dev/xvde - 2>&1'.format(size),
                user='root')
        except subprocess.CalledProcessError:
            self.fail('origin changes did not refresh snapshot')

    def test_004_snapshot_non_persistent(self):
        '''Test snapshot volume non-persistence'''
        return self.loop.run_until_complete(
            self._test_004_snapshot_non_persistent())

    async def _test_004_snapshot_non_persistent(self):
        size = 128 * 1024 * 1024
        volume_config = {
            'pool': self.pool.name,
            'size': size,
            'save_on_stop': True,
            'rw': True,
        }
        testvol = self.vm1.storage.init_volume('testvol', volume_config)
        await qubes.utils.coro_maybe(testvol.create())
        volume_config = {
            'pool': self.pool.name,
            'size': size,
            'snap_on_start': True,
            'source': testvol.vid,
            'rw': True,
        }
        del testvol
        testvol_snap = self.vm2.storage.init_volume('testvol', volume_config)
        await qubes.utils.coro_maybe(testvol_snap.create())
        del testvol_snap
        self.app.save()
        await self.vm2.start()
        await self.wait_for_session(self.vm2)

        # snapshot image not clean
        await self.vm2.run_for_stdio(
            'head -c {} /dev/zero | diff -q /dev/xvde -'.format(size),
            user='root')

        # Write to read-write snapshot volume failed
        await self.vm2.run_for_stdio('echo test123 > /dev/xvde && sync',
            user='root')
        await self.vm2.shutdown(wait=True)
        await self.vm2.start()

        # changes on snapshot survived VM restart
        await self.vm2.run_for_stdio(
            'head -c {} /dev/zero 2>&1 | diff -q /dev/xvde - 2>&1'.format(size),
            user='root')

    def test_005_size_after_clone(self):
        '''Test snapshot volume non-persistence'''
        return self.loop.run_until_complete(
            self._test_005_size_after_clone())

    async def _test_005_size_after_clone(self):
        size = 128 * 1024 * 1024
        volume_config = {
            'pool': self.pool.name,
            'size': size,
            'save_on_stop': True,
            'rw': True,
        }
        testvol = self.vm1.storage.init_volume('testvol', volume_config)
        await qubes.utils.coro_maybe(testvol.create())
        self.assertEquals(testvol.size, size)
        volume_config = {
            'pool': self.pool.name,
            'size': size // 2,
            'save_on_stop': True,
            'rw': True,
        }
        testvol2 = self.vm2.storage.init_volume('testvol2', volume_config)
        await qubes.utils.coro_maybe(testvol2.create())
        self.assertEquals(testvol2.size, size // 2)
        await qubes.utils.coro_maybe(testvol2.import_volume(testvol))
        self.assertEquals(testvol2.size, size)


class StorageFile(StorageTestMixin, qubes.tests.SystemTestCase):
    def init_pool(self):
        self.dir_path = '/var/tmp/test-pool'
        self.pool = self.loop.run_until_complete(
            self.app.add_pool(dir_path=self.dir_path,
                name='test-pool', driver='file'))
        os.makedirs(os.path.join(self.dir_path, 'appvms', self.vm1.name),
            exist_ok=True)
        os.makedirs(os.path.join(self.dir_path, 'appvms', self.vm2.name),
            exist_ok=True)

    def cleanup_pool(self):
        self.loop.run_until_complete(self.app.remove_pool('test-pool'))
        shutil.rmtree(self.dir_path)


class StorageReflinkMixin(StorageTestMixin):
    def cleanup_pool(self):
        self.loop.run_until_complete(self.app.remove_pool(self.pool.name))

    def init_pool(self, fs_type, **kwargs):
        name = 'test-reflink-integration-on-' + fs_type
        dir_path = os.path.join('/var/tmp', name)
        qubes.tests.storage_reflink.mkdir_fs(dir_path, fs_type,
                                             cleanup_via=self.addCleanup)
        self.pool = self.loop.run_until_complete(
            self.app.add_pool(name=name, dir_path=dir_path,
                              driver='file-reflink', **kwargs))

class StorageReflinkOnBtrfs(StorageReflinkMixin, qubes.tests.SystemTestCase):
    def init_pool(self):
        super().init_pool('btrfs')

class StorageReflinkOnExt4(StorageReflinkMixin, qubes.tests.SystemTestCase):
    def init_pool(self):
        super().init_pool('ext4', setup_check=False)


@qubes.tests.storage_lvm.skipUnlessLvmPoolExists
class StorageLVM(StorageTestMixin, qubes.tests.SystemTestCase):
    def init_pool(self):
        self.created_pool = False
        # check if the default LVM Thin pool qubes_dom0/pool00 exists
        volume_group, thin_pool = \
            qubes.tests.storage_lvm.DEFAULT_LVM_POOL.split('/', 1)
        self.pool = self._find_pool(volume_group, thin_pool)
        if not self.pool:
            self.pool = self.loop.run_until_complete(
                self.app.add_pool(**qubes.tests.storage_lvm.POOL_CONF))
            self.created_pool = True

    def cleanup_pool(self):
        ''' Remove the default lvm pool if it was created only for this test '''
        if self.created_pool:
            self.loop.run_until_complete(self.app.remove_pool(self.pool.name))

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


class StorageZFSMixin(StorageTestMixin):
    def init_pool(self, **kwargs):
        name = "test-reflink-integration-on-zfs"
        setup = qubes.tests.storage_zfs.setup_test_zfs_pool
        self.pool_backing_file, self.pool_test_dataset = setup(name)
        self.pool = self.loop.run_until_complete(
            self.app.add_pool(
                name=name,
                container=self.pool_test_dataset,
                driver="zfs",
                **kwargs,
            )
        )

    def cleanup_pool(self):
        pool_name = self.pool.name
        self.loop.run_until_complete(self.app.remove_pool(pool_name))
        qubes.tests.storage_zfs.teardown_test_zfs_pool(
            self.pool_backing_file,
            pool_name,
        )


@qubes.tests.storage_zfs.skip_unless_zfs_available
class StorageZFS(StorageZFSMixin, qubes.tests.SystemTestCase):
    pass
