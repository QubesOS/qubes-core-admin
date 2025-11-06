#!/usr/bin/python3
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

"""
Test disposable qube call latency

Methodology:
    - Source must be up and running
    - Target must be up and running if:
        - if it is the first batch of preloaded disposables; or
        - it is not a disposable.

Reading:
    - Different data points may be used differently. Keys such as "iterations",
      "hcl-*" and "os-*" can be used to enforce comparison to happen only
      against the same system. In some circumstances, keys such as
      "os-version", "kernel" and "date" can be used to compare against
      different version across time.
    - Some results may be skewed, "mean and "median" is useful when the test is
      stable, as they will be very close to each other. If the test is not
      stable, "mean" and "median" can be very similar, therefore it is
      recommended to render line graphs per iteration or a distribution graph
      for a better analysis.
    - The "median" is skewed on concurrent tests as it doesn't consider the
      bursts of concurrency. Using "mean" and "total" is recommended.
    - On preload tests, "mean" and "median" is relevant when iterations is
      higher than the number of preloaded disposables, as it will represent the
      average. This average is not the best metric when measuring workflows
      that are spread out, such as clicking on app menus, where just a few
      requests are made. The best metric for this use case is the data points
      of the initial iterations.
"""

import argparse
import asyncio
import concurrent.futures
import dataclasses
import json
import logging
import os
import statistics
import subprocess
import time
import yaml
from datetime import datetime, timezone

from deepmerge import Merger
import qubesadmin

# nose will duplicate this logger.
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
handler = logging.StreamHandler()
formatter = logging.Formatter(
    "%(asctime)s: %(levelname)s: %(funcName)s: %(message)s"
)
handler.setFormatter(formatter)
logger.addHandler(handler)


merger = Merger(
    [(list, ["override"]), (dict, ["merge"]), (set, ["override"])],
    ["override"],
    ["override"],
)


@dataclasses.dataclass
class TestConfig:
    """
    Test configuration.

    :param str name: test name
    :param bool gui: wait for GUI session
    :param bool concurrent: request concurrently
    :param bool from_dom0: initiate call from dom0
    :param int preload_max: number of disposables to preload
    :param bool non_dispvm: target a non disposable qube
    :param bool admin_api: use the Admin API directly
    :param str extra_id: base test that extra ID varies from
    :param str pretty_name: human-readable name

    Notes
    -----
    Source-Target:
        - dom0-dispvm: Menu items, management scripts
        - vm-dispvm: Offloading dangerous operations to disposable,
          opening/sanitizing files, fetching web pages, building.
        - *-vm: Fast way to test if the tests are working.
            - qubesadmin: Raw call to measure phases. Doesn't represent the
              most realistic output as users would most likely interact with it
              via wrappers such as qvm-run.
        - vm-dispvm:
            - qrexec-client-vm: scripts
    Wrappers vs API
        - Wrappers represent the most realistic output as users normally
          interact with if for common use cases, such as clicking on the app
          menu (qvm-run) or opening file in a disposable (qrexec-client-vm).
        - API calls are made directly with qubesadmin, but it doesn't represent
          the most realistic output as users would most likely interact with it
          via wrappers. Calls are only made from dom0, it would require deeper
          setup (install package on templates, configure Qrexec policy) to
          allow a domU to be the source of API calls.
    GUI VS non-GUI:
        - GUI tests workflows that uses disposables to open untrusted files or
          programs that requires graphics. Instead of relying on what xdg-open
          would do on the target, we simply time the moment until the GUI
          session starts on the target.
        - non-GUI tests a workflow that uses disposables to run untrusted code.
    Sequential VS Concurrent:
        - Sequential calls represent a result closer to end-user workflow, as
          it is simpler to achieve.
        - Concurrent calls are multiple requests that are done without regards
          to the previous request completion.
        - Concurrency mean time is skewed as there are multiples simultaneous
          calls.
    Normal VS Preloaded:
        - Improving normal qube startup will shorten preload usage time, but
          the reverse is not true. Normal disposables are a control group for
          preloaded disposables.
        - Preloading more than 2 is not useful on sequential calls as long as
          on the next call, there is a preload that has been completed.
    """

    name: str
    gui: bool = False
    concurrent: bool = False
    from_dom0: bool = False
    preload_max: int = 0
    non_dispvm: bool = False
    admin_api: bool = False
    extra_id: str = ""
    pretty_name: str = dataclasses.field(init=False)

    def __post_init__(self):
        if self.admin_api:
            pretty_type = "API"
        elif self.from_dom0:
            pretty_type = "qvm-run"
        else:
            pretty_type = "qrexec-client-vm"

        if self.from_dom0:
            pretty_from = "dom0"
        else:
            pretty_from = "qube"

        if self.concurrent:
            pretty_strategy = "{} concurrent".format(MAX_CONCURRENCY)
        else:
            pretty_strategy = ""

        if self.gui:
            pretty_what = "GUI"
        else:
            pretty_what = "simple"

        if self.non_dispvm:
            pretty_to = "in another running qube"
        else:
            disp_suffix = ""
            disp_prefix = "a "
            if self.preload_max:
                disp_prefix = ""
                disp_suffix = "s"
                if self.preload_max > 1:
                    disp_suffix = "s"
                pretty_to = "in {}disposable{} ({} preloaded)".format(
                    disp_prefix, disp_suffix, self.preload_max
                )
            else:
                if self.concurrent:
                    disp_prefix = ""
                    disp_suffix = "s"
                pretty_to = "in {}disposable{}".format(disp_prefix, disp_suffix)

        pretty_name = "{} runs".format(pretty_from.capitalize())
        if pretty_strategy:
            pretty_name += " {}".format(pretty_strategy)
        if pretty_what:
            app_suffix = ""
            if self.concurrent:
                app_suffix = "s"
            pretty_name += " {} app{} ".format(pretty_what, app_suffix)
        pretty_name += "{}".format(pretty_to)
        if pretty_type:
            pretty_name += " ({})".format(pretty_type)
        self.pretty_name = pretty_name


