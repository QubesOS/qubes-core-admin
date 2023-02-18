# -*- encoding: utf-8 -*-
#
# The Qubes OS Project, http://www.qubes-os.org
#
# Copyright (C) 2020 Marek Marczykowski-Górecki
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

"""Extension responsible for announcing supported features"""

import qubes.ext
import qubes.config

# pylint: disable=too-few-public-methods

class SupportedFeaturesExtension(qubes.ext.Extension):
    """This extension handles VM announcing non-service features as
        'supported-feature.*' features.
    """

    @qubes.ext.handler('features-request')
    def supported_features(self, vm, event, untrusted_features):
        """Handle advertisement of supported features"""
        # pylint: disable=unused-argument

        if getattr(vm, 'template', None):
            vm.log.warning(
                'Ignoring qubes.FeaturesRequest from template-based VM')
            return

        new_supported_features = set()
        for requested_feature in untrusted_features:
            if not requested_feature.startswith('supported-feature.'):
                continue
            if untrusted_features[requested_feature] == '1':
                # only allow to advertise feature as supported, lack of entry
                #  means feature is not supported
                new_supported_features.add(requested_feature)
        del untrusted_features

        # if no feature is supported, ignore the whole thing - do not clear
        # all features in case of empty request (manual or such)
        if not new_supported_features:
            return

        old_supported_features = set(
            feat for feat in vm.features
            if feat.startswith('supported-feature.') and vm.features[feat])

        for feature in new_supported_features.difference(
                old_supported_features):
            vm.features[feature] = True

        for feature in old_supported_features.difference(
                new_supported_features):
            del vm.features[feature]

    @qubes.ext.handler('features-request')
    def supported_rpc(self, vm, event, untrusted_features):
        """Handle advertisement of supported rpc services"""
        # pylint: disable=unused-argument

        new_supported_rpc = set()
        for requested_feature in untrusted_features:
            if not requested_feature.startswith('supported-rpc.'):
                continue
            if untrusted_features[requested_feature] == '1':
                # only allow to advertise feature as supported, lack of entry
                #  means feature is not supported
                new_supported_rpc.add(requested_feature)
        del untrusted_features

        # if no feature is supported, ignore the whole thing - do not clear
        # all features in case of empty request (manual or such)
        if not new_supported_rpc:
            return

        old_supported_rpc = set(
            feat for feat in vm.features
            if feat.startswith('supported-rpc.') and vm.features[feat])

        for feature in new_supported_rpc.difference(
                old_supported_rpc):
            vm.features[feature] = True

        for feature in old_supported_rpc.difference(
                new_supported_rpc):
            del vm.features[feature]
