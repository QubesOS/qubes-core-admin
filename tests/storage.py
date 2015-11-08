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
from qubes.qubes import defaults
from qubes.storage.xen import XenPool, XenStorage
from qubes.tests import QubesTestCase, SystemTestsMixin


class TC_00_Storage(SystemTestsMixin, QubesTestCase):

    """ This class tests the utility methods from :mod:``qubes.storage`` """

    def test_000_dump(self):
        """ Dumps storage instance to a storage string  """
        vmname = self.make_vm_name('appvm')
        template = self.qc.get_default_template()
        vm = self.qc.add_new_vm('QubesAppVm', name=vmname,
                                pool_name='default', template=template)
        storage = vm.storage
        result = qubes.storage.dump(storage)
        expected = 'qubes.storage.xen.XenStorage'
        self.assertEquals(result, expected)

    def test_001_load(self):
        """ Loads storage type from a storage string  """
        result = qubes.storage.load('qubes.storage.xen.XenStorage')
        self.assertTrue(result is XenStorage)

    def test_002_default_pool_types(self):
        """ The only predifined pool type is xen """
        result = defaults['pool_types'].keys()
        expected = ["xen"]
        self.assertEquals(result, expected)

    def test_003_get_pool_klass(self):
        """ Expect the default pool to be `XenPool` """
        result = qubes.storage._get_pool_klass('default')
        self.assertTrue(result is XenPool)

    def test_004_pool_exists_default(self):
        """ Expect the default pool to exists """
        self.assertTrue(qubes.storage.pool_exists('default'))

    def test_005_pool_exists_random(self):
        """ Expect this pool to not a exist """
        self.assertFalse(
            qubes.storage.pool_exists('asdh312096r832598213iudhas'))

    def test_006_add_remove_pool(self):
        """ Tries to adding and removing a pool. """
        pool_name = 'asdjhrp89132'

        # make sure it's really does not exist
        qubes.storage.remove_pool(pool_name)

        qubes.storage.add_pool(pool_name, type='xen')
        self.assertTrue(qubes.storage.pool_exists(pool_name))

        qubes.storage.remove_pool(pool_name)
        self.assertFalse(qubes.storage.pool_exists(pool_name))


class TC_00_Pool(SystemTestsMixin, QubesTestCase):

    """ This class tests some properties of the 'default' pool. """

    def test000_default_pool_dir(self):
        """ The predefined dir for the default pool should be ``/var/lib/qubes``

            .. sealso::
               Data :data:``qubes.qubes.defaults['pool_config']``.
        """
        vm = self._init_app_vm()
        result = qubes.storage.get_pool("default", vm).dir
        expected = '/var/lib/qubes/'
        self.assertEquals(result, expected)

    def test001_default_storage_class(self):
        """ Check when using default pool the Storage is ``XenStorage``. """
        result = self._init_app_vm().storage
        self.assertIsInstance(result, XenStorage)

    def test_002_default_pool_name(self):
        """ Default pool_name is 'default'. """
        vm = self._init_app_vm()
        self.assertEquals(vm.pool_name, "default")

    def _init_app_vm(self):
        """ Return initalised, but not created, AppVm. """
        vmname = self.make_vm_name('appvm')
        template = self.qc.get_default_template()
        return self.qc.add_new_vm('QubesAppVm', name=vmname, template=template,
                                  pool_name='default')


