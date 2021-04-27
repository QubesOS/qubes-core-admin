# -*- encoding: utf-8 -*-
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
import qubes.ext.core_features
import qubes.ext.services
import qubes.ext.windows
import qubes.tests

from unittest import mock

class TC_00_CoreFeatures(qubes.tests.QubesTestCase):
    def setUp(self):
        super().setUp()
        self.ext = qubes.ext.core_features.CoreFeatures()
        self.vm = mock.AsyncMock()
        self.features = {}
        self.vm.configure_mock(**{
            'features.get.side_effect': self.features.get,
            'features.items.side_effect': self.features.items,
            'features.__iter__.side_effect': self.features.__iter__,
            'features.__contains__.side_effect': self.features.__contains__,
            'features.__setitem__.side_effect': self.features.__setitem__,
            'features.__delitem__.side_effect': self.features.__delitem__,
            })

    def test_010_notify_tools(self):
        del self.vm.template
        self.loop.run_until_complete(
            self.ext.qubes_features_request(self.vm, 'features-request',
                untrusted_features={
                    'gui': '1',
                    'version': '1',
                    'default-user': 'user',
                    'qrexec': '1',
                    'vmexec': '1'}))
        self.assertListEqual(self.vm.mock_calls, [
            ('features.get', ('qrexec', False), {}),
            ('features.__contains__', ('qrexec',), {}),
            ('features.__setitem__', ('qrexec', True), {}),
            ('features.__contains__', ('gui',), {}),
            ('features.__setitem__', ('gui', True), {}),
            ('features.__setitem__', ('vmexec', True), {}),
            ('features.get', ('qrexec', False), {}),
            ('fire_event_async', ('template-postinstall',), {}),
            ('fire_event_async().__iter__', (), {}),
        ])

    def test_011_notify_tools_uninstall(self):
        del self.vm.template
        self.loop.run_until_complete(
            self.ext.qubes_features_request(self.vm, 'features-request',
                untrusted_features={
                    'gui': '0',
                    'version': '1',
                    'default-user': 'user',
                    'qrexec': '0',
                    'vmexec': '0'}))
        self.assertListEqual(self.vm.mock_calls, [
            ('features.get', ('qrexec', False), {}),
            ('features.__contains__', ('qrexec',), {}),
            ('features.__setitem__', ('qrexec', False), {}),
            ('features.__contains__', ('gui',), {}),
            ('features.__setitem__', ('gui', False), {}),
            ('features.__setitem__', ('vmexec', False), {}),
            ('features.get', ('qrexec', False), {}),
        ])

    def test_012_notify_tools_uninstall2(self):
        del self.vm.template
        self.loop.run_until_complete(
            self.ext.qubes_features_request(self.vm, 'features-request',
                untrusted_features={
                    'version': '1',
                    'default-user': 'user',
                }))
        self.assertListEqual(self.vm.mock_calls, [
            ('features.get', ('qrexec', False), {}),
            ('features.get', ('qrexec', False), {}),
        ])

    def test_013_notify_tools_no_version(self):
        del self.vm.template
        self.loop.run_until_complete(
            self.ext.qubes_features_request(self.vm, 'features-request',
                untrusted_features={
                    'qrexec': '1',
                    'gui': '1',
                    'default-user': 'user',
                }))
        self.assertListEqual(self.vm.mock_calls, [
            ('features.get', ('qrexec', False), {}),
            ('features.__contains__', ('qrexec',), {}),
            ('features.__setitem__', ('qrexec', True), {}),
            ('features.__contains__', ('gui',), {}),
            ('features.__setitem__', ('gui', True), {}),
            ('features.get', ('qrexec', False), {}),
            ('fire_event_async', ('template-postinstall',), {}),
            ('fire_event_async().__iter__', (), {}),
        ])

    def test_015_notify_tools_invalid_value_qrexec(self):
        del self.vm.template
        self.loop.run_until_complete(
            self.ext.qubes_features_request(self.vm, 'features-request',
                untrusted_features={
                    'version': '1',
                    'qrexec': 'invalid',
                    'gui': '1',
                    'default-user': 'user',
                }))
        self.assertEqual(self.vm.mock_calls, [
            ('features.get', ('qrexec', False), {}),
            ('features.__contains__', ('gui',), {}),
            ('features.__setitem__', ('gui', True), {}),
            ('features.get', ('qrexec', False), {}),
        ])

    def test_016_notify_tools_invalid_value_gui(self):
        del self.vm.template
        self.loop.run_until_complete(
            self.ext.qubes_features_request(self.vm, 'features-request',
                untrusted_features={
                    'version': '1',
                    'qrexec': '1',
                    'gui': 'invalid',
                    'default-user': 'user',
                }))
        self.assertListEqual(self.vm.mock_calls, [
            ('features.get', ('qrexec', False), {}),
            ('features.__contains__', ('qrexec',), {}),
            ('features.__setitem__', ('qrexec', True), {}),
            ('features.get', ('qrexec', False), {}),
            ('fire_event_async', ('template-postinstall',), {}),
            ('fire_event_async().__iter__', (), {}),
        ])

    def test_017_notify_tools_template_based(self):
        self.loop.run_until_complete(
            self.ext.qubes_features_request(self.vm, 'features-request',
                untrusted_features={
                    'version': '1',
                    'qrexec': '1',
                    'gui': '1',
                    'default-user': 'user',
                }))
        self.assertEqual(self.vm.mock_calls, [
            ('template.__bool__', (), {}),
            ('log.warning', ('Ignoring qubes.NotifyTools for template-based '
                             'VM',), {})
        ])

    def test_018_notify_tools_already_installed(self):
        self.features['qrexec'] = True
        self.features['gui'] = True
        del self.vm.template
        self.loop.run_until_complete(
            self.ext.qubes_features_request(self.vm, 'features-request',
                untrusted_features={
                    'gui': '1',
                    'version': '1',
                    'default-user': 'user',
                    'qrexec': '1'}))
        self.assertListEqual(self.vm.mock_calls, [
            ('features.get', ('qrexec', False), {}),
            ('features.__contains__', ('qrexec',), {}),
            ('features.__contains__', ('gui',), {}),
        ])

    def test_100_servicevm_feature(self):
        self.vm.provides_network = True
        self.ext.set_servicevm_feature(self.vm)
        self.assertEqual(self.features['servicevm'], 1)

        self.vm.provides_network = False
        self.ext.set_servicevm_feature(self.vm)
        self.assertNotIn('servicevm', self.features)


