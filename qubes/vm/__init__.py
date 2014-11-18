#!/usr/bin/python2 -O

'''Qubes Virtual Machines

Main public classes
-------------------

.. autoclass:: BaseVM
   :members:
   :show-inheritance:
.. autoclass:: property
   :members:
   :show-inheritance:

Helper classes and functions
----------------------------

.. autoclass:: VMPlugin
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

import qubes.plugins

class property(object):
    '''Qubes VM property.

    This class holds one property that can be saved and loaded from qubes.xml

    :param str name: name of the property
    :param object default: default value
    :param type type: if not :py:obj:`None`, this is used to initialise value
    :param int order: order of evaluation (bigger order values are later)
    :param str doc: docstring

    '''

    def __init__(self, name, default=None, type=None, order=0, doc=None):
        self.__name__ = name
        self._default = default
        self._type = type
        self.order = order
        self.__doc__ = doc

        self._attr_name = '_qubesprop_' + self.__name__

    def __get__(self, instance, owner):
        if instance is None:
            return self

        try:
            return getattr(instance, self._attr_name)

        except AttributeError:
            if self._default is None:
                raise AttributeError('property not set')
            else:
                return self._default

    def __set__(self, instance, value):
        setattr(instance, self._attr_name,
            (self._type(value) if self._type is not None else value))

    def __repr__(self):
        return '<{} object at {:#x} name={!r} default={!r}>'.format(
            self.__class__.__name__, id(self), self.__name__, self._default)

    def __hash__(self):
        return hash(self.__name__)

    def __eq__(self, other):
        return self.__name__ == other.__name__

class VMPlugin(qubes.plugins.Plugin):
    '''Metaclass for :py:class:`.BaseVM`'''
    def __init__(cls, name, bases, dict_):
        super(VMPlugin, cls).__init__(name, bases, dict_)
        cls.__hooks__ = collections.defaultdict(list)

class BaseVM(object):
    '''Base class for all VMs

    :param xml: xml node from which to deserialise
    :type xml: :py:class:`lxml.etree._Element` or :py:obj:`None`

    This class is responsible for serialising and deserialising machines and
    provides basic framework. It contains no management logic. For that, see
    :py:class:`qubes.vm.qubesvm.QubesVM`.
    '''

    __metaclass__ = VMPlugin

    def get_props_list(self):
        '''List all properties attached to this VM'''
        props = set()
        for class_ in self.__class__.__mro__:
            props.update(prop for prop in class_.__dict__.values()
                if isinstance(prop, property))
        return sorted(props, key=lambda prop: (prop.order, prop.__name__))

    def __init__(self, xml):
        self._xml = xml

        self.services = {}
        self.devices = collections.defaultdict(list)
        self.tags = {}

        if self._xml is None:
            return

        # properties
        all_names = set(prop.__name__ for prop in self.get_props_list())
        for node in self._xml.xpath('.//property'):
            name = node.get('name')
            value = node.get('ref') or node.text

            if not name in all_names:
                raise AttributeError(
                    'No property {!r} found in {!r}'.format(
                        name, self.__class__))

            setattr(self, name, value)

        # tags
        for node in self._xml.xpath('.//tag'):
            self.tags[node.get('name')] = node.text

        # services
        for node in self._xml.xpath('.//service'):
            self.services[node.text] = bool(ast.literal_eval(node.get('enabled', 'True')))

        # devices (pci, usb, ...)
        for parent in self._xml.xpath('.//devices'):
            devclass = parent.get('class')
            for node in parent.xpath('./device'):
                self.devices[devclass].append(node.text)

        # firewall
        #TODO

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
