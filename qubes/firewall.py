#!/usr/bin/python2 -O
# vim: fileencoding=utf-8
# pylint: disable=too-few-public-methods
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
import subprocess

import lxml.etree
import os
import socket

import qubes
import qubes.vm.qubesvm


class RuleOption(object):
    def __init__(self, value):
        self._value = str(value)

    @property
    def rule(self):
        raise NotImplementedError

    def __str__(self):
        return self._value

    def __eq__(self, other):
        return str(self) == other

# noinspection PyAbstractClass
class RuleChoice(RuleOption):
    # pylint: disable=abstract-method
    def __init__(self, value):
        super(RuleChoice, self).__init__(value)
        self.allowed_values = \
            [v for k, v in self.__class__.__dict__.items()
                if not k.startswith('__') and isinstance(v, basestring) and
                   not v.startswith('__')]
        if value not in self.allowed_values:
            raise ValueError(value)


class Action(RuleChoice):
    accept = 'accept'
    drop = 'drop'

    @property
    def rule(self):
        return 'action=' + str(self)


class Proto(RuleChoice):
    tcp = 'tcp'
    udp = 'udp'
    icmp = 'icmp'

    @property
    def rule(self):
        return 'proto=' + str(self)


class DstHost(RuleOption):
    '''Represent host/network address: either IPv4, IPv6, or DNS name'''
    def __init__(self, value, prefixlen=None):
        # TODO: in python >= 3.3 ipaddress module could be used
        if value.count('/') > 1:
            raise ValueError('Too many /: ' + value)
        elif not value.count('/'):
            # add prefix length to bare IP addresses
            try:
                socket.inet_pton(socket.AF_INET6, value)
                self.prefixlen = prefixlen or 128
                if self.prefixlen < 0 or self.prefixlen > 128:
                    raise ValueError(
                        'netmask for IPv6 must be between 0 and 128')
                value += '/' + str(self.prefixlen)
                self.type = 'dst6'
            except socket.error:
                try:
                    socket.inet_pton(socket.AF_INET, value)
                    if value.count('.') != 3:
                        raise ValueError(
                            'Invalid number of dots in IPv4 address')
                    self.prefixlen = prefixlen or 32
                    if self.prefixlen < 0 or self.prefixlen > 32:
                        raise ValueError(
                            'netmask for IPv4 must be between 0 and 32')
                    value += '/' + str(self.prefixlen)
                    self.type = 'dst4'
                except socket.error:
                    self.type = 'dsthost'
                    self.prefixlen = 0
        else:
            host, prefixlen = value.split('/', 1)
            prefixlen = int(prefixlen)
            if prefixlen < 0:
                raise ValueError('netmask must be non-negative')
            self.prefixlen = prefixlen
            try:
                socket.inet_pton(socket.AF_INET6, host)
                if prefixlen > 128:
                    raise ValueError('netmask for IPv6 must be <= 128')
                self.type = 'dst6'
            except socket.error:
                try:
                    socket.inet_pton(socket.AF_INET, host)
                    if prefixlen > 32:
                        raise ValueError('netmask for IPv4 must be <= 32')
                    self.type = 'dst4'
                    if host.count('.') != 3:
                        raise ValueError(
                            'Invalid number of dots in IPv4 address')
                except socket.error:
                    raise ValueError('Invalid IP address: ' + host)

        super(DstHost, self).__init__(value)

    @property
    def rule(self):
        return self.type + '=' + str(self)


class DstPorts(RuleOption):
    def __init__(self, value):
        if isinstance(value, int):
            value = str(value)
        if value.count('-') == 1:
            self.range = [int(x) for x in value.split('-', 1)]
        elif not value.count('-'):
            self.range = [int(value), int(value)]
        else:
            raise ValueError(value)
        if any(port < 0 or port > 65536 for port in self.range):
            raise ValueError('Ports out of range')
        if self.range[0] > self.range[1]:
            raise ValueError('Invalid port range')
        super(DstPorts, self).__init__(
            str(self.range[0]) if self.range[0] == self.range[1]
            else '-'.join(map(str, self.range)))

    @property
    def rule(self):
        return 'dstports=' + '{!s}-{!s}'.format(*self.range)


