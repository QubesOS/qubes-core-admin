#!/usr/bin/python2 -O
# vim: fileencoding=utf-8

#
# The Qubes OS Project, https://www.qubes-os.org/
#
# Copyright (C) 2016
#                   Marek Marczykowski-Górecki <marmarek@invisiblethingslab.com>
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

import datetime
import os

import lxml.etree
import unittest

import qubes.firewall
import qubes.tests


class TestOption(qubes.firewall.RuleChoice):
    opt1 = 'opt1'
    opt2 = 'opt2'
    another = 'another'

class TestVMM(object):
    def __init__(self):
        self.offline_mode = True


class TestApp(object):
    def __init__(self):
        self.vmm = TestVMM()


class TestVM(object):
    def __init__(self):
        self.firewall_conf = 'test-firewall.xml'
        self.dir_path = '/tmp'
        self.app = TestApp()


# noinspection PyPep8Naming
class TC_00_RuleChoice(qubes.tests.QubesTestCase):
    def test_000_accept_allowed(self):
        with self.assertNotRaises(ValueError):
            TestOption('opt1')
            TestOption('opt2')
            TestOption('another')

    def test_001_value_list(self):
        instance = TestOption('opt1')
        self.assertEqual(
            set(instance.allowed_values), {'opt1', 'opt2', 'another'})

    def test_010_reject_others(self):
        self.assertRaises(ValueError, lambda: TestOption('invalid'))


class TC_01_Action(qubes.tests.QubesTestCase):
    def test_000_allowed_values(self):
        with self.assertNotRaises(ValueError):
            instance = qubes.firewall.Action('accept')
        self.assertEqual(
            set(instance.allowed_values), {'accept', 'drop'})

    def test_001_rule(self):
        instance = qubes.firewall.Action('accept')
        self.assertEqual(instance.rule, 'action=accept')


# noinspection PyPep8Naming
class TC_02_Proto(qubes.tests.QubesTestCase):
    def test_000_allowed_values(self):
        with self.assertNotRaises(ValueError):
            instance = qubes.firewall.Proto('tcp')
        self.assertEqual(
            set(instance.allowed_values), {'tcp', 'udp', 'icmp'})

    def test_001_rule(self):
        instance = qubes.firewall.Proto('tcp')
        self.assertEqual(instance.rule, 'proto=tcp')


