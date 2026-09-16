#!/usr/bin/python3
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
import argparse
import dataclasses
import os
import sys
import subprocess
import tempfile

import qubesadmin
from qubesadmin.tools import qvm_device

@dataclasses.dataclass
class TestConfig:
    name: str


# from fio manual
fio_output_headers = "terse_version_3;fio_version;jobname;groupid;error;read_kb;read_bandwidth_kb;read_iops;read_runtime_ms;read_slat_min_us;read_slat_max_us;read_slat_mean_us;read_slat_dev_us;read_clat_min_us;read_clat_max_us;read_clat_mean_us;read_clat_dev_us;read_clat_pct01;read_clat_pct02;read_clat_pct03;read_clat_pct04;read_clat_pct05;read_clat_pct06;read_clat_pct07;read_clat_pct08;read_clat_pct09;read_clat_pct10;read_clat_pct11;read_clat_pct12;read_clat_pct13;read_clat_pct14;read_clat_pct15;read_clat_pct16;read_clat_pct17;read_clat_pct18;read_clat_pct19;read_clat_pct20;read_tlat_min_us;read_lat_max_us;read_lat_mean_us;read_lat_dev_us;read_bw_min_kb;read_bw_max_kb;read_bw_agg_pct;read_bw_mean_kb;read_bw_dev_kb;write_kb;write_bandwidth_kb;write_iops;write_runtime_ms;write_slat_min_us;write_slat_max_us;write_slat_mean_us;write_slat_dev_us;write_clat_min_us;write_clat_max_us;write_clat_mean_us;write_clat_dev_us;write_clat_pct01;write_clat_pct02;write_clat_pct03;write_clat_pct04;write_clat_pct05;write_clat_pct06;write_clat_pct07;write_clat_pct08;write_clat_pct09;write_clat_pct10;write_clat_pct11;write_clat_pct12;write_clat_pct13;write_clat_pct14;write_clat_pct15;write_clat_pct16;write_clat_pct17;write_clat_pct18;write_clat_pct19;write_clat_pct20;write_tlat_min_us;write_lat_max_us;write_lat_mean_us;write_lat_dev_us;write_bw_min_kb;write_bw_max_kb;write_bw_agg_pct;write_bw_mean_kb;write_bw_dev_kb;cpu_user;cpu_sys;cpu_csw;cpu_mjf;cpu_minf;iodepth_1;iodepth_2;iodepth_4;iodepth_8;iodepth_16;iodepth_32;iodepth_64;lat_2us;lat_4us;lat_10us;lat_20us;lat_50us;lat_100us;lat_250us;lat_500us;lat_750us;lat_1000us;lat_2ms;lat_4ms;lat_10ms;lat_20ms;lat_50ms;lat_100ms;lat_250ms;lat_500ms;lat_750ms;lat_1000ms;lat_2000ms;lat_over_2000ms;disk_name;disk_read_iops;disk_write_iops;disk_read_merges;disk_write_merges;disk_read_ticks;write_ticks;disk_queue_time;disk_util"


fio_config = """
[global]
ioengine=libaio
randrepeat=0
refill_buffers
end_fsync=1
direct=1
rwmixread=70
size=1024m
zero_buffers=0
runtime=5
numjobs=1
unlink=1

[seq1m_q8t1_read]
iodepth=8
bs=1024k
rw=read

[seq1m_q8t1_write]
iodepth=8
bs=1024k
rw=write

[seq1m_q1t1_read]
iodepth=1
bs=1024k
rw=read

[seq1m_q1t1_write]
iodepth=1
bs=1024k
rw=write

[rnd4k_q32t1_read]
iodepth=32
bs=4k
rw=randread

[rnd4k_q32t1_write]
iodepth=32
bs=4k
rw=randwrite

[rnd4k_q1t1_read]
iodepth=1
bs=4k
rw=randread

[rnd4k_q1t1_write]
iodepth=1
bs=4k
rw=randwrite
"""


