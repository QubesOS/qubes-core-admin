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
import subprocess
import sys
import time

import qubes.tests


class TC_00_QrexecPerfMixin:
    def setUp(self: qubes.tests.SystemTestCase):
        super().setUp()
        self.vm1 = self.app.add_new_vm(
            "AppVM",
            name=self.make_vm_name("vm1"),
            label="red",
        )
        self.vm2 = self.app.add_new_vm(
            "AppVM",
            name=self.make_vm_name("vm2"),
            label="red",
        )
        self.loop.run_until_complete(
            asyncio.gather(
                self.vm1.create_on_disk(),
                self.vm2.create_on_disk(),
            )
        )
        self.loop.run_until_complete(
            asyncio.gather(
                self.vm1.start(),
                self.vm2.start(),
            )
        )

    def run_test(self, name):
        cmd = [
            "/usr/lib/qubes/tests/qrexec_perf.py",
            f"--vm1={self.vm1.name}",
            f"--vm2={self.vm2.name}",
            name,
        ]
        p = self.loop.run_until_complete(asyncio.create_subprocess_exec(*cmd))
        self.loop.run_until_complete(p.wait())
        if p.returncode:
            self.fail(f"'{' '.join(cmd)}' failed: {p.returncode}")

    def test_000_simple(self):
        """Measure simple exec-based vm-vm calls latency"""
        self.loop.run_until_complete(self.wait_for_session(self.vm2))
        self.run_test("exec")

    def test_010_simple_root(self):
        """Measure simple exec-based vm-vm calls latency, use root to
        bypass qrexec-fork-server"""
        self.run_test("exec-root")

    def test_020_socket(self):
        """Measure simple socket-based vm-vm calls latency"""
        self.run_test("socket")

    def test_030_socket_root(self):
        """Measure simple socket-based vm-vm calls latency, use root to
        bypass qrexec-fork-server"""
        self.run_test("socket-root")

    def test_100_simple_data_simplex(self):
        """Measure simple exec-based vm-vm calls throughput"""
        self.run_test("exec-data-simplex")

    def test_110_simple_data_duplex(self):
        """Measure simple exec-based vm-vm calls throughput"""
        self.run_test("exec-data-duplex")

    def test_120_simple_data_duplex_root(self):
        """Measure simple exec-based vm-vm calls throughput"""
        self.run_test("exec-data-duplex-root")

    def test_130_socket_data_duplex(self):
        """Measure simple socket-based vm-vm calls throughput"""
        self.run_test("socket-data-duplex")


def create_testcases_for_templates():
    return qubes.tests.create_testcases_for_templates(
        "TC_00_QrexecPerf",
        TC_00_QrexecPerfMixin,
        qubes.tests.SystemTestCase,
        module=sys.modules[__name__],
    )


def load_tests(loader, tests, pattern):
    tests.addTests(loader.loadTestsFromNames(create_testcases_for_templates()))
    return tests


qubes.tests.maybe_create_testcases_on_import(create_testcases_for_templates)
