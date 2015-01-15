#!/usr/bin/python2 -O

import sys
import unittest

import qubes
import qubes.vm.adminvm

import qubes.tests

class TestVMM(object):
    def __init__(self, offline_mode=False):
        self.offline_mode = offline_mode

class TestHost(object):
    def __init__(self, offline_mode=False):
        self.memory_total = 1000

# this probably can be shared and not as dummy as is
class TestApp(qubes.tests.TestEmitter):
    def __init__(self):
        self.vmm = TestVMM()
        self.host = TestHost()


@qubes.tests.skipUnlessDom0
class TC_00_AdminVM(qubes.tests.QubesTestCase):
    def setUp(self):
        try:
            self.app = TestApp()
            self.vm = qubes.vm.adminvm.AdminVM(self.app,
                xml=None, qid=0, name='dom0')
        except:
            if self.id().endswith('.test_000_init'):
                raise
            self.skipTest('setup failed')

    def test_000_init(self):
        pass

    def test_100_xid(self):
        self.assertEqual(self.vm.xid, 0)

    def test_101_libvirt_domain(self):
        self.assertIs(self.vm.libvirt_domain, None)

    def test_200_libvirt_netvm(self):
        self.assertIs(self.vm.netvm, None)

    def test_300_is_running(self):
        self.assertTrue(self.vm.is_running())

    def test_301_get_power_state(self):
        self.assertEqual(self.vm.get_power_state(), 'Running')

    def test_302_get_mem(self):
        self.assertGreater(self.vm.get_mem(), 0)

    @unittest.skip('mock object does not support this')
    def test_303_get_mem_static_max(self):
        self.assertGreater(self.vm.get_mem_static_max(), 0)

    def test_304_get_disk_utilization(self):
        self.assertEqual(self.vm.get_disk_utilization(), 0)

    def test_305_get_disk_utilization_private_img(self):
        self.assertEqual(self.vm.get_disk_utilization_private_img(), 0)

    def test_306_get_private_img_sz(self):
        self.assertEqual(self.vm.get_private_img_sz(), 0)

    def test_307_verify_files(self):
        self.assertEqual(self.vm.get_private_img_sz(), 0)

    def test_310_start(self):
        with self.assertRaises(qubes.QubesException):
            self.vm.start()

    @unittest.skip('this functionality is undecided')
    def test_311_suspend(self):
        with self.assertRaises(qubes.QubesException):
            self.vm.suspend()
