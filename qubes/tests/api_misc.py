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
import asyncio
from datetime import datetime
from unittest import mock
import qubes.tests
import qubes.api.misc


class TC_00_API_Misc(qubes.tests.QubesTestCase):
    maxDiff = None
    def setUp(self):
        super(TC_00_API_Misc, self).setUp()
        self.tpl = mock.NonCallableMagicMock(name='template')
        del self.tpl.template
        self.async_src = mock.AsyncMock()
        self.src = mock.NonCallableMagicMock(name='appvm',
            template=self.tpl)
        self.src.configure_mock(fire_event_async=self.async_src)
        self.app = mock.NonCallableMock()
        self.dest = mock.NonCallableMock()
        self.dest.name = 'dom0'
        self.app.configure_mock(domains={
            'dom0': self.dest,
            'test-vm': self.src,
        })

    def configure_qdb(self, entries):
        self.src.configure_mock(**{
            'untrusted_qdb.read.side_effect': (
                lambda path: entries.get(path, None)),
            'untrusted_qdb.list.side_effect': (
                lambda path: sorted(entries.keys())),
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
            mock.call.untrusted_qdb.list('/features-request/'),
            mock.call.untrusted_qdb.read('/features-request/feature1'),
            mock.call.untrusted_qdb.read('/features-request/feature2'),
            mock.call.untrusted_qdb.read('/features-request/feature3'),
            mock.call.fire_event_async('features-request', untrusted_features={
                'feature1': '1', 'feature2': '', 'feature3': 'other'}),
        ])

    def test_001_features_request_empty(self):
        self.configure_qdb({})
        response = self.call_mgmt_func(b'qubes.FeaturesRequest')
        self.assertIsNone(response)
        self.assertEqual(self.app.mock_calls, [
            mock.call.save()
        ])
        self.assertEqual(self.src.mock_calls, [
            mock.call.untrusted_qdb.list('/features-request/'),
            mock.call.fire_event_async('features-request',
                untrusted_features={}),
        ])

    def test_002_features_request_invalid1(self):
        qdb_entries = {
            '/features-request/feature1': b'test spaces',
        }
        self.configure_qdb(qdb_entries)
        with self.assertRaises(qubes.api.PermissionDenied):
            self.call_mgmt_func(b'qubes.FeaturesRequest')
        self.assertEqual(self.app.mock_calls, [])
        self.assertEqual(self.src.mock_calls, [
            mock.call.untrusted_qdb.list('/features-request/'),
            mock.call.untrusted_qdb.read('/features-request/feature1'),
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
            mock.call.untrusted_qdb.list('/features-request/'),
            mock.call.untrusted_qdb.read('/features-request/feature1'),
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
        response = self.call_mgmt_func(b'qubes.NotifyTools')
        self.assertIsNone(response)
        self.assertEqual(self.app.mock_calls, [
            mock.call.save()
        ])
        self.assertEqual(self.src.mock_calls, [
            mock.call.untrusted_qdb.read('/qubes-tools/qrexec'),
            mock.call.untrusted_qdb.read('/qubes-tools/gui'),
            mock.call.untrusted_qdb.read('/qubes-tools/gui-emulated'),
            mock.call.untrusted_qdb.read('/qubes-tools/default-user'),
            mock.call.untrusted_qdb.read('/qubes-tools/os'),
            mock.call.fire_event_async('features-request', untrusted_features={
                'gui': '1',
                'default-user': 'user',
                'qrexec': '1',
                'os': 'Linux'}),
        ])
        self.assertEqual(self.app.mock_calls, [mock.call.save()])

    def test_013_notify_tools_no_version(self):
        qdb_entries = {
            '/qubes-tools/qrexec': b'1',
            '/qubes-tools/gui': b'1',
            '/qubes-tools/os': b'Linux',
            '/qubes-tools/default-user': b'user',
        }
        self.configure_qdb(qdb_entries)
        response = self.call_mgmt_func(b'qubes.NotifyTools')
        self.assertIsNone(response)
        self.assertEqual(self.src.mock_calls, [
            mock.call.untrusted_qdb.read('/qubes-tools/qrexec'),
            mock.call.untrusted_qdb.read('/qubes-tools/gui'),
            mock.call.untrusted_qdb.read('/qubes-tools/gui-emulated'),
            mock.call.untrusted_qdb.read('/qubes-tools/default-user'),
            mock.call.untrusted_qdb.read('/qubes-tools/os'),
            mock.call.fire_event_async('features-request', untrusted_features={
                'gui': '1',
                'default-user': 'user',
                'qrexec': '1',
                'os': 'Linux'}),
        ])
        self.assertEqual(self.app.mock_calls, [mock.call.save()])

    def test_015_notify_tools_invalid_value_qrexec(self):
        qdb_entries = {
            '/qubes-tools/version': b'1',
            '/qubes-tools/qrexec': b'invalid value',
            '/qubes-tools/gui': b'0',
            '/qubes-tools/os': b'Linux',
            '/qubes-tools/default-user': b'user',
        }
        self.configure_qdb(qdb_entries)
        with self.assertRaises(qubes.api.PermissionDenied):
            self.call_mgmt_func(b'qubes.NotifyTools')
        self.assertEqual(self.app.mock_calls, [])
        self.assertEqual(self.src.mock_calls, [
            mock.call.untrusted_qdb.read('/qubes-tools/qrexec'),
        ])

    def test_016_notify_tools_invalid_value_gui(self):
        qdb_entries = {
            '/qubes-tools/version': b'1',
            '/qubes-tools/qrexec': b'1',
            '/qubes-tools/gui': b'invalid value',
            '/qubes-tools/os': b'Linux',
            '/qubes-tools/default-user': b'user',
        }
        self.configure_qdb(qdb_entries)
        with self.assertRaises(qubes.api.PermissionDenied):
            self.call_mgmt_func(b'qubes.NotifyTools')
        self.assertEqual(self.app.mock_calls, [])
        self.assertEqual(self.src.mock_calls, [
            mock.call.untrusted_qdb.read('/qubes-tools/qrexec'),
            mock.call.untrusted_qdb.read('/qubes-tools/gui'),
        ])

    def test_020_notify_updates_standalone(self):
        del self.src.template
        with DatetimeMock() as mock_date:
            response = self.call_mgmt_func(
                b'qubes.NotifyUpdates', payload=b'1\n')
            self.assertIsNone(response)
            expected = [
                mock.call.updateable.__bool__(),
                mock.call.features.__getitem__('updates-available'),
                mock.call.features.__getitem__().__bool__(),
                mock.call.features.__setitem__('updates-available', True),
                mock.call.features.__setitem__(
                    'last-updates-check', mock_date.str
                ),
            ]
        self.assertEqual(self.src.mock_calls, expected,
                         "\nActual:\n" + str(self.src.mock_calls) +
                         "\nExpected\n" + str(expected))
        self.assertEqual(self.app.mock_calls, [mock.call.save()])

    def test_021_notify_updates_standalone2(self):
        del self.src.template
        with DatetimeMock() as mock_date:
            response = self.call_mgmt_func(
                b'qubes.NotifyUpdates', payload=b'0\n')
            self.assertIsNone(response)
            expected = [
                mock.call.updateable.__bool__(),
                mock.call.features.__getitem__('updates-available'),
                mock.call.features.__getitem__().__bool__(),
                mock.call.features.__setitem__('last-update', mock_date.str),
                mock.call.features.__setitem__('updates-available', False),
                mock.call.features.__setitem__(
                    'last-updates-check', mock_date.str
                ),
            ]
        self.assertEqual(self.src.mock_calls, expected,
                         "\nActual:\n" + str(self.src.mock_calls) +
                         "\nExpected\n" + str(expected))
        self.assertEqual(self.app.mock_calls, [
            mock.call.save()
        ])

    def test_022_notify_updates_invalid(self):
        del self.src.template
        with self.assertRaises(qubes.api.PermissionDenied):
            self.call_mgmt_func(b'qubes.NotifyUpdates', payload=b'')
        self.assertEqual(self.src.mock_calls, [])
        self.assertEqual(self.tpl.mock_calls, [])
        self.assertEqual(self.app.mock_calls, [])

    def test_023_notify_updates_invalid2(self):
        del self.src.template
        with self.assertRaises(qubes.api.PermissionDenied):
            self.call_mgmt_func(b'qubes.NotifyUpdates', payload=b'no updates')
        self.assertEqual(self.src.mock_calls, [])
        self.assertEqual(self.tpl.mock_calls, [])
        self.assertEqual(self.app.mock_calls, [])

    def test_024_notify_updates_template_based_no_updates(self):
        '''No updates on template-based VM, should not reset state'''
        self.src.updateable = False
        self.src.template.is_running.return_value = False
        response = self.call_mgmt_func(b'qubes.NotifyUpdates', payload=b'0\n')
        self.assertIsNone(response)
        self.assertEqual(self.tpl.mock_calls, [
            mock.call.updateable.__bool__(),
            mock.call.is_running(),
        ])
        self.assertEqual(self.app.mock_calls, [])

    def test_025_notify_updates_template_based(self):
        '''Some updates on template-based VM, should save flag'''
        self.src.updateable = False
        self.tpl.is_running.return_value = False
        self.src.storage.outdated_volumes = []
        with DatetimeMock() as mock_date:
            response = self.call_mgmt_func(
                b'qubes.NotifyUpdates', payload=b'1\n')
            self.assertIsNone(response)
            expected = [
                mock.call.updateable.__bool__(),
                mock.call.is_running(),
                mock.call.features.__getitem__('updates-available'),
                mock.call.features.__getitem__().__bool__(),
                mock.call.features.__setitem__('updates-available', True),
                mock.call.features.__setitem__(
                    'last-updates-check', mock_date.str
                ),
            ]

        self.assertEqual(self.src.mock_calls, [])
        self.assertEqual(self.tpl.mock_calls, expected,
                         "\nActual:\n" + str(self.tpl.mock_calls) +
                         "\nExpected\n" + str(expected))
        self.assertEqual(self.app.mock_calls, [
            mock.call.save()
        ])

    def test_026_notify_updates_template_based_outdated(self):
        self.src.updateable = False
        self.src.template.is_running.return_value = False
        self.src.storage.outdated_volumes = ['root']
        response = self.call_mgmt_func(b'qubes.NotifyUpdates', payload=b'1\n')
        self.assertIsNone(response)
        self.assertEqual(self.src.mock_calls, [])
        self.assertEqual(self.tpl.mock_calls, [
            mock.call.updateable.__bool__(),
            mock.call.is_running(),
        ])
        self.assertIsInstance(self.tpl.updates_available, mock.Mock)
        self.assertEqual(self.app.mock_calls, [])

    def test_027_notify_updates_template_based_template_running(self):
        self.src.updateable = False
        self.src.template.is_running.return_value = True
        self.src.storage.outdated_volumes = []
        response = self.call_mgmt_func(b'qubes.NotifyUpdates', payload=b'1\n')
        self.assertIsNone(response)
        self.assertEqual(self.src.mock_calls, [])
        self.assertEqual(self.tpl.mock_calls, [
            mock.call.updateable.__bool__(),
            mock.call.is_running(),
        ])
        self.assertIsInstance(self.src.updates_available, mock.Mock)
        self.assertEqual(self.app.mock_calls, [])

    def test_028_notify_updates_template_based_dispvm(self):
        self.dvm = self.src
        self.dvm.updateable = False
        self.srv = mock.NonCallableMagicMock(template=self.dvm)
        self.src.updateable = False
        self.src.template.is_running.return_value = False
        self.src.storage.outdated_volumes = []
        with DatetimeMock() as mock_date:
            response = self.call_mgmt_func(
                b'qubes.NotifyUpdates', payload=b'1\n')
            self.assertIsNone(response)
            expected = [
                mock.call.updateable.__bool__(),
                mock.call.is_running(),
                mock.call.features.__getitem__('updates-available'),
                mock.call.features.__getitem__().__bool__(),
                mock.call.features.__setitem__('updates-available', True),
                mock.call.features.__setitem__(
                    'last-updates-check', mock_date.str
                ),
            ]
        self.assertEqual(self.src.mock_calls, [])
        self.assertEqual(self.tpl.mock_calls, expected,
                         "\nActual:\n" + str(self.tpl.mock_calls) +
                         "\nExpected\n" + str(expected))
        self.assertEqual(self.dvm.mock_calls, [])
        self.assertIsInstance(self.src.updates_available, mock.Mock)
        self.assertEqual(self.app.mock_calls, [
            mock.call.save()
        ])


class DatetimeMock:
    def __init__(self, year=2038, month=1, day=19, hour=3, minute=14, second=7):
        self.mock_date = None
        self.datetime = datetime(year, month, day, hour, minute, second)

    def __enter__(self):
        self.mock_date = mock.patch('qubes.api.misc.datetime').start()
        self.mock_date.today.return_value = self.datetime
        self.mock_date.side_effect = lambda *args, **kw: datetime(*args, **kw)
        self.mock_date.str = self.datetime.strftime('%Y-%m-%d %H:%M:%S')
        return self.mock_date

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.mock_date.stop()
