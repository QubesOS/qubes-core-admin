#!/usr/bin/env python3
# pylint: disable=missing-module-docstring,missing-class-docstring,missing-function-docstring
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

# TODO: ben
# ben:
#   * Read: Ten simple rules for better figures, recommended by matplotlib site:
#        https://journals.plos.org/ploscompbiol/article?id=10.1371/journal.pcbi.1003833
# marta:
#   * Every chart should answer a single question or illustrate a single point,
# marek:
#   * Compare same test results (different reports) and check for discrepancies.
#     Define a percentage threshold for all performance tests.

import argparse
import json
import logging
import operator
import os
import sys
import textwrap

from typing import Callable, Any

# TODO: ben: add to test packages, delete ~/.cache/matplotlib to load new fonts
# Debian: fonts-open-sans python3-numpy python-matplotlib
# Fedora: open-sans-fonts python3-numpy python-matplotlib
import numpy as np
import math
import matplotlib
import matplotlib.pyplot as plt
import matplotlib.image

FIGSIZE = plt.rcParamsDefault["figure.figsize"]
WIDTH = FIGSIZE[0]
HEIGHT = FIGSIZE[1]

matplotlib.rcParams["toolbar"] = "none"
plt.style.use("dark_background")
plt.rcParams["font.family"] = "Open Sans"
plt.rcParams["font.size"] = 20
plt.rcParams["axes.titlesize"] = 30
plt.rcParams["axes.labelsize"] = 30
plt.rcParams["axes.titleweight"] = "bold"
plt.rcParams["figure.constrained_layout.use"] = True
plt.rcParams["figure.autolayout"] = True
plt.rcParams["figure.figsize"] = WIDTH * 5, HEIGHT * 5
plt.rcParams["figure.titlesize"] = 36
plt.rcParams["figure.titleweight"] = "bold"


COLORS = {
    "Main Black": "#333333",
    "Sub Gray": "#888888",
    "Icon Dark Gray": "#8e8e95",
    "Middle Gray": "#bfbfbf",
    "Light Gray": "#d2d2d2",
    "Background Gray": "#f5f5f5",
    "Primary Blue": "#3874d8",
    "Info Blue": "#43c4f3",
    "Qubes Blue": "#63a0ff",
    "Light Blue": "#99bfff",
    "Success Green": "#5ad840",
    "Purple": "#9f389f",
    "Danger Red": "#bd2727",
    "Warning Orange": "#e79e27",
    "Alert Yellow": "#e7e532",
}
CAPTION_COLOR = COLORS["Light Gray"]


def wrap_text(text: list, width: int) -> list:
    new_text = []
    for item in text:
        new_text.append(
            textwrap.fill(item, width=width, break_long_words=False)
        )
    return new_text


def filter_data(
    data: dict,
    conditions: dict,
    operators: dict[str, Callable[[Any, Any], bool]] | None = None,
) -> dict:
    """
    :param dict data: results
    :param dict conditions: filters
    :param dict operators: filter operators

    >>> filter_data(data, {"admin_api": True, "gui": True})
    >>> filter_data(data, {"preload_max": 0}, {"preload_max": operator.ne)
    """
    if operators is None:
        operators = {}
    return {
        k: v
        for k, v in data.items()
        if all(
            op(v.get(key, None), conditions[key])
            for key, condition_value in conditions.items()
            for op in [operators.get(key, operator.eq)]
        )
    }


def get_value(data: dict, key: str) -> list:
    return [k[key] for k in data.values()]


def assert_items_match(data: dict, keys: list) -> None:
    """
    When you want to compare against tests that have the same setting but there
    is not a canonical value for it, such as "iterations" or "hcl-memory", use
    the value from the first item in data as canonical and assert that all
    settings specified have the same value. In other words, enforce that the
    compared tests is appropriate.

    :param dict data: results
    :param list keys: filters

    >>> assert_items_match(data, ["iterations", "hcl-memory"])
    """
    conditions = {}
    failed = {}
    for key in keys:
        conditions[key] = get_value(data, key)
        if len(set(conditions[key])) > 1:
            failed[key] = conditions[key]
    if failed:
        names = get_value(data, "name")
        raise AssertionError(
            "Queried '{}' for identical '{}' but not all values match: "
            "{}".format(", ".join(names), ", ".join(failed.keys()), failed)
        )


