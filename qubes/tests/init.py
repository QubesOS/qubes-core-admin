# pylint: disable=protected-access,pointless-statement

#
# The Qubes OS Project, https://www.qubes-os.org/
#
# Copyright (C) 2014-2015  Joanna Rutkowska <joanna@invisiblethingslab.com>
# Copyright (C) 2014-2015  Wojtek Porczyk <woju@invisiblethingslab.com>
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
#

import unittest
import uuid

import lxml.etree

import qubes
import qubes.app
import qubes.events
import qubes.vm

import qubes.tests

class TC_00_Label(qubes.tests.QubesTestCase):
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


class TC_10_property(qubes.tests.QubesTestCase):
    def setUp(self):
        super().setUp()
        try:
            class MyTestHolder(qubes.tests.TestEmitter, qubes.PropertyHolder):
                testprop1 = qubes.property('testprop1')
        except:  # pylint: disable=bare-except
            self.skipTest('MyTestHolder class definition failed')
        self.holder = MyTestHolder(None)

    def test_000_init(self):
        pass

    def test_001_hash(self):
        hash(self.holder.__class__.testprop1)

    def test_002_eq(self):
        self.assertEqual(qubes.property('testprop2'),
            qubes.property('testprop2'))

    def test_010_set(self):
        self.holder.testprop1 = 'testvalue'
        self.assertEventFired(self.holder, 'property-pre-set:testprop1',
            kwargs={'name': 'testprop1', 'newvalue': 'testvalue'})
        self.assertEventFired(self.holder, 'property-set:testprop1',
            kwargs={'name': 'testprop1', 'newvalue': 'testvalue'})

    def test_020_get(self):
        self.holder.testprop1 = 'testvalue'
        self.assertEqual(self.holder.testprop1, 'testvalue')

    def test_021_get_unset(self):
        with self.assertRaises(AttributeError):
            self.holder.testprop1

    def test_022_get_default(self):
        class MyTestHolder(qubes.tests.TestEmitter, qubes.PropertyHolder):
            testprop1 = qubes.property('testprop1', default='defaultvalue')
        holder = MyTestHolder(None)

        self.assertEqual(holder.testprop1, 'defaultvalue')
        self.assertEqual(
            type(holder).testprop1.get_default(holder),
            'defaultvalue')

    def test_023_get_default_func(self):
        class MyTestHolder(qubes.tests.TestEmitter, qubes.PropertyHolder):
            testprop1 = qubes.property('testprop1',
                default=(lambda self: 'defaultvalue'))
        holder = MyTestHolder(None)

        self.assertEqual(holder.testprop1, 'defaultvalue')
        holder.testprop1 = 'testvalue'
        self.assertEqual(holder.testprop1, 'testvalue')
        self.assertEventFired(holder, 'property-pre-set:testprop1',
            kwargs={'name': 'testprop1',
                'newvalue': 'testvalue',
                'oldvalue': 'defaultvalue'})
        self.assertEventFired(holder, 'property-set:testprop1',
            kwargs={'name': 'testprop1',
                'newvalue': 'testvalue',
                'oldvalue': 'defaultvalue'})

    def test_030_set_setter(self):
        def setter(self2, prop, value):
            self.assertIs(self2, holder)
            self.assertIs(prop, MyTestHolder.testprop1)
            self.assertEqual(value, 'testvalue')
            return 'settervalue'

        class MyTestHolder(qubes.tests.TestEmitter, qubes.PropertyHolder):
            testprop1 = qubes.property('testprop1', setter=setter)
        holder = MyTestHolder(None)

        holder.testprop1 = 'testvalue'
        self.assertEqual(holder.testprop1, 'settervalue')
        self.assertEventFired(holder, 'property-pre-set:testprop1',
            kwargs={'name': 'testprop1', 'newvalue': 'settervalue'})
        self.assertEventFired(holder, 'property-set:testprop1',
            kwargs={'name': 'testprop1', 'newvalue': 'settervalue'})

    def test_031_set_type(self):
        class MyTestHolder(qubes.tests.TestEmitter, qubes.PropertyHolder):
            testprop1 = qubes.property('testprop1', type=int)
        holder = MyTestHolder(None)

        holder.testprop1 = '5'
        self.assertEqual(holder.testprop1, 5)
        self.assertNotEqual(holder.testprop1, '5')
        self.assertEventFired(holder, 'property-pre-set:testprop1',
            kwargs={'name': 'testprop1', 'newvalue': 5})
        self.assertEventFired(holder, 'property-set:testprop1',
            kwargs={'name': 'testprop1', 'newvalue': 5})

    def test_080_delete(self):
        self.holder.testprop1 = 'testvalue'
        try:
            if self.holder.testprop1 != 'testvalue':
                self.skipTest('testprop1 value is wrong')
        except AttributeError:
            self.skipTest('testprop1 value is wrong')

        del self.holder.testprop1

        with self.assertRaises(AttributeError):
            self.holder.testprop1

        self.assertEventFired(self.holder, 'property-pre-del:testprop1',
            kwargs={'name': 'testprop1', 'oldvalue': 'testvalue'})
        self.assertEventFired(self.holder, 'property-pre-reset:testprop1',
            kwargs={'name': 'testprop1', 'oldvalue': 'testvalue'})
        self.assertEventFired(self.holder, 'property-del:testprop1',
            kwargs={'name': 'testprop1', 'oldvalue': 'testvalue'})
        self.assertEventFired(self.holder, 'property-reset:testprop1',
            kwargs={'name': 'testprop1', 'oldvalue': 'testvalue'})

    def test_081_delete_by_assign(self):
        self.holder.testprop1 = 'testvalue'
        try:
            if self.holder.testprop1 != 'testvalue':
                self.skipTest('testprop1 value is wrong')
        except AttributeError:
            self.skipTest('testprop1 value is wrong')

        self.holder.testprop1 = qubes.property.DEFAULT

        with self.assertRaises(AttributeError):
            self.holder.testprop1

    def test_082_delete_default(self):
        class MyTestHolder(qubes.tests.TestEmitter, qubes.PropertyHolder):
            testprop1 = qubes.property('testprop1', default='defaultvalue')
        holder = MyTestHolder(None)
        holder.testprop1 = 'testvalue'

        try:
            if holder.testprop1 != 'testvalue':
                self.skipTest('testprop1 value is wrong')
        except AttributeError:
            self.skipTest('testprop1 value is wrong')

        del holder.testprop1

        self.assertEqual(holder.testprop1, 'defaultvalue')
        self.assertEventFired(holder, 'property-pre-del:testprop1', kwargs={
            'name': 'testprop1', 'oldvalue': 'testvalue'})
        self.assertEventFired(holder, 'property-pre-reset:testprop1', kwargs={
            'name': 'testprop1', 'oldvalue': 'testvalue'})
        self.assertEventFired(holder, 'property-del:testprop1', kwargs={
            'name': 'testprop1', 'oldvalue': 'testvalue'})
        self.assertEventFired(holder, 'property-reset:testprop1', kwargs={
            'name': 'testprop1', 'oldvalue': 'testvalue'})

    def test_090_write_once_set(self):
        class MyTestHolder(qubes.tests.TestEmitter, qubes.PropertyHolder):
            testprop1 = qubes.property('testprop1', write_once=True)
        holder = MyTestHolder(None)

        holder.testprop1 = 'testvalue'

        with self.assertRaises(AttributeError):
            holder.testprop1 = 'testvalue2'

    def test_091_write_once_delete(self):
        class MyTestHolder(qubes.tests.TestEmitter, qubes.PropertyHolder):
            testprop1 = qubes.property('testprop1', write_once=True)
        holder = MyTestHolder(None)

        holder.testprop1 = 'testvalue'

        with self.assertRaises(AttributeError):
            del holder.testprop1


