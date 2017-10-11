#
# The Qubes OS Project, https://www.qubes-os.org/
#
# Copyright (C) 2010-2015  Joanna Rutkowska <joanna@invisiblethingslab.com>
# Copyright (C) 2014-2015  Wojtek Porczyk <woju@invisiblethingslab.com>
#
# This library is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 2.1 of the License, or (at your option) any later version.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with this library; if not, see <https://www.gnu.org/licenses/>.
#

#
# THIS FILE SHOULD BE CONFIGURED PER PRODUCT
# or better, once first custom product arrives,
# make a real /etc/qubes/master.conf or whatever
#

'''Constants which can be configured in one place'''

import os.path

qubes_base_dir = "/var/lib/qubes"
system_path = {
    'qubes_guid_path': '/usr/bin/qubes-guid',
    'qrexec_daemon_path': '/usr/lib/qubes/qrexec-daemon',
    'qrexec_client_path': '/usr/lib/qubes/qrexec-client',
    'qubesdb_daemon_path': '/usr/sbin/qubesdb-daemon',

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
}

vm_files = {
    'root_img': 'root.img',
    'rootcow_img': 'root-cow.img',
    'volatile_img': 'volatile.img',
    'clean_volatile_img': 'clean-volatile.img.tar',
    'private_img': 'private.img',
    'kernels_subdir': 'kernels',
    'firewall_conf': 'firewall.xml',
    'whitelisted_appmenus': 'whitelisted-appmenus.list',
    'updates_stat_file': 'updates.stat',
}

defaults = {
    'libvirt_uri': 'xen:///',
    'memory': 400,
    'hvm_memory': 400,
    'kernelopts': "nopat",
    'kernelopts_pcidevs': "nopat iommu=soft swiotlb=8192",

    'dom0_update_check_interval': 6*3600,

    'private_img_size': 2*1024*1024*1024,
    'root_img_size': 10*1024*1024*1024,

    'pool_configs': {
        # create file pool even when the default one is LVM
        'varlibqubes': {'dir_path': qubes_base_dir,
                    'driver': 'file',
                    'name': 'varlibqubes'},
        'linux-kernel': {
            'dir_path': os.path.join(qubes_base_dir,
                                     system_path['qubes_kernels_base_dir']),
            'driver': 'linux-kernel',
            'name': 'linux-kernel'
        }
    },

    # how long (in sec) to wait for VMs to shutdown,
    # before killing them (when used qvm-run with --wait option),
    'shutdown_counter_max': 60,

    'vm_default_netmask': "255.255.255.0",

    'appvm_label': 'red',
    'template_label': 'black',
    'servicevm_label': 'red',
}

max_qid = 254
max_netid = 254
max_dispid = 10000
#: built-in standard labels, if creating new one, allocate them above this
# number, at least until label index is removed from API
max_default_label = 8

#: profiles for admin.backup.* calls
backup_profile_dir = '/etc/qubes/backup'