# noinspection PyPep8Naming
class TC_02_DstHost(qubes.tests.QubesTestCase):
    def test_000_hostname(self):
        with self.assertNotRaises(ValueError):
            instance = qubes.firewall.DstHost('qubes-os.org')
        self.assertEqual(instance.type, 'dsthost')

    def test_001_ipv4(self):
        with self.assertNotRaises(ValueError):
            instance = qubes.firewall.DstHost('127.0.0.1')
        self.assertEqual(instance.type, 'dst4')
        self.assertEqual(instance.prefixlen, 32)
        self.assertEqual(str(instance), '127.0.0.1/32')
        self.assertEqual(instance.rule, 'dst4=127.0.0.1/32')

    def test_002_ipv4_prefixlen(self):
        with self.assertNotRaises(ValueError):
            instance = qubes.firewall.DstHost('127.0.0.0', 8)
        self.assertEqual(instance.type, 'dst4')
        self.assertEqual(instance.prefixlen, 8)
        self.assertEqual(str(instance), '127.0.0.0/8')
        self.assertEqual(instance.rule, 'dst4=127.0.0.0/8')

    def test_003_ipv4_parse_prefixlen(self):
        with self.assertNotRaises(ValueError):
            instance = qubes.firewall.DstHost('127.0.0.0/8')
        self.assertEqual(instance.type, 'dst4')
        self.assertEqual(instance.prefixlen, 8)
        self.assertEqual(str(instance), '127.0.0.0/8')
        self.assertEqual(instance.rule, 'dst4=127.0.0.0/8')

    def test_004_ipv4_invalid_prefix(self):
        with self.assertRaises(ValueError):
            qubes.firewall.DstHost('127.0.0.0/33')
        with self.assertRaises(ValueError):
            qubes.firewall.DstHost('127.0.0.0', 33)
        with self.assertRaises(ValueError):
            qubes.firewall.DstHost('127.0.0.0/-1')

    def test_005_ipv4_reject_shortened(self):
        # not strictly required, but ppl are used to it
        with self.assertRaises(ValueError):
            qubes.firewall.DstHost('127/8')

    def test_006_ipv4_invalid_addr(self):
        with self.assertRaises(ValueError):
            qubes.firewall.DstHost('137.327.0.0/16')
        with self.assertRaises(ValueError):
            qubes.firewall.DstHost('1.2.3.4.5/32')

    @unittest.expectedFailure
    def test_007_ipv4_invalid_network(self):
        with self.assertRaises(ValueError):
            qubes.firewall.DstHost('127.0.0.1/32')

    def test_010_ipv6(self):
        with self.assertNotRaises(ValueError):
            instance = qubes.firewall.DstHost('2001:abcd:efab::3')
        self.assertEqual(instance.type, 'dst6')
        self.assertEqual(instance.prefixlen, 128)
        self.assertEqual(str(instance), '2001:abcd:efab::3/128')
        self.assertEqual(instance.rule, 'dst6=2001:abcd:efab::3/128')

    def test_011_ipv6_prefixlen(self):
        with self.assertNotRaises(ValueError):
            instance = qubes.firewall.DstHost('2001:abcd:efab::', 64)
        self.assertEqual(instance.type, 'dst6')
        self.assertEqual(instance.prefixlen, 64)
        self.assertEqual(str(instance), '2001:abcd:efab::/64')
        self.assertEqual(instance.rule, 'dst6=2001:abcd:efab::/64')

    def test_012_ipv6_parse_prefixlen(self):
        with self.assertNotRaises(ValueError):
            instance = qubes.firewall.DstHost('2001:abcd:efab::/64')
        self.assertEqual(instance.type, 'dst6')
        self.assertEqual(instance.prefixlen, 64)
        self.assertEqual(str(instance), '2001:abcd:efab::/64')
        self.assertEqual(instance.rule, 'dst6=2001:abcd:efab::/64')

    def test_013_ipv6_invalid_prefix(self):
        with self.assertRaises(ValueError):
            qubes.firewall.DstHost('2001:abcd:efab::3/129')
        with self.assertRaises(ValueError):
            qubes.firewall.DstHost('2001:abcd:efab::3', 129)
        with self.assertRaises(ValueError):
            qubes.firewall.DstHost('2001:abcd:efab::3/-1')

    def test_014_ipv6_invalid_addr(self):
        with self.assertRaises(ValueError):
            qubes.firewall.DstHost('2001:abcd:efab0123::3/128')
        with self.assertRaises(ValueError):
            qubes.firewall.DstHost('2001:abcd:efab:3/128')
        with self.assertRaises(ValueError):
            qubes.firewall.DstHost('2001:abcd:efab:a:a:a:a:a:a:3/128')
        with self.assertRaises(ValueError):
            qubes.firewall.DstHost('2001:abcd:efgh::3/128')

    @unittest.expectedFailure
    def test_015_ipv6_invalid_network(self):
        with self.assertRaises(ValueError):
            qubes.firewall.DstHost('2001:abcd:efab::3/64')

    @unittest.expectedFailure
    def test_020_invalid_hostname(self):
        with self.assertRaises(ValueError):
            qubes.firewall.DstHost('www  qubes-os.org')
        with self.assertRaises(ValueError):
            qubes.firewall.DstHost('https://qubes-os.org')

class TC_03_DstPorts(qubes.tests.QubesTestCase):
    def test_000_single_str(self):
        with self.assertNotRaises(ValueError):
            instance = qubes.firewall.DstPorts('80')
        self.assertEqual(str(instance), '80')
        self.assertEqual(instance.range, [80, 80])
        self.assertEqual(instance.rule, 'dstports=80-80')

    def test_001_single_int(self):
        with self.assertNotRaises(ValueError):
            instance = qubes.firewall.DstPorts(80)
        self.assertEqual(str(instance), '80')
        self.assertEqual(instance.range, [80, 80])
        self.assertEqual(instance.rule, 'dstports=80-80')

    def test_002_range(self):
        with self.assertNotRaises(ValueError):
            instance = qubes.firewall.DstPorts('80-90')
        self.assertEqual(str(instance), '80-90')
        self.assertEqual(instance.range, [80, 90])
        self.assertEqual(instance.rule, 'dstports=80-90')

    def test_003_invalid(self):
        with self.assertRaises(ValueError):
            qubes.firewall.DstPorts('80-90-100')
        with self.assertRaises(ValueError):
            qubes.firewall.DstPorts('abcdef')
        with self.assertRaises(ValueError):
            qubes.firewall.DstPorts('80 90')
        with self.assertRaises(ValueError):
            qubes.firewall.DstPorts('')

    def test_004_reversed_range(self):
        with self.assertRaises(ValueError):
            qubes.firewall.DstPorts('100-20')

    def test_005_out_of_range(self):
        with self.assertRaises(ValueError):
            qubes.firewall.DstPorts('1000000000000')
        with self.assertRaises(ValueError):
            qubes.firewall.DstPorts(1000000000000)
        with self.assertRaises(ValueError):
            qubes.firewall.DstPorts('1-1000000000000')


