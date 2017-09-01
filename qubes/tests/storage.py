#
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
#
import unittest.mock
import qubes.log
import qubes.storage
from qubes.exc import QubesException
from qubes.storage import pool_drivers
from qubes.storage.file import FilePool
from qubes.tests import SystemTestCase

# :pylint: disable=invalid-name


class TestPool(unittest.mock.Mock):
    def __init__(self, *args, **kwargs):
        super(TestPool, self).__init__(*args, spec=qubes.storage.Pool, **kwargs)
        try:
            self.name = kwargs['name']
        except KeyError:
            pass

    def __str__(self):
        return 'test'

    def init_volume(self, vm, volume_config):
        vol = unittest.mock.Mock(spec=qubes.storage.Volume)
        vol.configure_mock(**volume_config)
        vol.pool = self
        vol.import_data.return_value = '/tmp/test-' + vm.name
        return vol


class TestVM(object):
    def __init__(self, test, template=None):
        self.app = test.app
        self.name = test.make_vm_name('appvm')
        self.dir_path = '/var/lib/qubes/appvms/' + self.name
        self.log = qubes.log.get_vm_logger(self.name)

        if template:
            self.template = template

    def is_template(self):
        # :pylint: disable=no-self-use
        return False

    def is_disposablevm(self):
        # :pylint: disable=no-self-use
        return False


class TestTemplateVM(TestVM):
    dir_path_prefix = qubes.config.system_path['qubes_templates_dir']

    def __init__(self, test, template=None):
        super(TestTemplateVM, self).__init__(test, template)
        self.dir_path = '/var/lib/qubes/vm-templates/' + self.name

    def is_template(self):
        return True


class TestDisposableVM(TestVM):
    def is_disposablevm(self):
        return True

class TestApp(qubes.Qubes):
    def __init__(self, *args, **kwargs):  # pylint: disable=unused-argument
        super(TestApp, self).__init__('/tmp/qubes-test.xml',
            load=False, offline_mode=True, **kwargs)
        self.load_initial_values()

class TC_00_Pool(SystemTestCase):
    """ This class tests the utility methods from :mod:``qubes.storage`` """

    def setUp(self):
        super(TC_00_Pool, self).setUp()
        self.app.close()
        self.app = TestApp()

    def test_000_unknown_pool_driver(self):
        # :pylint: disable=protected-access
        """ Expect an exception when unknown pool is requested"""
        with self.assertRaises(QubesException):
            self.app.get_pool('foo-bar')

    def test_001_all_pool_drivers(self):
        """ The only predefined pool driver is file """
        self.assertCountEqual(['linux-kernel', 'lvm_thin', 'file'], pool_drivers())

    def test_002_get_pool_klass(self):
        """ Expect the default pool to be `FilePool` """
        # :pylint: disable=protected-access
        result = self.app.get_pool('varlibqubes')
        self.assertIsInstance(result, FilePool)

    def test_003_pool_exists_default(self):
        """ Expect the default pool to exists """
        self.assertPoolExists('varlibqubes')

    def test_004_add_remove_pool(self):
        """ Tries to adding and removing a pool. """
        pool_name = 'asdjhrp89132'

        # make sure it's really does not exist
        self.app.remove_pool(pool_name)
        self.assertFalse(self.assertPoolExists(pool_name))

        self.app.add_pool(name=pool_name,
                          driver='file',
                          dir_path='/tmp/asdjhrp89132')
        self.assertTrue(self.assertPoolExists(pool_name))

        self.app.remove_pool(pool_name)
        self.assertFalse(self.assertPoolExists(pool_name))

    def assertPoolExists(self, pool):
        """ Check if specified pool exists """
        return pool in self.app.pools.keys()
