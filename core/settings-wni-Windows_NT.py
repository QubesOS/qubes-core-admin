#!/usr/bin/python2

from __future__ import absolute_import
import _winreg
import os
import sys

from qubes.storage.wni import QubesWniVmStorage

DEFAULT_INSTALLDIR = 'c:\\program files\\Invisible Things Lab\\Qubes WNI'
DEFAULT_STOREDIR = 'c:\\qubes'

def apply(system_path, vm_files, defaults):
    system_path['qubes_base_dir'] = DEFAULT_STOREDIR
    installdir = DEFAULT_INSTALLDIR
    try:
        reg_key = _winreg.OpenKey(_winreg.HKEY_LOCAL_MACHINE,
                "Software\\Invisible Things Lab\\Qubes WNI")
        installdir = _winreg.QueryValueEx(reg_key, "InstallDir")[0]
        system_path['qubes_base_dir'] = \
                _winreg.QueryValueEx(reg_key, "StoreDir")[0]
    except WindowsError as e:
        print >>sys.stderr, \
                "WARNING: invalid installation: missing registry entries (%s)" \
                % str(e)

    system_path['config_template_pv'] = \
            os.path.join(installdir, 'vm-template.xml')
    system_path['config_template_hvm'] = \
            os.path.join(installdir, 'vm-template-hvm.xml')
    system_path['qubes_icon_dir'] = os.path.join(installdir, 'icons')
    system_path['qubesdb_daemon_path'] = \
            os.path.join(installdir, 'bin\\qubesdb-daemon.exe')
    system_path['qrexec_daemon_path'] = \
            os.path.join(installdir, 'bin\\qrexec-daemon.exe')
    system_path['qrexec_client_path'] = \
            os.path.join(installdir, 'bin\\qrexec-client.exe')
    system_path['qrexec_policy_dir'] = \
            os.path.join(installdir, 'qubes-rpc\\policy')
    # Specific to WNI - normally VM have this file
    system_path['qrexec_agent_path'] = \
            os.path.join(installdir, 'bin\\qrexec-agent.exe')

    defaults['libvirt_uri'] = 'wni:///'
    defaults['storage_class'] = QubesWniVmStorage
