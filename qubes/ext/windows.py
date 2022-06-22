# -*- encoding: utf-8 -*-
#
# The Qubes OS Project, http://www.qubes-os.org
#
# Copyright (C) 2017 Marek Marczykowski-Górecki
#                               <marmarek@invisiblethingslab.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, see <http://www.gnu.org/licenses/>.

import qubes.ext
import qubes.utils

class WindowsFeatures(qubes.ext.Extension):
    # pylint: disable=too-few-public-methods
    @qubes.ext.handler('features-request')
    def qubes_features_request(self, vm, event, untrusted_features):
        '''Handle features provided requested by Qubes Windows Tools'''
        # pylint: disable=unused-argument
        if getattr(vm, 'template', None):
            vm.log.warning(
                'Ignoring qubes.NotifyTools for template-based VM')
            return

        guest_os = None
        if 'os' in untrusted_features:
            if untrusted_features['os'] in ['Windows', 'Linux']:
                guest_os = untrusted_features['os']

        qrexec = None
        if 'qrexec' in untrusted_features:
            if untrusted_features['qrexec'] == '1':
                # qrexec feature is set by CoreFeatures extension
                qrexec = True

        del untrusted_features

        if guest_os:
            vm.features['os'] = guest_os
        if guest_os == 'Windows' and qrexec:
            vm.features['rpc-clipboard'] = True
            setattr(vm, 'maxmem', 0)
            setattr(vm, 'qrexec_timeout', 6000)
            if vm.features.check_with_template('stubdom-qrexec', None) is None:
                vm.features['stubdom-qrexec'] = True
            if vm.features.check_with_template('audio-model', None) is None:
                vm.features['audio-model'] = 'ich6'
            if vm.features.check_with_template('timezone', None) is None:
                vm.features['timezone'] = 'localtime'
            if vm.features.check_with_template('no-monitor-layout',
                                               None) is None:
                vm.features['no-monitor-layout'] = True

    @qubes.ext.handler('domain-create-on-disk')
    async def on_domain_create_on_disk(self, vm, _event, **kwargs):
        # pylint: disable=unused-argument
        if getattr(vm, 'template', None) is None:
            # handle only template-based vms
            return

        template = vm.template
        if template.features.check_with_template('os', None) != 'Windows':
            # ignore non-windows templates
            return

        if vm.volumes['private'].save_on_stop:
            # until windows tools get ability to prepare private.img on its own,
            # copy one from the template
            vm.log.info('Windows template - cloning private volume')
            await qubes.utils.coro_maybe(
                vm.volumes['private'].import_volume(
                    template.volumes['private']))
