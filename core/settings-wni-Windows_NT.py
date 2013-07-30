#!/usr/bin/python2

from __future__ import absolute_import

from qubes.storage.wni import QubesWniVmStorage

def apply(system_path, vm_files, defaults):
    system_path['qubes_base_dir'] = 'c:\\qubes'
    defaults['libvirt_uri'] = 'test:///default'
    defaults['storage_class'] = QubesWniVmStorage
