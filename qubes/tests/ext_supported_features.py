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

from unittest import mock

import qubes.ext.supported_features
import qubes.tests


class TC_30_SupportedFeatures(qubes.tests.QubesTestCase):
    def setUp(self):
        super().setUp()
        self.ext = qubes.ext.supported_features.SupportedFeaturesExtension()
        self.features = {}
        specs = {
            "features.get.side_effect": self.features.get,
            "features.items.side_effect": self.features.items,
            "features.__iter__.side_effect": self.features.__iter__,
            "features.__contains__.side_effect": self.features.__contains__,
            "features.__setitem__.side_effect": self.features.__setitem__,
            "features.__delitem__.side_effect": self.features.__delitem__,
        }
        vmspecs = {
            **specs,
            **{
                "template": None,
                "maxmem": 1024,
                "is_running.return_value": True,
            },
        }
        dom0specs = {
            **specs,
            **{
                "name": "dom0",
            },
        }
        self.vm = mock.MagicMock()
        self.vm.configure_mock(**vmspecs)
        self.dom0 = mock.MagicMock()
        self.dom0.configure_mock(**dom0specs)

    def test_010_supported_features(self):
        self.ext.supported_features(
            self.vm,
            "features-request",
            untrusted_features={
                "supported-feature.test1": "1",  # ok
                "supported-feature.test2": "0",  # ignored
                "supported-feature.test3": "some text",  # ignored
                "no-feature": "1",  # ignored
            },
        )
        self.assertEqual(
            self.features,
            {
                "supported-feature.test1": True,
            },
        )

    def test_011_supported_features_add(self):
        self.features["supported-feature.test1"] = "1"
        self.ext.supported_features(
            self.vm,
            "features-request",
            untrusted_features={
                "supported-feature.test1": "1",  # ok
                "supported-feature.test2": "1",  # ok
            },
        )
        # also check if existing one is untouched
        self.assertEqual(
            self.features,
            {
                "supported-feature.test1": "1",
                "supported-feature.test2": True,
            },
        )

    def test_012_supported_features_remove(self):
        self.features["supported-feature.test1"] = "1"
        self.ext.supported_features(
            self.vm,
            "features-request",
            untrusted_features={
                "supported-feature.test2": "1",  # ok
            },
        )
        self.assertEqual(
            self.features,
            {
                "supported-feature.test2": True,
            },
        )

    def test_020_supported_rpc(self):
        self.ext.supported_rpc(
            self.vm,
            "features-request",
            untrusted_features={
                "supported-rpc.qubes.SomeService": "1",  # ok
                "supported-rpc.test2": "0",  # ignored
                "supported-rpc.test3": "some text",  # ignored
                "no-feature": "1",  # ignored
            },
        )
        self.assertEqual(
            self.features,
            {
                "supported-rpc.qubes.SomeService": True,
            },
        )

    def test_021_supported_rpc_add(self):
        self.features["supported-rpc.qubes.SomeService"] = "1"
        self.ext.supported_rpc(
            self.vm,
            "features-request",
            untrusted_features={
                "supported-rpc.qubes.SomeService": "1",  # ok
                "supported-rpc.test2": "1",  # ok
            },
        )
        # also check if existing one is untouched
        self.assertEqual(
            self.features,
            {
                "supported-rpc.qubes.SomeService": "1",
                "supported-rpc.test2": True,
            },
        )

    def test_022_supported_rpc_remove(self):
        self.features["supported-rpc.qubes.SomeService"] = "1"
        self.ext.supported_rpc(
            self.vm,
            "features-request",
            untrusted_features={
                "supported-rpc.test2": "1",  # ok
            },
        )
        self.assertEqual(
            self.features,
            {
                "supported-rpc.test2": True,
            },
        )