POLICY_FILE = "/run/qubes/policy.d/10-test-dispvm-perf.policy"
# MAX_PRELOAD is the number doesn't overpreload or underpreload (best
# performance) on sequential calls between the tests
# "dispvm-preload(-NUMBER)-api" (tested on fedora-42-xfce). Machines with
# different hardware or domains that boot faster or slower can theoretically
# have a different best value.
MAX_PRELOAD = 4
# The preload number is set to MAX_CONCURRENCY on concurrent calls. This number
# is also used by non preloaded disposables to set the maximum workers/jobs.
MAX_CONCURRENCY = 4
# A value that is not too short that would impact accuracy and not too long to
# burn OpenQA. It is a multiple of MAX_CONCURRENCY so there is no remainder
# when using concurrency.
ITERATIONS = MAX_CONCURRENCY * 3
# A small round precision excludes noise. It is also used to have 0 padding (as
# a string) to align fields.
ROUND_PRECISION = 3

ALL_TESTS = [
    TestConfig("vm-vm", non_dispvm=True),
    TestConfig("vm-vm-gui", gui=True, non_dispvm=True),
    TestConfig("vm-vm-concurrent", concurrent=True, non_dispvm=True),
    TestConfig(
        "vm-vm-gui-concurrent", gui=True, concurrent=True, non_dispvm=True
    ),
    TestConfig("dom0-vm-api", non_dispvm=True, admin_api=True, from_dom0=True),
    TestConfig(
        "dom0-vm-gui-api",
        gui=True,
        non_dispvm=True,
        admin_api=True,
        from_dom0=True,
    ),
    TestConfig(
        "dom0-vm-concurrent-api",
        concurrent=True,
        non_dispvm=True,
        admin_api=True,
        from_dom0=True,
    ),
    TestConfig(
        "dom0-vm-gui-concurrent-api",
        gui=True,
        concurrent=True,
        non_dispvm=True,
        admin_api=True,
        from_dom0=True,
    ),
    TestConfig("vm-dispvm"),
    TestConfig("vm-dispvm-gui", gui=True),
    TestConfig("vm-dispvm-concurrent", concurrent=True),
    TestConfig("vm-dispvm-gui-concurrent", gui=True, concurrent=True),
    TestConfig("vm-dispvm-preload", preload_max=MAX_PRELOAD),
    TestConfig("vm-dispvm-preload-gui", gui=True, preload_max=MAX_PRELOAD),
    TestConfig(
        "vm-dispvm-preload-concurrent",
        concurrent=True,
        preload_max=MAX_CONCURRENCY,
    ),
    TestConfig(
        "vm-dispvm-preload-gui-concurrent",
        gui=True,
        concurrent=True,
        preload_max=MAX_CONCURRENCY,
    ),
    TestConfig("dom0-dispvm", from_dom0=True),
    TestConfig("dom0-dispvm-gui", gui=True, from_dom0=True),
    TestConfig("dom0-dispvm-concurrent", concurrent=True, from_dom0=True),
    TestConfig(
        "dom0-dispvm-gui-concurrent", gui=True, concurrent=True, from_dom0=True
    ),
    TestConfig("dom0-dispvm-preload", from_dom0=True, preload_max=MAX_PRELOAD),
    TestConfig(
        "dom0-dispvm-preload-gui",
        gui=True,
        from_dom0=True,
        preload_max=MAX_PRELOAD,
    ),
    TestConfig(
        "dom0-dispvm-preload-concurrent",
        concurrent=True,
        from_dom0=True,
        preload_max=MAX_CONCURRENCY,
    ),
    TestConfig(
        "dom0-dispvm-preload-gui-concurrent",
        gui=True,
        concurrent=True,
        from_dom0=True,
        preload_max=MAX_CONCURRENCY,
    ),
    TestConfig("dom0-dispvm-api", admin_api=True, from_dom0=True),
    TestConfig(
        "dom0-dispvm-concurrent-api",
        concurrent=True,
        admin_api=True,
        from_dom0=True,
    ),
    TestConfig("dom0-dispvm-gui-api", gui=True, admin_api=True, from_dom0=True),
    TestConfig(
        "dom0-dispvm-gui-concurrent-api",
        gui=True,
        concurrent=True,
        admin_api=True,
        from_dom0=True,
    ),
    TestConfig(
        "dom0-dispvm-preload-1-api",
        preload_max=1,
        admin_api=True,
        extra_id="dom0-dispvm-preload-api",
        from_dom0=True,
    ),
    TestConfig(
        "dom0-dispvm-preload-1-gui-api",
        preload_max=1,
        gui=True,
        admin_api=True,
        extra_id="dom0-dispvm-preload-gui-api",
        from_dom0=True,
    ),
    TestConfig(
        "dom0-dispvm-preload-2-api",
        preload_max=2,
        admin_api=True,
        extra_id="dom0-dispvm-preload-api",
        from_dom0=True,
    ),
    TestConfig(
        "dom0-dispvm-preload-2-gui-api",
        preload_max=2,
        gui=True,
        admin_api=True,
        extra_id="dom0-dispvm-preload-gui-api",
        from_dom0=True,
    ),
    TestConfig(
        "dom0-dispvm-preload-3-api",
        preload_max=3,
        admin_api=True,
        extra_id="dom0-dispvm-preload-api",
        from_dom0=True,
    ),
    TestConfig(
        "dom0-dispvm-preload-3-gui-api",
        preload_max=3,
        gui=True,
        admin_api=True,
        extra_id="dom0-dispvm-preload-gui-api",
        from_dom0=True,
    ),
    TestConfig(
        "dom0-dispvm-preload-4-api",
        preload_max=4,
        admin_api=True,
        from_dom0=True,
    ),
    TestConfig(
        "dom0-dispvm-preload-4-gui-api",
        preload_max=4,
        gui=True,
        admin_api=True,
        from_dom0=True,
    ),
    TestConfig(
        "dom0-dispvm-preload-5-api",
        preload_max=5,
        admin_api=True,
        extra_id="dom0-dispvm-preload-api",
        from_dom0=True,
    ),
    TestConfig(
        "dom0-dispvm-preload-5-gui-api",
        preload_max=5,
        gui=True,
        admin_api=True,
        extra_id="dom0-dispvm-preload-gui-api",
        from_dom0=True,
    ),
    TestConfig(
        "dom0-dispvm-preload-6-api",
        preload_max=6,
        admin_api=True,
        extra_id="dom0-dispvm-preload-api",
        from_dom0=True,
    ),
    TestConfig(
        "dom0-dispvm-preload-6-gui-api",
        preload_max=6,
        gui=True,
        admin_api=True,
        extra_id="dom0-dispvm-preload-gui-api",
        from_dom0=True,
    ),
    TestConfig(
        "dom0-dispvm-preload-concurrent-api",
        concurrent=True,
        preload_max=MAX_CONCURRENCY,
        admin_api=True,
        from_dom0=True,
    ),
    TestConfig(
        "dom0-dispvm-preload-gui-concurrent-api",
        gui=True,
        concurrent=True,
        preload_max=MAX_CONCURRENCY,
        admin_api=True,
        from_dom0=True,
    ),
]


