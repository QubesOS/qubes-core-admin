#
# The Qubes OS Project, https://www.qubes-os.org/
#
# Copyright (C) 2025 Marek Marczykowski-Górecki
#                           <marmarek@invisiblethingslab.com>
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
import sys
import time

import qubes.tests


class TC_00_DispVMPerfMixin:
    def setUp(self: qubes.tests.SystemTestCase):
        super().setUp()
        if "whonix-g" in self.template:
            self.skipTest(
                "whonix gateway is not supported as DisposableVM Template"
            )
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
        self.loop.run_until_complete(
            asyncio.gather(
                self.dvm.create_on_disk(),
                self.vm1.create_on_disk(),
                self.vm2.create_on_disk(),
            )
        )
        start_tasks = [self.vm1.start()]
        if self._testMethodName.startswith("vm"):
            start_tasks.append(self.vm2.start())
        self.loop.run_until_complete(asyncio.gather(*start_tasks))

    def tearDown(self: qubes.tests.SystemTestCase):
        super().tearDown()
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
        if name.startswith("vm"):
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

    def test_000_dispvm(self):
        """Latency of vm-dispvm calls"""
        self.run_test("dispvm")

    def test_001_dispvm_gui(self):
        """Latency of vm-dispvm GUI calls"""
        self.run_test("dispvm-gui")

    def test_002_dispvm_concurrent(self):
        """Latency of vm-dispvm concurrent calls"""
        self.run_test("dispvm-concurrent")

    def test_003_dispvm_gui_concurrent(self):
        """Latency of vm-dispvm concurrent GUI calls"""
        self.run_test("dispvm-gui-concurrent")

    def test_006_dispvm_from_dom0(self):
        """Latency of dom0-dispvm calls"""
        self.run_test("dispvm-dom0")

    def test_007_dispvm_from_dom0_gui(self):
        """Latency of dom0-dispvm GUI calls"""
        self.run_test("dispvm-dom0-gui")

    def test_008_dispvm_from_dom0_concurrent(self):
        """Latency of dom0-dispvm concurrent calls"""
        self.run_test("dispvm-dom0-concurrent")

    def test_009_dispvm_from_dom0_gui_concurrent(self):
        """Latency of dom0-dispvm concurrent GUI calls"""
        self.run_test("dispvm-dom0-gui-concurrent")

    def test_020_dispvm_preload(self):
        """Latency of vm-dispvm (preload) calls"""
        self.run_test("dispvm-preload")

    def test_021_dispvm_preload_gui(self):
        """Latency of vm-dispvm (preload) GUI calls"""
        self.run_test("dispvm-preload-gui")

    def test_022_dispvm_preload_concurrent(self):
        """Latency of vm-dispvm (preload) concurrent calls"""
        self.run_test("dispvm-preload-concurrent")

    def test_023_dispvm_preload_gui_concurrent(self):
        """Latency of vm-dispvm (preload) concurrent GUI calls"""
        self.run_test("dispvm-preload-gui-concurrent")

    def test_026_dispvm_from_dom0_preload(self):
        """Latency of dom0-dispvm (preload) calls"""
        self.run_test("dispvm-preload-dom0")

    def test_027_dispvm_from_dom0_preload_gui(self):
        """Latency of dom0-dispvm (preload) GUI calls"""
        self.run_test("dispvm-preload-dom0-gui")

    def test_028_dispvm_from_dom0_preload_concurrent(self):
        """Latency of dom0-dispvm (preload) concurrent calls"""
        self.run_test("dispvm-preload-dom0-concurrent")

    def test_029_dispvm_from_dom0_preload_gui_concurrent(self):
        """Latency of dom0-dispvm (preload) concurrent GUI calls"""
        self.run_test("dispvm-preload-dom0-gui-concurrent")

    def test_400_dispvm_api(self):
        """Latency of dom0-dispvm API calls"""
        self.run_test("dispvm-api")

    def test_401_dispvm_gui_api(self):
        """Latency of dom0-dispvm GUI API calls"""
        self.run_test("dispvm-gui-api")

    def test_402_dispvm_concurrent_api(self):
        """Latency of dom0-dispvm concurrent API calls"""
        self.run_test("dispvm-concurrent-api")

    def test_403_dispvm_gui_concurrent_api(self):
        """Latency of dom0-dispvm concurrent GUI API calls"""
        self.run_test("dispvm-gui-concurrent-api")

    def test_404_dispvm_preload_more_api(self):
        """Latency of dom0-dispvm (preload more) API calls"""
        self.run_test("dispvm-preload-more-api")

    def test_404_dispvm_preload_less_api(self):
        """Latency of dom0-dispvm (preload less) API calls"""
        self.run_test("dispvm-preload-less-api")

    def test_404_dispvm_preload_api(self):
        """Latency of dom0-dispvm (preload) API calls"""
        self.run_test("dispvm-preload-api")

    def test_405_dispvm_preload_gui_api(self):
        """Latency of dom0-dispvm (preload) GUI API calls"""
        self.run_test("dispvm-preload-gui-api")

    def test_406_dispvm_preload_concurrent_api(self):
        """Latency of dom0-dispvm (preload) concurrent GUI API calls"""
        self.run_test("dispvm-preload-concurrent-api")

    def test_407_dispvm_preload_gui_concurrent_api(self):
        """Latency of dom0-dispvm (preload) concurrent GUI API calls"""
        self.run_test("dispvm-preload-gui-concurrent-api")

    def test_900_vm(self):
        """Latency of vm-vm calls"""
        self.run_test("vm")

    def test_901_vm_gui(self):
        """Latency of vm-vm GUI calls"""
        self.run_test("vm-gui")

    def test_902_vm_concurrent(self):
        """Latency of vm-vm concurrent calls"""
        self.run_test("vm-concurrent")

    def test_903_vm_gui_concurrent(self):
        """Latency of vm-vm concurrent GUI calls"""
        self.run_test("vm-gui-concurrent")

    def test_904_vm_api(self):
        """Latency of dom0-vm API calls"""
        self.run_test("vm-api")

    def test_905_vm_gui_api(self):
        """Latency of dom0-vm GUI API calls"""
        self.run_test("vm-gui-api")

    def test_906_vm_concurrent_api(self):
        """Latency of dom0-vm concurrent API calls"""
        self.run_test("vm-concurrent-api")

    def test_907_vm_gui_concurrent_api(self):
        """Latency of dom0-vm concurrent GUI API calls"""
        self.run_test("vm-gui-concurrent-api")


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
