# -*- encoding: utf-8 -*-
#
# The Qubes OS Project, http://www.qubes-os.org
#
# Copyright (C) 2019 Marek Marczykowski-Górecki
#                               <marmarek@invisiblethingslab.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, see <http://www.gnu.org/licenses/>.
import asyncio
import qubes.api.internal
import qubes.tests
import qubes.vm.adminvm
from unittest import mock
import json
import uuid


def mock_coro(f):
    async def coro_f(*args, **kwargs):
        return f(*args, **kwargs)

    return coro_f


TEST_UUID = uuid.UUID("50c7dad4-5f1e-4586-9f6a-bf10a86ba6f0")


class TC_00_API_Misc(qubes.tests.QubesTestCase):
    maxDiff = None

    def setUp(self):
        super().setUp()
        self.app = mock.NonCallableMock()
        self.dom0 = mock.NonCallableMock(spec=qubes.vm.adminvm.AdminVM)
        self.dom0.name = "dom0"
        self.dom0.features = {}
        self.domains = {
            "dom0": self.dom0,
        }
        self.app.domains = mock.MagicMock(
            **{
                "__iter__.side_effect": lambda: iter(self.domains.values()),
                "__getitem__.side_effect": self.domains.get,
            }
        )

    def tearDown(self):
        self.domains.clear()
        self.dom0 = None
        super().tearDown()

    def create_mockvm(self, features=None):
        if features is None:
            features = {}
        vm = mock.Mock()
        vm.features.check_with_template.side_effect = features.get
        vm.features.get.side_effect = features.get
        vm.run_service.return_value.wait = mock_coro(
            vm.run_service.return_value.wait
        )
        vm.run_service = mock_coro(vm.run_service)
        vm.suspend = mock_coro(vm.suspend)
        vm.resume = mock_coro(vm.resume)
        return vm

    def call_mgmt_func(self, method, arg=b"", payload=b""):
        mgmt_obj = qubes.api.internal.QubesInternalAPI(
            self.app, b"dom0", method, b"dom0", arg
        )

        loop = asyncio.get_event_loop()
        response = loop.run_until_complete(
            mgmt_obj.execute(untrusted_payload=payload)
        )
        return response

    def test_000_suspend_pre(self):
        running_vm = self.create_mockvm(features={"qrexec": True})
        running_vm.is_running.return_value = True

        not_running_vm = self.create_mockvm(features={"qrexec": True})
        not_running_vm.is_running.return_value = False

        no_qrexec_vm = self.create_mockvm()
        no_qrexec_vm.is_running.return_value = True

        paused_vm = self.create_mockvm(features={"qrexec": True})
        paused_vm.is_running.return_value = True
        paused_vm.get_power_state.return_value = "Paused"
        paused_vm.name = "SleepingBeauty"

        self.domains.update(
            {
                "running": running_vm,
                "not-running": not_running_vm,
                "no-qrexec": no_qrexec_vm,
                "paused": paused_vm,
            }
        )

        with mock.patch.object(
            qubes.api.internal,
            "PREVIOUSLY_PAUSED",
            "/tmp/qubes-previously-paused.tmp",
        ):
            ret = self.call_mgmt_func(b"internal.SuspendPre")
        self.assertIsNone(ret)
        self.assertFalse(self.dom0.called)

        self.assertNotIn(
            ("run_service", ("qubes.SuspendPreAll",), mock.ANY),
            not_running_vm.mock_calls,
        )
        self.assertNotIn(("suspend", (), {}), not_running_vm.mock_calls)

        self.assertIn(
            ("run_service", ("qubes.SuspendPreAll",), mock.ANY),
            running_vm.mock_calls,
        )
        self.assertIn(("suspend", (), {}), running_vm.mock_calls)

        self.assertNotIn(
            ("run_service", ("qubes.SuspendPreAll",), mock.ANY),
            no_qrexec_vm.mock_calls,
        )

        self.assertNotIn(
            ("run_service", ("qubes.SuspendPreAll",), mock.ANY),
            paused_vm.mock_calls,
        )
        self.assertIn(("suspend", (), {}), running_vm.mock_calls)

        self.assertIn(("suspend", (), {}), no_qrexec_vm.mock_calls)

    def test_001_suspend_post(self):
        running_vm = self.create_mockvm(features={"qrexec": True})
        running_vm.is_running.return_value = True
        running_vm.get_power_state.return_value = "Suspended"

        not_running_vm = self.create_mockvm(features={"qrexec": True})
        not_running_vm.is_running.return_value = False
        not_running_vm.get_power_state.return_value = "Halted"

        no_qrexec_vm = self.create_mockvm()
        no_qrexec_vm.is_running.return_value = True
        no_qrexec_vm.get_power_state.return_value = "Suspended"

        paused_vm = self.create_mockvm(features={"qrexec": True})
        paused_vm.is_running.return_value = True
        paused_vm.get_power_state.return_value = "Paused"
        paused_vm.name = "SleepingBeauty"

        self.domains.update(
            {
                "running": running_vm,
                "not-running": not_running_vm,
                "no-qrexec": no_qrexec_vm,
                "paused": paused_vm,
            }
        )

        with mock.patch.object(
            qubes.api.internal,
            "PREVIOUSLY_PAUSED",
            "/tmp/qubes-previously-paused.tmp",
        ):
            ret = self.call_mgmt_func(b"internal.SuspendPost")
        self.assertIsNone(ret)
        self.assertFalse(self.dom0.called)

        self.assertNotIn(
            ("run_service", ("qubes.SuspendPostAll",), mock.ANY),
            not_running_vm.mock_calls,
        )
        self.assertNotIn(("resume", (), {}), not_running_vm.mock_calls)

        self.assertIn(
            ("run_service", ("qubes.SuspendPostAll",), mock.ANY),
            running_vm.mock_calls,
        )
        self.assertIn(("resume", (), {}), running_vm.mock_calls)

        self.assertNotIn(
            ("run_service", ("qubes.SuspendPostAll",), mock.ANY),
            no_qrexec_vm.mock_calls,
        )
        self.assertIn(("resume", (), {}), no_qrexec_vm.mock_calls)

        self.assertNotIn(
            ("run_service", ("qubes.SuspendPostAll",), mock.ANY),
            paused_vm.mock_calls,
        )
        self.assertNotIn(("resume", (), {}), paused_vm.mock_calls)

    def test_010_get_system_info(self):
        self.dom0.name = "dom0"
        self.dom0.features = {}
        self.dom0.tags = ["tag1", "tag2"]
        self.dom0.default_dispvm = None
        self.dom0.template_for_dispvms = False
        self.dom0.label.icon = "icon-dom0"
        self.dom0.get_power_state.return_value = "Running"
        self.dom0.uuid = uuid.UUID("00000000-0000-0000-0000-000000000000")
        del self.dom0.guivm

        vm = mock.NonCallableMock(spec=qubes.vm.qubesvm.QubesVM)
        vm.name = "vm"
        vm.features = {"internal": 1}
        vm.tags = ["tag3", "tag4"]
        vm.default_dispvm = vm
        vm.template_for_dispvms = True
        vm.label.icon = "icon-vm"
        vm.guivm = vm
        vm.get_power_state.return_value = "Halted"
        vm.uuid = TEST_UUID
        self.domains["vm"] = vm

        expected_data = {
            "domains": {
                "dom0": {
                    "tags": ["tag1", "tag2"],
                    "type": "AdminVM",
                    "default_dispvm": None,
                    "template_for_dispvms": False,
                    "icon": "icon-dom0",
                    "internal": None,
                    "guivm": None,
                    "power_state": "Running",
                    "relayvm": None,
                    "transport_rpc": None,
                    "uuid": "00000000-0000-0000-0000-000000000000",
                },
                "vm": {
                    "tags": ["tag3", "tag4"],
                    "type": "QubesVM",
                    "default_dispvm": "vm",
                    "template_for_dispvms": True,
                    "icon": "icon-vm",
                    "internal": 1,
                    "guivm": "vm",
                    "power_state": "Halted",
                    "relayvm": None,
                    "transport_rpc": None,
                    "uuid": str(TEST_UUID),
                },
            }
        }
        ret = json.loads(self.call_mgmt_func(b"internal.GetSystemInfo"))
        self.assertEqual(
            ret,
            expected_data,
        )

        # test if data got cached (should give outdated answer without events)
        vm.tags = ["tag4", "tag5"]
        ret = json.loads(self.call_mgmt_func(b"internal.GetSystemInfo"))
        self.assertEqual(
            ret,
            expected_data,
        )

        # and if the cache got invalidated on event
        vm.add_handler.mock_calls[0][1][1](vm, "domain-tag-add:test4")
        expected_data["domains"]["vm"]["tags"] = ["tag4", "tag5"]
        ret = json.loads(self.call_mgmt_func(b"internal.GetSystemInfo"))
        self.assertEqual(
            ret,
            expected_data,
        )
