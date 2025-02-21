#
# The Qubes OS Project, http://www.qubes-os.org
#
# Copyright (C) 2016 Marek Marczykowski-Górecki
#                                        <marmarek@invisiblethingslab.com>
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

import qubes.config
import qubes.tests
import qubesadmin.exc


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

    def wait_for_dispvm_destroy(self, dispvm_name):
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
        super(TC_20_DispVMMixin, self).setUp()
        if "whonix-g" in self.template:
            self.skipTest(
                "whonix gateway is not supported as DisposableVM Template"
            )
        self.init_default_template(self.template)
        self.disp_base = self.app.add_new_vm(
            qubes.vm.appvm.AppVM,
            name=self.make_vm_name("dvm"),
            label="red",
            template_for_dispvms=True,
        )
        self.loop.run_until_complete(self.disp_base.create_on_disk())
        self.app.default_dispvm = self.disp_base
        self.app.save()
        self.preload_cmd = [
            "qvm-run",
            "-p",
            f"--dispvm={self.disp_base.name}",
            "--",
            "qubesdb-read /name | tr -d '\n'",
        ]

    def tearDown(self):  # pylint: disable=invalid-name
        if "gui" in self.disp_base.features:
            del self.disp_base.features["gui"]
        old_preload = self.disp_base.get_feat_preload()
        self.app.default_dispvm = None
        tasks = [self.app.domains[x].cleanup() for x in old_preload]
        self.loop.run_until_complete(asyncio.gather(*tasks))
        self.disp_base.features["preload-dispvm-max"] = False
        super(TC_20_DispVMMixin, self).tearDown()

    def _test_event_handler(
        self, vm, event, *args, **kwargs
    ):  # pylint: disable=unused-argument
        if not hasattr(self, "event_handler"):
            self.event_handler = {}
        self.event_handler.setdefault(vm.name, {})[event] = True

    def _test_event_was_handled(self, vm, event):
        if not hasattr(self, "event_handler"):
            self.event_handler = {}
        return self.event_handler.get(vm, {}).get(event)

    async def no_preload(self):
        # Trick to gather this function as an async task.
        await asyncio.sleep(0)
        self.disp_base.features["preload-dispvm-max"] = False

    async def run_preload_proc(self):
        proc = await asyncio.create_subprocess_exec(
            *self.preload_cmd,
            stdout=asyncio.subprocess.PIPE,
        )
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=60)
            return stdout.decode()
        except asyncio.TimeoutError:
            proc.terminate()
            await proc.wait()
            raise

    async def run_preload(self):
        appvm = self.disp_base
        dispvm = appvm.get_feat_preload()[0]
        dispvm = self.app.domains[dispvm]
        self.assertTrue(dispvm.is_preload)
        self.assertTrue(dispvm.features.get("internal", False))
        appvm.add_handler(
            "domain-preload-dispvm-autostart", self._test_event_handler
        )
        appvm.add_handler(
            "domain-preload-dispvm-start", self._test_event_handler
        )
        appvm.add_handler(
            "domain-preload-dispvm-used", self._test_event_handler
        )
        dispvm.add_handler("domain-paused", self._test_event_handler)
        dispvm.add_handler("domain-unpaused", self._test_event_handler)
        dispvm.add_handler(
            "domain-feature-set:preload-dispvm-completed",
            self._test_event_handler,
        )
        dispvm.add_handler(
            "domain-feature-set:preload-dispvm-in-progress",
            self._test_event_handler,
        )
        dispvm.add_handler(
            "domain-feature-delete:preload-dispvm-in-progress",
            self._test_event_handler,
        )
        dispvm.add_handler(
            "domain-feature-delete:internal", self._test_event_handler
        )
        dispvm_name = dispvm.name
        stdout = await self.run_preload_proc()
        self.assertEqual(stdout, dispvm_name)
        self.assertFalse(
            self._test_event_was_handled(
                appvm.name, "domain-preload-dispvm-autostart"
            )
        )
        self.assertFalse(
            self._test_event_was_handled(
                appvm.name, "domain-preload-dispvm-start"
            )
        )
        self.assertTrue(
            self._test_event_was_handled(
                appvm.name, "domain-preload-dispvm-used"
            )
        )
        self.assertTrue(
            self._test_event_was_handled(
                dispvm_name, "domain-feature-set:preload-dispvm-completed"
            )
        )
        self.assertTrue(
            self._test_event_was_handled(
                dispvm_name, "domain-feature-set:preload-dispvm-in-progress"
            )
        )
        self.assertTrue(
            self._test_event_was_handled(
                dispvm_name, "domain-feature-delete:preload-dispvm-in-progress"
            )
        )
        if self._test_event_was_handled(dispvm_name, "domain-paused"):
            self.assertTrue(
                self._test_event_was_handled(dispvm_name, "domain-unpaused")
            )
        if not appvm.features.get("internal", False):
            self.assertTrue(
                self._test_event_was_handled(
                    dispvm_name, "domain-feature-delete:internal"
                )
            )
        next_preload_list = appvm.get_feat_preload()
        self.assertTrue(next_preload_list)
        self.assertNotIn(dispvm_name, next_preload_list)

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

    def test_011_dvm_run_preload_reject_max(self):
        """Test preloading when max has been reached"""
        self.loop.run_until_complete(
            qubes.vm.dispvm.DispVM.from_appvm(self.disp_base, preload=True)
        )
        self.assertEqual(0, len(self.disp_base.get_feat_preload()))

    def test_012_dvm_run_preload_low_mem(self):
        """Test preloading with low memory"""
        self.loop.run_until_complete(self._test_012_dvm_run_preload_low_mem())

    async def _test_012_dvm_run_preload_low_mem(self):
        # pylint: disable=unspecified-encoding
        unpatched_open = open

        def mock_open_mem(file, *args, **kwargs):
            if file == qubes.config.qmemman_avail_mem_file:
                memory = str(getattr(self.disp_base, "memory", 0) * 1024 * 1024)
                return mock_open(read_data=memory)()
            return unpatched_open(file, *args, **kwargs)

        with patch("builtins.open", side_effect=mock_open_mem):
            self.disp_base.features["preload-dispvm-max"] = "2"
            for _ in range(15):
                if len(self.disp_base.get_feat_preload()) == 2:
                    break
                await asyncio.sleep(1)
            self.assertEqual(1, len(self.disp_base.get_feat_preload()))

    def test_013_dvm_run_preload_gui(self):
        """Test preloading with GUI feature enabled"""
        self.loop.run_until_complete(self._test_013_dvm_run_preload_gui())

    async def _test_013_dvm_run_preload_gui(self):
        self.disp_base.features["gui"] = True
        self.disp_base.features["preload-dispvm-max"] = "1"
        for _ in range(10):
            if len(self.disp_base.get_feat_preload()) == 1:
                break
            await asyncio.sleep(1)
        else:
            self.fail("didn't preload in time")
        await self.run_preload()

    def test_014_dvm_run_preload_nogui(self):
        """Test preloading with GUI feature disabled"""
        self.loop.run_until_complete(self._test_014_dvm_run_preload_nogui())

    async def _test_014_dvm_run_preload_nogui(self):
        self.disp_base.features["gui"] = False
        self.disp_base.features["preload-dispvm-max"] = "1"
        for _ in range(10):
            if len(self.disp_base.get_feat_preload()) == 1:
                break
            await asyncio.sleep(1)
        else:
            self.fail("didn't preload in time")
        self.preload_cmd.insert(1, "--no-gui")
        await self.run_preload()

    def test_015_dvm_run_preload_race_more(self):
        """Test race requesting multiple preloaded qubes"""
        self.loop.run_until_complete(self._test_015_dvm_run_preload_race_more())

    async def _test_preload_wait_pause(self, preload_max):
        """Waiting for pause avoids objects leaking."""
        for _ in range(60):
            if len(self.disp_base.get_feat_preload()) == preload_max:
                break
            await asyncio.sleep(1)
        else:
            self.fail("didn't preload in time")
        preload_dispvm = self.disp_base.get_feat_preload()
        preload_unfinished = preload_dispvm
        for _ in range(60):
            for qube in preload_unfinished.copy():
                if self.app.domains[qube].is_paused():
                    preload_unfinished.remove(qube)
                    continue
            if not preload_unfinished:
                break
            await asyncio.sleep(1)
        else:
            self.fail("last preloaded didn't pause in time")

    async def _test_015_dvm_run_preload_race_more(self):
        # The limiting factor is how much memory is available on OpenQA and the
        # unreasonable memory allocated before the qube is paused due to:
        #   https://github.com/QubesOS/qubes-issues/issues/9917
        # Whonix (Kicksecure) 17 fail more due to memory consumption. From the
        # templates deployed by default, only Debian and Fedora survives due to
        # using less memory than the other OSes.
        preload_max = 4
        os_dist = self.disp_base.features.check_with_template("os-distribution")
        if os_dist in ["whonix", "kicksecure"]:
            preload_max -= 1
        self.disp_base.features["preload-dispvm-max"] = str(preload_max)
        await self._test_preload_wait_pause(preload_max)
        old_preload = self.disp_base.get_feat_preload()
        tasks = [self.run_preload_proc() for _ in range(preload_max)]
        targets = await asyncio.gather(*tasks)
        await self._test_preload_wait_pause(preload_max)
        preload_dispvm = self.disp_base.get_feat_preload()
        self.assertTrue(set(old_preload).isdisjoint(preload_dispvm))
        self.assertEqual(len(targets), preload_max)
        self.assertEqual(len(targets), len(set(targets)))

    def test_016_dvm_run_preload_race_less(self):
        """Test race requesting preloaded qube while the maximum is zeroed."""
        self.loop.run_until_complete(self._test_016_dvm_run_preload_race_less())

    async def _test_016_dvm_run_preload_race_less(self):
        self.disp_base.features["preload-dispvm-max"] = "1"
        for _ in range(60):
            if len(self.disp_base.get_feat_preload()) == 1:
                break
            await asyncio.sleep(1)
        else:
            self.fail("didn't preload in time")
        tasks = [self.run_preload_proc(), self.no_preload()]
        target = await asyncio.gather(*tasks)
        target_dispvm = target[0]
        self.assertTrue(target_dispvm.startswith("disp"))

    def test_017_dvm_run_preload_autostart(self):
        proc = self.loop.run_until_complete(
            asyncio.create_subprocess_exec("/usr/lib/qubes/preload-dispvm")
        )
        self.loop.run_until_complete(
            asyncio.wait_for(proc.communicate(), timeout=10)
        )
        self.assertEqual(self.disp_base.get_feat_preload(), [])
        self.disp_base.features["preload-dispvm-max"] = "1"
        for _ in range(10):
            if len(self.disp_base.get_feat_preload()) == 1:
                break
            self.loop.run_until_complete(asyncio.sleep(1))
        else:
            self.fail("didn't preload in time")
        old_preload = self.disp_base.get_feat_preload()
        proc = self.loop.run_until_complete(
            asyncio.create_subprocess_exec("/usr/lib/qubes/preload-dispvm")
        )
        self.loop.run_until_complete(asyncio.wait_for(proc.wait(), timeout=30))
        preload_dispvm = self.disp_base.get_feat_preload()
        self.assertEqual(len(old_preload), 1)
        self.assertEqual(len(preload_dispvm), 1)
        self.assertTrue(
            set(old_preload).isdisjoint(preload_dispvm),
            f"old_preload={old_preload} preload_dispvm={preload_dispvm}",
        )

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
