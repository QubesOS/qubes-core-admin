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

import os

from unittest import mock

import qubes.ext.services
import qubes.tests


class TC_20_Services(qubes.tests.QubesTestCase):
    def setUp(self):
        super().setUp()
        self.ext = qubes.ext.services.ServicesExtension()
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

    def test_000_write_to_qdb(self):
        self.features["service.test1"] = "1"
        self.features["service.test2"] = ""

        self.ext.on_domain_qdb_create(self.vm, "domain-qdb-create")
        self.assertEqual(
            sorted(self.vm.untrusted_qdb.mock_calls),
            [
                ("write", ("/qubes-service/meminfo-writer", "1"), {}),
                ("write", ("/qubes-service/test1", "1"), {}),
                ("write", ("/qubes-service/test2", "0"), {}),
            ],
        )

    def test_001_feature_set(self):
        self.ext.on_domain_feature_set(
            self.vm,
            "feature-set:service.test_no_oldvalue",
            "service.test_no_oldvalue",
            "1",
        )
        self.ext.on_domain_feature_set(
            self.vm,
            "feature-set:service.test_oldvalue",
            "service.test_oldvalue",
            "1",
            "",
        )
        self.ext.on_domain_feature_set(
            self.vm,
            "feature-set:service.test_disable",
            "service.test_disable",
            "",
            "1",
        )
        self.ext.on_domain_feature_set(
            self.vm,
            "feature-set:service.test_disable_no_oldvalue",
            "service.test_disable_no_oldvalue",
            "",
        )

        self.assertEqual(
            sorted(self.vm.untrusted_qdb.mock_calls),
            sorted(
                [
                    ("write", ("/qubes-service/test_no_oldvalue", "1"), {}),
                    ("write", ("/qubes-service/test_oldvalue", "1"), {}),
                    ("write", ("/qubes-service/test_disable", "0"), {}),
                    (
                        "write",
                        ("/qubes-service/test_disable_no_oldvalue", "0"),
                        {},
                    ),
                ]
            ),
        )

    def test_002_feature_delete(self):
        self.ext.on_domain_feature_delete(
            self.vm, "feature-delete:service.test3", "service.test3"
        )
        self.assertEqual(
            sorted(self.vm.untrusted_qdb.mock_calls),
            [
                ("rm", ("/qubes-service/test3",), {}),
            ],
        )

    def test_003_feature_set_invalid(self):
        for val in ("", ".", "a/b", "aa" * 30):
            with self.assertRaises(qubes.exc.QubesValueError):
                self.ext.on_domain_feature_pre_set(
                    self.vm, "feature-set:service." + val, "service." + val, "1"
                )

    def test_010_supported_services(self):
        self.ext.supported_services(
            self.vm,
            "features-request",
            untrusted_features={
                "supported-service.test1": "1",  # ok
                "supported-service.test2": "0",  # ignored
                "supported-service.test3": "some text",  # ignored
                "no-service": "1",  # ignored
            },
        )
        self.assertEqual(
            self.features,
            {
                "supported-service.test1": True,
            },
        )

    def test_011_supported_services_add(self):
        self.features["supported-service.test1"] = "1"
        self.ext.supported_services(
            self.vm,
            "features-request",
            untrusted_features={
                "supported-service.test1": "1",  # ok
                "supported-service.test2": "1",  # ok
            },
        )
        # also check if existing one is untouched
        self.assertEqual(
            self.features,
            {
                "supported-service.test1": "1",
                "supported-service.test2": True,
            },
        )

    def test_012_supported_services_remove(self):
        self.features["supported-service.test1"] = "1"
        self.ext.supported_services(
            self.vm,
            "features-request",
            untrusted_features={
                "supported-service.test2": "1",  # ok
            },
        )
        self.assertEqual(
            self.features,
            {
                "supported-service.test2": True,
            },
        )

    def test_013_feature_set_dom0(self):
        test_base_dir = "/tmp/qubes-test-dir"
        base_dir_patch = mock.patch.dict(
            qubes.config.system_path, {"dom0_services_dir": test_base_dir}
        )
        base_dir_patch.start()
        self.addCleanup(base_dir_patch.stop)
        service = "guivm-gui-agent"
        service_path = test_base_dir + "/" + service

        self.ext.on_domain_feature_set(
            self.dom0,
            "feature-set:service.service.guivm-gui-agent",
            "service.guivm-gui-agent",
            "1",
        )
        self.assertEqual(os.path.exists(service_path), True)

    def test_014_feature_delete_dom0(self):
        test_base_dir = "/tmp/qubes-test-dir"
        base_dir_patch = mock.patch.dict(
            qubes.config.system_path, {"dom0_services_dir": test_base_dir}
        )
        base_dir_patch.start()
        self.addCleanup(base_dir_patch.stop)
        service = "guivm-gui-agent"
        service_path = test_base_dir + "/" + service

        self.ext.on_domain_feature_set(
            self.dom0,
            "feature-set:service.service.guivm-gui-agent",
            "service.guivm-gui-agent",
            "1",
        )

        self.ext.on_domain_feature_delete(
            self.dom0,
            "feature-delete:service.service.guivm-gui-agent",
            "service.guivm-gui-agent",
        )

        self.assertEqual(os.path.exists(service_path), False)

    def test_014_feature_set_empty_value_dom0(self):
        test_base_dir = "/tmp/qubes-test-dir"
        base_dir_patch = mock.patch.dict(
            qubes.config.system_path, {"dom0_services_dir": test_base_dir}
        )
        base_dir_patch.start()
        self.addCleanup(base_dir_patch.stop)
        service = "guivm-gui-agent"
        service_path = test_base_dir + "/" + service

        self.ext.on_domain_feature_set(
            self.dom0,
            "feature-set:service.service.guivm-gui-agent",
            "service.guivm-gui-agent",
            "",
        )

        self.assertEqual(os.path.exists(service_path), False)

    def test_020_app_dispvm_init(self):
        self.features["service.app-dispvm.short-name"] = "1"
        short_name_hash = "uRc_3Q51DYlZXclkZX_BN2iYvUkKh8qXRxkqvvGAwEI"
        long_name = "long-nameeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
        long_name_hash = "Szm7u1YaqyWBAi2tG6eCWfXYIE7YHxQU7hpcCYZ1qbc"
        self.features[(f"service.app-dispvm.{long_name}")] = "1"

        self.ext.on_domain_qdb_create(self.vm, "domain-qdb-create")
        self.assertEqual(
            sorted(self.vm.untrusted_qdb.mock_calls),
            [
                (
                    "write",
                    (f"/hash-app-dispvm/{long_name_hash}", long_name),
                    {},
                ),
                (
                    "write",
                    (f"/hash-app-dispvm/{short_name_hash}", "short-name"),
                    {},
                ),
                ("write", ("/qubes-service/app-dispvm.short-name", "1"), {}),
                ("write", ("/qubes-service/meminfo-writer", "1"), {}),
            ],
        )

    def test_021_app_dispvm_add(self):
        short_name_hash = "uRc_3Q51DYlZXclkZX_BN2iYvUkKh8qXRxkqvvGAwEI"
        long_name = "long-nameeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
        long_name_hash = "Szm7u1YaqyWBAi2tG6eCWfXYIE7YHxQU7hpcCYZ1qbc"
        self.ext.on_domain_feature_pre_set(
            self.vm,
            "feature-set:service.app-dispvm.short-name",
            "service.app-dispvm.short-name",
            "1",
        )
        self.ext.on_domain_feature_set(
            self.vm,
            "feature-set:service.app-dispvm.short-name",
            "service.app-dispvm.short-name",
            "1",
        )
        self.assertEqual(
            sorted(self.vm.untrusted_qdb.mock_calls),
            [
                (
                    "write",
                    (f"/hash-app-dispvm/{short_name_hash}", "short-name"),
                    {},
                ),
                ("write", ("/qubes-service/app-dispvm.short-name", "1"), {}),
            ],
        )

        self.ext.on_domain_feature_pre_set(
            self.vm,
            f"feature-set:service.app-dispvm.{long_name}",
            f"service.app-dispvm.{long_name}",
            "1",
        )
        self.ext.on_domain_feature_set(
            self.vm,
            f"feature-set:service.app-dispvm.{long_name}",
            f"service.app-dispvm.{long_name}",
            "1",
        )

        self.assertEqual(
            sorted(self.vm.untrusted_qdb.mock_calls),
            [
                (
                    "write",
                    (f"/hash-app-dispvm/{long_name_hash}", long_name),
                    {},
                ),
                (
                    "write",
                    (f"/hash-app-dispvm/{short_name_hash}", "short-name"),
                    {},
                ),
                ("write", ("/qubes-service/app-dispvm.short-name", "1"), {}),
            ],
        )

    def test_022_app_dispvm_del(self):
        short_name_hash = "uRc_3Q51DYlZXclkZX_BN2iYvUkKh8qXRxkqvvGAwEI"
        long_name = "long-nameeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
        long_name_hash = "Szm7u1YaqyWBAi2tG6eCWfXYIE7YHxQU7hpcCYZ1qbc"
        self.ext.on_domain_feature_delete(
            self.vm,
            "feature-set:service.app-dispvm.short-name",
            "service.app-dispvm.short-name",
        )
        self.assertEqual(
            sorted(self.vm.untrusted_qdb.mock_calls),
            [
                ("rm", (f"/hash-app-dispvm/{short_name_hash}",), {}),
                ("rm", ("/qubes-service/app-dispvm.short-name",), {}),
            ],
        )

        self.ext.on_domain_feature_delete(
            self.vm,
            f"feature-set:service.app-dispvm.{long_name}",
            f"service.app-dispvm.{long_name}",
        )

        self.assertEqual(
            sorted(self.vm.untrusted_qdb.mock_calls),
            [
                ("rm", (f"/hash-app-dispvm/{long_name_hash}",), {}),
                ("rm", (f"/hash-app-dispvm/{short_name_hash}",), {}),
                ("rm", ("/qubes-service/app-dispvm.short-name",), {}),
            ],
        )