class TC_01_Pool(SystemTestsMixin, QubesTestCase):

    """ Test the paths for the default Xen file based storage (``XenStorage``).
    """

    POOL_DIR = '/var/lib/qubes/test-pool'
    APPVMS_DIR = '/var/lib/qubes/test-pool/appvms'
    TEMPLATES_DIR = '/var/lib/qubes/test-pool/vm-templates'
    SERVICE_DIR = '/var/lib/qubes/test-pool/servicevms'

    def setUp(self):
        """ Add a test file based storage pool """
        super(TC_01_Pool, self).setUp()
        qubes.storage.add_pool('test-pool', type='xen', dir=self.POOL_DIR)

    def tearDown(self):
        """ Remove the file based storage pool after testing """
        super(TC_01_Pool, self).tearDown()
        qubes.storage.remove_pool("test-pool")
        shutil.rmtree(self.POOL_DIR, ignore_errors=True)

    def test_001_pool_exists(self):
        """ Check if the storage pool was added to the storage pool config """
        self.assertTrue(qubes.storage.pool_exists('test-pool'))

    def test_002_pool_dir_create(self):
        """ Check if the storage pool dir and subdirs were created """

        # The dir should not exists before
        self.assertFalse(os.path.exists(self.POOL_DIR))

        vmname = self.make_vm_name('appvm')
        template = self.qc.get_default_template()
        self.qc.add_new_vm('QubesAppVm', name=vmname, template=template,
                           pool_name='test-pool')

        self.assertTrue(os.path.exists(self.POOL_DIR))
        self.assertTrue(os.path.exists(self.APPVMS_DIR))
        self.assertTrue(os.path.exists(self.SERVICE_DIR))
        self.assertTrue(os.path.exists(self.TEMPLATES_DIR))

    def test_003_pool_dir(self):
        """ Check if the vm storage pool_dir is the same as specified """
        vmname = self.make_vm_name('appvm')
        template = self.qc.get_default_template()
        vm = self.qc.add_new_vm('QubesAppVm', name=vmname, template=template,
                                pool_name='test-pool')
        result = qubes.storage.get_pool('test-pool', vm).dir
        self.assertEquals(self.POOL_DIR, result)

    def test_004_app_vmdir(self):
        """ Check the vm storage dir for an AppVm"""
        vmname = self.make_vm_name('appvm')
        template = self.qc.get_default_template()
        vm = self.qc.add_new_vm('QubesAppVm', name=vmname, template=template,
                                pool_name='test-pool')

        expected = os.path.join(self.APPVMS_DIR, vm.name)
        result = vm.storage.vmdir
        self.assertEquals(expected, result)

    def test_005_hvm_vmdir(self):
        """ Check the vm storage dir for a HVM"""
        vmname = self.make_vm_name('hvm')
        vm = self.qc.add_new_vm('QubesHVm', name=vmname,
                                pool_name='test-pool')

        expected = os.path.join(self.APPVMS_DIR, vm.name)
        result = vm.storage.vmdir
        self.assertEquals(expected, result)

    def test_006_net_vmdir(self):
        """ Check the vm storage dir for a Netvm"""
        vmname = self.make_vm_name('hvm')
        vm = self.qc.add_new_vm('QubesNetVm', name=vmname,
                                pool_name='test-pool')

        expected = os.path.join(self.SERVICE_DIR, vm.name)
        result = vm.storage.vmdir
        self.assertEquals(expected, result)

    def test_007_proxy_vmdir(self):
        """ Check the vm storage dir for a ProxyVm"""
        vmname = self.make_vm_name('proxyvm')
        vm = self.qc.add_new_vm('QubesProxyVm', name=vmname,
                                pool_name='test-pool')

        expected = os.path.join(self.SERVICE_DIR, vm.name)
        result = vm.storage.vmdir
        self.assertEquals(expected, result)

    def test_008_admin_vmdir(self):
        """ Check the vm storage dir for a AdminVm"""
        # TODO How to test AdminVm?
        pass

    def test_009_template_vmdir(self):
        """ Check the vm storage dir for a TemplateVm"""
        vmname = self.make_vm_name('templatevm')
        vm = self.qc.add_new_vm('QubesTemplateVm', name=vmname,
                                pool_name='test-pool')

        expected = os.path.join(self.TEMPLATES_DIR, vm.name)
        result = vm.storage.vmdir
        self.assertEquals(expected, result)

    def test_010_template_hvm_vmdir(self):
        """ Check the vm storage dir for a TemplateHVm"""
        vmname = self.make_vm_name('templatehvm')
        vm = self.qc.add_new_vm('QubesTemplateHVm', name=vmname,
                                pool_name='test-pool')

        expected = os.path.join(self.TEMPLATES_DIR, vm.name)
        result = vm.storage.vmdir
        self.assertEquals(expected, result)
