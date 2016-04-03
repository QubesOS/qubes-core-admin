#!/usr/bin/python2 -O
# vim: fileencoding=utf-8

#
# The Qubes OS Project, https://www.qubes-os.org/
#
# Copyright (C) 2010-2015  Joanna Rutkowska <joanna@invisiblethingslab.com>
# Copyright (C) 2011-2015  Marek Marczykowski-Górecki
#                              <marmarek@invisiblethingslab.com>
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

'''Qubes Virtual Machines

'''

import ast
import collections
import datetime
import functools
import itertools
import os
import re
import subprocess
import sys
import xml.parsers.expat

import lxml.etree

import qubes
import qubes.log
import qubes.devices
import qubes.events
import qubes.tools.qvm_ls


class Features(dict):
    '''Manager of the features.

    Features can have three distinct values: no value (not present in mapping,
    which is closest thing to :py:obj:`None`), empty string (which is
    interpreted as :py:obj:`False`) and non-empty string, which is
    :py:obj:`True`. Anything assigned to the mapping is coerced to strings,
    however if you assign instances of :py:class:`bool`, they are converted as
    described above. Be aware that assigning the number `0` (which is considered
    false in Python) will result in string `'0'`, which is considered true.

    This class inherits from dict, but has most of the methods that manipulate
    the item disarmed (they raise NotImplementedError). The ones that are left
    fire appropriate events on the qube that owns an instance of this class.
    '''

    #
    # Those are the methods that affect contents. Either disarm them or make
    # them report appropriate events. Good approach is to rewrite them carefully
    # using official documentation, but use only our (overloaded) methods.
    #
    def __init__(self, vm, other=None, **kwargs):
        super(Features, self).__init__()
        self.vm = vm
        self.update(other, **kwargs)

    def __delitem__(self, key):
        super(Features, self).__delitem__(key)
        self.vm.fire_event('domain-feature-delete', key)

    def __setitem__(self, key, value):
        if value is None or isinstance(value, bool):
            value = '1' if value else ''
        else:
            value = str(value)
        self.vm.fire_event('domain-feature-set', key, value)
        super(Features, self).__setitem__(key, value)

    def clear(self):
        for key in self:
            del self[key]

    def pop(self):
        '''Not implemented
        :raises: NotImplementedError
        '''
        raise NotImplementedError()

    def popitem(self):
        '''Not implemented
        :raises: NotImplementedError
        '''
        raise NotImplementedError()

    def setdefault(self):
        '''Not implemented
        :raises: NotImplementedError
        '''
        raise NotImplementedError()

    def update(self, other=None, **kwargs):
        if other is not None:
            if hasattr(other, 'keys'):
                for key in other:
                    self[key] = other[key]
            else:
                for key, value in other:
                    self[key] = value

        for key in kwargs:
            self[key] = kwargs[key]

    #
    # end of overriding
    #

    _NO_DEFAULT = object()
    def check_with_template(self, feature, default=_NO_DEFAULT):
        if feature in self:
            return self[feature]

        if hasattr(self.vm, 'template') and self.vm.template is not None \
                and feature in self.vm.template.features:
            return self.vm.template.features[feature]

        if default is self._NO_DEFAULT:
            raise KeyError(feature)

        return default


class BaseVMMeta(qubes.events.EmitterMeta):
    '''Metaclass for :py:class:`.BaseVM`'''
    def __init__(cls, name, bases, dict_):
        super(BaseVMMeta, cls).__init__(name, bases, dict_)
        qubes.tools.qvm_ls.process_class(cls)


