#!/usr/bin/python2
# -*- coding: utf-8 -*-
#
# The Qubes OS Project, http://www.qubes-os.org
#
# Copyright (C) 2010  Joanna Rutkowska <joanna@invisiblethingslab.com>
# Copyright (C) 2013  Marek Marczykowski <marmarek@invisiblethingslab.com>
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

import os.path

from qubes.qubes import (
    register_qubes_vm_class,
    system_path,
    QubesResizableVmWithResize2fs,
    QubesVmLabel,
)


class QubesAppVm(QubesResizableVmWithResize2fs):
    """
    A class that represents an AppVM. A child of QubesVm.
    """
    def get_attrs_config(self):
        attrs_config = super(QubesAppVm, self).get_attrs_config()
        attrs_config['dir_path']['func'] = \
            lambda value: value if value is not None else \
                os.path.join(system_path["qubes_appvms_dir"], self.name)

        return attrs_config

    @property
    def type(self):
        return "AppVM"

    def is_appvm(self):
        return True

register_qubes_vm_class(QubesAppVm)
