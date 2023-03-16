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
import shutil
import unittest.mock
import qubes.log
import qubes.storage
from qubes.exc import QubesException
from qubes.storage import pool_drivers
from qubes.storage.file import FilePool
from qubes.storage.reflink import ReflinkPool
from qubes.tests import SystemTestCase, QubesTestCase

# :pylint: disable=invalid-name


class TestPool(unittest.mock.Mock):
    def __init__(self, **kwargs):
        super(TestPool, self).__init__(spec=qubes.storage.Pool, **kwargs)
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
        self.dir_path_prefix = 'appvms'
        self.dir_path = '/var/lib/qubes/appvms/' + self.name
        self.log = qubes.log.get_vm_logger(self.name)

        if template:
            self.template = template

    def is_template(self):
        return False

    def is_disposablevm(self):
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
        self.default_pool = self.pools['varlibqubes']

class TC_00_Pool(QubesTestCase):
    """ This class tests the utility methods from :mod:``qubes.storage`` """

    def setUp(self):
        super(TC_00_Pool, self).setUp()
        self.basedir_patch = unittest.mock.patch('qubes.config.qubes_base_dir',
            '/tmp/qubes-test-basedir')
        self.basedir_patch.start()
        self.app = TestApp()

    def tearDown(self):
        self.basedir_patch.stop()
        self.app.close()
        del self.app
        shutil.rmtree('/tmp/qubes-test-basedir', ignore_errors=True)
        super().tearDown()

    def test_000_unknown_pool_driver(self):
        # :pylint: disable=protected-access
        """ Expect an exception when unknown pool is requested"""
        with self.assertRaises(QubesException):
            self.app.get_pool('foo-bar')

    def test_001_all_pool_drivers(self):
        """ Expect all our pool drivers (and only them) """
        self.assertCountEqual(
            ["linux-kernel", "lvm_thin", "file", "file-reflink", "callback", "zfs"],
            pool_drivers(),
        )

    def test_002_get_pool_klass(self):
        """ Expect the default pool to be `FilePool` or `ReflinkPool` """
        # :pylint: disable=protected-access
        result = self.app.get_pool('varlibqubes')
        self.assertTrue(isinstance(result, FilePool)
                        or isinstance(result, ReflinkPool))

    def test_003_pool_exists_default(self):
        """ Expect the default pool to exists """
        self.assertPoolExists('varlibqubes')

    def test_004_add_remove_pool(self):
        """ Tries to adding and removing a pool. """
        pool_name = 'asdjhrp89132'

        # make sure it's really does not exist
        self.loop.run_until_complete(self.app.remove_pool(pool_name))
        self.assertFalse(self.assertPoolExists(pool_name))

        self.loop.run_until_complete(
            self.app.add_pool(name=pool_name,
                          driver='file',
                          dir_path='/tmp/asdjhrp89132'))
        self.assertTrue(self.assertPoolExists(pool_name))

        self.loop.run_until_complete(self.app.remove_pool(pool_name))
        self.assertFalse(self.assertPoolExists(pool_name))

    def assertPoolExists(self, pool):
        """ Check if specified pool exists """
        return pool in self.app.pools.keys()

    def test_005_remove_used(self):
        pool_name = 'test-pool-asdf'

        dir_path = '/tmp/{}'.format(pool_name)
        pool = self.loop.run_until_complete(
            self.app.add_pool(name=pool_name,
                driver='file',
                dir_path=dir_path))
        self.addCleanup(shutil.rmtree, dir_path)
        vm = self.app.add_new_vm('StandaloneVM', label='red',
            name=self.make_vm_name('vm'))
        self.loop.run_until_complete(vm.create_on_disk(pool=pool))
        with self.assertRaises(qubes.exc.QubesPoolInUseError):
            self.loop.run_until_complete(self.app.remove_pool(pool_name))

    def test_006_pool_usage_qubespool(self):
        qubes_pool = self.app.get_pool('varlibqubes')

        usage_details = qubes_pool.usage_details

        self.assertIsNotNone(usage_details['data_size'],
                             "Data size incorrectly reported as None")
        self.assertIsNotNone(usage_details['data_usage'],
                             "Data usage incorrectly reported as None")

    def test_007_pool_kernels_usage(self):
        pool_name = 'kernels_test_pools'
        dir_path = '/tmp/{}'.format(pool_name)
        pool = self.loop.run_until_complete(
            self.app.add_pool(name=pool_name,
                              driver='linux-kernel',
                              dir_path=dir_path))
        self.assertTrue(self.assertPoolExists(pool_name))

        qubes_pool = self.app.get_pool(pool_name)

        usage_details = qubes_pool.usage_details

        self.assertEqual(usage_details,
                         {},
                         "Kernels pool should not report usage details.")

        self.loop.run_until_complete(self.app.remove_pool(pool_name))
