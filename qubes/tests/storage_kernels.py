# -*- encoding: utf8 -*-
#
# The Qubes OS Project, http://www.qubes-os.org
#
# Copyright (C) 2017 Marek Marczykowski-Górecki
#                               <marmarek@invisiblethingslab.com>
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
# with this program; if not, see <http://www.gnu.org/licenses/>.

''' Tests for the kernels storage backend '''

import os
import shutil

import asyncio

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
        os.makedirs(dummy_kernel)
        open(os.path.join(dummy_kernel, 'vmlinuz'), 'w').close()
        open(os.path.join(dummy_kernel, 'modules.img'), 'w').close()
        open(os.path.join(dummy_kernel, 'initramfs'), 'w').close()
        self.default_kernel = 'dummy'

    def cleanup(self):
        ''' Remove temporary directories '''
        shutil.rmtree(self.pools['linux-kernel'].dir_path)

    def create_dummy_template(self):
        ''' Initalizes a dummy TemplateVM as the `default_template` '''
        template = self.add_new_vm(qubes.vm.templatevm.TemplateVM,
                                   name='test-template', label='red',
                                   memory=1024, maxmem=1024)
        self.default_template = template




class TC_01_KernelVolumes(qubes.tests.QubesTestCase):
    ''' Test correct handling of different types of volumes '''

    POOL_DIR = '/tmp/test-pool'
    POOL_NAME = 'test-pool'
    POOL_CONF = {'driver': 'linux-kernel', 'dir_path': POOL_DIR, 'name':
        POOL_NAME}

    def setUp(self):
        """ Add a test file based storage pool """
        super(TC_01_KernelVolumes, self).setUp()
        self.app = TestApp()
        self.app.create_dummy_template()
        self.app.add_pool(**self.POOL_CONF)

    def tearDown(self):
        """ Remove the file based storage pool after testing """
        self.app.remove_pool("test-pool")
        self.app.cleanup()
        super(TC_01_KernelVolumes, self).tearDown()
        shutil.rmtree(self.POOL_DIR, ignore_errors=True)

    def test_000_reject_rw(self):
        config = {
            'name': 'root',
            'pool': self.POOL_NAME,
            'save_on_stop': True,
            'rw': True,
        }
        vm = qubes.tests.storage.TestVM(self)
        vm.kernel = 'dummy'
        with self.assertRaises(AssertionError):
            self.app.get_pool(self.POOL_NAME).init_volume(vm, config)

    def test_001_simple_volume(self):
        config = {
            'name': 'kernel',
            'pool': self.POOL_NAME,
            'rw': False,
        }

        template_vm = self.app.default_template
        vm = qubes.tests.storage.TestVM(self, template=template_vm)
        vm.kernel = 'dummy'
        volume = self.app.get_pool(self.POOL_NAME).init_volume(vm, config)
        self.assertEqual(volume.name, 'kernel')
        self.assertEqual(volume.pool, self.POOL_NAME)
        self.assertFalse(volume.snap_on_start)
        self.assertFalse(volume.save_on_stop)
        self.assertFalse(volume.rw)
        self.assertEqual(volume.usage, 0)
        expected_path = '/tmp/test-pool/dummy/modules.img'
        self.assertEqual(volume.path, expected_path)
        block_dev = volume.block_device()
        self.assertIsInstance(block_dev, qubes.storage.BlockDevice)
        self.assertEqual(block_dev.devtype, 'disk')
        self.assertEqual(block_dev.path, expected_path)
        self.assertEqual(block_dev.name, 'kernel')

    def test_002_follow_kernel_change(self):
        config = {
            'name': 'kernel',
            'pool': self.POOL_NAME,
            'rw': False,
        }

        template_vm = self.app.default_template
        vm = qubes.tests.storage.TestVM(self, template=template_vm)
        vm.kernel = 'dummy'
        volume = self.app.get_pool(self.POOL_NAME).init_volume(vm, config)
        self.assertEqual(volume.name, 'kernel')
        self.assertEqual(volume.pool, self.POOL_NAME)
        self.assertEqual(volume.path, '/tmp/test-pool/dummy/modules.img')
        vm.kernel = 'updated'
        self.assertEqual(volume.path, '/tmp/test-pool/updated/modules.img')

    def test_003_kernel_none(self):
        config = {
            'name': 'kernel',
            'pool': self.POOL_NAME,
            'rw': False,
        }

        template_vm = self.app.default_template
        vm = qubes.tests.storage.TestVM(self, template=template_vm)
        vm.kernel = None
        volume = self.app.get_pool(self.POOL_NAME).init_volume(vm, config)
        self.assertEqual(volume.name, 'kernel')
        self.assertEqual(volume.pool, self.POOL_NAME)
        self.assertFalse(volume.snap_on_start)
        self.assertFalse(volume.save_on_stop)
        self.assertFalse(volume.rw)
        self.assertEqual(volume.usage, 0)
        self.assertIsNone(volume.path)
        self.assertIsNone(volume.vid)
        block_dev = volume.block_device()
        self.assertIsNone(block_dev)

    def test_004_kernel_none_change(self):
        config = {
            'name': 'kernel',
            'pool': self.POOL_NAME,
            'rw': False,
        }

        template_vm = self.app.default_template
        vm = qubes.tests.storage.TestVM(self, template=template_vm)
        vm.kernel = None
        volume = self.app.get_pool(self.POOL_NAME).init_volume(vm, config)
        self.assertIsNone(volume.path)
        self.assertIsNone(volume.vid)
        block_dev = volume.block_device()
        self.assertIsNone(block_dev)
        vm.kernel = 'dummy'
        expected_path = '/tmp/test-pool/dummy/modules.img'
        self.assertEqual(volume.path, expected_path)
        block_dev = volume.block_device()
        self.assertIsInstance(block_dev, qubes.storage.BlockDevice)
        self.assertEqual(block_dev.devtype, 'disk')
        self.assertEqual(block_dev.path, expected_path)
        self.assertEqual(block_dev.name, 'kernel')

    def test_005_kernel_none_change(self):
        config = {
            'name': 'kernel',
            'pool': self.POOL_NAME,
            'rw': False,
        }

        template_vm = self.app.default_template
        vm = qubes.tests.storage.TestVM(self, template=template_vm)
        vm.kernel = 'dummy'
        volume = self.app.get_pool(self.POOL_NAME).init_volume(vm, config)
        expected_path = '/tmp/test-pool/dummy/modules.img'
        self.assertEqual(volume.path, expected_path)
        block_dev = volume.block_device()
        self.assertIsInstance(block_dev, qubes.storage.BlockDevice)
        self.assertEqual(block_dev.devtype, 'disk')
        self.assertEqual(block_dev.path, expected_path)
        self.assertEqual(block_dev.name, 'kernel')
        vm.kernel = None
        self.assertIsNone(volume.path)
        self.assertIsNone(volume.vid)
        block_dev = volume.block_device()
        self.assertIsNone(block_dev)