class TC_04_IcmpType(qubes.tests.QubesTestCase):
    def test_000_number(self):
        with self.assertNotRaises(ValueError):
            instance = qubes.firewall.IcmpType(8)
        self.assertEqual(str(instance), '8')
        self.assertEqual(instance.rule, 'icmptype=8')

    def test_001_str(self):
        with self.assertNotRaises(ValueError):
            instance = qubes.firewall.IcmpType('8')
        self.assertEqual(str(instance), '8')
        self.assertEqual(instance.rule, 'icmptype=8')

    def test_002_invalid(self):
        with self.assertRaises(ValueError):
            qubes.firewall.IcmpType(600)
        with self.assertRaises(ValueError):
            qubes.firewall.IcmpType(-1)
        with self.assertRaises(ValueError):
            qubes.firewall.IcmpType('abcde')
        with self.assertRaises(ValueError):
            qubes.firewall.IcmpType('')


class TC_05_SpecialTarget(qubes.tests.QubesTestCase):
    def test_000_allowed_values(self):
        with self.assertNotRaises(ValueError):
            instance = qubes.firewall.SpecialTarget('dns')
        self.assertEqual(
            set(instance.allowed_values), {'dns'})

    def test_001_rule(self):
        instance = qubes.firewall.SpecialTarget('dns')
        self.assertEqual(instance.rule, 'specialtarget=dns')


class TC_06_Expire(qubes.tests.QubesTestCase):
    def test_000_number(self):
        with self.assertNotRaises(ValueError):
            instance = qubes.firewall.Expire(1463292452)
        self.assertEqual(str(instance), '1463292452')
        self.assertEqual(instance.datetime,
            datetime.datetime(2016, 5, 15, 6, 7, 32))
        self.assertIsNone(instance.rule)

    def test_001_str(self):
        with self.assertNotRaises(ValueError):
            instance = qubes.firewall.Expire('1463292452')
        self.assertEqual(str(instance), '1463292452')
        self.assertEqual(instance.datetime,
            datetime.datetime(2016, 5, 15, 6, 7, 32))
        self.assertIsNone(instance.rule)

    def test_002_invalid(self):
        with self.assertRaises(ValueError):
            qubes.firewall.Expire('abcdef')
        with self.assertRaises(ValueError):
            qubes.firewall.Expire('')

    def test_003_expired(self):
        with self.assertNotRaises(ValueError):
            instance = qubes.firewall.Expire('1463292452')
        self.assertTrue(instance.expired)
        with self.assertNotRaises(ValueError):
            instance = qubes.firewall.Expire('1583292452')
        self.assertFalse(instance.expired)


class TC_07_Comment(qubes.tests.QubesTestCase):
    def test_000_str(self):
        with self.assertNotRaises(ValueError):
            instance = qubes.firewall.Comment('Some comment')
        self.assertEqual(str(instance), 'Some comment')
        self.assertIsNone(instance.rule)


