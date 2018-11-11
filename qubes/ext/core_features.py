# -*- encoding: utf8 -*-
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
import asyncio

import qubes.ext

class CoreFeatures(qubes.ext.Extension):
    # pylint: disable=too-few-public-methods
    @qubes.ext.handler('features-request')
    @asyncio.coroutine
    def qubes_features_request(self, vm, event, untrusted_features):
        '''Handle features provided by qubes-core-agent and qubes-gui-agent'''
        # pylint: disable=no-self-use,unused-argument
        if getattr(vm, 'template', None):
            vm.log.warning(
                'Ignoring qubes.NotifyTools for template-based VM')
            return

        requested_features = {}
        for feature in ('qrexec', 'gui', 'gui-emulated', 'qubes-firewall'):
            untrusted_value = untrusted_features.get(feature, None)
            if untrusted_value in ('1', '0'):
                requested_features[feature] = bool(int(untrusted_value))
        del untrusted_features

        # default user for qvm-run etc
        # starting with Qubes 4.x ignored
        # qrexec agent presence (0 or 1)
        # gui agent presence (0 or 1)

        qrexec_before = vm.features.get('qrexec', False)
        for feature in ('qrexec', 'gui', 'gui-emulated'):
            # do not allow (Template)VM to override setting if already set
            # some other way
            if feature in requested_features and feature not in vm.features:
                vm.features[feature] = requested_features[feature]

        # those features can be freely enabled or disabled by template
        for feature in ('qubes-firewall',):
            if feature in requested_features:
                vm.features[feature] = requested_features[feature]

        if not qrexec_before and vm.features.get('qrexec', False):
            # if this is the first time qrexec was advertised, now can finish
            #  template setup
            yield from vm.fire_event_async('template-postinstall')
