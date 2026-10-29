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

import qubes.ext.admin
import qubes.tests


class TC_50_Admin(qubes.tests.QubesTestCase):
    maxDiff = None

    def setUp(self):
        super().setUp()
        self.ext = qubes.ext.admin.AdminExtension()

    def tearDown(self):
        self.ext.on_qubes_close("app", "qubes-close")
        super().tearDown()

    def test_000_features_permission(self):
        feature = qubes.ext.admin.PROHIBITED_FEATURES[0]
        for mode in ["Set", "Remove"]:
            with self.subTest(mode=mode):
                with self.assertRaises(qubes.exc.PermissionDenied):
                    self.ext.on_feature_set_or_remove(
                        "test-vm1",
                        f"admin-permission:admin.vm.feature.{mode}",
                        feature,
                    )

    def test_000_properties_permission(self):
        prop = qubes.ext.admin.PROHIBITED_PROPERTIES[0]
        for mode in ["Set", "Reset"]:
            with self.subTest(mode=mode):
                with self.assertRaises(qubes.exc.PermissionDenied):
                    self.ext.on_property_set_or_remove(
                        "test-vm1",
                        f"admin-permission:admin.vm.property.{mode}",
                        prop,
                    )

    def test_000_tags_permission(self):
        tag = "created-by-test"
        for mode in ["Set", "Remove"]:
            with self.subTest(mode=mode):
                with self.assertRaises(qubes.exc.PermissionDenied):
                    self.ext.on_tag_set_or_remove(
                        "test-vm1",
                        f"admin-permission:admin.vm.tag.{mode}",
                        tag,
                    )

    def test_001_derived_tags_permission(self):
        dom0 = mock.MagicMock(spec=qubes.vm.adminvm.AdminVM)
        for tag in ("guivm-sys-gui", "audiovm-sys-audio", "relayvm-sys-relay"):
            for event in (
                "admin-permission:admin.vm.tag.Set",
                "admin-permission:admin.vm.tag.Remove",
            ):
                with self.subTest(tag=tag, event=event):
                    with self.assertRaises(qubes.exc.PermissionDenied):
                        self.ext.on_tag_set_or_remove("test-vm1", event, tag)
                    # Dom0 can still change them
                    self.ext.on_tag_set_or_remove(dom0, event, tag)
        # Other tags are not protected
        self.ext.on_tag_set_or_remove(
            "test-vm1", "admin-permission:admin.vm.tag.Set", "work"
        )