def get_fname(index: int = 2) -> str:
    return sys._getframe(index).f_code.co_name


def get_pretty_graph_name(name) -> str:
    assert name.startswith("graph_")
    return name.replace("graph_", "").replace("_", "-")


def get_graphs() -> list:
    return [
        get_pretty_graph_name(method)
        for method in dir(Graph)
        if callable(getattr(Graph, method)) and method.startswith("graph_")
    ]


class Graph:  # pylint: disable=too-many-instance-attributes
    """
    Generate graphs from disposable performance results. To add a new graph add
    a new function that starts with "graph_XX", where XX is a 2 digit number
    and is responsible for the order in which graphs are shown and saved. See
    the following pseudo-code example:

    >>> def graph_99_test(self) -> None:
    ...     fig, ax = plt.subplots()
    ...     ax.bar(x, y)
    ...     self.end(plt)
    """

    def __init__(
        self,
        orig_data: dict,
        default_template: str = "",
        graphs: list | None = None,
        show: bool = True,
        show_image: bool = False,
        output_dir: str = "",
    ):
        logging.info("Initializing")
        self.orig_data = orig_data
        self.default_template = default_template
        self.graphs = graphs or []
        self.show = show
        self.output_dir = output_dir
        self.show_image = show_image
        self.graph_index = 0

        self.templates = sorted(set(get_value(self.orig_data, "template")))
        if self.default_template:
            self.data = filter_data(
                self.orig_data, {"template": self.default_template}
            )
            if not self.data:
                logging.critical(
                    "Default template specified not found: '%s'",
                    self.default_template,
                )
                sys.exit(1)
        else:
            logging.info("Default template not specified, using newest fedora")
            fedora_template = max(
                (
                    v
                    for v in self.orig_data.values()
                    if v["os-distribution"] == "fedora"
                ),
                key=lambda v: (
                    v["os-version"],
                    v["template"].endswith("-xfce"),
                ),
            )["template"]
            logging.info("Newest fedora is '%s'", fedora_template)
            self.data = filter_data(
                self.orig_data, {"template": fedora_template}
            )
            self.default_template = fedora_template

        items_must_match = [
            "iterations",
            "kernel",
            "kernelopts",
            "memory",
            "maxmem",
            "vcpus",
            "qrexec_timeout",
            "shutdown_timeout",
            "hcl-qubes",
            "hcl-xen",
            "hcl-kernel",
            "hcl-memory",
        ]
        assert_items_match(self.data, items_must_match)

        self.api_tests = filter_data(self.data, {"admin_api": True})

        self.dispvm_api_tests = filter_data(
            self.api_tests,
            {
                "non_dispvm": False,
                "admin_api": True,
                "concurrent": False,
                "extra_id": "",
            },
        )
        self.dispvm_api_tests_names = get_value(self.dispvm_api_tests, "name")

        self.dispvm_tests = filter_data(
            self.data,
            {
                "non_dispvm": False,
                "admin_api": False,
                "concurrent": False,
                "extra_id": "",
            },
        )
        self.dispvm_tests_means = get_value(self.dispvm_tests, "mean")
        self.dispvm_tests_names = get_value(self.dispvm_tests, "name")
        self.dispvm_hatch = [
            "/" if self.dispvm_tests[test]["concurrent"] else ""
            for test in self.dispvm_tests.keys()
        ]
        self.dispvm_colors = [
            (
                COLORS["Success Green"]
                if test["preload_max"]
                else COLORS["Alert Yellow"]
            )
            for name, test in self.dispvm_tests.items()
        ]

        self.stage_dict = {
            "dom": {"color": COLORS["Icon Dark Gray"], "legend": "Others"},
            "disp": {"color": COLORS["Middle Gray"], "legend": "Others"},
            "exec": {"color": COLORS["Warning Orange"], "legend": "Execution"},
            "clean": {"color": COLORS["Sub Gray"], "legend": "Cleanup"},
        }
        self.preload_stage_dict = {
            "dom": {"color": COLORS["Icon Dark Gray"], "legend": "Others"},
            "disp": {"color": COLORS["Middle Gray"], "legend": "Others"},
            "exec": {"color": COLORS["Primary Blue"], "legend": "Execution"},
            "clean": {"color": COLORS["Sub Gray"], "legend": "Cleanup"},
        }

        self.stages = []
        for test, result in self.api_tests.items():
            if result.get("api_results", {}).get("stage", {}):
                self.stages.extend(result["api_results"]["stage"].keys())
        self.stage_order = ["dom", "disp", "exec", "clean", "total"]
        self.stages = sorted(
            list(set(self.stages)),
            key=lambda s: (
                self.stage_order.index(s)
                if s in self.stage_order
                else len(self.stage_order)
            ),
        )
        logging.info("Initialized")

    def run(self) -> None:
        avail_graphs = get_graphs()
        for i, graph in enumerate(avail_graphs):
            self.graph_index = i
            method = getattr(self, "graph_" + graph.replace("-", "_"))
            if not self.graphs or graph in self.graphs:
                logging.info("Generating graph %s", graph)
                try:
                    method()
                    logging.info("Completed graph %s", graph)
                except NotImplementedError:
                    logging.warning("Skipped unfinished graph %s", graph)

    def end(self, plot, name: str = "") -> None:
        """Save figure, show plot and close it."""
        if name:
            name = get_fname() + "_" + name
        else:
            name = get_fname()

        if self.output_dir:
            logging.info("Saving figure %s", name)
            file = os.path.join(self.output_dir, name)
            plot.savefig(file, bbox_inches="tight", pad_inches=1)
        if self.show:
            logging.info("Showing %s", name)
            plot.show()
        plot.close()

        if self.output_dir and self.show_image:
            full_file = file + ".png"
            logging.info("Showing image %s", full_file)
            img = matplotlib.image.imread(full_file)
            plot.imshow(img)
            plot.axis("off")
            plot.show()
            plot.close()

    def bar_plot(
        self,
        tests,
        titles: list = None,
        title_query: str = "",
        title_prefix: bool = True,
        keys: list = ["mean"],
    ) -> list[matplotlib.figure.Figure]:
        """
        Assemble figure of bar plot where normal and preload tests are grouped.
        Each tests passed is subplotted.
        """
        if not tests:
            raise ValueError("tests not provided")
        figures = []
        colors = [
            COLORS["Sub Gray"],
            COLORS["Primary Blue"],
        ]
        test_len = len(tests)
        cols = math.ceil(math.sqrt(test_len))
        rows = math.ceil(test_len / cols)
        data_tests = {k: v for t in tests for k, v in t.items()}
        for key in keys:
            fig, axs = plt.subplots(
                rows, cols, figsize=(2 * cols * WIDTH, 2 * rows * HEIGHT)
            )
            axs = axs.flatten() if test_len > 1 else [axs]
            top_value = math.ceil(max(get_value(data_tests, key)))
            top_tick = int(10 * top_value / 10)
            yticks = [round(x, 1) for x in np.linspace(0, top_tick, 4)]
            for num, test_method in enumerate(tests):
                normal_tests_method = filter_data(
                    test_method, {"preload_max": 0}
                )
                iterations = get_value(normal_tests_method, "iterations")[0]
                preload_tests_method = filter_data(
                    test_method,
                    {"preload_max": 1},
                    {"preload_max": operator.ge},
                )
                normal_tests_names_pretty = wrap_text(
                    get_value(normal_tests_method, "pretty_name"), 25
                )
                label_array = np.arange(len(normal_tests_names_pretty))
                normal_values = get_value(normal_tests_method, key)
                preload_values = get_value(preload_tests_method, key)
                tests_legend = ["Normal", "Preload"]
                tests_values = [
                    normal_values,
                    preload_values,
                ]

                values_count = len(tests_values)
                width = 0.8 / values_count
                bars = []
                for i, values in enumerate(tests_values):
                    positions = (
                        label_array + (i - (values_count - 1) / 2) * width
                    )
                    bars.append(
                        axs[num].bar(
                            positions,
                            values,
                            width=width,
                            color=colors[i],
                            label=tests_legend[i],
                        )
                    )
                for bar_plot in bars:
                    axs[num].bar_label(bar_plot, fmt="%.2f", padding=0)

                ratio = np.divide(
                    normal_values,
                    preload_values,
                    out=np.zeros_like(normal_values, dtype=float),
                    where=preload_values != 0,
                )

                for i in range(len(normal_tests_names_pretty)):
                    # This difference is the same when comparing the mean
                    # iteration time and the total run time because the mean
                    # calculation is the total run time divided by the total
                    # iterations.
                    xpos = label_array[i]
                    max_mean = max(normal_values[i], preload_values[i])
                    min_mean = min(normal_values[i], preload_values[i])
                    height = ((max_mean - min_mean) / 2) + min_mean
                    if ratio[i] > 1:
                        color = COLORS["Success Green"]
                    else:
                        color = COLORS["Danger Red"]
                    axs[num].text(
                        xpos,
                        height,
                        f"{ratio[i]:.2f}x",
                        color=color,
                        ha="left",
                        va="center",
                    )

                axs[num].set_ylabel("Time (s)")
                pretty_iterations = "over {} iterations".format(iterations)
                pretty_title = ""
                if title_prefix:
                    pretty_title = "{} run time {}".format(
                        key.capitalize(), pretty_iterations
                    )
                if title_query or (titles and len(titles) >= num):
                    if title_prefix:
                        pretty_title += " with"
                    if title_query:
                        with_title = " {}".format(
                            get_value(test_method, title_query)[0]
                        )
                    else:
                        with_title = " {}".format(titles[num])
                    pretty_title += with_title
                axs[num].set_title(pretty_title)
                axs[num].set_yticks(yticks)
                axs[num].set_xticks(label_array, normal_tests_names_pretty)
                axs[num].legend()
            for axis in axs[test_len:]:
                axis.set_visible(False)
            figures.append(fig)
        return figures

    def graph_00_specs(self) -> None:
        first_test = list(self.data.keys())[0]
        data = self.data[first_test]
        specs = {
            "date": data["date"],
            "template-buildtime": data["template-buildtime"],
            "kernel": data["kernel"],
            "hcl-memory": data["hcl-memory"],
            "hcl-certified": data["hcl-certified"],
            "hcl-qubes": data["hcl-qubes"],
            "hcl-xen": data["hcl-xen"],
            "hcl-model": data["hcl-model"],
            "hcl-bios": data["hcl-bios"],
            "hcl-cpu": data["hcl-cpu"],
        }
        specs_text = """
        System specifications:

        - Date: {}
        - Template: {}
        - Template build time: {}
        - Certified: {}
        - Qubes: {}
        - Kernel: {}
        - Xen: {}
        - RAM: {} MiB
        - CPU: {}
        - BIOS: {}
        """.format(
            specs["date"],
            self.default_template,
            specs["template-buildtime"],
            specs["hcl-certified"],
            specs["hcl-qubes"],
            specs["kernel"],
            specs["hcl-xen"],
            specs["hcl-memory"],
            specs["hcl-cpu"],
            specs["hcl-bios"],
        )
        fig = plt.figure(figsize=(2 * WIDTH, 2 * HEIGHT))
        fig.clf()
        fig.text(
            0.5,
            0.5,
            specs_text,
            ha="left",
            va="center",
        )
        self.end(plt)

    def graph_01_bar(self) -> None:
        normal_tests = filter_data(self.dispvm_api_tests, {"preload_max": 0})
        assert_items_match(normal_tests, ["iterations"])
        preload_tests = filter_data(
            self.dispvm_api_tests,
            {"preload_max": 1},
            {"preload_max": operator.ge},
        )
        assert_items_match(preload_tests, ["iterations"])

        fig = self.bar_plot([self.dispvm_api_tests])[0]
        assert_items_match(preload_tests, ["preload_max"])
        preload_max = get_value(preload_tests, "preload_max")[0]
        caption = (
            f"Compares workflows of normal disposables and {preload_max} "
            + "preloaded."
        )
        fig.supxlabel(
            caption,
            wrap=True,
            color=CAPTION_COLOR,
        )
        self.end(plt)

    def graph_02_stage_stack(self) -> None:
        tests = filter_data(self.dispvm_api_tests, {"preload_max": 0})
        assert_items_match(tests, ["iterations"])
        iterations = get_value(tests, "iterations")[0]
        tests_names_pretty = get_value(tests, "pretty_name")
        preload_tests = filter_data(
            self.dispvm_api_tests,
            {"preload_max": 1},
            {"preload_max": operator.ge},
        )

        important_stages = ["exec", "clean", "total"]
        label_array = np.arange(len(tests_names_pretty))
        label_count = len(tests_names_pretty)
        width = 0.8 / label_count
        up_to_exec = self.stages[:-2]
        for num, stage_intro in enumerate([up_to_exec, self.stages]):
            fig, axs = plt.subplots(figsize=(WIDTH * 3, HEIGHT * 3))
            bottom = np.zeros(len(tests_names_pretty))
            bottom_preload = np.zeros(len(tests_names_pretty))
            for stage in stage_intro:
                means_stage = np.array(
                    [
                        test["api_results"]["stage"][stage]["mean"]
                        for test in tests.values()
                    ]
                )
                preload_means_stage = np.array(
                    [
                        test["api_results"]["stage"][stage]["mean"]
                        for test in preload_tests.values()
                    ]
                )
                if stage in ["exec", "total"]:
                    ratio = np.divide(
                        means_stage,
                        preload_means_stage,
                        out=np.zeros_like(means_stage, dtype=float),
                        where=preload_means_stage != 0,
                    )

                    for i in range(label_count):
                        if stage not in stage_intro:
                            break
                        if stage == "exec" and "total" in stage_intro:
                            break
                        xpos = label_array[i]
                        max_mean = max(means_stage[i], preload_means_stage[i])
                        min_mean = min(means_stage[i], preload_means_stage[i])
                        height = ((max_mean - min_mean) / 2) + min_mean
                        if ratio[i] > 1:
                            color = COLORS["Success Green"]
                        else:
                            color = COLORS["Danger Red"]
                        axs.text(
                            xpos,
                            height,
                            f"{ratio[i]:.2f}x",
                            color=color,
                        )

                if stage != "total":

                    positions = label_array - width / 2
                    bars_normal = axs.bar(
                        positions,
                        means_stage,
                        width=width,
                        bottom=bottom,
                        color=self.stage_dict[stage]["color"],
                        label=stage if stage not in important_stages else None,
                    )
                    bottom += means_stage

                    positions = label_array + width / 2
                    bars_preload = axs.bar(
                        positions,
                        preload_means_stage,
                        width=width,
                        bottom=bottom_preload,
                        color=self.preload_stage_dict[stage]["color"],
                    )
                    bottom_preload += preload_means_stage

                    if stage in important_stages:
                        axs.bar_label(
                            bars_normal, fmt="%.2f", label_type="center"
                        )
                        axs.bar_label(
                            bars_preload, fmt="%.2f", label_type="center"
                        )
                    if stage == list(self.stage_dict.keys())[-1]:
                        axs.bar_label(
                            bars_normal, fmt="%.2f", label_type="edge"
                        )
                        axs.bar_label(
                            bars_preload, fmt="%.2f", label_type="edge"
                        )

            plt.xticks(label_array, tests_names_pretty)
            plt.ylabel("Time (s)")
            pretty_iterations = " over {} iterations".format(iterations)
            plt.title("Mean time per stage" + pretty_iterations)
            legend_handles = [
                matplotlib.patches.Patch(
                    color=value["color"], label=value["legend"]
                )
                for stage, value in list(reversed(self.stage_dict.items()))
                if stage in important_stages and stage in stage_intro
            ]
            legend_handles.insert(
                -1,
                *[
                    matplotlib.patches.Patch(
                        color=value["color"], label="Preload " + value["legend"]
                    )
                    for key, value in list(
                        reversed(self.preload_stage_dict.items())
                    )
                    if key in ["exec"]
                ],
            )
            plt.legend(handles=legend_handles)
            assert_items_match(preload_tests, ["preload_max"])
            preload_max = get_value(preload_tests, "preload_max")[0]
            caption = (
                f"Compares workflows of normal disposables and {preload_max} "
                + "preloaded. Stages that compose a call are stacked."
            )
            fig.supxlabel(
                caption,
                wrap=True,
                color=CAPTION_COLOR,
            )
            self.end(plt, str(num))

    def graph_03_stage_dist(self) -> None:
        tests = self.dispvm_api_tests
        assert_items_match(tests, ["iterations"])
        tests_names_pretty = get_value(tests, "pretty_name")
        for num, stage in enumerate(["exec", "clean", "total"]):
            stage_values = []
            for _, test in tests.items():
                stage_values.append(
                    test["api_results"]["stage"][stage]["values"]
                )
            fig, axs = plt.subplots(figsize=(WIDTH * 3, HEIGHT * 3))
            x_pos = np.arange(1, len(stage_values) + 1)
            jitter_strength = 0.1
            for i, values in enumerate(stage_values, start=1):
                x_jittered = (
                    i + (np.random.rand(len(values)) - 0.5) * jitter_strength
                )
                color = (
                    COLORS["Primary Blue"]
                    if tests[list(tests.keys())[i - 1]]["preload_max"]
                    else COLORS["Light Gray"]
                )
                axs.scatter(x_jittered, values, s=100, alpha=0.8, color=color)
            axs.set_xticks(x_pos, wrap_text(tests_names_pretty, 25))
            axs.set_ylabel("Time (s)")
            if stage == "total":
                stage_pretty = stage.capitalize()
            else:
                stage_pretty = self.stage_dict[stage]["legend"]
            axs.set_title("%s stage distribution" % stage_pretty)
            caption = (
                f"Compares {stage_pretty} stage of API workflows of normal "
                + "disposables and preloaded ones using scatter distribution "
                + "with jitter to highlight the density."
            )
            fig.supxlabel(
                caption,
                wrap=True,
                color=CAPTION_COLOR,
            )
            self.end(plt, str(num) + "_" + stage)

    def graph_04_line(self) -> None:
        def filter_preload(value, cond):  # pylint: disable=unused-argument
            return value == 0 or (3 <= value <= 5)

        tests = filter_data(
            self.api_tests,
            {
                "non_dispvm": False,
                "admin_api": True,
                "concurrent": False,
                "gui": False,
                "preload_max": None,
            },
            {
                "preload_max": filter_preload,
            },
        )
        tests = dict(sorted(tests.items(), key=lambda x: x[1]["preload_max"]))
        for num, stage in enumerate(["exec", "clean", "total"]):
            fig, axs = plt.subplots(figsize=(WIDTH * 3, HEIGHT * 3))
            points_seen = set()
            for test in tests.values():
                name = test["pretty_name"]
                iteration_data = test.get("api_results", {}).get(
                    "iteration", {}
                )
                iterations = range(1, test["iterations"] + 1)
                stage_data = test.get("api_results", {}).get("stage", {})
                mean = round(stage_data[stage]["mean"], 1)
                times = [iteration_data[str(it)][stage] for it in iterations]
                axs.plot(
                    iterations,
                    times,
                    label=f"{name} \u03bc {mean}",
                    linestyle="--",
                )
                rounder = 1
                for x_val, y_val in zip(iterations, times):
                    if (x_val, round(y_val, rounder)) in points_seen:
                        continue
                    points_seen.add((x_val, round(y_val, rounder)))
                    axs.text(
                        x_val,
                        y_val,
                        str(round(y_val, rounder)),
                        ha="center",
                    )
            if stage == "total":
                stage_pretty = stage.capitalize()
            else:
                stage_pretty = self.stage_dict[stage]["legend"]
            axs.set_ylabel("Time (seconds)")
            axs.set_title(f"{stage_pretty} time per iteration")
            axs.set_xticks(iterations)
            axs.legend()
            caption = (
                "Compares workflows of normal disposables and preloaded ones "
                + f"during {stage_pretty} stage."
            )
            fig.supxlabel(
                caption,
                wrap=True,
                color=CAPTION_COLOR,
            )
            self.end(plt, str(num) + "_" + stage)

    def graph_08_template(self) -> None:
        tests = filter_data(
            self.orig_data,
            {
                "admin_api": True,
                "non_dispvm": False,
                "extra_id": "",
                "concurrent": False,
            },
        )
        template_tests = []
        for template in self.templates:
            template_tests.append(filter_data(tests, {"template": template}))

        fig = self.bar_plot(
            template_tests, title_query="template", title_prefix=False
        )[0]
        fig.suptitle("Mean run time with different templates")
        preload_tests = filter_data(
            tests, {"preload_max": 1}, {"preload_max": operator.ge}
        )
        assert_items_match(preload_tests, ["preload_max"])
        preload_max = get_value(preload_tests, "preload_max")[0]
        caption = (
            f"Compares workflows of normal disposables and {preload_max} "
            + "preloaded."
        )
        fig.supxlabel(
            caption,
            wrap=True,
            color=CAPTION_COLOR,
        )
        self.end(plt)

    def graph_09_method(self) -> None:
        orig_tests = filter_data(
            self.data, {"non_dispvm": False, "extra_id": ""}
        )
        for query in ["concurrent-gui", "gui", "concurrent", "gui-concurrent"]:
            if query == "concurrent-gui":
                tests = filter_data(orig_tests, {"concurrent": True})
                query_name = "with concurrency (with and without GUI),"
                query_file = "wconc_nogui_gui"
            elif query == "gui":
                tests = filter_data(orig_tests, {"concurrent": False})
                query_name = "with and without GUI,"
                query_file = "nogui_gui"
            elif query == "concurrent":
                tests = filter_data(orig_tests, {"gui": False})
                query_name = "with and without concurrency,"
                query_file = "noconc_conc"
            elif query == "gui-concurrent":
                tests = filter_data(orig_tests, {"gui": True})
                query_name = "with GUI (with and without concurrency),"
                query_file = "wgui_noconc_conc"
            else:
                raise ValueError

            dom0_api = filter_data(
                tests, {"from_dom0": True, "admin_api": True}
            )
            dom0_qvm = filter_data(
                tests, {"from_dom0": True, "admin_api": False}
            )
            vm_qrexec = filter_data(
                tests, {"from_dom0": False, "admin_api": False}
            )

            fig = self.bar_plot(
                [dom0_api, dom0_qvm, vm_qrexec],
                titles=["dom0 API", "dom0 qvm", "qube qrexec-client-vm"],
                title_prefix=False,
            )[0]
            fig.suptitle(
                "Mean run time {} using different callers".format(query_name),
            )
            preload_tests = filter_data(
                tests, {"preload_max": 1}, {"preload_max": operator.ge}
            )
            assert_items_match(preload_tests, ["preload_max"])
            preload_max = get_value(preload_tests, "preload_max")[0]
            caption = (
                f"Compares workflows of normal disposables and {preload_max} "
                + "preloaded."
            )
            fig.supxlabel(
                caption,
                wrap=True,
                color=CAPTION_COLOR,
            )
            self.end(plt, query_file)


