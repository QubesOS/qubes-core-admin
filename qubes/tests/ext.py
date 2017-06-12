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

from unittest import mock

import qubes.ext.core_features
import qubes.tests


class TC_00_CoreFeatures(qubes.tests.QubesTestCase):
    def setUp(self):
        super().setUp()
        self.ext = qubes.ext.core_features.CoreFeatures()
        self.vm = mock.MagicMock()
        self.features = {}
        self.vm.configure_mock(**{
            'features.get.side_effect': self.features.get,
            'features.__contains__.side_effect': self.features.__contains__,
            'features.__setitem__.side_effect': self.features.__setitem__,
            })

    def test_010_notify_tools(self):
        del self.vm.template
        self.ext.qubes_features_request(self.vm, 'features-request',
            untrusted_features={
                'gui': '1',
                'version': '1',
                'default-user': 'user',
                'qrexec': '1'}),
        self.assertEqual(self.vm.mock_calls, [
            ('features.get', ('qrexec', False), {}),
            ('features.__contains__', ('qrexec',), {}),
            ('features.__setitem__', ('qrexec', True), {}),
            ('features.__contains__', ('gui',), {}),
            ('features.__setitem__', ('gui', True), {}),
            ('features.get', ('qrexec', False), {}),
            ('fire_event', ('template-postinstall',), {})
        ])

    def test_011_notify_tools_uninstall(self):
        del self.vm.template
        self.ext.qubes_features_request(self.vm, 'features-request',
            untrusted_features={
                'gui': '0',
                'version': '1',
                'default-user': 'user',
                'qrexec': '0'}),
        self.assertEqual(self.vm.mock_calls, [
            ('features.get', ('qrexec', False), {}),
            ('features.__contains__', ('qrexec',), {}),
            ('features.__setitem__', ('qrexec', False), {}),
            ('features.__contains__', ('gui',), {}),
            ('features.__setitem__', ('gui', False), {}),
            ('features.get', ('qrexec', False), {}),
        ])

    def test_012_notify_tools_uninstall2(self):
        del self.vm.template
        self.ext.qubes_features_request(self.vm, 'features-request',
            untrusted_features={
                'version': '1',
                'default-user': 'user',
            })
        self.assertEqual(self.vm.mock_calls, [
            ('features.get', ('qrexec', False), {}),
            ('features.get', ('qrexec', False), {}),
        ])

    def test_013_notify_tools_no_version(self):
        del self.vm.template
        self.ext.qubes_features_request(self.vm, 'features-request',
            untrusted_features={
                'qrexec': '1',
                'gui': '1',
                'default-user': 'user',
            })
        self.assertEqual(self.vm.mock_calls, [
            ('features.get', ('qrexec', False), {}),
            ('features.__contains__', ('qrexec',), {}),
            ('features.__setitem__', ('qrexec', True), {}),
            ('features.__contains__', ('gui',), {}),
            ('features.__setitem__', ('gui', True), {}),
            ('features.get', ('qrexec', False), {}),
            ('fire_event', ('template-postinstall',), {})
        ])

    def test_014_notify_tools_invalid_version(self):
        del self.vm.template
        with self.assertRaises(ValueError):
            self.ext.qubes_features_request(self.vm, 'features-request',
                untrusted_features={
                    'version': 'this is invalid',
                    'qrexec': '1',
                    'gui': '1',
                    'default-user': 'user',
                })
        self.assertEqual(self.vm.mock_calls, [])

    def test_015_notify_tools_invalid_value_qrexec(self):
        del self.vm.template
        self.ext.qubes_features_request(self.vm, 'features-request',
            untrusted_features={
                'version': '1',
                'qrexec': 'invalid',
                'gui': '1',
                'default-user': 'user',
            })
        self.assertEqual(self.vm.mock_calls, [
            ('features.get', ('qrexec', False), {}),
            ('features.__contains__', ('gui',), {}),
            ('features.__setitem__', ('gui', True), {}),
            ('features.get', ('qrexec', False), {}),
        ])

    def test_016_notify_tools_invalid_value_gui(self):
        del self.vm.template
        self.ext.qubes_features_request(self.vm, 'features-request',
            untrusted_features={
                'version': '1',
                'qrexec': '1',
                'gui': 'invalid',
                'default-user': 'user',
            })
        self.assertEqual(self.vm.mock_calls, [
            ('features.get', ('qrexec', False), {}),
            ('features.__contains__', ('qrexec',), {}),
            ('features.__setitem__', ('qrexec', True), {}),
            ('features.get', ('qrexec', False), {}),
            ('fire_event', ('template-postinstall',), {})
        ])

    def test_017_notify_tools_template_based(self):
        self.ext.qubes_features_request(self.vm, 'features-request',
            untrusted_features={
                'version': '1',
                'qrexec': '1',
                'gui': '1',
                'default-user': 'user',
            })
        self.assertEqual(self.vm.mock_calls, [
            ('template.__bool__', (), {}),
            ('log.warning', ('Ignoring qubes.NotifyTools for template-based '
                             'VM',), {})
        ])

    def test_018_notify_tools_already_installed(self):
        self.features['qrexec'] = True
        self.features['gui'] = True
        del self.vm.template
        self.ext.qubes_features_request(self.vm, 'features-request',
            untrusted_features={
                'gui': '1',
                'version': '1',
                'default-user': 'user',
                'qrexec': '1'}),
        self.assertEqual(self.vm.mock_calls, [
            ('features.get', ('qrexec', False), {}),
            ('features.__contains__', ('qrexec',), {}),
            ('features.__contains__', ('gui',), {}),
        ])
