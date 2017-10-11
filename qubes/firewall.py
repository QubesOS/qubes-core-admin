# pylint: disable=too-few-public-methods

#
# The Qubes OS Project, https://www.qubes-os.org/
#
# Copyright (C) 2016
#                   Marek Marczykowski-Górecki <marmarek@invisiblethingslab.com>
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

import datetime
import string
import subprocess

import itertools
import os
import socket
import lxml.etree

import qubes
import qubes.vm.qubesvm


class RuleOption(object):
    def __init__(self, untrusted_value):
        # subset of string.punctuation
        safe_set = string.ascii_letters + string.digits + \
                   ':;,./-_[]'
        assert all(x in safe_set for x in str(untrusted_value))
        value = str(untrusted_value)
        self._value = value

    @property
    def rule(self):
        raise NotImplementedError

    @property
    def api_rule(self):
        return self.rule

    def __str__(self):
        return self._value

    def __eq__(self, other):
        return str(self) == other

# noinspection PyAbstractClass
class RuleChoice(RuleOption):
    # pylint: disable=abstract-method
    def __init__(self, untrusted_value):
        # preliminary validation
        super(RuleChoice, self).__init__(untrusted_value)
        self.allowed_values = \
            [v for k, v in self.__class__.__dict__.items()
                if not k.startswith('__') and isinstance(v, str) and
                   not v.startswith('__')]
        if untrusted_value not in self.allowed_values:
            raise ValueError(untrusted_value)


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
    def __init__(self, untrusted_value, prefixlen=None):
        if untrusted_value.count('/') > 1:
            raise ValueError('Too many /: ' + untrusted_value)
        elif not untrusted_value.count('/'):
            # add prefix length to bare IP addresses
            try:
                socket.inet_pton(socket.AF_INET6, untrusted_value)
                value = untrusted_value
                self.prefixlen = prefixlen or 128
                if self.prefixlen < 0 or self.prefixlen > 128:
                    raise ValueError(
                        'netmask for IPv6 must be between 0 and 128')
                value += '/' + str(self.prefixlen)
                self.type = 'dst6'
            except socket.error:
                try:
                    socket.inet_pton(socket.AF_INET, untrusted_value)
                    if untrusted_value.count('.') != 3:
                        raise ValueError(
                            'Invalid number of dots in IPv4 address')
                    value = untrusted_value
                    self.prefixlen = prefixlen or 32
                    if self.prefixlen < 0 or self.prefixlen > 32:
                        raise ValueError(
                            'netmask for IPv4 must be between 0 and 32')
                    value += '/' + str(self.prefixlen)
                    self.type = 'dst4'
                except socket.error:
                    self.type = 'dsthost'
                    self.prefixlen = 0
                    safe_set = string.ascii_lowercase + string.digits + '-._'
                    if not all(c in safe_set for c in untrusted_value):
                        raise ValueError('Invalid hostname')
                    value = untrusted_value
        else:
            untrusted_host, untrusted_prefixlen = untrusted_value.split('/', 1)
            prefixlen = int(untrusted_prefixlen)
            if prefixlen < 0:
                raise ValueError('netmask must be non-negative')
            self.prefixlen = prefixlen
            try:
                socket.inet_pton(socket.AF_INET6, untrusted_host)
                value = untrusted_value
                if prefixlen > 128:
                    raise ValueError('netmask for IPv6 must be <= 128')
                self.type = 'dst6'
            except socket.error:
                try:
                    socket.inet_pton(socket.AF_INET, untrusted_host)
                    if prefixlen > 32:
                        raise ValueError('netmask for IPv4 must be <= 32')
                    self.type = 'dst4'
                    if untrusted_host.count('.') != 3:
                        raise ValueError(
                            'Invalid number of dots in IPv4 address')
                    value = untrusted_value
                except socket.error:
                    raise ValueError('Invalid IP address: ' + untrusted_host)

        super(DstHost, self).__init__(value)

    @property
    def rule(self):
        return self.type + '=' + str(self)


