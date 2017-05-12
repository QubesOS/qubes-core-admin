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

''' Tests for management calls endpoints '''

import asyncio
import os
import shutil
import unittest.mock

import libvirt

import qubes
import qubes.api.admin
import qubes.tests

# properties defined in API
volume_properties = [
    'pool', 'vid', 'size', 'usage', 'rw', 'internal', 'source',
    'save_on_stop', 'snap_on_start']


class AdminAPITestCase(qubes.tests.QubesTestCase):
    def setUp(self):
        super().setUp()
        app = qubes.Qubes('/tmp/qubes-test.xml', load=False)
        app.vmm = unittest.mock.Mock(spec=qubes.app.VMMConnection)
        app.load_initial_values()
        app.default_kernel = '1.0'
        app.default_netvm = None
        self.template = app.add_new_vm('TemplateVM', label='black',
            name='test-template')
        app.default_template = 'test-template'
        with qubes.tests.substitute_entry_points('qubes.storage',
                'qubes.tests.storage'):
            app.add_pool('test', driver='test')
        app.save = unittest.mock.Mock()
        self.vm = app.add_new_vm('AppVM', label='red', name='test-vm1',
            template='test-template')
        self.app = app
        libvirt_attrs = {
            'libvirt_conn.lookupByUUID.return_value.isActive.return_value':
                False,
            'libvirt_conn.lookupByUUID.return_value.state.return_value':
                [libvirt.VIR_DOMAIN_SHUTOFF],
        }
        app.vmm.configure_mock(**libvirt_attrs)

        self.emitter = qubes.tests.TestEmitter()
        self.app.domains[0].fire_event = self.emitter.fire_event
        self.app.domains[0].fire_event_pre = self.emitter.fire_event_pre

        self.test_base_dir = '/tmp/qubes-test-dir'
        self.base_dir_patch = unittest.mock.patch.dict(qubes.config.system_path,
            {'qubes_base_dir': self.test_base_dir})
        self.base_dir_patch.start()

    def tearDown(self):
        self.base_dir_patch.stop()
        if os.path.exists(self.test_base_dir):
            shutil.rmtree(self.test_base_dir)
        super(AdminAPITestCase, self).tearDown()

    def call_mgmt_func(self, method, dest, arg=b'', payload=b''):
        mgmt_obj = qubes.api.admin.QubesAdminAPI(self.app, b'dom0', method, dest, arg)

        loop = asyncio.get_event_loop()
        response = loop.run_until_complete(
            mgmt_obj.execute(untrusted_payload=payload))
        self.assertEventFired(self.emitter,
            'mgmt-permission:' + method.decode('ascii'))
        return response