class TC_03_KernelPool(qubes.tests.QubesTestCase):
    """ Test the paths for the default file based pool (``FilePool``).
    """

    POOL_DIR = '/tmp/test-pool'
    POOL_NAME = 'test-pool'
    POOL_CONFIG = {'driver': 'linux-kernel', 'dir_path': POOL_DIR, 'name':
        POOL_NAME}

    def setUp(self):
        """ Add a test file based storage pool """
        super(TC_03_KernelPool, self).setUp()
        self.app = TestApp()
        self.app.create_dummy_template()
        dummy_kernel = os.path.join(self.POOL_DIR, 'dummy')
        os.makedirs(dummy_kernel)
        open(os.path.join(dummy_kernel, 'vmlinuz'), 'w').close()
        open(os.path.join(dummy_kernel, 'modules.img'), 'w').close()
        open(os.path.join(dummy_kernel, 'initramfs'), 'w').close()
        self.app.add_pool(**self.POOL_CONFIG)

    def tearDown(self):
        """ Remove the file based storage pool after testing """
        self.app.remove_pool("test-pool")
        self.app.cleanup()
        super(TC_03_KernelPool, self).tearDown()
        shutil.rmtree(self.POOL_DIR, ignore_errors=True)
        if os.path.exists('/tmp/qubes-test'):
            shutil.rmtree('/tmp/qubes-test')

    def test_001_pool_exists(self):
        """ Check if the storage pool was added to the storage pool config """
        self.assertIn('test-pool', self.app.pools.keys())

    def test_002_pool_volumes(self):
        """ List volumes """
        volumes = self.app.pools[self.POOL_NAME].volumes
        self.assertEqual(len(volumes), 1)
        vol = volumes[0]
        self.assertEqual(vol.vid, 'dummy')
        self.assertEqual(vol.path, '/tmp/test-pool/dummy/modules.img')
