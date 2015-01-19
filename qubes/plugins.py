#!/usr/bin/python2 -O
# vim: fileencoding=utf-8

#
# The Qubes OS Project, https://www.qubes-os.org/
#
# Copyright (C) 2014-2015  Joanna Rutkowska <joanna@invisiblethingslab.com>
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