class TestHolder(qubes.tests.TestEmitter, qubes.PropertyHolder):
    testprop1 = qubes.property('testprop1', order=0)
    testprop2 = qubes.property('testprop2', order=1, save_via_ref=True)
    testprop3 = qubes.property('testprop3', order=2, default='testdefault')
    testprop4 = qubes.property('testprop4', order=3)


class TC_20_PropertyHolder(qubes.tests.QubesTestCase):
    def setUp(self):
        super().setUp()
        xml = lxml.etree.XML('''
<qubes version="3">
    <properties>
        <property name="testprop1">testvalue1</property>
        <property name="testprop2" ref="testref2" />
    </properties>
</qubes>
        ''')

        self.holder = TestHolder(xml)

    def test_000_property_list(self):
        self.assertListEqual([p.__name__ for p in self.holder.property_list()],
            ['testprop1', 'testprop2', 'testprop3', 'testprop4'])

    def test_001_property_get_def(self):
        self.assertIs(
            self.holder.property_get_def('testprop1'), TestHolder.testprop1)
        self.assertIs(self.holder.property_get_def(TestHolder.testprop1),
            TestHolder.testprop1)

    def test_002_load_properties(self):
        self.holder.load_properties()

        self.assertEventFired(self.holder, 'property-set:testprop1')

        self.assertEqual(self.holder.testprop1, 'testvalue1')
        self.assertEqual(self.holder.testprop2, 'testref2')
        self.assertEqual(self.holder.testprop3, 'testdefault')

        with self.assertRaises(AttributeError):
            self.holder.testprop4

    def test_003_property_is_default(self):
        self.holder.load_properties()
        self.assertFalse(self.holder.property_is_default('testprop1'))
        self.assertFalse(self.holder.property_is_default('testprop2'))
        self.assertTrue(self.holder.property_is_default('testprop3'))
        self.assertTrue(self.holder.property_is_default('testprop4'))
        with self.assertRaises(AttributeError):
            self.holder.property_is_default('testprop5')

    @unittest.skip('test not implemented')
    def test_004_property_init(self):
        pass

    @unittest.skip('test not implemented')
    def test_005_clone_properties(self):
        pass

    def test_006_xml_properties(self):
        self.holder.load_properties()

        elements = self.holder.xml_properties()
        elements_with_defaults = self.holder.xml_properties(with_defaults=True)

        self.assertEqual(len(elements), 2)
        self.assertEqual(len(elements_with_defaults), 3)

        expected_prop1 = lxml.etree.Element('property', name='testprop1')
        expected_prop1.text = 'testvalue1'
        self.assertXMLEqual(elements_with_defaults[0], expected_prop1)

        expected_prop2 = lxml.etree.Element('property',
            name='testprop2', ref='testref2')
        self.assertXMLEqual(elements_with_defaults[1], expected_prop2)

        expected_prop3 = lxml.etree.Element('property', name='testprop3')
        expected_prop3.text = 'testdefault'
        self.assertXMLEqual(elements_with_defaults[2], expected_prop3)

    def test_007_property_get_default(self):
        self.assertEqual(
            self.holder.property_get_default('testprop3'),
            'testdefault')
        with self.assertRaises(AttributeError):
            self.holder.property_get_default('testprop1'),

    @unittest.skip('test not implemented')
    def test_010_property_require(self):
        pass


