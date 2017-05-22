# pylint: disable=protected-access

#
# The Qubes OS Project, https://www.qubes-os.org/
#
# Copyright (C) 2014-2015  Joanna Rutkowska <joanna@invisiblethingslab.com>
# Copyright (C) 2014-2015  Wojtek Porczyk <woju@invisiblethingslab.com>
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
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
#

import lxml.etree

import qubes
import qubes.events
import qubes.vm

import qubes.tests

class TestVMM(object):
    def __init__(self):
        super(TestVMM, self).__init__()
        self.offline_mode = True


class TestApp(object):
    def __init__(self):
        super(TestApp, self).__init__()
        self.domains = {}
        self.vmm = TestVMM()


class TestVM(qubes.vm.BaseVM):
    qid = qubes.property('qid', type=int)
    name = qubes.property('name')
    testprop = qubes.property('testprop')
    testlabel = qubes.property('testlabel')
    defaultprop = qubes.property('defaultprop', default='defaultvalue')

class TC_10_BaseVM(qubes.tests.QubesTestCase):
    def setUp(self):
        self.xml = lxml.etree.XML('''
<qubes version="3"> <!-- xmlns="https://qubes-os.org/QubesXML/1" -->
    <labels>
        <label id="label-1" color="#cc0000">red</label>
    </labels>

    <domains>
        <domain id="domain-1" class="TestVM">
            <properties>
                <property name="qid">1</property>
                <property name="name">domain1</property>
                <property name="testprop">testvalue</property>
                <property name="testlabel" ref="label-1" />
            </properties>

            <tags>
                <tag name="testtag"/>
            </tags>

            <features>
                <feature name="testfeature_empty"></feature>
                <feature name="testfeature_aqq">aqq</feature>
            </features>

            <devices class="pci">
                <device backend-domain="domain1" id="00_11.22">
                  <option name="no-strict-reset">True</option>
                </device>
            </devices>

            <devices class="usb" />
            <devices class="audio-in" />
            <devices class="firewire" />
            <devices class="i2c" />
            <devices class="isa" />
        </domain>
    </domains>
</qubes>
        ''')

    def test_000_load(self):
        node = self.xml.xpath('//domain')[0]
        vm = TestVM(TestApp(), node)
        vm.app.domains['domain1'] = vm
        vm.load_properties(load_stage=None)
        vm.load_extras()

        self.assertEqual(vm.qid, 1)
        self.assertEqual(vm.testprop, 'testvalue')
        self.assertEqual(vm.testprop, 'testvalue')
        self.assertEqual(vm.testlabel, 'label-1')
        self.assertEqual(vm.defaultprop, 'defaultvalue')
        self.assertEqual(vm.tags, {'testtag'})
        self.assertEqual(vm.features, {
            'testfeature_empty': '',
            'testfeature_aqq': 'aqq',
        })

        self.assertCountEqual(vm.devices.keys(), ('pci',))
        self.assertCountEqual(list(vm.devices['pci'].persistent()),
            [qubes.ext.pci.PCIDevice(vm, '00_11.22')])

        assignments = list(vm.devices['pci'].assignments())
        self.assertEqual(len(assignments), 1)
        self.assertEqual(assignments[0].options, {'no-strict-reset': 'True'})
        self.assertEqual(assignments[0].persistent, True)

        self.assertXMLIsValid(vm.__xml__(), 'domain.rng')

    def test_001_nxproperty(self):
        xml = lxml.etree.XML('''
<qubes version="3">
    <domains>
        <domain id="domain-1" class="TestVM">
            <properties>
                <property name="qid">1</property>
                <property name="name">domain1</property>
                <property name="nxproperty">nxvalue</property>
            </properties>
        </domain>
    </domains>
</qubes>
        ''')

        node = xml.xpath('//domain')[0]

        with self.assertRaises(TypeError):
            TestVM(None, node)

    def test_002_save_nxproperty(self):
        vm = TestVM(None, None, qid=1, name='testvm')
        vm.nxproperty = 'value'
        xml = vm.__xml__()
        self.assertNotIn('nxproperty', xml)


