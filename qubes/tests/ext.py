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
import unittest.mock

import qubes.ext.admin
import qubes.ext.core_features
import qubes.ext.custom_persist
import qubes.ext.services
import qubes.ext.windows
import qubes.ext.supported_features
import qubes.ext.vm_config
import qubes.tests
import qubes.vm.qubesvm

from unittest import mock


class TC_00_CoreFeatures(qubes.tests.QubesTestCase):
    maxDiff = None

    def setUp(self):
        super().setUp()
        self.ext = qubes.ext.core_features.CoreFeatures()
        self.vm = mock.MagicMock()
        self.async_vm = mock.AsyncMock()
        self.features = {}
        self.vm.configure_mock(
            **{
                "features.get.side_effect": self.features.get,
                "features.items.side_effect": self.features.items,
                "features.__iter__.side_effect": self.features.__iter__,
                "features.__contains__.side_effect": self.features.__contains__,
                "features.__setitem__.side_effect": self.features.__setitem__,
                "features.__delitem__.side_effect": self.features.__delitem__,
                "fire_event_async": self.async_vm,
            }
        )

    def test_010_notify_tools(self):
        del self.vm.template
        self.loop.run_until_complete(
            self.ext.qubes_features_request(
                self.vm,
                "features-request",
                untrusted_features={
                    "gui": "1",
                    "version": "1",
                    "default-user": "user",
                    "qrexec": "1",
                    "vmexec": "1",
                },
            )
        )
        self.assertListEqual(
            self.vm.mock_calls,
            [
                ("features.items", (), {}),
                ("features.get", ("qrexec", False), {}),
                ("features.__contains__", ("qrexec",), {}),
                ("features.__setitem__", ("qrexec", True), {}),
                ("features.__contains__", ("gui",), {}),
                ("features.__setitem__", ("gui", True), {}),
                ("features.__setitem__", ("vmexec", True), {}),
                ("features.get", ("qrexec", False), {}),
                ("fire_event_async", ("template-postinstall",), {}),
            ],
        )

    def test_011_notify_tools_uninstall(self):
        del self.vm.template
        self.loop.run_until_complete(
            self.ext.qubes_features_request(
                self.vm,
                "features-request",
                untrusted_features={
                    "gui": "0",
                    "version": "1",
                    "default-user": "user",
                    "qrexec": "0",
                    "vmexec": "0",
                },
            )
        )
        self.assertListEqual(
            self.vm.mock_calls,
            [
                ("features.items", (), {}),
                ("features.get", ("qrexec", False), {}),
                ("features.__contains__", ("qrexec",), {}),
                ("features.__setitem__", ("qrexec", False), {}),
                ("features.__contains__", ("gui",), {}),
                ("features.__setitem__", ("gui", False), {}),
                ("features.__setitem__", ("vmexec", False), {}),
                ("features.get", ("qrexec", False), {}),
            ],
        )

    def test_012_notify_tools_uninstall2(self):
        del self.vm.template
        self.loop.run_until_complete(
            self.ext.qubes_features_request(
                self.vm,
                "features-request",
                untrusted_features={
                    "version": "1",
                    "default-user": "user",
                },
            )
        )
        self.assertListEqual(
            self.vm.mock_calls,
            [
                ("features.items", (), {}),
                ("features.get", ("qrexec", False), {}),
                ("features.get", ("qrexec", False), {}),
            ],
        )

    def test_013_notify_tools_no_version(self):
        del self.vm.template
        self.loop.run_until_complete(
            self.ext.qubes_features_request(
                self.vm,
                "features-request",
                untrusted_features={
                    "qrexec": "1",
                    "gui": "1",
                    "default-user": "user",
                },
            )
        )
        self.assertListEqual(
            self.vm.mock_calls,
            [
                ("features.items", (), {}),
                ("features.get", ("qrexec", False), {}),
                ("features.__contains__", ("qrexec",), {}),
                ("features.__setitem__", ("qrexec", True), {}),
                ("features.__contains__", ("gui",), {}),
                ("features.__setitem__", ("gui", True), {}),
                ("features.get", ("qrexec", False), {}),
                ("fire_event_async", ("template-postinstall",), {}),
            ],
        )

    def test_015_notify_tools_invalid_value_qrexec(self):
        del self.vm.template
        self.loop.run_until_complete(
            self.ext.qubes_features_request(
                self.vm,
                "features-request",
                untrusted_features={
                    "version": "1",
                    "qrexec": "invalid",
                    "gui": "1",
                    "default-user": "user",
                },
            )
        )
        self.assertEqual(
            self.vm.mock_calls,
            [
                ("features.items", (), {}),
                ("features.get", ("qrexec", False), {}),
                ("features.__contains__", ("gui",), {}),
                ("features.__setitem__", ("gui", True), {}),
                ("features.get", ("qrexec", False), {}),
            ],
        )

    def test_016_notify_tools_invalid_value_gui(self):
        del self.vm.template
        self.loop.run_until_complete(
            self.ext.qubes_features_request(
                self.vm,
                "features-request",
                untrusted_features={
                    "version": "1",
                    "qrexec": "1",
                    "gui": "invalid",
                    "default-user": "user",
                },
            )
        )
        self.assertListEqual(
            self.vm.mock_calls,
            [
                ("features.items", (), {}),
                ("features.get", ("qrexec", False), {}),
                ("features.__contains__", ("qrexec",), {}),
                ("features.__setitem__", ("qrexec", True), {}),
                ("features.get", ("qrexec", False), {}),
                ("fire_event_async", ("template-postinstall",), {}),
            ],
        )

    def test_017_notify_tools_template_based(self):
        self.loop.run_until_complete(
            self.ext.qubes_features_request(
                self.vm,
                "features-request",
                untrusted_features={
                    "version": "1",
                    "qrexec": "1",
                    "gui": "1",
                    "default-user": "user",
                },
            )
        )
        self.assertEqual(
            self.vm.mock_calls,
            [
                ("template.__bool__", (), {}),
                (
                    "log.warning",
                    ("Ignoring qubes.NotifyTools for template-based " "VM",),
                    {},
                ),
            ],
        )

    def test_018_notify_tools_already_installed(self):
        self.features["qrexec"] = True
        self.features["gui"] = True
        del self.vm.template
        self.loop.run_until_complete(
            self.ext.qubes_features_request(
                self.vm,
                "features-request",
                untrusted_features={
                    "gui": "1",
                    "version": "1",
                    "default-user": "user",
                    "qrexec": "1",
                },
            )
        )
        self.assertListEqual(
            self.vm.mock_calls,
            [
                ("features.items", (), {}),
                ("features.get", ("qrexec", False), {}),
                ("features.__contains__", ("qrexec",), {}),
                ("features.__contains__", ("gui",), {}),
            ],
        )

    def test_20_version(self):
        self.features["qrexec"] = True
        del self.vm.template
        self.loop.run_until_complete(
            self.ext.qubes_features_request(
                self.vm,
                "features-request",
                untrusted_features={"qubes-agent-version": "4.1"},
            )
        )
        self.assertListEqual(
            self.vm.mock_calls,
            [
                ("features.__setitem__", ("qubes-agent-version", "4.1"), {}),
                ("features.items", (), {}),
                ("features.get", ("qrexec", False), {}),
            ],
        )

    def test_21_version_invalid(self):
        self.features["qrexec"] = True
        del self.vm.template
        self.loop.run_until_complete(
            self.ext.qubes_features_request(
                self.vm,
                "features-request",
                untrusted_features={"qubes-agent-version": "4"},
            )
        )
        self.assertListEqual(
            self.vm.mock_calls,
            [
                ("features.items", (), {}),
                ("features.get", ("qrexec", False), {}),
            ],
        )
        self.vm.mock_calls.clear()
        self.loop.run_until_complete(
            self.ext.qubes_features_request(
                self.vm,
                "features-request",
                untrusted_features={"qubes-agent-version": "4.1.1"},
            )
        )
        self.assertListEqual(
            self.vm.mock_calls,
            [
                ("features.items", (), {}),
                ("features.get", ("qrexec", False), {}),
            ],
        )
        self.vm.mock_calls.clear()
        self.loop.run_until_complete(
            self.ext.qubes_features_request(
                self.vm,
                "features-request",
                untrusted_features={"qubes-agent-version": "notnumeric"},
            )
        )
        self.assertListEqual(
            self.vm.mock_calls,
            [
                ("features.items", (), {}),
                ("features.get", ("qrexec", False), {}),
            ],
        )
        self.vm.mock_calls.clear()
        self.loop.run_until_complete(
            self.ext.qubes_features_request(
                self.vm,
                "features-request",
                untrusted_features={"qubes-agent-version": "40000000"},
            )
        )
        self.assertListEqual(
            self.vm.mock_calls,
            [
                ("features.items", (), {}),
                ("features.get", ("qrexec", False), {}),
            ],
        )

    def test_30_distro_meta(self):
        self.features["qrexec"] = True
        del self.vm.template
        self.loop.run_until_complete(
            self.ext.qubes_features_request(
                self.vm,
                "features-request",
                untrusted_features={
                    "os": "Linux",
                    "os-distribution": "debian",
                    "os-version": "12",
                    "os-eol": "2026-06-10",
                },
            )
        )
        self.assertListEqual(
            self.vm.mock_calls,
            [
                ("features.__setitem__", ("os-distribution", "debian"), {}),
                ("features.__setitem__", ("os-version", "12"), {}),
                ("features.__setitem__", ("os-eol", "2026-06-10"), {}),
                ("features.items", (), {}),
                ("features.get", ("qrexec", False), {}),
            ],
        )

    def test_031_distro_meta_ubuntu(self):
        self.features["qrexec"] = True
        del self.vm.template
        self.loop.run_until_complete(
            self.ext.qubes_features_request(
                self.vm,
                "features-request",
                untrusted_features={
                    "os": "Linux",
                    "os-distribution": "ubuntu",
                    "os-distribution-like": "debian",
                    "os-version": "22.04",
                    "os-eol": "2027-06-01",
                },
            )
        )
        self.assertListEqual(
            self.vm.mock_calls,
            [
                ("features.__setitem__", ("os-distribution", "ubuntu"), {}),
                (
                    "features.__setitem__",
                    ("os-distribution-like", "debian"),
                    {},
                ),
                ("features.__setitem__", ("os-version", "22.04"), {}),
                ("features.__setitem__", ("os-eol", "2027-06-01"), {}),
                ("features.items", (), {}),
                ("features.get", ("qrexec", False), {}),
            ],
        )

    def test_032_distro_meta_invalid(self):
        self.features["qrexec"] = True
        del self.vm.template
        self.loop.run_until_complete(
            self.ext.qubes_features_request(
                self.vm,
                "features-request",
                untrusted_features={
                    "os": "Linux",
                    "os-distribution": "ubuntu",
                    "os-distribution-like": "debian",
                    "os-version": "123aaa",
                    "os-eol": "20270601",
                },
            )
        )
        self.assertListEqual(
            self.vm.mock_calls,
            [
                ("features.__setitem__", ("os-distribution", "ubuntu"), {}),
                (
                    "features.__setitem__",
                    ("os-distribution-like", "debian"),
                    {},
                ),
                ("log.warning", unittest.mock.ANY, {}),
                ("log.warning", unittest.mock.ANY, {}),
                ("features.items", (), {}),
                ("features.get", ("qrexec", False), {}),
            ],
        )

    def test_033_distro_meta_invalid2(self):
        self.features["qrexec"] = True
        del self.vm.template
        self.loop.run_until_complete(
            self.ext.qubes_features_request(
                self.vm,
                "features-request",
                untrusted_features={
                    "os": "Linux",
                    "os-distribution": "ubuntu",
                    "os-distribution-like": "debian",
                    "os-version": "a123",
                    "os-eol": "2027-06-40",
                },
            )
        )
        self.assertListEqual(
            self.vm.mock_calls,
            [
                ("features.__setitem__", ("os-distribution", "ubuntu"), {}),
                (
                    "features.__setitem__",
                    ("os-distribution-like", "debian"),
                    {},
                ),
                ("log.warning", unittest.mock.ANY, {}),
                ("log.warning", unittest.mock.ANY, {}),
                ("features.items", (), {}),
                ("features.get", ("qrexec", False), {}),
            ],
        )

    def test_034_distro_meta_empty(self):
        self.features["qrexec"] = True
        del self.vm.template
        self.loop.run_until_complete(
            self.ext.qubes_features_request(
                self.vm,
                "features-request",
                untrusted_features={
                    "os": "",
                    "os-distribution": "",
                    "os-distribution-like": "",
                    "os-version": "",
                    "os-eol": "",
                },
            )
        )
        self.assertListEqual(
            self.vm.mock_calls,
            [
                ("features.items", (), {}),
                ("features.get", ("qrexec", False), {}),
            ],
        )

    def test_040_bootmode_noname(self):
        del self.vm.template
        self.loop.run_until_complete(
            self.ext.qubes_features_request(
                self.vm,
                "features-request",
                untrusted_features={
                    "boot-mode.kernelopts.vmreq": "vmreq1 vmreq2",
                },
            )
        )
        self.assertListEqual(
            self.vm.mock_calls,
            [
                ("features.items", (), {}),
                (
                    "features.__setitem__",
                    ("boot-mode.kernelopts.vmreq", "vmreq1 vmreq2"),
                    {},
                ),
                ("features.get", ("qrexec", False), {}),
                ("features.get", ("qrexec", False), {}),
            ],
        )

    def test_041_bootmode_withname(self):
        del self.vm.template
        self.loop.run_until_complete(
            self.ext.qubes_features_request(
                self.vm,
                "features-request",
                untrusted_features={
                    "boot-mode.name.vmreq": "VMReq",
                    "boot-mode.kernelopts.vmreq": "vmreq1 vmreq2",
                },
            )
        )
        self.assertListEqual(
            self.vm.mock_calls,
            [
                ("features.items", (), {}),
                (
                    "features.__setitem__",
                    ("boot-mode.kernelopts.vmreq", "vmreq1 vmreq2"),
                    {},
                ),
                (
                    "features.__setitem__",
                    ("boot-mode.name.vmreq", "VMReq"),
                    {},
                ),
                ("features.get", ("qrexec", False), {}),
                ("features.get", ("qrexec", False), {}),
            ],
        )

    def test_042_bootmode_extraname(self):
        del self.vm.template
        self.loop.run_until_complete(
            self.ext.qubes_features_request(
                self.vm,
                "features-request",
                untrusted_features={
                    "boot-mode.name.vmreq1": "VMReq1",
                    "boot-mode.kernelopts.vmreq1": "vmreq1-1 vmreq1-2",
                    "boot-mode.name.bad": "Bad Entry",
                    "boot-mode.name.vmreq2": "VMReq2",
                    "boot-mode.kernelopts.vmreq2": "vmreq2-1 vmreq2-2",
                },
            )
        )
        self.assertListEqual(
            self.vm.mock_calls,
            [
                ("features.items", (), {}),
                (
                    "features.__setitem__",
                    ("boot-mode.kernelopts.vmreq1", "vmreq1-1 vmreq1-2"),
                    {},
                ),
                (
                    "features.__setitem__",
                    ("boot-mode.kernelopts.vmreq2", "vmreq2-1 vmreq2-2"),
                    {},
                ),
                (
                    "features.__setitem__",
                    ("boot-mode.name.vmreq1", "VMReq1"),
                    {},
                ),
                (
                    "features.__setitem__",
                    ("boot-mode.name.vmreq2", "VMReq2"),
                    {},
                ),
                ("features.get", ("qrexec", False), {}),
                ("features.get", ("qrexec", False), {}),
            ],
        )

    def test_043_bootmode_extrakernelopts(self):
        del self.vm.template
        self.loop.run_until_complete(
            self.ext.qubes_features_request(
                self.vm,
                "features-request",
                untrusted_features={
                    "boot-mode.name.vmreq1": "VMReq1",
                    "boot-mode.kernelopts.vmreq1": "vmreq1-1 vmreq1-2",
                    "boot-mode.kernelopts.extra": "extra-opts",
                    "boot-mode.name.vmreq2": "VMReq2",
                    "boot-mode.kernelopts.vmreq2": "vmreq2-1 vmreq2-2",
                },
            )
        )
        self.assertListEqual(
            self.vm.mock_calls,
            [
                ("features.items", (), {}),
                (
                    "features.__setitem__",
                    ("boot-mode.kernelopts.vmreq1", "vmreq1-1 vmreq1-2"),
                    {},
                ),
                (
                    "features.__setitem__",
                    ("boot-mode.kernelopts.extra", "extra-opts"),
                    {},
                ),
                (
                    "features.__setitem__",
                    ("boot-mode.kernelopts.vmreq2", "vmreq2-1 vmreq2-2"),
                    {},
                ),
                (
                    "features.__setitem__",
                    ("boot-mode.name.vmreq1", "VMReq1"),
                    {},
                ),
                (
                    "features.__setitem__",
                    ("boot-mode.name.vmreq2", "VMReq2"),
                    {},
                ),
                ("features.get", ("qrexec", False), {}),
                ("features.get", ("qrexec", False), {}),
            ],
        )

    def test_044_bootmode_discard_old(self):
        del self.vm.template
        self.features["boot-mode.name.old"] = "Old"
        self.features["boot-mode.kernelopts.old"] = "old1 old2"
        self.loop.run_until_complete(
            self.ext.qubes_features_request(
                self.vm,
                "features-request",
                untrusted_features={
                    "boot-mode.name.vmreq1": "VMReq1",
                    "boot-mode.kernelopts.vmreq1": "vmreq1-1 vmreq1-2",
                },
            )
        )
        self.assertListEqual(
            self.vm.mock_calls,
            [
                ("features.items", (), {}),
                ("features.__delitem__", ("boot-mode.name.old",), {}),
                ("features.__delitem__", ("boot-mode.kernelopts.old",), {}),
                (
                    "features.__setitem__",
                    ("boot-mode.kernelopts.vmreq1", "vmreq1-1 vmreq1-2"),
                    {},
                ),
                (
                    "features.__setitem__",
                    ("boot-mode.name.vmreq1", "VMReq1"),
                    {},
                ),
                ("features.get", ("qrexec", False), {}),
                ("features.get", ("qrexec", False), {}),
            ],
        )

    def test_045_bootmode_update_old(self):
        del self.vm.template
        self.features["boot-mode.name.old1"] = "Old1"
        self.features["boot-mode.kernelopts.old1"] = "old1-1 old1-2"
        self.features["boot-mode.name.old2"] = "Old2"
        self.features["boot-mode.kernelopts.old2"] = "old2-1 old2-2"
        self.loop.run_until_complete(
            self.ext.qubes_features_request(
                self.vm,
                "features-request",
                untrusted_features={
                    "boot-mode.name.vmreq1": "VMReq1",
                    "boot-mode.kernelopts.vmreq1": "vmreq1-1 vmreq1-2",
                    "boot-mode.kernelopts.old1": "old-newer1-1 old-newer1-2",
                },
            )
        )
        self.assertListEqual(
            self.vm.mock_calls,
            [
                ("features.items", (), {}),
                ("features.__delitem__", ("boot-mode.name.old1",), {}),
                ("features.__delitem__", ("boot-mode.name.old2",), {}),
                ("features.__delitem__", ("boot-mode.kernelopts.old2",), {}),
                (
                    "features.__setitem__",
                    ("boot-mode.kernelopts.vmreq1", "vmreq1-1 vmreq1-2"),
                    {},
                ),
                (
                    "features.__setitem__",
                    ("boot-mode.kernelopts.old1", "old-newer1-1 old-newer1-2"),
                    {},
                ),
                (
                    "features.__setitem__",
                    ("boot-mode.name.vmreq1", "VMReq1"),
                    {},
                ),
                ("features.get", ("qrexec", False), {}),
                ("features.get", ("qrexec", False), {}),
            ],
        )

    def test_046_bootmode_flood1(self):
        del self.vm.template
        self.loop.run_until_complete(
            self.ext.qubes_features_request(
                self.vm,
                "features-request",
                untrusted_features={
                    "boot-mode.kernelopts.garbage1": "garbage1",
                    "boot-mode.kernelopts.garbage2": "garbage2",
                    "boot-mode.kernelopts.garbage3": "garbage3",
                    "boot-mode.kernelopts.garbage4": "garbage4",
                    "boot-mode.kernelopts.garbage5": "garbage5",
                    "boot-mode.kernelopts.garbage6": "garbage6",
                    "boot-mode.kernelopts.garbage7": "garbage7",
                    "boot-mode.kernelopts.garbage8": "garbage8",
                    "boot-mode.kernelopts.garbage9": "garbage9",
                    "boot-mode.kernelopts.garbage10": "garbage10",
                    "boot-mode.kernelopts.garbage11": "garbage11",
                    "boot-mode.kernelopts.garbage12": "garbage12",
                    "boot-mode.kernelopts.garbage13": "garbage13",
                    "boot-mode.kernelopts.garbage14": "garbage14",
                    "boot-mode.kernelopts.garbage15": "garbage15",
                    "boot-mode.kernelopts.garbage16": "garbage16",
                    "boot-mode.kernelopts.garbage17": "garbage17",
                    "boot-mode.kernelopts.garbage18": "garbage18",
                    "boot-mode.kernelopts.garbage19": "garbage19",
                    "boot-mode.kernelopts.garbage20": "garbage20",
                    "boot-mode.kernelopts.garbage21": "garbage21",
                    "boot-mode.kernelopts.garbage22": "garbage22",
                    "boot-mode.kernelopts.garbage23": "garbage23",
                    "boot-mode.kernelopts.garbage24": "garbage24",
                    "boot-mode.kernelopts.garbage25": "garbage25",
                    "boot-mode.kernelopts.garbage26": "garbage26",
                    "boot-mode.kernelopts.garbage27": "garbage27",
                    "boot-mode.kernelopts.garbage28": "garbage28",
                    "boot-mode.kernelopts.garbage29": "garbage29",
                    "boot-mode.kernelopts.garbage30": "garbage30",
                    "boot-mode.kernelopts.garbage31": "garbage31",
                    "boot-mode.kernelopts.garbage32": "garbage32",
                    "boot-mode.kernelopts.garbage33": "garbage33",
                    "boot-mode.kernelopts.garbage34": "garbage34",
                    "boot-mode.kernelopts.garbage35": "garbage35",
                    "boot-mode.kernelopts.garbage36": "garbage36",
                    "boot-mode.kernelopts.garbage37": "garbage37",
                    "boot-mode.kernelopts.garbage38": "garbage38",
                    "boot-mode.kernelopts.garbage39": "garbage39",
                    "boot-mode.kernelopts.garbage40": "garbage40",
                    "boot-mode.kernelopts.garbage41": "garbage41",
                    "boot-mode.kernelopts.garbage42": "garbage42",
                    "boot-mode.kernelopts.garbage43": "garbage43",
                    "boot-mode.kernelopts.garbage44": "garbage44",
                    "boot-mode.kernelopts.garbage45": "garbage45",
                    "boot-mode.kernelopts.garbage46": "garbage46",
                    "boot-mode.kernelopts.garbage47": "garbage47",
                    "boot-mode.kernelopts.garbage48": "garbage48",
                    "boot-mode.kernelopts.garbage49": "garbage49",
                    "boot-mode.kernelopts.garbage50": "garbage50",
                    "boot-mode.kernelopts.garbage51": "garbage51",
                    "boot-mode.kernelopts.garbage52": "garbage52",
                    "boot-mode.kernelopts.garbage53": "garbage53",
                    "boot-mode.kernelopts.garbage54": "garbage54",
                    "boot-mode.kernelopts.garbage55": "garbage55",
                    "boot-mode.kernelopts.garbage56": "garbage56",
                    "boot-mode.kernelopts.garbage57": "garbage57",
                    "boot-mode.kernelopts.garbage58": "garbage58",
                    "boot-mode.kernelopts.garbage59": "garbage59",
                    "boot-mode.kernelopts.garbage60": "garbage60",
                    "boot-mode.kernelopts.garbage61": "garbage61",
                    "boot-mode.kernelopts.garbage62": "garbage62",
                    "boot-mode.kernelopts.garbage63": "garbage63",
                    "boot-mode.kernelopts.garbage64": "garbage64",
                    "boot-mode.kernelopts.garbage65": "garbage65",
                },
            )
        )
        self.assertListEqual(
            self.vm.mock_calls,
            [
                ("features.items", (), {}),
                ("features.get", ("qrexec", False), {}),
                ("features.get", ("qrexec", False), {}),
            ],
        )

    def test_047_bootmode_flood2(self):
        del self.vm.template
        self.features["boot-mode.kernelopts.garbage1"] = "garbage1"
        self.features["boot-mode.kernelopts.garbage2"] = "garbage2"
        self.features["boot-mode.kernelopts.garbage3"] = "garbage3"
        self.features["boot-mode.kernelopts.garbage4"] = "garbage4"
        self.features["boot-mode.kernelopts.garbage5"] = "garbage5"
        self.features["boot-mode.kernelopts.garbage6"] = "garbage6"
        self.features["boot-mode.kernelopts.garbage7"] = "garbage7"
        self.features["boot-mode.kernelopts.garbage8"] = "garbage8"
        self.features["boot-mode.kernelopts.garbage9"] = "garbage9"
        self.features["boot-mode.kernelopts.garbage10"] = "garbage10"
        self.loop.run_until_complete(
            self.ext.qubes_features_request(
                self.vm,
                "features-request",
                untrusted_features={
                    "boot-mode.kernelopts.garbage11": "garbage11",
                    "boot-mode.kernelopts.garbage12": "garbage12",
                    "boot-mode.kernelopts.garbage13": "garbage13",
                    "boot-mode.kernelopts.garbage14": "garbage14",
                    "boot-mode.kernelopts.garbage15": "garbage15",
                    "boot-mode.kernelopts.garbage16": "garbage16",
                    "boot-mode.kernelopts.garbage17": "garbage17",
                    "boot-mode.kernelopts.garbage18": "garbage18",
                    "boot-mode.kernelopts.garbage19": "garbage19",
                    "boot-mode.kernelopts.garbage20": "garbage20",
                    "boot-mode.kernelopts.garbage21": "garbage21",
                    "boot-mode.kernelopts.garbage22": "garbage22",
                    "boot-mode.kernelopts.garbage23": "garbage23",
                    "boot-mode.kernelopts.garbage24": "garbage24",
                    "boot-mode.kernelopts.garbage25": "garbage25",
                    "boot-mode.kernelopts.garbage26": "garbage26",
                    "boot-mode.kernelopts.garbage27": "garbage27",
                    "boot-mode.kernelopts.garbage28": "garbage28",
                    "boot-mode.kernelopts.garbage29": "garbage29",
                    "boot-mode.kernelopts.garbage30": "garbage30",
                    "boot-mode.kernelopts.garbage31": "garbage31",
                    "boot-mode.kernelopts.garbage32": "garbage32",
                    "boot-mode.kernelopts.garbage33": "garbage33",
                    "boot-mode.kernelopts.garbage34": "garbage34",
                    "boot-mode.kernelopts.garbage35": "garbage35",
                    "boot-mode.kernelopts.garbage36": "garbage36",
                    "boot-mode.kernelopts.garbage37": "garbage37",
                    "boot-mode.kernelopts.garbage38": "garbage38",
                    "boot-mode.kernelopts.garbage39": "garbage39",
                    "boot-mode.kernelopts.garbage40": "garbage40",
                    "boot-mode.kernelopts.garbage41": "garbage41",
                    "boot-mode.kernelopts.garbage42": "garbage42",
                    "boot-mode.kernelopts.garbage43": "garbage43",
                    "boot-mode.kernelopts.garbage44": "garbage44",
                    "boot-mode.kernelopts.garbage45": "garbage45",
                    "boot-mode.kernelopts.garbage46": "garbage46",
                    "boot-mode.kernelopts.garbage47": "garbage47",
                    "boot-mode.kernelopts.garbage48": "garbage48",
                    "boot-mode.kernelopts.garbage49": "garbage49",
                    "boot-mode.kernelopts.garbage50": "garbage50",
                    "boot-mode.kernelopts.garbage51": "garbage51",
                    "boot-mode.kernelopts.garbage52": "garbage52",
                    "boot-mode.kernelopts.garbage53": "garbage53",
                    "boot-mode.kernelopts.garbage54": "garbage54",
                    "boot-mode.kernelopts.garbage55": "garbage55",
                    "boot-mode.kernelopts.garbage56": "garbage56",
                    "boot-mode.kernelopts.garbage57": "garbage57",
                    "boot-mode.kernelopts.garbage58": "garbage58",
                    "boot-mode.kernelopts.garbage59": "garbage59",
                    "boot-mode.kernelopts.garbage60": "garbage60",
                    "boot-mode.kernelopts.garbage61": "garbage61",
                    "boot-mode.kernelopts.garbage62": "garbage62",
                    "boot-mode.kernelopts.garbage63": "garbage63",
                    "boot-mode.kernelopts.garbage64": "garbage64",
                    "boot-mode.kernelopts.garbage65": "garbage65",
                },
            )
        )
        self.assertListEqual(
            self.vm.mock_calls,
            [
                ("features.items", (), {}),
                (
                    "features.__delitem__",
                    ("boot-mode.kernelopts.garbage1",),
                    {},
                ),
                (
                    "features.__delitem__",
                    ("boot-mode.kernelopts.garbage2",),
                    {},
                ),
                (
                    "features.__delitem__",
                    ("boot-mode.kernelopts.garbage3",),
                    {},
                ),
                (
                    "features.__delitem__",
                    ("boot-mode.kernelopts.garbage4",),
                    {},
                ),
                (
                    "features.__delitem__",
                    ("boot-mode.kernelopts.garbage5",),
                    {},
                ),
                (
                    "features.__delitem__",
                    ("boot-mode.kernelopts.garbage6",),
                    {},
                ),
                (
                    "features.__delitem__",
                    ("boot-mode.kernelopts.garbage7",),
                    {},
                ),
                (
                    "features.__delitem__",
                    ("boot-mode.kernelopts.garbage8",),
                    {},
                ),
                (
                    "features.__delitem__",
                    ("boot-mode.kernelopts.garbage9",),
                    {},
                ),
                (
                    "features.__delitem__",
                    ("boot-mode.kernelopts.garbage10",),
                    {},
                ),
                (
                    "features.__setitem__",
                    ("boot-mode.kernelopts.garbage11", "garbage11"),
                    {},
                ),
                (
                    "features.__setitem__",
                    ("boot-mode.kernelopts.garbage12", "garbage12"),
                    {},
                ),
                (
                    "features.__setitem__",
                    ("boot-mode.kernelopts.garbage13", "garbage13"),
                    {},
                ),
                (
                    "features.__setitem__",
                    ("boot-mode.kernelopts.garbage14", "garbage14"),
                    {},
                ),
                (
                    "features.__setitem__",
                    ("boot-mode.kernelopts.garbage15", "garbage15"),
                    {},
                ),
                (
                    "features.__setitem__",
                    ("boot-mode.kernelopts.garbage16", "garbage16"),
                    {},
                ),
                (
                    "features.__setitem__",
                    ("boot-mode.kernelopts.garbage17", "garbage17"),
                    {},
                ),
                (
                    "features.__setitem__",
                    ("boot-mode.kernelopts.garbage18", "garbage18"),
                    {},
                ),
                (
                    "features.__setitem__",
                    ("boot-mode.kernelopts.garbage19", "garbage19"),
                    {},
                ),
                (
                    "features.__setitem__",
                    ("boot-mode.kernelopts.garbage20", "garbage20"),
                    {},
                ),
                (
                    "features.__setitem__",
                    ("boot-mode.kernelopts.garbage21", "garbage21"),
                    {},
                ),
                (
                    "features.__setitem__",
                    ("boot-mode.kernelopts.garbage22", "garbage22"),
                    {},
                ),
                (
                    "features.__setitem__",
                    ("boot-mode.kernelopts.garbage23", "garbage23"),
                    {},
                ),
                (
                    "features.__setitem__",
                    ("boot-mode.kernelopts.garbage24", "garbage24"),
                    {},
                ),
                (
                    "features.__setitem__",
                    ("boot-mode.kernelopts.garbage25", "garbage25"),
                    {},
                ),
                (
                    "features.__setitem__",
                    ("boot-mode.kernelopts.garbage26", "garbage26"),
                    {},
                ),
                (
                    "features.__setitem__",
                    ("boot-mode.kernelopts.garbage27", "garbage27"),
                    {},
                ),
                (
                    "features.__setitem__",
                    ("boot-mode.kernelopts.garbage28", "garbage28"),
                    {},
                ),
                (
                    "features.__setitem__",
                    ("boot-mode.kernelopts.garbage29", "garbage29"),
                    {},
                ),
                (
                    "features.__setitem__",
                    ("boot-mode.kernelopts.garbage30", "garbage30"),
                    {},
                ),
                (
                    "features.__setitem__",
                    ("boot-mode.kernelopts.garbage31", "garbage31"),
                    {},
                ),
                (
                    "features.__setitem__",
                    ("boot-mode.kernelopts.garbage32", "garbage32"),
                    {},
                ),
                (
                    "features.__setitem__",
                    ("boot-mode.kernelopts.garbage33", "garbage33"),
                    {},
                ),
                (
                    "features.__setitem__",
                    ("boot-mode.kernelopts.garbage34", "garbage34"),
                    {},
                ),
                (
                    "features.__setitem__",
                    ("boot-mode.kernelopts.garbage35", "garbage35"),
                    {},
                ),
                (
                    "features.__setitem__",
                    ("boot-mode.kernelopts.garbage36", "garbage36"),
                    {},
                ),
                (
                    "features.__setitem__",
                    ("boot-mode.kernelopts.garbage37", "garbage37"),
                    {},
                ),
                (
                    "features.__setitem__",
                    ("boot-mode.kernelopts.garbage38", "garbage38"),
                    {},
                ),
                (
                    "features.__setitem__",
                    ("boot-mode.kernelopts.garbage39", "garbage39"),
                    {},
                ),
                (
                    "features.__setitem__",
                    ("boot-mode.kernelopts.garbage40", "garbage40"),
                    {},
                ),
                (
                    "features.__setitem__",
                    ("boot-mode.kernelopts.garbage41", "garbage41"),
                    {},
                ),
                (
                    "features.__setitem__",
                    ("boot-mode.kernelopts.garbage42", "garbage42"),
                    {},
                ),
                (
                    "features.__setitem__",
                    ("boot-mode.kernelopts.garbage43", "garbage43"),
                    {},
                ),
                (
                    "features.__setitem__",
                    ("boot-mode.kernelopts.garbage44", "garbage44"),
                    {},
                ),
                (
                    "features.__setitem__",
                    ("boot-mode.kernelopts.garbage45", "garbage45"),
                    {},
                ),
                (
                    "features.__setitem__",
                    ("boot-mode.kernelopts.garbage46", "garbage46"),
                    {},
                ),
                (
                    "features.__setitem__",
                    ("boot-mode.kernelopts.garbage47", "garbage47"),
                    {},
                ),
                (
                    "features.__setitem__",
                    ("boot-mode.kernelopts.garbage48", "garbage48"),
                    {},
                ),
                (
                    "features.__setitem__",
                    ("boot-mode.kernelopts.garbage49", "garbage49"),
                    {},
                ),
                (
                    "features.__setitem__",
                    ("boot-mode.kernelopts.garbage50", "garbage50"),
                    {},
                ),
                (
                    "features.__setitem__",
                    ("boot-mode.kernelopts.garbage51", "garbage51"),
                    {},
                ),
                (
                    "features.__setitem__",
                    ("boot-mode.kernelopts.garbage52", "garbage52"),
                    {},
                ),
                (
                    "features.__setitem__",
                    ("boot-mode.kernelopts.garbage53", "garbage53"),
                    {},
                ),
                (
                    "features.__setitem__",
                    ("boot-mode.kernelopts.garbage54", "garbage54"),
                    {},
                ),
                (
                    "features.__setitem__",
                    ("boot-mode.kernelopts.garbage55", "garbage55"),
                    {},
                ),
                (
                    "features.__setitem__",
                    ("boot-mode.kernelopts.garbage56", "garbage56"),
                    {},
                ),
                (
                    "features.__setitem__",
                    ("boot-mode.kernelopts.garbage57", "garbage57"),
                    {},
                ),
                (
                    "features.__setitem__",
                    ("boot-mode.kernelopts.garbage58", "garbage58"),
                    {},
                ),
                (
                    "features.__setitem__",
                    ("boot-mode.kernelopts.garbage59", "garbage59"),
                    {},
                ),
                (
                    "features.__setitem__",
                    ("boot-mode.kernelopts.garbage60", "garbage60"),
                    {},
                ),
                (
                    "features.__setitem__",
                    ("boot-mode.kernelopts.garbage61", "garbage61"),
                    {},
                ),
                (
                    "features.__setitem__",
                    ("boot-mode.kernelopts.garbage62", "garbage62"),
                    {},
                ),
                (
                    "features.__setitem__",
                    ("boot-mode.kernelopts.garbage63", "garbage63"),
                    {},
                ),
                (
                    "features.__setitem__",
                    ("boot-mode.kernelopts.garbage64", "garbage64"),
                    {},
                ),
                (
                    "features.__setitem__",
                    ("boot-mode.kernelopts.garbage65", "garbage65"),
                    {},
                ),
                ("features.get", ("qrexec", False), {}),
                ("features.get", ("qrexec", False), {}),
            ],
        )

    def test_048_bootmode_defaultname(self):
        del self.vm.template
        self.loop.run_until_complete(
            self.ext.qubes_features_request(
                self.vm,
                "features-request",
                untrusted_features={
                    "boot-mode.name.vmreq": "VMReq",
                    "boot-mode.kernelopts.vmreq": "vmreq1 vmreq2",
                    "boot-mode.name.default": "No Params",
                },
            )
        )
        self.assertListEqual(
            self.vm.mock_calls,
            [
                ("features.items", (), {}),
                (
                    "features.__setitem__",
                    ("boot-mode.kernelopts.vmreq", "vmreq1 vmreq2"),
                    {},
                ),
                (
                    "features.__setitem__",
                    ("boot-mode.name.vmreq", "VMReq"),
                    {},
                ),
                (
                    "features.__setitem__",
                    ("boot-mode.name.default", "No Params"),
                    {},
                ),
                ("features.get", ("qrexec", False), {}),
                ("features.get", ("qrexec", False), {}),
            ],
        )

    def test_049_bootmode_multidots(self):
        del self.vm.template
        self.loop.run_until_complete(
            self.ext.qubes_features_request(
                self.vm,
                "features-request",
                untrusted_features={
                    "boot-mode.name.vmreq": "VMReq",
                    "boot-mode.kernelopts.vmreq": "vmreq1 vmreq2",
                    "boot-mode.name.vmreq.two": "VMReq Two",
                    "boot-mode.kernelopts.vmreq.two": "vmreqtwo1 vmreqtwo2",
                },
            )
        )
        self.assertListEqual(
            self.vm.mock_calls,
            [
                ("features.items", (), {}),
                (
                    "features.__setitem__",
                    ("boot-mode.kernelopts.vmreq", "vmreq1 vmreq2"),
                    {},
                ),
                (
                    "features.__setitem__",
                    ("boot-mode.name.vmreq", "VMReq"),
                    {},
                ),
                ("features.get", ("qrexec", False), {}),
                ("features.get", ("qrexec", False), {}),
            ],
        )

    def test_050_bootmode_noid(self):
        del self.vm.template
        self.loop.run_until_complete(
            self.ext.qubes_features_request(
                self.vm,
                "features-request",
                untrusted_features={
                    "boot-mode.name.vmreq": "VMReq",
                    "boot-mode.kernelopts.vmreq": "vmreq1 vmreq2",
                    "boot-mode.name.": "Ghost",
                    "boot-mode.kernelopts.": "ghost",
                },
            )
        )
        self.assertListEqual(
            self.vm.mock_calls,
            [
                ("features.items", (), {}),
                (
                    "features.__setitem__",
                    ("boot-mode.kernelopts.vmreq", "vmreq1 vmreq2"),
                    {},
                ),
                (
                    "features.__setitem__",
                    ("boot-mode.name.vmreq", "VMReq"),
                    {},
                ),
                ("features.get", ("qrexec", False), {}),
                ("features.get", ("qrexec", False), {}),
            ],
        )

    def test_051_bootmode_defaultkernelopts(self):
        del self.vm.template
        self.loop.run_until_complete(
            self.ext.qubes_features_request(
                self.vm,
                "features-request",
                untrusted_features={
                    "boot-mode.name.vmreq": "VMReq",
                    "boot-mode.kernelopts.vmreq": "vmreq1 vmreq2",
                    "boot-mode.kernelopts.default": "default_kernelopts",
                },
            )
        )
        self.assertListEqual(
            self.vm.mock_calls,
            [
                ("features.items", (), {}),
                (
                    "features.__setitem__",
                    ("boot-mode.kernelopts.vmreq", "vmreq1 vmreq2"),
                    {},
                ),
                (
                    "features.__setitem__",
                    ("boot-mode.name.vmreq", "VMReq"),
                    {},
                ),
                ("features.get", ("qrexec", False), {}),
                ("features.get", ("qrexec", False), {}),
            ],
        )

    def test_052_bootmode_active_appvm_default(self):
        del self.vm.template
        self.vm.bootmode = ""
        self.vm.appvm_default_bootmode = ""
        self.loop.run_until_complete(
            self.ext.qubes_features_request(
                self.vm,
                "features-request",
                untrusted_features={
                    "boot-mode.name.vmreq1": "VMReq1",
                    "boot-mode.kernelopts.vmreq1": "vmreq1-1 vmreq1-2",
                    "boot-mode.name.vmreq2": "VMReq2",
                    "boot-mode.kernelopts.vmreq2": "vmreq2-1 vmreq2-2",
                    "boot-mode.active": "vmreq1",
                    "boot-mode.appvm-default": "vmreq2",
                },
            )
        )
        self.assertListEqual(
            self.vm.mock_calls,
            [
                ("features.items", (), {}),
                (
                    "features.__setitem__",
                    ("boot-mode.kernelopts.vmreq1", "vmreq1-1 vmreq1-2"),
                    {},
                ),
                (
                    "features.__setitem__",
                    ("boot-mode.kernelopts.vmreq2", "vmreq2-1 vmreq2-2"),
                    {},
                ),
                (
                    "features.__setitem__",
                    ("boot-mode.name.vmreq1", "VMReq1"),
                    {},
                ),
                (
                    "features.__setitem__",
                    ("boot-mode.name.vmreq2", "VMReq2"),
                    {},
                ),
                (
                    "features.__contains__",
                    ("boot-mode.kernelopts.vmreq1",),
                    {},
                ),
                (
                    "features.__setitem__",
                    ("boot-mode.active", "vmreq1"),
                    {},
                ),
                (
                    "features.__contains__",
                    ("boot-mode.kernelopts.vmreq2",),
                    {},
                ),
                (
                    "features.__setitem__",
                    ("boot-mode.appvm-default", "vmreq2"),
                    {},
                ),
                ("features.get", ("qrexec", False), {}),
                ("features.get", ("qrexec", False), {}),
            ],
        )

    def test_053_bootmode_active_appvm_default_mod(self):
        del self.vm.template
        self.vm.bootmode = ""
        self.vm.appvm_default_bootmode = ""
        self.features["boot-mode.kernelopts.old1"] = "oldopts1"
        self.features["boot-mode.active"] = "old1"
        self.features["boot-mode.kernelopts.old2"] = "oldopts2"
        self.features["boot-mode.appvm-default"] = "old2"
        self.loop.run_until_complete(
            self.ext.qubes_features_request(
                self.vm,
                "features-request",
                untrusted_features={
                    "boot-mode.name.vmreq1": "VMReq1",
                    "boot-mode.kernelopts.vmreq1": "vmreq1-1 vmreq1-2",
                    "boot-mode.name.vmreq2": "VMReq2",
                    "boot-mode.kernelopts.vmreq2": "vmreq2-1 vmreq2-2",
                    "boot-mode.active": "vmreq1",
                    "boot-mode.appvm-default": "vmreq2",
                },
            )
        )
        self.assertListEqual(
            self.vm.mock_calls,
            [
                ("features.items", (), {}),
                (
                    "features.__delitem__",
                    ("boot-mode.kernelopts.old1",),
                    {},
                ),
                (
                    "features.__delitem__",
                    ("boot-mode.kernelopts.old2",),
                    {},
                ),
                (
                    "features.__setitem__",
                    ("boot-mode.kernelopts.vmreq1", "vmreq1-1 vmreq1-2"),
                    {},
                ),
                (
                    "features.__setitem__",
                    ("boot-mode.kernelopts.vmreq2", "vmreq2-1 vmreq2-2"),
                    {},
                ),
                (
                    "features.__setitem__",
                    ("boot-mode.name.vmreq1", "VMReq1"),
                    {},
                ),
                (
                    "features.__setitem__",
                    ("boot-mode.name.vmreq2", "VMReq2"),
                    {},
                ),
                (
                    "features.__contains__",
                    ("boot-mode.kernelopts.vmreq1",),
                    {},
                ),
                (
                    "features.__setitem__",
                    ("boot-mode.active", "vmreq1"),
                    {},
                ),
                (
                    "features.__contains__",
                    ("boot-mode.kernelopts.vmreq2",),
                    {},
                ),
                (
                    "features.__setitem__",
                    ("boot-mode.appvm-default", "vmreq2"),
                    {},
                ),
                ("features.get", ("qrexec", False), {}),
                ("features.get", ("qrexec", False), {}),
            ],
        )

    def test_054_bootmode_active_appvm_default_wrong(self):
        del self.vm.template
        self.vm.bootmode = ""
        self.vm.appvm_default_bootmode = ""
        self.loop.run_until_complete(
            self.ext.qubes_features_request(
                self.vm,
                "features-request",
                untrusted_features={
                    "boot-mode.name.vmreq": "VMReq",
                    "boot-mode.kernelopts.vmreq": "vmreq1 vmreq2",
                    "boot-mode.active": "nonexistent1",
                    "boot-mode.appvm-default": "nonexistent2",
                },
            )
        )
        self.assertListEqual(
            self.vm.mock_calls,
            [
                ("features.items", (), {}),
                (
                    "features.__setitem__",
                    ("boot-mode.kernelopts.vmreq", "vmreq1 vmreq2"),
                    {},
                ),
                (
                    "features.__setitem__",
                    ("boot-mode.name.vmreq", "VMReq"),
                    {},
                ),
                (
                    "features.__contains__",
                    ("boot-mode.kernelopts.nonexistent1",),
                    {},
                ),
                (
                    "features.__contains__",
                    ("boot-mode.kernelopts.nonexistent2",),
                    {},
                ),
                ("features.get", ("qrexec", False), {}),
                ("features.get", ("qrexec", False), {}),
            ],
        )

    def test_055_bootmode_preserve_oldvals(self):
        del self.vm.template
        self.features["boot-mode.name.old1"] = "Old1"
        self.features["boot-mode.kernelopts.old1"] = "oldopts1"
        self.features["boot-mode.name.old2"] = "Old2"
        self.features["boot-mode.kernelopts.old2"] = "oldopts2"
        self.loop.run_until_complete(
            self.ext.qubes_features_request(
                self.vm,
                "features-request",
                untrusted_features={
                    "boot-mode.name.old1": "Old1",
                    "boot-mode.kernelopts.old1": "oldopts1",
                    "boot-mode.name.old2": "Old2",
                    "boot-mode.kernelopts.old2": "oldopts2",
                },
            )
        )
        self.assertListEqual(
            self.vm.mock_calls,
            [
                ("features.items", (), {}),
                (
                    "features.__setitem__",
                    ("boot-mode.kernelopts.old1", "oldopts1"),
                    {},
                ),
                (
                    "features.__setitem__",
                    ("boot-mode.kernelopts.old2", "oldopts2"),
                    {},
                ),
                (
                    "features.__setitem__",
                    ("boot-mode.name.old1", "Old1"),
                    {},
                ),
                (
                    "features.__setitem__",
                    ("boot-mode.name.old2", "Old2"),
                    {},
                ),
                ("features.get", ("qrexec", False), {}),
                ("features.get", ("qrexec", False), {}),
            ],
        )

    def test_056_bootmode_default_user(self):
        del self.vm.template
        self.loop.run_until_complete(
            self.ext.qubes_features_request(
                self.vm,
                "features-request",
                untrusted_features={
                    "boot-mode.name.vmreq": "VMReq",
                    "boot-mode.kernelopts.vmreq": "vmreq1 vmreq2",
                    "boot-mode.default-user.vmreq": "altuser",
                },
            )
        )
        self.assertListEqual(
            self.vm.mock_calls,
            [
                ("features.items", (), {}),
                (
                    "features.__setitem__",
                    ("boot-mode.kernelopts.vmreq", "vmreq1 vmreq2"),
                    {},
                ),
                (
                    "features.__setitem__",
                    ("boot-mode.name.vmreq", "VMReq"),
                    {},
                ),
                (
                    "features.__setitem__",
                    ("boot-mode.default-user.vmreq", "altuser"),
                    {},
                ),
                ("features.get", ("qrexec", False), {}),
                ("features.get", ("qrexec", False), {}),
            ],
        )

    def test_056_bootmode_default_user_mismatch(self):
        del self.vm.template
        self.loop.run_until_complete(
            self.ext.qubes_features_request(
                self.vm,
                "features-request",
                untrusted_features={
                    "boot-mode.name.vmreq": "VMReq",
                    "boot-mode.kernelopts.vmreq": "vmreq1 vmreq2",
                    "boot-mode.default-user.nope": "altuser",
                },
            )
        )
        self.assertListEqual(
            self.vm.mock_calls,
            [
                ("features.items", (), {}),
                (
                    "features.__setitem__",
                    ("boot-mode.kernelopts.vmreq", "vmreq1 vmreq2"),
                    {},
                ),
                (
                    "features.__setitem__",
                    ("boot-mode.name.vmreq", "VMReq"),
                    {},
                ),
                ("features.get", ("qrexec", False), {}),
                ("features.get", ("qrexec", False), {}),
            ],
        )

    def test_057_bootmode_default_user_default_bootmode(self):
        del self.vm.template
        self.loop.run_until_complete(
            self.ext.qubes_features_request(
                self.vm,
                "features-request",
                untrusted_features={
                    "boot-mode.default-user.default": "altuser",
                },
            )
        )
        self.assertListEqual(
            self.vm.mock_calls,
            [
                ("features.items", (), {}),
                ("features.get", ("qrexec", False), {}),
                ("features.get", ("qrexec", False), {}),
            ],
        )

    def test_100_servicevm_feature(self):
        self.vm.provides_network = True
        self.ext.set_servicevm_feature(self.vm)
        self.assertEqual(self.features["servicevm"], 1)

        self.vm.provides_network = False
        self.ext.set_servicevm_feature(self.vm)
        self.assertNotIn("servicevm", self.features)


