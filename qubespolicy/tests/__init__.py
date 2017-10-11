# -*- encoding: utf8 -*-
#
# The Qubes OS Project, http://www.qubes-os.org
#
# Copyright (C) 2017 Marek Marczykowski-Górecki
#                               <marmarek@invisiblethingslab.com>
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
import os
import socket
import unittest.mock

import shutil

import qubes.tests
import qubespolicy

tmp_policy_dir = '/tmp/policy'

system_info = {
    'domains': {
        'dom0': {
            'tags': ['dom0-tag'],
            'type': 'AdminVM',
            'default_dispvm': 'default-dvm',
            'template_for_dispvms': False,
        },
        'test-vm1': {
            'tags': ['tag1', 'tag2'],
            'type': 'AppVM',
            'default_dispvm': 'default-dvm',
            'template_for_dispvms': False,
        },
        'test-vm2': {
            'tags': ['tag2'],
            'type': 'AppVM',
            'default_dispvm': 'default-dvm',
            'template_for_dispvms': False,
        },
        'test-vm3': {
            'tags': ['tag3'],
            'type': 'AppVM',
            'default_dispvm': 'default-dvm',
            'template_for_dispvms': True,
        },
        'default-dvm': {
            'tags': [],
            'type': 'AppVM',
            'default_dispvm': 'default-dvm',
            'template_for_dispvms': True,
        },
        'test-invalid-dvm': {
            'tags': ['tag1', 'tag2'],
            'type': 'AppVM',
            'default_dispvm': 'test-vm1',
            'template_for_dispvms': False,
        },
        'test-no-dvm': {
            'tags': ['tag1', 'tag2'],
            'type': 'AppVM',
            'default_dispvm': None,
            'template_for_dispvms': False,
        },
        'test-template': {
            'tags': ['tag1', 'tag2'],
            'type': 'TemplateVM',
            'default_dispvm': 'default-dvm',
            'template_for_dispvms': False,
        },
        'test-standalone': {
            'tags': ['tag1', 'tag2'],
            'type': 'StandaloneVM',
            'default_dispvm': 'default-dvm',
            'template_for_dispvms': False,
        },
    }
}


