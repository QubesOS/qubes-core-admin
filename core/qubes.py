#!/usr/bin/python2
# -*- coding: utf-8 -*-
#
# The Qubes OS Project, http://www.qubes-os.org
#
# Copyright (C) 2010  Joanna Rutkowska <joanna@invisiblethingslab.com>
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.
#
#


qubes_base_dir   = "/var/lib/qubes"
system_path = {
    'qubes_guid_path': '/usr/bin/qubes-guid',
    'qrexec_daemon_path': '/usr/lib/qubes/qrexec-daemon',
    'qrexec_client_path': '/usr/lib/qubes/qrexec-client',
    'qubesdb_daemon_path': '/usr/sbin/qubesdb-daemon',

    'qubes_base_dir': qubes_base_dir,

    # Relative to qubes_base_dir
    'qubes_appvms_dir': 'appvms',
    'qubes_templates_dir': 'vm-templates',
    'qubes_servicevms_dir': 'servicevms',
    'qubes_store_filename': 'qubes.xml',
    'qubes_kernels_base_dir': 'vm-kernels',

    # qubes_icon_dir is obsolete
    # use QIcon.fromTheme() where applicable
    'qubes_icon_dir': '/usr/share/icons/hicolor/128x128/devices',

    'qrexec_policy_dir': '/etc/qubes-rpc/policy',

    'config_template_pv': '/usr/share/qubes/vm-template.xml',

    'qubes_pciback_cmd': '/usr/lib/qubes/unbind-pci-device.sh',
    'prepare_volatile_img_cmd': '/usr/lib/qubes/prepare-volatile-img.sh',
}

vm_files = {
    'root_img': 'root.img',
    'rootcow_img': 'root-cow.img',
    'volatile_img': 'volatile.img',
    'private_img': 'private.img',
    'kernels_subdir': 'kernels',
    'firewall_conf': 'firewall.xml',
    'whitelisted_appmenus': 'whitelisted-appmenus.list',
    'updates_stat_file': 'updates.stat',
}

defaults = {
    'libvirt_uri': 'xen:///',
    'memory': 400,
    'kernelopts': "nopat",
    'kernelopts_pcidevs': "nopat iommu=soft swiotlb=8192",

    'dom0_update_check_interval': 6*3600,

    'private_img_size': 2*1024*1024*1024,
    'root_img_size': 10*1024*1024*1024,

    'storage_class': None,

    # how long (in sec) to wait for VMs to shutdown,
    # before killing them (when used qvm-run with --wait option),
    'shutdown_counter_max': 60,

    'vm_default_netmask': "255.255.255.0",

    # Set later
    'appvm_label': None,
    'template_label': None,
    'servicevm_label': None,
}

qubes_max_qid = 254
qubes_max_netid = 254

##########################################


def register_qubes_vm_class(vm_class):
    QubesVmClasses[vm_class.__name__] = vm_class
    # register class as local for this module - to make it easy to import from
    # other modules
    setattr(sys.modules[__name__], vm_class.__name__, vm_class)


class QubesDaemonPidfile(object):
    def __init__(self, name):
        self.name = name
        self.path = "/var/run/qubes/" + name + ".pid"

    def create_pidfile(self):
        f = open (self.path, 'w')
        f.write(str(os.getpid()))
        f.close()

    def pidfile_exists(self):
        return os.path.exists(self.path)

    def read_pid(self):
        f = open (self.path)
        pid = f.read ().strip()
        f.close()
        return int(pid)

    def pidfile_is_stale(self):
        if not self.pidfile_exists():
            return False

        # check if the pid file is valid...
        proc_path = "/proc/" + str(self.read_pid()) + "/cmdline"
        if not os.path.exists (proc_path):
            print >> sys.stderr, \
                "Path {0} doesn't exist, assuming stale pidfile.".\
                    format(proc_path)
            return True

        return False # It's a good pidfile

    def remove_pidfile(self):
        os.remove (self.path)

    def __enter__ (self):
        # assumes the pidfile doesn't exist -- you should ensure it before opening the context
        self.create_pidfile()

    def __exit__ (self, exc_type, exc_val, exc_tb):
        self.remove_pidfile()
        return False

### Initialization code

defaults["appvm_label"] = QubesVmLabels["red"]
defaults["template_label"] = QubesVmLabels["black"]
defaults["servicevm_label"] = QubesVmLabels["red"]


QubesVmClasses = {}
modules_dir = os.path.join(os.path.dirname(__file__), 'modules')
for module_file in sorted(os.listdir(modules_dir)):
    if not module_file.endswith(".py") or module_file == "__init__.py":
        continue
    __import__('qubes.modules.%s' % module_file[:-3])

try:
    import qubes.settings
    qubes.settings.apply(system_path, vm_files, defaults)
except ImportError:
    pass

for path_key in system_path.keys():
    if not os.path.isabs(system_path[path_key]):
        system_path[path_key] = os.path.join(
            system_path['qubes_base_dir'], system_path[path_key])

# vim:sw=4:et:
