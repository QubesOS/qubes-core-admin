#!/usr/bin/python2 -O
# -*- coding: utf-8 -*-

import imp
import inspect
import os
import sys

class Plugin(type):
    def __init__(cls, name, bases, dict_):
        if hasattr(cls, 'register'):
            cls.register[cls.__name__] = cls
        else:
            # we've got root class
            cls.register = {}

    def __getitem__(cls, name):
        return cls.register[name]

def load(modfile):
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
