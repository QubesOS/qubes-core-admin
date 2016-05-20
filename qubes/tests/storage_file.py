# The Qubes OS Project, https://www.qubes-os.org/
#
# Copyright (C) 2015  Bahtiar `kalkin-` Gadimov <bahtiar@gadimov.de>
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

import os
import shutil

import qubes.storage
import qubes.tests.storage
from qubes.config import defaults
from qubes.storage import Storage
from qubes.storage.file import (OriginFile, ReadOnlyFile, ReadWriteFile,
                                SnapshotFile, VolatileFile)
from qubes.tests import QubesTestCase, SystemTestsMixin
from qubes.tests.storage import TestVM

# :pylint: disable=invalid-name


class TC_00_FilePool(SystemTestsMixin, QubesTestCase):
    """ This class tests some properties of the 'default' pool. """

    def test000_default_pool_dir(self):
        """ The predefined dir for the default pool should be ``/var/lib/qubes``

            .. sealso::
               Data :data:``qubes.qubes.defaults['pool_config']``.
        """
        result = self.app.get_pool("default").dir_path
        expected = '/var/lib/qubes'
        self.assertEquals(result, expected)

    def test001_default_storage_class(self):
        """ Check when using default pool the Storage is ``Storage``. """
        result = self._init_app_vm().storage
        self.assertIsInstance(result, Storage)

    def _init_app_vm(self):
        """ Return initalised, but not created, AppVm. """
        vmname = self.make_vm_name('appvm')
        self.init_default_template()
        return self.app.add_new_vm(qubes.vm.appvm.AppVM,
                                   name=vmname,
                                   template=self.app.default_template,
                                   label='red')


