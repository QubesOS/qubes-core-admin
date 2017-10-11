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

import os
import unittest.mock as mock

import lxml.etree

import qubes
import qubes.events

import qubes.tests
import qubes.tests.init

class TestApp(qubes.tests.TestEmitter):
    pass


class TC_20_QubesHost(qubes.tests.QubesTestCase):
    sample_xc_domain_getinfo = [
        {'paused': 0, 'cpu_time': 243951379111104, 'ssidref': 0,
            'hvm': 0, 'shutdown_reason': 255, 'dying': 0,
            'mem_kb': 3733212, 'domid': 0, 'max_vcpu_id': 7,
            'crashed': 0, 'running': 1, 'maxmem_kb': 3734236,
            'shutdown': 0, 'online_vcpus': 8,
            'handle': [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
            'cpupool': 0, 'blocked': 0},
        {'paused': 0, 'cpu_time': 2849496569205, 'ssidref': 0,
            'hvm': 0, 'shutdown_reason': 255, 'dying': 0,
            'mem_kb': 303916, 'domid': 1, 'max_vcpu_id': 0,
            'crashed': 0, 'running': 0, 'maxmem_kb': 308224,
            'shutdown': 0, 'online_vcpus': 1,
            'handle': [116, 174, 229, 207, 17, 1, 79, 39, 191, 37, 41,
                186, 205, 158, 219, 8],
            'cpupool': 0, 'blocked': 1},
        {'paused': 0, 'cpu_time': 249658663079978, 'ssidref': 0,
            'hvm': 0, 'shutdown_reason': 255, 'dying': 0,
            'mem_kb': 3782668, 'domid': 11, 'max_vcpu_id': 7,
            'crashed': 0, 'running': 0, 'maxmem_kb': 3783692,
            'shutdown': 0, 'online_vcpus': 8,
            'handle': [169, 95, 55, 127, 140, 94, 79, 220, 186, 210,
                117, 5, 148, 11, 185, 206],
            'cpupool': 0, 'blocked': 1}]

    def setUp(self):
        super(TC_20_QubesHost, self).setUp()
        self.app = TestApp()
        self.app.vmm = mock.Mock()
        self.qubes_host = qubes.app.QubesHost(self.app)

    def test_000_get_vm_stats_single(self):
        self.app.vmm.configure_mock(**{
            'xc.domain_getinfo.return_value': self.sample_xc_domain_getinfo
        })

        info_time, info = self.qubes_host.get_vm_stats()
        self.assertEqual(self.app.vmm.mock_calls, [
            ('xc.domain_getinfo', (0, 1024), {}),
        ])
        self.assertIsNotNone(info_time)
        expected_info = {
            0: {
                'cpu_time': 243951379111104//8,
                'cpu_usage': 0,
                'memory_kb': 3733212,
            },
            1: {
                'cpu_time': 2849496569205,
                'cpu_usage': 0,
                'memory_kb': 303916,
            },
            11: {
                'cpu_time': 249658663079978//8,
                'cpu_usage': 0,
                'memory_kb': 3782668,
            },
        }
        self.assertEqual(info, expected_info)

    def test_001_get_vm_stats_twice(self):
        self.app.vmm.configure_mock(**{
            'xc.domain_getinfo.return_value': self.sample_xc_domain_getinfo
        })

        prev_time, prev_info = self.qubes_host.get_vm_stats()
        prev_time -= 1
        prev_info[0]['cpu_time'] -= 10**8
        prev_info[1]['cpu_time'] -= 10**9
        prev_info[11]['cpu_time'] -= 125 * 10**6
        info_time, info = self.qubes_host.get_vm_stats(prev_time, prev_info)
        self.assertIsNotNone(info_time)
        expected_info = {
            0: {
                'cpu_time': 243951379111104//8,
                'cpu_usage': 9,
                'memory_kb': 3733212,
            },
            1: {
                'cpu_time': 2849496569205,
                'cpu_usage': 99,
                'memory_kb': 303916,
            },
            11: {
                'cpu_time': 249658663079978//8,
                'cpu_usage': 12,
                'memory_kb': 3782668,
            },
        }
        self.assertEqual(info, expected_info)
        self.assertEqual(self.app.vmm.mock_calls, [
            ('xc.domain_getinfo', (0, 1024), {}),
            ('xc.domain_getinfo', (0, 1024), {}),
        ])

    def test_002_get_vm_stats_one_vm(self):
        self.app.vmm.configure_mock(**{
            'xc.domain_getinfo.return_value': [self.sample_xc_domain_getinfo[1]]
        })

        vm = mock.Mock
        vm.xid = 1
        vm.name = 'somevm'

        info_time, info = self.qubes_host.get_vm_stats(only_vm=vm)
        self.assertIsNotNone(info_time)
        self.assertEqual(self.app.vmm.mock_calls, [
            ('xc.domain_getinfo', (1, 1), {}),
        ])



class TC_30_VMCollection(qubes.tests.QubesTestCase):
    def setUp(self):
        super().setUp()
        self.app = TestApp()
        self.vms = qubes.app.VMCollection(self.app)

        self.testvm1 = qubes.tests.init.TestVM(
            None, None, qid=1, name='testvm1')
        self.testvm2 = qubes.tests.init.TestVM(
            None, None, qid=2, name='testvm2')

        self.addCleanup(self.cleanup_vmcollection)

    def cleanup_vmcollection(self):
        self.testvm1.close()
        self.testvm2.close()
        self.vms.close()
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


class TC_89_QubesEmpty(qubes.tests.QubesTestCase):
    def tearDown(self):
        try:
            os.unlink('/tmp/qubestest.xml')
        except:
            pass
        super().tearDown()

    @qubes.tests.skipUnlessDom0
    def test_000_init_empty(self):
        # pylint: disable=no-self-use,unused-variable,bare-except
        try:
            os.unlink('/tmp/qubestest.xml')
        except FileNotFoundError:
            pass
        qubes.Qubes.create_empty_store('/tmp/qubestest.xml').close()


class TC_90_Qubes(qubes.tests.QubesTestCase):
    def tearDown(self):
        try:
            os.unlink('/tmp/qubestest.xml')
        except:
            pass
        super().tearDown()

    def setUp(self):
        super(TC_90_Qubes, self).setUp()
        self.app = qubes.Qubes('/tmp/qubestest.xml', load=False,
            offline_mode=True)
        self.addCleanup(self.cleanup_qubes)
        self.app.load_initial_values()
        self.template = self.app.add_new_vm('TemplateVM', name='test-template',
            label='green')

    def cleanup_qubes(self):
        self.app.close()
        del self.app
        try:
            del self.template
        except AttributeError:
            pass

    def test_100_clockvm(self):
        appvm = self.app.add_new_vm('AppVM', name='test-vm', template=self.template,
            label='red')
        self.assertIsNone(self.app.clockvm)
        self.assertNotIn('service.clocksync', appvm.features)
        self.assertNotIn('service.clocksync', self.template.features)
        self.app.clockvm = appvm
        self.assertIn('service.clocksync', appvm.features)
        self.assertTrue(appvm.features['service.clocksync'])
        self.app.clockvm = self.template
        self.assertNotIn('service.clocksync', appvm.features)
        self.assertIn('service.clocksync', self.template.features)
        self.assertTrue(self.template.features['service.clocksync'])

    def test_200_remove_template(self):
        appvm = self.app.add_new_vm('AppVM', name='test-vm',
            template=self.template,
            label='red')
        with mock.patch.object(self.app, 'vmm'):
            with self.assertRaises(qubes.exc.QubesException):
                del self.app.domains[self.template]

    def test_201_remove_netvm(self):
        netvm = self.app.add_new_vm('AppVM', name='test-netvm',
            template=self.template, provides_network=True,
            label='red')
        appvm = self.app.add_new_vm('AppVM', name='test-vm',
            template=self.template,
            label='red')
        appvm.netvm = netvm
        with mock.patch.object(self.app, 'vmm'):
            with self.assertRaises(qubes.exc.QubesVMInUseError):
                del self.app.domains[netvm]

    def test_202_remove_default_netvm(self):
        netvm = self.app.add_new_vm('AppVM', name='test-netvm',
            template=self.template, provides_network=True,
            label='red')
        self.app.default_netvm = netvm
        with mock.patch.object(self.app, 'vmm'):
            with self.assertRaises(qubes.exc.QubesVMInUseError):
                del self.app.domains[netvm]

    def test_203_remove_default_dispvm(self):
        appvm = self.app.add_new_vm('AppVM', name='test-appvm',
            template=self.template,
            label='red')
        self.app.default_dispvm = appvm
        with mock.patch.object(self.app, 'vmm'):
            with self.assertRaises(qubes.exc.QubesVMInUseError):
                del self.app.domains[appvm]

    def test_204_remove_appvm_dispvm(self):
        dispvm = self.app.add_new_vm('AppVM', name='test-appvm',
            template=self.template,
            label='red')
        appvm = self.app.add_new_vm('AppVM', name='test-appvm2',
            template=self.template, default_dispvm=dispvm,
            label='red')
        with mock.patch.object(self.app, 'vmm'):
            with self.assertRaises(qubes.exc.QubesVMInUseError):
                del self.app.domains[dispvm]

    def test_205_remove_appvm_dispvm(self):
        appvm = self.app.add_new_vm('AppVM', name='test-appvm',
            template=self.template, template_for_dispvms=True,
            label='red')
        dispvm = self.app.add_new_vm('DispVM', name='test-dispvm',
            template=appvm,
            label='red')
        with mock.patch.object(self.app, 'vmm'):
            with self.assertRaises(qubes.exc.QubesVMInUseError):
                del self.app.domains[appvm]

    @qubes.tests.skipUnlessGit
    def test_900_example_xml_in_doc(self):
        self.assertXMLIsValid(
            lxml.etree.parse(open(
                os.path.join(qubes.tests.in_git, 'doc/example.xml'), 'rb')),
            'qubes.rng')
