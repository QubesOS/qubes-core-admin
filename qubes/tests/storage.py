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

import qubes.log
from qubes.storage import StoragePoolException, pool_drivers
from qubes.storage.xen import XenPool
from qubes.tests import QubesTestCase


class TestApp(qubes.tests.TestEmitter):
    pass


class TestVM(object):
    def __init__(self, app, qid, name, pool_name, template=None):
        super(TestVM, self).__init__()
        self.app = app
        self.qid = qid
        self.name = name
        self.pool_name = pool_name
        self.template = template
        self.hvm = False
        self.storage = qubes.storage.get_pool(self.pool_name,
                                              self).get_storage()
        self.log = qubes.log.get_vm_logger(self.name)

    def is_template(self):
        return False

    def is_disposablevm(self):
        return False

    @property
    def dir_path(self):
        return self.storage.vmdir


class TestTemplateVM(TestVM):
    def is_template(self):
        return True


class TestDisposableVM(TestVM):
    def is_disposablevm(self):
        return True


class TC_00_Pool(QubesTestCase):
    """ This class tests the utility methods from :mod:``qubes.storage`` """

    def setUp(self):
        super(TC_00_Pool, self).setUp()

    def test_000_unknown_pool_driver(self):
        # :pylint: disable=protected-access
        """ Expect an exception when unknown pool is requested"""
        with self.assertRaises(StoragePoolException):
            qubes.storage._get_pool_klass('foo-bar')

    def test_001_all_pool_drivers(self):
        """ The only predefined pool driver is file """
        self.assertEquals(["xen"], pool_drivers())

    def test_002_get_pool_klass(self):
        """ Expect the default pool to be `XenPool` """
        # :pylint: disable=protected-access
        result = qubes.storage._get_pool_klass('default')
        self.assertTrue(result is XenPool)

    def test_003_pool_exists_default(self):
        """ Expect the default pool to exists """
        self.assertTrue(qubes.storage.pool_exists('default'))

    def test_004_pool_exists_random(self):
        """ Expect this pool to not a exist """
        self.assertFalse(qubes.storage.pool_exists(
            'asdh312096r832598213iudhas'))

    def test_005_add_remove_pool(self):
        """ Tries to adding and removing a pool. """
        pool_name = 'asdjhrp89132'

        # make sure it's really does not exist
        qubes.storage.remove_pool(pool_name)

        qubes.storage.add_pool(pool_name, driver='xen')
        self.assertTrue(qubes.storage.pool_exists(pool_name))

        qubes.storage.remove_pool(pool_name)
        self.assertFalse(qubes.storage.pool_exists(pool_name))