all_tests = [
    TestConfig("seq1m_q8t1_read"),
    TestConfig("seq1m_q8t1_write"),
    TestConfig("seq1m_q1t1_read"),
    TestConfig("seq1m_q1t1_write"),
    TestConfig("rnd4k_q32t1_read"),
    TestConfig("rnd4k_q32t1_write"),
    TestConfig("rnd4k_q1t1_read"),
    TestConfig("rnd4k_q1t1_write"),
]

def qvm_block_run(args, app):
    devclass='block'
    parser = qvm_device.get_parser(devclass)
    args = parser.parse_args(args, app=app)

    try:
        args.func(args)
    except qubesadmin.exc.QubesException as e:
        parser.print_error(str(e))
        raise


class TestRun:
    def __init__(self, vm, app=None):
        self.app = app or qubesadmin.Qubes()
        self.vm = vm
        self.testpath = None
        self.name_prefix = None

    def prepare(self):
        return

    def finalize(self):
        return

    def report_result(self, test_name, result):
        # for short results takes average
        read_kb = [int(l.split(";")[6]) for l in result.splitlines()]
        write_kb = [int(l.split(";")[47]) for l in result.splitlines()]
        read_kb = sum(read_kb) // len(read_kb)
        write_kb = sum(write_kb) // len(write_kb)
        print(
            f"FIO results ({test_name}): "
            f"READ {read_kb}kb/s WRITE {write_kb}kb/s ({result})"
        )
        results_file = os.environ.get("QUBES_TEST_PERF_FILE")
        if results_file:
            try:
                name_prefix = f"{self.vm.template!s}:"
            except AttributeError:
                name_prefix = f"{self.vm!s}:"
            name_prefix += f"{self.name_prefix}:"
            add_header = False
            if not os.path.exists(results_file):
                add_header = True
            with open(results_file, "a") as f:
                if add_header:
                    f.write("# " + fio_output_headers + "\n")
                for line in result.splitlines():
                    f.write(name_prefix + test_name + " " + line + "\n")

    def run_test(self, test_config: TestConfig):
        self.prepare()
        try:
            assert self.testpath, f"Test path not set: {self.testpath}"
            if self.vm.klass == "AdminVM":
                with tempfile.NamedTemporaryFile() as f:
                    f.write(fio_config.encode())
                    f.flush()
                    result = subprocess.check_output(
                        [
                            "fio",
                            "--minimal",
                            f"--filename={self.testpath}",
                            f"--section={test_config.name}",
                            f.name,
                        ],
                    )
            else:
                self.vm.run_with_args(
                    "tee", "/tmp/test.fio", input=fio_config.encode()
                )
                result = self.vm.run(
                    f"fio --minimal --filename={self.testpath}"
                    f" --section={test_config.name} /tmp/test.fio",
                    user="root",
                    stdout=subprocess.PIPE,
                )[0]

            self.report_result(test_config.name, result.strip().decode())
        finally:
            self.finalize()


class TestRunVolume(TestRun):
    def __init__(self, vm, volume, app=None):
        super().__init__(vm, app=app)
        self.volume = volume
        self.name_prefix = volume

    def prepare(self):
        if self.vm.klass == "AdminVM":
            if self.volume == "root":
                dirpath = "/root"
            elif self.volume == "varlibqubes":
                dirpath = "/var/lib/qubes"
            else:
                raise ValueError(f"Unsupported volume {self.volume} for dom0")
        elif self.volume == "private":
            dirpath = "/home/user"
        elif self.volume == "root":
            dirpath = "/root"
        elif self.volume == "volatile":
            self.vm.run(
                "mkfs.ext4 -F /dev/xvdc3 && mkdir -p /mnt/volatile && mount "
                "/dev/xvdc3 /mnt/volatile",
                user="root",
            )
            dirpath = "/mnt/volatile"
        else:
            raise ValueError(f"Unsupported volume {self.volume} for VM")

        self.testpath = os.path.join(dirpath, "fio-test-file")


