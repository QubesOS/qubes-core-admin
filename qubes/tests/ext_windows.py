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

import qubes.ext.windows
import qubes.tests


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
                "features.check_with_template.side_effect": self.mock_check_tpl,
                "features.__contains__.side_effect": self.features.__contains__,
                "features.__setitem__.side_effect": self.features.__setitem__,
            }
        )

    def mock_check_tpl(self, name, default):
        if hasattr(self.vm, "template"):
            return self.features.get(
                name, self.template_features.get(name, default)
            )
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
