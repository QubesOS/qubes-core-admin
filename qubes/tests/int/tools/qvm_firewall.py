#!/usr/bin/python2
# -*- encoding: utf8 -*-
#
# The Qubes OS Project, http://www.qubes-os.org
#
# Copyright (C) 2016 Marek Marczykowski-Górecki 
#                               <marmarek@invisiblethingslab.com>
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

import qubes.firewall
import qubes.tests
import qubes.tests.tools
import qubes.tools.qvm_firewall
import qubes.vm.appvm


class TC_10_ArgParser(qubes.tests.SystemTestsMixin, qubes.tests.QubesTestCase):
    list_header = ['NO', 'ACTION', 'HOST', 'PROTOCOL', 'PORT(S)',
        'SPECIAL TARGET', 'ICMP TYPE']

    def setUp(self):
        super(TC_10_ArgParser, self).setUp()
        self.init_default_template()
        self.vm = self.app.add_new_vm(qubes.vm.appvm.AppVM, None,
            name=self.make_vm_name('vm'), label='red')
        self.vm.create_on_disk()
        self.app.save()

    def test_000_list(self):
        with qubes.tests.tools.StdoutBuffer() as stdout:
            qubes.tools.qvm_firewall.main([self.vm.name, 'list'])
            self.assertEqual(stdout.getvalue(),
                '  '.join(self.list_header) + '\n')

    def test_001_list(self):
        self.vm.firewall.rules.append(
            qubes.firewall.Rule(action='accept', dsthost='127.0.0.2',
                proto='tcp', dstports=80))
        self.vm.firewall.rules.append(
            qubes.firewall.Rule(action='accept', dsthost='127.0.0.3',
                proto='icmp', icmptype=8))
        self.vm.firewall.rules.append(
            qubes.firewall.Rule(action='accept', specialtarget='dns'))
        self.vm.firewall.save()
        expected_output = (
            'NO  ACTION  HOST          PROTOCOL  PORT(S)  SPECIAL TARGET  ICMP '
            'TYPE\n'
            '0   accept  127.0.0.2/32  tcp       80                            '
            '    \n'
            '1   accept  127.0.0.3/32  icmp                               8    '
            '    \n'
            '2   accept                                   dns                  '
            '    \n'
        )
        with qubes.tests.tools.StdoutBuffer() as stdout:
            qubes.tools.qvm_firewall.main([self.vm.name, 'list'])
            self.assertEqual(
                '\n'.join(l.rstrip() for l in stdout.getvalue().splitlines()),
                '\n'.join(l.rstrip() for l in expected_output.splitlines()))

    def test_002_list_raw(self):
        self.vm.firewall.rules = [
            qubes.firewall.Rule(action='accept', dsthost='127.0.0.2',
                proto='tcp', dstports=80),
            qubes.firewall.Rule(action='accept', dsthost='127.0.0.3',
                proto='icmp', icmptype=8),
            qubes.firewall.Rule(action='accept', specialtarget='dns'),
        ]
        self.vm.firewall.save()
        expected_output = '\n'.join(rule.rule for rule in
            self.vm.firewall.rules) + '\n'
        with qubes.tests.tools.StdoutBuffer() as stdout:
            qubes.tools.qvm_firewall.main(['--raw', self.vm.name, 'list'])
            self.assertEqual(stdout.getvalue(), expected_output)

    def test_010_add(self):
        qubes.tools.qvm_firewall.main(
            [self.vm.name, 'add', 'accept', '1.2.3.0/24', 'tcp', '443'])
        self.assertEqual(self.vm.firewall.rules,
            [qubes.firewall.Rule(action='accept', dsthost='1.2.3.0/24',
                proto='tcp', dstports='443')])

    def test_011_add_before(self):
        self.vm.firewall.rules = [
            qubes.firewall.Rule(action='accept', dsthost='1.2.3.1'),
            qubes.firewall.Rule(action='accept', dsthost='1.2.3.2'),
            qubes.firewall.Rule(action='accept', dsthost='1.2.3.3'),
        ]
        self.vm.firewall.save()
        qubes.tools.qvm_firewall.main(
            [self.vm.name, 'add', '--before', '2',
                'accept', '1.2.3.0/24', 'tcp', '443'])
        self.vm.firewall.load()
        self.assertEqual(self.vm.firewall.rules,
            [qubes.firewall.Rule(action='accept', dsthost='1.2.3.1'),
             qubes.firewall.Rule(action='accept', dsthost='1.2.3.2'),
             qubes.firewall.Rule(action='accept', dsthost='1.2.3.0/24',
                proto='tcp', dstports='443'),
             qubes.firewall.Rule(action='accept', dsthost='1.2.3.3'),
             ])

    def test_020_del(self):
        self.vm.firewall.rules = [
            qubes.firewall.Rule(action='accept', dsthost='1.2.3.1'),
            qubes.firewall.Rule(action='accept', dsthost='1.2.3.2'),
            qubes.firewall.Rule(action='accept', dsthost='1.2.3.3'),
        ]
        self.vm.firewall.save()
        qubes.tools.qvm_firewall.main(
            [self.vm.name, 'del', 'accept', '1.2.3.2'])
        self.vm.firewall.load()
        self.assertEqual(self.vm.firewall.rules,
            [qubes.firewall.Rule(action='accept', dsthost='1.2.3.1'),
             qubes.firewall.Rule(action='accept', dsthost='1.2.3.3'),
             ])

    def test_021_del_by_number(self):
        self.vm.firewall.rules = [
            qubes.firewall.Rule(action='accept', dsthost='1.2.3.1'),
            qubes.firewall.Rule(action='accept', dsthost='1.2.3.2'),
            qubes.firewall.Rule(action='accept', dsthost='1.2.3.3'),
        ]
        self.vm.firewall.save()
        qubes.tools.qvm_firewall.main(
            [self.vm.name, 'del', '--rule-no', '1'])
        self.vm.firewall.load()
        self.assertEqual(self.vm.firewall.rules,
            [qubes.firewall.Rule(action='accept', dsthost='1.2.3.1'),
             qubes.firewall.Rule(action='accept', dsthost='1.2.3.3'),
             ])

    def test_030_policy(self):
        with qubes.tests.tools.StdoutBuffer() as stdout:
            qubes.tools.qvm_firewall.main([self.vm.name, 'policy'])
            self.assertEqual(stdout.getvalue(), 'accept\n')
        self.vm.firewall.policy = 'drop'
        self.vm.firewall.save()
        with qubes.tests.tools.StdoutBuffer() as stdout:
            qubes.tools.qvm_firewall.main([self.vm.name, 'policy'])
            self.assertEqual(stdout.getvalue(), 'drop\n')

    def test_031_policy_set(self):
        qubes.tools.qvm_firewall.main([self.vm.name, 'policy', 'drop'])
        self.assertEqual(self.vm.firewall.policy, 'drop')
        qubes.tools.qvm_firewall.main([self.vm.name, 'policy', 'accept'])
        self.vm.firewall.load()
        self.assertEqual(self.vm.firewall.policy, 'accept')

