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
import os
import time
import subprocess
import dataclasses

import qubesadmin


@dataclasses.dataclass
class TestConfig:
    name: str
    gui: bool = False
    concurrent: bool = False
    from_dom0: bool = False
    preload_max: int = 0
    non_dispvm: bool = False


POLICY_FILE = "/run/qubes/policy.d/10-test-dispvm-perf.policy"
# TODO: ben: sequential can use max=2 without issues but for concurrent calls,
# a large max would bring great benefit.
DEFAULT_MAX_PRELOAD = 2
MAX_CONCURRENCY = 4
ITERATIONS = MAX_CONCURRENCY * 4

ALL_TESTS = [
    TestConfig("vm", non_dispvm=True),
    TestConfig("dispvm"),
    TestConfig("dispvm-gui", gui=True),
    TestConfig("dispvm-concurrent", concurrent=True),
    TestConfig("dispvm-concurrent-gui", gui=True, concurrent=True),
    TestConfig("dispvm-dom0", from_dom0=True),
    TestConfig("dispvm-dom0-gui", gui=True, from_dom0=True),
    TestConfig("dispvm-dom0-concurrent", concurrent=True, from_dom0=True),
    TestConfig(
        "dispvm-dom0-concurrent-gui", gui=True, concurrent=True, from_dom0=True
    ),
    TestConfig("dispvm-preload", preload_max=DEFAULT_MAX_PRELOAD),
    TestConfig("dispvm-preload-gui", gui=True, preload_max=DEFAULT_MAX_PRELOAD),
    TestConfig(
        "dispvm-preload-concurrent",
        concurrent=True,
        preload_max=MAX_CONCURRENCY,
    ),
    TestConfig(
        "dispvm-preload-concurrent-gui",
        gui=True,
        concurrent=True,
        preload_max=MAX_CONCURRENCY,
    ),
    TestConfig(
        "dispvm-preload-dom0", from_dom0=True, preload_max=DEFAULT_MAX_PRELOAD
    ),
    TestConfig(
        "dispvm-preload-dom0-gui",
        gui=True,
        from_dom0=True,
        preload_max=DEFAULT_MAX_PRELOAD,
    ),
    TestConfig(
        "dispvm-preload-dom0-concurrent",
        concurrent=True,
        from_dom0=True,
        preload_max=MAX_CONCURRENCY,
    ),
    TestConfig(
        "dispvm-preload-dom0-concurrent-gui",
        gui=True,
        concurrent=True,
        from_dom0=True,
        preload_max=MAX_CONCURRENCY,
    ),
]


