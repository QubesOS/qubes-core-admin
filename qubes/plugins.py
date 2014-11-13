#!/usr/bin/python2 -O
# -*- coding: utf-8 -*-

'''Plugins helpers for Qubes

Qubes uses two types of plugins: virtual machines and extensions.
'''

import imp
import inspect
import os
import sys

class Plugin(type):
    '''Base metaclass for plugins'''
    def __init__(cls, name, bases, dict_):
        if hasattr(cls, 'register'):
            cls.register[cls.__name__] = cls
        else:
            # we've got root class
            cls.register = {}

    def __getitem__(cls, name):
        return cls.register[name]

def load(modfile):
    '''Load (import) all plugins from subpackage.

    This function should be invoked from ``__init__.py`` in a package like that:

    >>> __all__ = qubes.plugins.load(__file__) # doctest: +SKIP
    '''
    path = os.path.dirname(modfile)
    listdir = os.listdir(path)
    ret = set()
    for suffix, mode, type_ in imp.get_suffixes():
        for filename in listdir:
            if filename.endswith(suffix):
                ret.add(filename[:-len(suffix)])
    if '__init__' in ret:
        ret.remove('__init__')
    return list(sorted(ret))