class TC_20_Tags(qubes.tests.QubesTestCase):
    def setUp(self):
        super(TC_20_Tags, self).setUp()
        self.vm = qubes.tests.TestEmitter()
        self.tags = qubes.vm.Tags(self.vm)

    def test_000_add(self):
        self.tags.add('testtag')
        self.assertEventFired(self.vm, 'domain-tag-add',
            kwargs={'tag': 'testtag'})

    def test_001_add_existing(self):
        self.tags.add('testtag')
        self.vm.fired_events.clear()
        self.tags.add('testtag')
        self.assertEventNotFired(self.vm, 'domain-tag-add')

    def test_002_remove(self):
        self.tags.add('testtag')
        self.vm.fired_events.clear()
        self.tags.remove('testtag')
        self.assertEventFired(self.vm, 'domain-tag-delete',
            kwargs={'tag': 'testtag'})

    def test_003_remove_not_present(self):
        with self.assertRaises(KeyError):
            self.tags.remove('testtag')
        self.assertEventNotFired(self.vm, 'domain-tag-delete')

    def test_004_discard_not_present(self):
        with self.assertNotRaises(KeyError):
            self.tags.discard('testtag')
        self.assertEventNotFired(self.vm, 'domain-tag-delete')

    def test_005_discard_present(self):
        self.tags.add('testtag')
        with self.assertNotRaises(KeyError):
            self.tags.discard('testtag')
        self.assertEventFired(self.vm, 'domain-tag-delete',
            kwargs={'tag': 'testtag'})

    def test_006_clear(self):
        self.tags.add('testtag')
        self.tags.add('testtag2')
        self.vm.fired_events.clear()
        self.tags.clear()
        self.assertEventFired(self.vm, 'domain-tag-delete',
            kwargs={'tag': 'testtag'})
        self.assertEventFired(self.vm, 'domain-tag-delete',
            kwargs={'tag': 'testtag2'})

    def test_007_update(self):
        self.tags.add('testtag')
        self.tags.add('testtag2')
        self.vm.fired_events.clear()
        self.tags.update(('testtag2', 'testtag3'))
        self.assertEventFired(self.vm, 'domain-tag-add',
            kwargs={'tag': 'testtag3'})
        self.assertEventNotFired(self.vm, 'domain-tag-add',
            kwargs={'tag': 'testtag2'})


class TC_21_Features(qubes.tests.QubesTestCase):
    def setUp(self):
        super(TC_21_Features, self).setUp()
        self.vm = qubes.tests.TestEmitter()
        self.features = qubes.vm.Features(self.vm)

    def test_000_set(self):
        self.features['testfeature'] = 'value'
        self.assertEventFired(self.vm, 'domain-feature-set',
            kwargs={'key': 'testfeature', 'value': 'value'})

    def test_001_set_existing(self):
        self.features['test'] = 'value'
        self.vm.fired_events.clear()
        self.features['test'] = 'value'
        self.assertEventFired(self.vm, 'domain-feature-set',
            kwargs={'key': 'test', 'value': 'value'})

    def test_002_unset(self):
        self.features['test'] = 'value'
        self.vm.fired_events.clear()
        del self.features['test']
        self.assertEventFired(self.vm, 'domain-feature-delete',
            kwargs={'key': 'test'})

    def test_003_unset_not_present(self):
        with self.assertRaises(KeyError):
            del self.features['test']
        self.assertEventNotFired(self.vm, 'domain-feature-delete')

    def test_004_set_bool_true(self):
        self.features['test'] = True
        self.assertTrue(self.features['test'])
        self.assertEventFired(self.vm, 'domain-feature-set',
            kwargs={'key': 'test', 'value': '1'})

    def test_005_set_bool_false(self):
        self.features['test'] = False
        self.assertFalse(self.features['test'])
        self.assertEventFired(self.vm, 'domain-feature-set',
            kwargs={'key': 'test', 'value': ''})

    def test_006_set_int(self):
        self.features['test'] = 123
        self.assertEventFired(self.vm, 'domain-feature-set',
            kwargs={'key': 'test', 'value': '123'})

    def test_007_clear(self):
        self.features['test'] = 'value1'
        self.features['test2'] = 'value2'
        self.vm.fired_events.clear()
        self.features.clear()
        self.assertEventFired(self.vm, 'domain-feature-delete',
            kwargs={'key': 'test'})
        self.assertEventFired(self.vm, 'domain-feature-delete',
            kwargs={'key': 'test2'})

    def test_008_update(self):
        self.features['test'] = 'value'
        self.features['test2'] = 'value2'
        self.vm.fired_events.clear()
        self.features.update({'test2': 'value3', 'test3': 'value4'})
        self.assertEqual(self.features['test2'], 'value3')
        self.assertEqual(self.features['test3'], 'value4')
        self.assertEqual(self.features['test'], 'value')
        self.assertEventFired(self.vm, 'domain-feature-set',
            kwargs={'key': 'test2', 'value': 'value3'})
        self.assertEventFired(self.vm, 'domain-feature-set',
            kwargs={'key': 'test3', 'value': 'value4'})
