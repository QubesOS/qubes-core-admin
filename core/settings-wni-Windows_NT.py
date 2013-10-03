#!/usr/bin/python2

from __future__ import absolute_import

from qubes.storage.wni import QubesWniVmStorage

def apply(system_path, vm_files, defaults):
    system_path['qubes_base_dir'] = 'c:\\qubes'
    system_path['config_template_pv'] = 'c:/program files/Invisible Things Lab/Qubes/vm-template.xml'
    system_path['config_template_hvm'] = 'c:/program files/Invisible Things Lab/Qubes/vm-template-hvm.xml'
    system_path['qubes_icon_dir'] = \
            'c:/program files/Invisible Things Lab/Qubes/icons'
    system_path['qubesdb_daemon_path'] = \
            'c:/program files/Invisible Things Lab/Qubes/bin/qubesdb-daemon.exe'
    system_path['qrexec_daemon_path'] = \
            'c:/program files/Invisible Things Lab/Qubes/bin/qrexec-daemon.exe'
    system_path['qrexec_client_path'] = \
            'c:/program files/Invisible Things Lab/Qubes/bin/qrexec-client.exe'
    # Specific to WNI - normally VM have this file
    system_path['qrexec_agent_path'] = \
            'c:/program files/Invisible Things Lab/Qubes/bin/qrexec-agent.exe'

    defaults['libvirt_uri'] = 'wni:///'
    defaults['storage_class'] = QubesWniVmStorage
