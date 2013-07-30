#!/usr/bin/python2
#
# The Qubes OS Project, http://www.qubes-os.org
#
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

from __future__ import absolute_import

import sys
import os
import os.path
import win32api
import win32net
import pywintypes

from qubes.storage import QubesVmStorage
from qubes.qubes import QubesException

class QubesWniVmStorage(QubesVmStorage):
    """
    Class for VM storage of WNI VMs.
    """

    def __init__(self, vm, **kwargs):
        super(QubesWniVmStorage, self).__init__(vm, **kwargs)
        # Use the user profile as "private.img"
        self.private_img = os.path.join("c:\\Users", self.vm.name)

    def get_config_params(self):
        return {}

    def create_on_disk_private_img(self, verbose, source_template = None):
        win32api.ShellExecute(None, "runas",
                "net", "user %s %s /ADD" % (self.vm.name, "testpass"),
                None, 0)

    def create_on_disk_root_img(self, verbose, source_template = None):
        pass

    def remove_from_disk(self):
        win32api.ShellExecute(None, "runas",
                "net", "user %s /DELETE" % (self.vm.name),
                None, 0)
        super(QubesWniVmStorage, self).remove_from_disk()

    def verify_files(self):
        if not os.path.exists (self.vmdir):
            raise QubesException (
                    "VM directory doesn't exist: {0}".\
                            format(self.vmdir))

        try:
            # TemplateVm in WNI is quite virtual, so do not require the user
            if not self.vm.is_template():
                win32net.NetUserGetInfo(None, self.vm.name, 0)
        except pywintypes.error, details:
            if details[0] == 2221:
                # "The user name cannot be found."
                raise QubesException("User %s doesn't exist" % self.vm.name)
            else:
                raise

    def reset_volatile_storage(self, verbose = False, source_template = None):
        pass

    def prepare_for_vm_startup(self):
        if self.vm.is_template():
            raise QubesException("Starting TemplateVM is not supported")