def get_load() -> str:
    with open("/proc/loadavg", "r", encoding="ascii") as file:
        load = file.read()
    return load.rstrip()


def get_time():
    return time.clock_gettime(time.CLOCK_MONOTONIC)


def hcl() -> dict:
    completed_process = subprocess.run(
        ["qubes-hcl-report", "--yaml-only"], capture_output=True, check=True
    )
    report = yaml.safe_load(completed_process.stdout)
    data = {
        "hcl-qubes": report["versions"][0]["qubes"].rstrip(),
        "hcl-xen": report["versions"][0]["xen"].rstrip(),
        "hcl-kernel": report["versions"][0]["kernel"].rstrip(),
        "hcl-memory": int(report["memory"].rstrip()),
    }
    if os.environ.get("QUBES_TEST_PERF_HWINFO"):
        data.update(
            {
                "hcl-certified": report["certified"].rstrip() != "no",
                "hcl-brand": report["brand"].rstrip(),
                "hcl-model": report["model"].rstrip(),
                "hcl-bios": report["bios"].rstrip(),
                "hcl-cpu": report["cpu"].rstrip(),
                "hcl-scsi": report["scsi"].rstrip(),
                "hcl-nvme": report["nvme"].rstrip(),
            }
        )
    return data


class TestRun:
    def __init__(self, dom0, dvm, vm1, vm2):
        self.dom0 = dom0
        self.dvm = dvm
        self.vm1 = vm1
        self.vm2 = vm2
        self.app = self.dom0.app
        self.adminvm = self.dom0
        self.iterations = ITERATIONS
        self.gui_service = "qubes.WaitForSession"
        self.nogui_service = "qubes.WaitForRunningSystem"

    async def wait_preload(
        self,
        preload_max,
        appvm=None,
        wait_completion=True,
        fail_on_timeout=True,
        timeout=60,
    ):
        """Waiting for completion avoids coroutine objects leaking."""
        logger.info("preload_max: '%s'", preload_max)
        if not appvm:
            appvm = self.dvm
        for _ in range(timeout):
            preload_dispvm = appvm.features.get("preload-dispvm", "")
            preload_dispvm = preload_dispvm.split(" ") or []
            if len(preload_dispvm) == preload_max:
                break
            await asyncio.sleep(1)
        else:
            if fail_on_timeout:
                raise Exception("didn't preload in time")
        if not wait_completion:
            logger.info("end")
            return
        preload_dispvm = appvm.features.get("preload-dispvm", "")
        preload_dispvm = preload_dispvm.split(" ") or []
        preload_unfinished = preload_dispvm
        for _ in range(timeout):
            for qube in preload_unfinished.copy():
                self.app.domains.refresh_cache(force=True)
                qube = self.app.domains[qube]
                completed = qube.features.get("preload-dispvm-completed")
                if completed:
                    preload_unfinished.remove(qube)
                    continue
            if not preload_unfinished:
                break
            await asyncio.sleep(1)
        else:
            if fail_on_timeout:
                raise Exception("last preloaded didn't complete in time")
        logger.info("end")

    def wait_for_dispvm_destroy(self, dispvm_names):
        logger.info("Waiting for destruction of disposables: %s", dispvm_names)
        timeout = 60
        while True:
            self.app.domains.refresh_cache(force=True)
            if set(dispvm_names).isdisjoint(self.app.domains):
                break
            time.sleep(1)
            timeout -= 1
            if timeout <= 0:
                raise Exception("didn't destroy dispvm(s) in time")

    def run_latency_calls(self, test):
        if test.gui:
            service = self.gui_service
        else:
            service = self.nogui_service

        if test.concurrent:
            term = "&"
            timeout = self.iterations / MAX_CONCURRENCY * 30
        else:
            term = ";"
            timeout = self.iterations * 30

        if test.from_dom0:
            caller = "qvm-run -p --service --filter-escape-chars "
            caller += "--no-color-output --no-color-stderr "
            if test.gui:
                caller += "--gui "
            else:
                caller += "--no-gui "
            caller += f"--dispvm={self.dvm.name} "
            cmd = f"{caller} -- {service}"
        else:
            if test.non_dispvm:
                target = self.vm2.name
            else:
                target = "@dispvm"
            cmd = f"qrexec-client-vm -- {target} {service}"

        code = (
            "set -eu --; "
            f'max_concurrency="{MAX_CONCURRENCY}"; '
            f"for i in $(seq {self.iterations}); do "
            '  echo "$i"; '
            f"  {cmd} {term}"
            '  pid="${!-}"; '
            '  if test -n "${pid}"; then '
            '    set -- "${@}" "${pid}"; '
            '    if test "${#}" = "${max_concurrency}" && test -n "${1}"; then'
            '      wait "${1}"; shift; '
            "    fi; "
            "  fi; "
            "done; "
            'wait "${@}"'
        )

        start_time = get_time()
        try:
            if test.from_dom0:
                subprocess.run(
                    code,
                    shell=True,
                    check=True,
                    capture_output=True,
                    timeout=timeout,
                )
            else:
                self.vm1.run(code, timeout=timeout)
        except subprocess.CalledProcessError as e:
            raise Exception(
                f"service '{cmd}' failed ({e.returncode}):"
                f" {e.stdout},"
                f" {e.stderr}"
            )
        except subprocess.TimeoutExpired as e:
            raise Exception(
                f"service '{cmd}' failed: timeout expired:"
                f" {e.stdout},"
                f" {e.stderr}"
            )
        end_time = get_time()
        return round(end_time - start_time, ROUND_PRECISION)

    def call_api(self, test, service, qube):
        start_time = get_time()
        app = qubesadmin.Qubes()
        domains = app.domains
        if test.non_dispvm:
            # Even though we already have the qube object passed from the
            # class, assume we don't so we can calculate gathering.
            target_qube = domains[self.vm1.name]
            domain_time = get_time()
        else:
            appvm = domains[qube]
            domain_time = get_time()
            target_wrapper = qubesadmin.vm.DispVM.from_appvm(app, appvm)
            target_qube = target_wrapper.create_disposable()
        name = target_qube.name
        # A very small number, if it appears, it will show a bottleneck at
        # DispVM.from_appvm.
        target_time = get_time()
        try:
            target_qube.run_service_for_stdio(service, timeout=60)
        except subprocess.CalledProcessError as e:
            raise Exception(
                f"'{name}': service '{service}' failed ({e.returncode}):"
                f" {e.stdout},"
                f" {e.stderr}"
            )
        except subprocess.TimeoutExpired as e:
            raise Exception(
                f"'{name}': service '{service}' failed: timeout expired:"
                f" {e.stdout},"
                f" {e.stderr}"
            )
        run_service_time = get_time()
        if not test.non_dispvm:
            target_qube.cleanup()
            cleanup_time = get_time()
            end_time = cleanup_time
        else:
            end_time = get_time()
        runtime = {}
        runtime["dom"] = round(domain_time - start_time, ROUND_PRECISION)
        if not test.non_dispvm:
            runtime["disp"] = round(target_time - domain_time, ROUND_PRECISION)
        runtime["exec"] = round(run_service_time - target_time, ROUND_PRECISION)
        if not test.non_dispvm:
            runtime["clean"] = round(
                cleanup_time - run_service_time, ROUND_PRECISION
            )
        runtime["total"] = round(end_time - start_time, ROUND_PRECISION)
        return runtime

    async def api_thread(self, test, service, qube):
        tasks = []
        loop = asyncio.get_running_loop()
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=MAX_CONCURRENCY
        ) as executor:
            exec_args = self.call_api, test, service, qube
            for _ in range(1, self.iterations + 1):
                future = loop.run_in_executor(executor, *exec_args)
                tasks.append(future)
            all_results = await asyncio.gather(*tasks)
        return all_results

    async def run_latency_api_calls(self, test):
        if test.gui:
            service = self.gui_service
        else:
            service = self.nogui_service
        if test.non_dispvm:
            qube = self.vm2
        else:
            qube = self.dvm

        results = {}
        results["api_results"] = {}
        results["api_results"]["iteration"] = {}
        results["api_results"]["stage"] = {}
        start_time = get_time()
        if test.concurrent:
            all_results = await self.api_thread(test, service, qube)
            for i in range(1, self.iterations + 1):
                results["api_results"]["iteration"][i] = all_results[i - 1]
        else:
            for i in range(1, self.iterations + 1):
                try:
                    results["api_results"]["iteration"][i] = self.call_api(
                        test=test, service=service, qube=qube
                    )
                except:
                    logger.critical("Failed call_api() on iteration %d", i)
                    raise
        end_time = get_time()

        sample_keys = list(results["api_results"]["iteration"][1].keys())
        value_keys = [k for k in sample_keys if k != "total"]
        headers = (
            ["iter"]
            + [f"{k}" for k in value_keys]
            + ["total"]
            + [f"{k}%" for k in value_keys]
        )
        rows = []
        for key, values in results["api_results"]["iteration"].items():
            total = values.get("total", 0)
            row_values = [str(key)]
            for k in value_keys:
                row_values.append(f"{values.get(k, 0):.{ROUND_PRECISION}f}")
            row_values.append(f"{total:.{ROUND_PRECISION}f}")
            for k in value_keys:
                pct = (values.get(k, 0) / total * 100) if total != 0 else 0
                row_values.append(f"{pct:.0f}%")
            rows.append(row_values)
        col_widths = [len(h) for h in headers]
        for row in rows:
            for i, value in enumerate(row):
                col_widths[i] = max(col_widths[i], len(value))
        header_row = " ".join(
            h.rjust(col_widths[i]) for i, h in enumerate(headers)
        )

        print()
        print(header_row)
        for row in rows:
            print(
                " ".join(val.rjust(col_widths[i]) for i, val in enumerate(row))
            )

        values_by_stage = {key: {} for key in sample_keys}
        for subdict in results["api_results"]["iteration"].values():
            for key, value in subdict.items():
                values_by_stage[key].setdefault("values", []).append(value)
        for key, value in values_by_stage.items():
            values = value["values"]
            mean = round(statistics.mean(values), ROUND_PRECISION)
            median = round(statistics.median(values), ROUND_PRECISION)
            values_by_stage[key]["mean"] = mean
            values_by_stage[key]["median"] = median
        results["api_results"]["stage"].update(values_by_stage)

        total_time = round(end_time - start_time, ROUND_PRECISION)
        return total_time, results

    def report_result(self, test, result):
        try:
            template = self.vm1.template.name
        except AttributeError:
            template = self.vm1.name
        data = vars(test)
        data["template"] = str(template)
        if test.admin_api:
            total_time = result[0]
            data.update(result[1].items())
        else:
            total_time = result
        mean = round(total_time / self.iterations, ROUND_PRECISION)

        data.update(
            {
                "iterations": self.iterations,
                "mean": mean,
                "total": total_time,
                "date": datetime.now(timezone.utc).strftime(
                    "%Y-%m-%dT%H:%M:%S"
                ),
            }
        )

        template_properties = {}
        int_properties = [
            "memory",
            "maxmem",
            "vcpus",
            "qrexec_timeout",
            "shutdown_timeout",
        ]
        wanted_properties = [*int_properties, "kernel", "kernelopts"]
        for prop in wanted_properties:
            val = getattr(self.vm1, prop, "")
            if prop in int_properties:
                val = int(val or 0)
            template_properties[prop] = val
        data.update(template_properties)

        template_features = {}
        int_features = ["os-version"]
        wanted_features = [
            "template-buildtime",
            "last-update",
            "os",
            "os-distribution",
            *int_features,
        ]
        for feature in wanted_features:
            val = self.vm1.features.check_with_template(feature, "")
            if feature in int_features:
                val = int(val or 0)
            template_features[feature] = val
        data.update(template_features)

        data.update(hcl())

        pretty_mean = f"{mean:.{ROUND_PRECISION}f}"
        pretty_total_time = f"{total_time:.{ROUND_PRECISION}f}"
        pretty_items = "iterations=" + str(self.iterations)
        pretty_items += " mean=" + pretty_mean
        print(f"Run time ({pretty_items}): {pretty_total_time}s")
        results_file = os.environ.get("QUBES_TEST_PERF_FILE")
        if not results_file:
            return
        try:
            name_prefix = f"{template!s}_"
        except AttributeError:
            name_prefix = f"{template!s}_"
        data_final = {}
        data_final[name_prefix + test.name] = data
        try:
            with open(results_file, "r", encoding="ascii") as file:
                old_data = json.load(file)
        except (FileNotFoundError, json.JSONDecodeError):
            old_data = {}
        data_final = merger.merge(old_data, data_final)
        with open(results_file, "w", encoding="ascii") as file:
            json.dump(data_final, file, indent=2)

    async def run_test(self, test: TestConfig):
        with open(POLICY_FILE, "w", encoding="ascii") as policy:
            gui_prefix = f"{self.gui_service} * {self.vm1.name}"
            nogui_prefix = f"{self.nogui_service} * {self.vm1.name}"
            if test.non_dispvm:
                target = f"{self.vm2.name}"
            else:
                target = "@dispvm"
            policy.write(
                f"{gui_prefix} {target} allow\n"
                f"{nogui_prefix} {target} allow\n"
            )
        orig_preload_threshold = self.dom0.features.get(
            "preload-dispvm-threshold"
        )
        orig_preload_max = self.dom0.features.get("preload-dispvm-max")
        if orig_preload_threshold is not None:
            logger.info("Deleting threshold feature")
            del self.dom0.features["preload-dispvm-threshold"]
        if orig_preload_max is not None:
            logger.info("Deleting global max feature")
            del self.dom0.features["preload-dispvm-max"]
        try:
            if test.preload_max:
                preload_max = test.preload_max
                logger.info("Setting local max feature: '%s'", preload_max)
                self.dvm.features["preload-dispvm-max"] = str(preload_max)
                await self.wait_preload(preload_max)
            for qube in [self.vm1, self.vm2]:
                if not qube:
                    # Might be an empty string.
                    continue
                logger.info(
                    "Waiting for qube '%s' to finish startup",
                    qube.name,
                )
                # GUI wait for user is-system-running while noGUI service waits
                # for system is-system-running.
                qube.run_service_for_stdio(self.nogui_service, timeout=60)
                qube.run_service_for_stdio(self.gui_service, timeout=60)
            logger.info("Load before test: '%s'", get_load())
            if test.admin_api:
                result = await self.run_latency_api_calls(test)
            else:
                result = self.run_latency_calls(test)
            self.report_result(test, result)
        except:
            logger.error("Failed to run test: '%s'", test.name)
            raise
        finally:
            if test.preload_max:
                old_preload_max = int(
                    self.dvm.features.get("preload-dispvm-max", 0) or 0
                )
                logger.info(
                    "Waiting to preload the old test setting: '%s'",
                    old_preload_max,
                )
                await self.wait_preload(old_preload_max)
                old_preload = self.dvm.features.get("preload-dispvm", "")
                old_preload = old_preload.split(" ") or []
                logger.info("Deleting local max feature")
                del self.dvm.features["preload-dispvm-max"]
                self.wait_for_dispvm_destroy(old_preload)
            if orig_preload_threshold is not None:
                logger.info(
                    "Setting the original threshold feature: '%s'",
                    orig_preload_threshold,
                )
                self.dom0.features["preload-dispvm-threshold"] = (
                    orig_preload_threshold
                )
            if orig_preload_max is not None:
                logger.info(
                    "Setting the global max feature: '%s'", orig_preload_max
                )
                self.dom0.features["preload-dispvm-max"] = orig_preload_max
            os.unlink(POLICY_FILE)
            if not os.getenv("QUBES_TEST_SKIP_TEARDOWN_SLEEP"):
                logger.info("Load before sleep: '%s'", get_load())
                delay = 5
                if not test.non_dispvm:
                    delay += 10
                    if test.gui:
                        delay += 2
                    if test.concurrent:
                        delay += 8
                logger.info("Sleeping for '%d' seconds", delay)
                time.sleep(delay)
                logger.info("Load after sleep: '%s'", get_load())


def main():
    parser = argparse.ArgumentParser(
        epilog="You can set QUBES_TEST_PERF_FILE env variable to a path where "
        "machine-readable results should be saved. If you want to share a "
        "detailed result containing hardware information, set "
        "QUBES_TEST_PERF_HWINFO to a non empty value. Many qubes will be "
        "created if running a lot of these tests, it is recommended to disable "
        "LVM archiving in backup.archive in /etc/lvm/lvm.conf and restart "
        "lvm2-monitor.service, else tests may fail."
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

    for test in tests:
        logger.info("Running test %s: %s", test.name, test.pretty_name)
        asyncio.run(run.run_test(test))


if __name__ == "__main__":
    main()