class TC_00_PolicyRule(qubes.tests.QubesTestCase):
    def test_000_verify_target_value(self):
        self.assertTrue(
            qubespolicy.verify_target_value(system_info, 'test-vm1'))
        self.assertTrue(
            qubespolicy.verify_target_value(system_info, 'default-dvm'))
        self.assertTrue(
            qubespolicy.verify_target_value(system_info, '$dispvm'))
        self.assertTrue(
            qubespolicy.verify_target_value(system_info, '$dispvm:default-dvm'))
        self.assertTrue(
            qubespolicy.verify_target_value(system_info, 'test-template'))
        self.assertTrue(
            qubespolicy.verify_target_value(system_info, 'test-standalone'))
        self.assertTrue(
            qubespolicy.verify_target_value(system_info, '$adminvm'))
        self.assertFalse(
            qubespolicy.verify_target_value(system_info, 'no-such-vm'))
        self.assertFalse(
            qubespolicy.verify_target_value(system_info,
                '$dispvm:test-invalid-dvm'))
        self.assertFalse(
            qubespolicy.verify_target_value(system_info, '$dispvm:test-vm1'))
        self.assertFalse(
            qubespolicy.verify_target_value(system_info, ''))
        self.assertFalse(
            qubespolicy.verify_target_value(system_info, '$default'))
        self.assertFalse(
            qubespolicy.verify_target_value(system_info, '$anyvm'))
        self.assertFalse(
            qubespolicy.verify_target_value(system_info, '$tag:tag1'))
        self.assertFalse(
            qubespolicy.verify_target_value(system_info, '$dispvm:$tag:tag1'))
        self.assertFalse(
            qubespolicy.verify_target_value(system_info, '$invalid'))

    def test_010_verify_special_value(self):
        self.assertTrue(qubespolicy.verify_special_value('$tag:tag',
            for_target=False))
        self.assertTrue(qubespolicy.verify_special_value('$tag:other-tag',
            for_target=False))
        self.assertTrue(qubespolicy.verify_special_value('$type:AppVM',
            for_target=False))
        self.assertTrue(qubespolicy.verify_special_value('$adminvm',
            for_target=False))
        self.assertTrue(qubespolicy.verify_special_value('$dispvm:some-vm',
            for_target=True))
        self.assertTrue(qubespolicy.verify_special_value('$dispvm:$tag:tag1',
            for_target=True))
        self.assertFalse(qubespolicy.verify_special_value('$default',
            for_target=False))
        self.assertFalse(qubespolicy.verify_special_value('$dispvm',
            for_target=False))
        self.assertFalse(qubespolicy.verify_special_value('$dispvm:some-vm',
            for_target=False))
        self.assertFalse(qubespolicy.verify_special_value('$dispvm:$tag:tag1',
            for_target=False))
        self.assertFalse(qubespolicy.verify_special_value('$invalid',
            for_target=False))
        self.assertFalse(qubespolicy.verify_special_value('vm-name',
            for_target=False))
        self.assertFalse(qubespolicy.verify_special_value('$tag:',
            for_target=False))
        self.assertFalse(qubespolicy.verify_special_value('$type:',
            for_target=False))

    def test_020_line_simple(self):
        line = qubespolicy.PolicyRule('$anyvm $anyvm ask', 'filename', 12)
        self.assertEqual(line.filename, 'filename')
        self.assertEqual(line.lineno, 12)
        self.assertEqual(line.action, qubespolicy.Action.ask)
        self.assertEqual(line.source, '$anyvm')
        self.assertEqual(line.target, '$anyvm')
        self.assertEqual(line.full_action, 'ask')
        self.assertIsNone(line.override_target)
        self.assertIsNone(line.override_user)
        self.assertIsNone(line.default_target)

    def test_021_line_simple(self):
        # also check spaces in action field
        line = qubespolicy.PolicyRule(
            '$tag:tag1 $type:AppVM ask, target=test-vm2, user=user',
            'filename', 12)
        self.assertEqual(line.filename, 'filename')
        self.assertEqual(line.lineno, 12)
        self.assertEqual(line.action, qubespolicy.Action.ask)
        self.assertEqual(line.source, '$tag:tag1')
        self.assertEqual(line.target, '$type:AppVM')
        self.assertEqual(line.full_action, 'ask, target=test-vm2, user=user')
        self.assertEqual(line.override_target, 'test-vm2')
        self.assertEqual(line.override_user, 'user')
        self.assertIsNone(line.default_target)

    def test_022_line_simple(self):
        line = qubespolicy.PolicyRule(
            '$anyvm $default allow,target=$dispvm:test-vm2',
            'filename', 12)
        self.assertEqual(line.filename, 'filename')
        self.assertEqual(line.lineno, 12)
        self.assertEqual(line.action, qubespolicy.Action.allow)
        self.assertEqual(line.source, '$anyvm')
        self.assertEqual(line.target, '$default')
        self.assertEqual(line.full_action, 'allow,target=$dispvm:test-vm2')
        self.assertEqual(line.override_target, '$dispvm:test-vm2')
        self.assertIsNone(line.override_user)
        self.assertIsNone(line.default_target)

    def test_023_line_simple(self):
        line = qubespolicy.PolicyRule(
            '$anyvm $default ask,default_target=test-vm1',
            'filename', 12)
        self.assertEqual(line.filename, 'filename')
        self.assertEqual(line.lineno, 12)
        self.assertEqual(line.action, qubespolicy.Action.ask)
        self.assertEqual(line.source, '$anyvm')
        self.assertEqual(line.target, '$default')
        self.assertEqual(line.full_action, 'ask,default_target=test-vm1')
        self.assertIsNone(line.override_target)
        self.assertIsNone(line.override_user)
        self.assertEqual(line.default_target, 'test-vm1')

    def test_024_line_simple(self):
        line = qubespolicy.PolicyRule(
            '$anyvm $adminvm ask,default_target=$adminvm',
            'filename', 12)
        self.assertEqual(line.filename, 'filename')
        self.assertEqual(line.lineno, 12)
        self.assertEqual(line.action, qubespolicy.Action.ask)
        self.assertEqual(line.source, '$anyvm')
        self.assertEqual(line.target, '$adminvm')
        self.assertEqual(line.full_action, 'ask,default_target=$adminvm')
        self.assertIsNone(line.override_target)
        self.assertIsNone(line.override_user)
        self.assertEqual(line.default_target, '$adminvm')

    def test_030_line_invalid(self):
        invalid_lines = [
            '$dispvm $default allow',  # $dispvm can't be a source
            '$default $default allow',  # $default can't be a source
            '$anyvm $default allow,target=$dispvm:$tag:tag1',  # $dispvm:$tag
            #  as override target
            '$anyvm $default allow,target=$tag:tag1',  # $tag as override target
            '$anyvm $default deny,target=test-vm1',  # target= used with deny
            '$anyvm $anyvm deny,default_target=test-vm1',  # default_target=
            # with deny
            '$anyvm $anyvm deny,user=user',  # user= with deny
            '$anyvm $anyvm invalid',  # invalid action
            '$anyvm $anyvm allow,invalid=xx',  # invalid option
            '$anyvm $anyvm',  # missing action
            '$anyvm $anyvm allow,default_target=test-vm1',  # default_target=
            #  with allow
            '$invalid $anyvm allow',  # invalid source
            '$anyvm $invalid deny',  # invalid target
            '',  # empty line
            '$anyvm $anyvm allow extra',  # trailing words
            '$anyvm $default allow',  # $default allow without target=
        ]
        for line in invalid_lines:
            with self.subTest(line):
                with self.assertRaises(qubespolicy.PolicySyntaxError):
                    qubespolicy.PolicyRule(line, 'filename', 12)

    def test_040_match_single(self):
        is_match_single = qubespolicy.PolicyRule.is_match_single
        self.assertTrue(is_match_single(system_info, '$anyvm', 'test-vm1'))
        self.assertTrue(is_match_single(system_info, '$anyvm', '$default'))
        self.assertTrue(is_match_single(system_info, '$anyvm', ''))
        self.assertTrue(is_match_single(system_info, '$default', ''))
        self.assertTrue(is_match_single(system_info, '$default', '$default'))
        self.assertTrue(is_match_single(system_info, '$tag:tag1', 'test-vm1'))
        self.assertTrue(is_match_single(system_info, '$type:AppVM', 'test-vm1'))
        self.assertTrue(is_match_single(system_info,
            '$type:TemplateVM', 'test-template'))
        self.assertTrue(is_match_single(system_info, '$anyvm', '$dispvm'))
        self.assertTrue(is_match_single(system_info,
            '$anyvm', '$dispvm:default-dvm'))
        self.assertTrue(is_match_single(system_info, '$dispvm', '$dispvm'))
        self.assertTrue(is_match_single(system_info,
            '$dispvm:$tag:tag3', '$dispvm:test-vm3'))
        self.assertTrue(is_match_single(system_info, '$adminvm', '$adminvm'))
        self.assertTrue(is_match_single(system_info, '$adminvm', 'dom0'))
        self.assertTrue(is_match_single(system_info, 'dom0', '$adminvm'))
        self.assertTrue(is_match_single(system_info, 'dom0', 'dom0'))
        self.assertTrue(is_match_single(system_info,
            '$dispvm:default-dvm', '$dispvm:default-dvm'))
        self.assertTrue(is_match_single(system_info, '$anyvm', '$dispvm'))
        self.assertTrue(is_match_single(system_info, '$anyvm', 'test-vm1'))
        self.assertTrue(is_match_single(system_info, '$anyvm', 'test-vm1'))
        self.assertTrue(is_match_single(system_info, '$anyvm', 'test-vm1'))

        self.assertFalse(is_match_single(system_info, '$default', 'test-vm1'))
        self.assertFalse(is_match_single(system_info, '$tag:tag1', 'test-vm3'))
        self.assertFalse(is_match_single(system_info, '$anyvm', 'no-such-vm'))
        # test-vm1.template_for_dispvms=False
        self.assertFalse(is_match_single(system_info,
            '$anyvm', '$dispvm:test-vm1'))
        # test-vm1.template_for_dispvms=False
        self.assertFalse(is_match_single(system_info,
            '$dispvm:test-vm1', '$dispvm:test-vm1'))
        self.assertFalse(is_match_single(system_info,
            '$dispvm:$tag:tag1', '$dispvm:test-vm1'))
        # test-vm3 has not tag1
        self.assertFalse(is_match_single(system_info,
            '$dispvm:$tag:tag1', '$dispvm:test-vm3'))
        # default-dvm has no tag3
        self.assertFalse(is_match_single(system_info,
            '$dispvm:$tag:tag3', '$dispvm:default-dvm'))
        self.assertFalse(is_match_single(system_info, '$anyvm', 'dom0'))
        self.assertFalse(is_match_single(system_info, '$anyvm', '$adminvm'))
        self.assertFalse(is_match_single(system_info,
            '$tag:dom0-tag', '$adminvm'))
        self.assertFalse(is_match_single(system_info,
            '$type:AdminVM', '$adminvm'))
        self.assertFalse(is_match_single(system_info,
            '$tag:dom0-tag', 'dom0'))
        self.assertFalse(is_match_single(system_info,
            '$type:AdminVM', 'dom0'))
        self.assertFalse(is_match_single(system_info, '$tag:tag1', 'dom0'))
        self.assertFalse(is_match_single(system_info, '$anyvm', '$tag:tag1'))
        self.assertFalse(is_match_single(system_info, '$anyvm', '$type:AppVM'))
        self.assertFalse(is_match_single(system_info, '$anyvm', '$invalid'))
        self.assertFalse(is_match_single(system_info, '$invalid', '$invalid'))
        self.assertFalse(is_match_single(system_info, '$anyvm', 'no-such-vm'))
        self.assertFalse(is_match_single(system_info,
            'no-such-vm', 'no-such-vm'))
        self.assertFalse(is_match_single(system_info, '$dispvm', 'test-vm1'))
        self.assertFalse(is_match_single(system_info, '$dispvm', 'default-dvm'))
        self.assertFalse(is_match_single(system_info,
            '$dispvm:default-dvm', 'default-dvm'))
        self.assertFalse(is_match_single(system_info, '$anyvm', 'test-vm1\n'))
        self.assertFalse(is_match_single(system_info, '$anyvm', 'test-vm1  '))

    def test_050_match(self):
        line = qubespolicy.PolicyRule('$anyvm $anyvm allow')
        self.assertTrue(line.is_match(system_info, 'test-vm1', 'test-vm2'))
        line = qubespolicy.PolicyRule('$anyvm $anyvm allow')
        self.assertFalse(line.is_match(system_info, 'no-such-vm', 'test-vm2'))
        line = qubespolicy.PolicyRule('$anyvm $anyvm allow')
        self.assertFalse(line.is_match(system_info, 'test-vm1', 'no-such-vm'))
        line = qubespolicy.PolicyRule('$anyvm $dispvm allow')
        self.assertTrue(line.is_match(system_info, 'test-vm1', '$dispvm'))
        line = qubespolicy.PolicyRule('$anyvm $dispvm allow')
        self.assertFalse(line.is_match(system_info,
            'test-vm1', '$dispvm:default-dvm'))
        line = qubespolicy.PolicyRule('$anyvm $dispvm:default-dvm allow')
        self.assertTrue(line.is_match(system_info, 'test-vm1', '$dispvm'))
        line = qubespolicy.PolicyRule('$anyvm $dispvm:default-dvm allow')
        self.assertTrue(line.is_match(system_info,
            'test-vm1', '$dispvm:default-dvm'))
        line = qubespolicy.PolicyRule('$anyvm $dispvm:$tag:tag3 allow')
        self.assertTrue(line.is_match(system_info,
            'test-vm1', '$dispvm:test-vm3'))

    def test_060_expand_target(self):
        lines = {
            '$anyvm $anyvm allow': ['test-vm1', 'test-vm2', 'test-vm3',
                '$dispvm:test-vm3',
                'default-dvm', '$dispvm:default-dvm', 'test-invalid-dvm',
                'test-no-dvm', 'test-template', 'test-standalone', '$dispvm'],
            '$anyvm $dispvm allow': ['$dispvm'],
            '$anyvm $dispvm:default-dvm allow': ['$dispvm:default-dvm'],
            # no DispVM from test-vm1 allowed
            '$anyvm $dispvm:test-vm1 allow': [],
            '$anyvm $dispvm:test-vm3 allow': ['$dispvm:test-vm3'],
            '$anyvm $dispvm:$tag:tag1 allow': [],
            '$anyvm $dispvm:$tag:tag3 allow': ['$dispvm:test-vm3'],
            '$anyvm test-vm1 allow': ['test-vm1'],
            '$anyvm $type:AppVM allow': ['test-vm1', 'test-vm2', 'test-vm3',
                'default-dvm', 'test-invalid-dvm', 'test-no-dvm'],
            '$anyvm $type:TemplateVM allow': ['test-template'],
            '$anyvm $tag:tag1 allow': ['test-vm1', 'test-invalid-dvm',
                'test-template', 'test-standalone', 'test-no-dvm'],
            '$anyvm $tag:tag2 allow': ['test-vm1', 'test-vm2',
                'test-invalid-dvm', 'test-template', 'test-standalone',
                'test-no-dvm'],
            '$anyvm $tag:no-such-tag allow': [],
        }
        for line in lines:
            with self.subTest(line):
                policy_line = qubespolicy.PolicyRule(line)
                self.assertCountEqual(list(policy_line.expand_target(system_info)),
                    lines[line])

    def test_070_expand_override_target(self):
        line = qubespolicy.PolicyRule(
            '$anyvm $anyvm allow,target=test-vm2')
        self.assertEqual(
            line.expand_override_target(system_info, 'test-vm1'),
            'test-vm2')

    def test_071_expand_override_target_dispvm(self):
        line = qubespolicy.PolicyRule(
            '$anyvm $anyvm allow,target=$dispvm')
        self.assertEqual(
            line.expand_override_target(system_info, 'test-vm1'),
            '$dispvm:default-dvm')

    def test_072_expand_override_target_dispvm_specific(self):
        line = qubespolicy.PolicyRule(
            '$anyvm $anyvm allow,target=$dispvm:test-vm3')
        self.assertEqual(
            line.expand_override_target(system_info, 'test-vm1'),
            '$dispvm:test-vm3')

    def test_073_expand_override_target_dispvm_none(self):
        line = qubespolicy.PolicyRule(
            '$anyvm $anyvm allow,target=$dispvm')
        self.assertEqual(
            line.expand_override_target(system_info, 'test-no-dvm'),
            None)

    def test_074_expand_override_target_dom0(self):
        line = qubespolicy.PolicyRule(
            '$anyvm $anyvm allow,target=dom0')
        self.assertEqual(
            line.expand_override_target(system_info, 'test-no-dvm'),
            'dom0')

    def test_075_expand_override_target_dom0(self):
        line = qubespolicy.PolicyRule(
            '$anyvm $anyvm allow,target=$adminvm')
        self.assertEqual(
            line.expand_override_target(system_info, 'test-no-dvm'),
            '$adminvm')


