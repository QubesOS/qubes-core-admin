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
import win32netcon
import win32security
import win32profile
import pywintypes
import random

from qubes.storage import QubesVmStorage
from qubes.qubes import QubesException,system_path

class QubesWniVmStorage(QubesVmStorage):
    """
    Class for VM storage of WNI VMs.
    """

    def __init__(self, *args, **kwargs):
        super(QubesWniVmStorage, self).__init__(*args, **kwargs)
        # Use the user profile as "private.img"
        self.home_root = win32profile.GetProfilesDirectory()
        # FIXME: the assignment below may not always be correct,
        # but GetUserProfileDirectory needs a user token...
        self.private_img = os.path.join(self.home_root, self._get_username())

        # Pass paths for WNI libvirt driver
        os.putenv("WNI_DRIVER_QUBESDB_PATH", system_path['qubesdb_daemon_path'])
        os.putenv("WNI_DRIVER_QREXEC_PATH", system_path['qrexec_agent_path'])

    def _get_username(self, vmname = None):
        if vmname is None:
            vmname = self.vm.name
        return "qubes-vm-%s" % vmname

    def _get_random_password(self, vmname = None):
        if vmname is None:
            vmname = self.vm.name
        return '%x' % random.SystemRandom().getrandombits(256)

    def get_config_params(self):
        return {}

    def create_on_disk_private_img(self, verbose, source_template = None):
        # FIXME: this may not always be correct
        home_dir = os.path.join(self.home_root, self._get_username())
        # Create user data in information level 1 (PyUSER_INFO_1) format.
        user_data = {}
        user_data['name'] = self._get_username()
        user_data['full_name'] = self._get_username()
        # libvirt driver doesn't need to know the password anymore
        user_data['password'] = self._get_random_password()
        user_data['flags'] = (
                win32netcon.UF_NORMAL_ACCOUNT |
                win32netcon.UF_SCRIPT |
                win32netcon.UF_DONT_EXPIRE_PASSWD |
                win32netcon.UF_PASSWD_CANT_CHANGE
                )
        user_data['priv'] = win32netcon.USER_PRIV_USER
        user_data['home_dir'] = home_dir
        user_data['max_storage'] = win32netcon.USER_MAXSTORAGE_UNLIMITED
        # TODO: catch possible exception
        win32net.NetUserAdd(None, 1, user_data)

    def create_on_disk_root_img(self, verbose, source_template = None):
        pass

    def remove_from_disk(self):
        try:
            sid = win32security.LookupAccountName(None, self._get_username())[0]
            string_sid = win32security.ConvertSidToStringSid(sid)
            win32profile.DeleteProfile(string_sid)
            win32net.NetUserDel(None, self._get_username())
        except pywintypes.error, details:
            if details[0] == 2221:
                # "The user name cannot be found."
                raise IOError("User %s doesn't exist" % self._get_username())
            else:
                raise

        super(QubesWniVmStorage, self).remove_from_disk()

    def rename(self, old_name, new_name):
        super(QubesWniVmStorage, self).rename(old_name, new_name)
        user_data = {}
        user_data['name'] = self._get_username(new_name)
        win32net.NetUserSetInfo(None,
                self._get_username(old_name), 0, user_data)
        #TODO: rename user profile

    def verify_files(self):
        if not os.path.exists (self.vmdir):
            raise QubesException (
                    "VM directory doesn't exist: {0}".\
                            format(self.vmdir))

        try:
            # TemplateVm in WNI is quite virtual, so do not require the user
            if not self.vm.is_template():
                win32net.NetUserGetInfo(None, self._get_username(), 0)
        except pywintypes.error, details:
            if details[0] == 2221:
                # "The user name cannot be found."
                raise QubesException("User %s doesn't exist" % self._get_username())
            else:
                raise

    def reset_volatile_storage(self, verbose = False, source_template = None):
        pass

    def prepare_for_vm_startup(self, verbose = False):
        if self.vm.is_template():
            raise QubesException("Starting TemplateVM is not supported")
