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

import qubes.ext.vm_config
import qubes.tests


class TC_20_VmConfig(qubes.tests.QubesTestCase):
    def setUp(self):
        super().setUp()
        self.ext = qubes.ext.vm_config.VMConfig()
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
            },
        }
        self.vm = mock.MagicMock()
        self.vm.configure_mock(**vmspecs)

    def test_000_write_to_qdb(self):
        self.features["vm-config.test1"] = "1"
        self.features["vm-config.test2"] = "teststring"

        self.ext.on_domain_qdb_create(self.vm, "domain-qdb-create")
        self.assertEqual(
            sorted(self.vm.untrusted_qdb.mock_calls),
            [
                ("write", ("/vm-config/test1", "1"), {}),
                ("write", ("/vm-config/test2", "teststring"), {}),
            ],
        )

    def test_001_feature_set(self):
        self.ext.on_domain_feature_set(
            self.vm,
            "feature-set:vm-config.test_no_oldvalue",
            "vm-config.test_no_oldvalue",
            "testvalue",
        )
        self.ext.on_domain_feature_set(
            self.vm,
            "feature-set:vm-config.test_oldvalue",
            "vm-config.test_oldvalue",
            "newvalue",
            "",
        )
        self.ext.on_domain_feature_set(
            self.vm,
            "feature-set:vm-config.test_disable",
            "vm-config.test_disable",
            "",
            "oldvalue",
        )
        self.ext.on_domain_feature_set(
            self.vm,
            "feature-set:vm-config.test_disable_no_oldvalue",
            "vm-config.test_disable_no_oldvalue",
            "",
        )

        self.assertEqual(
            sorted(self.vm.untrusted_qdb.mock_calls),
            sorted(
                [
                    ("write", ("/vm-config/test_no_oldvalue", "testvalue"), {}),
                    ("write", ("/vm-config/test_oldvalue", "newvalue"), {}),
                    ("write", ("/vm-config/test_disable", ""), {}),
                    ("write", ("/vm-config/test_disable_no_oldvalue", ""), {}),
                ]
            ),
        )

    def test_002_feature_delete(self):
        self.ext.on_domain_feature_delete(
            self.vm, "feature-delete:vm-config.test3", "vm-config.test3"
        )
        self.assertEqual(
            sorted(self.vm.untrusted_qdb.mock_calls),
            [
                ("rm", ("/vm-config/test3",), {}),
            ],
        )
