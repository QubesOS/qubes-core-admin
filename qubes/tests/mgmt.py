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
import libvirt
import unittest.mock

import qubes
import qubes.tests
import qubes.mgmt


class MgmtTestCase(qubes.tests.QubesTestCase):
    def setUp(self):
        super().setUp()
        app = qubes.Qubes('/tmp/qubes-test.xml', load=False)
        app.vmm = unittest.mock.Mock(spec=qubes.app.VMMConnection)
        app.load_initial_values()
        app.default_kernel = '1.0'
        app.default_netvm = None
        app.add_new_vm('TemplateVM', label='black', name='test-template')
        app.default_template = 'test-template'
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

    def call_mgmt_func(self, method, dest, arg=b'', payload=b''):
        mgmt_obj = qubes.mgmt.QubesMgmt(self.app, b'dom0', method, dest, arg)

        loop = asyncio.get_event_loop()
        response = loop.run_until_complete(
            mgmt_obj.execute(untrusted_payload=payload))
        self.assertEventFired(self.emitter,
            'mgmt-permission:' + method.decode('ascii'))
        return response


class TC_00_VMs(MgmtTestCase):
    def test_000_vm_list(self):
        value = self.call_mgmt_func(b'mgmt.vm.List', b'dom0')
        self.assertEqual(value,
            'dom0 class=AdminVM state=Running\n'
            'test-template class=TemplateVM state=Halted\n'
            'test-vm1 class=AppVM state=Halted\n')

    def test_001_vm_list_single(self):
        value = self.call_mgmt_func(b'mgmt.vm.List', b'test-vm1')
        self.assertEqual(value,
            'test-vm1 class=AppVM state=Halted\n')

    def test_002_vm_list_unexpected_arg(self):
        with self.assertRaises(AssertionError):
            self.call_mgmt_func(b'mgmt.vm.List', b'dom0', b'test-vm1', b'')

    def test_003_vm_list_unexpected_payload(self):
        with self.assertRaises(AssertionError):
            self.call_mgmt_func(b'mgmt.vm.List', b'dom0', b'', b'test-vm1')

    def test_010_vm_property_list(self):
        # this test is kind of stupid, but at least check if appropriate
        # mgmt-permission event is fired
        value = self.call_mgmt_func(b'mgmt.vm.property.List', b'test-vm1')
        properties = self.app.domains['test-vm1'].property_list()
        self.assertEqual(value,
            ''.join('{}\n'.format(prop.__name__) for prop in properties))

    def test_020_vm_property_get_str(self):
        value = self.call_mgmt_func(b'mgmt.vm.property.Get', b'test-vm1',
            b'name')
        self.assertEqual(value, 'default=False type=str test-vm1')

    def test_021_vm_property_get_int(self):
        value = self.call_mgmt_func(b'mgmt.vm.property.Get', b'test-vm1',
            b'vcpus')
        self.assertEqual(value, 'default=True type=int 42')

    def test_022_vm_property_get_bool(self):
        value = self.call_mgmt_func(b'mgmt.vm.property.Get', b'test-vm1',
            b'provides_network')
        self.assertEqual(value, 'default=True type=bool False')

    def test_023_vm_property_get_label(self):
        value = self.call_mgmt_func(b'mgmt.vm.property.Get', b'test-vm1',
            b'label')
        self.assertEqual(value, 'default=False type=label red')

    def test_024_vm_property_get_vm(self):
        value = self.call_mgmt_func(b'mgmt.vm.property.Get', b'test-vm1',
            b'template')
        self.assertEqual(value, 'default=False type=vm test-template')

    def test_025_vm_property_get_vm_none(self):
        value = self.call_mgmt_func(b'mgmt.vm.property.Get', b'test-vm1',
            b'netvm')
        self.assertEqual(value, 'default=True type=vm ')

    def test_030_vm_property_set_vm(self):
        netvm = self.app.add_new_vm('AppVM', label='red', name='test-net',
            template='test-template', provides_network=True)

        with unittest.mock.patch('qubes.vm.VMProperty.__set__') as mock:
            value = self.call_mgmt_func(b'mgmt.vm.property.Set', b'test-vm1',
                b'netvm', b'test-net')
            self.assertIsNone(value)
            mock.assert_called_once_with(self.vm, netvm)
        self.app.save.assert_called_once_with()

    def test_031_vm_property_set_vm_invalid1(self):
        with unittest.mock.patch('qubes.vm.VMProperty.__set__') as mock:
            with self.assertRaises(qubes.exc.QubesValueError):
                self.call_mgmt_func(b'mgmt.vm.property.Set', b'test-vm1',
                    b'netvm', b'no-such-vm')
            self.assertFalse(mock.called)
        self.assertFalse(self.app.save.called)

    def test_032_vm_property_set_vm_invalid2(self):
        with unittest.mock.patch('qubes.vm.VMProperty.__set__') as mock:
            with self.assertRaises(qubes.exc.QubesValueError):
                self.call_mgmt_func(b'mgmt.vm.property.Set', b'test-vm1',
                    b'netvm', b'forbidden-chars/../!')
            self.assertFalse(mock.called)
        self.assertFalse(self.app.save.called)

    def test_033_vm_property_set_vm_invalid3(self):
        with unittest.mock.patch('qubes.vm.VMProperty.__set__') as mock:
            with self.assertRaises(qubes.exc.QubesValueError):
                self.call_mgmt_func(b'mgmt.vm.property.Set', b'test-vm1',
                    b'netvm', b'\x80\x90\xa0')
            self.assertFalse(mock.called)
        self.assertFalse(self.app.save.called)

    def test_034_vm_propert_set_bool_true(self):
        with unittest.mock.patch('qubes.property.__set__') as mock:
            value = self.call_mgmt_func(b'mgmt.vm.property.Set', b'test-vm1',
                b'autostart', b'True')
            self.assertIsNone(value)
            mock.assert_called_once_with(self.vm, True)
        self.app.save.assert_called_once_with()

    def test_035_vm_propert_set_bool_false(self):
        with unittest.mock.patch('qubes.property.__set__') as mock:
            value = self.call_mgmt_func(b'mgmt.vm.property.Set', b'test-vm1',
                b'autostart', b'False')
            self.assertIsNone(value)
            mock.assert_called_once_with(self.vm, False)
        self.app.save.assert_called_once_with()

    def test_036_vm_propert_set_bool_invalid1(self):
        with unittest.mock.patch('qubes.property.__set__') as mock:
            with self.assertRaises(qubes.exc.QubesValueError):
                self.call_mgmt_func(b'mgmt.vm.property.Set', b'test-vm1',
                    b'autostart', b'some string')
            self.assertFalse(mock.called)
        self.assertFalse(self.app.save.called)

    def test_037_vm_propert_set_bool_invalid2(self):
        with unittest.mock.patch('qubes.property.__set__') as mock:
            with self.assertRaises(qubes.exc.QubesValueError):
                self.call_mgmt_func(b'mgmt.vm.property.Set', b'test-vm1',
                    b'autostart', b'\x80\x90@#$%^&*(')
            self.assertFalse(mock.called)
        self.assertFalse(self.app.save.called)

    def test_038_vm_propert_set_str(self):
        with unittest.mock.patch('qubes.property.__set__') as mock:
            value = self.call_mgmt_func(b'mgmt.vm.property.Set', b'test-vm1',
                b'kernel', b'1.0')
            self.assertIsNone(value)
            mock.assert_called_once_with(self.vm, '1.0')
        self.app.save.assert_called_once_with()

    def test_039_vm_propert_set_str_invalid1(self):
        with unittest.mock.patch('qubes.property.__set__') as mock:
            with self.assertRaises(qubes.exc.QubesValueError):
                self.call_mgmt_func(b'mgmt.vm.property.Set', b'test-vm1',
                    b'kernel', b'some, non-ASCII: \x80\xd2')
            self.assertFalse(mock.called)
        self.assertFalse(self.app.save.called)

    def test_040_vm_propert_set_int(self):
        with unittest.mock.patch('qubes.property.__set__') as mock:
            value = self.call_mgmt_func(b'mgmt.vm.property.Set', b'test-vm1',
                b'maxmem', b'1024000')
            self.assertIsNone(value)
            mock.assert_called_once_with(self.vm, 1024000)
        self.app.save.assert_called_once_with()

    def test_041_vm_propert_set_int_invalid1(self):
        with unittest.mock.patch('qubes.property.__set__') as mock:
            with self.assertRaises(qubes.exc.QubesValueError):
                self.call_mgmt_func(b'mgmt.vm.property.Set', b'test-vm1',
                    b'maxmem', b'fourty two')
            self.assertFalse(mock.called)
        self.assertFalse(self.app.save.called)

    def test_042_vm_propert_set_label(self):
        with unittest.mock.patch('qubes.property.__set__') as mock:
            value = self.call_mgmt_func(b'mgmt.vm.property.Set', b'test-vm1',
                b'label', b'green')
            self.assertIsNone(value)
            mock.assert_called_once_with(self.vm, 'green')
        self.app.save.assert_called_once_with()

    def test_043_vm_propert_set_label_invalid1(self):
        with unittest.mock.patch('qubes.property.__set__') as mock:
            with self.assertRaises(qubes.exc.QubesValueError):
                self.call_mgmt_func(b'mgmt.vm.property.Set', b'test-vm1',
                    b'maxmem', b'some, non-ASCII: \x80\xd2')
            self.assertFalse(mock.called)
        self.assertFalse(self.app.save.called)

    @unittest.skip('label existence not checked before actual setter yet')
    def test_044_vm_propert_set_label_invalid2(self):
        with unittest.mock.patch('qubes.property.__set__') as mock:
            with self.assertRaises(qubes.exc.QubesValueError):
                self.call_mgmt_func(b'mgmt.vm.property.Set', b'test-vm1',
                    b'maxmem', b'non-existing-color')
            self.assertFalse(mock.called)
        self.assertFalse(self.app.save.called)

    def test_050_vm_property_help(self):
        value = self.call_mgmt_func(b'mgmt.vm.property.Help', b'test-vm1',
            b'label')
        self.assertEqual(value,
            'Colourful label assigned to VM. This is where the colour of the '
            'padlock is set.')
        self.assertFalse(self.app.save.called)

    def test_051_vm_property_help_unexpected_payload(self):
        with self.assertRaises(AssertionError):
            self.call_mgmt_func(b'mgmt.vm.property.Help', b'test-vm1',
                b'label', b'asdasd')

        self.assertFalse(self.app.save.called)

    def test_052_vm_property_help_invalid_property(self):
        with self.assertRaises(AssertionError):
            self.call_mgmt_func(b'mgmt.vm.property.Help', b'test-vm1',
                b'no-such-property')

        self.assertFalse(self.app.save.called)

    def test_060_vm_property_reset(self):
        with unittest.mock.patch('qubes.property.__delete__') as mock:
            value = self.call_mgmt_func(b'mgmt.vm.property.Reset', b'test-vm1',
                b'default_user')
            mock.assert_called_with(self.vm)
        self.assertIsNone(value)
        self.app.save.assert_called_once_with()

    def test_061_vm_property_reset_unexpected_payload(self):
        with unittest.mock.patch('qubes.property.__delete__') as mock:
            with self.assertRaises(AssertionError):
                self.call_mgmt_func(b'mgmt.vm.property.Help', b'test-vm1',
                    b'label', b'asdasd')
            self.assertFalse(mock.called)
        self.assertFalse(self.app.save.called)

    def test_062_vm_property_reset_invalid_property(self):
        with unittest.mock.patch('qubes.property.__delete__') as mock:
            with self.assertRaises(AssertionError):
                self.call_mgmt_func(b'mgmt.vm.property.Help', b'test-vm1',
                    b'no-such-property')
            self.assertFalse(mock.called)
        self.assertFalse(self.app.save.called)
