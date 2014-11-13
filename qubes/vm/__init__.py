#!/usr/bin/python2 -O

import collections
import functools
import sys

import dateutil.parser

import qubes.plugins

class property(object):
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
    def __init__(cls, name, bases, dict_):
        super(VMPlugin, cls).__init__(name, bases, dict_)
        cls.__hooks__ = collections.defaultdict(list)

class BaseVM(object):
    __metaclass__ = VMPlugin

    def get_props_list(self):
        props = set()
        for class_ in self.__class__.__mro__:
            props.update(prop for prop in class_.__dict__.values()
                if isinstance(prop, property))
        return sorted(props, key=lambda prop: (prop.order, prop.__name__))

    def __init__(self, D):
        for prop in self.get_props_list():
            if prop.__name__ in D:
                setattr(self, prop.__name__, D[prop.__name__])

    def __repr__(self):
        return '<{} object at {:#x} {}>'.format(
            self.__class__.__name__, id(self),
            ' '.join('{}={}'.format(prop.__name__, getattr(self, prop.__name__))
                for prop in self.get_props_list()))

    @classmethod
    def add_hook(cls, event, f):
        cls.__hooks__[event].append(f)

    def fire_hooks(self, event, *args, **kwargs):
        for cls in self.__class__.__mro__:
            if not hasattr(cls, '__hooks__'): continue
            for hook in cls.__hooks__[event]:
                hook(self, *args, **kwargs)


def load(class_, D):
    cls = BaseVM[class_]
    return cls(D)

__all__ = qubes.plugins.load(__file__)
