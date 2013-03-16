#!/usr/bin/python2
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

from qubes.qubes import QubesVm,QubesVmLabel,register_qubes_vm_class

class QubesAppVm(QubesVm):
    """
    A class that represents an AppVM. A child of QubesVm.
    """
    def _get_attrs_config(self):
        attrs_config = super(QubesAppVm, self)._get_attrs_config()
        attrs_config['dir_path']['eval'] = 'value if value is not None else os.path.join(system_path["qubes_appvms_dir"], self.name)'

        return attrs_config

    @property
    def type(self):
        return "AppVM"

    def is_appvm(self):
        return True

    def create_on_disk(self, verbose, source_template = None):
        if dry_run:
            return

        super(QubesAppVm, self).create_on_disk(verbose, source_template=source_template)

        if not self.internal:
            self.create_appmenus (verbose=verbose, source_template=source_template)

    def remove_from_disk(self):
        if dry_run:
            return

        self.remove_appmenus()
        super(QubesAppVm, self).remove_from_disk()

register_qubes_vm_class(QubesAppVm)
