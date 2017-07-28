# pylint: disable=protected-access,pointless-statement

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

import os
import uuid

import lxml.etree

import qubes
import qubes.events

import qubes.tests
import qubes.tests.init

class TestApp(qubes.tests.TestEmitter):
    pass

class TC_30_VMCollection(qubes.tests.QubesTestCase):
    def setUp(self):
        super().setUp()
        self.app = TestApp()
        self.vms = qubes.app.VMCollection(self.app)

        self.testvm1 = qubes.tests.init.TestVM(
            None, None, qid=1, name='testvm1')
        self.testvm2 = qubes.tests.init.TestVM(
            None, None, qid=2, name='testvm2')

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

        testvm_qid_collision = qubes.tests.init.TestVM(
            None, None, name='testvm2', qid=1)
        testvm_name_collision = qubes.tests.init.TestVM(
            None, None, name='testvm1', qid=2)

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

    def test_101_get_new_unused_netid(self):
        self.vms.add(self.testvm1)
        self.vms.add(self.testvm2)

        self.vms.get_new_unused_netid()

#   def test_200_get_vms_based_on(self):
#       pass

#   def test_201_get_vms_connected_to(self):
#       pass


class TC_90_Qubes(qubes.tests.QubesTestCase):
    def tearDown(self):
        try:
            os.unlink('/tmp/qubestest.xml')
        except:
            pass
        super(TC_90_Qubes, self).tearDown()

    @qubes.tests.skipUnlessDom0
    def test_000_init_empty(self):
        # pylint: disable=no-self-use,unused-variable,bare-except
        try:
            os.unlink('/tmp/qubestest.xml')
        except FileNotFoundError:
            pass
        qubes.Qubes.create_empty_store('/tmp/qubestest.xml')

    def test_100_clockvm(self):
        app = qubes.Qubes('/tmp/qubestest.xml', load=False, offline_mode=True)
        app.load_initial_values()

        template = app.add_new_vm('TemplateVM', name='test-template',
            label='green')
        appvm = app.add_new_vm('AppVM', name='test-vm', template=template,
            label='red')
        self.assertIsNone(app.clockvm)
        self.assertNotIn('service.clocksync', appvm.features)
        self.assertNotIn('service.clocksync', template.features)
        app.clockvm = appvm
        self.assertIn('service.clocksync', appvm.features)
        self.assertTrue(appvm.features['service.clocksync'])
        app.clockvm = template
        self.assertNotIn('service.clocksync', appvm.features)
        self.assertIn('service.clocksync', template.features)
        self.assertTrue(template.features['service.clocksync'])

    @qubes.tests.skipUnlessGit
    def test_900_example_xml_in_doc(self):
        self.assertXMLIsValid(
            lxml.etree.parse(open(
                os.path.join(qubes.tests.in_git, 'doc/example.xml'), 'rb')),
            'qubes.rng')
