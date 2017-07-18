#
# The Qubes OS Project, http://www.qubes-os.org
#
# Copyright (C) 2016 Bahtiar `kalkin-` Gadimov <bahtiar@gadimov.de>
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
''' Tests for lvm storage driver. By default tests are going to use the
    'qubes_dom0/pool00'. An alternative LVM thin pool may be provided via
    :envvar:`DEFAULT_LVM_POOL` shell variable.

    Any pool variables prefixed with 'LVM_' or 'lvm_' represent a LVM
    'volume_group/thin_pool' combination. Pool variables without a prefix
    represent a :py:class:`qubes.storage.lvm.ThinPool`.
'''

import os
import unittest

import qubes.tests
from qubes.storage.lvm import ThinPool, ThinVolume

if 'DEFAULT_LVM_POOL' in os.environ.keys():
    DEFAULT_LVM_POOL = os.environ['DEFAULT_LVM_POOL']
else:
    DEFAULT_LVM_POOL = 'qubes_dom0/pool00'


def lvm_pool_exists(volume_group, thin_pool):
    ''' Returns ``True`` if thin pool exists in the volume group. '''
    path = "/dev/mapper/{!s}-{!s}".format(volume_group, thin_pool)
    return os.path.exists(path)


def skipUnlessLvmPoolExists(test_item):  # pylint: disable=invalid-name
    ''' Decorator that skips LVM tests if the default pool is missing. '''
    volume_group, thin_pool = DEFAULT_LVM_POOL.split('/', 1)
    result = lvm_pool_exists(volume_group, thin_pool)
    msg = 'LVM thin pool {!r} does not exist'.format(DEFAULT_LVM_POOL)
    return unittest.skipUnless(result, msg)(test_item)


POOL_CONF = {'name': 'test-lvm',
             'driver': 'lvm_thin',
             'volume_group': DEFAULT_LVM_POOL.split('/')[0],
             'thin_pool': DEFAULT_LVM_POOL.split('/')[1]}


class ThinPoolBase(qubes.tests.QubesTestCase):
    ''' Sanity tests for :py:class:`qubes.storage.lvm.ThinPool` '''

    created_pool = False

    def setUp(self):
        super(ThinPoolBase, self).setUp()
        volume_group, thin_pool = DEFAULT_LVM_POOL.split('/', 1)
        self.pool = self._find_pool(volume_group, thin_pool)
        if not self.pool:
            self.pool = self.app.add_pool(**POOL_CONF)
            self.created_pool = True

    def tearDown(self):
        ''' Remove the default lvm pool if it was created only for this test '''
        if self.created_pool:
            self.app.remove_pool(self.pool.name)
        super(ThinPoolBase, self).tearDown()


    def _find_pool(self, volume_group, thin_pool):
        ''' Returns the pool matching the specified ``volume_group`` &
            ``thin_pool``, or None.
        '''
        pools = [p for p in self.app.pools
            if issubclass(p.__class__, ThinPool)]
        for pool in pools:
            if pool.volume_group == volume_group \
                    and pool.thin_pool == thin_pool:
                return pool
        return None

@skipUnlessLvmPoolExists
class TC_00_ThinPool(ThinPoolBase):
    ''' Sanity tests for :py:class:`qubes.storage.lvm.ThinPool` '''

    def setUp(self):
        xml_path = '/tmp/qubes-test.xml'
        self.app = qubes.Qubes.create_empty_store(store=xml_path,
            clockvm=None,
            updatevm=None,
            offline_mode=True,
        )
        os.environ['QUBES_XML_PATH'] = xml_path
        super(TC_00_ThinPool, self).setUp()

    def tearDown(self):
        super(TC_00_ThinPool, self).tearDown()
        os.unlink(self.app.store)
        del self.app
        for attr in dir(self):
            if isinstance(getattr(self, attr), qubes.vm.BaseVM):
                delattr(self, attr)

    def test_000_default_thin_pool(self):
        ''' Check whether :py:data`DEFAULT_LVM_POOL` exists. This pool is
            created by default, if at installation time LVM + Thin was chosen.
        '''
        msg = 'Thin pool {!r} does not exist'.format(DEFAULT_LVM_POOL)
        self.assertTrue(self.pool, msg)

    def test_001_origin_volume(self):
        ''' Test origin volume creation '''
        config = {
            'name': 'root',
            'pool': self.pool.name,
            'save_on_stop': True,
            'rw': True,
            'size': qubes.config.defaults['root_img_size'],
        }
        vm = qubes.tests.storage.TestVM(self)
        volume = self.app.get_pool(self.pool.name).init_volume(vm, config)
        self.assertIsInstance(volume, ThinVolume)
        self.assertEqual(volume.name, 'root')
        self.assertEqual(volume.pool, self.pool.name)
        self.assertEqual(volume.size, qubes.config.defaults['root_img_size'])
        volume.create()
        path = "/dev/%s" % volume.vid
        self.assertTrue(os.path.exists(path))
        volume.remove()

    def test_003_read_write_volume(self):
        ''' Test read-write volume creation '''
        config = {
            'name': 'root',
            'pool': self.pool.name,
            'rw': True,
            'save_on_stop': True,
            'size': qubes.config.defaults['root_img_size'],
        }
        vm = qubes.tests.storage.TestVM(self)
        volume = self.app.get_pool(self.pool.name).init_volume(vm, config)
        self.assertIsInstance(volume, ThinVolume)
        self.assertEqual(volume.name, 'root')
        self.assertEqual(volume.pool, self.pool.name)
        self.assertEqual(volume.size, qubes.config.defaults['root_img_size'])
        volume.create()
        path = "/dev/%s" % volume.vid
        self.assertTrue(os.path.exists(path))
        volume.remove()

@skipUnlessLvmPoolExists
class TC_01_ThinPool(qubes.tests.SystemTestCase, ThinPoolBase):
    ''' Sanity tests for :py:class:`qubes.storage.lvm.ThinPool` '''

    def setUp(self):
        super(TC_01_ThinPool, self).setUp()
        self.init_default_template()

    def test_004_import(self):
        template_vm = self.app.default_template
        name = self.make_vm_name('import')
        vm = self.app.add_new_vm(qubes.vm.templatevm.TemplateVM, name=name,
                            label='red')
        vm.clone_properties(template_vm)
        vm.clone_disk_files(template_vm, pool='test-lvm')
        for v_name, volume in vm.volumes.items():
            if volume.save_on_stop:
                expected = "/dev/{!s}/{!s}-{!s}".format(
                    DEFAULT_LVM_POOL.split('/')[0], vm.name, v_name)
                self.assertEqual(volume.path, expected)
        with self.assertNotRaises(qubes.exc.QubesException):
            vm.start()

    def test_005_create_appvm(self):
        vm = self.app.add_new_vm(cls=qubes.vm.appvm.AppVM,
                                 name=self.make_vm_name('appvm'), label='red')
        vm.create_on_disk(pool='test-lvm')
        for v_name, volume in vm.volumes.items():
            if volume.save_on_stop:
                expected = "/dev/{!s}/{!s}-{!s}".format(
                    DEFAULT_LVM_POOL.split('/')[0], vm.name, v_name)
                self.assertEqual(volume.path, expected)
        with self.assertNotRaises(qubes.exc.QubesException):
            vm.start()
