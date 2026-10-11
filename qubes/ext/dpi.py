# -*- encoding: utf-8 -*-
#
# The Qubes OS Project, http://www.qubes-os.org
#
# Copyright (C) 2026 Guillaume Chinal <guiiix@invisiblethingslab.com>
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

import os
import qubes.ext
import qubes.config
import logging


class DPI(qubes.ext.Extension):
    """This extension allows manage screen DPI"""

    def _write_scale_value(self, vm, write_all=False, dpi_scale_val=None):
        logging.getLogger().info(
            f"_write_scale_value: {vm}, {write_all}, {dpi_scale_val}"
        )
        if "dom0" not in vm.app.domains:
            return

        dom0 = vm.app.domains["dom0"]
        dpi_scale = dpi_scale_val or dom0.features.get("dpi.scale")

        if dpi_scale:
            if write_all:
                for domain in vm.app.domains:
                    if domain.is_running():
                        logging.getLogger().info(
                            f"_write_scale_value: {domain}: writing /dpi/scale => {dpi_scale}"
                        )
                        domain.untrusted_qdb.write("/dpi/scale", str(dpi_scale))

            else:
                logging.getLogger().info(
                    f"_write_scale_value: {vm}: writing /dpi/scale => {dpi_scale}"
                )
                vm.untrusted_qdb.write("/dpi/scale", str(dpi_scale))

    @qubes.ext.handler("domain-qdb-create")
    def on_domain_qdb_create(self, vm, event):
        """Write the DPI value into VM DB at startup"""
        # pylint: disable=unused-argument
        self._write_scale_value(vm)

    @qubes.ext.handler("domain-feature-set:dpi.scale")
    def on_domain_feature_set(self, vm, event, feature, value, oldvalue=None):
        """Update DPI value of running VMs when the feature is updated on dom0"""
        # pylint: disable=unused-argument

        if feature == "dpi.scale" and vm.name == "dom0":
            self._write_scale_value(vm, write_all=True)

    @qubes.ext.handler("domain-feature-delete:dpi.scale")
    def on_domain_feature_delete(self, vm, event, feature):
        """Reset DPI on running VMs"""
        # pylint: disable=unused-argument
        if feature == "dpi.scale" and vm.name == "dom0":
            self._write_scale_value(vm, write_all=True, dpi_scale_val=1)
