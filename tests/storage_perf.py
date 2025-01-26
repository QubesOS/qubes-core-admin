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
import subprocess
import tempfile

import qubesadmin


@dataclasses.dataclass
class TestConfig:
    name: str
    fio_config: str


# from fio manual
fio_output_headers = "terse_version_3;fio_version;jobname;groupid;error;read_kb;read_bandwidth_kb;read_iops;read_runtime_ms;read_slat_min_us;read_slat_max_us;read_slat_mean_us;read_slat_dev_us;read_clat_min_us;read_clat_max_us;read_clat_mean_us;read_clat_dev_us;read_clat_pct01;read_clat_pct02;read_clat_pct03;read_clat_pct04;read_clat_pct05;read_clat_pct06;read_clat_pct07;read_clat_pct08;read_clat_pct09;read_clat_pct10;read_clat_pct11;read_clat_pct12;read_clat_pct13;read_clat_pct14;read_clat_pct15;read_clat_pct16;read_clat_pct17;read_clat_pct18;read_clat_pct19;read_clat_pct20;read_tlat_min_us;read_lat_max_us;read_lat_mean_us;read_lat_dev_us;read_bw_min_kb;read_bw_max_kb;read_bw_agg_pct;read_bw_mean_kb;read_bw_dev_kb;write_kb;write_bandwidth_kb;write_iops;write_runtime_ms;write_slat_min_us;write_slat_max_us;write_slat_mean_us;write_slat_dev_us;write_clat_min_us;write_clat_max_us;write_clat_mean_us;write_clat_dev_us;write_clat_pct01;write_clat_pct02;write_clat_pct03;write_clat_pct04;write_clat_pct05;write_clat_pct06;write_clat_pct07;write_clat_pct08;write_clat_pct09;write_clat_pct10;write_clat_pct11;write_clat_pct12;write_clat_pct13;write_clat_pct14;write_clat_pct15;write_clat_pct16;write_clat_pct17;write_clat_pct18;write_clat_pct19;write_clat_pct20;write_tlat_min_us;write_lat_max_us;write_lat_mean_us;write_lat_dev_us;write_bw_min_kb;write_bw_max_kb;write_bw_agg_pct;write_bw_mean_kb;write_bw_dev_kb;cpu_user;cpu_sys;cpu_csw;cpu_mjf;cpu_minf;iodepth_1;iodepth_2;iodepth_4;iodepth_8;iodepth_16;iodepth_32;iodepth_64;lat_2us;lat_4us;lat_10us;lat_20us;lat_50us;lat_100us;lat_250us;lat_500us;lat_750us;lat_1000us;lat_2ms;lat_4ms;lat_10ms;lat_20ms;lat_50ms;lat_100ms;lat_250ms;lat_500ms;lat_750ms;lat_1000ms;lat_2000ms;lat_over_2000ms;disk_name;disk_read_iops;disk_write_iops;disk_read_merges;disk_write_merges;disk_read_ticks;write_ticks;disk_queue_time;disk_util"

fio_seq_write = """
[global]
name=fio-seq-write
filename=fio-seq-write
rw=write
bs=256K
direct=0
numjobs=1
time_based
runtime=90
unlink=1

[file1]
size=1G
ioengine=libaio
iodepth=16
"""

fio_rand_write = """
[global]
name=fio-rand-write
filename=fio-rand-write
rw=randwrite
bs=4K
direct=0
numjobs=4
time_based
runtime=90
unlink=1

[file1]
size=1G
ioengine=libaio
iodepth=16
"""

fio_rand_read = """
[global]
name=fio-rand-read
filename=fio-rand-read
rw=randread
bs=4K
direct=0
numjobs=1
time_based
runtime=90
unlink=1

[file1]
size=1G
ioengine=libaio
iodepth=16
"""

fio_seq_read = """
[global]
name=fio-seq-reads
filename=fio-seq-reads
rw=read
bs=256K
direct=1
numjobs=1
time_based
runtime=90
unlink=1

[file1]
size=1G
ioengine=libaio
iodepth=16
"""

all_tests = [
    TestConfig("seq-read", fio_seq_read),
    TestConfig("seq-write", fio_seq_write),
    TestConfig("rand-read", fio_rand_read),
    TestConfig("rand-write", fio_rand_write),
]


class TestRun:
    def __init__(self, vm, volume):
        self.vm = vm
        self.volume = volume

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
                name_prefix = f"{self.vm.template!s}_"
            except AttributeError:
                name_prefix = f"{self.vm!s}_"
            name_prefix += f"{self.volume}_"
            add_header = False
            if not os.path.exists(results_file):
                add_header = True
            with open(results_file, "a") as f:
                if add_header:
                    f.write("# " + fio_output_headers + "\n")
                for line in result.splitlines():
                    f.write(name_prefix + test_name + " " + line + "\n")

    def prepare_volume(self) -> str:
        if self.vm.klass == "AdminVM":
            if self.volume == "root":
                return "/root"
            if self.volume == "varlibqubes":
                return "/var/lib/qubes"
            raise ValueError(f"Unsupported volume {self.volume} for dom0")
        if self.volume == "private":
            return "/home/user"
        if self.volume == "root":
            return "/root"
        if self.volume == "volatile":
            self.vm.run(
                "mkfs.ext4 -F /dev/xvdc3 && mkdir -p /mnt/volatile && mount "
                "/dev/xvdc3 /mnt/volatile",
                user="root",
            )
            return "/mnt/volatile"
        raise ValueError(f"Unsupported volume {self.volume} for VM")

    def run_test(self, test_config: TestConfig):
        path = self.prepare_volume()
        if self.vm.klass == "AdminVM":
            with tempfile.NamedTemporaryFile() as f:
                f.write(test_config.fio_config.encode())
                f.flush()
                result = subprocess.check_output(
                    ["fio", "--minimal", f.name], cwd=path
                )
        else:
            self.vm.run_with_args(
                "tee", "/tmp/test.fio", input=test_config.fio_config.encode()
            )
            result = self.vm.run(
                f"cd {path} && fio --minimal /tmp/test.fio",
                user="root",
                stdout=subprocess.PIPE,
            )[0]
        self.report_result(test_config.name, result.strip().decode())


parser = argparse.ArgumentParser()
parser.add_argument(
    "--vm", required=True, help="VM to run test in, can be dom0"
)
parser.add_argument(
    "--volume",
    default="root",
    help="Which volume to test, possible values for VM: private, root, volatile; "
    "possible values for dom0: root, varlibqubes",
)
parser.add_argument("test", choices=[t.name for t in all_tests] + ["all"])


def main():
    args = parser.parse_args()

    if args.test == "all":
        tests = all_tests
    else:
        tests = [t for t in all_tests if t.name == args.test]

    app = qubesadmin.Qubes()

    run = TestRun(app.domains[args.vm], args.volume)

    for test in tests:
        run.run_test(test)


if __name__ == "__main__":
    main()