class TestRun:
    def __init__(self, dom0, dvm, vm1, vm2):
        self.dom0 = dom0
        self.dvm = dvm
        self.vm1 = vm1
        self.vm2 = vm2
        self.iterations = ITERATIONS

    def run_latency_calls(self, test):
        start_time = time.clock_gettime(time.CLOCK_MONOTONIC)

        if test.gui:
            service = "qubes.WaitForSession"
        else:
            service = "qubes.WaitForRunningSystem"

        if test.concurrent:
            term = "&"
        else:
            term = ";"

        if test.from_dom0:
            caller = "qvm-run -p --service --filter-escape-chars "
            if test.gui:
                caller += "--gui "
            else:
                caller += "--no-gui "
            caller += f"--dispvm={self.dvm.name} "
            cmd = f"{caller} -- {service}"
        else:
            if test.non_dispvm:
                cmd = f"qrexec-client-vm -- {self.vm2.name} {service}"
            else:
                cmd = f"qrexec-client-vm -- @dispvm {service}"

        # TODO: ben: This is not optimal for concurrent connections.
        # I was using this inside the max_concurrency statement:
        #  "     sleep 1.5; "
        code = (
            "set -e; "
            f"pids=(); max_concurrency={MAX_CONCURRENCY}; "
            f"for i in $(seq {self.iterations}); do "
            f"  out=$({cmd}) {term}"
            "  pids+=($!);"
            "  if (( ${#pids[@]} == max_concurrency )); then"
            '    wait "${pids[@]}"; pids=(); '
            "  fi; "
            "done"
        )
        try:
            if test.from_dom0:
                subprocess.run(code, shell=True, check=True)
            else:
                self.vm1.run(code)
        except subprocess.CalledProcessError as e:
            raise Exception(
                f"service '{cmd}' failed ({e.returncode}):"
                f" {e.stdout},"
                f" {e.stderr}"
            )
        end_time = time.clock_gettime(time.CLOCK_MONOTONIC)
        return end_time - start_time

    def report_result(self, test, result):
        items = " ".join(
            "{}={}".format(key, value) for key, value in vars(test).items()
        )
        average = result / self.iterations
        items += f" iterations={self.iterations} {average=}"
        print(f"Run time ({items}): {result}s")
        results_file = os.environ.get("QUBES_TEST_PERF_FILE")
        if results_file:
            try:
                if self.vm2 and self.vm1.template != self.vm2.template:
                    name_prefix = (
                        f"{self.vm1.template!s}_" f"{self.vm2.template!s}_"
                    )
                else:
                    name_prefix = f"{self.vm1.template!s}_"
            except AttributeError:
                if self.vm2:
                    name_prefix = f"{self.vm1!s}_{self.vm2!s}_"
                else:
                    name_prefix = f"{self.vm1!s}_"
            with open(results_file, "a", encoding="ascii") as file:
                file.write(
                    name_prefix
                    + test.name
                    + " "
                    + str(result)
                    + " "
                    + str(items)
                    + "\n"
                )

    def run_test(self, test: TestConfig):
        with open(POLICY_FILE, "w", encoding="ascii") as policy:
            gui_prefix = f"qubes.WaitForSession * {self.vm1.name}"
            nogui_prefix = f"qubes.WaitForRunningSystem * {self.vm1.name}"
            if test.non_dispvm:
                target = f"{self.vm2.name}"
            else:
                target = "@dispvm"
            policy.write(
                f"{gui_prefix} {target} allow\n"
                f"{nogui_prefix} {target} allow\n"
            )
        if test.preload_max:
            original_preload = self.dom0.features.get("preload-dispvm-max")
            if original_preload is not None:
                del self.dom0.features["preload-dispvm-max"]
        try:
            if test.preload_max:
                preload_max = test.preload_max
                self.dvm.features["preload-dispvm-max"] = str(preload_max)
                # TODO: ben: wait for preload to complete
                time.sleep(preload_max * 7)
            result = self.run_latency_calls(test)
            self.report_result(test, result)
        finally:
            if test.preload_max:
                del self.dvm.features["preload-dispvm-max"]
                if original_preload is not None:
                    self.dom0.features["preload-dispvm-max"] = original_preload
            os.unlink(POLICY_FILE)


def main():
    parser = argparse.ArgumentParser(
        epilog="You can set QUBES_TEST_PERF_FILE env variable to a path where "
        "machine-readable results should be saved."
    )
    parser.add_argument("--dvm", required=True)
    parser.add_argument("--vm1", required=True)
    parser.add_argument("--vm2", required=True)
    parser.add_argument(
        "--iterations",
        default=os.environ.get("QUBES_TEST_ITERATIONS", ITERATIONS),
        type=int,
    )
    parser.add_argument("test", choices=[t.name for t in ALL_TESTS] + ["all"])
    args = parser.parse_args()
    app = qubesadmin.Qubes()

    if args.test == "all":
        tests = ALL_TESTS
    else:
        tests = [t for t in ALL_TESTS if t.name == args.test]

    run = TestRun(
        dom0=app.domains["dom0"],
        dvm=app.domains[args.dvm],
        vm1=app.domains[args.vm1],
        vm2="" if not args.vm2 else app.domains[args.vm2],
    )
    if args.iterations:
        run.iterations = args.iterations

    for index, test in enumerate(tests):
        if index > 0:
            # Cool down.
            time.sleep(20)
        run.run_test(test)


if __name__ == "__main__":
    main()
