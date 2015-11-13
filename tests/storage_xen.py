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
from qubes.tests import QubesTestCase, SystemTestsMixin
from qubes.storage.xen import XenStorage


class TC_00_XenPool(SystemTestsMixin, QubesTestCase):

    """ This class tests some properties of the 'default' pool. """

    def test000_default_pool_dir(self):
        """ The predefined dir for the default pool should be ``/var/lib/qubes``

            .. sealso::
               Data :data:``qubes.qubes.defaults['pool_config']``.
        """
        vm = self._init_app_vm()
        result = qubes.storage.get_pool("default", vm).dir_path
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


class TC_01_XenPool(SystemTestsMixin, QubesTestCase):

    """ Test the paths for the default Xen file based storage (``XenStorage``).
    """

    POOL_DIR = '/var/lib/qubes/test-pool'
    APPVMS_DIR = '/var/lib/qubes/test-pool/appvms'
    TEMPLATES_DIR = '/var/lib/qubes/test-pool/vm-templates'
    SERVICE_DIR = '/var/lib/qubes/test-pool/servicevms'

    def setUp(self):
        """ Add a test file based storage pool """
        super(TC_01_XenPool, self).setUp()
        qubes.storage.add_pool('test-pool', driver='xen',
                               dir_path=self.POOL_DIR)

    def tearDown(self):
        """ Remove the file based storage pool after testing """
        super(TC_01_XenPool, self).tearDown()
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
        result = qubes.storage.get_pool('test-pool', vm).dir_path
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

    def test_011_appvm_file_images(self):
        """ Check if all the needed image files are created for an AppVm"""

        vmname = self.make_vm_name('appvm')
        template = self.qc.get_default_template()
        vm = self.qc.add_new_vm('QubesAppVm', name=vmname, template=template,
                                pool_name='test-pool')
        vm.create_on_disk(verbose=False)

        expected_vmdir = os.path.join(self.APPVMS_DIR, vm.name)
        self.assertEqualsAndExists(vm.storage.vmdir, expected_vmdir)

        expected_private_path = os.path.join(expected_vmdir, 'private.img')
        self.assertEqualsAndExists(vm.storage.private_img,
                                   expected_private_path)

        expected_volatile_path = os.path.join(expected_vmdir, 'volatile.img')
        self.assertEqualsAndExists(vm.storage.volatile_img,
                                   expected_volatile_path)

    def test_012_hvm_file_images(self):
        """ Check if all the needed image files are created for a HVm"""

        vmname = self.make_vm_name('hvm')
        vm = self.qc.add_new_vm('QubesHVm', name=vmname,
                                pool_name='test-pool')
        vm.create_on_disk(verbose=False)

        expected_vmdir = os.path.join(self.APPVMS_DIR, vm.name)
        self.assertEqualsAndExists(vm.storage.vmdir, expected_vmdir)

        expected_private_path = os.path.join(expected_vmdir, 'private.img')
        self.assertEqualsAndExists(vm.storage.private_img,
                                   expected_private_path)

        expected_root_path = os.path.join(expected_vmdir, 'root.img')
        self.assertEqualsAndExists(vm.storage.root_img, expected_root_path)

        expected_volatile_path = os.path.join(expected_vmdir, 'volatile.img')
        self.assertEqualsAndExists(vm.storage.volatile_img,
                                   expected_volatile_path)

    def assertEqualsAndExists(self, result_path, expected_path):
        """ Check if the ``result_path``, matches ``expected_path`` and exists.

            See also: :meth:``assertExist``
        """
        self.assertEquals(result_path, expected_path)
        self.assertExist(result_path)

    def assertExist(self, path):
        """ Assert that the given path exists. """
        self.assertTrue(os.path.exists(path))