class TC_10_WindowsFeatures(qubes.tests.QubesTestCase):
    def setUp(self):
        super().setUp()
        self.ext = qubes.ext.windows.WindowsFeatures()
        self.vm = mock.MagicMock()
        self.features = {}
        self.vm.configure_mock(**{
            'features.get.side_effect': self.features.get,
            'features.__contains__.side_effect': self.features.__contains__,
            'features.__setitem__.side_effect': self.features.__setitem__,
            })

    def test_000_notify_tools_full(self):
        del self.vm.template
        self.ext.qubes_features_request(self.vm, 'features-request',
            untrusted_features={
                'gui': '1',
                'version': '1',
                'default-user': 'user',
                'qrexec': '1',
                'os': 'Windows'})
        self.assertEqual(self.vm.mock_calls, [
            ('features.__setitem__', ('os', 'Windows'), {}),
            ('features.__setitem__', ('rpc-clipboard', True), {}),
        ])

    def test_001_notify_tools_no_qrexec(self):
        del self.vm.template
        self.ext.qubes_features_request(self.vm, 'features-request',
            untrusted_features={
                'gui': '1',
                'version': '1',
                'default-user': 'user',
                'qrexec': '0',
                'os': 'Windows'})
        self.assertEqual(self.vm.mock_calls, [
            ('features.__setitem__', ('os', 'Windows'), {}),
        ])

    def test_002_notify_tools_other_os(self):
        del self.vm.template
        self.ext.qubes_features_request(self.vm, 'features-request',
            untrusted_features={
                'gui': '1',
                'version': '1',
                'default-user': 'user',
                'qrexec': '1',
                'os': 'other'})
        self.assertEqual(self.vm.mock_calls, [])

