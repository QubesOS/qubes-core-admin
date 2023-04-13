# -*- encoding: utf-8 -*-
#
# The Qubes OS Project, http://www.qubes-os.org
#
# Copyright (C) 2017 Marek Marczykowski-Górecki
#                               <marmarek@invisiblethingslab.com>
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

"""Extension exposing vm-config features to QubesDB"""

import qubes.ext
import qubes.config

PREFIX = 'vm-config.'


class VMConfig(qubes.ext.Extension):
    """This extension export features with 'vm-config.' prefix to QubesDB in
    /vm-config/ tree.
    """

    @qubes.ext.handler('domain-qdb-create')
    def on_domain_qdb_create(self, vm, event):
        """Actually export features"""
        # pylint: disable=unused-argument
        for feature, value in vm.features.items():
            if not feature.startswith(PREFIX):
                continue
            config = feature[len(PREFIX):]

            vm.untrusted_qdb.write('/vm-config/{}'.format(config),
                                   str(value))

    @qubes.ext.handler('domain-feature-set:*')
    def on_domain_feature_set(self, vm, event, feature, value, oldvalue=None):
        """Update /vm-config/ QubesDB tree in runtime"""
        # pylint: disable=unused-argument

        if not feature.startswith(PREFIX):
            return
        config = feature[len(PREFIX):]
        # qubesdb keys are limited to 63 bytes, and "/vm-config/" is
        # 11 bytes.  That leaves 52 for the config name.
        if len(config) > 52:
            raise qubes.exc.QubesValueError(
                    'VM config name must not exceed 46 bytes')
        # The empty string is not a valid file name.
        if not config:
            raise qubes.exc.QubesValueError('Empty config name not allowed')
        # Require config names to start with an ASCII letter.  This implicitly
        # rejects names which start with '-' (which could be interpreted as an
        # option) or are '.' or '..'.
        if not (('a' <= config[0] <= 'z') or ('A' <= config[0] <= 'Z')):
            raise qubes.exc.QubesValueError(
                    'Config name must start with an ASCII letter')

        if not vm.is_running():
            return

        vm.untrusted_qdb.write('/vm-config/' + config,
                               str(value))

    @qubes.ext.handler('domain-feature-delete:*')
    def on_domain_feature_delete(self, vm, event, feature):
        """Update /vm-config/ QubesDB tree in runtime"""
        # pylint: disable=unused-argument
        if not vm.is_running():
            return
        if not feature.startswith(PREFIX):
            return
        config = feature[len(PREFIX):]

        vm.untrusted_qdb.rm('/vm-config/{}'.format(config))
