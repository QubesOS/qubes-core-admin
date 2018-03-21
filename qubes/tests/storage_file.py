#
# The Qubes OS Project, https://www.qubes-os.org/
#
# Copyright (C) 2015  Bahtiar `kalkin-` Gadimov <bahtiar@gadimov.de>
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

''' Tests for the file storage backend '''

import os
import shutil

import asyncio
import unittest.mock

import qubes.storage
import qubes.tests.storage
from qubes.config import defaults

# :pylint: disable=invalid-name


class TestApp(qubes.Qubes):
    ''' A Mock App object '''
    def __init__(self, *args, **kwargs):  # pylint: disable=unused-argument
        super(TestApp, self).__init__('/tmp/qubes-test.xml', load=False,
                                      offline_mode=True, **kwargs)
        self.load_initial_values()
        self.pools['linux-kernel'].dir_path = '/tmp/qubes-test-kernel'
        dummy_kernel = os.path.join(self.pools['linux-kernel'].dir_path,
                                    'dummy')
        os.makedirs(dummy_kernel, exist_ok=True)
        open(os.path.join(dummy_kernel, 'vmlinuz'), 'w').close()
        open(os.path.join(dummy_kernel, 'modules.img'), 'w').close()
        open(os.path.join(dummy_kernel, 'initramfs'), 'w').close()
        self.default_kernel = 'dummy'

    def cleanup(self):
        ''' Remove temporary directories '''
        shutil.rmtree(self.pools['linux-kernel'].dir_path)
        if os.path.exists(self.store):
            os.unlink(self.store)

    def create_dummy_template(self):
        ''' Initalizes a dummy TemplateVM as the `default_template` '''
        template = self.add_new_vm(qubes.vm.templatevm.TemplateVM,
                                   name='test-template', label='red',
                                   memory=1024, maxmem=1024)
        self.default_template = template


class TC_00_FilePool(qubes.tests.QubesTestCase):
    """ This class tests some properties of the 'default' pool.

        This test might become obsolete if we change the driver for the default
        pool to something else as 'file'.
    """

    def setUp(self):
        super(TC_00_FilePool, self).setUp()
        self.app = TestApp()

    def tearDown(self):
        self.app.cleanup()
        self.app.close()
        del self.app
        super(TC_00_FilePool, self).tearDown()

    def test000_default_pool_dir(self):
        """ The predefined dir for the default pool should be ``/var/lib/qubes``

            .. sealso::
               Data :data:``qubes.qubes.defaults['pool_config']``.
        """
        result = self.app.get_pool("varlibqubes").dir_path
        expected = '/var/lib/qubes'
        self.assertEqual(result, expected)

    def test001_default_storage_class(self):
        """ Check when using default pool the Storage is
            ``qubes.storage.Storage``. """
        result = self._init_app_vm().storage
        self.assertIsInstance(result, qubes.storage.Storage)

    def _init_app_vm(self):
        """ Return initalised, but not created, AppVm. """
        vmname = self.make_vm_name('appvm')
        self.app.create_dummy_template()
        return self.app.add_new_vm(qubes.vm.appvm.AppVM, name=vmname,
                                   template=self.app.default_template,
                                   label='red')