class TC_20_Services(qubes.tests.QubesTestCase):
    def setUp(self):
        super().setUp()
        self.ext = qubes.ext.services.ServicesExtension()
        self.features = {}
        specs = {
            'features.get.side_effect': self.features.get,
            'features.items.side_effect': self.features.items,
            'features.__iter__.side_effect': self.features.__iter__,
            'features.__contains__.side_effect': self.features.__contains__,
            'features.__setitem__.side_effect': self.features.__setitem__,
            'features.__delitem__.side_effect': self.features.__delitem__,
        }
        vmspecs = {**specs, **{
            'template': None,
            'maxmem': 1024,
            'is_running.return_value': True,
            }}
        dom0specs = {**specs, **{
            'name': "dom0",
            }}
        self.vm = mock.MagicMock()
        self.vm.configure_mock(**vmspecs)
        self.dom0 = mock.MagicMock()
        self.dom0.configure_mock(**dom0specs)

    def test_000_write_to_qdb(self):
        self.features['service.test1'] = '1'
        self.features['service.test2'] = ''

        self.ext.on_domain_qdb_create(self.vm, 'domain-qdb-create')
        self.assertEqual(sorted(self.vm.untrusted_qdb.mock_calls), [
            ('write', ('/qubes-service/meminfo-writer', '1'), {}),
            ('write', ('/qubes-service/test1', '1'), {}),
            ('write', ('/qubes-service/test2', '0'), {}),
        ])

    def test_001_feature_set(self):
        self.ext.on_domain_feature_set(self.vm,
            'feature-set:service.test_no_oldvalue',
            'service.test_no_oldvalue', '1')
        self.ext.on_domain_feature_set(self.vm,
            'feature-set:service.test_oldvalue',
            'service.test_oldvalue', '1', '')
        self.ext.on_domain_feature_set(self.vm,
            'feature-set:service.test_disable',
            'service.test_disable', '', '1')
        self.ext.on_domain_feature_set(self.vm,
            'feature-set:service.test_disable_no_oldvalue',
            'service.test_disable_no_oldvalue', '')

        self.assertEqual(sorted(self.vm.untrusted_qdb.mock_calls), sorted([
            ('write', ('/qubes-service/test_no_oldvalue', '1'), {}),
            ('write', ('/qubes-service/test_oldvalue', '1'), {}),
            ('write', ('/qubes-service/test_disable', '0'), {}),
            ('write', ('/qubes-service/test_disable_no_oldvalue', '0'), {}),
        ]))

    def test_002_feature_delete(self):
        self.ext.on_domain_feature_delete(self.vm,
            'feature-delete:service.test3', 'service.test3')
        self.assertEqual(sorted(self.vm.untrusted_qdb.mock_calls), [
            ('rm', ('/qubes-service/test3',), {}),
        ])

    def test_010_supported_services(self):
        self.ext.supported_services(self.vm, 'features-request',
            untrusted_features={
                'supported-service.test1': '1',  # ok
                'supported-service.test2': '0',  # ignored
                'supported-service.test3': 'some text',  # ignored
                'no-service': '1',  # ignored
            })
        self.assertEqual(self.features, {
            'supported-service.test1': True,
        })

    def test_011_supported_services_add(self):
        self.features['supported-service.test1'] = '1'
        self.ext.supported_services(self.vm, 'features-request',
            untrusted_features={
                'supported-service.test1': '1',  # ok
                'supported-service.test2': '1',  # ok
            })
        # also check if existing one is untouched
        self.assertEqual(self.features, {
            'supported-service.test1': '1',
            'supported-service.test2': True,
        })

    def test_012_supported_services_remove(self):
        self.features['supported-service.test1'] = '1'
        self.ext.supported_services(self.vm, 'features-request',
            untrusted_features={
                'supported-service.test2': '1',  # ok
            })
        self.assertEqual(self.features, {
            'supported-service.test2': True,
        })

    def test_013_feature_set_dom0(self):
        self.test_base_dir = '/tmp/qubes-test-dir'
        self.base_dir_patch = mock.patch.dict(
            qubes.config.system_path, {'dom0_services_dir': self.test_base_dir})
        self.base_dir_patch.start()
        self.addCleanup(self.base_dir_patch.stop)
        service = 'guivm-gui-agent'
        service_path = self.test_base_dir + '/' + service

        self.ext.on_domain_feature_set(
            self.dom0,
            'feature-set:service.service.guivm-gui-agent',
            'service.guivm-gui-agent', '1')
        self.assertEqual(os.path.exists(service_path), True)

    def test_014_feature_delete_dom0(self):
        self.test_base_dir = '/tmp/qubes-test-dir'
        self.base_dir_patch = mock.patch.dict(
            qubes.config.system_path, {'dom0_services_dir': self.test_base_dir})
        self.base_dir_patch.start()
        self.addCleanup(self.base_dir_patch.stop)
        service = 'guivm-gui-agent'
        service_path = self.test_base_dir + '/' + service

        self.ext.on_domain_feature_set(
            self.dom0,
            'feature-set:service.service.guivm-gui-agent',
            'service.guivm-gui-agent', '1')

        self.ext.on_domain_feature_delete(
            self.dom0,
            'feature-delete:service.service.guivm-gui-agent',
            'service.guivm-gui-agent')

        self.assertEqual(os.path.exists(service_path), False)

    def test_014_feature_set_empty_value_dom0(self):
        self.test_base_dir = '/tmp/qubes-test-dir'
        self.base_dir_patch = mock.patch.dict(
            qubes.config.system_path, {'dom0_services_dir': self.test_base_dir})
        self.base_dir_patch.start()
        self.addCleanup(self.base_dir_patch.stop)
        service = 'guivm-gui-agent'
        service_path = self.test_base_dir + '/' + service

        self.ext.on_domain_feature_set(
            self.dom0,
            'feature-set:service.service.guivm-gui-agent',
            'service.guivm-gui-agent', '')

        self.assertEqual(os.path.exists(service_path), False)

