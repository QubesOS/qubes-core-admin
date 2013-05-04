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

import os
import subprocess
import sys

from qubes.qubes import QubesVm,register_qubes_vm_class,dry_run
from qubes.qubes import QubesVmCollection,QubesException,QubesVmLabels
from qubes.qubes import defaults,system_path,vm_files

class QubesTemplateVm(QubesVm):
    """
    A class that represents an TemplateVM. A child of QubesVm.
    """

    # In which order load this VM type from qubes.xml
    load_order = 50

    def get_attrs_config(self):
        attrs_config = super(QubesTemplateVm, self).get_attrs_config()
        attrs_config['dir_path']['func'] = \
            lambda value: value if value is not None else \
                os.path.join(system_path["qubes_templates_dir"], self.name)
        attrs_config['label']['default'] = defaults["template_label"]

        # New attributes

        # Image for template changes
        attrs_config['rootcow_img'] = {
            'func': lambda x: os.path.join(self.dir_path, vm_files["rootcow_img"]) }
        # Clean image for root-cow and swap (AppVM side)
        attrs_config['clean_volatile_img'] = {
            'func': lambda x: os.path.join(self.dir_path, vm_files["clean_volatile_img"]) }

        return attrs_config

    def __init__(self, **kwargs):

        super(QubesTemplateVm, self).__init__(**kwargs)

        self.appvms = QubesVmCollection()

    @property
    def type(self):
        return "TemplateVM"

    @property
    def updateable(self):
        return True

    def is_template(self):
        return True

    def get_firewall_defaults(self):
        return { "rules": list(), "allow": False, "allowDns": False, "allowIcmp": False, "allowYumProxy": True }

    # FIXME: source_template unused
    def get_rootdev(self, source_template=None):
        return self._format_disk_dev(
                "{dir}/root.img:{dir}/root-cow.img".format(
                    dir=self.dir_path),
                "block-origin", "xvda", True)

    def clone_disk_files(self, src_vm, verbose):
        if dry_run:
            return

        super(QubesTemplateVm, self).clone_disk_files(src_vm=src_vm, verbose=verbose)

        if verbose:
            print >> sys.stderr, "--> Copying the template's clean volatile image:\n{0} ==>\n{1}".\
                    format(src_vm.clean_volatile_img, self.clean_volatile_img)
        # We prefer to use Linux's cp, because it nicely handles sparse files
        retcode = subprocess.call (["cp", src_vm.clean_volatile_img, self.clean_volatile_img])
        if retcode != 0:
            raise IOError ("Error while copying {0} to {1}".\
                           format(src_vm.clean_volatile_img, self.clean_volatile_img))
        if verbose:
            print >> sys.stderr, "--> Copying the template's volatile image:\n{0} ==>\n{1}".\
                    format(self.clean_volatile_img, self.volatile_img)
        # We prefer to use Linux's cp, because it nicely handles sparse files
        retcode = subprocess.call (["cp", self.clean_volatile_img, self.volatile_img])
        if retcode != 0:
            raise IOError ("Error while copying {0} to {1}".\
                           format(self.clean_img, self.volatile_img))

        # Create root-cow.img
        self.commit_changes(verbose=verbose)

    def post_rename(self, old_name):
        super(QubesTemplateVm, self).post_rename(old_name)

        old_dirpath = os.path.join(os.path.dirname(self.dir_path), old_name)
        self.clean_volatile_img = self.clean_volatile_img.replace(old_dirpath, self.dir_path)
        self.rootcow_img = self.rootcow_img.replace(old_dirpath, self.dir_path)

    def verify_files(self):
        if dry_run:
            return

        super(QubesTemplateVm, self).verify_files()

        if not os.path.exists (self.volatile_img):
            raise QubesException (
                "VM volatile image file doesn't exist: {0}".\
                format(self.volatile_img))

        if not os.path.exists (self.clean_volatile_img):
            raise QubesException (
                "Clean VM volatile image file doesn't exist: {0}".\
                format(self.clean_volatile_img))

        return True

    def reset_volatile_storage(self, verbose = False):
        assert not self.is_running(), "Attempt to clean volatile image of running Template VM!"

        if verbose:
            print >> sys.stderr, "--> Cleaning volatile image: {0}...".format (self.volatile_img)
        if dry_run:
            return
        if os.path.exists (self.volatile_img):
           os.remove (self.volatile_img)

        retcode = subprocess.call (["tar", "xf", self.clean_volatile_img, "-C", self.dir_path])
        if retcode != 0:
            raise IOError ("Error while unpacking {0} to {1}".\
                           format(self.template.clean_volatile_img, self.volatile_img))

    def commit_changes (self, verbose = False):

        assert not self.is_running(), "Attempt to commit changes on running Template VM!"

        if verbose:
            print >> sys.stderr, "--> Commiting template updates... COW: {0}...".format (self.rootcow_img)

        if dry_run:
            return
        if os.path.exists (self.rootcow_img):
           os.rename (self.rootcow_img, self.rootcow_img + '.old')

        f_cow = open (self.rootcow_img, "w")
        f_root = open (self.root_img, "r")
        f_root.seek(0, os.SEEK_END)
        f_cow.truncate (f_root.tell()) # make empty sparse file of the same size as root.img
        f_cow.close ()
        f_root.close()

register_qubes_vm_class(QubesTemplateVm)