class BaseVM(qubes.PropertyHolder):
    '''Base class for all VMs

    :param app: Qubes application context
    :type app: :py:class:`qubes.Qubes`
    :param xml: xml node from which to deserialise
    :type xml: :py:class:`lxml.etree._Element` or :py:obj:`None`

    This class is responsible for serializing and deserialising machines and
    provides basic framework. It contains no management logic. For that, see
    :py:class:`qubes.vm.qubesvm.QubesVM`.
    '''
    # pylint: disable=no-member

    __metaclass__ = BaseVMMeta

    def __init__(self, app, xml, features=None, devices=None, tags=None,
            **kwargs):
        # pylint: disable=redefined-outer-name

        # self.app must be set before super().__init__, because some property
        # setters need working .app attribute
        #: mother :py:class:`qubes.Qubes` object
        self.app = app

        super(BaseVM, self).__init__(xml, **kwargs)

        #: dictionary of features of this qube
        self.features = Features(self, features)

        #: :py:class:`DeviceManager` object keeping devices that are attached to
        #: this domain
        self.devices = devices or qubes.devices.DeviceManager(self)

        #: user-specified tags
        self.tags = tags or {}

        if self.xml is not None:
            # features
            for node in xml.xpath('./features/feature'):
                self.features[node.get('name')] = node.text

            # devices (pci, usb, ...)
            for parent in xml.xpath('./devices'):
                devclass = parent.get('class')
                for node in parent.xpath('./device'):
                    self.devices[devclass].attach(node.text)

            # tags
            for node in xml.xpath('./tags/tag'):
                self.tags[node.get('name')] = node.text

            # TODO: firewall, policy

            # check if properties are appropriate
            all_names = set(prop.__name__ for prop in self.property_list())

            for node in self.xml.xpath('./properties/property'):
                name = node.get('name')
                if not name in all_names:
                    raise TypeError(
                        'property {!r} not applicable to {!r}'.format(
                            name, self.__class__.__name__))

        #: logger instance for logging messages related to this VM
        self.log = None

        if hasattr(self, 'name'):
            self.init_log()


    def init_log(self):
        '''Initialise logger for this domain.'''
        self.log = qubes.log.get_vm_logger(self.name)


    def __xml__(self):
        element = lxml.etree.Element('domain')
        element.set('id', 'domain-' + str(self.qid))
        element.set('class', self.__class__.__name__)

        element.append(self.xml_properties())

        features = lxml.etree.Element('features')
        for feature in self.features:
            node = lxml.etree.Element('feature', name=feature)
            node.text = self.features[feature]
            features.append(node)
        element.append(features)

        for devclass in self.devices:
            devices = lxml.etree.Element('devices')
            devices.set('class', devclass)
            for device in self.devices[devclass]:
                node = lxml.etree.Element('device')
                node.text = device
                devices.append(node)
            element.append(devices)

        tags = lxml.etree.Element('tags')
        for tag in self.tags:
            node = lxml.etree.Element('tag', name=tag)
            node.text = self.tags[tag]
            tags.append(node)
        element.append(tags)

        return element

    def __repr__(self):
        proprepr = []
        for prop in self.property_list():
            try:
                proprepr.append('{}={!s}'.format(
                    prop.__name__, getattr(self, prop.__name__)))
            except AttributeError:
                continue

        return '<{} object at {:#x} {}>'.format(
            self.__class__.__name__, id(self), ' '.join(proprepr))


    #
    # xml serialising methods
    #

    @staticmethod
    def lvxml_net_dev(ip, mac, backend):
        '''Return ``<interface>`` node for libvirt xml.

        This was previously _format_net_dev

        :param str ip: IP address of the frontend
        :param str mac: MAC (Ethernet) address of the frontend
        :param qubes.vm.qubesvm.QubesVM backend: Backend domain
        :rtype: lxml.etree._Element
        '''

        interface = lxml.etree.Element('interface', type='ethernet')
        interface.append(lxml.etree.Element('mac', address=mac))
        interface.append(lxml.etree.Element('ip', address=ip))
        interface.append(lxml.etree.Element('backenddomain', name=backend.name))
        interface.append(lxml.etree.Element('script', path="vif-route-qubes"))

        return interface


    @staticmethod
    def lvxml_pci_dev(address):
        '''Return ``<hostdev>`` node for libvirt xml.

        This was previously _format_pci_dev

        :param str ip: IP address of the frontend
        :param str mac: MAC (Ethernet) address of the frontend
        :param qubes.vm.qubesvm.QubesVM backend: Backend domain
        :rtype: lxml.etree._Element
        '''

        dev_match = re.match(r'([0-9a-f]+):([0-9a-f]+)\.([0-9a-f]+)', address)
        if not dev_match:
            raise ValueError('Invalid PCI device address: {!r}'.format(address))

        hostdev = lxml.etree.Element('hostdev', type='pci', managed='yes')
        source = lxml.etree.Element('source')
        source.append(lxml.etree.Element('address',
            bus='0x' + dev_match.group(1),
            slot='0x' + dev_match.group(2),
            function='0x' + dev_match.group(3)))
        hostdev.append(source)
        return hostdev

    #
    # old libvirt XML
    # TODO rewrite it to do proper XML synthesis via lxml.etree
    #

    def get_config_params(self):
        '''Return parameters for libvirt's XML domain config

        .. deprecated:: 3.0-alpha This will go away.
        '''

        args = {}
        args['name'] = self.name
        args['uuid'] = str(self.uuid)
        args['vmdir'] = self.dir_path
        args['pcidevs'] = ''.join(lxml.etree.tostring(self.lvxml_pci_dev(dev))
            for dev in self.devices['pci'])
        args['maxmem'] = str(self.maxmem)
        args['vcpus'] = str(self.vcpus)
        args['mem'] = str(min(self.memory, self.maxmem))

        # If dynamic memory management disabled, set maxmem=mem
        if not self.features.get('meminfo-writer', True):
            args['maxmem'] = args['mem']

        if self.netvm is not None:
            args['ip'] = self.ip
            args['mac'] = self.mac
            args['gateway'] = self.netvm.gateway

            for i, addr in zip(itertools.count(start=1), self.dns):
                args['dns{}'.format(i)] = addr

            args['netmask'] = self.netmask
            args['netdev'] = lxml.etree.tostring(
                self.lvxml_net_dev(self.ip, self.mac, self.netvm))
            args['network_begin'] = ''
            args['network_end'] = ''
            args['no_network_begin'] = '<!--'
            args['no_network_end'] = '-->'
        else:
            args['ip'] = ''
            args['mac'] = ''
            args['gateway'] = ''
            args['dns1'] = ''
            args['dns2'] = ''
            args['netmask'] = ''
            args['netdev'] = ''
            args['network_begin'] = '<!--'
            args['network_end'] = '-->'
            args['no_network_begin'] = ''
            args['no_network_end'] = ''

        args.update(self.storage.get_config_params())

        if hasattr(self, 'kernelopts'):
            args['kernelopts'] = self.kernelopts
            if self.debug:
                self.log.info(
                    "Debug mode: adding 'earlyprintk=xen' to kernel opts")
                args['kernelopts'] += ' earlyprintk=xen'

        return args


    def create_config_file(self, file_path=None, prepare_dvm=False):
        '''Create libvirt's XML domain config file

        If :py:attr:`qubes.vm.qubesvm.QubesVM.uses_custom_config` is true, this
        does nothing.

        :param str file_path: Path to file to create \
            (default: :py:attr:`qubes.vm.qubesvm.QubesVM.conf_file`)
        :param bool prepare_dvm: If we are in the process of preparing \
            DisposableVM
        '''

        if file_path is None:
            file_path = self.conf_file
        # TODO
        # if self.uses_custom_config:
        #     conf_appvm = open(file_path, "r")
        #     domain_config = conf_appvm.read()
        #     conf_appvm.close()
        #     return domain_config

        domain_config = self.app.env.get_template('libvirt/xen.xml').render(
            vm=self, prepare_dvm=prepare_dvm)

        # FIXME: This is only for debugging purposes
        old_umask = os.umask(002)
        try:
            conf_appvm = open(file_path, "w")
            conf_appvm.write(domain_config)
            conf_appvm.close()
        except: # pylint: disable=bare-except
            # Ignore errors
            pass
        finally:
            os.umask(old_umask)

        return domain_config


    #
    # firewall
    # TODO rewrite it, have <firewall/> node under <domain/>
    # and possibly integrate with generic policy framework
    #

    def write_firewall_conf(self, conf):
        '''Write firewall config file.
        '''
        defaults = self.get_firewall_conf()
        expiring_rules_present = False
        for item in defaults.keys():
            if item not in conf:
                conf[item] = defaults[item]

        root = lxml.etree.Element(
                "QubesFirewallRules",
                policy=("allow" if conf["allow"] else "deny"),
                dns=("allow" if conf["allowDns"] else "deny"),
                icmp=("allow" if conf["allowIcmp"] else "deny"),
                yumProxy=("allow" if conf["allowYumProxy"] else "deny"))

        for rule in conf["rules"]:
            # For backward compatibility
            if "proto" not in rule:
                if rule["portBegin"] is not None and rule["portBegin"] > 0:
                    rule["proto"] = "tcp"
                else:
                    rule["proto"] = "any"
            element = lxml.etree.Element(
                    "rule",
                    address=rule["address"],
                    proto=str(rule["proto"]),
            )
            if rule["netmask"] is not None and rule["netmask"] != 32:
                element.set("netmask", str(rule["netmask"]))
            if rule.get("portBegin", None) is not None and \
                            rule["portBegin"] > 0:
                element.set("port", str(rule["portBegin"]))
            if rule.get("portEnd", None) is not None and rule["portEnd"] > 0:
                element.set("toport", str(rule["portEnd"]))
            if "expire" in rule:
                element.set("expire", str(rule["expire"]))
                expiring_rules_present = True

            root.append(element)

        tree = lxml.etree.ElementTree(root)

        try:
            old_umask = os.umask(002)
            with open(os.path.join(self.dir_path,
                    self.firewall_conf), 'w') as fd:
                tree.write(fd, encoding="UTF-8", pretty_print=True)
            fd.close()
            os.umask(old_umask)
        except EnvironmentError as err: # pylint: disable=broad-except
            print >> sys.stderr, "{0}: save error: {1}".format(
                    os.path.basename(sys.argv[0]), err)
            return False

        # Automatically enable/disable 'updates-proxy-setup' service based on
        # allowYumProxy
        if conf['allowYumProxy']:
            self.features['updates-proxy-setup'] = '1'
        else:
            try:
                del self.features['updates-proxy-setup']
            except KeyError:
                pass

        if expiring_rules_present:
            subprocess.call(["sudo", "systemctl", "start",
                             "qubes-reload-firewall@%s.timer" % self.name])

        # XXX any better idea? some arguments?
        self.fire_event('firewall-changed')

        return True

    def has_firewall(self):
        return os.path.exists(os.path.join(self.dir_path, self.firewall_conf))

    @staticmethod
    def get_firewall_defaults():
        return {
            'rules': list(),
            'allow': True,
            'allowDns': True,
            'allowIcmp': True,
            'allowYumProxy': False}

    def get_firewall_conf(self):
        conf = self.get_firewall_defaults()

        try:
            tree = lxml.etree.parse(os.path.join(self.dir_path,
                self.firewall_conf))
            root = tree.getroot()

            conf["allow"] = (root.get("policy") == "allow")
            conf["allowDns"] = (root.get("dns") == "allow")
            conf["allowIcmp"] = (root.get("icmp") == "allow")
            conf["allowYumProxy"] = (root.get("yumProxy") == "allow")

            for element in root:
                rule = {}
                attr_list = ("address", "netmask", "proto", "port", "toport",
                             "expire")

                for attribute in attr_list:
                    rule[attribute] = element.get(attribute)

                if rule["netmask"] is not None:
                    rule["netmask"] = int(rule["netmask"])
                else:
                    rule["netmask"] = 32

                if rule["port"] is not None:
                    rule["portBegin"] = int(rule["port"])
                else:
                    # backward compatibility
                    rule["portBegin"] = 0

                # For backward compatibility
                if rule["proto"] is None:
                    if rule["portBegin"] > 0:
                        rule["proto"] = "tcp"
                    else:
                        rule["proto"] = "any"

                if rule["toport"] is not None:
                    rule["portEnd"] = int(rule["toport"])
                else:
                    rule["portEnd"] = None

                if rule["expire"] is not None:
                    rule["expire"] = int(rule["expire"])
                    if rule["expire"] <= int(datetime.datetime.now().strftime(
                            "%s")):
                        continue
                else:
                    del rule["expire"]

                del rule["port"]
                del rule["toport"]

                conf["rules"].append(rule)

        except EnvironmentError as err: # pylint: disable=broad-except
            # problem accessing file, like ENOTFOUND, EPERM or sth
            # return default config
            return conf

        except (xml.parsers.expat.ExpatError,
                ValueError, LookupError) as err:
            # config is invalid
            print("{0}: load error: {1}".format(
                os.path.basename(sys.argv[0]), err))
            return None

        return conf
