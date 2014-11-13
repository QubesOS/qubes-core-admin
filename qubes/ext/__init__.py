#!/usr/bin/python2 -O

'''Qubes extensions

Extensions provide additional features (like application menus) found only on
some systems. They may be OS- or architecture-dependent or custom-developed for
particular customer.

.. autoclass:: Extension
   :members:
   :show-inheritance:

.. autoclass:: ExtensionPlugin
   :members:
   :show-inheritance:

'''

import inspect

import qubes.events
import qubes.plugins

class ExtensionPlugin(qubes.plugins.Plugin):
    '''Metaclass for :py:class:`Extension`'''
    def __init__(cls, name, bases, dict_):
        super(ExtensionPlugin, cls).__init__(name, bases, dict_)
        cls._instance = None

    def __call__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super(ExtensionPlugin, cls).__call__(*args, **kwargs)
        return cls._instance

class Extension(object):
    '''Base class for all extensions'''
    __metaclass__ = ExtensionPlugin
    def __init__(self):
        for name in dir(self):
            attr = getattr(self, name)
            if not ishook(attr):
                continue

            if attr.ho_vm is not None:
                attr.ho_vm.add_hook(event, attr)
            else:
                # global hook
                qubes.events.add_system_hook(event, attr)

def init():
    for ext in Extension.register.values():
        instance = ext()

__all__ = qubes.plugins.load(__file__)