class TC_30_SupportedFeatures(qubes.tests.QubesTestCase):
    def setUp(self):
        super().setUp()
        self.ext = qubes.ext.supported_features.SupportedFeaturesExtension()
        self.features = {}
        specs = {
            'features.get.side_effect': self.features.get,
            'features.items.side_effect': self.features.items,
            'features.__iter__.side_effect': self.features.__iter__,
            'features.__contains__.side_effect': self.features.__contains__,
            'features.__setitem__.side_effect': self.features.__setitem__,
            'features.__delitem__.side_effect': self.features.__delitem__,
        }
        vmspecs = {**specs, **{
            'template': None,
            'maxmem': 1024,
            'is_running.return_value': True,
            }}
        dom0specs = {**specs, **{
            'name': "dom0",
            }}
        self.vm = mock.MagicMock()
        self.vm.configure_mock(**vmspecs)
        self.dom0 = mock.MagicMock()
        self.dom0.configure_mock(**dom0specs)

    def test_010_supported_features(self):
        self.ext.supported_features(self.vm, 'features-request',
            untrusted_features={
                'supported-feature.test1': '1',  # ok
                'supported-feature.test2': '0',  # ignored
                'supported-feature.test3': 'some text',  # ignored
                'no-feature': '1',  # ignored
            })
        self.assertEqual(self.features, {
            'supported-feature.test1': True,
        })

    def test_011_supported_features_add(self):
        self.features['supported-feature.test1'] = '1'
        self.ext.supported_features(self.vm, 'features-request',
            untrusted_features={
                'supported-feature.test1': '1',  # ok
                'supported-feature.test2': '1',  # ok
            })
        # also check if existing one is untouched
        self.assertEqual(self.features, {
            'supported-feature.test1': '1',
            'supported-feature.test2': True,
        })

    def test_012_supported_features_remove(self):
        self.features['supported-feature.test1'] = '1'
        self.ext.supported_features(self.vm, 'features-request',
            untrusted_features={
                'supported-feature.test2': '1',  # ok
            })
        self.assertEqual(self.features, {
            'supported-feature.test2': True,
        })
