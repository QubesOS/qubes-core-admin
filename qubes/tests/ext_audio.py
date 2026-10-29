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

    def qdb_not_ready(self, vm, qdb):
        # First access returns None (QubesDB not up yet). A second access
        # would return qdb.
        return mock.patch.object(
            type(vm),
            "untrusted_qdb",
            new_callable=mock.PropertyMock,
            side_effect=[None, qdb],
            create=True,
        )

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

    def test_001_domain_start_qdb_not_ready(self):
        self.audiovm.xid = 42
        qdb = mock.MagicMock()
        with mock.patch.object(
            self.ext, "attached_vms", return_value=[self.client]
        ), mock.patch.object(
            self.client, "is_running", return_value=True
        ), self.qdb_not_ready(
            self.client, qdb
        ):
            self.ext.on_domain_start(self.audiovm, "domain-start")
        qdb.write.assert_not_called()

    def test_002_domain_start_skips_qdb_not_ready(self):
        self.audiovm.xid = 42
        qdb = mock.MagicMock()
        self.client_alt.name = "client-alt"
        with mock.patch.object(
            self.ext,
            "attached_vms",
            return_value=[self.client, self.client_alt],
        ), mock.patch.object(
            self.client, "is_running", return_value=True
        ), mock.patch.object(
            self.client_alt, "is_running", return_value=True
        ), self.qdb_not_ready(
            self.client, qdb
        ):
            self.ext.on_domain_start(self.audiovm, "domain-start")
        qdb.write.assert_not_called()
        self.client_alt.untrusted_qdb.write.assert_called_once_with(
            "/qubes-audio-domain-xid", "42"
        )

    def test_003_set_qubesdb_audiovm_qdb_not_ready(self):
        self.audiovm.xid = 42
        self.audiovm.is_running.return_value = True
        self.client.is_running.return_value = True
        self.client.audiovm = self.audiovm
        qdb = mock.MagicMock()
        with self.qdb_not_ready(self.client, qdb):
            self.ext.set_qubesdb_audiovm(self.client)
        qdb.write.assert_not_called()

    def test_004_set_qubesdb_audiovm_none_qdb_not_ready(self):
        self.client.is_running.return_value = True
        self.client.audiovm = None
        qdb = mock.MagicMock()
        with self.qdb_not_ready(self.client, qdb):
            self.ext.set_qubesdb_audiovm(self.client)
        qdb.rm.assert_not_called()

    def test_005_qdb_ready_later(self):
        self.audiovm.xid = 42
        self.audiovm.is_running.return_value = True
        self.client.is_running.return_value = True
        self.client.audiovm = self.audiovm
        self.client.untrusted_qdb = None
        self.ext.set_qubesdb_audiovm(self.client)
        qdb = mock.MagicMock()
        self.client.untrusted_qdb = qdb
        self.ext.on_domain_qdb_create(self.client, "domain-qdb-create")
        qdb.write.assert_called_once_with("/qubes-audio-domain-xid", "42")