class TC_08_Rule(qubes.tests.QubesTestCase):
    def test_000_simple(self):
        with self.assertNotRaises(ValueError):
            rule = qubes.firewall.Rule(None, action='accept', proto='icmp')
        self.assertEqual(rule.rule, 'action=accept proto=icmp')
        self.assertIsNone(rule.dsthost)
        self.assertIsNone(rule.dstports)
        self.assertIsNone(rule.icmptype)
        self.assertIsNone(rule.comment)
        self.assertIsNone(rule.expire)
        self.assertEqual(str(rule.action), 'accept')
        self.assertEqual(str(rule.proto), 'icmp')

    def test_001_expire(self):
        with self.assertNotRaises(ValueError):
            rule = qubes.firewall.Rule(None, action='accept', proto='icmp',
                expire='1463292452')
        self.assertIsNone(rule.rule)

        with self.assertNotRaises(ValueError):
            rule = qubes.firewall.Rule(None, action='accept', proto='icmp',
                expire='1663292452')
        self.assertIsNotNone(rule.rule)


    def test_002_dstports(self):
        with self.assertNotRaises(ValueError):
            rule = qubes.firewall.Rule(None, action='accept', proto='tcp',
                dstports=80)
        self.assertEqual(str(rule.dstports), '80')
        with self.assertNotRaises(ValueError):
            rule = qubes.firewall.Rule(None, action='accept', proto='udp',
                dstports=80)
        self.assertEqual(str(rule.dstports), '80')

    def test_003_reject_invalid(self):
        with self.assertRaises((ValueError, AssertionError)):
            # missing action
            qubes.firewall.Rule(None, proto='icmp')
        with self.assertRaises(ValueError):
            # not proto=tcp or proto=udp for dstports
            qubes.firewall.Rule(None, action='accept', proto='icmp',
                dstports=80)
        with self.assertRaises(ValueError):
            # not proto=tcp or proto=udp for dstports
            qubes.firewall.Rule(None, action='accept', dstports=80)
        with self.assertRaises(ValueError):
            # not proto=icmp for icmptype
            qubes.firewall.Rule(None, action='accept', proto='tcp',
                icmptype=8)
        with self.assertRaises(ValueError):
            # not proto=icmp for icmptype
            qubes.firewall.Rule(None, action='accept', icmptype=8)

    def test_004_proto_change(self):
        rule = qubes.firewall.Rule(None, action='accept', proto='tcp')
        with self.assertNotRaises(ValueError):
            rule.proto = 'udp'
        self.assertEqual(rule.rule, 'action=accept proto=udp')
        rule = qubes.firewall.Rule(None, action='accept', proto='tcp',
            dstports=80)
        with self.assertNotRaises(ValueError):
            rule.proto = 'udp'
        self.assertEqual(rule.rule, 'action=accept proto=udp dstports=80-80')
        rule = qubes.firewall.Rule(None, action='accept')
        with self.assertNotRaises(ValueError):
            rule.proto = 'udp'
        self.assertEqual(rule.rule, 'action=accept proto=udp')
        with self.assertNotRaises(ValueError):
            rule.dstports = 80
        self.assertEqual(rule.rule, 'action=accept proto=udp dstports=80-80')
        with self.assertNotRaises(ValueError):
            rule.proto = 'icmp'
        self.assertEqual(rule.rule, 'action=accept proto=icmp')
        self.assertIsNone(rule.dstports)
        rule.icmptype = 8
        self.assertEqual(rule.rule, 'action=accept proto=icmp icmptype=8')
        with self.assertNotRaises(ValueError):
            rule.proto = qubes.property.DEFAULT
        self.assertEqual(rule.rule, 'action=accept')
        self.assertIsNone(rule.dstports)

    def test_005_from_xml_v1(self):
        xml_txt = \
            '<rule address="192.168.0.0" proto="tcp" netmask="24" port="443"/>'
        with self.assertNotRaises(ValueError):
            rule = qubes.firewall.Rule.from_xml_v1(
                lxml.etree.fromstring(xml_txt), 'accept')
        self.assertEqual(rule.dsthost, '192.168.0.0/24')
        self.assertEqual(rule.proto, 'tcp')
        self.assertEqual(rule.dstports, '443')
        self.assertIsNone(rule.expire)
        self.assertIsNone(rule.comment)

    def test_006_from_xml_v1(self):
        xml_txt = \
            '<rule address="qubes-os.org" proto="tcp" ' \
            'port="443" toport="1024"/>'
        with self.assertNotRaises(ValueError):
            rule = qubes.firewall.Rule.from_xml_v1(
                lxml.etree.fromstring(xml_txt), 'drop')
        self.assertEqual(rule.dsthost, 'qubes-os.org')
        self.assertEqual(rule.proto, 'tcp')
        self.assertEqual(rule.dstports, '443-1024')
        self.assertEqual(rule.action, 'drop')
        self.assertIsNone(rule.expire)
        self.assertIsNone(rule.comment)

    def test_007_from_xml_v1(self):
        xml_txt = \
            '<rule address="192.168.0.0" netmask="24" expire="1463292452"/>'
        with self.assertNotRaises(ValueError):
            rule = qubes.firewall.Rule.from_xml_v1(
                lxml.etree.fromstring(xml_txt), 'accept')
        self.assertEqual(rule.dsthost, '192.168.0.0/24')
        self.assertEqual(rule.expire, '1463292452')
        self.assertEqual(rule.action, 'accept')
        self.assertIsNone(rule.proto)
        self.assertIsNone(rule.dstports)


