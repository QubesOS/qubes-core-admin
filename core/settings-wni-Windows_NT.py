#!/usr/bin/python2

from __future__ import absolute_import

from qubes.storage.wni import QubesWniVmStorage

def apply(system_path, vm_files, defaults):
    system_path['qubes_base_dir'] = 'c:\\qubes'
    system_path['config_template_pv'] = 'c:/program files/Invisible Things Lab/Qubes/vm-template.xml'
    system_path['config_template_hvm'] = 'c:/program files/Invisible Things Lab/Qubes/vm-template-hvm.xml'
    defaults['libvirt_uri'] = 'test:///default'
    defaults['storage_class'] = QubesWniVmStorage