class TC_10_PolicyAction(qubes.tests.QubesTestCase):
    def test_000_init(self):
        rule = qubespolicy.PolicyRule('$anyvm $anyvm deny')
        with self.assertRaises(qubespolicy.AccessDenied):
            qubespolicy.PolicyAction('test.service', 'test-vm1', 'test-vm2',
                rule, 'test-vm2')

    def test_001_init(self):
        rule = qubespolicy.PolicyRule('$anyvm $anyvm ask')
        action = qubespolicy.PolicyAction('test.service', 'test-vm1',
            None, rule, 'test-vm2', ['test-vm2', 'test-vm3'])
        self.assertEqual(action.service, 'test.service')
        self.assertEqual(action.source, 'test-vm1')
        self.assertIsNone(action.target)
        self.assertEqual(action.original_target, 'test-vm2')
        self.assertEqual(action.targets_for_ask, ['test-vm2', 'test-vm3'])
        self.assertEqual(action.rule, rule)
        self.assertEqual(action.action, qubespolicy.Action.ask)

    def test_002_init_invalid(self):
        rule_ask = qubespolicy.PolicyRule('$anyvm $anyvm ask')
        rule_allow = qubespolicy.PolicyRule('$anyvm $anyvm allow')
        with self.assertRaises(AssertionError):
            qubespolicy.PolicyAction('test.service', 'test-vm1',
            None, rule_allow, 'test-vm2', None)
        with self.assertRaises(AssertionError):
            qubespolicy.PolicyAction('test.service', 'test-vm1',
            'test-vm2', rule_allow, 'test-vm2', ['test-vm2', 'test-vm3'])

        with self.assertRaises(AssertionError):
            qubespolicy.PolicyAction('test.service', 'test-vm1',
            None, rule_ask, 'test-vm2', None)

    def test_003_init_default_target(self):
        rule_ask = qubespolicy.PolicyRule('$anyvm $anyvm ask')

        action = qubespolicy.PolicyAction('test.service', 'test-vm1',
            'test-vm1', rule_ask, 'test-vm2', ['test-vm2'])
        self.assertIsNone(action.target)

        action = qubespolicy.PolicyAction('test.service', 'test-vm1',
            'test-vm2', rule_ask, 'test-vm2', ['test-vm2'])
        self.assertEqual(action.target, 'test-vm2')

    def test_010_handle_user_response(self):
        rule = qubespolicy.PolicyRule('$anyvm $anyvm ask')
        action = qubespolicy.PolicyAction('test.service', 'test-vm1',
            None, rule, 'test-vm2', ['test-vm2', 'test-vm3'])
        action.handle_user_response(True, 'test-vm2')
        self.assertEqual(action.action, qubespolicy.Action.allow)
        self.assertEqual(action.target, 'test-vm2')

    def test_011_handle_user_response(self):
        rule = qubespolicy.PolicyRule('$anyvm $anyvm ask')
        action = qubespolicy.PolicyAction('test.service', 'test-vm1',
            None, rule, 'test-vm2', ['test-vm2', 'test-vm3'])
        with self.assertRaises(AssertionError):
            action.handle_user_response(True, 'test-no-dvm')

    def test_012_handle_user_response(self):
        rule = qubespolicy.PolicyRule('$anyvm $anyvm ask')
        action = qubespolicy.PolicyAction('test.service', 'test-vm1',
            None, rule, 'test-vm2', ['test-vm2', 'test-vm3'])
        with self.assertRaises(qubespolicy.AccessDenied):
            action.handle_user_response(False, None)
        self.assertEqual(action.action, qubespolicy.Action.deny)

    def test_013_handle_user_response_with_default_target(self):
        rule = qubespolicy.PolicyRule(
            '$anyvm $anyvm ask,default_target=test-vm2')
        action = qubespolicy.PolicyAction('test.service', 'test-vm1',
            None, rule, 'test-vm2', ['test-vm2', 'test-vm3'])
        action.handle_user_response(True, 'test-vm2')
        self.assertEqual(action.action, qubespolicy.Action.allow)
        self.assertEqual(action.target, 'test-vm2')

    @unittest.mock.patch('qubespolicy.qubesd_call')
    @unittest.mock.patch('subprocess.call')
    def test_020_execute(self, mock_subprocess, mock_qubesd_call):
        rule = qubespolicy.PolicyRule('$anyvm $anyvm allow')
        action = qubespolicy.PolicyAction('test.service', 'test-vm1',
            'test-vm2', rule, 'test-vm2')
        action.execute('some-ident')
        self.assertEqual(mock_qubesd_call.mock_calls,
            [unittest.mock.call('test-vm2', 'admin.vm.Start')])
        self.assertEqual(mock_subprocess.mock_calls,
            [unittest.mock.call([qubespolicy.QREXEC_CLIENT, '-d', 'test-vm2',
             '-c', 'some-ident', 'DEFAULT:QUBESRPC test.service test-vm1'])])

    @unittest.mock.patch('qubespolicy.qubesd_call')
    @unittest.mock.patch('subprocess.call')
    def test_021_execute_dom0(self, mock_subprocess, mock_qubesd_call):
        rule = qubespolicy.PolicyRule('$anyvm dom0 allow')
        action = qubespolicy.PolicyAction('test.service', 'test-vm1',
            'dom0', rule, 'dom0')
        action.execute('some-ident')
        self.assertEqual(mock_qubesd_call.mock_calls, [])
        self.assertEqual(mock_subprocess.mock_calls,
            [unittest.mock.call([qubespolicy.QREXEC_CLIENT, '-d', 'dom0',
             '-c', 'some-ident',
             qubespolicy.QUBES_RPC_MULTIPLEXER_PATH +
             ' test.service test-vm1 dom0'])])

    @unittest.mock.patch('qubespolicy.qubesd_call')
    @unittest.mock.patch('subprocess.call')
    def test_022_execute_dispvm(self, mock_subprocess, mock_qubesd_call):
        rule = qubespolicy.PolicyRule('$anyvm $dispvm:default-dvm allow')
        action = qubespolicy.PolicyAction('test.service', 'test-vm1',
            '$dispvm:default-dvm', rule, '$dispvm:default-dvm')
        mock_qubesd_call.side_effect = (lambda target, call:
            b'dispvm-name' if call == 'admin.vm.CreateDisposable' else
            unittest.mock.DEFAULT)
        action.execute('some-ident')
        self.assertEqual(mock_qubesd_call.mock_calls,
            [unittest.mock.call('default-dvm', 'admin.vm.CreateDisposable'),
             unittest.mock.call('dispvm-name', 'admin.vm.Start'),
             unittest.mock.call('dispvm-name', 'admin.vm.Kill')])
        self.assertEqual(mock_subprocess.mock_calls,
            [unittest.mock.call([qubespolicy.QREXEC_CLIENT, '-d', 'dispvm-name',
             '-c', 'some-ident', '-W',
             'DEFAULT:QUBESRPC test.service test-vm1'])])

    @unittest.mock.patch('qubespolicy.qubesd_call')
    @unittest.mock.patch('subprocess.call')
    def test_023_execute_already_running(self, mock_subprocess,
            mock_qubesd_call):
        rule = qubespolicy.PolicyRule('$anyvm $anyvm allow')
        action = qubespolicy.PolicyAction('test.service', 'test-vm1',
            'test-vm2', rule, 'test-vm2')
        mock_qubesd_call.side_effect = \
            qubespolicy.QubesMgmtException('QubesVMNotHaltedError')
        action.execute('some-ident')
        self.assertEqual(mock_qubesd_call.mock_calls,
            [unittest.mock.call('test-vm2', 'admin.vm.Start')])
        self.assertEqual(mock_subprocess.mock_calls,
            [unittest.mock.call([qubespolicy.QREXEC_CLIENT, '-d', 'test-vm2',
             '-c', 'some-ident', 'DEFAULT:QUBESRPC test.service test-vm1'])])

    @unittest.mock.patch('qubespolicy.qubesd_call')
    @unittest.mock.patch('subprocess.call')
    def test_024_execute_startup_error(self, mock_subprocess,
            mock_qubesd_call):
        rule = qubespolicy.PolicyRule('$anyvm $anyvm allow')
        action = qubespolicy.PolicyAction('test.service', 'test-vm1',
            'test-vm2', rule, 'test-vm2')
        mock_qubesd_call.side_effect = \
            qubespolicy.QubesMgmtException('QubesVMError')
        with self.assertRaises(qubespolicy.QubesMgmtException):
            action.execute('some-ident')
        self.assertEqual(mock_qubesd_call.mock_calls,
            [unittest.mock.call('test-vm2', 'admin.vm.Start')])
        self.assertEqual(mock_subprocess.mock_calls, [])

