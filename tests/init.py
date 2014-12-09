#!/usr/bin/python2 -O

import sys
import unittest

import lxml.etree

sys.path.insert(0, '../')
import qubes
import qubes.vm

class TC_10_Label(unittest.TestCase):
    def test_000_constructor(self):
        label = qubes.Label(1, '#cc0000', 'red')

        self.assertEqual(label.index, 1)
        self.assertEqual(label.color, '#cc0000')
        self.assertEqual(label.name, 'red')
        self.assertEqual(label.icon, 'appvm-red')
        self.assertEqual(label.icon_dispvm, 'dispvm-red')

    def test_001_fromxml(self):
        xml = lxml.etree.XML('''
<qubes version="3">
    <labels>
        <label id="label-1" color="#cc0000">red</label>
    </labels>
</qubes>
        ''')

        node = xml.xpath('//label')[0]
        label = qubes.Label.fromxml(node)

        self.assertEqual(label.index, 1)
        self.assertEqual(label.color, '#cc0000')
        self.assertEqual(label.name, 'red')
        self.assertEqual(label.icon, 'appvm-red')
        self.assertEqual(label.icon_dispvm, 'dispvm-red')


class TestHolder(qubes.PropertyHolder):
    testprop1 = qubes.property('testprop1', order=0)
    testprop2 = qubes.property('testprop2', order=1, save_via_ref=True)
    testprop3 = qubes.property('testprop3', order=2, default='testdefault')
    testprop4 = qubes.property('testprop4', order=3)

class TC_00_PropertyHolder(unittest.TestCase):
    def assertXMLEqual(self, xml1, xml2):
        self.assertEqual(xml1.tag, xml2.tag)
        self.assertEqual(xml1.text, xml2.text)
        self.assertEqual(sorted(xml1.keys()), sorted(xml2.keys()))
        for key in xml1.keys():
            self.assertEqual(xml1.get(key), xml2.get(key))

    def setUp(self):
        xml = lxml.etree.XML('''
<qubes version="3">
    <properties>
        <property name="testprop1">testvalue1</property>
        <property name="testprop2" ref="testref2" />
    </properties>
</qubes>
        ''')

        self.holder = TestHolder(xml)

    def test_000_load_properties(self):
        self.holder.load_properties()
        self.assertEquals(self.holder.testprop1, 'testvalue1')
        self.assertEquals(self.holder.testprop2, 'testref2')
        self.assertEquals(self.holder.testprop3, 'testdefault')

        with self.assertRaises(AttributeError):
            self.holder.testprop4

    def test_001_save_properties(self):
        self.holder.load_properties()

        elements = self.holder.save_properties()
        elements_with_defaults = self.holder.save_properties(with_defaults=True)

        self.assertEqual(len(elements), 2)
        self.assertEqual(len(elements_with_defaults), 3)

        expected_prop1 = lxml.etree.Element('property', name='testprop1')
        expected_prop1.text = 'testvalue1'
        self.assertXMLEqual(elements_with_defaults[0], expected_prop1)

        expected_prop2 = lxml.etree.Element('property', name='testprop2', ref='testref2')
        self.assertXMLEqual(elements_with_defaults[1], expected_prop2)

        expected_prop3 = lxml.etree.Element('property', name='testprop3')
        expected_prop3.text = 'testdefault'
        self.assertXMLEqual(elements_with_defaults[2], expected_prop3)


class TestVM(qubes.vm.BaseVM):
    qid = qubes.property('qid', type=int)
    name = qubes.property('name')
    netid = qid

class TC_11_VMCollection(unittest.TestCase):
    def setUp(self):
        # XXX passing None may be wrong in the future
        self.vms = qubes.VMCollection(None)

        self.testvm1 = TestVM(None, None, qid=1, name='testvm1')
        self.testvm2 = TestVM(None, None, qid=2, name='testvm2')

    def test_000_contains(self):
        self.vms._dict = {1: self.testvm1}

        self.assertIn(1, self.vms)
        self.assertIn('testvm1', self.vms)
        self.assertIn(self.testvm1, self.vms)

        self.assertNotIn(2, self.vms)
        self.assertNotIn('testvm2', self.vms)
        self.assertNotIn(self.testvm2, self.vms)

    def test_001_getitem(self):
        self.vms._dict = {1: self.testvm1}

        self.assertIs(self.vms[1], self.testvm1)
        self.assertIs(self.vms['testvm1'], self.testvm1)
        self.assertIs(self.vms[self.testvm1], self.testvm1)

    def test_002_add(self):
        self.vms.add(self.testvm1)
        self.assertIn(1, self.vms)

        with self.assertRaises(TypeError):
            self.vms.add(object())

        testvm_qid_collision = TestVM(None, None, name='testvm2', qid=1)
        testvm_name_collision = TestVM(None, None, name='testvm1', qid=2)

        with self.assertRaises(ValueError):
            self.vms.add(testvm_qid_collision)
        with self.assertRaises(ValueError):
            self.vms.add(testvm_name_collision)

    def test_003_qids(self):
        self.vms.add(self.testvm1)
        self.vms.add(self.testvm2)

        self.assertItemsEqual(self.vms.qids(), [1, 2])
        self.assertItemsEqual(self.vms.keys(), [1, 2])

    def test_004_names(self):
        self.vms.add(self.testvm1)
        self.vms.add(self.testvm2)

        self.assertItemsEqual(self.vms.names(), ['testvm1', 'testvm2'])

    def test_005_vms(self):
        self.vms.add(self.testvm1)
        self.vms.add(self.testvm2)

        self.assertItemsEqual(self.vms.vms(), [self.testvm1, self.testvm2])
        self.assertItemsEqual(self.vms.values(), [self.testvm1, self.testvm2])

    def test_006_items(self):
        self.vms.add(self.testvm1)
        self.vms.add(self.testvm2)

        self.assertItemsEqual(self.vms.items(), [(1, self.testvm1), (2, self.testvm2)])

    def test_007_len(self):
        self.vms.add(self.testvm1)
        self.vms.add(self.testvm2)

        self.assertEqual(len(self.vms), 2)

    def test_008_delitem(self):
        self.vms.add(self.testvm1)
        self.vms.add(self.testvm2)

        del self.vms['testvm2']

        self.assertItemsEqual(self.vms.vms(), [self.testvm1])

    def test_100_get_new_unused_qid(self):
        self.vms.add(self.testvm1)
        self.vms.add(self.testvm2)

        self.vms.get_new_unused_qid()

    def test_101_get_new_unused_netid(self):
        self.vms.add(self.testvm1)
        self.vms.add(self.testvm2)

        self.vms.get_new_unused_netid()

#   def test_200_get_vms_based_on(self):
#       pass

#   def test_201_get_vms_connected_to(self):
#       pass


class TC_20_Qubes(unittest.TestCase):
    pass
