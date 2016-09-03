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
                <tag name="testtag">tagvalue</tag>
            </tags>

            <features>
                <feature name="testfeature_empty"></feature>
                <feature name="testfeature_aqq">aqq</feature>
            </features>

            <devices class="pci">
                <device backend-domain="domain1" id="00:11.22"/>
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
        self.assertEqual(vm.tags, {'testtag': 'tagvalue'})
        self.assertEqual(vm.features, {
            'testfeature_empty': '',
            'testfeature_aqq': 'aqq',
        })

        self.assertItemsEqual(vm.devices.keys(), ('pci',))
        self.assertItemsEqual(list(vm.devices['pci'].attached(persistent=True)),
            [qubes.ext.pci.PCIDevice(vm, '00:11.22')])

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
