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

import qubes.ext.core_features
import qubes.tests


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
                (
                    "log.warning",
                    ("Ignoring qubes.NotifyTools for template-based VM",),
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
                ("log.warning", mock.ANY, {}),
                ("log.warning", mock.ANY, {}),
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
                ("log.warning", mock.ANY, {}),
                ("log.warning", mock.ANY, {}),
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

    def test_058_bootmode_standalone_default_good(self):
        del self.vm.template
        self.loop.run_until_complete(
            self.ext.qubes_features_request(
                self.vm,
                "features-request",
                untrusted_features={
                    "boot-mode.kernelopts.orig-mode": "test1",
                    "boot-mode.kernelopts.new-mode": "test2",
                    "boot-mode.standalone-default": "new-mode",
                },
            )
        )
        self.assertListEqual(
            self.vm.mock_calls,
            [
                ("features.items", (), {}),
                (
                    "features.__setitem__",
                    ("boot-mode.kernelopts.orig-mode", "test1"),
                    {},
                ),
                (
                    "features.__setitem__",
                    ("boot-mode.kernelopts.new-mode", "test2"),
                    {},
                ),
                (
                    "features.__contains__",
                    ("boot-mode.kernelopts.new-mode",),
                    {},
                ),
                (
                    "features.__setitem__",
                    ("boot-mode.standalone-default", "new-mode"),
                    {},
                ),
                ("features.get", ("qrexec", False), {}),
                ("features.get", ("qrexec", False), {}),
            ],
        )

    def test_059_bootmode_standalone_default_bad(self):
        del self.vm.template
        self.loop.run_until_complete(
            self.ext.qubes_features_request(
                self.vm,
                "features-request",
                untrusted_features={
                    "boot-mode.kernelopts.orig-mode": "test1",
                    "boot-mode.kernelopts.new-mode": "test2",
                    "boot-mode.standalone-default": "missing-mode",
                },
            )
        )
        self.assertListEqual(
            self.vm.mock_calls,
            [
                ("features.items", (), {}),
                (
                    "features.__setitem__",
                    ("boot-mode.kernelopts.orig-mode", "test1"),
                    {},
                ),
                (
                    "features.__setitem__",
                    ("boot-mode.kernelopts.new-mode", "test2"),
                    {},
                ),
                (
                    "features.__contains__",
                    ("boot-mode.kernelopts.missing-mode",),
                    {},
                ),
                ("features.get", ("qrexec", False), {}),
                ("features.get", ("qrexec", False), {}),
            ],
        )

    def test_060_anon_timezone_set(self):
        del self.vm.template
        self.loop.run_until_complete(
            self.ext.qubes_features_request(
                self.vm,
                "features-request",
                untrusted_features={
                    "anon-timezone": "1",
                },
            )
        )
        self.assertListEqual(
            self.vm.mock_calls,
            [
                ("features.items", (), {}),
                ("features.__setitem__", ("anon-timezone", True), {}),
                ("features.get", ("qrexec", False), {}),
                ("features.get", ("qrexec", False), {}),
            ],
        )

    def test_061_anon_timezone_prevent_unset(self):
        del self.vm.template
        self.loop.run_until_complete(
            self.ext.qubes_features_request(
                self.vm,
                "features-request",
                untrusted_features={
                    "anon-timezone": "0",
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
