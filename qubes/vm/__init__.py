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

import dateutil.parser
import lxml.etree

import qubes
import qubes.events
import qubes.plugins


class BaseVMMeta(qubes.plugins.Plugin, qubes.events.EmitterMeta):
    '''Metaclass for :py:class:`.BaseVM`'''
    def __init__(cls, name, bases, dict_):
        super(BaseVMMeta, cls).__init__(name, bases, dict_)
        cls.__hooks__ = collections.defaultdict(list)


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
        self.devices = collections.defaultdict(list) if devices is None else devices
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
        element = lxml.etree.Element('domain', id='domain-' + str(self.qid))

        element.append(self.save_properties())

        services = lxml.etree.Element('services')
        for service in self.services:
            node = lxml.etree.Element('service')
            node.text = service
            if not self.services[service]:
                node.set('enabled', 'False')
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
        return '<{} object at {:#x} {}>'.format(
            self.__class__.__name__, id(self),
            ' '.join('{}={}'.format(prop.__name__, getattr(self, prop.__name__))
                for prop in self.get_props_list()))


    @classmethod
    def add_hook(cls, event, f):
        '''Add hook to entire VM class and all subclasses

        :param str event: event type
        :param callable f: function to fire on event

        Prototype of the function depends on the exact type of event. Classes
        which inherit from this class will also inherit the hook.
        '''

        cls.__hooks__[event].append(f)


    def fire_hooks(self, event, *args, **kwargs):
        '''Fire hooks associated with an event

        :param str event: event type

        *args* and *kwargs* are passed to each function
        '''

        for cls in self.__class__.__mro__:
            if not hasattr(cls, '__hooks__'): continue
            for hook in cls.__hooks__[event]:
                hook(self, *args, **kwargs)


def load(class_, D):
    cls = BaseVM[class_]
    return cls(D)

__all__ = qubes.plugins.load(__file__)
