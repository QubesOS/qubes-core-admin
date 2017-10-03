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

import lxml.etree

import qubes.storage
import qubes.tests
import qubes.tests.vm.qubesvm
import qubes.vm.appvm
import qubes.vm.templatevm

class TestApp(object):
    labels = {1: qubes.Label(1, '0xcc0000', 'red')}

    def __init__(self):
        self.domains = {}

class TestProp(object):
    # pylint: disable=too-few-public-methods
    __name__ = 'testprop'

class TestVM(object):
    # pylint: disable=too-few-public-methods
    app = TestApp()

    def __init__(self, **kwargs):
        self.running = False
        self.installed_by_rpm = False
        for k, v in kwargs.items():
            setattr(self, k, v)

    def is_running(self):
        return self.running

class TestPool(qubes.storage.Pool):
    def init_volume(self, vm, volume_config):
        vid = '{}/{}'.format(vm.name, volume_config['name'])
        assert volume_config.pop('pool', None) == self
        return qubes.storage.Volume(vid=vid, pool=self, **volume_config)


class TC_90_AppVM(qubes.tests.vm.qubesvm.QubesVMTestsMixin,
        qubes.tests.QubesTestCase):
    def setUp(self):
        super().setUp()
        self.app.pools['default'] = TestPool('default')
        self.app.pools['linux-kernel'] = mock.Mock(**{
            'init_volume.return_value.pool': 'linux-kernel'})
        self.template = qubes.vm.templatevm.TemplateVM(self.app, None,
            qid=1, name=qubes.tests.VMPREFIX + 'template')
        self.app.domains[self.template.name] = self.template
        self.app.domains[self.template] = self.template
        self.addCleanup(self.cleanup_appvm)

    def cleanup_appvm(self):
        self.template.close()
        del self.template
        self.app.domains.clear()
        self.app.pools.clear()

    def get_vm(self, **kwargs):
        vm = qubes.vm.appvm.AppVM(self.app, None,
            qid=2, name=qubes.tests.VMPREFIX + 'test',
            template=self.template,
            **kwargs)
        self.addCleanup(vm.close)
        return vm

    def test_000_init(self):
        self.get_vm()

    def test_001_storage_init(self):
        vm = self.get_vm()
        self.assertTrue(vm.volume_config['private']['save_on_stop'])
        self.assertFalse(vm.volume_config['private']['snap_on_start'])
        self.assertIsNone(vm.volume_config['private'].get('source', None))

        self.assertFalse(vm.volume_config['root']['save_on_stop'])
        self.assertTrue(vm.volume_config['root']['snap_on_start'])
        self.assertEqual(vm.volume_config['root'].get('source', None),
            self.template.volumes['root'])

        self.assertFalse(
            vm.volume_config['volatile'].get('save_on_stop', False))
        self.assertFalse(
            vm.volume_config['volatile'].get('snap_on_start', False))
        self.assertIsNone(vm.volume_config['volatile'].get('source', None))

    def test_002_storage_template_change(self):
        vm = self.get_vm()
        # create new mock, so new template will get different volumes
        self.app.pools['default'] = mock.Mock(**{
            'init_volume.return_value.pool': 'default'})
        template2 = qubes.vm.templatevm.TemplateVM(self.app, None,
            qid=3, name=qubes.tests.VMPREFIX + 'template2')
        self.app.domains[template2.name] = template2
        self.app.domains[template2] = template2

        vm.template = template2
        self.assertFalse(vm.volume_config['root']['save_on_stop'])
        self.assertTrue(vm.volume_config['root']['snap_on_start'])
        self.assertNotEqual(vm.volume_config['root'].get('source', None),
            self.template.volumes['root'].source)
        self.assertEqual(vm.volume_config['root'].get('source', None),
            template2.volumes['root'])

    def test_003_template_change_running(self):
        vm = self.get_vm()
        with mock.patch.object(vm, 'get_power_state') as mock_power:
            mock_power.return_value = 'Running'
            with self.assertRaises(qubes.exc.QubesVMNotHaltedError):
                vm.template = self.template

    def test_004_template_reset(self):
        vm = self.get_vm()
        with self.assertRaises(qubes.exc.QubesValueError):
            vm.template = qubes.property.DEFAULT

    def test_500_property_migrate_template_for_dispvms(self):
        xml_template = '''
        <domain class="AppVM" id="domain-1">
            <properties>
                <property name="qid">1</property>
                <property name="name">testvm</property>
                <property name="label" ref="label-1" />
                <property name="dispvm_allowed">{value}</property>
            </properties>
        </domain>
        '''
        xml = lxml.etree.XML(xml_template.format(value='True'))
        vm = qubes.vm.appvm.AppVM(self.app, xml)
        self.assertEqual(vm.template_for_dispvms, True)
        with self.assertRaises(AttributeError):
            vm.dispvm_allowed

        xml = lxml.etree.XML(xml_template.format(value='False'))
        vm = qubes.vm.appvm.AppVM(self.app, xml)
        self.assertEqual(vm.template_for_dispvms, False)
        with self.assertRaises(AttributeError):
            vm.dispvm_allowed