class TC_01_FileVolumes(SystemTestsMixin, QubesTestCase):
    POOL_DIR = '/var/lib/qubes/test-pool'
    POOL_NAME = 'test-pool'
    POOL_CONF = {'driver': 'file', 'dir_path': POOL_DIR, 'name': POOL_NAME}

    def setUp(self):
        """ Add a test file based storage pool """
        super(TC_01_FileVolumes, self).setUp()
        self.init_default_template()
        self.app.add_pool(**self.POOL_CONF)

    def tearDown(self):
        """ Remove the file based storage pool after testing """
        self.app.remove_pool("test-pool")
        super(TC_01_FileVolumes, self).tearDown()
        shutil.rmtree(self.POOL_DIR, ignore_errors=True)

    def test_000_origin_volume(self):
        config = {
            'name': 'root',
            'pool': self.POOL_NAME,
            'volume_type': 'origin',
            'size': defaults['root_img_size'],
        }
        vm = TestVM(self)
        result = self.app.get_pool(self.POOL_NAME).init_volume(vm, config)
        self.assertIsInstance(result, OriginFile)
        self.assertEqual(result.name, 'root')
        self.assertEqual(result.pool, self.POOL_NAME)
        self.assertEqual(result.size, defaults['root_img_size'])

    def test_001_snapshot_volume(self):
        original_path = '/var/lib/qubes/vm-templates/fedora-23/root.img'
        original_size = qubes.config.defaults['root_img_size']
        config = {
            'name': 'root',
            'pool': 'default',
            'volume_type': 'snapshot',
            'vid': original_path,
        }
        vm = TestVM(self, template=self.app.default_template)
        result = self.app.get_pool(self.POOL_NAME).init_volume(vm, config)
        self.assertIsInstance(result, SnapshotFile)
        self.assertEqual(result.name, 'root')
        self.assertEqual(result.pool, 'default')
        self.assertEqual(result.size, original_size)

    def test_002_read_write_volume(self):
        config = {
            'name': 'root',
            'pool': self.POOL_NAME,
            'volume_type': 'read-write',
            'size': defaults['root_img_size'],
        }
        vm = TestVM(self)
        result = self.app.get_pool(self.POOL_NAME).init_volume(vm, config)
        self.assertIsInstance(result, ReadWriteFile)
        self.assertEqual(result.name, 'root')
        self.assertEqual(result.pool, self.POOL_NAME)
        self.assertEqual(result.size, defaults['root_img_size'])

    def test_003_read_volume(self):
        template = self.app.default_template
        original_path = template.volumes['root'].vid
        original_size = qubes.config.defaults['root_img_size']
        config = {
            'name': 'root',
            'pool': 'default',
            'volume_type': 'read-only',
            'vid': original_path
        }
        vm = TestVM(self, template=template)

        result = self.app.get_pool(self.POOL_NAME).init_volume(vm, config)
        self.assertIsInstance(result, ReadOnlyFile)
        self.assertEqual(result.name, 'root')
        self.assertEqual(result.pool, 'default')
        self.assertEqual(result.size, original_size)

    def test_004_volatile_volume(self):
        config = {
            'name': 'root',
            'pool': self.POOL_NAME,
            'volume_type': 'volatile',
            'size': defaults['root_img_size'],
        }
        vm = TestVM(self)
        result = self.app.get_pool(self.POOL_NAME).init_volume(vm, config)
        self.assertIsInstance(result, VolatileFile)
        self.assertEqual(result.name, 'root')
        self.assertEqual(result.pool, self.POOL_NAME)
        self.assertEqual(result.size, defaults['root_img_size'])

    def test_005_appvm_volumes(self):
        ''' Check if AppVM volumes are propertly initialized '''
        vmname = self.make_vm_name('appvm')
        vm = self.app.add_new_vm(qubes.vm.appvm.AppVM,
                                 name=vmname,
                                 template=self.app.default_template,
                                 label='red')

        volumes = vm.volumes
        self.assertIsInstance(volumes['root'], SnapshotFile)
        self.assertIsInstance(volumes['private'], OriginFile)
        self.assertIsInstance(volumes['volatile'], VolatileFile)
        expected = vm.template.dir_path + '/root.img:' + vm.template.dir_path \
            + '/root-cow.img'
        self.assertVolumePath(vm, 'root', expected, rw=False)
        expected = vm.dir_path + '/private.img:' + \
            vm.dir_path + '/private-cow.img'
        self.assertVolumePath(vm, 'private', expected, rw=True)
        expected = vm.dir_path + '/volatile.img'
        self.assertVolumePath(vm, 'volatile', expected, rw=True)

    def test_006_template_volumes(self):
        ''' Check if TemplateVM volumes are propertly initialized '''
        vmname = self.make_vm_name('appvm')
        vm = self.app.add_new_vm(qubes.vm.templatevm.TemplateVM,
                                 name=vmname,
                                 label='red')

        volumes = vm.volumes
        self.assertIsInstance(volumes['root'], OriginFile)
        self.assertIsInstance(volumes['private'], ReadWriteFile)
        self.assertIsInstance(volumes['volatile'], VolatileFile)
        expected = vm.dir_path + '/root.img:' + vm.dir_path + '/root-cow.img'
        self.assertVolumePath(vm, 'root', expected, rw=True)
        expected = vm.dir_path + '/private.img'
        self.assertVolumePath(vm, 'private', expected, rw=True)
        expected = vm.dir_path + '/volatile.img'
        self.assertVolumePath(vm, 'volatile', expected, rw=True)

    def assertVolumePath(self, vm, dev_name, expected, rw=True):
        # :pylint: disable=invalid-name
        volumes = vm.volumes
        b_dev = volumes[dev_name].block_device()
        self.assertEqual(b_dev.rw, rw)
        self.assertEquals(b_dev.path, expected)


