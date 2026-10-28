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

import qubes.ext.audio
import qubes.tests


class TC_60_Audio(qubes.tests.QubesTestCase):
    def setUp(self):
        super().setUp()
        self.ext = qubes.ext.audio.AUDIO()
        self.audiovm = mock.MagicMock()
        self.audiovm.name = "sys-audio"
        self.client = mock.MagicMock()
        self.client.name = "client"
        self.client_alt = mock.MagicMock()
        self.client_alt.name = "client"

    def test_000_shutdown(self):
        self.ext.on_domain_pre_shutdown(
            self.audiovm,
            "domain-pre-shutdown",
        )

    def test_000_shutdown_used(self):
        with mock.patch.object(
            self.ext, "attached_vms", return_value=[self.client]
        ), mock.patch.object(self.client, "is_running", return_value=True):
            self.client.is_preload = False
            with self.assertRaises(qubes.exc.QubesVMInUseError):
                self.ext.on_domain_pre_shutdown(
                    self.audiovm,
                    "domain-pre-shutdown",
                )

            self.client.is_preload = True
            self.ext.on_domain_pre_shutdown(
                self.audiovm,
                "domain-pre-shutdown",
            )

    def test_000_shutdown_used_by_some(self):
        with mock.patch.object(
            self.ext,
            "attached_vms",
            return_value=[self.client, self.client_alt],
        ), mock.patch.object(
            self.client, "is_running", return_value=True
        ), mock.patch.object(
            self.client_alt, "is_running", return_value=True
        ):
            self.client.is_preload = False
            self.client_alt.is_preload = True
            with self.assertRaises(qubes.exc.QubesVMInUseError):
                self.ext.on_domain_pre_shutdown(
                    self.audiovm,
                    "domain-pre-shutdown",
                )

