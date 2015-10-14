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

import unittest

import qubes
import qubes.exc
import qubes.config
import qubes.vm.qubesvm

import qubes.tests


class TestProp(object):
    # pylint: disable=too-few-public-methods
    __name__ = 'testprop'


class TestVM(object):
    # pylint: disable=too-few-public-methods
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
            qubes.vm.qubesvm._setter_qid(self.vm,
                self.prop, qubes.config.max_qid + 5)


    def test_010_setter_name(self):
        self.assertEqual(
            qubes.vm.qubesvm._setter_name(self.vm, self.prop, 'test_name-1'),
            'test_name-1')

    def test_011_setter_name_longer_than_31(self):
        # pylint: disable=invalid-name
        with self.assertRaises(ValueError):
            qubes.vm.qubesvm._setter_name(self.vm, self.prop, 't' * 32)

    def test_012_setter_name_illegal_character(self):
        # pylint: disable=invalid-name
        with self.assertRaises(ValueError):
            qubes.vm.qubesvm._setter_name(self.vm, self.prop, 'test#')

    def test_013_setter_name_first_not_letter(self):
        # pylint: disable=invalid-name
        with self.assertRaises(ValueError):
            qubes.vm.qubesvm._setter_name(self.vm, self.prop, '1test')

    def test_014_setter_name_running(self):
        self.vm.running = True
        with self.assertRaises(qubes.exc.QubesVMNotHaltedError):
            qubes.vm.qubesvm._setter_name(self.vm, self.prop, 'testname')

    def test_015_setter_name_installed_by_rpm(self):
        # pylint: disable=invalid-name
        self.vm.installed_by_rpm = True
        with self.assertRaises(qubes.exc.QubesException):
            qubes.vm.qubesvm._setter_name(self.vm, self.prop, 'testname')


    @unittest.skip('test not implemented')
    def test_020_setter_kernel(self):
        pass


class TC_90_QubesVM(qubes.tests.QubesTestCase):
    @unittest.skip('test not implemented')
    def test_000_init(self):
        pass
