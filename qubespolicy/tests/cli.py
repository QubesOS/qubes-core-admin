# -*- encoding: utf-8 -*-
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
import os
import tempfile
import unittest.mock

import shutil

import qubes.tests
import qubespolicy
import qubespolicy.cli
import qubespolicy.tests



class TC_00_qrexec_policy(qubes.tests.QubesTestCase):
    def setUp(self):
        super(TC_00_qrexec_policy, self).setUp()
        self.policy_patch = unittest.mock.patch('qubespolicy.Policy')
        self.policy_mock = self.policy_patch.start()

        self.system_info_patch = unittest.mock.patch(
            'qubespolicy.get_system_info')
        self.system_info_mock = self.system_info_patch.start()

        self.system_info = {
            'domains': {'dom0': {'icon': 'black', 'template_for_dispvms': False},
                'test-vm1': {'icon': 'red', 'template_for_dispvms': False},
                'test-vm2': {'icon': 'red', 'template_for_dispvms': False},
                'test-vm3': {'icon': 'green', 'template_for_dispvms': True}, }}
        self.system_info_mock.return_value = self.system_info

        self.dbus_patch = unittest.mock.patch('pydbus.SystemBus')
        self.dbus_mock = self.dbus_patch.start()

        self.policy_dir = tempfile.TemporaryDirectory()
        self.policydir_patch = unittest.mock.patch('qubespolicy.POLICY_DIR',
            self.policy_dir.name)
        self.policydir_patch.start()

    def tearDown(self):
        self.policydir_patch.stop()
        self.policy_dir.cleanup()
        self.dbus_patch.start()
        self.system_info_patch.stop()
        self.policy_patch.stop()
        super(TC_00_qrexec_policy, self).tearDown()

    def test_000_allow(self):
        self.policy_mock.configure_mock(**{
            'return_value.evaluate.return_value.action':
                qubespolicy.Action.allow,
        })
        retval = qubespolicy.cli.main(
            ['source-id', 'source', 'target', 'service', 'process_ident'])
        self.assertEqual(retval, 0)
        self.assertEqual(self.policy_mock.mock_calls, [
            ('', ('service',), {}),
            ('().evaluate', (self.system_info, 'source',
                'target'), {}),
            ('().evaluate().target.__str__', (), {}),
            ('().evaluate().execute', ('process_ident,source,source-id', ), {}),
        ])
        self.assertEqual(self.dbus_mock.mock_calls, [])

    def test_010_ask_allow(self):
        self.policy_mock.configure_mock(**{
            'return_value.evaluate.return_value.action':
                qubespolicy.Action.ask,
            'return_value.evaluate.return_value.target':
                None,
            'return_value.evaluate.return_value.targets_for_ask':
                ['test-vm1', 'test-vm2'],
        })
        self.dbus_mock.configure_mock(**{
            'return_value.get.return_value.Ask.return_value': 'test-vm1'
        })
        retval = qubespolicy.cli.main(
            ['source-id', 'source', 'target', 'service', 'process_ident'])
        self.assertEqual(retval, 0)
        self.assertEqual(self.policy_mock.mock_calls, [
            ('', ('service',), {}),
            ('().evaluate', (self.system_info, 'source',
                'target'), {}),
            ('().evaluate().handle_user_response', (True, 'test-vm1'), {}),
            ('().evaluate().execute', ('process_ident,source,source-id', ), {}),
        ])
        icons = {
            'dom0': 'black',
            'test-vm1': 'red',
            'test-vm2': 'red',
            'test-vm3': 'green',
            '$dispvm:test-vm3': 'green',
        }
        self.assertEqual(self.dbus_mock.mock_calls, [
            ('', (), {}),
            ('().get', ('org.qubesos.PolicyAgent',
                '/org/qubesos/PolicyAgent'), {}),
            ('().get().Ask', ('source', 'service', ['test-vm1', 'test-vm2'],
            '', icons), {}),
        ])

    def test_011_ask_deny(self):
        self.policy_mock.configure_mock(**{
            'return_value.evaluate.return_value.action':
                qubespolicy.Action.ask,
            'return_value.evaluate.return_value.target':
                None,
            'return_value.evaluate.return_value.targets_for_ask':
                ['test-vm1', 'test-vm2'],
            'return_value.evaluate.return_value.handle_user_response'
            '.side_effect':
                qubespolicy.AccessDenied,
        })
        self.dbus_mock.configure_mock(**{
            'return_value.get.return_value.Ask.return_value': ''
        })
        retval = qubespolicy.cli.main(
            ['source-id', 'source', 'target', 'service', 'process_ident'])
        self.assertEqual(retval, 1)
        self.assertEqual(self.policy_mock.mock_calls, [
            ('', ('service',), {}),
            ('().evaluate', (self.system_info, 'source',
                'target'), {}),
            ('().evaluate().handle_user_response', (False,), {}),
        ])
        icons = {
            'dom0': 'black',
            'test-vm1': 'red',
            'test-vm2': 'red',
            'test-vm3': 'green',
            '$dispvm:test-vm3': 'green',
        }
        self.assertEqual(self.dbus_mock.mock_calls, [
            ('', (), {}),
            ('().get', ('org.qubesos.PolicyAgent',
                '/org/qubesos/PolicyAgent'), {}),
            ('().get().Ask', ('source', 'service', ['test-vm1', 'test-vm2'],
            '', icons), {}),
        ])

    def test_012_ask_default_target(self):
        self.policy_mock.configure_mock(**{
            'return_value.evaluate.return_value.action':
                qubespolicy.Action.ask,
            'return_value.evaluate.return_value.target':
                'test-vm1',
            'return_value.evaluate.return_value.targets_for_ask':
                ['test-vm1', 'test-vm2'],
        })
        self.dbus_mock.configure_mock(**{
            'return_value.get.return_value.Ask.return_value': 'test-vm1'
        })
        retval = qubespolicy.cli.main(
            ['source-id', 'source', 'target', 'service', 'process_ident'])
        self.assertEqual(retval, 0)
        self.assertEqual(self.policy_mock.mock_calls, [
            ('', ('service',), {}),
            ('().evaluate', (self.system_info, 'source',
                'target'), {}),
            ('().evaluate().handle_user_response', (True, 'test-vm1'), {}),
            ('().evaluate().execute', ('process_ident,source,source-id',), {}),
        ])
        icons = {
            'dom0': 'black',
            'test-vm1': 'red',
            'test-vm2': 'red',
            'test-vm3': 'green',
            '$dispvm:test-vm3': 'green',
        }
        self.assertEqual(self.dbus_mock.mock_calls, [
            ('', (), {}),
            ('().get', ('org.qubesos.PolicyAgent',
                '/org/qubesos/PolicyAgent'), {}),
            ('().get().Ask', ('source', 'service', ['test-vm1', 'test-vm2'],
            'test-vm1', icons), {}),
        ])

    def test_020_deny(self):
        self.policy_mock.configure_mock(**{
            'return_value.evaluate.return_value.action':
                qubespolicy.Action.deny,
            'return_value.evaluate.return_value.execute.side_effect':
                qubespolicy.AccessDenied,
        })
        retval = qubespolicy.cli.main(
            ['source-id', 'source', 'target', 'service', 'process_ident'])
        self.assertEqual(retval, 1)
        self.assertEqual(self.policy_mock.mock_calls, [
            ('', ('service',), {}),
            ('().evaluate', (self.system_info, 'source',
                'target'), {}),
            ('().evaluate().target.__str__', (), {}),
            ('().evaluate().execute', ('process_ident,source,source-id',), {}),
        ])
        self.assertEqual(self.dbus_mock.mock_calls, [])

    def test_030_just_evaluate_allow(self):
        self.policy_mock.configure_mock(**{
            'return_value.evaluate.return_value.action':
                qubespolicy.Action.allow,
        })
        retval = qubespolicy.cli.main(
            ['--just-evaluate',
                'source-id', 'source', 'target', 'service', 'process_ident'])
        self.assertEqual(retval, 0)
        self.assertEqual(self.policy_mock.mock_calls, [
            ('', ('service',), {}),
            ('().evaluate', (self.system_info, 'source',
                'target'), {}),
        ])
        self.assertEqual(self.dbus_mock.mock_calls, [])

    def test_031_just_evaluate_deny(self):
        self.policy_mock.configure_mock(**{
            'return_value.evaluate.return_value.action':
                qubespolicy.Action.deny,
        })
        retval = qubespolicy.cli.main(
            ['--just-evaluate',
                'source-id', 'source', 'target', 'service', 'process_ident'])
        self.assertEqual(retval, 1)
        self.assertEqual(self.policy_mock.mock_calls, [
            ('', ('service',), {}),
            ('().evaluate', (self.system_info, 'source',
                'target'), {}),
        ])
        self.assertEqual(self.dbus_mock.mock_calls, [])

    def test_032_just_evaluate_ask(self):
        self.policy_mock.configure_mock(**{
            'return_value.evaluate.return_value.action':
                qubespolicy.Action.ask,
        })
        retval = qubespolicy.cli.main(
            ['--just-evaluate',
                'source-id', 'source', 'target', 'service', 'process_ident'])
        self.assertEqual(retval, 1)
        self.assertEqual(self.policy_mock.mock_calls, [
            ('', ('service',), {}),
            ('().evaluate', (self.system_info, 'source',
                'target'), {}),
        ])
        self.assertEqual(self.dbus_mock.mock_calls, [])

    def test_033_just_evaluate_ask_assume_yes(self):
        self.policy_mock.configure_mock(**{
            'return_value.evaluate.return_value.action':
                qubespolicy.Action.ask,
        })
        retval = qubespolicy.cli.main(
            ['--just-evaluate', '--assume-yes-for-ask',
                'source-id', 'source', 'target', 'service', 'process_ident'])
        self.assertEqual(retval, 0)
        self.assertEqual(self.policy_mock.mock_calls, [
            ('', ('service',), {}),
            ('().evaluate', (self.system_info, 'source',
                'target'), {}),
        ])
        self.assertEqual(self.dbus_mock.mock_calls, [])

    def test_040_create_policy(self):
        self.policy_mock.configure_mock(**{
            'side_effect':
                [qubespolicy.PolicyNotFound('service'), unittest.mock.DEFAULT],
            'return_value.evaluate.return_value.action':
                qubespolicy.Action.allow,
        })
        self.dbus_mock.configure_mock(**{
            'return_value.get.return_value.ConfirmPolicyCreate.return_value':
                True
        })
        retval = qubespolicy.cli.main(
            ['source-id', 'source', 'target', 'service', 'process_ident'])
        self.assertEqual(retval, 0)
        self.assertEqual(self.policy_mock.mock_calls, [
            ('', ('service',), {}),
            ('', ('service',), {}),
            ('().evaluate', (self.system_info, 'source',
                'target'), {}),
            ('().evaluate().target.__str__', (), {}),
            ('().evaluate().execute', ('process_ident,source,source-id',), {}),
        ])
        self.assertEqual(self.dbus_mock.mock_calls, [
            ('', (), {}),
            ('().get', ('org.qubesos.PolicyAgent',
            '/org/qubesos/PolicyAgent'), {}),
            ('().get().ConfirmPolicyCreate', ('source', 'service'), {}),
        ])
        policy_path = os.path.join(self.policy_dir.name, 'service')
        self.assertTrue(os.path.exists(policy_path))
        with open(policy_path) as policy_file:
            self.assertEqual(policy_file.read(),
                "## Policy file automatically created on first service call.\n"
                "## Fill free to edit.\n"
                "## Note that policy parsing stops at the first match\n"
                "\n"
                "## Please use a single # to start your custom comments\n"
                "\n"
                "$anyvm  $anyvm  ask\n")

    def test_041_create_policy_abort(self):
        self.policy_mock.configure_mock(**{
            'side_effect':
                [qubespolicy.PolicyNotFound('service'), unittest.mock.DEFAULT],
            'return_value.evaluate.return_value.action':
                qubespolicy.Action.deny,
        })
        self.dbus_mock.configure_mock(**{
            'return_value.get.return_value.ConfirmPolicyCreate.return_value':
                False
        })
        retval = qubespolicy.cli.main(
            ['source-id', 'source', 'target', 'service', 'process_ident'])
        self.assertEqual(retval, 1)
        self.assertEqual(self.policy_mock.mock_calls, [
            ('', ('service',), {}),
        ])
        self.assertEqual(self.dbus_mock.mock_calls, [
            ('', (), {}),
            ('().get', ('org.qubesos.PolicyAgent',
            '/org/qubesos/PolicyAgent'), {}),
            ('().get().ConfirmPolicyCreate', ('source', 'service'), {}),
        ])
        policy_path = os.path.join(self.policy_dir.name, 'service')
        self.assertFalse(os.path.exists(policy_path))
