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
import uuid

import qubes
import qubes.exc
import qubes.config
import qubes.vm.qubesvm

import qubes.tests

class TestApp(object):
    labels = {1: qubes.Label(1, '0xcc0000', 'red')}

class TestProp(object):
    # pylint: disable=too-few-public-methods
    __name__ = 'testprop'

class TestVM(object):
    # pylint: disable=too-few-public-methods
    app = TestApp()

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

    def test_011_setter_name_not_a_string(self):
        # pylint: disable=invalid-name
        with self.assertRaises(TypeError):
            qubes.vm.qubesvm._setter_name(self.vm, self.prop, False)

    def test_012_setter_name_longer_than_31(self):
        # pylint: disable=invalid-name
        with self.assertRaises(ValueError):
            qubes.vm.qubesvm._setter_name(self.vm, self.prop, 't' * 32)

    def test_013_setter_name_illegal_character(self):
        # pylint: disable=invalid-name
        with self.assertRaises(ValueError):
            qubes.vm.qubesvm._setter_name(self.vm, self.prop, 'test#')

    def test_014_setter_name_first_not_letter(self):
        # pylint: disable=invalid-name
        with self.assertRaises(ValueError):
            qubes.vm.qubesvm._setter_name(self.vm, self.prop, '1test')

    def test_015_setter_name_running(self):
        self.vm.running = True
        with self.assertRaises(qubes.exc.QubesVMNotHaltedError):
            qubes.vm.qubesvm._setter_name(self.vm, self.prop, 'testname')

    def test_016_setter_name_installed_by_rpm(self):
        # pylint: disable=invalid-name
        self.vm.installed_by_rpm = True
        with self.assertRaises(qubes.exc.QubesException):
            qubes.vm.qubesvm._setter_name(self.vm, self.prop, 'testname')


    @unittest.skip('test not implemented')
    def test_020_setter_kernel(self):
        pass


    def test_030_setter_label_object(self):
        label = TestApp.labels[1]
        self.assertIs(label,
            qubes.vm.qubesvm._setter_label(self.vm, self.prop, label))

    def test_031_setter_label_getitem(self):
        label = TestApp.labels[1]
        self.assertIs(label,
            qubes.vm.qubesvm._setter_label(self.vm, self.prop, 'label-1'))

    # there is no check for self.app.get_label()


class TC_90_QubesVM(qubes.tests.QubesTestCase):
    def setUp(self):
        super(TC_90_QubesVM, self).setUp()
        self.app = qubes.tests.vm.TestApp()

    def get_vm(self, **kwargs):
        return qubes.vm.qubesvm.QubesVM(self.app, None,
            qid=1, name=qubes.tests.VMPREFIX + 'test',
            **kwargs)

    def test_000_init(self):
        self.get_vm()

    def test_001_init_no_qid_or_name(self):
        with self.assertRaises(AssertionError):
            qubes.vm.qubesvm.QubesVM(self.app, None,
                name=qubes.tests.VMPREFIX + 'test')
        with self.assertRaises(AssertionError):
            qubes.vm.qubesvm.QubesVM(self.app, None,
                qid=1)

    def test_003_init_fire_domain_init(self):
        class TestVM2(qubes.vm.qubesvm.QubesVM):
            event_fired = False
            @qubes.events.handler('domain-init')
            def on_domain_init(self, event): # pylint: disable=unused-argument
                self.__class__.event_fired = True

        TestVM2(self.app, None, qid=1, name=qubes.tests.VMPREFIX + 'test')
        self.assertTrue(TestVM2.event_fired)

    def test_004_uuid_autogen(self):
        vm = self.get_vm()
        self.assertTrue(hasattr(vm, 'uuid'))

    def test_100_qid(self):
        vm = self.get_vm()
        self.assertIsInstance(vm.qid, int)
        with self.assertRaises(AttributeError):
            vm.qid = 2

    def test_110_name(self):
        vm = self.get_vm()
        self.assertIsInstance(vm.name, basestring)

    def test_120_uuid(self):
        my_uuid = uuid.uuid4()
        vm = self.get_vm(uuid=my_uuid)
        self.assertIsInstance(vm.uuid, uuid.UUID)
        self.assertIs(vm.uuid, my_uuid)
        with self.assertRaises(AttributeError):
            vm.uuid = uuid.uuid4()

#   label = qubes.property('label',
#   netvm = qubes.VMProperty('netvm', load_stage=4, allow_none=True,
#   conf_file = qubes.property('conf_file', type=str,
#   firewall_conf = qubes.property('firewall_conf', type=str,
#   installed_by_rpm = qubes.property('installed_by_rpm',
#   memory = qubes.property('memory', type=int,
#   maxmem = qubes.property('maxmem', type=int, default=None,
#   internal = qubes.property('internal', default=False,
#   vcpus = qubes.property('vcpus',
#   kernel = qubes.property('kernel', type=str,
#   kernelopts = qubes.property('kernelopts', type=str, load_stage=4,
#   mac = qubes.property('mac', type=str,
#   debug = qubes.property('debug', type=bool, default=False,
#   default_user = qubes.property('default_user', type=str,
#   qrexec_timeout = qubes.property('qrexec_timeout', type=int, default=60,
#   autostart = qubes.property('autostart', default=False,
#   include_in_backups = qubes.property('include_in_backups', default=True,
#   backup_content = qubes.property('backup_content', default=False,
#   backup_size = qubes.property('backup_size', type=int, default=0,
#   backup_path = qubes.property('backup_path', type=str, default='',
#   backup_timestamp = qubes.property('backup_timestamp', default=None,

    @qubes.tests.skipUnlessDom0
    def test_200_create_on_disk(self):
        vm = self.get_vm()
        vm.create_on_disk()

    @unittest.skip('test not implemented')
    def test_300_rename(self):
        pass
