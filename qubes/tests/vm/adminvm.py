#
# The Qubes OS Project, https://www.qubes-os.org/
#
# Copyright (C) 2014-2015  Joanna Rutkowska <joanna@invisiblethingslab.com>
# Copyright (C) 2014-2015  Wojtek Porczyk <woju@invisiblethingslab.com>
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
#
import grp
import os
import subprocess
import unittest
import unittest.mock

import qubes
import qubes.exc
import qubes.vm
import qubes.vm.adminvm

import qubes.tests


class TC_00_AdminVM(qubes.tests.QubesTestCase):
    def setUp(self):
        super().setUp()
        self.app = qubes.Qubes(
            "/tmp/qubestest.xml", load=False, offline_mode=True
        )
        self.app.load_initial_values()
        self.vm = self.app.domains["dom0"]
        self.template = self.app.add_new_vm(
            "TemplateVM", name="test-template", label="green"
        )
        self.template.features["qrexec"] = True
        self.template.features["supported-rpc.qubes.WaitForRunningSystem"] = (
            True
        )
        self.appvm = self.app.add_new_vm(
            "AppVM",
            name="test-dvm",
            template=self.template,
            label="red",
        )
        self.appvm.features["gui"] = False
        self.appvm.template_for_dispvms = True
        self.emitter = qubes.tests.TestEmitter()

    def tearDown(self) -> None:
        del self.appvm
        del self.template
        del self.vm
        self.app.close()
        del self.app
        del self.emitter
        try:
            os.unlink("/tmp/qubestest.xml")
        except:  # pylint: disable=bare-except
            pass
        super().tearDown()

    async def coroutine_mock(self, mock, *args, **kwargs):
        return mock(*args, **kwargs)

    def test_000_init(self):
        pass

    def test_001_property_icon(self):
        self.assertEqual(self.vm.icon, "adminvm-black")

    def test_100_xid(self):
        self.assertEqual(self.vm.xid, 0)

    def test_101_libvirt_domain(self):
        with unittest.mock.patch.object(self.app, "vmm") as mock_vmm:
            self.assertIsNotNone(self.vm.libvirt_domain)
            self.assertEqual(
                mock_vmm.mock_calls,
                [
                    ("libvirt_conn.lookupByID", (0,), {}),
                ],
            )

    def test_300_is_running(self):
        self.assertTrue(self.vm.is_running())

    def test_301_get_power_state(self):
        self.assertEqual(self.vm.get_power_state(), "Running")

    def test_302_get_mem(self):
        self.assertGreater(self.vm.get_mem(), 0)

    @unittest.skip("mock object does not support this")
    def test_303_get_mem_static_max(self):
        self.assertGreater(self.vm.get_mem_static_max(), 0)

    def test_310_start(self):
        with self.assertRaises(qubes.exc.QubesException):
            self.vm.start()

    @unittest.skip("this functionality is undecided")
    def test_311_suspend(self):
        with self.assertRaises(qubes.exc.QubesException):
            self.vm.suspend()

    @unittest.mock.patch("asyncio.create_subprocess_exec")
    def test_700_run_service(self, mock_subprocess):
        # if there is a user in 'qubes' group, it should be used by default
        try:
            group = grp.getgrnam("qubes")
            default_user = group.gr_mem[0]
            command_prefix = ["runuser", "-u", default_user, "--"]
        except (KeyError, IndexError):
            command_prefix = []

        with self.subTest("running"):
            self.loop.run_until_complete(self.vm.run_service("test.service"))
            mock_subprocess.assert_called_once_with(
                *command_prefix,
                "/usr/lib/qubes/qubes-rpc-multiplexer",
                "test.service",
                "dom0",
                "name",
                "dom0"
            )

        mock_subprocess.reset_mock()
        with self.subTest("other_user"):
            self.loop.run_until_complete(
                self.vm.run_service("test.service", user="other")
            )
            mock_subprocess.assert_called_once_with(
                "runuser",
                "-u",
                "other",
                "--",
                "/usr/lib/qubes/qubes-rpc-multiplexer",
                "test.service",
                "dom0",
                "name",
                "dom0",
            )

            mock_subprocess.reset_mock()
        with self.subTest("other_source"):
            self.loop.run_until_complete(
                self.vm.run_service("test.service", source=self.appvm.name)
            )
            mock_subprocess.assert_called_once_with(
                *command_prefix,
                "/usr/lib/qubes/qubes-rpc-multiplexer",
                "test.service",
                self.appvm.name,
                "name",
                "dom0"
            )

    @unittest.mock.patch("qubes.vm.adminvm.AdminVM.run_service")
    def test_710_run_service_for_stdio(self, mock_run_service):
        communicate_mock = mock_run_service.return_value.communicate
        communicate_mock.return_value = (b"stdout", b"stderr")
        mock_run_service.return_value.returncode = 0

        with self.subTest("default"):
            value = self.loop.run_until_complete(
                self.vm.run_service_for_stdio("test.service")
            )
            mock_run_service.assert_called_once_with(
                "test.service",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.PIPE,
            )
            communicate_mock.assert_called_once_with(input=None)
            self.assertEqual(value, (b"stdout", b"stderr"))

        mock_run_service.reset_mock()
        communicate_mock.reset_mock()
        with self.subTest("with_input"):
            value = self.loop.run_until_complete(
                self.vm.run_service_for_stdio("test.service", input=b"abc")
            )
            mock_run_service.assert_called_once_with(
                "test.service",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.PIPE,
            )
            communicate_mock.assert_called_once_with(input=b"abc")
            self.assertEqual(value, (b"stdout", b"stderr"))

        mock_run_service.reset_mock()
        communicate_mock.reset_mock()
        with self.subTest("error"):
            mock_run_service.return_value.returncode = 1
            with self.assertRaises(subprocess.CalledProcessError) as exc:
                self.loop.run_until_complete(
                    self.vm.run_service_for_stdio("test.service")
                )
            mock_run_service.assert_called_once_with(
                "test.service",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.PIPE,
            )
            communicate_mock.assert_called_once_with(input=None)
            self.assertEqual(exc.exception.returncode, 1)
            self.assertEqual(exc.exception.output, b"stdout")
            self.assertEqual(exc.exception.stderr, b"stderr")

    def test_711_adminvm_ordering(self):
        assert self.vm < qubes.vm.qubesvm.QubesVM(
            self.app, None, qid=1, name="dom0"
        )

    def test_800_preload_set_max(self):
        self.app.default_dispvm = None
        with unittest.mock.patch.object(
            self.appvm, "fire_event"
        ) as mock_events:
            self.vm.features["preload-dispvm-max"] = "1"
            mock_events.assert_not_called()
        del self.vm.features["preload-dispvm-max"]

        self.app.default_dispvm = self.appvm
        with unittest.mock.patch.object(
            self.appvm, "fire_event"
        ) as mock_sync, unittest.mock.patch.object(
            self.appvm, "fire_event_async"
        ) as mock_async:
            self.vm.features["preload-dispvm-max"] = "1"
            mock_sync.assert_called_once_with(
                "domain-feature-pre-set:preload-dispvm-max",
                pre_event=True,
                feature="preload-dispvm-max",
                value="1",
                oldvalue=None,
            )
            mock_async.assert_called_once_with(
                "domain-preload-dispvm-start", reason=unittest.mock.ANY
            )

        # Setting the feature to the same value it has skips firing the event.
        with unittest.mock.patch.object(
            self.appvm, "fire_event"
        ) as mock_events:
            self.vm.features["preload-dispvm-max"] = "1"
            mock_events.assert_not_called()

    def test_801_preload_del_max(self):
        self.vm.features["preload-dispvm-max"] = "1"
        self.app.default_dispvm = None
        with unittest.mock.patch.object(
            self.appvm, "fire_event_async"
        ) as mock_events:
            del self.vm.features["preload-dispvm-max"]
            mock_events.assert_not_called()

        self.vm.features["preload-dispvm-max"] = "1"
        self.app.default_dispvm = self.appvm
        with unittest.mock.patch.object(
            self.appvm, "fire_event_async"
        ) as mock_events:
            del self.vm.features["preload-dispvm-max"]
            mock_events.assert_called_once_with(
                "domain-preload-dispvm-start", reason=unittest.mock.ANY
            )

    def test_802_preload_set_threshold(self):
        cases_valid = ["", "0", "1"]
        cases_invalid = ["a", "-1", "1 1"]
        for value in cases_invalid:
            with self.subTest(value=value):
                with self.assertRaises(qubes.exc.QubesValueError):
                    self.vm.features["preload-dispvm-threshold"] = value
        for value in cases_valid:
            with self.subTest(value=value):
                self.vm.features["preload-dispvm-threshold"] = value

    def test_803_preload_set_delay(self):
        cases_valid = ["", "0", "1", "-1", "3.14"]
        cases_invalid = ["a", ".2.", "1 1"]
        for value in cases_invalid:
            with self.subTest(value=value):
                with self.assertRaises(qubes.exc.QubesValueError):
                    self.vm.features["preload-dispvm-delay"] = value
        for value in cases_valid:
            with self.subTest(value=value):
                self.vm.features["preload-dispvm-delay"] = value