class TC_20_Policy(qubes.tests.QubesTestCase):

    def setUp(self):
        super(TC_20_Policy, self).setUp()
        if not os.path.exists(tmp_policy_dir):
            os.mkdir(tmp_policy_dir)

    def tearDown(self):
        shutil.rmtree(tmp_policy_dir)
        super(TC_20_Policy, self).tearDown()

    def test_000_load(self):
        with open(os.path.join(tmp_policy_dir, 'test.service'), 'w') as f:
            f.write('test-vm1 test-vm2 allow\n')
            f.write('\n')
            f.write('# comment\n')
            f.write('test-vm2 test-vm3 ask\n')
            f.write('   # comment  \n')
            f.write('$anyvm $anyvm ask\n')
        policy = qubespolicy.Policy('test.service', tmp_policy_dir)
        self.assertEqual(policy.service, 'test.service')
        self.assertEqual(len(policy.policy_rules), 3)
        self.assertEqual(policy.policy_rules[0].source, 'test-vm1')
        self.assertEqual(policy.policy_rules[0].target, 'test-vm2')
        self.assertEqual(policy.policy_rules[0].action,
            qubespolicy.Action.allow)

    def test_001_not_existent(self):
        with self.assertRaises(qubespolicy.AccessDenied):
            qubespolicy.Policy('no-such.service', tmp_policy_dir)

    def test_002_include(self):
        with open(os.path.join(tmp_policy_dir, 'test.service'), 'w') as f:
            f.write('test-vm1 test-vm2 allow\n')
            f.write('$include:test.service2\n')
            f.write('$anyvm $anyvm deny\n')
        with open(os.path.join(tmp_policy_dir, 'test.service2'), 'w') as f:
            f.write('test-vm3 $default allow,target=test-vm2\n')
        policy = qubespolicy.Policy('test.service', tmp_policy_dir)
        self.assertEqual(policy.service, 'test.service')
        self.assertEqual(len(policy.policy_rules), 3)
        self.assertEqual(policy.policy_rules[0].source, 'test-vm1')
        self.assertEqual(policy.policy_rules[0].target, 'test-vm2')
        self.assertEqual(policy.policy_rules[0].action,
            qubespolicy.Action.allow)
        self.assertEqual(policy.policy_rules[0].filename,
            tmp_policy_dir + '/test.service')
        self.assertEqual(policy.policy_rules[0].lineno, 1)
        self.assertEqual(policy.policy_rules[1].source, 'test-vm3')
        self.assertEqual(policy.policy_rules[1].target, '$default')
        self.assertEqual(policy.policy_rules[1].action,
            qubespolicy.Action.allow)
        self.assertEqual(policy.policy_rules[1].filename,
            tmp_policy_dir + '/test.service2')
        self.assertEqual(policy.policy_rules[1].lineno, 1)
        self.assertEqual(policy.policy_rules[2].source, '$anyvm')
        self.assertEqual(policy.policy_rules[2].target, '$anyvm')
        self.assertEqual(policy.policy_rules[2].action,
            qubespolicy.Action.deny)
        self.assertEqual(policy.policy_rules[2].filename,
            tmp_policy_dir + '/test.service')
        self.assertEqual(policy.policy_rules[2].lineno, 3)

    def test_010_find_rule(self):
        with open(os.path.join(tmp_policy_dir, 'test.service'), 'w') as f:
            f.write('test-vm1 test-vm2 allow\n')
            f.write('test-vm1 $anyvm ask\n')
            f.write('test-vm2 $tag:tag1 deny\n')
            f.write('test-vm2 $tag:tag2 allow\n')
            f.write('test-vm2 $dispvm:$tag:tag3 allow\n')
            f.write('test-vm2 $dispvm:$tag:tag2 allow\n')
            f.write('test-vm2 $dispvm:default-dvm allow\n')
            f.write('$type:AppVM $default allow,target=test-vm3\n')
            f.write('$tag:tag1 $type:AppVM allow\n')
        policy = qubespolicy.Policy('test.service', tmp_policy_dir)
        self.assertEqual(policy.find_matching_rule(
            system_info, 'test-vm1', 'test-vm2'), policy.policy_rules[0])
        self.assertEqual(policy.find_matching_rule(
            system_info, 'test-vm1', 'test-vm3'), policy.policy_rules[1])
        self.assertEqual(policy.find_matching_rule(
            system_info, 'test-vm2', 'test-vm2'), policy.policy_rules[3])
        self.assertEqual(policy.find_matching_rule(
            system_info, 'test-vm2', 'test-no-dvm'), policy.policy_rules[2])
        # $anyvm matches $default too
        self.assertEqual(policy.find_matching_rule(
            system_info, 'test-vm1', ''), policy.policy_rules[1])
        self.assertEqual(policy.find_matching_rule(
            system_info, 'test-vm2', ''), policy.policy_rules[7])
        self.assertEqual(policy.find_matching_rule(
            system_info, 'test-vm2', '$default'), policy.policy_rules[7])
        self.assertEqual(policy.find_matching_rule(
            system_info, 'test-no-dvm', 'test-vm3'), policy.policy_rules[8])
        self.assertEqual(policy.find_matching_rule(
            system_info, 'test-vm2', '$dispvm:test-vm3'),
            policy.policy_rules[4])
        self.assertEqual(policy.find_matching_rule(
            system_info, 'test-vm2', '$dispvm'),
            policy.policy_rules[6])
        with self.assertRaises(qubespolicy.AccessDenied):
            policy.find_matching_rule(
                system_info, 'test-no-dvm', 'test-standalone')
        with self.assertRaises(qubespolicy.AccessDenied):
            policy.find_matching_rule(system_info, 'test-no-dvm', '$dispvm')
        with self.assertRaises(qubespolicy.AccessDenied):
            policy.find_matching_rule(
                system_info, 'test-standalone', '$default')

    def test_020_collect_targets_for_ask(self):
        with open(os.path.join(tmp_policy_dir, 'test.service'), 'w') as f:
            f.write('test-vm1 test-vm2 allow\n')
            f.write('test-vm1 $anyvm ask\n')
            f.write('test-vm2 $tag:tag1 deny\n')
            f.write('test-vm2 $tag:tag2 allow\n')
            f.write('test-no-dvm $type:AppVM deny\n')
            f.write('$type:AppVM $default allow,target=test-vm3\n')
            f.write('$tag:tag1 $type:AppVM allow\n')
            f.write('test-no-dvm $dispvm allow\n')
            f.write('test-standalone $dispvm allow\n')
        policy = qubespolicy.Policy('test.service', tmp_policy_dir)
        self.assertCountEqual(policy.collect_targets_for_ask(system_info,
            'test-vm1'), ['test-vm1', 'test-vm2', 'test-vm3',
                '$dispvm:test-vm3',
                'default-dvm', '$dispvm:default-dvm', 'test-invalid-dvm',
                'test-no-dvm', 'test-template', 'test-standalone'])
        self.assertCountEqual(policy.collect_targets_for_ask(system_info,
            'test-vm2'), ['test-vm2', 'test-vm3'])
        self.assertCountEqual(policy.collect_targets_for_ask(system_info,
            'test-vm3'), ['test-vm3'])
        self.assertCountEqual(policy.collect_targets_for_ask(system_info,
            'test-standalone'), ['test-vm1', 'test-vm2', 'test-vm3',
            'default-dvm', 'test-no-dvm', 'test-invalid-dvm',
            '$dispvm:default-dvm'])
        self.assertCountEqual(policy.collect_targets_for_ask(system_info,
            'test-no-dvm'), [])

    def test_030_eval_simple(self):
        with open(os.path.join(tmp_policy_dir, 'test.service'), 'w') as f:
            f.write('test-vm1 test-vm2 allow\n')

        policy = qubespolicy.Policy('test.service', tmp_policy_dir)
        action = policy.evaluate(system_info, 'test-vm1', 'test-vm2')
        self.assertEqual(action.rule, policy.policy_rules[0])
        self.assertEqual(action.action, qubespolicy.Action.allow)
        self.assertEqual(action.target, 'test-vm2')
        self.assertEqual(action.original_target, 'test-vm2')
        self.assertEqual(action.service, 'test.service')
        self.assertIsNone(action.targets_for_ask)
        with self.assertRaises(qubespolicy.AccessDenied):
            policy.evaluate(system_info, 'test-vm2', '$default')

    def test_031_eval_default(self):
        with open(os.path.join(tmp_policy_dir, 'test.service'), 'w') as f:
            f.write('test-vm1 test-vm2 allow\n')
            f.write('test-vm1 $default allow,target=test-vm2\n')
            f.write('$tag:tag1 test-vm2 ask\n')
            f.write('$tag:tag2 $anyvm allow\n')
            f.write('test-vm3 $anyvm deny\n')

        policy = qubespolicy.Policy('test.service', tmp_policy_dir)
        action = policy.evaluate(system_info, 'test-vm1', '$default')
        self.assertEqual(action.rule, policy.policy_rules[1])
        self.assertEqual(action.action, qubespolicy.Action.allow)
        self.assertEqual(action.target, 'test-vm2')
        self.assertEqual(action.original_target, '$default')
        self.assertEqual(action.service, 'test.service')
        self.assertIsNone(action.targets_for_ask)
        with self.assertRaises(qubespolicy.AccessDenied):
            # action allow should hit, but no target specified (either by
            # caller or policy)
            policy.evaluate(system_info, 'test-standalone', '$default')

    def test_032_eval_ask(self):
        with open(os.path.join(tmp_policy_dir, 'test.service'), 'w') as f:
            f.write('test-vm1 test-vm2 allow\n')
            f.write('test-vm1 $default allow,target=test-vm2\n')
            f.write('$tag:tag1 test-vm2 ask\n')
            f.write('$tag:tag1 test-vm3 ask,default_target=test-vm3\n')
            f.write('$tag:tag2 $anyvm allow\n')
            f.write('test-vm3 $anyvm deny\n')

        policy = qubespolicy.Policy('test.service', tmp_policy_dir)
        action = policy.evaluate(system_info, 'test-standalone', 'test-vm2')
        self.assertEqual(action.rule, policy.policy_rules[2])
        self.assertEqual(action.action, qubespolicy.Action.ask)
        self.assertIsNone(action.target)
        self.assertEqual(action.original_target, 'test-vm2')
        self.assertEqual(action.service, 'test.service')
        self.assertCountEqual(action.targets_for_ask,
            ['test-vm1', 'test-vm2', 'test-vm3', '$dispvm:test-vm3',
                'default-dvm', '$dispvm:default-dvm', 'test-invalid-dvm',
                'test-no-dvm', 'test-template', 'test-standalone'])

    def test_033_eval_ask(self):
        with open(os.path.join(tmp_policy_dir, 'test.service'), 'w') as f:
            f.write('test-vm1 test-vm2 allow\n')
            f.write('test-vm1 $default allow,target=test-vm2\n')
            f.write('$tag:tag1 test-vm2 ask\n')
            f.write('$tag:tag1 test-vm3 ask,default_target=test-vm3\n')
            f.write('$tag:tag2 $anyvm allow\n')
            f.write('test-vm3 $anyvm deny\n')

        policy = qubespolicy.Policy('test.service', tmp_policy_dir)
        action = policy.evaluate(system_info, 'test-standalone', 'test-vm3')
        self.assertEqual(action.rule, policy.policy_rules[3])
        self.assertEqual(action.action, qubespolicy.Action.ask)
        self.assertEqual(action.target, 'test-vm3')
        self.assertEqual(action.original_target, 'test-vm3')
        self.assertEqual(action.service, 'test.service')
        self.assertCountEqual(action.targets_for_ask,
            ['test-vm1', 'test-vm2', 'test-vm3', '$dispvm:test-vm3',
                'default-dvm', '$dispvm:default-dvm', 'test-invalid-dvm',
                'test-no-dvm', 'test-template', 'test-standalone'])

    def test_034_eval_resolve_dispvm(self):
        with open(os.path.join(tmp_policy_dir, 'test.service'), 'w') as f:
            f.write('test-vm3 $dispvm allow\n')

        policy = qubespolicy.Policy('test.service', tmp_policy_dir)
        action = policy.evaluate(system_info, 'test-vm3', '$dispvm')
        self.assertEqual(action.rule, policy.policy_rules[0])
        self.assertEqual(action.action, qubespolicy.Action.allow)
        self.assertEqual(action.target, '$dispvm:default-dvm')
        self.assertEqual(action.original_target, '$dispvm')
        self.assertEqual(action.service, 'test.service')
        self.assertIsNone(action.targets_for_ask)

    def test_035_eval_resolve_dispvm_fail(self):
        with open(os.path.join(tmp_policy_dir, 'test.service'), 'w') as f:
            f.write('test-no-dvm $dispvm allow\n')

        policy = qubespolicy.Policy('test.service', tmp_policy_dir)
        with self.assertRaises(qubespolicy.AccessDenied):
            policy.evaluate(system_info, 'test-no-dvm', '$dispvm')

    def test_036_eval_invalid_override_target(self):
        with open(os.path.join(tmp_policy_dir, 'test.service'), 'w') as f:
            f.write('test-vm3 $anyvm allow,target=no-such-vm\n')

        policy = qubespolicy.Policy('test.service', tmp_policy_dir)
        with self.assertRaises(qubespolicy.AccessDenied):
            policy.evaluate(system_info, 'test-vm3', '$default')

    def test_037_eval_ask_no_targets(self):
        with open(os.path.join(tmp_policy_dir, 'test.service'), 'w') as f:
            f.write('test-vm3 $default ask\n')

        policy = qubespolicy.Policy('test.service', tmp_policy_dir)
        with self.assertRaises(qubespolicy.AccessDenied):
            policy.evaluate(system_info, 'test-vm3', '$default')


