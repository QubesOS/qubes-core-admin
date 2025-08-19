#
# The Qubes OS Project, https://www.qubes-os.org/
#
# Copyright (C) 2025 Benjamin Grande <ben.grande.b@gmail.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU Lesser General Public License as published by
# the Free Software Foundation; either version 2.1 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public License along
# with this program; if not, see <http://www.gnu.org/licenses/>.

import asyncio
import os
import shutil
import sys
import tempfile

import qubes.tests


class TC_00_DispVMPerfMixin:
    def setUp(self: qubes.tests.SystemTestCase):
        super().setUp()
        if "whonix-g" in self.template:
            self.skipTest(
                "whonix gateway is not supported as DisposableVM Template"
            )
        self.results = os.getenv("QUBES_TEST_PERF_FILE")
        self.test_dir = None
        if "_reader" in self._testMethodName:
            prefix = self.template + "_"
            if self.results:
                prefix = self.results + "_" + prefix
            self.test_dir = tempfile.mkdtemp(prefix=prefix)
            self.vm2 = None
            return
        self.dvm = self.app.add_new_vm(
            "AppVM",
            name=self.make_vm_name("dvm"),
            label="red",
            template=self.app.domains[self.template],
            template_for_dispvms=True,
        )
        self.vm1 = self.app.add_new_vm(
            "AppVM",
            name=self.make_vm_name("vm1"),
            label="red",
            template=self.app.domains[self.template],
            default_dispvm=self.dvm,
        )
        self.vm2 = self.app.add_new_vm(
            "AppVM",
            name=self.make_vm_name("vm2"),
            label="red",
            template=self.app.domains[self.template],
            default_dispvm=self.dvm,
        )
        # Necessary to be done post qube creation because of Whonix Admin Addon:
        #   https://github.com/QubesOS/qubes-core-admin-addon-whonix/pull/25
        for qube in [self.dvm, self.vm1, self.vm2]:
            qube.default_dispvm = self.dvm
            qube.netvm = None
        self.loop.run_until_complete(
            asyncio.gather(
                self.dvm.create_on_disk(),
                self.vm1.create_on_disk(),
                self.vm2.create_on_disk(),
            )
        )
        self.loop.run_until_complete(self.start_vm(self.dvm))
        self.shutdown_and_wait(self.dvm)
        start_tasks = [self.vm1.start()]
        if "_vm" in self._testMethodName:
            start_tasks.append(self.vm2.start())
        self.loop.run_until_complete(asyncio.gather(*start_tasks))

    def tearDown(self: qubes.tests.SystemTestCase):
        super().tearDown()
        if self.test_dir and os.getenv("QUBES_TEST_PERF_GRAPH_DELETE"):
            shutil.rmtree(self.test_dir)
        if self.vm2:
            if self.vm2.is_running():
                self.loop.run_until_complete(
                    asyncio.gather(
                        self.vm2.shutdown(),
                    )
                )

    def run_test(self, name):
        dvm = self.dvm.name
        vm1 = self.vm1.name
        vm2 = ""
        if "-vm" in name:
            vm2 = self.vm2.name
        cmd = [
            "/usr/lib/qubes/tests/dispvm_perf.py",
            f"--dvm={dvm}",
            f"--vm1={vm1}",
            f"--vm2={vm2}",
            name,
        ]
        p = self.loop.run_until_complete(asyncio.create_subprocess_exec(*cmd))
        self.loop.run_until_complete(p.wait())
        if p.returncode:
            self.fail(f"'{' '.join(cmd)}' failed: {p.returncode}")

    def run_reader(self, args: list):
        if not self.results:
            self.skipTest("Did not set QUBES_TEST_PERF_FILE")
        cmd = [
            "/usr/lib/qubes/tests/dispvm_perf_reader.py",
            f"--template={self.template}",
            f"--output-dir={self.test_dir}",
            *args,
            "--",
            self.results,
        ]
        p = self.loop.run_until_complete(asyncio.create_subprocess_exec(*cmd))
        self.loop.run_until_complete(p.wait())
        if p.returncode:
            self.fail(f"'{' '.join(cmd)}' failed: {p.returncode}")

    def test_000_vm_dispvm(self):
        """Latency of vm-dispvm calls"""
        self.run_test("vm-dispvm")

    def test_001_vm_dispvm_gui(self):
        """Latency of vm-dispvm GUI calls"""
        self.run_test("vm-dispvm-gui")

    def test_002_vm_dispvm_concurrent(self):
        """Latency of vm-dispvm concurrent calls"""
        self.run_test("vm-dispvm-concurrent")

    def test_003_vm_dispvm_gui_concurrent(self):
        """Latency of vm-dispvm concurrent GUI calls"""
        self.run_test("vm-dispvm-gui-concurrent")

    def test_006_dom0_dispvm(self):
        """Latency of dom0-dispvm calls"""
        self.run_test("dom0-dispvm")

    def test_007_dom0_dispvm_gui(self):
        """Latency of dom0-dispvm GUI calls"""
        self.run_test("dom0-dispvm-gui")

    def test_008_dom0_dispvm_concurrent(self):
        """Latency of dom0-dispvm concurrent calls"""
        self.run_test("dom0-dispvm-concurrent")

    def test_009_dom0_dispvm_gui_concurrent(self):
        """Latency of dom0-dispvm concurrent GUI calls"""
        self.run_test("dom0-dispvm-gui-concurrent")

    def test_020_vm_dispvm_preload(self):
        """Latency of vm-dispvm (preload) calls"""
        self.run_test("vm-dispvm-preload")

    def test_021_vm_dispvm_preload_gui(self):
        """Latency of vm-dispvm (preload) GUI calls"""
        self.run_test("vm-dispvm-preload-gui")

    def test_022_vm_dispvm_preload_concurrent(self):
        """Latency of vm-dispvm (preload) concurrent calls"""
        self.run_test("vm-dispvm-preload-concurrent")

    def test_023_vm_dispvm_preload_gui_concurrent(self):
        """Latency of vm-dispvm (preload) concurrent GUI calls"""
        self.run_test("vm-dispvm-preload-gui-concurrent")

    def test_026_dom0_dispvm_preload(self):
        """Latency of dom0-dispvm (preload) calls"""
        self.run_test("dom0-dispvm-preload")

    def test_027_dom0_dispvm_preload_gui(self):
        """Latency of dom0-dispvm (preload) GUI calls"""
        self.run_test("dom0-dispvm-preload-gui")

    def test_028_dom0_dispvm_preload_concurrent(self):
        """Latency of dom0-dispvm (preload) concurrent calls"""
        self.run_test("dom0-dispvm-preload-concurrent")

    def test_029_dom0_dispvm_preload_gui_concurrent(self):
        """Latency of dom0-dispvm (preload) concurrent GUI calls"""
        self.run_test("dom0-dispvm-preload-gui-concurrent")

    def test_400_dom0_dispvm_api(self):
        """Latency of dom0-dispvm API calls"""
        self.run_test("dom0-dispvm-api")

    def test_401_dom0_dispvm_gui_api(self):
        """Latency of dom0-dispvm GUI API calls"""
        self.run_test("dom0-dispvm-gui-api")

    def test_402_dom0_dispvm_concurrent_api(self):
        """Latency of dom0-dispvm concurrent API calls"""
        self.run_test("dom0-dispvm-concurrent-api")

    def test_403_dom0_dispvm_gui_concurrent_api(self):
        """Latency of dom0-dispvm concurrent GUI API calls"""
        self.run_test("dom0-dispvm-gui-concurrent-api")

    def test_404_dom0_dispvm_preload_less_less_api(self):
        """Latency of dom0-dispvm (preload less less) API calls"""
        self.run_test("dom0-dispvm-preload-less-less-api")

    def test_405_dom0_dispvm_preload_less_api(self):
        """Latency of dom0-dispvm (preload less) API calls"""
        self.run_test("dom0-dispvm-preload-less-api")

    def test_406_dom0_dispvm_preload_api(self):
        """Latency of dom0-dispvm (preload) API calls"""
        self.run_test("dom0-dispvm-preload-api")

    def test_407_dom0_dispvm_preload_more_api(self):
        """Latency of dom0-dispvm (preload more) API calls"""
        self.run_test("dom0-dispvm-preload-more-api")

    def test_408_dom0_dispvm_preload_more_more_api(self):
        """Latency of dom0-dispvm (preload more more) API calls"""
        self.run_test("dom0-dispvm-preload-more-more-api")

    def test_409_dom0_dispvm_preload_gui_api(self):
        """Latency of dom0-dispvm (preload) GUI API calls"""
        self.run_test("dom0-dispvm-preload-gui-api")

    def test_410_dom0_dispvm_preload_concurrent_api(self):
        """Latency of dom0-dispvm (preload) concurrent GUI API calls"""
        self.run_test("dom0-dispvm-preload-concurrent-api")

    def test_411_dom0_dispvm_preload_gui_concurrent_api(self):
        """Latency of dom0-dispvm (preload) concurrent GUI API calls"""
        self.run_test("dom0-dispvm-preload-gui-concurrent-api")

    def test_800_vm_vm(self):
        """Latency of vm-vm calls"""
        self.run_test("vm-vm")

    def test_801_vm_vm_gui(self):
        """Latency of vm-vm GUI calls"""
        self.run_test("vm-vm-gui")

    def test_802_vm_vm_concurrent(self):
        """Latency of vm-vm concurrent calls"""
        self.run_test("vm-vm-concurrent")

    def test_803_vm_vm_gui_concurrent(self):
        """Latency of vm-vm concurrent GUI calls"""
        self.run_test("vm-vm-gui-concurrent")

    def test_804_dom0_vm_api(self):
        """Latency of dom0-vm API calls"""
        self.run_test("dom0-vm-api")

    def test_805_dom0_vm_gui_api(self):
        """Latency of dom0-vm GUI API calls"""
        self.run_test("dom0-vm-gui-api")

    def test_806_dom0_vm_concurrent_api(self):
        """Latency of dom0-vm concurrent API calls"""
        self.run_test("dom0-vm-concurrent-api")

    def test_807_dom0_vm_gui_concurrent_api(self):
        """Latency of dom0-vm concurrent GUI API calls"""
        self.run_test("dom0-vm-gui-concurrent-api")

    def test_900_reader(self):
        """Render performance graphs."""
        self.run_reader(["--log-level=INFO", "--no-show"])


def create_testcases_for_templates():
    return qubes.tests.create_testcases_for_templates(
        "TC_00_DispVMPerf",
        TC_00_DispVMPerfMixin,
        qubes.tests.SystemTestCase,
        module=sys.modules[__name__],
    )


def load_tests(loader, tests, pattern):  # pylint: disable=unused-argument
    tests.addTests(loader.loadTestsFromNames(create_testcases_for_templates()))
    return tests


qubes.tests.maybe_create_testcases_on_import(create_testcases_for_templates)