class IcmpType(RuleOption):
    def __init__(self, value):
        super(IcmpType, self).__init__(value)
        value = int(value)
        if value < 0 or value > 255:
            raise ValueError('ICMP type out of range')

    @property
    def rule(self):
        return 'icmptype=' + str(self)


class SpecialTarget(RuleChoice):
    dns = 'dns'

    @property
    def rule(self):
        return 'specialtarget=' + str(self)


class Expire(RuleOption):
    def __init__(self, value):
        super(Expire, self).__init__(value)
        self.datetime = datetime.datetime.utcfromtimestamp(int(value))

    @property
    def rule(self):
        return None

    @property
    def expired(self):
        return self.datetime < datetime.datetime.utcnow()


class Comment(RuleOption):
    @property
    def rule(self):
        return None


class Rule(qubes.PropertyHolder):
    def __init__(self, xml, **kwargs):
        super(Rule, self).__init__(xml, **kwargs)
        self.load_properties()
        self.events_enabled = True
        # validate dependencies
        if self.dstports:
            self.on_set_dstports('property-set:dstports', 'dstports',
                self.dstports, None)
        if self.icmptype:
            self.on_set_icmptype('property-set:icmptype', 'icmptype',
                self.icmptype, None)
        self.property_require('action', False, True)

    action = qubes.property('action',
        type=Action,
        order=0,
        doc='rule action')

    proto = qubes.property('proto',
        type=Proto,
        default=None,
        order=1,
        doc='protocol to match')

    dsthost = qubes.property('dsthost',
        type=DstHost,
        default=None,
        order=1,
        doc='destination host/network')

    dstports = qubes.property('dstports',
        type=DstPorts,
        default=None,
        order=2,
        doc='Destination port(s) (for \'tcp\' and \'udp\' protocol only)')

    icmptype = qubes.property('icmptype',
        type=IcmpType,
        default=None,
        order=2,
        doc='ICMP packet type (for \'icmp\' protocol only)')

    specialtarget = qubes.property('specialtarget',
        type=SpecialTarget,
        default=None,
        order=1,
        doc='Special target, for now only \'dns\' supported')

    expire = qubes.property('expire',
        type=Expire,
        default=None,
        doc='Timestamp (UNIX epoch) on which this rule expire')

    comment = qubes.property('comment',
        type=Comment,
        default=None,
        doc='User comment')

    # noinspection PyUnusedLocal
    @qubes.events.handler('property-pre-set:dstports')
    def on_set_dstports(self, _event, _prop, _new_value, _old_value=None):
        if self.proto not in ('tcp', 'udp'):
            raise ValueError(
                'dstports valid only for \'tcp\' and \'udp\' protocols')

    # noinspection PyUnusedLocal
    @qubes.events.handler('property-pre-set:icmptype')
    def on_set_icmptype(self, _event, _prop, _new_value, _old_value=None):
        if self.proto not in ('icmp',):
            raise ValueError('icmptype valid only for \'icmp\' protocol')

    # noinspection PyUnusedLocal
    @qubes.events.handler('property-set:proto')
    def on_set_proto(self, _event, _prop, new_value, _old_value=None):
        if new_value not in ('tcp', 'udp'):
            self.dstports = qubes.property.DEFAULT
        if new_value not in ('icmp',):
            self.icmptype = qubes.property.DEFAULT

    @qubes.events.handler('property-del:proto')
    def on_del_proto(self, _event, _prop, _old_value):
        self.dstports = qubes.property.DEFAULT
        self.icmptype = qubes.property.DEFAULT

    @property
    def rule(self):
        if self.expire and self.expire.expired:
            return None
        values = []
        for prop in self.property_list():
            value = getattr(self, prop.__name__)
            if value is None:
                continue
            if value.rule is None:
                continue
            values.append(value.rule)
        return ' '.join(values)

    @classmethod
    def from_xml_v1(cls, node, action):
        netmask = node.get('netmask')
        if netmask is None:
            netmask = 32
        else:
            netmask = int(netmask)
        address = node.get('address')
        if address:
            dsthost = DstHost(address, netmask)
        else:
            dsthost = None

        proto = node.get('proto')

        port = node.get('port')
        toport = node.get('toport')
        if port and toport:
            dstports = port + '-' + toport
        elif port:
            dstports = port
        else:
            dstports = None

        # backward compatibility: protocol defaults to TCP if port is specified
        if dstports and not proto:
            proto = 'tcp'

        if proto == 'any':
            proto = None

        expire = node.get('expire')

        kwargs = {
            'action': action,
        }
        if dsthost:
            kwargs['dsthost'] = dsthost
        if dstports:
            kwargs['dstports'] = dstports
        if proto:
            kwargs['proto'] = proto
        if expire:
            kwargs['expire'] = expire

        return cls(None, **kwargs)

    def __eq__(self, other):
        return self.rule == other.rule

