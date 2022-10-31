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
    'qrexec_daemon_path': '/usr/sbin/qrexec-daemon',
    'qrexec_client_path': '/usr/bin/qrexec-client',
    'qrexec_rpc_multiplexer': '/usr/lib/qubes/qubes-rpc-multiplexer',
    'qubesdb_daemon_path': '/usr/sbin/qubesdb-daemon',

    # Relative to qubes_base_dir
    'qubes_appvms_dir': 'appvms',
    'qubes_templates_dir': 'vm-templates',
    'qubes_store_filename': 'qubes.xml',
    'qubes_kernels_base_dir': 'vm-kernels',

    # qubes_icon_dir is obsolete
    # use QIcon.fromTheme() where applicable
    'qubes_icon_dir': '/usr/share/icons/hicolor/128x128/devices',

    'dom0_services_dir': '/var/run/qubes-service',
}

defaults = {
    'libvirt_uri': 'xen:///',
    'memory': 400,
    'hvm_memory': 400,
    'kernelopts': "swiotlb=2048",
    'kernelopts_pcidevs': "",
    'kernelopts_common': ('root=/dev/mapper/dmroot ro nomodeset console=hvc0 '
             'rd_NO_PLYMOUTH rd.plymouth.enable=0 plymouth.enable=0 '),

    'private_img_size': 2*1024*1024*1024,
    'root_img_size': 10*1024*1024*1024,

    'pool_configs': {
        # create file(-reflink) pool even when the default one is LVM
        'varlibqubes': {
            'dir_path': qubes_base_dir,
            'name': 'varlibqubes'
        },
        'linux-kernel': {
            'dir_path': os.path.join(qubes_base_dir,
                                     system_path['qubes_kernels_base_dir']),
            'driver': 'linux-kernel',
            'name': 'linux-kernel'
        }
    },
}

max_qid = 254
max_dispid = 10000

#: built-in standard labels, if creating new one, allocate them above this
# number, at least until label index is removed from API
max_default_label = 8

#: profiles for admin.backup.* calls
backup_profile_dir = '/etc/qubes/backup'

#: site-local prefix for all VMs
qubes_ipv6_prefix = 'fd09:24ef:4179:0000'

suspend_timeout = 60
