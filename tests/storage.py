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
        """ Loads storage driver from a storage string  """
        result = qubes.storage.load('qubes.storage.xen.XenStorage')
        self.assertTrue(result is XenStorage)

    def test_002_default_pool_drivers(self):
        """ The only predifined pool driver is xen """
        result = defaults['pool_drivers'].keys()
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

        qubes.storage.add_pool(pool_name, driver='xen')
        self.assertTrue(qubes.storage.pool_exists(pool_name))

        qubes.storage.remove_pool(pool_name)
        self.assertFalse(qubes.storage.pool_exists(pool_name))
