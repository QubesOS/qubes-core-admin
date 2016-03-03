#!/usr/bin/python2 -O
# vim: fileencoding=utf-8
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


class TC_00_DeviceCollection(qubes.tests.QubesTestCase):
    def setUp(self):
        self.emitter = qubes.tests.TestEmitter()
        self.collection = qubes.vm.DeviceCollection(self.emitter, 'testclass')

    def test_000_init(self):
        self.assertFalse(self.collection._set)

    def test_001_attach(self):
        self.collection.attach('testdev')
        self.assertEventFired(self.emitter, 'device-pre-attached:testclass')
        self.assertEventFired(self.emitter, 'device-attached:testclass')
        self.assertEventNotFired(self.emitter, 'device-pre-detached:testclass')
        self.assertEventNotFired(self.emitter, 'device-detached:testclass')

    def test_002_detach(self):
        self.collection.attach('testdev')
        self.collection.detach('testdev')
        self.assertEventFired(self.emitter, 'device-pre-attached:testclass')
        self.assertEventFired(self.emitter, 'device-attached:testclass')
        self.assertEventFired(self.emitter, 'device-pre-detached:testclass')
        self.assertEventFired(self.emitter, 'device-detached:testclass')

    def test_010_empty_detach(self):
        with self.assertRaises(LookupError):
            self.collection.detach('testdev')

    def test_011_double_attach(self):
        self.collection.attach('testdev')

        with self.assertRaises(LookupError):
            self.collection.attach('testdev')

    def test_012_double_detach(self):
        self.collection.attach('testdev')
        self.collection.detach('testdev')

        with self.assertRaises(LookupError):
            self.collection.detach('testdev')


class TC_01_DeviceManager(qubes.tests.QubesTestCase):
    def setUp(self):
        self.emitter = qubes.tests.TestEmitter()
        self.manager = qubes.vm.DeviceManager(self.emitter)

    def test_000_init(self):
        self.assertEqual(self.manager, {})

    def test_001_missing(self):
        self.manager['testclass'].attach('testdev')
        self.assertEventFired(self.emitter, 'device-attached:testclass')


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
                <tag name="testtag">tagvalue</tag>
            </tags>

            <features>
                <feature name="testfeature_none"/>
                <feature name="testfeature_empty"></feature>
                <feature name="testfeature_aqq">aqq</feature>
            </features>

            <devices class="pci">
                <device>00:11.22</device>
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
        vm = TestVM(None, node)
        vm.load_properties(load_stage=None)

        self.assertEqual(vm.qid, 1)
        self.assertEqual(vm.testprop, 'testvalue')
        self.assertEqual(vm.testprop, 'testvalue')
        self.assertEqual(vm.testlabel, 'label-1')
        self.assertEqual(vm.defaultprop, 'defaultvalue')
        self.assertEqual(vm.tags, {'testtag': 'tagvalue'})
        self.assertEqual(vm.features, {
            'testfeature_none': None,
            'testfeature_empty': '',
            'testfeature_aqq': 'aqq',
        })

        self.assertItemsEqual(vm.devices.keys(), ('pci',))
        self.assertItemsEqual(vm.devices['pci'], ('00:11.22',))

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