class DstPorts(RuleOption):
    def __init__(self, untrusted_value):
        if isinstance(untrusted_value, int):
            untrusted_value = str(untrusted_value)
        if untrusted_value.count('-') == 1:
            self.range = [int(x) for x in untrusted_value.split('-', 1)]
        elif not untrusted_value.count('-'):
            self.range = [int(untrusted_value), int(untrusted_value)]
        else:
            raise ValueError(untrusted_value)
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
    def __init__(self, untrusted_value):
        untrusted_value = int(untrusted_value)
        if untrusted_value < 0 or untrusted_value > 255:
            raise ValueError('ICMP type out of range')
        super(IcmpType, self).__init__(untrusted_value)

    @property
    def rule(self):
        return 'icmptype=' + str(self)


class SpecialTarget(RuleChoice):
    dns = 'dns'

    @property
    def rule(self):
        return 'specialtarget=' + str(self)


class Expire(RuleOption):
    def __init__(self, untrusted_value):
        super(Expire, self).__init__(untrusted_value)
        self.datetime = datetime.datetime.utcfromtimestamp(int(untrusted_value))

    @property
    def rule(self):
        return None

    @property
    def api_rule(self):
        return 'expire=' + str(self)

    @property
    def expired(self):
        return self.datetime < datetime.datetime.utcnow()


class Comment(RuleOption):
    # noinspection PyMissingConstructor
    def __init__(self, untrusted_value):
        # pylint: disable=super-init-not-called
        # subset of string.punctuation
        safe_set = string.ascii_letters + string.digits + \
                   ':;,./-_[] '
        assert all(x in safe_set for x in str(untrusted_value))
        value = str(untrusted_value)
        self._value = value

    @property
    def rule(self):
        return None

    @property
    def api_rule(self):
        return 'comment=' + str(self)


class Rule(qubes.PropertyHolder):
    def __init__(self, xml=None, **kwargs):
        '''Single firewall rule

        :param xml: XML element describing rule, or None
        :param kwargs: rule elements
        '''
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
    def on_set_dstports(self, event, name, newvalue, oldvalue=None):
        # pylint: disable=unused-argument
        if self.proto not in ('tcp', 'udp'):
            raise ValueError(
                'dstports valid only for \'tcp\' and \'udp\' protocols')

    # noinspection PyUnusedLocal
    @qubes.events.handler('property-pre-set:icmptype')
    def on_set_icmptype(self, event, name, newvalue, oldvalue=None):
        # pylint: disable=unused-argument
        if self.proto not in ('icmp',):
            raise ValueError('icmptype valid only for \'icmp\' protocol')

    # noinspection PyUnusedLocal
    @qubes.events.handler('property-set:proto')
    def on_set_proto(self, event, name, newvalue, oldvalue=None):
        # pylint: disable=unused-argument
        if newvalue not in ('tcp', 'udp'):
            self.dstports = qubes.property.DEFAULT
        if newvalue not in ('icmp',):
            self.icmptype = qubes.property.DEFAULT

    @qubes.events.handler('property-del:proto')
    def on_del_proto(self, event, name, oldvalue):
        # pylint: disable=unused-argument
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

    @property
    def api_rule(self):
        values = []
        # put comment at the end
        for prop in sorted(self.property_list(),
                key=(lambda p: p.__name__ == 'comment')):
            value = getattr(self, prop.__name__)
            if value is None:
                continue
            if value.api_rule is None:
                continue
            values.append(value.api_rule)
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

        return cls(**kwargs)

    @classmethod
    def from_api_string(cls, untrusted_rule):
        '''Parse a single line of firewall rule'''
        # comment is allowed to have spaces
        untrusted_options, _, untrusted_comment = untrusted_rule.partition(
            'comment=')
        # appropriate handlers in __init__ of individual options will perform
        #  option-specific validation
        kwargs = {}
        if untrusted_comment:
            kwargs['comment'] = Comment(untrusted_value=untrusted_comment)

        for untrusted_option in untrusted_options.strip().split(' '):
            untrusted_key, untrusted_value = untrusted_option.split('=', 1)
            if untrusted_key in kwargs:
                raise ValueError('Option \'{}\' already set'.format(
                    untrusted_key))
            if untrusted_key in [str(prop) for prop in cls.property_list()]:
                kwargs[untrusted_key] = cls.property_get_def(
                    untrusted_key).type(untrusted_value=untrusted_value)
            elif untrusted_key in ('dst4', 'dst6', 'dstname'):
                if 'dsthost' in kwargs:
                    raise ValueError('Option \'{}\' already set'.format(
                        'dsthost'))
                kwargs['dsthost'] = DstHost(untrusted_value=untrusted_value)
            else:
                raise ValueError('Unknown firewall option')

        return cls(**kwargs)

    def __eq__(self, other):
        if isinstance(other, Rule):
            return self.api_rule == other.api_rule
        return self.api_rule == str(other)

    def __hash__(self):
        return hash(self.api_rule)


