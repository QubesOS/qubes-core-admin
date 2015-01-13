#!/usr/bin/python2 -O

'''Qubes Virtual Machines

Main public classes
-------------------

.. autoclass:: BaseVM
   :members:
   :show-inheritance:

Helper classes and functions
----------------------------

.. autoclass:: BaseVMMeta
   :members:
   :show-inheritance:

Particular VM classes
---------------------

Main types:

.. toctree::
   :maxdepth: 1

   qubesvm
   appvm
   templatevm

Special VM types:

.. toctree::
   :maxdepth: 1

   netvm
   proxyvm
   dispvm
   adminvm

HVMs:

.. toctree::
   :maxdepth: 1

   hvm
   templatehvm

'''

import ast
import collections
import functools
import sys

import lxml.etree

import qubes
import qubes.events
import qubes.plugins


class BaseVMMeta(qubes.plugins.Plugin, qubes.events.EmitterMeta):
    '''Metaclass for :py:class:`.BaseVM`'''
    def __init__(cls, name, bases, dict_):
        super(BaseVMMeta, cls).__init__(name, bases, dict_)
        cls.__hooks__ = collections.defaultdict(list)


class DeviceCollection(object):
    '''Bag for devices.

    Used as default value for :py:meth:`DeviceManager.__missing__` factory.

    :param vm: VM for which we manage devices
    :param class_: device class
    '''

    def __init__(self, vm, class_):
        self._vm = vm
        self._class = class_
        self._set = set()


    def attach(self, device):
        '''Attach (add) device to domain.

        :param str device: device identifier (format is class-dependent)
        '''

        if device in self:
            raise KeyError(
                'device {!r} of class {} already attached to {!r}'.format(
                    device, self._class, self._vm))
        self._vm.fire_event_pre('device-pre-attached:{}'.format(self._class), device)
        self._set.add(device)
        self._vm.fire_event('device-attached:{}'.format(self._class), device)


    def detach(self, device):
        '''Detach (remove) device from domain.

        :param str device: device identifier (format is class-dependent)
        '''

        if device not in self:
            raise KeyError(
                'device {!r} of class {} not attached to {!r}'.format(
                    device, self._class, self._vm))
        self._vm.fire_event_pre('device-pre-detached:{}'.format(self._class), device)
        self._set.remove(device)
        self._vm.fire_event('device-detached:{}'.format(self._class), device)


    def __iter__(self):
        return iter(self._set)


    def __contains__(self, item):
        return item in self._set


class DeviceManager(dict):
    '''Device manager that hold all devices by their classess.

    :param vm: VM for which we manage devices
    '''

    def __init__(self, vm):
        super(DeviceManager, self).__init__()
        self._vm = vm

    def __missing__(self, key):
        return DeviceCollection(self._vm, key)


class BaseVM(qubes.PropertyHolder):
    '''Base class for all VMs

    :param app: Qubes application context
    :type app: :py:class:`qubes.Qubes`
    :param xml: xml node from which to deserialise
    :type xml: :py:class:`lxml.etree._Element` or :py:obj:`None`

    This class is responsible for serialising and deserialising machines and
    provides basic framework. It contains no management logic. For that, see
    :py:class:`qubes.vm.qubesvm.QubesVM`.
    '''

    __metaclass__ = BaseVMMeta

    def __init__(self, app, xml, load_stage=2, services={}, devices=None,
            tags={}, *args, **kwargs):
        self.app = app
        self.services = services
        self.devices = DeviceManager(self) if devices is None else devices
        self.tags = tags

        self.events_enabled = False
        all_names = set(prop.__name__ for prop in self.get_props_list(load_stage=2))
        for key in list(kwargs.keys()):
            if not key in all_names:
                raise AttributeError(
                    'No property {!r} found in {!r}'.format(
                        key, self.__class__))
            setattr(self, key, kwargs[key])
            del kwargs[key]

        super(BaseVM, self).__init__(xml, *args, **kwargs)

        self.events_enabled = True
        self.fire_event('property-load')


    def add_new_vm(self, vm):
        '''Add new Virtual Machine to colletion

        '''

        vm_cls = QubesVmClasses[vm_type]
        if 'template' in kwargs:
            if not vm_cls.is_template_compatible(kwargs['template']):
                raise QubesException("Template not compatible with selected "
                                     "VM type")

        vm = vm_cls(qid=qid, collection=self, **kwargs)
        if not self.verify_new_vm(vm):
            raise QubesException("Wrong VM description!")
        self[vm.qid] = vm

        # make first created NetVM the default one
        if self.default_fw_netvm_qid is None and vm.is_netvm():
            self.set_default_fw_netvm(vm)

        if self.default_netvm_qid is None and vm.is_proxyvm():
            self.set_default_netvm(vm)

        # make first created TemplateVM the default one
        if self.default_template_qid is None and vm.is_template():
            self.set_default_template(vm)

        # make first created ProxyVM the UpdateVM
        if self.updatevm_qid is None and vm.is_proxyvm():
            self.set_updatevm_vm(vm)

        # by default ClockVM is the first NetVM
        if self.clockvm_qid is None and vm.is_netvm():
            self.set_clockvm_vm(vm)

        return vm

    @classmethod
    def fromxml(cls, app, xml, load_stage=2):
        '''Create VM from XML node

        :param qubes.Qubes app: :py:class:`qubes.Qubes` application instance
        :param lxml.etree._Element xml: XML node reference
        :param int load_stage: do not change the default (2) unless you know, what you are doing
        '''