class TC_10_WindowsFeatures(qubes.tests.QubesTestCase):
    def setUp(self):
        super().setUp()
        self.ext = qubes.ext.windows.WindowsFeatures()
        self.vm = mock.MagicMock()
        self.template_features = {}
        self.features = {}
        self.vm.configure_mock(
            **{
                "features.get.side_effect": self.features.get,
                "features.check_with_template.side_effect": self.mock_check_with_template,
                "features.__contains__.side_effect": self.features.__contains__,
                "features.__setitem__.side_effect": self.features.__setitem__,
            }
        )

    def mock_check_with_template(self, name, default):
        if hasattr(self.vm, "template"):
            return self.features.get(
                name, self.template_features.get(name, default)
            )
        else:
            return self.features.get(name, default)

    def test_000_notify_tools_full(self):
        del self.vm.template
        self.ext.qubes_features_request(
            self.vm,
            "features-request",
            untrusted_features={
                "gui": "1",
                "version": "1",
                "default-user": "user",
                "qrexec": "1",
                "os": "Windows",
            },
        )
        self.assertEqual(
            self.features,
            {
                "os": "Windows",
                "rpc-clipboard": True,
                "stubdom-qrexec": True,
                "audio-model": "ich6",
                "timezone": "localtime",
                "no-monitor-layout": True,
            },
        )
        self.assertEqual(self.vm.maxmem, 0)
        self.assertEqual(self.vm.qrexec_timeout, 6000)

    def test_001_notify_tools_no_qrexec(self):
        del self.vm.template
        self.ext.qubes_features_request(
            self.vm,
            "features-request",
            untrusted_features={
                "gui": "1",
                "version": "1",
                "default-user": "user",
                "qrexec": "0",
                "os": "Windows",
            },
        )
        self.assertEqual(
            self.features,
            {
                "os": "Windows",
            },
        )

    def test_002_notify_tools_other_os(self):
        del self.vm.template
        self.ext.qubes_features_request(
            self.vm,
            "features-request",
            untrusted_features={
                "gui": "1",
                "version": "1",
                "default-user": "user",
                "qrexec": "1",
                "os": "other",
            },
        )
        self.assertEqual(self.features, {})

    def test_003_notify_tools_no_override(self):
        del self.vm.template
        self.features["audio-model"] = "ich9"
        self.ext.qubes_features_request(
            self.vm,
            "features-request",
            untrusted_features={
                "gui": "1",
                "version": "1",
                "default-user": "user",
                "qrexec": "1",
                "os": "Windows",
            },
        )
        self.assertEqual(
            self.features,
            {
                "os": "Windows",
                "rpc-clipboard": True,
                "stubdom-qrexec": True,
                "audio-model": "ich9",
                "timezone": "localtime",
                "no-monitor-layout": True,
            },
        )


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
        self.test_base_dir = "/tmp/qubes-test-dir"
        self.base_dir_patch = mock.patch.dict(
            qubes.config.system_path, {"dom0_services_dir": self.test_base_dir}
        )
        self.base_dir_patch.start()
        self.addCleanup(self.base_dir_patch.stop)
        service = "guivm-gui-agent"
        service_path = self.test_base_dir + "/" + service

        self.ext.on_domain_feature_set(
            self.dom0,
            "feature-set:service.service.guivm-gui-agent",
            "service.guivm-gui-agent",
            "1",
        )
        self.assertEqual(os.path.exists(service_path), True)

    def test_014_feature_delete_dom0(self):
        self.test_base_dir = "/tmp/qubes-test-dir"
        self.base_dir_patch = mock.patch.dict(
            qubes.config.system_path, {"dom0_services_dir": self.test_base_dir}
        )
        self.base_dir_patch.start()
        self.addCleanup(self.base_dir_patch.stop)
        service = "guivm-gui-agent"
        service_path = self.test_base_dir + "/" + service

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
        self.test_base_dir = "/tmp/qubes-test-dir"
        self.base_dir_patch = mock.patch.dict(
            qubes.config.system_path, {"dom0_services_dir": self.test_base_dir}
        )
        self.base_dir_patch.start()
        self.addCleanup(self.base_dir_patch.stop)
        service = "guivm-gui-agent"
        service_path = self.test_base_dir + "/" + service

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
        with self.assertRaises(qubes.exc.PermissionDenied):
            self.ext.on_feature_set_or_remove(
                "test-vm1",
                "admin-permission:admin.vm.feature.Set",
                feature,
            )

    def test_000_tags_permission(self):
        tag = "created-by-test"
        with self.assertRaises(qubes.exc.PermissionDenied):
            self.ext.on_tag_set_or_remove(
                "test-vm1",
                "admin-permission:admin.vm.tag.Set",
                tag,
            )
