#
# The Qubes OS Project, http://www.qubes-os.org
#
# Copyright (C) 2016 Marek Marczykowski-Górecki
#                                        <marmarek@invisiblethingslab.com>
# Copyright (C) 2025 Benjamin Grande <ben.grande.b@gmail.com>
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
import contextlib
import grp
import os
import pwd
import subprocess
import time
import unittest
from contextlib import suppress
from distutils import spawn
from unittest.mock import patch, mock_open
import asyncio
import sys
import logging

import qubes.config
import qubes.tests
import qubesadmin.exc

# nose will duplicate this logger.
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
handler = logging.StreamHandler()
formatter = logging.Formatter(
    "%(asctime)s: %(levelname)s: %(funcName)s: %(message)s"
)
handler.setFormatter(formatter)
logger.addHandler(handler)


class TC_04_DispVM(qubes.tests.SystemTestCase):
    def setUp(self):
        super(TC_04_DispVM, self).setUp()
        self.init_default_template()
        self.disp_base = self.app.add_new_vm(
            qubes.vm.appvm.AppVM,
            name=self.make_vm_name("dvm"),
            label="red",
        )
        self.loop.run_until_complete(self.disp_base.create_on_disk())
        self.disp_base.template_for_dispvms = True
        self.loop.run_until_complete(self.start_vm(self.disp_base))
        self.shutdown_and_wait(self.disp_base)
        self.app.default_dispvm = self.disp_base
        self.testvm = self.app.add_new_vm(
            qubes.vm.appvm.AppVM,
            name=self.make_vm_name("vm"),
            label="red",
        )
        self.loop.run_until_complete(self.testvm.create_on_disk())
        self.app.save()
        # used in test_01x
        self.startup_counter = 0

    def tearDown(self):
        self.app.default_dispvm = None
        super(TC_04_DispVM, self).tearDown()

    def wait_for_dispvm_destroy(self, dispvm_name: list):
        timeout = 20
        while dispvm_name in self.app.domains:
            self.loop.run_until_complete(asyncio.sleep(1))
            timeout -= 1
            if timeout <= 0:
                break

    def test_002_cleanup(self):
        self.loop.run_until_complete(self.testvm.start())

        try:
            (stdout, _) = self.loop.run_until_complete(
                self.testvm.run_for_stdio(
                    "qvm-run-vm --dispvm bash",
                    input=b"echo test; qubesdb-read /name; echo ERROR\n",
                )
            )
        except subprocess.CalledProcessError as err:
            self.fail(
                "qvm-run-vm failed with {} code, stderr: {}".format(
                    err.returncode, err.stderr
                )
            )
        lines = stdout.decode("ascii").splitlines()
        self.assertEqual(lines[0], "test")
        dispvm_name = lines[1]
        # wait for actual DispVM destruction
        self.wait_for_dispvm_destroy(dispvm_name)
        self.assertNotIn(dispvm_name, self.app.domains)

    def test_003_cleanup_destroyed(self):
        """
        Check if DispVM is properly removed even if it terminated itself (#1660)
        :return:
        """

        self.loop.run_until_complete(self.testvm.start())

        p = self.loop.run_until_complete(
            self.testvm.run(
                "qvm-run-vm --dispvm bash; true",
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
            )
        )
        p.stdin.write(b"qubesdb-read /name\n")
        p.stdin.write(b"echo ERROR\n")
        p.stdin.write(b"sudo poweroff\n")
        # do not close p.stdin on purpose - wait to automatic disconnect when
        #  domain is destroyed
        timeout = 80
        lines_task = asyncio.ensure_future(p.stdout.read())
        self.loop.run_until_complete(asyncio.wait_for(p.wait(), timeout))
        self.loop.run_until_complete(lines_task)
        lines = lines_task.result().splitlines()
        self.assertTrue(lines, "No output received from DispVM")
        dispvm_name = lines[0]
        self.assertNotEqual(dispvm_name, b"ERROR")

        self.assertNotIn(dispvm_name, self.app.domains)

    def _count_dispvms(self, *args, **kwargs):
        self.startup_counter += 1

    def test_010_failed_start(self):
        """
        Check if DispVM doesn't (attempt to) start twice.
        :return:
        """
        self.app.add_handler("domain-add", self._count_dispvms)
        self.addCleanup(
            self.app.remove_handler, "domain-add", self._count_dispvms
        )

        # make it fail to start
        self.app.default_dispvm.memory = self.app.host.memory_total * 2

        self.loop.run_until_complete(self.testvm.start())

        p = self.loop.run_until_complete(
            self.testvm.run(
                "qvm-run-vm --dispvm true",
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
            )
        )
        timeout = 120
        self.loop.run_until_complete(asyncio.wait_for(p.communicate(), timeout))
        self.assertEqual(p.returncode, 126)
        self.assertEqual(self.startup_counter, 1)

    def test_011_failed_start_timeout(self):
        """
        Check if DispVM doesn't (attempt to) start twice.
        :return:
        """
        self.app.add_handler("domain-add", self._count_dispvms)
        self.addCleanup(
            self.app.remove_handler, "domain-add", self._count_dispvms
        )

        # make it fail to start (timeout)
        self.app.default_dispvm.qrexec_timeout = 3

        self.loop.run_until_complete(self.testvm.start())

        p = self.loop.run_until_complete(
            self.testvm.run(
                "qvm-run-vm --dispvm true",
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
            )
        )
        timeout = 120
        self.loop.run_until_complete(asyncio.wait_for(p.communicate(), timeout))
        self.assertEqual(p.returncode, 126)
        self.assertEqual(self.startup_counter, 1)