#       sys.stderr.write('{}.fromxml(app={!r}, xml={!r}, load_stage={})\n'.format(
#           cls.__name__, app, xml, load_stage))
        if xml is None:
            return cls(app)

        services = {}
        devices = collections.defaultdict(list)
        tags = {}

        # services
        for node in xml.xpath('./services/service'):
            services[node.text] = bool(ast.literal_eval(node.get('enabled', 'True')))

        # devices (pci, usb, ...)
        for parent in xml.xpath('./devices'):
            devclass = parent.get('class')
            for node in parent.xpath('./device'):
                devices[devclass].append(node.text)

        # tags
        for node in xml.xpath('./tags/tag'):
            tags[node.get('name')] = node.text

        # properties
        self = cls(app, xml=xml, services=services, devices=devices, tags=tags)
        self.load_properties(load_stage=load_stage)

        # TODO: firewall, policy

#       sys.stderr.write('{}.fromxml return\n'.format(cls.__name__))
        return self


    def __xml__(self):
        element = lxml.etree.Element('domain')
        element.set('id', 'domain-' + str(self.qid))
        element.set('class', self.__class__.__name__)

        element.append(self.xml_properties())

        services = lxml.etree.Element('services')
        for service in self.services:
            node = lxml.etree.Element('service')
            node.text = service
            if not self.services[service]:
                node.set('enabled', 'false')
            services.append(node)
        element.append(services)

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
        for prop in self.get_props_list():
            try:
                proprepr.append('{}={!r}'.format(
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
        :param qubes.vm.QubesVM backend: Backend domain
        :rtype: lxml.etree._Element
        '''

        interface = lxml.etree.Element('interface', type='ethernet')
        interface.append(lxml.etree.Element('mac', address=mac))
        interface.append(lxml.etree.Element('ip', address=ip))
        interface.append(lxml.etree.Element('domain', name=backend.name))

        return interface


    @staticmethod
    def lvxml_pci_dev(address):
        '''Return ``<hostdev>`` node for libvirt xml.

        This was previously _format_pci_dev

        :param str ip: IP address of the frontend
        :param str mac: MAC (Ethernet) address of the frontend
        :param qubes.vm.QubesVM backend: Backend domain
        :rtype: lxml.etree._Element
        '''

        dev_match = re.match('([0-9a-f]+):([0-9a-f]+)\.([0-9a-f]+)', address)
        if not dev_match:
            raise QubesException("Invalid PCI device address: %s" % address)

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
        if hasattr(self, 'kernels_dir'):
            args['kerneldir'] = self.kernels_dir
        args['uuidnode'] = '<uuid>{!r}</uuid>'.format(self.uuid) \
            if hasattr(self, 'uuid') else ''
        args['vmdir'] = self.dir_path
        args['pcidevs'] = ''.join(lxml.etree.tostring(self.lvxml_pci_dev(dev))
            for dev in self.devices['pci'])
        args['maxmem'] = str(self.maxmem)
        args['vcpus'] = str(self.vcpus)
        args['mem'] = str(max(self.memory, self.maxmem))

        if 'meminfo-writer' in self.services and not self.services['meminfo-writer']:
            # If dynamic memory management disabled, set maxmem=mem
            args['maxmem'] = args['mem']

        if self.netvm is not None:
            args['ip'] = self.ip
            args['mac'] = self.mac
            args['gateway'] = self.netvm.gateway
            args['dns1'] = self.netvm.gateway
            args['dns2'] = self.secondary_dns
            args['netmask'] = self.netmask
            args['netdev'] = lxml.etree.tostring(self.lvxml_net_dev(self.ip, self.mac, self.netvm))
            args['disable_network1'] = '';
            args['disable_network2'] = '';
        else:
            args['ip'] = ''
            args['mac'] = ''
            args['gateway'] = ''
            args['dns1'] = ''
            args['dns2'] = ''
            args['netmask'] = ''
            args['netdev'] = ''
            args['disable_network1'] = '<!--';
            args['disable_network2'] = '-->';

        args.update(self.storage.get_config_params())

        if hasattr(self, 'kernelopts'):
            args['kernelopts'] = self.kernelopts
            if self.debug:
                self.log.info("Debug mode: adding 'earlyprintk=xen' to kernel opts")
                args['kernelopts'] += ' earlyprintk=xen'


    def create_config_file(self, file_path=None, prepare_dvm=False):
        '''Create libvirt's XML domain config file

        If :py:attr:`qubes.vm.qubesvm.QubesVM.uses_custom_config` is true, this
        does nothing.

        :param str file_path: Path to file to create (default: :py:attr:`qubes.vm.qubesvm.QubesVM.conf_file`)
        :param bool prepare_dvm: If we are in the process of preparing DisposableVM
        '''

        if file_path is None:
            file_path = self.conf_file
        if self.uses_custom_config:
            conf_appvm = open(file_path, "r")
            domain_config = conf_appvm.read()
            conf_appvm.close()
            return domain_config

        f_conf_template = open(self.config_file_template, 'r')
        conf_template = f_conf_template.read()
        f_conf_template.close()

        template_params = self.get_config_params()
        if prepare_dvm:
            template_params['name'] = '%NAME%'
            template_params['privatedev'] = ''
            template_params['netdev'] = re.sub(r"address='[0-9.]*'", "address='%IP%'", template_params['netdev'])
        domain_config = conf_template.format(**template_params)

        # FIXME: This is only for debugging purposes
        old_umask = os.umask(002)
        try:
            conf_appvm = open(file_path, "w")
            conf_appvm.write(domain_config)
            conf_appvm.close()
        except:
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
                policy = "allow" if conf["allow"] else "deny",
                dns = "allow" if conf["allowDns"] else "deny",
                icmp = "allow" if conf["allowIcmp"] else "deny",
                yumProxy = "allow" if conf["allowYumProxy"] else "deny"
        )

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
            with open(self.firewall_conf, 'w') as f:
                tree.write(f, encoding="UTF-8", pretty_print=True)
            f.close()
            os.umask(old_umask)
        except EnvironmentError as err:
            print >> sys.stderr, "{0}: save error: {1}".format(
                    os.path.basename(sys.argv[0]), err)
            return False

        # Automatically enable/disable 'yum-proxy-setup' service based on allowYumProxy
        if conf['allowYumProxy']:
            self.services['yum-proxy-setup'] = True
        else:
            if self.services.has_key('yum-proxy-setup'):
                self.services.pop('yum-proxy-setup')

        if expiring_rules_present:
            subprocess.call(["sudo", "systemctl", "start",
                             "qubes-reload-firewall@%s.timer" % self.name])

        return True

    def has_firewall(self):
        return os.path.exists (self.firewall_conf)

    def get_firewall_defaults(self):
        return { "rules": list(), "allow": True, "allowDns": True, "allowIcmp": True, "allowYumProxy": False }

    def get_firewall_conf(self):
        conf = self.get_firewall_defaults()

        try:
            tree = lxml.etree.parse(self.firewall_conf)
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
                    del(rule["expire"])

                del(rule["port"])
                del(rule["toport"])

                conf["rules"].append(rule)

        except EnvironmentError as err:
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

def load(class_, D):
    cls = BaseVM[class_]
    return cls(D)

__all__ = qubes.plugins.load(__file__)