def main() -> None:
    desc = "Reads dispvm performance tests from JSON and create graph"
    epilog = (
        "The default behavior is to show plots. Sample data at "
        + "tests-data/dispvm_perf/"
    )
    avail_graphs = get_graphs()
    avail_graphs_pretty = ", ".join(avail_graphs)
    template_desc = "Select template to analyze. Defaults to the newest fedora"
    graphs_desc = (
        "specify one or more graphs to show. Available options: "
        + avail_graphs_pretty
    )
    parser = argparse.ArgumentParser(description=desc, epilog=epilog)
    parser.add_argument(
        "-L",
        "--log-level",
        metavar="LEVEL",
        default="WARNING",
        help="Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)",
    )
    parser.add_argument(
        "-t",
        "--template",
        metavar="TEMPLATE",
        help=template_desc,
    )
    parser.add_argument(
        "-g",
        "--graph",
        metavar="GRAPH,...",
        action="store",
        help=graphs_desc,
    )
    parser.add_argument(
        "-n",
        "--no-show",
        action="store_false",
        default=True,
        help="don't display the plots",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        help="directory to save plots",
    )
    parser.add_argument(
        "-i",
        "--show-image",
        action="store_true",
        default=False,
        help="display graphs as image, requires --output-dir",
    )
    parser.add_argument(
        "file",
        metavar="FILE",
        type=argparse.FileType("r"),
        default="-",
        help="input file or '-' (or leave blank) for stdin",
    )
    args = parser.parse_args()

    if args.show_image and not args.output_dir:
        parser.error("--show-image requires --output-dir")

    log_level = getattr(logging, args.log_level.upper(), logging.WARNING)
    logging.basicConfig(
        format="%(asctime)s %(levelname)s %(funcName)s: %(message)s",
        level=log_level,
    )

    graphs = None
    if args.graph:
        graphs = [graph.strip() for graph in args.graph.split(",")]
        for graph in graphs:
            if graph not in avail_graphs:
                msg = (
                    "Provided graph "
                    + repr(graph)
                    + " is invalid. Available graphs: "
                    + str(avail_graphs)
                )
                raise ValueError(msg)

    logging.info("Loading data")
    data = json.load(args.file)
    logging.info("Loaded data")
    if args.output_dir:
        os.makedirs(args.output_dir, exist_ok=True)
    graph = Graph(
        data,
        default_template=args.template,
        graphs=graphs,
        show=args.no_show,
        output_dir=args.output_dir,
        show_image=args.show_image,
    )
    graph.run()


if __name__ == "__main__":
    main()
