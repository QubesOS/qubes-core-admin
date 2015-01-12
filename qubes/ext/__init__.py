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
    '''Base class for all extensions

    :param qubes.Qubes app: application object
    '''

    __metaclass__ = ExtensionPlugin

    def __init__(self, app):
        self.app = app

        for name in dir(self):
            attr = getattr(self, name)
            if not qubes.events.ishandler(attr):
                continue

            if attr.ha_vm is not None:
                attr.ha_vm.add_hook(attr.ha_event, attr)
            else:
                # global hook
                self.app.add_hook(attr.ha_event, attr)


def handler(*events, **kwargs):
    '''Event handler decorator factory.

    To hook an event, decorate a method in your plugin class with this
    decorator. You may hook both per-vm-class and global events.

    .. note::
        This decorator is intended only for extensions! For regular use in the
        core, see py:func:`qubes.events.handler`.

    :param str event: event type
    :param type vm: VM to hook (leave as None to hook all VMs)
    :param bool system: when :py:obj:`True`, hook is system-wide (not attached to any VM)
    '''

    def decorator(f):
        f.ha_events = events

        if kwargs.get('system', False):
            f.ha_vm = None
        elif 'vm' in kwargs:
            f.ha_vm = kwargs['vm']
        else:
            f.ha_vm = qubes.vm.BaseVM

        return f

    return decorator


__all__ = qubes.plugins.load(__file__)
