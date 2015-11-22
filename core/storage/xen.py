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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301,
# USA.
#

from __future__ import absolute_import

import os
import os.path
import re
import subprocess
import sys

from qubes.qubes import QubesException, vm_files
from qubes.storage import Pool, QubesVmStorage


class XenStorage(QubesVmStorage):
    """
    Class for VM storage of Xen VMs.
    """

    def __init__(self, vm, vmdir, **kwargs):
        """ Instantiate the storage.

            Args:
                vm: a QubesVM
                vmdir: the root directory of the pool
        """
        assert vm is not None
        assert vmdir is not None

        super(XenStorage, self).__init__(vm, **kwargs)

        self.vmdir = vmdir

        if self.vm.is_template():
            self.rootcow_img = os.path.join(self.vmdir,
                                            vm_files["rootcow_img"])
        else:
            self.rootcow_img = None

        self.private_img = os.path.join(vmdir, 'private.img')
        if self.vm.template:
            self.root_img = self.vm.template.root_img
        else:
            self.root_img = os.path.join(vmdir, 'root.img')
        self.volatile_img = os.path.join(vmdir, 'volatile.img')

    def root_dev_config(self):
        if self.vm.is_template() and \
                os.path.exists(os.path.join(self.vmdir, "root-cow.img")):
            return self.format_disk_dev(
                    "{dir}/root.img:{dir}/root-cow.img".format(
                        dir=self.vmdir),
                    "block-origin", self.root_dev, True)
        elif self.vm.template and not self.vm.template.storage.rootcow_img:
            # HVM template-based VM - template doesn't have own
            # root-cow.img, only one device-mapper layer
            return self.format_disk_dev(
                    "{tpldir}/root.img:{vmdir}/volatile.img".format(
                        tpldir=self.vm.template.dir_path,
                        vmdir=self.vmdir),
                    "block-snapshot", self.root_dev, True)
        elif self.vm.template:
            # any other template-based VM - two device-mapper layers: one
            # in dom0 (here) from root+root-cow, and another one from
            # this+volatile.img
            return self.format_disk_dev(
                    "{dir}/root.img:{dir}/root-cow.img".format(
                        dir=self.vm.template.dir_path),
                    "block-snapshot", self.root_dev, False)
        else:
            return self.format_disk_dev(
                    "{dir}/root.img".format(dir=self.vmdir),
                    None, self.root_dev, True)

    def private_dev_config(self):
        return self.format_disk_dev(self.private_img, None,
                                    self.private_dev, True)

    def volatile_dev_config(self):
        return self.format_disk_dev(self.volatile_img, None,
                                    self.volatile_dev, True)

    def create_on_disk_private_img(self, verbose, source_template = None):
        if source_template:
            template_priv = source_template.private_img
            if verbose:
                print >> sys.stderr, "--> Copying the template's private image: {0}".\
                        format(template_priv)
            self._copy_file(template_priv, self.private_img)
        else:
            f_private = open (self.private_img, "a+b")
            f_private.truncate (self.private_img_size)
            f_private.close ()

    def create_on_disk_root_img(self, verbose, source_template = None):
        if source_template:
            if not self.vm.updateable:
                # just use template's disk
                return
            else:
                template_root = source_template.root_img
                if verbose:
                    print >> sys.stderr, "--> Copying the template's root image: {0}".\
                            format(template_root)

                self._copy_file(template_root, self.root_img)
        else:
            f_root = open (self.root_img, "a+b")
            f_root.truncate (self.root_img_size)
            f_root.close ()
        if self.vm.is_template():
            self.commit_template_changes()

    def rename(self, old_name, new_name):
        super(XenStorage, self).rename(old_name, new_name)

        old_dirpath = os.path.join(os.path.dirname(self.vmdir), old_name)
        if self.rootcow_img:
            self.rootcow_img = self.rootcow_img.replace(old_dirpath,
                                                        self.vmdir)

    def resize_private_img(self, size):
        f_private = open (self.private_img, "a+b")
        f_private.truncate (size)
        f_private.close ()

        # find loop device if any
        p = subprocess.Popen (["sudo", "losetup", "--associated", self.private_img],
                stdout=subprocess.PIPE)
        result = p.communicate()
        m = re.match(r"^(/dev/loop\d+):\s", result[0])
        if m is not None:
            loop_dev = m.group(1)

            # resize loop device
            subprocess.check_call(["sudo", "losetup", "--set-capacity", loop_dev])

    def commit_template_changes(self):
        assert self.vm.is_template()
        if not self.rootcow_img:
            return
        if os.path.exists (self.rootcow_img):
           os.rename (self.rootcow_img, self.rootcow_img + '.old')

        old_umask = os.umask(002)
        f_cow = open (self.rootcow_img, "w")
        f_root = open (self.root_img, "r")
        f_root.seek(0, os.SEEK_END)
        f_cow.truncate (f_root.tell()) # make empty sparse file of the same size as root.img
        f_cow.close ()
        f_root.close()
        os.umask(old_umask)

    def reset_volatile_storage(self, verbose = False, source_template = None):
        if source_template is None:
            source_template = self.vm.template

        if source_template is not None:
            # template-based VM with only one device-mapper layer -
            # volatile.img used as upper layer on root.img, no root-cow.img
            # intermediate layer
            if not source_template.storage.rootcow_img:
                if os.path.exists(self.volatile_img):
                    if self.vm.debug:
                        if os.path.getmtime(source_template.storage.root_img)\
                                > os.path.getmtime(self.volatile_img):
                            if verbose:
                                print >>sys.stderr, "--> WARNING: template have changed, resetting root.img"
                        else:
                            if verbose:
                                print >>sys.stderr, "--> Debug mode: not resetting root.img"
                                print >>sys.stderr, "--> Debug mode: if you want to force root.img reset, either update template VM, or remove volatile.img file"
                            return
                    os.remove(self.volatile_img)

                f_volatile = open(self.volatile_img, "w")
                f_root = open(source_template.storage.root_img, "r")
                f_root.seek(0, os.SEEK_END)
                f_volatile.truncate(f_root.tell()) # make empty sparse file of the same size as root.img
                f_volatile.close()
                f_root.close()
                return
        super(XenStorage, self).reset_volatile_storage(
            verbose=verbose, source_template=source_template)

    def prepare_for_vm_startup(self, verbose):
        super(XenStorage, self).prepare_for_vm_startup(verbose=verbose)

        if self.drive is not None:
            (drive_type, drive_domain, drive_path) = self.drive.split(":")
            if drive_domain.lower() != "dom0":
                try:
                    # FIXME: find a better way to access QubesVmCollection
                    drive_vm = self.vm._collection.get_vm_by_name(drive_domain)
                    # prepare for improved QubesVmCollection
                    if drive_vm is None:
                        raise KeyError
                    if not drive_vm.is_running():
                        raise QubesException(
                            "VM '{}' holding '{}' isn't running".format(
                                drive_domain, drive_path))
                except KeyError:
                    raise QubesException(
                        "VM '{}' holding '{}' does not exists".format(
                            drive_domain, drive_path))


class XenPool(Pool):

    def __init__(self, vm, dir_path):
        super(XenPool, self).__init__(vm, dir_path)

    def getStorage(self):
        """ Returns an instantiated ``XenStorage``. """
        return XenStorage(self.vm, vmdir=self.vmdir)