@qubes.tests.skipUnlessDom0
class TC_03_FilePool(SystemTestsMixin, QubesTestCase):
    """ Test the paths for the default file based pool (``FilePool``).
    """

    POOL_DIR = '/var/lib/qubes/test-pool'
    APPVMS_DIR = '/var/lib/qubes/test-pool/appvms'
    TEMPLATES_DIR = '/var/lib/qubes/test-pool/vm-templates'
    SERVICE_DIR = '/var/lib/qubes/test-pool/servicevms'
    POOL_NAME = 'test-pool'
    POOL_CONFIG = {'driver': 'file', 'dir_path': POOL_DIR, 'name': POOL_NAME}

    def setUp(self):
        """ Add a test file based storage pool """
        super(TC_03_FilePool, self).setUp()
        self.init_default_template()
        self.app.add_pool(**self.POOL_CONFIG)

    def tearDown(self):
        """ Remove the file based storage pool after testing """
        self.app.remove_pool("test-pool")
        super(TC_03_FilePool, self).tearDown()
        shutil.rmtree(self.POOL_DIR, ignore_errors=True)

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

    def test_011_appvm_file_images(self):
        """ Check if all the needed image files are created for an AppVm"""

        vmname = self.make_vm_name('appvm')
        vm = self.app.add_new_vm(qubes.vm.appvm.AppVM,
                                 name=vmname,
                                 template=self.app.default_template,
                                 volume_config={
                                     'private': {
                                         'pool': 'test-pool'
                                     },
                                     'volatile': {
                                         'pool': 'test-pool'
                                     }
                                 },
                                 label='red')
        vm.storage.create_on_disk()

        expected_vmdir = os.path.join(self.APPVMS_DIR, vm.name)

        expected_private_origin_path = \
            os.path.join(expected_vmdir, 'private.img')
        expected_private_cow_path = \
            os.path.join(expected_vmdir, 'private-cow.img')
        expected_private_path = '%s:%s' % (expected_private_origin_path,
                                        expected_private_cow_path)
        self.assertEquals(vm.volumes['private'].path, expected_private_path)
        self.assertEqualsAndExists(vm.volumes['private'].path_origin,
            expected_private_origin_path)
        self.assertEqualsAndExists(vm.volumes['private'].path_cow,
            expected_private_cow_path)

        expected_volatile_path = os.path.join(expected_vmdir, 'volatile.img')
        self.assertEqualsAndExists(vm.volumes['volatile'].path,
                                   expected_volatile_path)

    def test_013_template_file_images(self):
        """ Check if root.img, private.img, volatile.img and root-cow.img are
            created propertly by the storage system
        """
        vmname = self.make_vm_name('tmvm')
        vm = self.app.add_new_vm(qubes.vm.templatevm.TemplateVM,
                                 name=vmname,
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
                                 },
                                 label='red')
        vm.create_on_disk()

        expected_vmdir = os.path.join(self.TEMPLATES_DIR, vm.name)

        expected_root_origin_path = os.path.join(expected_vmdir, 'root.img')
        expected_root_cow_path = os.path.join(expected_vmdir, 'root-cow.img')
        expected_root_path = '%s:%s' % (expected_root_origin_path,
                                        expected_root_cow_path)
        self.assertEquals(vm.volumes['root'].path, expected_root_path)
        self.assertExist(vm.volumes['root'].path_origin)

        expected_private_path = os.path.join(expected_vmdir, 'private.img')
        self.assertEqualsAndExists(vm.volumes['private'].path,
                                   expected_private_path)

        expected_volatile_path = os.path.join(expected_vmdir, 'volatile.img')
        self.assertEqualsAndExists(vm.volumes['volatile'].path,
                                   expected_volatile_path)

        vm.storage.commit_template_changes()
        expected_rootcow_path = os.path.join(expected_vmdir, 'root-cow.img')
        self.assertEqualsAndExists(vm.volumes['root'].path_cow,
                                   expected_rootcow_path)

    def assertEqualsAndExists(self, result_path, expected_path):
        """ Check if the ``result_path``, matches ``expected_path`` and exists.

            See also: :meth:``assertExist``
        """
        # :pylint: disable=invalid-name
        self.assertEquals(result_path, expected_path)
        self.assertExist(result_path)

    def assertExist(self, path):
        """ Assert that the given path exists. """
        # :pylint: disable=invalid-name
        self.assertTrue(os.path.exists(path), "Path %s does not exist" % path)
