#!/usr/bin/python2
# -*- encoding: utf8 -*-
#
# The Qubes OS Project, http://www.qubes-os.org
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

from __future__ import (
    absolute_import,
    division,
    print_function,
    unicode_literals,
)

from qubes.qubes import (
    register_qubes_vm_class,
    QubesException,
    QubesVm,
)


class QubesResizableVm(QubesVm):

    def resize_root_img(self, size):
        if self.template:
            raise QubesException("Cannot resize root.img of template-based VM"
                                 ". Resize the root.img of the template "
                                 "instead.")

        if self.is_running():
            raise QubesException("Cannot resize root.img of running VM")

        if size < self.get_root_img_sz():
            raise QubesException(
                "For your own safety shringing of root.img is disabled. If "
                "you really know what you are doing, use 'truncate' manually.")

        f_root = open(self.root_img, "a+b")
        f_root.truncate(size)
        f_root.close()


class QubesResizableVmWithResize2fs(QubesResizableVm):

    def resize_root_img(self, size):
        super(QubesResizableVmWithResize2fs, self).resize_root_img(size)
        self.start(start_guid=False)
        self.run("resize2fs /dev/mapper/dmroot", user="root", wait=True,
                 gui=False)
        self.shutdown()


register_qubes_vm_class(QubesResizableVm)
register_qubes_vm_class(QubesResizableVmWithResize2fs)
