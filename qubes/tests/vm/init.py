#!/usr/bin/python2 -O

import sys
import unittest

import lxml.etree

import qubes
import qubes.events
import qubes.vm

import qubes.tests


class TestEmitter(qubes.events.Emitter):
    def __init__(self):
        super(TestEmitter, self).__init__()
        self.device_pre_attached_fired = False
        self.device_attached_fired = False
        self.device_pre_detached_fired = False
        self.device_detached_fired = False

    @qubes.events.handler('device-pre-attached:testclass')
    def on_device_pre_attached(self, event, dev):
        self.device_pre_attached_fired = True

    @qubes.events.handler('device-attached:testclass')
    def on_device_attached(self, event, dev):
        if self.device_pre_attached_fired:
            self.device_attached_fired = True

    @qubes.events.handler('device-pre-detached:testclass')
    def on_device_pre_detached(self, event, dev):
        if self.device_attached_fired:
            self.device_pre_detached_fired = True

    @qubes.events.handler('device-detached:testclass')
    def on_device_detached(self, event, dev):
        if self.device_pre_detached_fired:
            self.device_detached_fired = True

class TC_00_DeviceCollection(qubes.tests.QubesTestCase):
    def setUp(self):
        self.emitter = TestEmitter()
        self.collection = qubes.vm.DeviceCollection(self.emitter, 'testclass')

    def test_000_init(self):
        self.assertFalse(self.collection._set)

    def test_001_attach(self):
        self.collection.attach('testdev')
        self.assertTrue(self.emitter.device_pre_attached_fired)
        self.assertTrue(self.emitter.device_attached_fired)
        self.assertFalse(self.emitter.device_pre_detached_fired)
        self.assertFalse(self.emitter.device_detached_fired)

    def test_002_detach(self):
        self.collection.attach('testdev')
        self.collection.detach('testdev')
        self.assertTrue(self.emitter.device_pre_attached_fired)
        self.assertTrue(self.emitter.device_attached_fired)
        self.assertTrue(self.emitter.device_pre_detached_fired)
        self.assertTrue(self.emitter.device_detached_fired)

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
        self.emitter = TestEmitter()
        self.manager = qubes.vm.DeviceManager(self.emitter)

    def test_000_init(self):
        self.assertEqual(self.manager, {})

    def test_001_missing(self):
        self.manager['testclass'].attach('testdev')
        self.assertTrue(self.emitter.device_attached_fired)


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

            <services>
                <service>testservice</service>
                <service enabled="True">enabledservice</service>
                <service enabled="False">disabledservice</service>
            </services>

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

    def test_000_BaseVM_load(self):
        node = self.xml.xpath('//domain')[0]
        vm = TestVM.fromxml(None, node)

        self.assertEqual(vm.qid, 1)
        self.assertEqual(vm.testprop, 'testvalue')
        self.assertEqual(vm.testprop, 'testvalue')
        self.assertEqual(vm.testlabel, 'label-1')
        self.assertEqual(vm.defaultprop, 'defaultvalue')
        self.assertEqual(vm.tags, {'testtag': 'tagvalue'})
        self.assertEqual(vm.devices, {'pci': ['00:11.22']})
        self.assertEqual(vm.services, {
            'testservice': True,
            'enabledservice': True,
            'disabledservice': False,
        })

        lxml.etree.ElementTree(vm.__xml__()).write(sys.stderr, encoding='utf-8', pretty_print=True)

    def test_001_BaseVM_nxproperty(self):
        xml = lxml.etree.XML('''
<qubes version="3">
    <domains>
        <domain id="domain-1" class="TestVM">
            <properties>
                <property name="nxproperty">nxvalue</property>
            </properties>
        </domain>
    </domains>
</qubes>
        ''')

        node = xml.xpath('//domain')[0]

        with self.assertRaises(AttributeError):
            TestVM.fromxml(None, node)
