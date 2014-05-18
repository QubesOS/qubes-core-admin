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

import sys
from qubes.qubes import QubesVm,QubesVmLabel,register_qubes_vm_class
from qubes.qubes import QubesDispVmLabels

class QubesDisposableVm(QubesVm):
    """
    A class that represents an DisposableVM. A child of QubesVm.
    """

    # In which order load this VM type from qubes.xml
    load_order = 120

    def get_attrs_config(self):
        attrs_config = super(QubesDisposableVm, self).get_attrs_config()

        # New attributes
        attrs_config['dispid'] = { 'save': lambda: str(self.dispid) }
        attrs_config['include_in_backups']['func'] = lambda x: False

        return attrs_config

    def __init__(self, **kwargs):

        super(QubesDisposableVm, self).__init__(dir_path="/nonexistent", **kwargs)

        assert self.template is not None, "Missing template for DisposableVM!"

        # Use DispVM icon with the same color
        if self._label:
            self._label = QubesDispVmLabels[self._label.name]
            self.icon_path = self._label.icon_path

    @property
    def type(self):
        return "DisposableVM"

    def is_disposablevm(self):
        return True

    @property
    def ip(self):
        if self.netvm is not None:
            return self.netvm.get_ip_for_dispvm(self.dispid)
        else:
            return None


    def get_xml_attrs(self):
        # Minimal set - do not inherit rest of attributes
        attrs = {}
        attrs["qid"] = str(self.qid)
        attrs["name"] = self.name
        attrs["dispid"] = str(self.dispid)
        attrs["template_qid"] = str(self.template.qid)
        attrs["label"] = self.label.name
        attrs["firewall_conf"] = self.relative_path(self.firewall_conf)
        attrs["netvm_qid"] = str(self.netvm.qid) if self.netvm is not None else "none"
        return attrs

    def verify_files(self):
        return True

# register classes
register_qubes_vm_class(QubesDisposableVm)
