#!/usr/bin/python2 -O

'''Qubes events.

Events are fired when something happens, like VM start or stop, property change
etc.

'''

import collections

import qubes.vm

#: collection of system-wide hooks
system_hooks = collections.defaultdict(list)

def hook(event, vm=None, system=False):
    '''Decorator factory.

    To hook an event, decorate a method in your plugin class with this
    decorator.

    :param str event: event type
    :param type vm: VM to hook (leave as None to hook all VMs)
    :param bool system: when :py:obj:`True`, hook is system-wide (not attached to any VM)
    '''

    def decorator(f):
        f.ho_event = event

        if system:
            f.ho_vm = None
        elif vm is None:
            f.ho_vm = qubes.vm.BaseVM
        else:
            f.ho_vm = vm

        return f

    return decorator

def ishook(o):
    '''Test if a method is hooked to an event.

    :param object o: suspected hook
    :return: :py:obj:`True` when function is a hook, :py:obj:`False` otherwise
    :rtype: bool
    '''

    return callable(o) \
        and hasattr(o, 'ho_event') \
        and hasattr(o, 'ho_vm')

def add_system_hook(event, f):
    '''Add system-wide hook.

    :param callable f: function to call
    '''

    global_hooks[event].append(f)

def fire_system_hooks(event, *args, **kwargs):
    '''Fire system-wide hooks.

    :param str event: event type

    *args* and *kwargs* are passed to all hooks.
    '''

    for hook in system_hooks[event]:
        hook(self, *args, **kwargs)
