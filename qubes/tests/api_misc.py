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
import asyncio
from unittest import mock
import qubes.tests
import qubes.api.misc


class TC_00_API_Misc(qubes.tests.QubesTestCase):
    def setUp(self):
        super(TC_00_API_Misc, self).setUp()
        self.src = mock.NonCallableMagicMock()
        self.app = mock.NonCallableMock()
        self.dest = mock.NonCallableMock()
        self.dest.name = 'dom0'
        self.app.configure_mock(domains={
            'dom0': self.dest,
            'test-vm': self.src,
        })

    def configure_qdb(self, entries):
        self.src.configure_mock(**{
            'qdb.read.side_effect': (lambda path: entries.get(path, None)),
            'qdb.list.side_effect': (lambda path: sorted(entries.keys())),
        })

    def call_mgmt_func(self, method, arg=b'', payload=b''):
        mgmt_obj = qubes.api.misc.QubesMiscAPI(self.app,
            b'test-vm', method, b'dom0', arg)

        loop = asyncio.get_event_loop()
        response = loop.run_until_complete(
            mgmt_obj.execute(untrusted_payload=payload))
        return response

    def test_000_features_request(self):
        qdb_entries = {
            '/features-request/feature1': b'1',
            '/features-request/feature2': b'',
            '/features-request/feature3': b'other',
        }
        self.configure_qdb(qdb_entries)
        response = self.call_mgmt_func(b'qubes.FeaturesRequest')
        self.assertIsNone(response)
        self.assertEqual(self.app.mock_calls, [
            mock.call.save()
        ])
        self.assertEqual(self.src.mock_calls, [
            mock.call.qdb.list('/features-request/'),
            mock.call.qdb.read('/features-request/feature1'),
            mock.call.qdb.read('/features-request/feature2'),
            mock.call.qdb.read('/features-request/feature3'),
            mock.call.fire_event('features-request', untrusted_features={
                'feature1': '1', 'feature2': '', 'feature3': 'other'})
        ])

    def test_001_features_request_empty(self):
        self.configure_qdb({})
        response = self.call_mgmt_func(b'qubes.FeaturesRequest')
        self.assertIsNone(response)
        self.assertEqual(self.app.mock_calls, [
            mock.call.save()
        ])
        self.assertEqual(self.src.mock_calls, [
            mock.call.qdb.list('/features-request/'),
            mock.call.fire_event('features-request', untrusted_features={})
        ])

    def test_002_features_request_invalid1(self):
        qdb_entries = {
            '/features-request/feature1': b'test spaces',
        }
        self.configure_qdb(qdb_entries)
        with self.assertRaises(AssertionError):
            self.call_mgmt_func(b'qubes.FeaturesRequest')
        self.assertEqual(self.app.mock_calls, [])
        self.assertEqual(self.src.mock_calls, [
            mock.call.qdb.list('/features-request/'),
            mock.call.qdb.read('/features-request/feature1'),
        ])

    def test_003_features_request_invalid2(self):
        qdb_entries = {
            '/features-request/feature1': b'\xfe\x01',
        }
        self.configure_qdb(qdb_entries)
        with self.assertRaises(UnicodeDecodeError):
            self.call_mgmt_func(b'qubes.FeaturesRequest')
        self.assertEqual(self.app.mock_calls, [])
        self.assertEqual(self.src.mock_calls, [
            mock.call.qdb.list('/features-request/'),
            mock.call.qdb.read('/features-request/feature1'),
        ])

    def test_010_notify_tools(self):
        qdb_entries = {
            '/qubes-tools/version': b'1',
            '/qubes-tools/qrexec': b'1',
            '/qubes-tools/gui': b'1',
            '/qubes-tools/os': b'Linux',
            '/qubes-tools/default-user': b'user',
        }
        self.configure_qdb(qdb_entries)
        del self.src.template
        self.src.configure_mock(**{'features.get.return_value': False})
        response = self.call_mgmt_func(b'qubes.NotifyTools')
        self.assertIsNone(response)
        self.assertEqual(self.app.mock_calls, [
            mock.call.save()
        ])
        self.assertEqual(self.src.mock_calls, [
            mock.call.qdb.read('/qubes-tools/version'),
            mock.call.qdb.read('/qubes-tools/qrexec'),
            mock.call.qdb.read('/qubes-tools/gui'),
            mock.call.features.get('qrexec', False),
            mock.call.features.__setitem__('qrexec', True),
            mock.call.features.__setitem__('gui', True),
            mock.call.fire_event('template-postinstall')
        ])

    def test_011_notify_tools_uninstall(self):
        qdb_entries = {
            '/qubes-tools/version': b'1',
            '/qubes-tools/qrexec': b'0',
            '/qubes-tools/gui': b'0',
            '/qubes-tools/os': b'Linux',
            '/qubes-tools/default-user': b'user',
        }
        self.configure_qdb(qdb_entries)
        del self.src.template
        self.src.configure_mock(**{'features.get.return_value': True})
        response = self.call_mgmt_func(b'qubes.NotifyTools')
        self.assertIsNone(response)
        self.assertEqual(self.app.mock_calls, [
            mock.call.save()
        ])
        self.assertEqual(self.src.mock_calls, [
            mock.call.qdb.read('/qubes-tools/version'),
            mock.call.qdb.read('/qubes-tools/qrexec'),
            mock.call.qdb.read('/qubes-tools/gui'),
            mock.call.features.get('qrexec', False),
            mock.call.features.__setitem__('qrexec', False),
            mock.call.features.__setitem__('gui', False),
        ])

    def test_012_notify_tools_uninstall2(self):
        qdb_entries = {
            '/qubes-tools/version': b'1',
            '/qubes-tools/os': b'Linux',
            '/qubes-tools/default-user': b'user',
        }
        self.configure_qdb(qdb_entries)
        del self.src.template
        self.src.configure_mock(**{'features.get.return_value': True})
        response = self.call_mgmt_func(b'qubes.NotifyTools')
        self.assertIsNone(response)
        self.assertEqual(self.app.mock_calls, [
            mock.call.save()
        ])
        self.assertEqual(self.src.mock_calls, [
            mock.call.qdb.read('/qubes-tools/version'),
            mock.call.qdb.read('/qubes-tools/qrexec'),
            mock.call.qdb.read('/qubes-tools/gui'),
            mock.call.features.get('qrexec', False),
            mock.call.features.__setitem__('qrexec', False),
            mock.call.features.__setitem__('gui', False),
        ])

    def test_013_notify_tools_no_version(self):
        qdb_entries = {
            '/qubes-tools/qrexec': b'0',
            '/qubes-tools/gui': b'0',
            '/qubes-tools/os': b'Linux',
            '/qubes-tools/default-user': b'user',
        }
        self.configure_qdb(qdb_entries)
        del self.src.template
        self.src.configure_mock(**{'features.get.return_value': True})
        response = self.call_mgmt_func(b'qubes.NotifyTools')
        self.assertIsNone(response)
        self.assertEqual(self.app.mock_calls, [])
        self.assertEqual(self.src.mock_calls, [
            mock.call.qdb.read('/qubes-tools/version'),
            mock.call.qdb.read('/qubes-tools/qrexec'),
            mock.call.qdb.read('/qubes-tools/gui'),
        ])

    def test_014_notify_tools_invalid_version(self):
        qdb_entries = {
            '/qubes-tools/version': b'this is invalid',
            '/qubes-tools/qrexec': b'0',
            '/qubes-tools/gui': b'0',
            '/qubes-tools/os': b'Linux',
            '/qubes-tools/default-user': b'user',
        }
        self.configure_qdb(qdb_entries)
        del self.src.template
        self.src.configure_mock(**{'features.get.return_value': True})
        with self.assertRaises(ValueError):
            self.call_mgmt_func(b'qubes.NotifyTools')
        self.assertEqual(self.app.mock_calls, [])
        self.assertEqual(self.src.mock_calls, [
            mock.call.qdb.read('/qubes-tools/version'),
            mock.call.qdb.read('/qubes-tools/qrexec'),
            mock.call.qdb.read('/qubes-tools/gui'),
        ])


    def test_015_notify_tools_invalid_value_qrexec(self):
        qdb_entries = {
            '/qubes-tools/version': b'1',
            '/qubes-tools/qrexec': b'invalid',
            '/qubes-tools/gui': b'0',
            '/qubes-tools/os': b'Linux',
            '/qubes-tools/default-user': b'user',
        }
        self.configure_qdb(qdb_entries)
        del self.src.template
        self.src.configure_mock(**{'features.get.return_value': True})
        with self.assertRaises(ValueError):
            self.call_mgmt_func(b'qubes.NotifyTools')
        self.assertEqual(self.app.mock_calls, [])
        self.assertEqual(self.src.mock_calls, [
            mock.call.qdb.read('/qubes-tools/version'),
            mock.call.qdb.read('/qubes-tools/qrexec'),
            mock.call.qdb.read('/qubes-tools/gui'),
        ])

    def test_016_notify_tools_invalid_value_gui(self):
        qdb_entries = {
            '/qubes-tools/version': b'1',
            '/qubes-tools/qrexec': b'1',
            '/qubes-tools/gui': b'invalid',
            '/qubes-tools/os': b'Linux',
            '/qubes-tools/default-user': b'user',
        }
        self.configure_qdb(qdb_entries)
        del self.src.template
        self.src.configure_mock(**{'features.get.return_value': True})
        with self.assertRaises(ValueError):
            self.call_mgmt_func(b'qubes.NotifyTools')
        self.assertEqual(self.app.mock_calls, [])
        self.assertEqual(self.src.mock_calls, [
            mock.call.qdb.read('/qubes-tools/version'),
            mock.call.qdb.read('/qubes-tools/qrexec'),
            mock.call.qdb.read('/qubes-tools/gui'),
        ])

    def test_017_notify_tools_template_based(self):
        qdb_entries = {
            '/qubes-tools/version': b'1',
            '/qubes-tools/qrexec': b'1',
            '/qubes-tools/gui': b'invalid',
            '/qubes-tools/os': b'Linux',
            '/qubes-tools/default-user': b'user',
        }
        self.configure_qdb(qdb_entries)
        self.src.configure_mock(**{'features.get.return_value': True})
        response = self.call_mgmt_func(b'qubes.NotifyTools')
        self.assertIsNone(response)
        self.assertEqual(self.app.mock_calls, [])
        self.assertEqual(self.src.mock_calls, [
            mock.call.template.__bool__(),
            mock.call.log.warning(
                'Ignoring qubes.NotifyTools for template-based VM')
        ])

    def test_018_notify_tools_already_installed(self):
        qdb_entries = {
            '/qubes-tools/version': b'1',
            '/qubes-tools/qrexec': b'1',
            '/qubes-tools/gui': b'1',
            '/qubes-tools/os': b'Linux',
            '/qubes-tools/default-user': b'user',
        }
        self.configure_qdb(qdb_entries)
        del self.src.template
        self.src.configure_mock(**{'features.get.return_value': True})
        response = self.call_mgmt_func(b'qubes.NotifyTools')
        self.assertIsNone(response)
        self.assertEqual(self.app.mock_calls, [
            mock.call.save()
        ])
        self.assertEqual(self.src.mock_calls, [
            mock.call.qdb.read('/qubes-tools/version'),
            mock.call.qdb.read('/qubes-tools/qrexec'),
            mock.call.qdb.read('/qubes-tools/gui'),
            mock.call.features.get('qrexec', False),
            mock.call.features.__setitem__('qrexec', True),
            mock.call.features.__setitem__('gui', True),
        ])

    def test_020_notify_updates_standalone(self):
        del self.src.template
        response = self.call_mgmt_func(b'qubes.NotifyUpdates', payload=b'1\n')
        self.assertIsNone(response)
        self.assertEqual(self.src.mock_calls, [
            mock.call.updateable.__bool__(),
        ])
        self.assertEqual(self.src.updates_available, True)
        self.assertEqual(self.app.mock_calls, [
            mock.call.save()
        ])

    def test_021_notify_updates_standalone2(self):
        del self.src.template
        response = self.call_mgmt_func(b'qubes.NotifyUpdates', payload=b'0\n')
        self.assertIsNone(response)
        self.assertEqual(self.src.mock_calls, [
            mock.call.updateable.__bool__(),
        ])
        self.assertEqual(self.src.updates_available, False)
        self.assertEqual(self.app.mock_calls, [
            mock.call.save()
        ])

    def test_022_notify_updates_invalid(self):
        del self.src.template
        with self.assertRaises(AssertionError):
            self.call_mgmt_func(b'qubes.NotifyUpdates', payload=b'')
        self.assertEqual(self.src.mock_calls, [])
        # not set property returns Mock()
        self.assertIsInstance(self.src.updates_available, mock.Mock)
        self.assertEqual(self.app.mock_calls, [])

    def test_023_notify_updates_invalid2(self):
        del self.src.template
        with self.assertRaises(AssertionError):
            self.call_mgmt_func(b'qubes.NotifyUpdates', payload=b'no updates')
        self.assertEqual(self.src.mock_calls, [])
        # not set property returns Mock()
        self.assertIsInstance(self.src.updates_available, mock.Mock)
        self.assertEqual(self.app.mock_calls, [])

    def test_024_notify_updates_template_based_no_updates(self):
        '''No updates on template-based VM, should not reset state'''
        self.src.updateable = False
        self.src.template.is_running.return_value = False
        response = self.call_mgmt_func(b'qubes.NotifyUpdates', payload=b'0\n')
        self.assertIsNone(response)
        self.assertEqual(self.src.mock_calls, [
            mock.call.template.is_running(),
        ])
        # not set property returns Mock()
        self.assertIsInstance(self.src.template.updates_available, mock.Mock)
        self.assertIsInstance(self.src.updates_available, mock.Mock)
        self.assertEqual(self.app.mock_calls, [])

    def test_025_notify_updates_template_based(self):
        '''Some updates on template-based VM, should save flag'''
        self.src.updateable = False
        self.src.template.is_running.return_value = False
        self.src.storage.outdated_volumes = []
        response = self.call_mgmt_func(b'qubes.NotifyUpdates', payload=b'1\n')
        self.assertIsNone(response)
        self.assertEqual(self.src.mock_calls, [
            mock.call.template.is_running(),
        ])
        # not set property returns Mock()
        self.assertIsInstance(self.src.updates_available, mock.Mock)
        self.assertEqual(self.src.template.updates_available, True)
        self.assertEqual(self.app.mock_calls, [
            mock.call.save()
        ])

    def test_026_notify_updates_template_based_outdated(self):
        self.src.updateable = False
        self.src.template.is_running.return_value = False
        self.src.storage.outdated_volumes = ['root']
        response = self.call_mgmt_func(b'qubes.NotifyUpdates', payload=b'1\n')
        self.assertIsNone(response)
        self.assertEqual(self.src.mock_calls, [
            mock.call.template.is_running(),
        ])
        # not set property returns Mock()
        self.assertIsInstance(self.src.updates_available, mock.Mock)
        self.assertIsInstance(self.src.template.updates_available, mock.Mock)
        self.assertEqual(self.app.mock_calls, [])

    def test_027_notify_updates_template_based_template_running(self):
        self.src.updateable = False
        self.src.template.is_running.return_value = True
        self.src.storage.outdated_volumes = []
        response = self.call_mgmt_func(b'qubes.NotifyUpdates', payload=b'1\n')
        self.assertIsNone(response)
        self.assertEqual(self.src.mock_calls, [
            mock.call.template.is_running(),
        ])
        # not set property returns Mock()
        self.assertIsInstance(self.src.template.updates_available, mock.Mock)
        self.assertIsInstance(self.src.updates_available, mock.Mock)
        self.assertEqual(self.app.mock_calls, [])