class TC_20_DispVMMixin(object):
    def setUp(self):  # pylint: disable=invalid-name
        logger.info("start")
        super(TC_20_DispVMMixin, self).setUp()
        if "whonix-g" in self.template:
            self.skipTest(
                "whonix gateway is not supported as DisposableVM Template"
            )
        self.app.add_handler("domain-add", self._on_domain_add)
        self.addCleanup(
            self.app.remove_handler, "domain-add", self._on_domain_add
        )
        self.adminvm = self.app.domains["dom0"]
        self.init_default_template(self.template)
        self.disp_base = self.app.add_new_vm(
            qubes.vm.appvm.AppVM,
            name=self.make_vm_name("dvm"),
            label="red",
            template_for_dispvms=True,
        )
        self.loop.run_until_complete(self.disp_base.create_on_disk())
        self.disp_base_alt = self.app.add_new_vm(
            qubes.vm.appvm.AppVM,
            name=self.make_vm_name("dvm-alt"),
            label="red",
            template_for_dispvms=True,
        )
        self.loop.run_until_complete(self.disp_base_alt.create_on_disk())
        start_tasks = [
            self.start_vm(self.disp_base),
            self.start_vm(self.disp_base_alt),
        ]
        shutdown_tasks = [
            self.disp_base.shutdown(wait=True),
            self.disp_base_alt.shutdown(wait=True),
        ]
        self.loop.run_until_complete(asyncio.gather(*start_tasks))
        self.loop.run_until_complete(asyncio.gather(*shutdown_tasks))
        # Setting "default_dispvm" fires the preload event before patches of
        # each test function is applied.
        if "_preload_" not in self._testMethodName:
            self.app.default_dispvm = self.disp_base
        self.cleanup_preload()
        self.app.save()
        self.preload_cmd = [
            "qvm-run",
            "-p",
            "--no-color-output",
            "--no-color-stderr",
            f"--dispvm={self.disp_base.name}",
            "--",
            "qubesdb-read /name | tr -d '\n'",
        ]
        logger.info("end")

    def tearDown(self):  # pylint: disable=invalid-name
        logger.info("start")
        if "gui" in self.disp_base.features:
            del self.disp_base.features["gui"]
        self.cleanup_preload()
        # See comment in setUp().
        if "_preload_" not in self._testMethodName:
            self.app.default_dispvm = None
        self.app.save()
        super(TC_20_DispVMMixin, self).tearDown()
        logger.info("end")

    def _test_event_handler(
        self, vm, event, *args, **kwargs
    ):  # pylint: disable=unused-argument
        if not hasattr(self, "event_handler"):
            self.event_handler = {}
        logger.info("%s[%s]", vm.name, event)
        self.event_handler.setdefault(vm.name, {}).setdefault(event, 0)
        self.event_handler[vm.name][event] += 1

    def _test_event_handler_remove(self, vm, event):
        if not hasattr(self, "event_handler"):
            self.event_handler = {}
        logger.info("%s[%s]", vm.name, event)
        self.event_handler.setdefault(vm.name, {})[event] = 0

    def _test_event_was_handled(self, vm, event):
        if not hasattr(self, "event_handler"):
            self.event_handler = {}
        return self.event_handler.get(vm, {}).get(event)

    def _register_handlers(self, vm):  # pylint: disable=unused-argument
        events = [
            # appvm
            "domain-preload-dispvm-autostart",
            "domain-preload-dispvm-start",
            "domain-preload-dispvm-used",
            # dispvm
            "domain-feature-set:preload-dispvm-in-progress",
            "domain-feature-delete:preload-dispvm-in-progress",
            "domain-feature-set:preload-dispvm-completed",
            "domain-paused",
            "domain-unpaused",
            "domain-feature-delete:internal",
            # debug
            "domain-shutdown",
        ]
        for event in events:
            vm.add_handler(event, self._test_event_handler)

    def _on_domain_add(self, app, event, vm):  # pylint: disable=unused-argument
        self._register_handlers(vm)

    async def cleanup_preload_run(self, qube):
        old_preload = qube.get_feat_preload()
        tasks = [self.app.domains[x].cleanup() for x in old_preload]
        await asyncio.gather(*tasks)

    def cleanup_preload(self):
        logger.info("start")
        default_dispvm = self.app.default_dispvm
        # Clean features from all qubes to avoid them being considered by
        # tests that target preloads on the whole system, such as
        # `/usr/lib/qubes/preload-dispvm`.
        if "preload-dispvm-threshold" in self.app.domains["dom0"].features:
            logger.info("deleting global threshold feature")
            del self.app.domains["dom0"].features["preload-dispvm-threshold"]
        for qube in self.app.domains:
            if "preload-dispvm-max" not in qube.features:
                continue
            logger.info("removing preloaded disposables: '%s'", qube.name)
            if qube == default_dispvm:
                self.loop.run_until_complete(
                    self.cleanup_preload_run(default_dispvm)
                )
            logger.info("deleting max preload feature")
            del qube.features["preload-dispvm-max"]
        logger.info("end")

    async def no_preload(self):
        # Trick to gather this function as an async task.
        await asyncio.sleep(0)
        self.disp_base.features["preload-dispvm-max"] = False

    def log_preload(self):
        preload_dict = {}
        default_dispvm = self.app.default_dispvm
        global_preload_max = None
        if default_dispvm:
            global_preload_max = default_dispvm.get_feat_global_preload_max()
        threshold = self.adminvm.features.get("preload-dispvm-threshold", None)
        preload_dict["global"] = {
            "name": default_dispvm.name if default_dispvm else None,
            "max": global_preload_max,
            "threshold": threshold,
        }
        for qube in [self.disp_base, self.disp_base_alt]:
            preload = qube.get_feat_preload()
            preload_max = qube.get_feat_preload_max()
            preload_dict[qube.name] = {"max": preload_max, "list": preload}
        logger.info(preload_dict)

    async def wait_preload(
        self,
        preload_max,
        appvm=None,
        wait_completion=True,
        fail_on_timeout=True,
        timeout=60,
    ):
        """Waiting for completion avoids coroutine objects leaking."""
        logger.info("start")
        if not appvm:
            appvm = self.disp_base
        for _ in range(timeout):
            preload_dispvm = appvm.get_feat_preload()
            if len(preload_dispvm) == preload_max:
                break
            await asyncio.sleep(1)
        else:
            if fail_on_timeout:
                self.fail("didn't preload in time")
        if not wait_completion:
            logger.info("end")
            return
        preload_dispvm = appvm.get_feat_preload()
        preload_unfinished = preload_dispvm
        for _ in range(timeout):
            for qube in preload_unfinished.copy():
                if self.app.domains[qube].preload_complete.is_set():
                    logger.info("preload completed for '%s'", qube)
                    preload_unfinished.remove(qube)
                    continue
            if not preload_unfinished:
                break
            await asyncio.sleep(1)
        else:
            if fail_on_timeout:
                self.fail("last preloaded didn't complete in time")
        logger.info("end")

    def wait_for_dispvm_destroy(self, dispvm_names):
        logger.info("start")
        timeout = 20
        while True:
            if set(dispvm_names).isdisjoint(self.app.domains):
                break
            self.loop.run_until_complete(asyncio.sleep(1))
            timeout -= 1
            if timeout <= 0:
                self.fail("didn't destroy dispvm(s) in time")
        logger.info("end")

    async def run_preload_proc(self):
        logger.info("start")
        proc = await asyncio.create_subprocess_exec(
            *self.preload_cmd,
            stdout=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.DEVNULL,
        )
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=60)
            return stdout.decode()
        except asyncio.TimeoutError:
            proc.terminate()
            await proc.wait()
            raise
        finally:
            logger.info("end")

    async def run_preload(self):
        logger.info("start")
        appvm = self.disp_base
        dispvm = appvm.get_feat_preload()[0]
        dispvm = self.app.domains[dispvm]
        self.assertTrue(dispvm.is_preload)
        self.assertTrue(dispvm.features.get("internal", False))
        dispvm_name = dispvm.name
        self._test_event_handler_remove(appvm, "domain-preload-dispvm-start")
        self._test_event_handler_remove(dispvm, "domain-unpaused")

        stdout = await self.run_preload_proc()
        self.assertEqual(stdout, dispvm_name)
        test_cases = [
            (False, appvm.name, "domain-preload-dispvm-autostart", True),
            (False, appvm.name, "domain-preload-dispvm-start", True),
            (True, appvm.name, "domain-preload-dispvm-used", True),
            (
                True,
                dispvm_name,
                "domain-feature-set:preload-dispvm-in-progress",
                True,
            ),
            (
                True,
                dispvm_name,
                "domain-feature-delete:preload-dispvm-in-progress",
                True,
            ),
            (
                True,
                dispvm_name,
                "domain-feature-set:preload-dispvm-completed",
                True,
            ),
            (
                True,
                dispvm_name,
                "domain-unpaused",
                self._test_event_was_handled(dispvm_name, "domain-paused"),
            ),
            (
                True,
                dispvm_name,
                "domain-feature-delete:internal",
                not appvm.features.get("internal", False),
            ),
        ]
        for assert_type, qube, event, test in test_cases:
            with self.subTest(
                assert_type=assert_type, qube=qube, event=event, test=test
            ):
                if test:
                    event_result = self._test_event_was_handled(qube, event)
                    if assert_type:
                        self.assertTrue(event_result)
                    else:
                        self.assertFalse(event_result)
        next_preload_list = appvm.get_feat_preload()
        self.assertTrue(next_preload_list)
        self.assertNotIn(dispvm_name, next_preload_list)
        logger.info("end")

    def test_010_dvm_run_simple(self):
        dispvm = self.loop.run_until_complete(
            qubes.vm.dispvm.DispVM.from_appvm(self.disp_base)
        )
        try:
            self.loop.run_until_complete(dispvm.start())
            (stdout, _) = self.loop.run_until_complete(
                dispvm.run_service_for_stdio(
                    "qubes.VMShell", input=b"echo test"
                )
            )
            self.assertEqual(stdout, b"test\n")
        finally:
            self.loop.run_until_complete(dispvm.cleanup())

    def test_011_preload_reject_max(self):
        """Test preloading when max has been reached"""
        self.loop.run_until_complete(
            qubes.vm.dispvm.DispVM.from_appvm(self.disp_base, preload=True)
        )
        self.assertEqual(0, len(self.disp_base.get_feat_preload()))

    def test_012_preload_low_mem(self):
        """Test preloading with low memory"""
        self.loop.run_until_complete(self._test_012_preload_low_mem())

    async def _test_012_preload_low_mem(self):
        # pylint: disable=unspecified-encoding
        logger.info("start")
        unpatched_open = open
        memory = int(getattr(self.disp_base, "memory", 0) * 1024**2)

        def mock_open_mem(file, *args, **kwargs):
            if file == qubes.config.qmemman_avail_mem_file:
                return mock_open(read_data=str(memory))()
            return unpatched_open(file, *args, **kwargs)

        def mock_open_mem_threshold(file, *args, **kwargs):
            if file == qubes.config.qmemman_avail_mem_file:
                return mock_open(read_data=str(memory * 2))()
            return unpatched_open(file, *args, **kwargs)

        preload_max = 2
        with patch("builtins.open", side_effect=mock_open_mem):
            logger.info("low mem standard")
            self.disp_base.features["preload-dispvm-max"] = str(preload_max)
            await self.wait_preload(
                preload_max, fail_on_timeout=False, timeout=15
            )
            self.assertEqual(1, len(self.disp_base.get_feat_preload()))
            # Nothing will be done here, just to prepare to the next test.
            self.disp_base.features["preload-dispvm-max"] = str(preload_max - 1)

        with patch("builtins.open", side_effect=mock_open_mem_threshold):
            logger.info("low mem threshold")
            self.adminvm.features["preload-dispvm-threshold"] = memory
            self.disp_base.features["preload-dispvm-max"] = str(preload_max)
            await self.wait_preload(
                preload_max, fail_on_timeout=False, timeout=15
            )
            self.assertEqual(1, len(self.disp_base.get_feat_preload()))

        logger.info("end")

    def test_013_preload_gui(self):
        """Test preloading with GUI feature enabled and use after
        completion."""
        self.loop.run_until_complete(self._test_013_preload_gui())

    async def _test_013_preload_gui(self):
        logger.info("start")
        preload_max = 1
        self.disp_base.features["gui"] = True
        self.disp_base.features["preload-dispvm-max"] = str(preload_max)
        await self.wait_preload(preload_max)
        await self.run_preload()
        logger.info("end")

    def test_014_preload_nogui(self):
        """Test preloading with GUI feature disabled and use before
        completion."""
        self.loop.run_until_complete(self._test_014_preload_nogui())

    async def _test_014_preload_nogui(self):
        logger.info("start")
        preload_max = 1
        self.disp_base.features["gui"] = False
        self.disp_base.features["preload-dispvm-max"] = str(preload_max)
        await self.wait_preload(preload_max, wait_completion=False)
        self.preload_cmd.insert(1, "--no-gui")
        await self.run_preload()
        logger.info("end")

    def test_015_preload_race_more(self):
        """Test race requesting multiple preloaded qubes"""
        self.loop.run_until_complete(self._test_015_preload_race_more())

    async def _test_015_preload_race_more(self):
        # The limiting factor is how much memory is available on OpenQA:
        # Whonix (Kicksecure) 17 fail more due to higher memory consumption.
        # From the templates deployed by default, only Debian and Fedora
        # survives due to using less memory than the other OSes.
        logger.info("start")
        preload_max = 3
        # dist = self.disp_base.features.check_with_template("os-distribution")
        # if dist in ["whonix", "kicksecure"]:
        #     preload_max -= 1
        self.disp_base.features["preload-dispvm-max"] = str(preload_max)
        await self.wait_preload(preload_max)
        old_preload = self.disp_base.get_feat_preload()
        tasks = [self.run_preload_proc() for _ in range(preload_max)]
        targets = await asyncio.gather(*tasks)
        await self.wait_preload(preload_max)
        preload_dispvm = self.disp_base.get_feat_preload()
        self.assertTrue(set(old_preload).isdisjoint(preload_dispvm))
        self.assertEqual(len(targets), preload_max)
        self.assertEqual(len(targets), len(set(targets)))
        logger.info("end")

    def test_016_preload_race_less(self):
        """Test race requesting preloaded qube while the maximum is zeroed."""
        self.loop.run_until_complete(self._test_016_preload_race_less())

    async def _test_016_preload_race_less(self):
        logger.info("start")
        preload_max = 1
        self.disp_base.features["preload-dispvm-max"] = str(preload_max)
        await self.wait_preload(preload_max, wait_completion=False)
        tasks = [self.run_preload_proc(), self.no_preload()]
        target = await asyncio.gather(*tasks)
        target_dispvm = target[0]
        self.assertTrue(target_dispvm.startswith("disp"))
        logger.info("end")

    def test_017_preload_autostart(self):
        """The script triggers the API call
        'admin.vm.CreateDisposable+preload-autostart' which fires the event
        'domain-preload-dispvm-autostart', clearing the current preload list
        and filling with new ones."""
        logger.info("start")
        self.app.default_dispvm = self.disp_base

        preload_max = 1
        logger.info("no refresh to be made")
        proc = self.loop.run_until_complete(
            asyncio.create_subprocess_exec("/usr/lib/qubes/preload-dispvm")
        )
        self.loop.run_until_complete(
            asyncio.wait_for(proc.communicate(), timeout=10)
        )
        self.assertEqual(self.disp_base.get_feat_preload(), [])

        logger.info("refresh to be made")
        self.disp_base.features["preload-dispvm-max"] = str(preload_max)
        self.loop.run_until_complete(self.wait_preload(preload_max))
        old_preload = self.disp_base.get_feat_preload()
        proc = self.loop.run_until_complete(
            asyncio.create_subprocess_exec("/usr/lib/qubes/preload-dispvm")
        )
        self.loop.run_until_complete(asyncio.wait_for(proc.wait(), timeout=40))
        preload_dispvm = self.disp_base.get_feat_preload()
        self.assertEqual(len(old_preload), preload_max)
        self.assertEqual(len(preload_dispvm), preload_max)
        self.assertTrue(
            set(old_preload).isdisjoint(preload_dispvm),
            f"old_preload={old_preload} preload_dispvm={preload_dispvm}",
        )

        logger.info("global refresh to be made")
        preload_max += 1
        self.adminvm.features["preload-dispvm-max"] = str(preload_max)
        self.loop.run_until_complete(self.wait_preload(preload_max))
        del self.disp_base.features["preload-dispvm-max"]
        old_preload = self.disp_base.get_feat_preload()
        proc = self.loop.run_until_complete(
            asyncio.create_subprocess_exec("/usr/lib/qubes/preload-dispvm")
        )
        self.loop.run_until_complete(asyncio.wait_for(proc.wait(), timeout=40))
        preload_dispvm = self.disp_base.get_feat_preload()
        self.assertEqual(len(old_preload), preload_max)
        self.assertEqual(len(preload_dispvm), preload_max)
        self.assertTrue(
            set(old_preload).isdisjoint(preload_dispvm),
            f"old_preload={old_preload} preload_dispvm={preload_dispvm}",
        )

        self.app.default_dispvm = None
        logger.info("end")

    def test_018_preload_global(self):
        """Tweak global preload setting and global dispvm."""
        self.loop.run_until_complete(self._test_018_preload_global())

    async def _test_018_preload_global(self):
        logger.info("start")
        self.log_preload()
        preload_max = 1

        logger.info("set global dispvm")
        self.app.default_dispvm = self.disp_base
        logger.info("set global feat, state must change")
        self.adminvm.features["preload-dispvm-max"] = str(preload_max)
        await self.wait_preload(preload_max)

        self.log_preload()
        logger.info("set local feat, state must not change")
        preload_max += 1
        self.disp_base.features["preload-dispvm-max"] = str(preload_max)
        await self.wait_preload(preload_max, fail_on_timeout=False, timeout=15)
        self.assertEqual(len(self.disp_base.get_feat_preload()), 1)

        self.log_preload()
        logger.info("del local feat, state must not change")
        del self.disp_base.features["preload-dispvm-max"]
        await asyncio.sleep(5)
        self.assertEqual(len(self.disp_base.get_feat_preload()), 1)

        self.log_preload()
        logger.info("set local feat and del global feat, state must change")
        self.disp_base.features["preload-dispvm-max"] = str(preload_max)
        del self.adminvm.features["preload-dispvm-max"]
        await self.wait_preload(preload_max)

        self.log_preload()
        logger.info("del local feat and set global feat, state must change")
        preload_max -= 1
        preload_remove = self.app.default_dispvm.get_feat_preload()
        self.disp_base.features["preload-dispvm-max"] = ""
        self.wait_for_dispvm_destroy(preload_remove)
        self.adminvm.features["preload-dispvm-max"] = str(preload_max)
        await self.wait_preload(preload_max)
        self.assertEqual(len(self.disp_base.get_feat_preload()), preload_max)

        self.log_preload()
        logger.info("switch global dispvm, state must change")
        self.app.default_dispvm = self.disp_base_alt
        await self.wait_preload(preload_max, appvm=self.disp_base_alt)

        self.log_preload()
        logger.info("set local feat, state must not change")
        preload_max += 1
        self.disp_base.features["preload-dispvm-max"] = str(preload_max)
        await self.wait_preload(preload_max)

        self.log_preload()
        logger.info("switch back global dispvm, state must change")
        preload_remove = self.app.default_dispvm.get_feat_preload()
        self.app.default_dispvm = self.disp_base
        self.wait_for_dispvm_destroy(preload_remove)
        await self.wait_preload(preload_max)

        self.log_preload()
        logger.info("unset global dispvm, state must change")
        preload_remove = self.app.default_dispvm.get_feat_preload()
        self.app.default_dispvm = None
        self.wait_for_dispvm_destroy(preload_remove)

        self.log_preload()
        logger.info("end")

    def test_019_preload_refresh(self):
        """Refresh preload on volume change."""
        self.loop.run_until_complete(self._test_019_preload_refresh())

    async def _test_019_preload_refresh(self):
        logger.info("start")
        self.log_preload()
        preload_max = 1

        self.disp_base.features["preload-dispvm-max"] = str(preload_max)
        for qube in [self.disp_base, self.disp_base.template]:
            await self.wait_preload(preload_max)
            old_preload = self.disp_base.get_feat_preload()
            await qube.start()
            # If services are still starting, it may delay shutdown longer than
            # the default timeout. Because we can't just kill default
            # templates, wait gracefully for system services to have started.
            await qube.run_service_for_stdio("qubes.WaitForRunningSystem")
            logger.info("shutdown '%s'", qube.name)
            await qube.shutdown(wait=True)
            await self.wait_preload(preload_max)
            preload_dispvm = self.disp_base.get_feat_preload()
            self.assertTrue(
                set(old_preload).isdisjoint(preload_dispvm),
                f"old_preload={old_preload} preload_dispvm={preload_dispvm}",
            )

        self.log_preload()
        logger.info("end")

    @unittest.skipUnless(
        spawn.find_executable("xdotool"), "xdotool not installed"
    )
    def test_020_gui_app(self):
        dispvm = self.loop.run_until_complete(
            qubes.vm.dispvm.DispVM.from_appvm(self.disp_base)
        )
        try:
            self.loop.run_until_complete(dispvm.start())
            self.loop.run_until_complete(self.wait_for_session(dispvm))
            p = self.loop.run_until_complete(
                dispvm.run_service(
                    "qubes.VMShell",
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                )
            )
            # wait for DispVM startup:
            p.stdin.write(b"echo test\n")
            self.loop.run_until_complete(p.stdin.drain())
            l = self.loop.run_until_complete(p.stdout.readline())
            self.assertEqual(l, b"test\n")

            self.assertTrue(dispvm.is_running())
            try:
                window_title = "user@%s" % (dispvm.name,)
                # close xterm on Return, but after short delay, to allow
                # xdotool to send also keyup event
                p.stdin.write(
                    "xterm -e "
                    '"sh -c \'echo \\"\033]0;{}\007\\";read x;'
                    "sleep 0.1;'\"\n".format(window_title).encode()
                )
                self.loop.run_until_complete(p.stdin.drain())
                self.wait_for_window(window_title)

                time.sleep(0.5)
                self.enter_keys_in_window(window_title, ["Return"])
                # Wait for window to close
                self.wait_for_window(window_title, show=False)
                p.stdin.close()
                self.loop.run_until_complete(asyncio.wait_for(p.wait(), 30))
            except:
                with suppress(ProcessLookupError):
                    p.terminate()
                self.loop.run_until_complete(p.wait())
                raise
            finally:
                del p
        finally:
            self.loop.run_until_complete(dispvm.cleanup())
            dispvm_name = dispvm.name
            del dispvm

        # give it a time for shutdown + cleanup
        self.loop.run_until_complete(asyncio.sleep(5))

        self.assertNotIn(
            dispvm_name, self.app.domains, "DispVM not removed from qubes.xml"
        )

    def _handle_editor(self, winid, copy=False):
        (window_title, _) = subprocess.Popen(
            ["xdotool", "getwindowname", winid], stdout=subprocess.PIPE
        ).communicate()
        window_title = (
            window_title.decode()
            .strip()
            .replace("(", r"\(")
            .replace(")", r"\)")
        )
        time.sleep(1)
        if (
            "gedit" in window_title
            or "KWrite" in window_title
            or "Mousepad" in window_title
            or "Geany" in window_title
            or "Text Editor" in window_title
        ):
            subprocess.check_call(
                ["xdotool", "windowactivate", "--sync", winid]
            )
            if copy:
                subprocess.check_call(
                    [
                        "xdotool",
                        "key",
                        "--window",
                        winid,
                        "key",
                        "ctrl+a",
                        "ctrl+c",
                        "ctrl+shift+c",
                    ]
                )
            else:
                subprocess.check_call(["xdotool", "type", "Test test 2"])
                subprocess.check_call(
                    ["xdotool", "key", "--window", winid, "key", "Return"]
                )
                time.sleep(0.5)
                subprocess.check_call(["xdotool", "key", "ctrl+s"])
            time.sleep(0.5)
            subprocess.check_call(["xdotool", "key", "ctrl+q"])
        elif "LibreOffice" in window_title:
            # wait for actual editor (we've got splash screen)
            search = subprocess.Popen(
                [
                    "xdotool",
                    "search",
                    "--sync",
                    "--onlyvisible",
                    "--all",
                    "--name",
                    "--class",
                    "disp*|Writer",
                ],
                stdout=subprocess.PIPE,
                stderr=open(os.path.devnull, "w"),
            )
            retcode = search.wait()
            if retcode == 0:
                winid = search.stdout.read().strip()
            time.sleep(0.5)
            subprocess.check_call(
                ["xdotool", "windowactivate", "--sync", winid]
            )
            if copy:
                subprocess.check_call(
                    [
                        "xdotool",
                        "key",
                        "--window",
                        winid,
                        "key",
                        "ctrl+a",
                        "ctrl+c",
                        "ctrl+shift+c",
                    ]
                )
            else:
                subprocess.check_call(["xdotool", "type", "Test test 2"])
                subprocess.check_call(
                    ["xdotool", "key", "--window", winid, "key", "Return"]
                )
                time.sleep(0.5)
                subprocess.check_call(
                    ["xdotool", "key", "--delay", "100", "ctrl+s", "Return"]
                )
            time.sleep(0.5)
            subprocess.check_call(["xdotool", "key", "ctrl+q"])
        elif "emacs" in window_title:
            subprocess.check_call(
                ["xdotool", "windowactivate", "--sync", winid]
            )
            if copy:
                subprocess.check_call(
                    ["xdotool", "key", "ctrl+x", "h", "alt+w", "ctrl+shift+c"]
                )
            else:
                subprocess.check_call(["xdotool", "type", "Test test 2"])
                subprocess.check_call(
                    ["xdotool", "key", "--window", winid, "key", "Return"]
                )
                time.sleep(0.5)
                subprocess.check_call(["xdotool", "key", "ctrl+x", "ctrl+s"])
            time.sleep(0.5)
            subprocess.check_call(["xdotool", "key", "ctrl+x", "ctrl+c"])
        elif "vim" in window_title or "user@" in window_title:
            subprocess.check_call(
                ["xdotool", "windowactivate", "--sync", winid]
            )
            if copy:
                raise NotImplementedError("copy not implemented for vim")
            else:
                subprocess.check_call(
                    ["xdotool", "key", "i", "type", "Test test 2"]
                )
                subprocess.check_call(
                    ["xdotool", "key", "--window", winid, "key", "Return"]
                )
                subprocess.check_call(
                    ["xdotool", "key", "Escape", "colon", "w", "q", "Return"]
                )
        else:
            raise KeyError(window_title)

    def _whonix_ws_dispvm_confirm(self, action_str):
        try:
            winid = self.wait_for_window(
                "qrexec-policy-agent",
                search_class=True,
                include_tray=False,
                timeout=5,
            )
        except Exception:
            return (
                False,
                "Failed to find qrexec confirmation window for "
                f"{action_str} action",
            )
        try:
            subprocess.run(
                [
                    "bash",
                    "-c",
                    "--",
                    f"xdotool windowfocus {winid}; sleep 1.1; "
                    "xdotool key enter",
                ],
                check=True,
            )
        except subprocess.CalledProcessError as err:
            return (
                False,
                "Failed to activate qrexec confirmation window for "
                "{} action: exit code {}, {}{}".format(
                    action_str, err.returncode, err.stdout, err.stderr
                ),
            )
        return (True, "")

    @unittest.skipUnless(
        spawn.find_executable("xdotool"), "xdotool not installed"
    )
    def test_030_edit_file(self):
        self.testvm1 = self.app.add_new_vm(
            qubes.vm.appvm.AppVM,
            name=self.make_vm_name("vm1"),
            label="red",
            template=self.app.domains[self.template],
        )
        self.loop.run_until_complete(self.testvm1.create_on_disk())
        self.app.save()

        self.loop.run_until_complete(self.testvm1.start())
        self.loop.run_until_complete(
            self.testvm1.run_for_stdio("echo test1 > /home/user/test.txt")
        )

        p = self.loop.run_until_complete(
            self.testvm1.run(
                "qvm-open-in-dvm /home/user/test.txt",
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
        )

        if "whonix-workstation" in self.template:
            dvm_confirm_rslt = self._whonix_ws_dispvm_confirm("edit file")
            if not dvm_confirm_rslt[0]:
                self.fail(dvm_confirm_rslt[1])

        # if first 5 windows isn't expected editor, there is no hope
        winid = None
        for _ in range(5):
            try:
                winid = self.wait_for_window(
                    "disp[0-9]*",
                    search_class=True,
                    include_tray=False,
                    timeout=60,
                )
            except Exception as e:
                try:
                    self.loop.run_until_complete(asyncio.wait_for(p.wait(), 1))
                except asyncio.TimeoutError:
                    raise e
                else:
                    stdout = self.loop.run_until_complete(p.stdout.read())
                    self.fail(
                        "qvm-open-in-dvm exited prematurely with {}: {}".format(
                            p.returncode, stdout
                        )
                    )
            # let the application initialize
            self.loop.run_until_complete(asyncio.sleep(1))
            try:
                self._handle_editor(winid)
                break
            except KeyError:
                winid = None
        if winid is None:
            self.fail("Timeout waiting for editor window")

        self.loop.run_until_complete(p.communicate())
        (test_txt_content, _) = self.loop.run_until_complete(
            self.testvm1.run_for_stdio("cat /home/user/test.txt")
        )
        # Drop BOM if added by editor
        if test_txt_content.startswith(b"\xef\xbb\xbf"):
            test_txt_content = test_txt_content[3:]
        self.assertEqual(test_txt_content, b"Test test 2\ntest1\n")

    def _get_open_script(self, application):
        """Generate a script to instruct *application* to open *filename*"""
        if application == "org.gnome.Nautilus":
            return (
                "#!/usr/bin/python3\n"
                "import sys, os"
                "from dogtail import tree, config\n"
                "config.config.actionDelay = 1.0\n"
                "config.config.defaultDelay = 1.0\n"
                "config.config.searchCutoffCount = 10\n"
                "app = tree.root.application('org.gnome.Nautilus')\n"
                "app.child(os.path.basename(sys.argv[1])).doubleClick()\n"
            ).encode()
        if application in (
            "mozilla-thunderbird",
            "thunderbird",
            "org.mozilla.thunderbird",
            "net.thunderbird.Thunderbird",
        ):
            with open(
                "/usr/share/qubes/tests-data/"
                "dispvm-open-thunderbird-attachment",
                "rb",
            ) as f:
                return f.read()
        assert False

    def _get_apps_list(self, template):
        try:
            # get first user in the qubes group
            qubes_grp = grp.getgrnam("qubes")
            qubes_user = pwd.getpwnam(qubes_grp.gr_mem[0])
        except KeyError:
            self.skipTest("Cannot find a user in the qubes group")

        desktop_list = os.listdir(
            os.path.join(
                qubes_user.pw_dir,
                f".local/share/qubes-appmenus/{template}/apps.templates",
            )
        )
        return [
            l[: -len(".desktop")]
            for l in desktop_list
            if l.endswith(".desktop")
        ]

    @unittest.skipUnless(
        spawn.find_executable("xdotool"), "xdotool not installed"
    )
    def test_100_open_in_dispvm(self):
        self.testvm1 = self.app.add_new_vm(
            qubes.vm.appvm.AppVM,
            name=self.make_vm_name("vm1"),
            label="red",
            template=self.app.domains[self.template],
        )
        self.loop.run_until_complete(self.testvm1.create_on_disk())
        self.app.save()

        app_id = "mozilla-thunderbird"
        if "debian" in self.template or "whonix" in self.template:
            app_id = "thunderbird"
        # F40+ has org.mozilla.thunderbird
        if "org.mozilla.thunderbird" in self._get_apps_list(self.template):
            app_id = "org.mozilla.thunderbird"
        # F41+ has net.thunderbird.Thunderbird
        if "net.thunderbird.Thunderbird" in self._get_apps_list(self.template):
            app_id = "net.thunderbird.Thunderbird"

        self.testvm1.features["service.app-dispvm." + app_id] = "1"
        self.loop.run_until_complete(self.testvm1.start())
        self.loop.run_until_complete(self.wait_for_session(self.testvm1))
        self.loop.run_until_complete(
            self.testvm1.run_for_stdio("echo test1 > /home/user/test.txt")
        )

        self.loop.run_until_complete(
            self.testvm1.run_for_stdio(
                "cat > /home/user/open-file",
                input=self._get_open_script(app_id),
            )
        )
        self.loop.run_until_complete(
            self.testvm1.run_for_stdio("chmod +x /home/user/open-file")
        )

        # disable donation message as it messes with editor detection
        self.loop.run_until_complete(
            self.testvm1.run_for_stdio(
                "cat > /etc/thunderbird/pref/test.js",
                input=b'pref("app.donation.eoy.version.viewed", 100);\n',
                user="root",
            )
        )

        self.loop.run_until_complete(
            self.testvm1.run_for_stdio(
                "gsettings set org.gnome.desktop.interface "
                "toolkit-accessibility true"
            )
        )

        app = self.loop.run_until_complete(
            self.testvm1.run_service("qubes.StartApp+" + app_id)
        )
        # give application a bit of time to start
        self.loop.run_until_complete(asyncio.sleep(3))

        try:
            click_to_open = self.loop.run_until_complete(
                self.testvm1.run_for_stdio(
                    "./open-file test.txt",
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                )
            )
        except subprocess.CalledProcessError as err:
            with contextlib.suppress(asyncio.TimeoutError):
                self.loop.run_until_complete(asyncio.wait_for(app.wait(), 30))
            if app.returncode == 127:
                self.skipTest("{} not installed".format(app_id))
            self.fail(
                "'./open-file test.txt' failed with {}: {}{}".format(
                    err.cmd, err.returncode, err.stdout, err.stderr
                )
            )

        if "whonix-workstation" in self.template:
            dvm_confirm_rslt = self._whonix_ws_dispvm_confirm("DispVM open")
            if not dvm_confirm_rslt[0]:
                self.fail(dvm_confirm_rslt[1])

        # if first 5 windows isn't expected editor, there is no hope
        winid = None
        for _ in range(5):
            winid = self.wait_for_window(
                "disp[0-9]*", search_class=True, include_tray=False, timeout=60
            )
            # let the application initialize
            self.loop.run_until_complete(asyncio.sleep(1))
            try:
                # copy, not modify - attachment is set as read-only
                self._handle_editor(winid, copy=True)
                break
            except KeyError:
                winid = None
        if winid is None:
            self.fail("Timeout waiting for editor window")

        self.loop.run_until_complete(
            self.wait_for_window_hide_coro("editor", winid)
        )

        with open("/var/run/qubes/qubes-clipboard.bin", "rb") as f:
            test_txt_content = f.read()
        self.assertEqual(test_txt_content.strip(), b"test1")

        # this doesn't really close the application, only the qrexec-client
        # process that started it; but clean it up anyway to not leak processes
        app.terminate()
        self.loop.run_until_complete(app.wait())


def create_testcases_for_templates():
    return qubes.tests.create_testcases_for_templates(
        "TC_20_DispVM",
        TC_20_DispVMMixin,
        qubes.tests.SystemTestCase,
        module=sys.modules[__name__],
    )


def load_tests(loader, tests, pattern):
    tests.addTests(loader.loadTestsFromNames(create_testcases_for_templates()))
    return tests


qubes.tests.maybe_create_testcases_on_import(create_testcases_for_templates)
