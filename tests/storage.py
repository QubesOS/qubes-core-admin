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


from qubes.tests import QubesTestCase, SystemTestsMixin
from qubes.qubes import defaults

import qubes.storage
from qubes.storage.xen import XenStorage, XenPool


class TC_00_Storage(SystemTestsMixin, QubesTestCase):

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


class TC_00_Pool(SystemTestsMixin, QubesTestCase):

    def test000_no_pool_dir(self):
        """ If no pool dir ist configured for a ``XenPool`` assume the default
            `/var/lib/qubes/`.
        """
        vm = self._init_app_vm()
        result = qubes.storage.get_pool("default", vm).dir
        expected = '/var/lib/qubes/'
        self.assertEquals(result, expected)

    def test001_default_storage_class(self):
        """ Check if when using default pool the Storage is ``XenStorage``. """
        result = self._init_app_vm().storage
        self.assertIsInstance(result, XenStorage)

    def test_002_pool_name(self):
        """ Default pool_name is 'default'. """
        vm = self._init_app_vm()
        self.assertEquals(vm.pool_name, "default")

    def _init_app_vm(self):
        """ Return initalised, but not created, AppVm. """
        vmname = self.make_vm_name('appvm')
        template = self.qc.get_default_template()
        return self.qc.add_new_vm('QubesAppVm', name=vmname, template=template,
                                  pool_name='default')
