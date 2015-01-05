#!/usr/bin/python2 -O

import sys
import unittest

import qubes
import qubes.vm.qubesvm

import qubes.tests


class TestProp(object):
    __name__ = 'testprop'


class TestVM(object):
    def __init__(self):
        self.running = False
        self.installed_by_rpm = False

    def is_running(self):
        return self.running


class TC_00_setters(qubes.tests.QubesTestCase):
    def setUp(self):
        self.vm = TestVM()
        self.prop = TestProp()


    def test_000_setter_qid(self):
        self.assertEqual(
            qubes.vm.qubesvm._setter_qid(self.vm, self.prop, 5), 5)

    def test_001_setter_qid_lt_0(self):
        with self.assertRaises(ValueError):
            qubes.vm.qubesvm._setter_qid(self.vm, self.prop, -1)

    def test_002_setter_qid_gt_max(self):
        with self.assertRaises(ValueError):
            qubes.vm.qubesvm._setter_qid(self.vm, self.prop, qubes.MAX_QID + 5)


    def test_010_setter_name(self):
        self.assertEqual(
            qubes.vm.qubesvm._setter_name(self.vm, self.prop, 'test_name-1'),
            'test_name-1')

    def test_011_setter_name_longer_than_31(self):
        with self.assertRaises(ValueError):
            qubes.vm.qubesvm._setter_name(self.vm, self.prop, 't' * 32)

    def test_012_setter_name_illegal_character(self):
        with self.assertRaises(ValueError):
            qubes.vm.qubesvm._setter_name(self.vm, self.prop, 'test#')

    def test_013_setter_name_first_not_letter(self):
        with self.assertRaises(ValueError):
            qubes.vm.qubesvm._setter_name(self.vm, self.prop, '1test')

    def test_014_setter_name_running(self):
        self.vm.running = True
        with self.assertRaises(qubes.QubesException):
            qubes.vm.qubesvm._setter_name(self.vm, self.prop, 'testname')

    def test_015_setter_name_installed_by_rpm(self):
        self.vm.installed_by_rpm = True
        with self.assertRaises(qubes.QubesException):
            qubes.vm.qubesvm._setter_name(self.vm, self.prop, 'testname')


    @unittest.skip('test not implemented')
    def test_020_setter_kernel(self):
        pass


class TC_90_QubesVM(qubes.tests.QubesTestCase):
    @unittest.skip('test not implemented')
    def test_000_init(self):    
        pass