class TC_00_VMs(AdminAPITestCase):
    def test_000_vm_list(self):
        value = self.call_mgmt_func(b'admin.vm.List', b'dom0')
        self.assertEqual(value,
            'dom0 class=AdminVM state=Running\n'
            'test-template class=TemplateVM state=Halted\n'
            'test-vm1 class=AppVM state=Halted\n')

    def test_001_vm_list_single(self):
        value = self.call_mgmt_func(b'admin.vm.List', b'test-vm1')
        self.assertEqual(value,
            'test-vm1 class=AppVM state=Halted\n')

    def test_010_vm_property_list(self):
        # this test is kind of stupid, but at least check if appropriate
        # mgmt-permission event is fired
        value = self.call_mgmt_func(b'admin.vm.property.List', b'test-vm1')
        properties = self.app.domains['test-vm1'].property_list()
        self.assertEqual(value,
            ''.join('{}\n'.format(prop.__name__) for prop in properties))

    def test_020_vm_property_get_str(self):
        value = self.call_mgmt_func(b'admin.vm.property.Get', b'test-vm1',
            b'name')
        self.assertEqual(value, 'default=False type=str test-vm1')

    def test_021_vm_property_get_int(self):
        value = self.call_mgmt_func(b'admin.vm.property.Get', b'test-vm1',
            b'vcpus')
        self.assertEqual(value, 'default=True type=int 42')

    def test_022_vm_property_get_bool(self):
        value = self.call_mgmt_func(b'admin.vm.property.Get', b'test-vm1',
            b'provides_network')
        self.assertEqual(value, 'default=True type=bool False')

    def test_023_vm_property_get_label(self):
        value = self.call_mgmt_func(b'admin.vm.property.Get', b'test-vm1',
            b'label')
        self.assertEqual(value, 'default=False type=label red')

    def test_024_vm_property_get_vm(self):
        value = self.call_mgmt_func(b'admin.vm.property.Get', b'test-vm1',
            b'template')
        self.assertEqual(value, 'default=False type=vm test-template')

    def test_025_vm_property_get_vm_none(self):
        value = self.call_mgmt_func(b'admin.vm.property.Get', b'test-vm1',
            b'netvm')
        self.assertEqual(value, 'default=True type=vm ')

    def test_030_vm_property_set_vm(self):
        netvm = self.app.add_new_vm('AppVM', label='red', name='test-net',
            template='test-template', provides_network=True)

        with unittest.mock.patch('qubes.vm.VMProperty.__set__') as mock:
            value = self.call_mgmt_func(b'admin.vm.property.Set', b'test-vm1',
                b'netvm', b'test-net')
            self.assertIsNone(value)
            mock.assert_called_once_with(self.vm, 'test-net')
        self.app.save.assert_called_once_with()

    def test_032_vm_property_set_vm_invalid1(self):
        with unittest.mock.patch('qubes.vm.VMProperty.__set__') as mock:
            with self.assertRaises(qubes.exc.QubesValueError):
                self.call_mgmt_func(b'admin.vm.property.Set', b'test-vm1',
                    b'netvm', b'forbidden-chars/../!')
            self.assertFalse(mock.called)
        self.assertFalse(self.app.save.called)

    def test_033_vm_property_set_vm_invalid2(self):
        with unittest.mock.patch('qubes.vm.VMProperty.__set__') as mock:
            with self.assertRaises(qubes.exc.QubesValueError):
                self.call_mgmt_func(b'admin.vm.property.Set', b'test-vm1',
                    b'netvm', b'\x80\x90\xa0')
            self.assertFalse(mock.called)
        self.assertFalse(self.app.save.called)

    def test_034_vm_propert_set_bool_true(self):
        with unittest.mock.patch('qubes.property.__set__') as mock:
            value = self.call_mgmt_func(b'admin.vm.property.Set', b'test-vm1',
                b'autostart', b'True')
            self.assertIsNone(value)
            mock.assert_called_once_with(self.vm, True)
        self.app.save.assert_called_once_with()

    def test_035_vm_propert_set_bool_false(self):
        with unittest.mock.patch('qubes.property.__set__') as mock:
            value = self.call_mgmt_func(b'admin.vm.property.Set', b'test-vm1',
                b'autostart', b'False')
            self.assertIsNone(value)
            mock.assert_called_once_with(self.vm, False)
        self.app.save.assert_called_once_with()

    def test_036_vm_propert_set_bool_invalid1(self):
        with unittest.mock.patch('qubes.property.__set__') as mock:
            with self.assertRaises(qubes.exc.QubesValueError):
                self.call_mgmt_func(b'admin.vm.property.Set', b'test-vm1',
                    b'autostart', b'some string')
            self.assertFalse(mock.called)
        self.assertFalse(self.app.save.called)

    def test_037_vm_propert_set_bool_invalid2(self):
        with unittest.mock.patch('qubes.property.__set__') as mock:
            with self.assertRaises(qubes.exc.QubesValueError):
                self.call_mgmt_func(b'admin.vm.property.Set', b'test-vm1',
                    b'autostart', b'\x80\x90@#$%^&*(')
            self.assertFalse(mock.called)
        self.assertFalse(self.app.save.called)

    def test_038_vm_propert_set_str(self):
        with unittest.mock.patch('qubes.property.__set__') as mock:
            value = self.call_mgmt_func(b'admin.vm.property.Set', b'test-vm1',
                b'kernel', b'1.0')
            self.assertIsNone(value)
            mock.assert_called_once_with(self.vm, '1.0')
        self.app.save.assert_called_once_with()

    def test_039_vm_propert_set_str_invalid1(self):
        with unittest.mock.patch('qubes.property.__set__') as mock:
            with self.assertRaises(qubes.exc.QubesValueError):
                self.call_mgmt_func(b'admin.vm.property.Set', b'test-vm1',
                    b'kernel', b'some, non-ASCII: \x80\xd2')
            self.assertFalse(mock.called)
        self.assertFalse(self.app.save.called)

    def test_040_vm_propert_set_int(self):
        with unittest.mock.patch('qubes.property.__set__') as mock:
            value = self.call_mgmt_func(b'admin.vm.property.Set', b'test-vm1',
                b'maxmem', b'1024000')
            self.assertIsNone(value)
            mock.assert_called_once_with(self.vm, 1024000)
        self.app.save.assert_called_once_with()

    def test_041_vm_propert_set_int_invalid1(self):
        with unittest.mock.patch('qubes.property.__set__') as mock:
            with self.assertRaises(qubes.exc.QubesValueError):
                self.call_mgmt_func(b'admin.vm.property.Set', b'test-vm1',
                    b'maxmem', b'fourty two')
            self.assertFalse(mock.called)
        self.assertFalse(self.app.save.called)

    def test_042_vm_propert_set_label(self):
        with unittest.mock.patch('qubes.property.__set__') as mock:
            value = self.call_mgmt_func(b'admin.vm.property.Set', b'test-vm1',
                b'label', b'green')
            self.assertIsNone(value)
            mock.assert_called_once_with(self.vm, 'green')
        self.app.save.assert_called_once_with()

    def test_043_vm_propert_set_label_invalid1(self):
        with unittest.mock.patch('qubes.property.__set__') as mock:
            with self.assertRaises(qubes.exc.QubesValueError):
                self.call_mgmt_func(b'admin.vm.property.Set', b'test-vm1',
                    b'maxmem', b'some, non-ASCII: \x80\xd2')
            self.assertFalse(mock.called)
        self.assertFalse(self.app.save.called)

    @unittest.skip('label existence not checked before actual setter yet')
    def test_044_vm_propert_set_label_invalid2(self):
        with unittest.mock.patch('qubes.property.__set__') as mock:
            with self.assertRaises(qubes.exc.QubesValueError):
                self.call_mgmt_func(b'admin.vm.property.Set', b'test-vm1',
                    b'maxmem', b'non-existing-color')
            self.assertFalse(mock.called)
        self.assertFalse(self.app.save.called)

    def test_050_vm_property_help(self):
        value = self.call_mgmt_func(b'admin.vm.property.Help', b'test-vm1',
            b'label')
        self.assertEqual(value,
            'Colourful label assigned to VM. This is where the colour of the '
            'padlock is set.')
        self.assertFalse(self.app.save.called)

    def test_052_vm_property_help_invalid_property(self):
        with self.assertRaises(AssertionError):
            self.call_mgmt_func(b'admin.vm.property.Help', b'test-vm1',
                b'no-such-property')

        self.assertFalse(self.app.save.called)

    def test_060_vm_property_reset(self):
        with unittest.mock.patch('qubes.property.__delete__') as mock:
            value = self.call_mgmt_func(b'admin.vm.property.Reset', b'test-vm1',
                b'default_user')
            mock.assert_called_with(self.vm)
        self.assertIsNone(value)
        self.app.save.assert_called_once_with()

    def test_062_vm_property_reset_invalid_property(self):
        with unittest.mock.patch('qubes.property.__delete__') as mock:
            with self.assertRaises(AssertionError):
                self.call_mgmt_func(b'admin.vm.property.Help', b'test-vm1',
                    b'no-such-property')
            self.assertFalse(mock.called)
        self.assertFalse(self.app.save.called)

    def test_070_vm_volume_list(self):
        self.vm.volumes = unittest.mock.Mock()
        volumes_conf = {
            'keys.return_value': ['root', 'private', 'volatile', 'kernel']
        }
        self.vm.volumes.configure_mock(**volumes_conf)
        value = self.call_mgmt_func(b'admin.vm.volume.List', b'test-vm1')
        self.assertEqual(value, 'root\nprivate\nvolatile\nkernel\n')
        # check if _only_ keys were accessed
        self.assertEqual(self.vm.volumes.mock_calls,
            [unittest.mock.call.keys()])

    def test_080_vm_volume_info(self):
        self.vm.volumes = unittest.mock.MagicMock()
        volumes_conf = {
            'keys.return_value': ['root', 'private', 'volatile', 'kernel']
        }
        for prop in volume_properties:
            volumes_conf[
                '__getitem__.return_value.{}'.format(prop)] = prop +'-value'
        self.vm.volumes.configure_mock(**volumes_conf)
        value = self.call_mgmt_func(b'admin.vm.volume.Info', b'test-vm1',
            b'private')
        self.assertEqual(value,
            ''.join('{p}={p}-value\n'.format(p=p) for p in volume_properties))
        self.assertEqual(self.vm.volumes.mock_calls,
            [unittest.mock.call.keys(),
             unittest.mock.call.__getattr__('__getitem__')('private')])

    def test_080_vm_volume_info_invalid_volume(self):
        self.vm.volumes = unittest.mock.MagicMock()
        volumes_conf = {
            'keys.return_value': ['root', 'private', 'volatile', 'kernel']
        }
        self.vm.volumes.configure_mock(**volumes_conf)
        with self.assertRaises(AssertionError):
            self.call_mgmt_func(b'admin.vm.volume.Info', b'test-vm1',
                b'no-such-volume')
        self.assertEqual(self.vm.volumes.mock_calls,
            [unittest.mock.call.keys()])

    def test_090_vm_volume_listsnapshots(self):
        self.vm.volumes = unittest.mock.MagicMock()
        volumes_conf = {
            'keys.return_value': ['root', 'private', 'volatile', 'kernel'],
            '__getitem__.return_value.revisions': ['rev1', 'rev2'],
        }
        self.vm.volumes.configure_mock(**volumes_conf)
        value = self.call_mgmt_func(b'admin.vm.volume.ListSnapshots',
            b'test-vm1', b'private')
        self.assertEqual(value,
            'rev1\nrev2\n')
        self.assertEqual(self.vm.volumes.mock_calls,
            [unittest.mock.call.keys(),
            unittest.mock.call.__getattr__('__getitem__')('private')])

    def test_090_vm_volume_listsnapshots_invalid_volume(self):
        self.vm.volumes = unittest.mock.MagicMock()
        volumes_conf = {
            'keys.return_value': ['root', 'private', 'volatile', 'kernel']
        }
        self.vm.volumes.configure_mock(**volumes_conf)
        with self.assertRaises(AssertionError):
            self.call_mgmt_func(b'admin.vm.volume.ListSnapshots', b'test-vm1',
                b'no-such-volume')
        self.assertEqual(self.vm.volumes.mock_calls,
            [unittest.mock.call.keys()])

    @unittest.skip('method not implemented yet')
    def test_100_vm_volume_snapshot(self):
        pass

    @unittest.skip('method not implemented yet')
    def test_100_vm_volume_snapshot_invlid_volume(self):
        self.vm.volumes = unittest.mock.MagicMock()
        volumes_conf = {
            'keys.return_value': ['root', 'private', 'volatile', 'kernel'],
            '__getitem__.return_value.revisions': ['rev1', 'rev2'],
        }
        self.vm.volumes.configure_mock(**volumes_conf)
        with self.assertRaises(AssertionError):
            self.call_mgmt_func(b'admin.vm.volume.Snapshots',
                b'test-vm1', b'no-such-volume')
        self.assertEqual(self.vm.volumes.mock_calls,
            [unittest.mock.call.keys()])

    @unittest.skip('method not implemented yet')
    def test_100_vm_volume_snapshot_invalid_revision(self):
        self.vm.volumes = unittest.mock.MagicMock()
        volumes_conf = {
            'keys.return_value': ['root', 'private', 'volatile', 'kernel']
        }
        self.vm.volumes.configure_mock(**volumes_conf)
        with self.assertRaises(AssertionError):
            self.call_mgmt_func(b'admin.vm.volume.Snapshots',
                b'test-vm1', b'private', b'no-such-rev')
        self.assertEqual(self.vm.volumes.mock_calls,
            [unittest.mock.call.keys(),
            unittest.mock.call.__getattr__('__getitem__')('private')])

    def test_110_vm_volume_revert(self):
        self.vm.volumes = unittest.mock.MagicMock()
        volumes_conf = {
            'keys.return_value': ['root', 'private', 'volatile', 'kernel'],
            '__getitem__.return_value.revisions': ['rev1', 'rev2'],
        }
        self.vm.volumes.configure_mock(**volumes_conf)
        self.vm.storage = unittest.mock.Mock()
        value = self.call_mgmt_func(b'admin.vm.volume.Revert',
            b'test-vm1', b'private', b'rev1')
        self.assertIsNone(value)
        self.assertEqual(self.vm.volumes.mock_calls,
            [unittest.mock.call.keys(),
                unittest.mock.call.__getattr__('__getitem__')('private')])
        self.assertEqual(self.vm.storage.mock_calls,
            [unittest.mock.call.get_pool(self.vm.volumes['private']),
             unittest.mock.call.get_pool().revert('rev1')])

    def test_110_vm_volume_revert_invalid_rev(self):
        self.vm.volumes = unittest.mock.MagicMock()
        volumes_conf = {
            'keys.return_value': ['root', 'private', 'volatile', 'kernel'],
            '__getitem__.return_value.revisions': ['rev1', 'rev2'],
        }
        self.vm.volumes.configure_mock(**volumes_conf)
        self.vm.storage = unittest.mock.Mock()
        with self.assertRaises(AssertionError):
            self.call_mgmt_func(b'admin.vm.volume.Revert',
                b'test-vm1', b'private', b'no-such-rev')
        self.assertEqual(self.vm.volumes.mock_calls,
            [unittest.mock.call.keys(),
                unittest.mock.call.__getattr__('__getitem__')('private')])
        self.assertFalse(self.vm.storage.called)

    def test_120_vm_volume_resize(self):
        self.vm.volumes = unittest.mock.MagicMock()
        volumes_conf = {
            'keys.return_value': ['root', 'private', 'volatile', 'kernel'],
        }
        self.vm.volumes.configure_mock(**volumes_conf)
        self.vm.storage = unittest.mock.Mock()
        value = self.call_mgmt_func(b'admin.vm.volume.Resize',
            b'test-vm1', b'private', b'1024000000')
        self.assertIsNone(value)
        self.assertEqual(self.vm.volumes.mock_calls,
            [unittest.mock.call.keys()])
        self.assertEqual(self.vm.storage.mock_calls,
            [unittest.mock.call.resize('private', 1024000000)])

    def test_120_vm_volume_resize_invalid_size1(self):
        self.vm.volumes = unittest.mock.MagicMock()
        volumes_conf = {
            'keys.return_value': ['root', 'private', 'volatile', 'kernel'],
        }
        self.vm.volumes.configure_mock(**volumes_conf)
        self.vm.storage = unittest.mock.Mock()
        with self.assertRaises(AssertionError):
            self.call_mgmt_func(b'admin.vm.volume.Resize',
                b'test-vm1', b'private', b'no-int-size')
        self.assertEqual(self.vm.volumes.mock_calls,
            [unittest.mock.call.keys()])
        self.assertFalse(self.vm.storage.called)

    def test_120_vm_volume_resize_invalid_size2(self):
        self.vm.volumes = unittest.mock.MagicMock()
        volumes_conf = {
            'keys.return_value': ['root', 'private', 'volatile', 'kernel'],
        }
        self.vm.volumes.configure_mock(**volumes_conf)
        self.vm.storage = unittest.mock.Mock()
        with self.assertRaises(AssertionError):
            self.call_mgmt_func(b'admin.vm.volume.Resize',
                b'test-vm1', b'private', b'-1')
        self.assertEqual(self.vm.volumes.mock_calls,
            [unittest.mock.call.keys()])
        self.assertFalse(self.vm.storage.called)

    def test_130_pool_list(self):
        self.app.pools = ['file', 'lvm']
        value = self.call_mgmt_func(b'admin.pool.List', b'dom0')
        self.assertEqual(value, 'file\nlvm\n')
        self.assertFalse(self.app.save.called)

    @unittest.mock.patch('qubes.storage.pool_drivers')
    @unittest.mock.patch('qubes.storage.driver_parameters')
    def test_140_pool_listdrivers(self, mock_parameters, mock_drivers):
        self.app.pools = ['file', 'lvm']

        mock_drivers.return_value = ['driver1', 'driver2']
        mock_parameters.side_effect = \
            lambda driver: {
                'driver1': ['param1', 'param2'],
                'driver2': ['param3', 'param4']
            }[driver]

        value = self.call_mgmt_func(b'admin.pool.ListDrivers', b'dom0')
        self.assertEqual(value,
            'driver1 param1 param2\ndriver2 param3 param4\n')
        self.assertEqual(mock_drivers.mock_calls, [unittest.mock.call()])
        self.assertEqual(mock_parameters.mock_calls,
            [unittest.mock.call('driver1'), unittest.mock.call('driver2')])
        self.assertFalse(self.app.save.called)

    def test_150_pool_info(self):
        self.app.pools = {
            'pool1': unittest.mock.Mock(config={
                'param1': 'value1', 'param2': 'value2'})
        }
        value = self.call_mgmt_func(b'admin.pool.Info', b'dom0', b'pool1')

        self.assertEqual(value, 'param1=value1\nparam2=value2\n')
        self.assertFalse(self.app.save.called)

    @unittest.mock.patch('qubes.storage.pool_drivers')
    @unittest.mock.patch('qubes.storage.driver_parameters')
    def test_160_pool_add(self, mock_parameters, mock_drivers):
        self.app.pools = {
            'file': unittest.mock.Mock(),
            'lvm': unittest.mock.Mock()
        }

        mock_drivers.return_value = ['driver1', 'driver2']
        mock_parameters.side_effect = \
            lambda driver: {
                'driver1': ['param1', 'param2'],
                'driver2': ['param3', 'param4']
            }[driver]

        self.app.add_pool = unittest.mock.Mock()

        value = self.call_mgmt_func(b'admin.pool.Add', b'dom0', b'driver1',
            b'name=test-pool\nparam1=some-value\n')
        self.assertIsNone(value)
        self.assertEqual(mock_drivers.mock_calls, [unittest.mock.call()])
        self.assertEqual(mock_parameters.mock_calls,
            [unittest.mock.call('driver1')])
        self.assertEqual(self.app.add_pool.mock_calls,
            [unittest.mock.call(name='test-pool', driver='driver1',
                param1='some-value')])
        self.assertTrue(self.app.save.called)

    @unittest.mock.patch('qubes.storage.pool_drivers')
    @unittest.mock.patch('qubes.storage.driver_parameters')
    def test_160_pool_add_invalid_driver(self, mock_parameters, mock_drivers):
        self.app.pools = {
            'file': unittest.mock.Mock(),
            'lvm': unittest.mock.Mock()
        }

        mock_drivers.return_value = ['driver1', 'driver2']
        mock_parameters.side_effect = \
            lambda driver: {
                'driver1': ['param1', 'param2'],
                'driver2': ['param3', 'param4']
            }[driver]

        self.app.add_pool = unittest.mock.Mock()

        with self.assertRaises(AssertionError):
            self.call_mgmt_func(b'admin.pool.Add', b'dom0',
                b'no-such-driver', b'name=test-pool\nparam1=some-value\n')
        self.assertEqual(mock_drivers.mock_calls, [unittest.mock.call()])
        self.assertEqual(mock_parameters.mock_calls, [])
        self.assertEqual(self.app.add_pool.mock_calls, [])
        self.assertFalse(self.app.save.called)


    @unittest.mock.patch('qubes.storage.pool_drivers')
    @unittest.mock.patch('qubes.storage.driver_parameters')
    def test_160_pool_add_invalid_param(self, mock_parameters, mock_drivers):
        self.app.pools = {
            'file': unittest.mock.Mock(),
            'lvm': unittest.mock.Mock()
        }

        mock_drivers.return_value = ['driver1', 'driver2']
        mock_parameters.side_effect = \
            lambda driver: {
                'driver1': ['param1', 'param2'],
                'driver2': ['param3', 'param4']
            }[driver]

        self.app.add_pool = unittest.mock.Mock()

        with self.assertRaises(AssertionError):
            self.call_mgmt_func(b'admin.pool.Add', b'dom0',
                b'driver1', b'name=test-pool\nparam3=some-value\n')
        self.assertEqual(mock_drivers.mock_calls, [unittest.mock.call()])
        self.assertEqual(mock_parameters.mock_calls,
            [unittest.mock.call('driver1')])
        self.assertEqual(self.app.add_pool.mock_calls, [])
        self.assertFalse(self.app.save.called)

    @unittest.mock.patch('qubes.storage.pool_drivers')
    @unittest.mock.patch('qubes.storage.driver_parameters')
    def test_160_pool_add_missing_name(self, mock_parameters, mock_drivers):
        self.app.pools = {
            'file': unittest.mock.Mock(),
            'lvm': unittest.mock.Mock()
        }

        mock_drivers.return_value = ['driver1', 'driver2']
        mock_parameters.side_effect = \
            lambda driver: {
                'driver1': ['param1', 'param2'],
                'driver2': ['param3', 'param4']
            }[driver]

        self.app.add_pool = unittest.mock.Mock()

        with self.assertRaises(AssertionError):
            self.call_mgmt_func(b'admin.pool.Add', b'dom0',
                b'driver1', b'param1=value\nparam2=some-value\n')
        self.assertEqual(mock_drivers.mock_calls, [unittest.mock.call()])
        self.assertEqual(mock_parameters.mock_calls, [])
        self.assertEqual(self.app.add_pool.mock_calls, [])
        self.assertFalse(self.app.save.called)

    @unittest.mock.patch('qubes.storage.pool_drivers')
    @unittest.mock.patch('qubes.storage.driver_parameters')
    def test_160_pool_add_existing_pool(self, mock_parameters, mock_drivers):
        self.app.pools = {
            'file': unittest.mock.Mock(),
            'lvm': unittest.mock.Mock()
        }

        mock_drivers.return_value = ['driver1', 'driver2']
        mock_parameters.side_effect = \
            lambda driver: {
                'driver1': ['param1', 'param2'],
                'driver2': ['param3', 'param4']
            }[driver]

        self.app.add_pool = unittest.mock.Mock()

        with self.assertRaises(AssertionError):
            self.call_mgmt_func(b'admin.pool.Add', b'dom0',
                b'driver1', b'name=file\nparam1=value\nparam2=some-value\n')
        self.assertEqual(mock_drivers.mock_calls, [unittest.mock.call()])
        self.assertEqual(mock_parameters.mock_calls, [])
        self.assertEqual(self.app.add_pool.mock_calls, [])
        self.assertFalse(self.app.save.called)

    @unittest.mock.patch('qubes.storage.pool_drivers')
    @unittest.mock.patch('qubes.storage.driver_parameters')
    def test_160_pool_add_invalid_config_format(self, mock_parameters,
            mock_drivers):
        self.app.pools = {
            'file': unittest.mock.Mock(),
            'lvm': unittest.mock.Mock()
        }

        mock_drivers.return_value = ['driver1', 'driver2']
        mock_parameters.side_effect = \
            lambda driver: {
                'driver1': ['param1', 'param2'],
                'driver2': ['param3', 'param4']
            }[driver]

        self.app.add_pool = unittest.mock.Mock()

        with self.assertRaises(AssertionError):
            self.call_mgmt_func(b'admin.pool.Add', b'dom0',
                b'driver1', b'name=test-pool\nparam 1=value\n_param2\n')
        self.assertEqual(mock_drivers.mock_calls, [unittest.mock.call()])
        self.assertEqual(mock_parameters.mock_calls, [])
        self.assertEqual(self.app.add_pool.mock_calls, [])
        self.assertFalse(self.app.save.called)

    def test_170_pool_remove(self):
        self.app.pools = {
            'file': unittest.mock.Mock(),
            'lvm': unittest.mock.Mock(),
            'test-pool': unittest.mock.Mock(),
        }
        self.app.remove_pool = unittest.mock.Mock()
        value = self.call_mgmt_func(b'admin.pool.Remove', b'dom0', b'test-pool')
        self.assertIsNone(value)
        self.assertEqual(self.app.remove_pool.mock_calls,
            [unittest.mock.call('test-pool')])
        self.assertTrue(self.app.save.called)

    def test_170_pool_remove_invalid_pool(self):
        self.app.pools = {
            'file': unittest.mock.Mock(),
            'lvm': unittest.mock.Mock(),
            'test-pool': unittest.mock.Mock(),
        }
        self.app.remove_pool = unittest.mock.Mock()
        with self.assertRaises(AssertionError):
            self.call_mgmt_func(b'admin.pool.Remove', b'dom0',
                b'no-such-pool')
        self.assertEqual(self.app.remove_pool.mock_calls, [])
        self.assertFalse(self.app.save.called)

    def test_180_label_list(self):
        value = self.call_mgmt_func(b'admin.label.List', b'dom0')
        self.assertEqual(value,
            ''.join('{}\n'.format(l.name) for l in self.app.labels.values()))
        self.assertFalse(self.app.save.called)

    def test_190_label_get(self):
        self.app.get_label = unittest.mock.Mock()
        self.app.get_label.configure_mock(**{'return_value.color': '0xff0000'})
        value = self.call_mgmt_func(b'admin.label.Get', b'dom0', b'red')
        self.assertEqual(value, '0xff0000')
        self.assertEqual(self.app.get_label.mock_calls,
            [unittest.mock.call('red')])
        self.assertFalse(self.app.save.called)

    def test_195_label_index(self):
        self.app.get_label = unittest.mock.Mock()
        self.app.get_label.configure_mock(**{'return_value.index': 1})
        value = self.call_mgmt_func(b'admin.label.Index', b'dom0', b'red')
        self.assertEqual(value, '1')
        self.assertEqual(self.app.get_label.mock_calls,
            [unittest.mock.call('red')])
        self.assertFalse(self.app.save.called)

    def test_200_label_create(self):
        self.app.get_label = unittest.mock.Mock()
        self.app.get_label.side_effect=KeyError
        self.app.labels = unittest.mock.MagicMock()
        labels_config = {
            'keys.return_value': range(1, 9),
        }
        self.app.labels.configure_mock(**labels_config)
        value = self.call_mgmt_func(b'admin.label.Create', b'dom0', b'cyan',
            b'0x00ffff')
        self.assertIsNone(value)
        self.assertEqual(self.app.get_label.mock_calls,
            [unittest.mock.call('cyan')])
        self.assertEqual(self.app.labels.mock_calls,
            [unittest.mock.call.keys(),
            unittest.mock.call.__getattr__('__setitem__')(9,
                qubes.Label(9, '0x00ffff', 'cyan'))])
        self.assertTrue(self.app.save.called)

    def test_200_label_create_invalid_color(self):
        self.app.get_label = unittest.mock.Mock()
        self.app.get_label.side_effect=KeyError
        self.app.labels = unittest.mock.MagicMock()
        labels_config = {
            'keys.return_value': range(1, 9),
        }
        self.app.labels.configure_mock(**labels_config)
        with self.assertRaises(AssertionError):
            self.call_mgmt_func(b'admin.label.Create', b'dom0', b'cyan',
                b'abcd')
        self.assertEqual(self.app.get_label.mock_calls,
            [unittest.mock.call('cyan')])
        self.assertEqual(self.app.labels.mock_calls, [])
        self.assertFalse(self.app.save.called)

    def test_200_label_create_invalid_name(self):
        self.app.get_label = unittest.mock.Mock()
        self.app.get_label.side_effect=KeyError
        self.app.labels = unittest.mock.MagicMock()
        labels_config = {
            'keys.return_value': range(1, 9),
        }
        self.app.labels.configure_mock(**labels_config)
        with self.assertRaises(AssertionError):
            self.call_mgmt_func(b'admin.label.Create', b'dom0', b'01',
                b'0xff0000')
        with self.assertRaises(AssertionError):
            self.call_mgmt_func(b'admin.label.Create', b'dom0', b'../xxx',
                b'0xff0000')
        with self.assertRaises(AssertionError):
            self.call_mgmt_func(b'admin.label.Create', b'dom0',
                b'strange-name!@#$',
                b'0xff0000')

        self.assertEqual(self.app.get_label.mock_calls, [])
        self.assertEqual(self.app.labels.mock_calls, [])
        self.assertFalse(self.app.save.called)

    def test_200_label_create_already_exists(self):
        self.app.get_label = unittest.mock.Mock(wraps=self.app.get_label)
        with self.assertRaises(qubes.exc.QubesValueError):
            self.call_mgmt_func(b'admin.label.Create', b'dom0', b'red',
                b'abcd')
        self.assertEqual(self.app.get_label.mock_calls,
            [unittest.mock.call('red')])
        self.assertFalse(self.app.save.called)

    def test_210_label_remove(self):
        label = qubes.Label(9, '0x00ffff', 'cyan')
        self.app.labels[9] = label
        self.app.get_label = unittest.mock.Mock(wraps=self.app.get_label,
            **{'return_value.index': 9})
        self.app.labels = unittest.mock.MagicMock(wraps=self.app.labels)
        value = self.call_mgmt_func(b'admin.label.Remove', b'dom0', b'cyan')
        self.assertIsNone(value)
        self.assertEqual(self.app.get_label.mock_calls,
            [unittest.mock.call('cyan')])
        self.assertEqual(self.app.labels.mock_calls,
            [unittest.mock.call.__delitem__(9)])
        self.assertTrue(self.app.save.called)

    def test_210_label_remove_invalid_label(self):
        with self.assertRaises(qubes.exc.QubesValueError):
            self.call_mgmt_func(b'admin.label.Remove', b'dom0',
                b'no-such-label')
        self.assertFalse(self.app.save.called)

    def test_210_label_remove_default_label(self):
        self.app.labels = unittest.mock.MagicMock(wraps=self.app.labels)
        self.app.get_label = unittest.mock.Mock(wraps=self.app.get_label,
            **{'return_value.index': 6})
        with self.assertRaises(AssertionError):
            self.call_mgmt_func(b'admin.label.Remove', b'dom0',
                b'blue')
        self.assertEqual(self.app.labels.mock_calls, [])
        self.assertFalse(self.app.save.called)

    def test_210_label_remove_in_use(self):
        self.app.labels = unittest.mock.MagicMock(wraps=self.app.labels)
        self.app.get_label = unittest.mock.Mock(wraps=self.app.get_label,
            **{'return_value.index': 1})
        with self.assertRaises(AssertionError):
            self.call_mgmt_func(b'admin.label.Remove', b'dom0',
                b'red')
        self.assertEqual(self.app.labels.mock_calls, [])
        self.assertFalse(self.app.save.called)

    def test_220_start(self):
        func_mock = unittest.mock.Mock()

        @asyncio.coroutine
        def coroutine_mock(*args, **kwargs):
            return func_mock(*args, **kwargs)
        self.vm.start = coroutine_mock
        value = self.call_mgmt_func(b'admin.vm.Start', b'test-vm1')
        self.assertIsNone(value)
        func_mock.assert_called_once_with()

    def test_230_shutdown(self):
        func_mock = unittest.mock.Mock()

        @asyncio.coroutine
        def coroutine_mock(*args, **kwargs):
            return func_mock(*args, **kwargs)
        self.vm.shutdown = coroutine_mock
        value = self.call_mgmt_func(b'admin.vm.Shutdown', b'test-vm1')
        self.assertIsNone(value)
        func_mock.assert_called_once_with()

    def test_240_pause(self):
        func_mock = unittest.mock.Mock()

        @asyncio.coroutine
        def coroutine_mock(*args, **kwargs):
            return func_mock(*args, **kwargs)
        self.vm.pause = coroutine_mock
        value = self.call_mgmt_func(b'admin.vm.Pause', b'test-vm1')
        self.assertIsNone(value)
        func_mock.assert_called_once_with()

    def test_250_unpause(self):
        func_mock = unittest.mock.Mock()

        @asyncio.coroutine
        def coroutine_mock(*args, **kwargs):
            return func_mock(*args, **kwargs)
        self.vm.unpause = coroutine_mock
        value = self.call_mgmt_func(b'admin.vm.Unpause', b'test-vm1')
        self.assertIsNone(value)
        func_mock.assert_called_once_with()

    def test_260_kill(self):
        func_mock = unittest.mock.Mock()

        @asyncio.coroutine
        def coroutine_mock(*args, **kwargs):
            return func_mock(*args, **kwargs)
        self.vm.kill = coroutine_mock
        value = self.call_mgmt_func(b'admin.vm.Kill', b'test-vm1')
        self.assertIsNone(value)
        func_mock.assert_called_once_with()

    def test_270_events(self):
        send_event = unittest.mock.Mock(spec=[])
        mgmt_obj = qubes.api.admin.QubesAdminAPI(self.app, b'dom0', b'admin.Events',
            b'dom0', b'', send_event=send_event)

        @asyncio.coroutine
        def fire_event():
            self.vm.fire_event('test-event', arg1='abc')
            mgmt_obj.cancel()

        loop = asyncio.get_event_loop()
        execute_task = asyncio.ensure_future(
            mgmt_obj.execute(untrusted_payload=b''))
        asyncio.ensure_future(fire_event())
        loop.run_until_complete(execute_task)
        self.assertIsNone(execute_task.result())
        self.assertEventFired(self.emitter,
            'mgmt-permission:' + 'admin.Events')
        self.assertEqual(send_event.mock_calls,
            [
                unittest.mock.call(self.app, 'connection-established'),
                unittest.mock.call(self.vm, 'test-event', arg1='abc')
            ])

    def test_271_events_add_vm(self):
        send_event = unittest.mock.Mock(spec=[])
        mgmt_obj = qubes.api.admin.QubesAdminAPI(self.app, b'dom0', b'admin.Events',
            b'dom0', b'', send_event=send_event)

        @asyncio.coroutine
        def fire_event():
            self.vm.fire_event('test-event', arg1='abc')
            # add VM _after_ starting admin.Events call
            vm = self.app.add_new_vm('AppVM', label='red', name='test-vm2',
                template='test-template')
            vm.fire_event('test-event2', arg1='abc')
            mgmt_obj.cancel()
            return vm

        loop = asyncio.get_event_loop()
        execute_task = asyncio.ensure_future(
            mgmt_obj.execute(untrusted_payload=b''))
        event_task = asyncio.ensure_future(fire_event())
        loop.run_until_complete(execute_task)
        vm2 = event_task.result()
        self.assertIsNone(execute_task.result())
        self.assertEventFired(self.emitter,
            'mgmt-permission:' + 'admin.Events')
        self.assertEqual(send_event.mock_calls,
            [
                unittest.mock.call(self.app, 'connection-established'),
                unittest.mock.call(self.vm, 'test-event', arg1='abc'),
                unittest.mock.call(self.app, 'domain-add', vm=vm2),
                unittest.mock.call(vm2, 'test-event2', arg1='abc'),
            ])

    def test_280_feature_list(self):
        self.vm.features['test-feature'] = 'some-value'
        value = self.call_mgmt_func(b'admin.vm.feature.List', b'test-vm1')
        self.assertEqual(value, 'test-feature\n')
        self.assertFalse(self.app.save.called)

    def test_290_feature_get(self):
        self.vm.features['test-feature'] = 'some-value'
        value = self.call_mgmt_func(b'admin.vm.feature.Get', b'test-vm1',
            b'test-feature')
        self.assertEqual(value, 'some-value')
        self.assertFalse(self.app.save.called)

    def test_291_feature_get_none(self):
        with self.assertRaises(qubes.exc.QubesFeatureNotFoundError):
            self.call_mgmt_func(b'admin.vm.feature.Get',
                b'test-vm1', b'test-feature')
        self.assertFalse(self.app.save.called)

    def test_300_feature_remove(self):
        self.vm.features['test-feature'] = 'some-value'
        value = self.call_mgmt_func(b'admin.vm.feature.Remove', b'test-vm1',
            b'test-feature')
        self.assertIsNone(value, None)
        self.assertNotIn('test-feature', self.vm.features)
        self.assertTrue(self.app.save.called)

    def test_301_feature_remove_none(self):
        with self.assertRaises(qubes.exc.QubesFeatureNotFoundError):
            self.call_mgmt_func(b'admin.vm.feature.Remove',
                b'test-vm1', b'test-feature')
        self.assertFalse(self.app.save.called)

    def test_310_feature_checkwithtemplate(self):
        self.vm.features['test-feature'] = 'some-value'
        value = self.call_mgmt_func(b'admin.vm.feature.CheckWithTemplate',
            b'test-vm1', b'test-feature')
        self.assertEqual(value, 'some-value')
        self.assertFalse(self.app.save.called)

    def test_311_feature_checkwithtemplate_tpl(self):
        self.template.features['test-feature'] = 'some-value'
        value = self.call_mgmt_func(b'admin.vm.feature.CheckWithTemplate',
            b'test-vm1', b'test-feature')
        self.assertEqual(value, 'some-value')
        self.assertFalse(self.app.save.called)

    def test_312_feature_checkwithtemplate_none(self):
        with self.assertRaises(qubes.exc.QubesFeatureNotFoundError):
            self.call_mgmt_func(b'admin.vm.feature.CheckWithTemplate',
                b'test-vm1', b'test-feature')
        self.assertFalse(self.app.save.called)

    def test_320_feature_set(self):
        value = self.call_mgmt_func(b'admin.vm.feature.Set',
            b'test-vm1', b'test-feature', b'some-value')
        self.assertIsNone(value)
        self.assertEqual(self.vm.features['test-feature'], 'some-value')
        self.assertTrue(self.app.save.called)

    def test_321_feature_set_empty(self):
        value = self.call_mgmt_func(b'admin.vm.feature.Set',
            b'test-vm1', b'test-feature', b'')
        self.assertIsNone(value)
        self.assertEqual(self.vm.features['test-feature'], '')
        self.assertTrue(self.app.save.called)

    def test_320_feature_set_invalid(self):
        with self.assertRaises(UnicodeDecodeError):
            self.call_mgmt_func(b'admin.vm.feature.Set',
                b'test-vm1', b'test-feature', b'\x02\x03\xffsome-value')
        self.assertNotIn('test-feature', self.vm.features)
        self.assertFalse(self.app.save.called)

    @asyncio.coroutine
    def dummy_coro(self, *args, **kwargs):
        pass

    @unittest.mock.patch('qubes.storage.Storage.create')
    def test_330_vm_create_standalone(self, storage_mock):
        storage_mock.side_effect = self.dummy_coro
        self.call_mgmt_func(b'admin.vm.Create.StandaloneVM',
            b'dom0', b'', b'name=test-vm2 label=red')

        self.assertIn('test-vm2', self.app.domains)
        vm = self.app.domains['test-vm2']
        self.assertIsInstance(vm, qubes.vm.standalonevm.StandaloneVM)
        self.assertEqual(vm.label, self.app.get_label('red'))
        self.assertEqual(storage_mock.mock_calls,
            [unittest.mock.call(self.app.domains['test-vm2']).create()])
        self.assertTrue(os.path.exists(os.path.join(
            self.test_base_dir, 'appvms', 'test-vm2')))

        self.assertTrue(self.app.save.called)

    @unittest.mock.patch('qubes.storage.Storage.create')
    def test_331_vm_create_standalone_spurious_template(self, storage_mock):
        storage_mock.side_effect = self.dummy_coro
        with self.assertRaises(AssertionError):
            self.call_mgmt_func(b'admin.vm.Create.StandaloneVM',
                b'dom0', b'test-template', b'name=test-vm2 label=red')

        self.assertNotIn('test-vm2', self.app.domains)
        self.assertEqual(storage_mock.mock_calls, [])
        self.assertFalse(os.path.exists(os.path.join(
            self.test_base_dir, 'appvms', 'test-vm2')))

        self.assertNotIn('test-vm2', self.app.domains)
        self.assertFalse(self.app.save.called)

    @unittest.mock.patch('qubes.storage.Storage.create')
    def test_332_vm_create_app(self, storage_mock):
        storage_mock.side_effect = self.dummy_coro
        self.call_mgmt_func(b'admin.vm.Create.AppVM',
            b'dom0', b'test-template', b'name=test-vm2 label=red')

        self.assertIn('test-vm2', self.app.domains)
        vm = self.app.domains['test-vm2']
        self.assertEqual(vm.label, self.app.get_label('red'))
        self.assertEqual(vm.template, self.app.domains['test-template'])
        self.assertEqual(storage_mock.mock_calls,
            [unittest.mock.call(self.app.domains['test-vm2']).create()])
        self.assertTrue(os.path.exists(os.path.join(
            self.test_base_dir, 'appvms', 'test-vm2')))

        self.assertTrue(self.app.save.called)

    @unittest.mock.patch('qubes.storage.Storage.create')
    def test_333_vm_create_app_missing_template(self, storage_mock):
        storage_mock.side_effect = self.dummy_coro
        with self.assertRaises(AssertionError):
            self.call_mgmt_func(b'admin.vm.Create.AppVM',
                b'dom0', b'', b'name=test-vm2 label=red')

        self.assertNotIn('test-vm2', self.app.domains)
        self.assertEqual(storage_mock.mock_calls, [])
        self.assertFalse(os.path.exists(os.path.join(
            self.test_base_dir, 'appvms', 'test-vm2')))

        self.assertNotIn('test-vm2', self.app.domains)
        self.assertFalse(self.app.save.called)

    @unittest.mock.patch('qubes.storage.Storage.create')
    def test_334_vm_create_invalid_name(self, storage_mock):
        storage_mock.side_effect = self.dummy_coro
        with self.assertRaises(qubes.exc.QubesValueError):
            self.call_mgmt_func(b'admin.vm.Create.AppVM',
                b'dom0', b'test-template', b'name=test-###')

        self.assertNotIn('test-###', self.app.domains)
        self.assertFalse(self.app.save.called)

    @unittest.mock.patch('qubes.storage.Storage.create')
    def test_335_vm_create_missing_name(self, storage_mock):
        storage_mock.side_effect = self.dummy_coro
        with self.assertRaises(AssertionError):
            self.call_mgmt_func(b'admin.vm.Create.AppVM',
                b'dom0', b'test-template', b'label=red')

        self.assertFalse(self.app.save.called)

    @unittest.mock.patch('qubes.storage.Storage.create')
    def test_336_vm_create_spurious_pool(self, storage_mock):
        storage_mock.side_effect = self.dummy_coro
        with self.assertRaises(AssertionError):
            self.call_mgmt_func(b'admin.vm.Create.AppVM',
                b'dom0', b'test-template',
                b'name=test-vm2 label=red pool=default')

        self.assertNotIn('test-vm2', self.app.domains)
        self.assertFalse(self.app.save.called)

    @unittest.mock.patch('qubes.storage.Storage.create')
    def test_337_vm_create_duplicate_name(self, storage_mock):
        storage_mock.side_effect = self.dummy_coro
        with self.assertRaises(qubes.exc.QubesException):
            self.call_mgmt_func(b'admin.vm.Create.AppVM',
                b'dom0', b'test-template',
                b'name=test-vm1 label=red')

        self.assertFalse(self.app.save.called)

    @unittest.mock.patch('qubes.storage.Storage.create')
    def test_338_vm_create_name_twice(self, storage_mock):
        storage_mock.side_effect = self.dummy_coro
        with self.assertRaises(AssertionError):
            self.call_mgmt_func(b'admin.vm.Create.AppVM',
                b'dom0', b'test-template',
                b'name=test-vm2 name=test-vm3 label=red')

        self.assertNotIn('test-vm2', self.app.domains)
        self.assertNotIn('test-vm3', self.app.domains)
        self.assertFalse(self.app.save.called)

    @unittest.mock.patch('qubes.storage.Storage.create')
    def test_340_vm_create_in_pool_app(self, storage_mock):
        storage_mock.side_effect = self.dummy_coro
        self.call_mgmt_func(b'admin.vm.CreateInPool.AppVM',
            b'dom0', b'test-template', b'name=test-vm2 label=red '
                                 b'pool=test')

        self.assertIn('test-vm2', self.app.domains)
        vm = self.app.domains['test-vm2']
        self.assertEqual(vm.label, self.app.get_label('red'))
        self.assertEqual(vm.template, self.app.domains['test-template'])
        # setting pool= affect only volumes actually created for this VM,
        # not used from a template or so
        self.assertEqual(vm.volume_config['root']['pool'], 'default')
        self.assertEqual(vm.volume_config['private']['pool'], 'test')
        self.assertEqual(vm.volume_config['volatile']['pool'], 'test')
        self.assertEqual(vm.volume_config['kernel']['pool'], 'linux-kernel')
        self.assertEqual(storage_mock.mock_calls,
            [unittest.mock.call(self.app.domains['test-vm2']).create()])
        self.assertTrue(os.path.exists(os.path.join(
            self.test_base_dir, 'appvms', 'test-vm2')))

        self.assertTrue(self.app.save.called)

    @unittest.mock.patch('qubes.storage.Storage.create')
    def test_341_vm_create_in_pool_private(self, storage_mock):
        storage_mock.side_effect = self.dummy_coro
        self.call_mgmt_func(b'admin.vm.CreateInPool.AppVM',
            b'dom0', b'test-template', b'name=test-vm2 label=red '
                                 b'pool:private=test')

        self.assertIn('test-vm2', self.app.domains)
        vm = self.app.domains['test-vm2']
        self.assertEqual(vm.label, self.app.get_label('red'))
        self.assertEqual(vm.template, self.app.domains['test-template'])
        self.assertEqual(vm.volume_config['root']['pool'], 'default')
        self.assertEqual(vm.volume_config['private']['pool'], 'test')
        self.assertEqual(vm.volume_config['volatile']['pool'], 'default')
        self.assertEqual(vm.volume_config['kernel']['pool'], 'linux-kernel')
        self.assertEqual(storage_mock.mock_calls,
            [unittest.mock.call(self.app.domains['test-vm2']).create()])
        self.assertTrue(os.path.exists(os.path.join(
            self.test_base_dir, 'appvms', 'test-vm2')))

        self.assertTrue(self.app.save.called)

    @unittest.mock.patch('qubes.storage.Storage.create')
    def test_342_vm_create_in_pool_invalid_pool(self, storage_mock):
        storage_mock.side_effect = self.dummy_coro
        with self.assertRaises(qubes.exc.QubesException):
            self.call_mgmt_func(b'admin.vm.CreateInPool.AppVM',
                b'dom0', b'test-template', b'name=test-vm2 label=red '
                                     b'pool=no-such-pool')

        self.assertFalse(self.app.save.called)

    @unittest.mock.patch('qubes.storage.Storage.create')
    def test_343_vm_create_in_pool_invalid_pool2(self, storage_mock):
        storage_mock.side_effect = self.dummy_coro
        with self.assertRaises(qubes.exc.QubesException):
            self.call_mgmt_func(b'admin.vm.CreateInPool.AppVM',
                b'dom0', b'test-template', b'name=test-vm2 label=red '
                                     b'pool:private=no-such-pool')

        self.assertNotIn('test-vm2', self.app.domains)
        self.assertFalse(self.app.save.called)

    @unittest.mock.patch('qubes.storage.Storage.create')
    def test_344_vm_create_in_pool_invalid_volume(self, storage_mock):
        storage_mock.side_effect = self.dummy_coro
        with self.assertRaises(AssertionError):
            self.call_mgmt_func(b'admin.vm.CreateInPool.AppVM',
                b'dom0', b'test-template', b'name=test-vm2 label=red '
                                     b'pool:invalid=test')

        self.assertNotIn('test-vm2', self.app.domains)
        self.assertFalse(self.app.save.called)

    @unittest.mock.patch('qubes.storage.Storage.create')
    def test_345_vm_create_in_pool_app_root(self, storage_mock):
        # setting custom pool for 'root' volume of AppVM should not be
        # allowed - this volume belongs to the template
        storage_mock.side_effect = self.dummy_coro
        with self.assertRaises(qubes.exc.QubesException):
            self.call_mgmt_func(b'admin.vm.CreateInPool.AppVM',
                b'dom0', b'test-template', b'name=test-vm2 label=red '
                                     b'pool:root=test')

        self.assertNotIn('test-vm2', self.app.domains)
        self.assertFalse(self.app.save.called)

    @unittest.mock.patch('qubes.storage.Storage.create')
    def test_346_vm_create_in_pool_duplicate_pool(self, storage_mock):
        # setting custom pool for 'root' volume of AppVM should not be
        # allowed - this volume belongs to the template
        storage_mock.side_effect = self.dummy_coro
        with self.assertRaises(AssertionError):
            self.call_mgmt_func(b'admin.vm.CreateInPool.AppVM',
                b'dom0', b'test-template', b'name=test-vm2 label=red '
                b'pool=test pool:root=test')

        self.assertNotIn('test-vm2', self.app.domains)
        self.assertFalse(self.app.save.called)

    @unittest.mock.patch('qubes.storage.Storage.clone')
    @unittest.mock.patch('qubes.storage.Storage.verify')
    def test_350_vm_clone(self, mock_verify, mock_clone):
        mock_clone.side_effect = self.dummy_coro
        mock_verify.side_effect = self.dummy_coro
        self.call_mgmt_func(b'admin.vm.Clone',
            b'test-vm1', b'', b'name=test-vm2')

        self.assertIn('test-vm2', self.app.domains)
        vm = self.app.domains['test-vm2']
        self.assertEqual(vm.label, self.app.get_label('red'))
        self.assertEqual(vm.template, self.app.domains['test-template'])
        self.assertEqual(mock_clone.mock_calls,
            [unittest.mock.call(self.app.domains['test-vm2']).clone(
                self.app.domains['test-vm1'])])
        self.assertTrue(os.path.exists(os.path.join(
            self.test_base_dir, 'appvms', 'test-vm2')))

        self.assertTrue(self.app.save.called)

    @unittest.mock.patch('qubes.storage.Storage.clone')
    @unittest.mock.patch('qubes.storage.Storage.verify')
    def test_351_vm_clone_extra_params(self, mock_verify, mock_clone):
        mock_clone.side_effect = self.dummy_coro
        mock_verify.side_effect = self.dummy_coro
        with self.assertRaises(qubes.exc.QubesException):
            self.call_mgmt_func(b'admin.vm.Clone',
                b'test-vm1', b'', b'name=test-vm2 label=red')

        self.assertNotIn('test-vm2', self.app.domains)
        self.assertEqual(mock_clone.mock_calls, [])
        self.assertFalse(os.path.exists(os.path.join(
            self.test_base_dir, 'appvms', 'test-vm2')))

        self.assertFalse(self.app.save.called)

    @unittest.mock.patch('qubes.storage.Storage.clone')
    @unittest.mock.patch('qubes.storage.Storage.verify')
    def test_352_vm_clone_duplicate_name(self, mock_verify, mock_clone):
        mock_clone.side_effect = self.dummy_coro
        mock_verify.side_effect = self.dummy_coro
        with self.assertRaises(qubes.exc.QubesException):
            self.call_mgmt_func(b'admin.vm.Clone',
                b'test-vm1', b'', b'name=test-vm1')

        self.assertFalse(self.app.save.called)

    @unittest.mock.patch('qubes.storage.Storage.clone')
    @unittest.mock.patch('qubes.storage.Storage.verify')
    def test_353_vm_clone_invalid_name(self, mock_verify, mock_clone):
        mock_clone.side_effect = self.dummy_coro
        mock_verify.side_effect = self.dummy_coro
        with self.assertRaises(qubes.exc.QubesException):
            self.call_mgmt_func(b'admin.vm.Clone',
                b'test-vm1', b'', b'name=test-vm2/..')

        self.assertNotIn('test-vm2/..', self.app.domains)
        self.assertEqual(mock_clone.mock_calls, [])
        self.assertFalse(os.path.exists(os.path.join(
            self.test_base_dir, 'appvms', 'test-vm2/..')))

        self.assertFalse(self.app.save.called)

    def test_990_vm_unexpected_payload(self):
        methods_with_no_payload = [
            b'admin.vm.List',
            b'admin.vm.Remove',
            b'admin.vm.property.List',
            b'admin.vm.property.Get',
            b'admin.vm.property.Help',
            b'admin.vm.property.HelpRst',
            b'admin.vm.property.Reset',
            b'admin.vm.feature.List',
            b'admin.vm.feature.Get',
            b'admin.vm.feature.CheckWithTemplate',
            b'admin.vm.feature.Remove',
            b'admin.vm.tag.List',
            b'admin.vm.tag.Get',
            b'admin.vm.tag.Remove',
            b'admin.vm.tag.Set',
            b'admin.vm.firewall.Get',
            b'admin.vm.firewall.RemoveRule',
            b'admin.vm.firewall.Flush',
            b'admin.vm.device.pci.Attach',
            b'admin.vm.device.pci.Detach',
            b'admin.vm.device.pci.List',
            b'admin.vm.device.pci.Available',
            b'admin.vm.microphone.Attach',
            b'admin.vm.microphone.Detach',
            b'admin.vm.microphone.Status',
            b'admin.vm.volume.ListSnapshots',
            b'admin.vm.volume.List',
            b'admin.vm.volume.Info',
            b'admin.vm.Start',
            b'admin.vm.Shutdown',
            b'admin.vm.Pause',
            b'admin.vm.Unpause',
            b'admin.vm.Kill',
            b'admin.Events',
            b'admin.vm.feature.List',
            b'admin.vm.feature.Get',
            b'admin.vm.feature.Remove',
            b'admin.vm.feature.CheckWithTemplate',
        ]
        # make sure also no methods on actual VM gets called
        vm_mock = unittest.mock.MagicMock()
        vm_mock.name = self.vm.name
        vm_mock.qid = self.vm.qid
        vm_mock.__lt__ = (lambda x, y: x.qid < y.qid)
        self.app.domains._dict[self.vm.qid] = vm_mock
        for method in methods_with_no_payload:
            # should reject payload regardless of having argument or not
            with self.subTest(method.decode('ascii')):
                with self.assertRaises(AssertionError):
                    self.call_mgmt_func(method, b'test-vm1', b'',
                        b'unexpected-payload')
                self.assertFalse(vm_mock.called)
                self.assertFalse(self.app.save.called)

            with self.subTest(method.decode('ascii') + '+arg'):
                with self.assertRaises(AssertionError):
                    self.call_mgmt_func(method, b'test-vm1', b'some-arg',
                        b'unexpected-payload')
                self.assertFalse(vm_mock.called)
                self.assertFalse(self.app.save.called)

    def test_991_vm_unexpected_argument(self):
        methods_with_no_argument = [
            b'admin.vm.List',
            b'admin.vm.Clone',
            b'admin.vm.Remove',
            b'admin.vm.property.List',
            b'admin.vm.feature.List',
            b'admin.vm.tag.List',
            b'admin.vm.firewall.List',
            b'admin.vm.firewall.Flush',
            b'admin.vm.device.pci.List',
            b'admin.vm.device.pci.Available',
            b'admin.vm.microphone.Attach',
            b'admin.vm.microphone.Detach',
            b'admin.vm.microphone.Status',
            b'admin.vm.volume.List',
            b'admin.vm.Start',
            b'admin.vm.Shutdown',
            b'admin.vm.Pause',
            b'admin.vm.Unpause',
            b'admin.vm.Kill',
            b'admin.Events',
            b'admin.vm.feature.List',
        ]
        # make sure also no methods on actual VM gets called
        vm_mock = unittest.mock.MagicMock()
        vm_mock.name = self.vm.name
        vm_mock.qid = self.vm.qid
        vm_mock.__lt__ = (lambda x, y: x.qid < y.qid)
        self.app.domains._dict[self.vm.qid] = vm_mock
        for method in methods_with_no_argument:
            # should reject argument regardless of having payload or not
            with self.subTest(method.decode('ascii')):
                with self.assertRaises(AssertionError):
                    self.call_mgmt_func(method, b'test-vm1', b'some-arg',
                        b'')
                self.assertFalse(vm_mock.called)
                self.assertFalse(self.app.save.called)

            with self.subTest(method.decode('ascii') + '+payload'):
                with self.assertRaises(AssertionError):
                    self.call_mgmt_func(method, b'test-vm1', b'unexpected-arg',
                        b'some-payload')
                self.assertFalse(vm_mock.called)
                self.assertFalse(self.app.save.called)

    def test_992_dom0_unexpected_payload(self):
        methods_with_no_payload = [
            b'admin.vmclass.List',
            b'admin.vm.List',
            b'admin.label.List',
            b'admin.label.Get',
            b'admin.label.Remove',
            b'admin.property.List',
            b'admin.property.Get',
            b'admin.property.Help',
            b'admin.property.HelpRst',
            b'admin.property.Reset',
            b'admin.pool.List',
            b'admin.pool.ListDrivers',
            b'admin.pool.Info',
            b'admin.pool.Remove',
            b'admin.backup.Execute',
            b'admin.Events',
        ]
        # make sure also no methods on actual VM gets called
        vm_mock = unittest.mock.MagicMock()
        vm_mock.name = self.vm.name
        vm_mock.qid = self.vm.qid
        vm_mock.__lt__ = (lambda x, y: x.qid < y.qid)
        self.app.domains._dict[self.vm.qid] = vm_mock
        for method in methods_with_no_payload:
            # should reject payload regardless of having argument or not
            with self.subTest(method.decode('ascii')):
                with self.assertRaises(AssertionError):
                    self.call_mgmt_func(method, b'dom0', b'',
                        b'unexpected-payload')
                self.assertFalse(vm_mock.called)
                self.assertFalse(self.app.save.called)

            with self.subTest(method.decode('ascii') + '+arg'):
                with self.assertRaises(AssertionError):
                    self.call_mgmt_func(method, b'dom0', b'some-arg',
                        b'unexpected-payload')
                self.assertFalse(vm_mock.called)
                self.assertFalse(self.app.save.called)

    def test_993_dom0_unexpected_argument(self):
        methods_with_no_argument = [
            b'admin.vmclass.List',
            b'admin.vm.List',
            b'admin.label.List',
            b'admin.property.List',
            b'admin.pool.List',
            b'admin.pool.ListDrivers',
            b'admin.Events',
        ]
        # make sure also no methods on actual VM gets called
        vm_mock = unittest.mock.MagicMock()
        vm_mock.name = self.vm.name
        vm_mock.qid = self.vm.qid
        vm_mock.__lt__ = (lambda x, y: x.qid < y.qid)
        self.app.domains._dict[self.vm.qid] = vm_mock
        for method in methods_with_no_argument:
            # should reject argument regardless of having payload or not
            with self.subTest(method.decode('ascii')):
                with self.assertRaises(AssertionError):
                    self.call_mgmt_func(method, b'dom0', b'some-arg',
                        b'')
                self.assertFalse(vm_mock.called)
                self.assertFalse(self.app.save.called)

            with self.subTest(method.decode('ascii') + '+payload'):
                with self.assertRaises(AssertionError):
                    self.call_mgmt_func(method, b'dom0', b'unexpected-arg',
                        b'some-payload')
                self.assertFalse(vm_mock.called)
                self.assertFalse(self.app.save.called)

    def test_994_dom0_only_calls(self):
        # TODO set some better arguments, to make sure the call was rejected
        # because of invalid destination, not invalid arguments
        methods_for_dom0_only = [
            b'admin.vmclass.List',
            b'admin.vm.Create.AppVM',
            b'admin.vm.CreateInPool.AppVM',
            b'admin.vm.CreateTemplate',
            b'admin.label.List',
            b'admin.label.Create',
            b'admin.label.Get',
            b'admin.label.Remove',
            b'admin.property.List',
            b'admin.property.Get',
            b'admin.property.Set',
            b'admin.property.Help',
            b'admin.property.HelpRst',
            b'admin.property.Reset',
            b'admin.pool.List',
            b'admin.pool.ListDrivers',
            b'admin.pool.Info',
            b'admin.pool.Add',
            b'admin.pool.Remove',
            b'admin.pool.volume.List',
            b'admin.pool.volume.Info',
            b'admin.pool.volume.ListSnapshots',
            b'admin.pool.volume.Snapshot',
            b'admin.pool.volume.Revert',
            b'admin.pool.volume.Resize',
            b'admin.backup.Execute',
            b'admin.backup.Info',
            b'admin.backup.Restore',
        ]
        # make sure also no methods on actual VM gets called
        vm_mock = unittest.mock.MagicMock()
        vm_mock.name = self.vm.name
        vm_mock.qid = self.vm.qid
        vm_mock.__lt__ = (lambda x, y: x.qid < y.qid)
        self.app.domains._dict[self.vm.qid] = vm_mock
        for method in methods_for_dom0_only:
            # should reject call regardless of having payload or not
            with self.subTest(method.decode('ascii')):
                with self.assertRaises(AssertionError):
                    self.call_mgmt_func(method, b'test-vm1', b'',
                        b'')
                self.assertFalse(vm_mock.called)
                self.assertFalse(self.app.save.called)

            with self.subTest(method.decode('ascii') + '+arg'):
                with self.assertRaises(AssertionError):
                    self.call_mgmt_func(method, b'test-vm1', b'some-arg',
                        b'')
                self.assertFalse(vm_mock.called)
                self.assertFalse(self.app.save.called)

            with self.subTest(method.decode('ascii') + '+payload'):
                with self.assertRaises(AssertionError):
                    self.call_mgmt_func(method, b'test-vm1', b'',
                        b'payload')
                self.assertFalse(vm_mock.called)
                self.assertFalse(self.app.save.called)

            with self.subTest(method.decode('ascii') + '+arg+payload'):
                with self.assertRaises(AssertionError):
                    self.call_mgmt_func(method, b'test-vm1', b'some-arg',
                        b'some-payload')
                self.assertFalse(vm_mock.called)
                self.assertFalse(self.app.save.called)

    @unittest.skip('undecided')
    def test_995_vm_only_calls(self):
        # XXX is it really a good idea to prevent those calls this early?
        # TODO set some better arguments, to make sure the call was rejected
        # because of invalid destination, not invalid arguments
        methods_for_vm_only = [
            b'admin.vm.Clone',
            b'admin.vm.Remove',
            b'admin.vm.property.List',
            b'admin.vm.property.Get',
            b'admin.vm.property.Set',
            b'admin.vm.property.Help',
            b'admin.vm.property.HelpRst',
            b'admin.vm.property.Reset',
            b'admin.vm.feature.List',
            b'admin.vm.feature.Get',
            b'admin.vm.feature.Set',
            b'admin.vm.feature.CheckWithTemplate',
            b'admin.vm.feature.Remove',
            b'admin.vm.tag.List',
            b'admin.vm.tag.Get',
            b'admin.vm.tag.Remove',
            b'admin.vm.tag.Set',
            b'admin.vm.firewall.Get',
            b'admin.vm.firewall.RemoveRule',
            b'admin.vm.firewall.InsertRule',
            b'admin.vm.firewall.Flush',
            b'admin.vm.device.pci.Attach',
            b'admin.vm.device.pci.Detach',
            b'admin.vm.device.pci.List',
            b'admin.vm.device.pci.Available',
            b'admin.vm.microphone.Attach',
            b'admin.vm.microphone.Detach',
            b'admin.vm.microphone.Status',
            b'admin.vm.volume.ListSnapshots',
            b'admin.vm.volume.List',
            b'admin.vm.volume.Info',
            b'admin.vm.volume.Revert',
            b'admin.vm.volume.Resize',
            b'admin.vm.Start',
            b'admin.vm.Shutdown',
            b'admin.vm.Pause',
            b'admin.vm.Unpause',
            b'admin.vm.Kill',
            b'admin.vm.feature.List',
            b'admin.vm.feature.Get',
            b'admin.vm.feature.Set',
            b'admin.vm.feature.Remove',
            b'admin.vm.feature.CheckWithTemplate',
        ]
        # make sure also no methods on actual VM gets called
        vm_mock = unittest.mock.MagicMock()
        vm_mock.name = self.vm.name
        vm_mock.qid = self.vm.qid
        vm_mock.__lt__ = (lambda x, y: x.qid < y.qid)
        self.app.domains._dict[self.vm.qid] = vm_mock
        for method in methods_for_vm_only:
            # should reject payload regardless of having argument or not
            # should reject call regardless of having payload or not
            with self.subTest(method.decode('ascii')):
                with self.assertRaises(AssertionError):
                    self.call_mgmt_func(method, b'dom0', b'',
                        b'')
                self.assertFalse(vm_mock.called)
                self.assertFalse(self.app.save.called)

            with self.subTest(method.decode('ascii') + '+arg'):
                with self.assertRaises(AssertionError):
                    self.call_mgmt_func(method, b'dom0', b'some-arg',
                        b'')
                self.assertFalse(vm_mock.called)
                self.assertFalse(self.app.save.called)

            with self.subTest(method.decode('ascii') + '+payload'):
                with self.assertRaises(AssertionError):
                    self.call_mgmt_func(method, b'dom0', b'',
                        b'payload')
                self.assertFalse(vm_mock.called)
                self.assertFalse(self.app.save.called)

            with self.subTest(method.decode('ascii') + '+arg+payload'):
                with self.assertRaises(AssertionError):
                    self.call_mgmt_func(method, b'dom0', b'some-arg',
                        b'some-payload')
                self.assertFalse(vm_mock.called)
                self.assertFalse(self.app.save.called)