class TC_01_FileVolumes(qubes.tests.QubesTestCase):
    ''' Test correct handling of different types of volumes '''

    POOL_DIR = '/tmp/test-pool'
    POOL_NAME = 'test-pool'
    POOL_CONF = {'driver': 'file', 'dir_path': POOL_DIR, 'name': POOL_NAME}

    def setUp(self):
        """ Add a test file based storage pool """
        super(TC_01_FileVolumes, self).setUp()
        self.app = TestApp()
        self.app.add_pool(**self.POOL_CONF)
        self.app.default_pool = self.app.get_pool(self.POOL_NAME)
        self.app.create_dummy_template()

    def tearDown(self):
        """ Remove the file based storage pool after testing """
        self.app.remove_pool("test-pool")
        self.app.cleanup()
        self.app.close()
        del self.app
        super(TC_01_FileVolumes, self).tearDown()
        shutil.rmtree(self.POOL_DIR, ignore_errors=True)

    def test_000_origin_volume(self):
        config = {
            'name': 'root',
            'pool': self.POOL_NAME,
            'save_on_stop': True,
            'rw': True,
            'size': defaults['root_img_size'],
        }
        vm = qubes.tests.storage.TestVM(self)
        volume = self.app.get_pool(self.POOL_NAME).init_volume(vm, config)
        self.assertEqual(volume.name, 'root')
        self.assertEqual(volume.pool, self.POOL_NAME)
        self.assertEqual(volume.size, defaults['root_img_size'])
        self.assertFalse(volume.snap_on_start)
        self.assertTrue(volume.save_on_stop)
        self.assertTrue(volume.rw)
        block = volume.block_device()
        self.assertEqual(block.path,
            '{base}.img:{base}-cow.img'.format(
                base=self.POOL_DIR + '/appvms/' + vm.name + '/root'))
        self.assertEqual(block.script, 'block-origin')
        self.assertEqual(block.rw, True)
        self.assertEqual(block.name, 'root')
        self.assertEqual(block.devtype, 'disk')
        self.assertIsNone(block.domain)

    def test_001_snapshot_volume(self):
        template_vm = self.app.default_template
        vm = qubes.tests.storage.TestVM(self, template=template_vm)

        original_size = qubes.config.defaults['root_img_size']
        source_config = {
            'name': 'root',
            'pool': self.POOL_NAME,
            'save_on_stop': True,
            'rw': False,
            'size': original_size,
        }
        source = self.app.get_pool(self.POOL_NAME).init_volume(template_vm,
            source_config)
        config = {
            'name': 'root',
            'pool': self.POOL_NAME,
            'snap_on_start': True,
            'rw': False,
            'source': source,
            'size': original_size,
        }

        volume = self.app.get_pool(self.POOL_NAME).init_volume(vm, config)
        self.assertEqual(volume.name, 'root')
        self.assertEqual(volume.pool, self.POOL_NAME)
        self.assertEqual(volume.size, original_size)
        self.assertTrue(volume.snap_on_start)
        self.assertTrue(volume.snap_on_start)
        self.assertFalse(volume.save_on_stop)
        self.assertFalse(volume.rw)
        self.assertEqual(volume.usage, 0)
        block = volume.block_device()
        assert isinstance(block, qubes.storage.BlockDevice)
        self.assertEqual(block.path,
            '{base}/{src}.img:{base}/{src}-cow.img:'
            '{base}/{dst}-cow.img'.format(
                base=self.POOL_DIR,
                src='vm-templates/' + template_vm.name + '/root',
                dst='appvms/' + vm.name + '/root',
        ))
        self.assertEqual(block.name, 'root')
        self.assertEqual(block.script, 'block-snapshot')
        self.assertEqual(block.rw, False)
        self.assertEqual(block.devtype, 'disk')

    def test_002_read_write_volume(self):
        config = {
            'name': 'root',
            'pool': self.POOL_NAME,
            'rw': True,
            'save_on_stop': True,
            'size': defaults['root_img_size'],
        }
        vm = qubes.tests.storage.TestVM(self)
        volume = self.app.get_pool(self.POOL_NAME).init_volume(vm, config)
        self.assertEqual(volume.name, 'root')
        self.assertEqual(volume.pool, self.POOL_NAME)
        self.assertEqual(volume.size, defaults['root_img_size'])
        self.assertFalse(volume.snap_on_start)
        self.assertTrue(volume.save_on_stop)
        self.assertTrue(volume.rw)
        block = volume.block_device()
        self.assertEqual(block.name, 'root')
        self.assertEqual(block.path, '{base}.img:{base}-cow.img'.format(
            base=self.POOL_DIR + '/appvms/' + vm.name + '/root'))
        self.assertEqual(block.rw, True)
        self.assertEqual(block.script, 'block-origin')

    def test_003_read_only_volume(self):
        template = self.app.default_template
        vid = template.volumes['root'].vid
        config = {
            'name': 'root',
            'pool': self.POOL_NAME,
            'rw': False,
            'vid': vid,
        }
        vm = qubes.tests.storage.TestVM(self, template=template)

        volume = self.app.get_pool(self.POOL_NAME).init_volume(vm, config)
        self.assertEqual(volume.name, 'root')
        self.assertEqual(volume.pool, self.POOL_NAME)

        # original_size = qubes.config.defaults['root_img_size']
        # FIXME: self.assertEqual(volume.size, original_size)
        self.assertFalse(volume.snap_on_start)
        self.assertFalse(volume.save_on_stop)
        self.assertFalse(volume.rw)
        block = volume.block_device()
        self.assertEqual(block.rw, False)

    def test_004_volatile_volume(self):
        config = {
            'name': 'root',
            'pool': self.POOL_NAME,
            'size': defaults['root_img_size'],
            'rw': True,
        }
        vm = qubes.tests.storage.TestVM(self)
        volume = self.app.get_pool(self.POOL_NAME).init_volume(vm, config)
        self.assertEqual(volume.name, 'root')
        self.assertEqual(volume.pool, self.POOL_NAME)
        self.assertEqual(volume.size, defaults['root_img_size'])
        self.assertFalse(volume.snap_on_start)
        self.assertFalse(volume.save_on_stop)
        self.assertTrue(volume.rw)

    def test_005_appvm_volumes(self):
        ''' Check if AppVM volumes are propertly initialized '''
        vmname = self.make_vm_name('appvm')
        vm = self.app.add_new_vm(qubes.vm.appvm.AppVM, name=vmname,
                                 template=self.app.default_template,
                                 label='red')

        template_dir = os.path.join(self.POOL_DIR, 'vm-templates',
            vm.template.name)
        vm_dir = os.path.join(self.POOL_DIR, 'appvms', vmname)
        expected = template_dir + '/root.img:' + \
                   template_dir + '/root-cow.img:' + \
                   vm_dir + '/root-cow.img'
        self.assertVolumePath(vm, 'root', expected, rw=True)
        expected = vm_dir + '/private.img:' + \
            vm_dir + '/private-cow.img'
        self.assertVolumePath(vm, 'private', expected, rw=True)
        expected = vm_dir + '/volatile.img'
        self.assertVolumePath(vm, 'volatile', expected, rw=True)

    def test_006_template_volumes(self):
        ''' Check if TemplateVM volumes are propertly initialized '''
        vmname = self.make_vm_name('appvm')
        vm = self.app.add_new_vm(qubes.vm.templatevm.TemplateVM, name=vmname,
                                 label='red')

        vm_dir = os.path.join(self.POOL_DIR, 'vm-templates', vmname)
        expected = vm_dir + '/root.img:' + vm_dir + '/root-cow.img'
        self.assertVolumePath(vm, 'root', expected, rw=True)
        expected = vm_dir + '/private.img:' + \
                   vm_dir + '/private-cow.img'
        self.assertVolumePath(vm, 'private', expected, rw=True)
        expected = vm_dir + '/volatile.img'
        self.assertVolumePath(vm, 'volatile', expected, rw=True)

    def test_010_revisions_to_keep_reject_invalid(self):
        ''' Check if TemplateVM volumes are propertly initialized '''
        config = {
            'name': 'root',
            'pool': self.POOL_NAME,
            'save_on_stop': True,
            'rw': True,
            'size': defaults['root_img_size'],
        }
        vm = qubes.tests.storage.TestVM(self)
        volume = self.app.get_pool(self.POOL_NAME).init_volume(vm, config)
        self.assertEqual(volume.revisions_to_keep, 1)
        with self.assertRaises((NotImplementedError, ValueError)):
            volume.revisions_to_keep = 2
        self.assertEqual(volume.revisions_to_keep, 1)

    def test_020_import_data(self):
        config = {
            'name': 'root',
            'pool': self.POOL_NAME,
            'save_on_stop': True,
            'rw': True,
            'size': 1024 * 1024,
        }
        vm = qubes.tests.storage.TestVM(self)
        volume = self.app.get_pool(self.POOL_NAME).init_volume(vm, config)
        volume.create()
        import_path = volume.import_data()
        self.assertNotEqual(volume.path, import_path)
        with open(import_path, 'w+') as import_file:
            import_file.write('test')
        volume.import_data_end(True)
        self.assertFalse(os.path.exists(import_path), import_path)
        with open(volume.path) as volume_file:
            volume_data = volume_file.read().strip('\0')
        self.assertEqual(volume_data, 'test')

    def test_021_import_data_fail(self):
        config = {
            'name': 'root',
            'pool': self.POOL_NAME,
            'save_on_stop': True,
            'rw': True,
            'size': 1024 * 1024,
        }
        vm = qubes.tests.storage.TestVM(self)
        volume = self.app.get_pool(self.POOL_NAME).init_volume(vm, config)
        volume.create()
        import_path = volume.import_data()
        self.assertNotEqual(volume.path, import_path)
        with open(import_path, 'w+') as import_file:
            import_file.write('test')
        volume.import_data_end(False)
        self.assertFalse(os.path.exists(import_path), import_path)
        with open(volume.path) as volume_file:
            volume_data = volume_file.read().strip('\0')
        self.assertNotEqual(volume_data, 'test')

    def assertVolumePath(self, vm, dev_name, expected, rw=True):
        # :pylint: disable=invalid-name
        volumes = vm.volumes
        b_dev = volumes[dev_name].block_device()
        self.assertEqual(b_dev.rw, rw)
        self.assertEqual(b_dev.path, expected)