class Firewall(object):
    def __init__(self, vm, load=True):
        assert hasattr(vm, 'firewall_conf')
        self.vm = vm
        #: firewall rules
        self.rules = []
        #: default action
        self.policy = None

        if load:
            self.load()

    def load_defaults(self):
        self.rules = []
        self.policy = Action('accept')

    def load(self):
        firewall_conf = os.path.join(self.vm.dir_path, self.vm.firewall_conf)
        if os.path.exists(firewall_conf):
            self.rules = []
            tree = lxml.etree.parse(firewall_conf)
            root = tree.getroot()

            version = root.get('version', '1')
            if version == '1':
                self.load_v1(root)
            elif version == '2':
                self.load_v2(root)
            else:
                raise qubes.exc.QubesVMError(self.vm,
                    'Unsupported firewall.xml version: {}'.format(version))
        else:
            self.load_defaults()

    def load_v1(self, xml_root):
        policy_v1 = xml_root.get('policy')
        assert policy_v1 in ('allow', 'deny')
        if policy_v1 == 'allow':
            self.policy = Action('accept')
        else:
            self.policy = Action('drop')

        def _translate_action(key):
            if xml_root.get(key, policy_v1) == 'allow':
                return Action.accept
            else:
                return Action.drop

        self.rules.append(Rule(None,
            action=_translate_action('dns'),
            specialtarget=SpecialTarget('dns')))

        self.rules.append(Rule(None,
            action=_translate_action('icmp'),
            proto=Proto.icmp))

        if self.policy == Action.accept:
            rule_action = Action.drop
        else:
            rule_action = Action.accept

        for element in xml_root:
            rule = Rule.from_xml_v1(element, rule_action)
            self.rules.append(rule)

    def load_v2(self, xml_root):
        self.policy = Action(xml_root.findtext('policy'))

        xml_rules = xml_root.find('rules')
        for xml_rule in xml_rules:
            rule = Rule(xml_rule)
            self.rules.append(rule)

    def save(self):
        firewall_conf = os.path.join(self.vm.dir_path, self.vm.firewall_conf)
        expiring_rules_present = False

        xml_root = lxml.etree.Element('firewall', version=str(2))

        xml_policy = lxml.etree.Element('policy')
        xml_policy.text = str(self.policy)
        xml_root.append(xml_policy)

        xml_rules = lxml.etree.Element('rules')
        for rule in self.rules:
            if rule.expire:
                if rule.expire and rule.expire.expired:
                    continue
                else:
                    expiring_rules_present = True
            xml_rule = lxml.etree.Element('rule')
            xml_rule.append(rule.xml_properties())
            xml_rules.append(xml_rule)

        xml_root.append(xml_rules)

        xml_tree = lxml.etree.ElementTree(xml_root)

        try:
            old_umask = os.umask(0o002)
            with open(firewall_conf, 'w') as firewall_xml:
                xml_tree.write(firewall_xml, encoding="UTF-8",
                    pretty_print=True)
            os.umask(old_umask)
        except EnvironmentError as err:
            self.vm.log.error("save error: {}".format(err))
            raise qubes.exc.QubesException('save error: {}'.format(err))

        if expiring_rules_present and not self.vm.app.vmm.offline_mode:
            subprocess.call(["sudo", "systemctl", "start",
                             "qubes-reload-firewall@%s.timer" % self.vm.name])