class TC_30_Misc(qubes.tests.QubesTestCase):
    @unittest.mock.patch('socket.socket')
    def test_000_qubesd_call(self, mock_socket):
        mock_config = {
            'return_value.makefile.return_value.read.return_value': b'0\x00data'
        }
        mock_socket.configure_mock(**mock_config)
        result = qubespolicy.qubesd_call('test', 'internal.method')
        self.assertEqual(result, b'data')
        self.assertEqual(mock_socket.mock_calls, [
            unittest.mock.call(socket.AF_UNIX, socket.SOCK_STREAM),
            unittest.mock.call().connect(qubespolicy.QUBESD_INTERNAL_SOCK),
            unittest.mock.call().sendall(b'dom0'),
            unittest.mock.call().sendall(b'\x00'),
            unittest.mock.call().sendall(b'internal.method'),
            unittest.mock.call().sendall(b'\x00'),
            unittest.mock.call().sendall(b'test'),
            unittest.mock.call().sendall(b'\x00'),
            unittest.mock.call().sendall(b'\x00'),
            unittest.mock.call().shutdown(socket.SHUT_WR),
            unittest.mock.call().makefile('rb'),
            unittest.mock.call().makefile().read(),
        ])

    @unittest.mock.patch('socket.socket')
    def test_001_qubesd_call_arg_payload(self, mock_socket):
        mock_config = {
            'return_value.makefile.return_value.read.return_value': b'0\x00data'
        }
        mock_socket.configure_mock(**mock_config)
        result = qubespolicy.qubesd_call('test', 'internal.method', 'arg',
            b'payload')
        self.assertEqual(result, b'data')
        self.assertEqual(mock_socket.mock_calls, [
            unittest.mock.call(socket.AF_UNIX, socket.SOCK_STREAM),
            unittest.mock.call().connect(qubespolicy.QUBESD_INTERNAL_SOCK),
            unittest.mock.call().sendall(b'dom0'),
            unittest.mock.call().sendall(b'\x00'),
            unittest.mock.call().sendall(b'internal.method'),
            unittest.mock.call().sendall(b'\x00'),
            unittest.mock.call().sendall(b'test'),
            unittest.mock.call().sendall(b'\x00'),
            unittest.mock.call().sendall(b'arg'),
            unittest.mock.call().sendall(b'\x00'),
            unittest.mock.call().sendall(b'payload'),
            unittest.mock.call().shutdown(socket.SHUT_WR),
            unittest.mock.call().makefile('rb'),
            unittest.mock.call().makefile().read(),
        ])

    @unittest.mock.patch('socket.socket')
    def test_002_qubesd_call_exception(self, mock_socket):
        mock_config = {
            'return_value.makefile.return_value.read.return_value':
                b'2\x00SomeError\x00traceback\x00message\x00'
        }
        mock_socket.configure_mock(**mock_config)
        with self.assertRaises(qubespolicy.QubesMgmtException) as e:
            qubespolicy.qubesd_call('test', 'internal.method')
        self.assertEqual(e.exception.exc_type, 'SomeError')
        self.assertEqual(mock_socket.mock_calls, [
            unittest.mock.call(socket.AF_UNIX, socket.SOCK_STREAM),
            unittest.mock.call().connect(qubespolicy.QUBESD_INTERNAL_SOCK),
            unittest.mock.call().sendall(b'dom0'),
            unittest.mock.call().sendall(b'\x00'),
            unittest.mock.call().sendall(b'internal.method'),
            unittest.mock.call().sendall(b'\x00'),
            unittest.mock.call().sendall(b'test'),
            unittest.mock.call().sendall(b'\x00'),
            unittest.mock.call().sendall(b'\x00'),
            unittest.mock.call().shutdown(socket.SHUT_WR),
            unittest.mock.call().makefile('rb'),
            unittest.mock.call().makefile().read(),
        ])

