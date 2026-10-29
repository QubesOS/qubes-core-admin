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

import qubes.ext.custom_persist
import qubes.tests


class TC_40_CustomPersist(qubes.tests.QubesTestCase):
    def setUp(self):
        super().setUp()
        self.ext = qubes.ext.custom_persist.CustomPersist()
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
        self.features["custom-persist.home"] = "/home"
        self.features["custom-persist.usrlocal"] = "/usr/local"
        self.features["custom-persist.var_test"] = "/var/test"

        self.ext.on_domain_qdb_create(self.vm, "domain-qdb-create")
        self.assertEqual(
            sorted(self.vm.untrusted_qdb.mock_calls),
            [
                mock.call.write("/persist/home", "/home"),
                mock.call.write("/persist/usrlocal", "/usr/local"),
                mock.call.write("/persist/var_test", "/var/test"),
            ],
        )

    def test_001_feature_set(self):
        self.ext.on_domain_feature_set(
            self.vm,
            "feature-set:custom-persist.test_no_oldvalue",
            "custom-persist.test_no_oldvalue",
            "/test_no_oldvalue",
        )
        self.ext.on_domain_feature_set(
            self.vm,
            "feature-set:custom-persist.test_oldvalue",
            "custom-persist.test_oldvalue",
            "/newvalue",
            "",
        )

        self.assertEqual(
            sorted(self.vm.untrusted_qdb.mock_calls),
            [
                mock.call.write(
                    "/persist/test_no_oldvalue", "/test_no_oldvalue"
                ),
                mock.call.write("/persist/test_oldvalue", "/newvalue"),
            ],
        )

    def test_002_feature_delete(self):
        self.ext.on_domain_feature_delete(
            self.vm, "feature-delete:custom-persist.test", "custom-persist.test"
        )
        self.vm.untrusted_qdb.rm.assert_called_with("/persist/test")

    def test_003_empty_key(self):
        with self.assertRaises(qubes.exc.QubesValueError) as e:
            self.ext.on_domain_feature_set(
                self.vm,
                "feature-set:custom-persist.",
                "custom-persist.",
                "/test",
                "",
            )
        self.assertEqual(str(e.exception), "custom-persist key cannot be empty")
        self.vm.untrusted_qdb.write.assert_not_called()

    def test_004_key_too_long(self):
        with self.assertRaises(qubes.exc.QubesValueError) as e:
            self.ext.on_domain_feature_set(
                self.vm,
                "feature-set:custom-persist." + "X" * 55,
                "custom-persist." + "X" * 55,
                "/test",
                "",
            )

        self.assertEqual(
            str(e.exception),
            "custom-persist key is too long (max 54), ignoring: " + "X" * 55,
        )
        self.vm.untrusted_qdb.assert_not_called()

    def test_005_other_feature_deletion(self):
        self.ext.on_domain_feature_delete(
            self.vm, "feature-delete:otherfeature.test", "otherfeature.test"
        )
        self.vm.untrusted_qdb.assert_not_called()

    def test_006_feature_set_while_vm_is_not_running(self):
        self.vm.is_running.return_value = False
        self.ext.on_domain_feature_set(
            self.vm,
            "feature-set:custom-persist.test",
            "custom-persist.test",
            "/test",
        )
        self.vm.untrusted_qdb.write.assert_not_called()

    def test_007_feature_set_value_with_option(self):
        self.ext.on_domain_feature_set(
            self.vm,
            "feature-set:custom-persist.test",
            "custom-persist.test",
            "dir:root:root:0755:/var/test",
            "",
        )
        self.vm.untrusted_qdb.write.assert_called_with(
            "/persist/test", "dir:root:root:0755:/var/test"
        )

    def test_008_feature_set_invalid_path(self):
        with self.assertRaises(qubes.exc.QubesValueError):
            self.ext.on_domain_feature_set(
                self.vm,
                "feature-set:custom-persist.test",
                "custom-persist.test",
                "test",
                "",
            )
        self.vm.untrusted_qdb.write.assert_not_called()

    def test_009_feature_set_invalid_option_type(self):
        with self.assertRaises(qubes.exc.QubesValueError):
            self.ext.on_domain_feature_set(
                self.vm,
                "feature-set:custom-persist.test",
                "custom-persist.test",
                "bad:root:root:0755:/var/test",
                "",
            )
        self.vm.untrusted_qdb.write.assert_not_called()

    def test_010_feature_set_invalid_option_mode_too_high(self):
        with self.assertRaises(qubes.exc.QubesValueError):
            self.ext.on_domain_feature_set(
                self.vm,
                "feature-set:custom-persist.test",
                "custom-persist.test",
                "file:root:root:9750:/var/test",
                "",
            )
        self.vm.untrusted_qdb.write.assert_not_called()

    def test_011_feature_set_invalid_option_mode_negative_high(self):
        with self.assertRaises(qubes.exc.QubesValueError):
            self.ext.on_domain_feature_set(
                self.vm,
                "feature-set:custom-persist.test",
                "custom-persist.test",
                "file:root:root:-755:/var/test",
                "",
            )
        self.vm.untrusted_qdb.write.assert_not_called()

    def test_012_feature_set_option_mode_without_leading_zero(self):
        self.ext.on_domain_feature_set(
            self.vm,
            "feature-set:custom-persist.test",
            "custom-persist.test",
            "file:root:root:755:/var/test",
            "",
        )
        self.vm.untrusted_qdb.write.assert_called_with(
            "/persist/test", "file:root:root:755:/var/test"
        )

    def test_013_feature_set_invalid_path_with_option(self):
        with self.assertRaises(qubes.exc.QubesValueError):
            self.ext.on_domain_feature_set(
                self.vm,
                "feature-set:custom-persist.test",
                "custom-persist.test",
                "dir:root:root:0755:var/test",
                "",
            )
        self.vm.untrusted_qdb.write.assert_not_called()

    def test_014_feature_set_path_with_colon_with_options(self):
        self.ext.on_domain_feature_set(
            self.vm,
            "feature-set:custom-persist.test",
            "custom-persist.test",
            "file:root:root:755:/var/test:dir:with:colon",
            "",
        )
        self.vm.untrusted_qdb.write.assert_called()

    def test_015_feature_set_path_with_colon_without_options(self):
        self.ext.on_domain_feature_set(
            self.vm,
            "feature-set:custom-persist.test",
            "custom-persist.test",
            "/var/test:dir:with:colon",
            "",
        )
        self.vm.untrusted_qdb.write.assert_called_with(
            "/persist/test", "/var/test:dir:with:colon"
        )