class TestRunDevice(TestRun):
    dom0_mountdir = "/run/media/perftest"
    vm_mountdir = "/media/perftest"

    def __init__(self, vm, device, mount=False, app=None):
        super().__init__(vm, app=app)
        self.device = device
        self.mount = mount
        if mount:
           self.name_prefix = "custom"
        else:
           self.name_prefix = "disk_raw"

    def prepare(self):
        if not os.path.exists(self.device):
            raise ValueError(f"Not a valid device: {self.device}")
        self.testpath = self.device

        # Only attach the block device if not dom0. Its not needed
        # anyway because it already has access to the block device.
        if self.vm.klass != "AdminVM":
            # TODO: First test to see if frontend device node is already
            # taken.
            frontend_dev_name = 'xvdp'
            dev = os.path.realpath(self.device, strict=True)
            qvm_block_run(['attach',
                           '-o', f'frontend-dev={frontend_dev_name}',
                           self.vm.name, f'dom0:{os.path.basename(dev)}'],
                          self.app)

            self.testpath = os.path.join("/dev", frontend_dev_name)

        if self.mount:
            if self.vm.klass == "AdminVM":
                result = subprocess.check_output(
                    [
                        "mount", "-m",
                        self.device,
                        self.dom0_mountdir,
                    ],
                )
                self.testpath = os.path.join(self.dom0_mountdir, "fio-test-file")
            else:
                self.vm.run_with_args(
                    "mount", "-m", self.testpath, self.vm_mountdir,
                    user="root",
                )
                self.testpath = os.path.join(self.vm_mountdir, "fio-test-file")

    def finalize(self):
        if self.mount:
            # Unmount previous mounts
            if self.vm.klass == "AdminVM":
                result = subprocess.check_output(
                    [
                        "umount",
                        self.dom0_mountdir,
                    ],
                )
            else:
                self.vm.run_with_args(
                    "umount", self.vm_mountdir,
                    user="root",
                )

        if self.vm.klass != "AdminVM":
            dev = os.path.realpath(self.device, strict=True)
            qvm_block_run(['detach', self.vm.name,
                           f'dom0:{os.path.basename(dev)}'],
                          self.app)


parser = argparse.ArgumentParser()
parser.add_argument(
    "--vm", required=True, help="VM to run test in, can be dom0"
)

group_ex = parser.add_mutually_exclusive_group()

group_ex.add_argument(
    "--volume",
    help="Which volume to test, possible values for VM: private, root, volatile; "
    "possible values for dom0: root, varlibqubes",
)

group_ex.add_argument(
    "--device",
    default="",
    help="Which block device to test, must be a path in /dev",
)

dev_group = parser.add_argument_group("Extra arguments for --device")
dev_group.add_argument(
    "-m", "--mount",
    default=False,
    action="store_true",
    help="Mount block device",
)

parser.add_argument("test", choices=[t.name for t in all_tests] + ["all"])


def main():
    args = parser.parse_args()
    if args.volume and args.device:
        parser.error("--volume and --device are mutually exclusive")
    elif not (args.volume or args.device):
        # If neither --volume nor --device was specified, default to
        # --volume root
        args.volume = "root"
    if args.volume and args.mount:
        parser.error("--volume cannot use --mount option")

    app = qubesadmin.Qubes()

    if args.test == "all":
        tests = all_tests
    else:
        tests = [t for t in all_tests if t.name == args.test]

    if args.volume:
        run = TestRunVolume(app.domains[args.vm], args.volume, app=app)
    else:
        run = TestRunDevice(app.domains[args.vm], args.device,
                            mount=args.mount, app=app)

    for test in tests:
        run.run_test(test)


if __name__ == "__main__":
    main()