class Firewall(object):
    def __init__(self, vm, load=True):
        assert hasattr(vm, 'firewall_conf')
        self.vm = vm
        #: firewall rules
        self.rules = []

        if load:
            self.load()

    @property
    def policy(self):
        ''' Default action - always 'drop' '''
        return Action('drop')

    def __eq__(self, other):
        if isinstance(other, Firewall):
            return self.rules == other.rules
        return NotImplemented

    def load_defaults(self):
        '''Load default firewall settings'''
        self.rules = [Rule(None, action='accept')]

    def clone(self, other):
        '''Clone firewall settings from other instance.
        This method discards pre-existing firewall settings.

        :param other: other :py:class:`Firewall` instance
        '''
        rules = []
        for rule in other.rules:
            # Rule constructor require some action, will be overwritten by
            # clone_properties below
            new_rule = Rule(action='drop')
            new_rule.clone_properties(rule)
            rules.append(new_rule)
        self.rules = rules

    def load(self):
        '''Load firewall settings from a file'''
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
        '''Load old (Qubes < 4.0) firewall XML format'''
        policy_v1 = xml_root.get('policy')
        assert policy_v1 in ('allow', 'deny')
        default_policy_is_accept = (policy_v1 == 'allow')

        def _translate_action(key):
            if xml_root.get(key, policy_v1) == 'allow':
                return Action.accept
            return Action.drop

        self.rules.append(Rule(None,
            action=_translate_action('dns'),
            specialtarget=SpecialTarget('dns')))

        self.rules.append(Rule(None,
            action=_translate_action('icmp'),
            proto=Proto.icmp))

        if default_policy_is_accept:
            rule_action = Action.drop
        else:
            rule_action = Action.accept

        for element in xml_root:
            rule = Rule.from_xml_v1(element, rule_action)
            self.rules.append(rule)
        if default_policy_is_accept:
            self.rules.append(Rule(None, action='accept'))

    def load_v2(self, xml_root):
        '''Load new (Qubes >= 4.0) firewall XML format'''
        xml_rules = xml_root.find('rules')
        for xml_rule in xml_rules:
            rule = Rule(xml_rule)
            self.rules.append(rule)

    def save(self):
        '''Save firewall rules to a file'''
        firewall_conf = os.path.join(self.vm.dir_path, self.vm.firewall_conf)
        expiring_rules_present = False

        xml_root = lxml.etree.Element('firewall', version=str(2))

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
            with open(firewall_conf, 'wb') as firewall_xml:
                xml_tree.write(firewall_xml, encoding="UTF-8",
                    pretty_print=True)
            os.umask(old_umask)
        except EnvironmentError as err:
            self.vm.log.error("save error: {}".format(err))
            raise qubes.exc.QubesException('save error: {}'.format(err))

        self.vm.fire_event('firewall-changed')

        if expiring_rules_present and not self.vm.app.vmm.offline_mode:
            subprocess.call(["sudo", "systemctl", "start",
                             "qubes-reload-firewall@%s.timer" % self.vm.name])

    def qdb_entries(self, addr_family=None):
        '''Return firewall settings serialized for QubesDB entries

        :param addr_family: include rules only for IPv4 (4) or IPv6 (6); if
        None, include both
        '''
        entries = {
            'policy': str(self.policy)
        }
        exclude_dsttype = None
        if addr_family is not None:
            exclude_dsttype = 'dst4' if addr_family == 6 else 'dst6'
        for ruleno, rule in zip(itertools.count(), self.rules):
            # exclude rules for another address family
            if rule.dsthost and rule.dsthost.type == exclude_dsttype:
                continue
            entries['{:04}'.format(ruleno)] = rule.rule
        return entries
