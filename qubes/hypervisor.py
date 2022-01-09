#
# The Qubes OS Project, https://www.qubes-os.org/
#
# Copyright (C) 2020  Jason Mehring <nrgaway@gmail.com>
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

'''Hypervisor utilities.'''

import pathlib


def hypervisor_name():
    '''Return hypervisor name.'''
    hypervisor = pathlib.Path('/sys/hypervisor/type')
    if hypervisor.exists():
        return hypervisor.read_text().strip().lower()
    if pathlib.Path('/sys/devices/virtual/misc/kvm').exists():
        return 'kvm'
    return None


def is_xen():
    '''Check if hypervisor is xen.'''
    return hypervisor_name() == 'xen'


def is_kvm():
    '''Check if hypervisor is xen.'''
    return hypervisor_name() == 'xen'
