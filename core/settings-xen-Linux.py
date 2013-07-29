#!/usr/bin/python2

from __future__ import absolute_import

from qubes.storage.xen import QubesXenVmStorage

def apply(system_path, vm_files, defaults):
    defaults['storage_class'] = QubesXenVmStorage