class TestVM(qubes.vm.BaseVM):
    qid = qubes.property('qid', type=int)
    name = qubes.property('name')
    uuid = uuid.uuid5(uuid.NAMESPACE_DNS, 'testvm')

    def __lt__(self, other):
        try:
            return self.name < other.name
        except AttributeError:
            return NotImplemented

    class MockLibvirt(object):
        def undefine(self):
            pass

    libvirt_domain = MockLibvirt()

    def is_halted(self):
        return True

    def get_power_state(self):
        return "Halted"

    def libvirt_undefine(self):
        pass


class TestApp(qubes.tests.TestEmitter):
    pass

class TC_30_VMCollection(qubes.tests.QubesTestCase):
    def setUp(self):
        super().setUp()
        self.app = TestApp()
        self.vms = qubes.app.VMCollection(self.app)

        self.testvm1 = TestVM(None, None, qid=1, name='testvm1')
        self.testvm2 = TestVM(None, None, qid=2, name='testvm2')
        self.addCleanup(self.cleanup_testvm)

    def cleanup_testvm(self):
        self.vms.close()
        self.testvm1.close()
        self.testvm2.close()
        del self.testvm1
        del self.testvm2
        del self.vms
        del self.app

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

        self.assertEventFired(self.app, 'domain-add',
            kwargs={'vm': self.testvm1})

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

        self.assertCountEqual(self.vms.qids(), [1, 2])
        self.assertCountEqual(self.vms.keys(), [1, 2])

    def test_004_names(self):
        self.vms.add(self.testvm1)
        self.vms.add(self.testvm2)

        self.assertCountEqual(self.vms.names(), ['testvm1', 'testvm2'])

    def test_005_vms(self):
        self.vms.add(self.testvm1)
        self.vms.add(self.testvm2)

        self.assertCountEqual(self.vms.vms(), [self.testvm1, self.testvm2])
        self.assertCountEqual(self.vms.values(), [self.testvm1, self.testvm2])

    def test_006_items(self):
        self.vms.add(self.testvm1)
        self.vms.add(self.testvm2)

        self.assertCountEqual(self.vms.items(),
            [(1, self.testvm1), (2, self.testvm2)])

    def test_007_len(self):
        self.vms.add(self.testvm1)
        self.vms.add(self.testvm2)

        self.assertEqual(len(self.vms), 2)

    def test_008_delitem(self):
        self.vms.add(self.testvm1)
        self.vms.add(self.testvm2)

        del self.vms['testvm2']

        self.assertCountEqual(self.vms.vms(), [self.testvm1])
        self.assertEventFired(self.app, 'domain-delete',
            kwargs={'vm': self.testvm2})

    def test_100_get_new_unused_qid(self):
        self.vms.add(self.testvm1)
        self.vms.add(self.testvm2)

        self.vms.get_new_unused_qid()

#   def test_200_get_vms_based_on(self):
#       pass

#   def test_201_get_vms_connected_to(self):
#       pass