class TC_03_FilePool(qubes.tests.QubesTestCase):
    """ Test the paths for the default file based pool (``FilePool``).
    """

    POOL_DIR = '/tmp/test-pool'
    APPVMS_DIR = '/tmp/test-pool/appvms'
    TEMPLATES_DIR = '/tmp/test-pool/vm-templates'
    SERVICE_DIR = '/tmp/test-pool/servicevms'
    POOL_NAME = 'test-pool'
    POOL_CONFIG = {'driver': 'file', 'dir_path': POOL_DIR, 'name': POOL_NAME}

    def setUp(self):
        """ Add a test file based storage pool """
        super(TC_03_FilePool, self).setUp()
        self.test_base_dir = '/tmp/qubes-test-dir'
        self.base_dir_patch = unittest.mock.patch.dict(qubes.config.system_path,
            {'qubes_base_dir': self.test_base_dir})
        self.base_dir_patch2 = unittest.mock.patch(
            'qubes.config.qubes_base_dir', self.test_base_dir)
        self.base_dir_patch3 = unittest.mock.patch.dict(
            qubes.config.defaults['pool_configs']['varlibqubes'],
            {'dir_path': self.test_base_dir})
        self.base_dir_patch.start()
        self.base_dir_patch2.start()
        self.base_dir_patch3.start()
        self.app = TestApp()
        self.app.add_pool(**self.POOL_CONFIG)
        self.app.create_dummy_template()

    def tearDown(self):
        """ Remove the file based storage pool after testing """
        self.app.remove_pool("test-pool")
        self.app.cleanup()
        self.app.close()
        del self.app
        self.base_dir_patch3.stop()
        self.base_dir_patch2.stop()
        self.base_dir_patch.stop()
        super(TC_03_FilePool, self).tearDown()
        shutil.rmtree(self.POOL_DIR, ignore_errors=True)
        if os.path.exists('/tmp/qubes-test-dir'):
            shutil.rmtree('/tmp/qubes-test-dir')

    def test_001_pool_exists(self):
        """ Check if the storage pool was added to the storage pool config """
        self.assertIn('test-pool', self.app.pools.keys())

    def test_002_pool_dir_create(self):
        """ Check if the storage pool dir and subdirs were created """
        # The dir should not exists before
        pool_name = 'foo'
        pool_dir = '/tmp/foo'
        appvms_dir = '/tmp/foo/appvms'
        templates_dir = '/tmp/foo/vm-templates'

        self.assertFalse(os.path.exists(pool_dir))

        self.app.add_pool(name=pool_name, dir_path=pool_dir, driver='file')

        self.assertTrue(os.path.exists(pool_dir))
        self.assertTrue(os.path.exists(appvms_dir))
        self.assertTrue(os.path.exists(templates_dir))

        shutil.rmtree(pool_dir, ignore_errors=True)

    def test_003_size(self):
        pool = self.app.get_pool(self.POOL_NAME)
        with self.assertNotRaises(NotImplementedError):
            size = pool.size
        statvfs = os.statvfs(self.POOL_DIR)
        self.assertEqual(size, statvfs.f_blocks * statvfs.f_frsize)

    def test_004_usage(self):
        pool = self.app.get_pool(self.POOL_NAME)
        with self.assertNotRaises(NotImplementedError):
            usage = pool.usage
        statvfs = os.statvfs(self.POOL_DIR)
        self.assertEqual(usage,
            statvfs.f_frsize * (statvfs.f_blocks - statvfs.f_bfree))

    def test_005_revisions_to_keep(self):
        pool = self.app.get_pool(self.POOL_NAME)
        self.assertEqual(pool.revisions_to_keep, 1)
        with self.assertRaises((NotImplementedError, ValueError)):
            pool.revisions_to_keep = 2
        self.assertEqual(pool.revisions_to_keep, 1)

    def test_011_appvm_file_images(self):
        """ Check if all the needed image files are created for an AppVm"""

        vmname = self.make_vm_name('appvm')
        vm = self.app.add_new_vm(qubes.vm.appvm.AppVM, name=vmname,
                                 template=self.app.default_template,
                                 volume_config={
                                     'private': {
                                         'pool': 'test-pool'
                                     },
                                     'volatile': {
                                         'pool': 'test-pool'
                                     }
                                 }, label='red')
        loop = asyncio.get_event_loop()
        loop.run_until_complete(vm.create_on_disk())

        expected_vmdir = os.path.join(self.APPVMS_DIR, vm.name)

        expected_private_path = os.path.join(expected_vmdir, 'private.img')
        self.assertEqual(vm.volumes['private'].path, expected_private_path)

        expected_volatile_path = os.path.join(expected_vmdir, 'volatile.img')
        vm.volumes['volatile'].reset()
        self.assertEqualAndExists(vm.volumes['volatile'].path,
                                  expected_volatile_path)

    def test_013_template_file_images(self):
        """ Check if root.img, private.img, volatile.img and root-cow.img are
            created propertly by the storage system
        """
        vmname = self.make_vm_name('tmvm')
        vm = self.app.add_new_vm(qubes.vm.templatevm.TemplateVM, name=vmname,
                                 volume_config={
                                     'root': {
                                         'pool': 'test-pool'
                                     },
                                     'private': {
                                         'pool': 'test-pool'
                                     },
                                     'volatile': {
                                         'pool': 'test-pool'
                                     }
                                 }, label='red')
        loop = asyncio.get_event_loop()
        loop.run_until_complete(vm.create_on_disk())

        expected_vmdir = os.path.join(self.TEMPLATES_DIR, vm.name)

        expected_root_origin_path = os.path.join(expected_vmdir, 'root.img')
        expected_root_cow_path = os.path.join(expected_vmdir, 'root-cow.img')
        expected_root_path = '%s:%s' % (expected_root_origin_path,
                                        expected_root_cow_path)
        self.assertEqual(vm.volumes['root'].block_device().path,
                          expected_root_path)
        self.assertExist(vm.volumes['root'].path)

        expected_private_path = os.path.join(expected_vmdir, 'private.img')
        self.assertEqualAndExists(vm.volumes['private'].path,
                                   expected_private_path)

        expected_rootcow_path = os.path.join(expected_vmdir, 'root-cow.img')
        self.assertEqual(vm.volumes['root'].path_cow, expected_rootcow_path)

    def assertEqualAndExists(self, result_path, expected_path):
        """ Check if the ``result_path``, matches ``expected_path`` and exists.

            See also: :meth:``assertExist``
        """
        # :pylint: disable=invalid-name
        self.assertEqual(result_path, expected_path)
        self.assertExist(result_path)

    def assertExist(self, path):
        """ Assert that the given path exists. """
        # :pylint: disable=invalid-name
        self.assertTrue(
            os.path.exists(path), "Path {!s} does not exist".format(path))