class TC_10_Firewall(qubes.tests.QubesTestCase):
    def setUp(self):
        super(TC_10_Firewall, self).setUp()
        self.vm = TestVM()
        firewall_path = os.path.join('/tmp', self.vm.firewall_conf)
        if os.path.exists(firewall_path):
            os.unlink(firewall_path)

    def tearDown(self):
        firewall_path = os.path.join('/tmp', self.vm.firewall_conf)
        if os.path.exists(firewall_path):
            os.unlink(firewall_path)
        return super(TC_10_Firewall, self).tearDown()

    def test_000_defaults(self):
        fw = qubes.firewall.Firewall(self.vm, False)
        fw.load_defaults()
        self.assertEqual(fw.policy, 'accept')
        self.assertEqual(fw.rules, [])

    def test_001_save_load_empty(self):
        fw = qubes.firewall.Firewall(self.vm, True)
        self.assertEqual(fw.policy, 'accept')
        self.assertEqual(fw.rules, [])
        fw.save()
        fw.load()
        self.assertEqual(fw.policy, 'accept')
        self.assertEqual(fw.rules, [])

    def test_002_save_load_rules(self):
        fw = qubes.firewall.Firewall(self.vm, True)
        rules = [
            qubes.firewall.Rule(None, action='drop', proto='icmp'),
            qubes.firewall.Rule(None, action='drop', proto='tcp', dstports=80),
            qubes.firewall.Rule(None, action='accept', proto='udp',
                dstports=67),
            qubes.firewall.Rule(None, action='accept', specialtarget='dns'),
            ]
        fw.rules.extend(rules)
        fw.policy = qubes.firewall.Action.drop
        fw.save()
        self.assertTrue(os.path.exists(os.path.join(
            self.vm.dir_path, self.vm.firewall_conf)))
        fw = qubes.firewall.Firewall(TestVM(), True)
        self.assertEqual(fw.policy, qubes.firewall.Action.drop)
        self.assertEqual(fw.rules, rules)

    def test_003_load_v1(self):
        xml_txt = """<QubesFirewallRules dns="allow" icmp="allow"
        policy="deny" yumProxy="allow">
            <rule address="192.168.0.0" proto="tcp" netmask="24" port="80"/>
            <rule address="qubes-os.org" proto="tcp" port="443"/>
        </QubesFirewallRules>
        """
        with open(os.path.join('/tmp', self.vm.firewall_conf), 'w') as f:
            f.write(xml_txt)
        with self.assertNotRaises(ValueError):
            fw = qubes.firewall.Firewall(self.vm)
        self.assertEqual(str(fw.policy), 'drop')
        rules = [
            qubes.firewall.Rule(None, action='accept', specialtarget='dns'),
            qubes.firewall.Rule(None, action='accept', proto='icmp'),
            qubes.firewall.Rule(None, action='accept', proto='tcp',
                dsthost='192.168.0.0/24', dstports='80'),
            qubes.firewall.Rule(None, action='accept', proto='tcp',
                dsthost='qubes-os.org', dstports='443')
        ]
        self.assertEqual(fw.rules, rules)

    def test_004_save_skip_expired(self):
        fw = qubes.firewall.Firewall(self.vm, True)
        rules = [
            qubes.firewall.Rule(None, action='drop', proto='icmp'),
            qubes.firewall.Rule(None, action='drop', proto='tcp', dstports=80),
            qubes.firewall.Rule(None, action='accept', proto='udp',
                dstports=67, expire=1373300257),
            qubes.firewall.Rule(None, action='accept', specialtarget='dns'),
            ]
        fw.rules.extend(rules)
        fw.policy = qubes.firewall.Action.drop
        fw.save()
        rules.pop(2)
        fw = qubes.firewall.Firewall(self.vm, True)
        self.assertEqual(fw.rules, rules)

    def test_005_qdb_entries(self):
        fw = qubes.firewall.Firewall(self.vm, True)
        rules = [
            qubes.firewall.Rule(None, action='drop', proto='icmp'),
            qubes.firewall.Rule(None, action='drop', proto='tcp', dstports=80),
            qubes.firewall.Rule(None, action='accept', proto='udp'),
            qubes.firewall.Rule(None, action='accept', specialtarget='dns'),
        ]
        fw.rules.extend(rules)
        fw.policy = qubes.firewall.Action.drop
        expected_qdb_entries = {
            'policy': 'drop',
            '0000': 'action=drop proto=icmp',
            '0001': 'action=drop proto=tcp dstports=80-80',
            '0002': 'action=accept proto=udp',
            '0003': 'action=accept specialtarget=dns',
        }
        self.assertEqual(fw.qdb_entries(), expected_qdb_entries)
