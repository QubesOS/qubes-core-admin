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
import contextlib
import os
import time
import subprocess
import dataclasses
from typing import Union

import qubesadmin


@dataclasses.dataclass
class TestConfig:
    name: str
    #: socket or exec
    socket: bool
    #: latency or throughput test
    throughput: bool
    #: user (via fork-server) or root
    root: bool
    #: for throughput test: simplex/duplex
    duplex: bool
    #: service file content or socat command
    service: Union[bytes, list[str]]


latency_service_exec = b"#!/bin/sh\necho test"
latency_service_socat = [
    "socat",
    "UNIX-LISTEN:/etc/qubes-rpc/test.Echo,mode=0666,fork",
    "EXEC:/bin/echo test",
]
throughput_service_exec_simplex = b"#!/bin/sh\nhead -c 100000000 /dev/zero\n"
throughput_service_exec_duplex = b"#!/bin/sh\ncat\n"
throughput_service_socat_duplex = [
    "socat",
    "UNIX-LISTEN:/etc/qubes-rpc/test.Echo,mode=0666,fork",
    "EXEC:/bin/cat",
]

all_tests = [
    TestConfig("exec", False, False, False, False, latency_service_exec),
    TestConfig("exec-root", False, False, True, False, latency_service_exec),
    TestConfig("socket", True, False, False, False, latency_service_socat),
    TestConfig("socket-root", True, False, True, False, latency_service_socat),
    TestConfig(
        "exec-data-simplex",
        False,
        True,
        False,
        False,
        throughput_service_exec_simplex,
    ),
    TestConfig(
        "exec-data-duplex",
        False,
        True,
        False,
        True,
        throughput_service_exec_simplex,
    ),
    TestConfig(
        "exec-data-duplex-root",
        False,
        True,
        True,
        True,
        throughput_service_exec_duplex,
    ),
    TestConfig(
        "socket-data-duplex",
        True,
        True,
        False,
        True,
        throughput_service_socat_duplex,
    ),
]

policy_file = "/run/qubes/policy.d/10-test-qrexec.policy"

parser = argparse.ArgumentParser(
    epilog="You can set QUBES_TEST_PERF_FILE env variable to a path where "
    "machine-readable results should be saved."
)
parser.add_argument("--vm1", required=True)
parser.add_argument("--vm2", required=True)
parser.add_argument(
    "--iterations",
    default=os.environ.get("QUBES_TEST_ITERATIONS", "500"),
    type=int,
)
parser.add_argument("test", choices=[t.name for t in all_tests] + ["all"])


class TestRun:
    def __init__(self, vm1, vm2):
        self.vm1 = vm1
        self.vm2 = vm2
        self.iterations = 500

    def run_latency_calls(self):
        start_time = time.clock_gettime(time.CLOCK_MONOTONIC)
        try:
            self.vm1.run(
                f"set -e;"
                f"for i in $(seq {self.iterations}); do "
                f"  out=$(qrexec-client-vm {self.vm2.name} test.Echo);"
                f"  test \"$out\" = 'test';"
                f"done"
            )
        except subprocess.CalledProcessError as e:
            raise Exception(
                f"test.Echo service failed ({e.returncode}):"
                f" {e.stdout},"
                f" {e.stderr}"
            )
        end_time = time.clock_gettime(time.CLOCK_MONOTONIC)
        return end_time - start_time

    def run_throughput_calls(self, duplex=False):
        prefix = ""
        if duplex:
            prefix = "head -c 100000000 /dev/zero | "
        start_time = time.clock_gettime(time.CLOCK_MONOTONIC)
        try:
            self.vm1.run(
                f"set -e;"
                f"for i in $(seq {self.iterations//2}); do "
                f"  out=$({prefix}qrexec-client-vm {self.vm2.name} test.Echo "
                f"| wc -c);"
                f'  test "$out" = \'100000000\' || {{ echo "failed iteration $i:'
                f" '$out'\"; exit 1; }};"
                f"done"
            )
        except subprocess.CalledProcessError as e:
            raise Exception(
                f"test.Echo service failed ({e.returncode}):"
                f" {e.stdout},"
                f" {e.stderr}"
            )
        end_time = time.clock_gettime(time.CLOCK_MONOTONIC)
        return end_time - start_time

    def report_result(self, test_name, result):
        print(f"Run time ({test_name}): {result}s")
        results_file = os.environ.get("QUBES_TEST_PERF_FILE")
        if results_file:
            try:
                if self.vm1.template != self.vm2.template:
                    name_prefix = (
                        f"{self.vm1.template!s}_" f"{self.vm2.template!s}_"
                    )
                else:
                    name_prefix = f"{self.vm1.template!s}_"
            except AttributeError:
                name_prefix = f"{self.vm1!s}_{self.vm2!s}_"
            with open(results_file, "a") as f:
                f.write(name_prefix + test_name + " " + str(result) + "\n")

    def run_test(self, test: TestConfig):
        if test.root:
            policy_action = "allow user=root"
        else:
            policy_action = "allow"

        service_proc = None
        if not test.socket:
            self.vm2.run_with_args(
                "rm", "-f", "/etc/qubes-rpc/test.Echo", user="root"
            )
            self.vm2.run_with_args(
                "tee",
                "/etc/qubes-rpc/test.Echo",
                input=test.service,
                user="root",
            )
            self.vm2.run_with_args(
                "chmod", "+x", "/etc/qubes-rpc/test.Echo", user="root"
            )
        else:
            self.vm2.run_with_args(
                "tee",
                "/etc/qubes/rpc-config/test.Echo",
                user="root",
                input=b"skip-service-descriptor=true\n",
            )
            cmd = qubesadmin.utils.encode_for_vmexec(test.service)
            service_proc = self.vm2.run_service(
                "qubes.VMExec+" + cmd, user="root"
            )
            # wait for socat startup
            self.vm2.run(
                "while ! test -e /etc/qubes-rpc/test.Echo; do sleep 0.1; done"
            )

        with open(policy_file, "w") as p:
            p.write(
                f"test.Echo + {self.vm1.name} {self.vm2.name} {policy_action}\n"
            )
        try:
            if test.throughput:
                result = self.run_throughput_calls(test.duplex)
            else:
                result = self.run_latency_calls()
            self.report_result(test.name, result)
        finally:
            os.unlink(policy_file)
            if service_proc:
                with contextlib.suppress(subprocess.CalledProcessError):
                    self.vm2.run_with_args("pkill", "socat", user="root")
                service_proc.wait()


def main():
    args = parser.parse_args()

    if args.test == "all":
        tests = all_tests
    else:
        tests = [t for t in all_tests if t.name == args.test]

    app = qubesadmin.Qubes()

    run = TestRun(app.domains[args.vm1], app.domains[args.vm2])
    if args.iterations:
        run.iterations = args.iterations

    for test in tests:
        run.run_test(test)


if __name__ == "__main__":
    main()
