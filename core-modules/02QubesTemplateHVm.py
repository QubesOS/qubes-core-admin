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
import os.path
import subprocess
import stat
import sys
import re

from qubes.qubes import QubesHVm,register_qubes_vm_class,dry_run,vmm
from qubes.qubes import QubesException,QubesVmCollection
from qubes.qubes import system_path,defaults

class QubesTemplateHVm(QubesHVm):
    """
    A class that represents an HVM template. A child of QubesHVm.
    """

    # In which order load this VM type from qubes.xml
    load_order = 50

    def get_attrs_config(self):
        attrs_config = super(QubesTemplateHVm, self).get_attrs_config()
        attrs_config['dir_path']['func'] = \
            lambda value: value if value is not None else \
                os.path.join(system_path["qubes_templates_dir"], self.name)
        attrs_config['label']['default'] = defaults["template_label"]
        return attrs_config


    def __init__(self, **kwargs):

        super(QubesTemplateHVm, self).__init__(**kwargs)

        self.appvms = QubesVmCollection()

    @property
    def type(self):
        return "TemplateHVM"

    @property
    def updateable(self):
        return True

    def is_template(self):
        return True

    def is_appvm(self):
        return False

    @property
    def rootcow_img(self):
        return self.storage.rootcow_img

    @classmethod
    def is_template_compatible(cls, template):
        if template is None:
            return True
        return False

    def resize_root_img(self, size):
        for vm in self.appvms.values():
            if vm.is_running():
                raise QubesException("Cannot resize root.img while any VM "
                                     "based on this tempate is running")
        return super(QubesTemplateHVm, self).resize_root_img(size)

    def start(self, *args, **kwargs):
        for vm in self.appvms.values():
            if vm.is_running():
                raise QubesException("Cannot start HVM template while VMs based on it are running")
        return super(QubesTemplateHVm, self).start(*args, **kwargs)

    def commit_changes (self, verbose = False):
        self.log.debug('commit_changes()')

        if not vmm.offline_mode:
            assert not self.is_running(), "Attempt to commit changes on running Template VM!"

        if verbose:
            print >> sys.stderr, "--> Commiting template updates... COW: {0}...".format (self.rootcow_img)

        if dry_run:
            return

        self.storage.commit_template_changes()

register_qubes_vm_class(QubesTemplateHVm)
