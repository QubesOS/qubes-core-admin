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

test_script = "/usr/lib/qubes/tests/storage_perf.py"


class StoragePerfBase(qubes.tests.SystemTestCase):
    def setUp(self):
        super().setUp()
        self.vm = self.app.domains[0]

    def run_test(self, volume, name):
        cmd = [
            test_script,
            f"--volume={volume}",
            f"--vm={self.vm.name}",
            name,
        ]
        p = self.loop.run_until_complete(asyncio.create_subprocess_exec(*cmd))
        self.loop.run_until_complete(p.wait())
        if p.returncode:
            self.fail(f"'{' '.join(cmd)}' failed: {p.returncode}")


class TC_00_StoragePerfDom0(StoragePerfBase):
    def test_000_root_seq1m_q8t1_read(self):
        self.run_test("root", "seq1m_q8t1_read")

    def test_001_root_seq1m_q8t1_write(self):
        self.run_test("root", "seq1m_q8t1_write")

    def test_003_root_seq1m_q1t1_read(self):
        self.run_test("root", "seq1m_q1t1_read")

    def test_004_root_seq1m_q1t1_write(self):
        self.run_test("root", "seq1m_q1t1_write")

    def test_005_root_rnd4k_q32t1_read(self):
        self.run_test("root", "rnd4k_q32t1_read")

    def test_005_root_rnd4k_q32t1_write(self):
        self.run_test("root", "rnd4k_q32t1_write")

    def test_006_root_rnd4k_q1t1_read(self):
        self.run_test("root", "rnd4k_q1t1_read")

    def test_007_root_rnd4k_q1t1_write(self):
        self.run_test("root", "rnd4k_q1t1_write")

    def test_010_varlibqubes_seq1m_q8t1_read(self):
        self.run_test("varlibqubes", "seq1m_q8t1_read")

    def test_011_varlibqubes_seq1m_q8t1_write(self):
        self.run_test("varlibqubes", "seq1m_q8t1_write")

    def test_013_varlibqubes_seq1m_q1t1_read(self):
        self.run_test("varlibqubes", "seq1m_q1t1_read")

    def test_014_varlibqubes_seq1m_q1t1_write(self):
        self.run_test("varlibqubes", "seq1m_q1t1_write")

    def test_015_varlibqubes_rnd4k_q32t1_read(self):
        self.run_test("varlibqubes", "rnd4k_q32t1_read")

    def test_015_varlibqubes_rnd4k_q32t1_write(self):
        self.run_test("varlibqubes", "rnd4k_q32t1_write")

    def test_016_varlibqubes_rnd4k_q1t1_read(self):
        self.run_test("varlibqubes", "rnd4k_q1t1_read")

    def test_017_varlibqubes_rnd4k_q1t1_write(self):
        self.run_test("varlibqubes", "rnd4k_q1t1_write")


class TC_10_StoragePerfVM(StoragePerfBase):
    def setUp(self):
        super().setUp()
        self.vm = self.app.add_new_vm(
            "AppVM",
            name=self.make_vm_name("vm1"),
            label="red",
        )
        self.loop.run_until_complete(
            self.vm.create_on_disk(),
        )
        self.loop.run_until_complete(
            self.vm.start(),
        )

    def test_000_root_seq1m_q8t1_read(self):
        self.run_test("root", "seq1m_q8t1_read")

    def test_001_root_seq1m_q8t1_write(self):
        self.run_test("root", "seq1m_q8t1_write")

    def test_002_root_seq1m_q1t1_read(self):
        self.run_test("root", "seq1m_q1t1_read")

    def test_003_root_seq1m_q1t1_write(self):
        self.run_test("root", "seq1m_q1t1_write")

    def test_004_root_rnd4k_q32t1_read(self):
        self.run_test("root", "rnd4k_q32t1_read")

    def test_005_root_rnd4k_q32t1_write(self):
        self.run_test("root", "rnd4k_q32t1_write")

    def test_006_root_rnd4k_q1t1_read(self):
        self.run_test("root", "rnd4k_q1t1_read")

    def test_007_root_rnd4k_q1t1_write(self):
        self.run_test("root", "rnd4k_q1t1_write")

    def test_010_private_seq1m_q8t1_read(self):
        self.run_test("private", "seq1m_q8t1_read")

    def test_011_private_seq1m_q8t1_write(self):
        self.run_test("private", "seq1m_q8t1_write")

    def test_012_private_seq1m_q1t1_read(self):
        self.run_test("private", "seq1m_q1t1_read")

    def test_013_private_seq1m_q1t1_write(self):
        self.run_test("private", "seq1m_q1t1_write")

    def test_014_private_rnd4k_q32t1_read(self):
        self.run_test("private", "rnd4k_q32t1_read")

    def test_015_private_rnd4k_q32t1_write(self):
        self.run_test("private", "rnd4k_q32t1_write")

    def test_016_private_rnd4k_q1t1_read(self):
        self.run_test("private", "rnd4k_q1t1_read")

    def test_017_private_rnd4k_q1t1_write(self):
        self.run_test("private", "rnd4k_q1t1_write")

    def test_020_volatile_seq1m_q8t1_read(self):
        self.run_test("volatile", "seq1m_q8t1_read")

    def test_021_volatile_seq1m_q8t1_write(self):
        self.run_test("volatile", "seq1m_q8t1_write")

    def test_022_volatile_seq1m_q1t1_read(self):
        self.run_test("volatile", "seq1m_q1t1_read")

    def test_023_volatile_seq1m_q1t1_write(self):
        self.run_test("volatile", "seq1m_q1t1_write")

    def test_024_volatile_rnd4k_q32t1_read(self):
        self.run_test("volatile", "rnd4k_q32t1_read")

    def test_025_volatile_rnd4k_q32t1_write(self):
        self.run_test("volatile", "rnd4k_q32t1_write")

    def test_026_volatile_rnd4k_q1t1_read(self):
        self.run_test("volatile", "rnd4k_q1t1_read")

    def test_027_volatile_rnd4k_q1t1_write(self):
        self.run_test("volatile", "rnd4k_q1t1_write")
