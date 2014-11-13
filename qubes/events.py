#!/usr/bin/python2 -O

import collections

import qubes.vm

system_hooks = collections.defaultdict(list)

def hook(event, vm=None, system=False):
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
    return callable(o) \
        and hasattr(o, 'ho_event') \
        and hasattr(o, 'ho_vm')

def add_system_hook(event, f):
    global_hooks[event].append(f)

def fire_system_hooks(event, *args, **kwargs):
    for hook in system_hooks[event]:
        hook(self, *args, **kwargs)
