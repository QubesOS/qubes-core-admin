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
# marek:
#   * Compare same test results (different reports) and check for discrepancies.
#     Define a percentage threshold. For all performance tests.
#   * Compare same test on different templates
#   * The big bar char grouped preload and normal and gui and non gui, that is
#     confusing.
# marta:
#   * Every chart should answer a single question or illustrate a single point,
#     unless the chart is big and the time to spend on it is also big, less
#     optimal because it may include too much complexity in a single graph.
#     Less is better.
#   * Asked for some charts such as the line chart to be split by the stages,
#     exec and total, side by side.
#   * Some charts would benefit by the difference in percentage
#   * The X labels are not clear without extra knowledge
#   * The stacked stage bar chart:
#     * Should use a lighter gray for unimportant stages
#     * Consider the unimportant legends appearing as "others"
#   * Don't present statistical distribution graphs to a general audience
#   * Remove median from general audience graphso

# TODO: ben: add to test packages
# Debian: fonts-open-sans python3-numpy python-matplotlib
# Fedora: open-sans-fonts python3-numpy python-matplotlib
import argparse
import json
import operator
import os
import numpy as np
from typing import Callable, Any
import matplotlib as mpl
from matplotlib.patches import Patch
from matplotlib.lines import Line2D
import matplotlib.pyplot as plt

mpl.rcParams["toolbar"] = "none"
plt.style.use("dark_background")
plt.rcParams["font.family"] = "Open Sans"
plt.rcParams["font.size"] = 20
plt.rcParams["axes.titlesize"] = 30
plt.rcParams["axes.labelsize"] = 30
plt.rcParams["axes.titleweight"] = "bold"


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


def get_value(data: dict, key) -> list:
    return [k[key] for k in data.values()]


def prettify_name(names: list) -> list:
    new_names = [n.replace("-", "\n") for n in names]
    return new_names


class Graph:  # pylint: disable=too-many-instance-attributes
    def __init__(
        self,
        orig_data: dict,
        default_template: str = "",
        graphs: list | None = None,
        show: bool = True,
        output_dir: str = "",
    ):
        self.orig_data = orig_data
        self.default_template = default_template
        self.graphs = graphs or []
        self.show = show
        self.output_dir = output_dir
        self.graph_index = 0

        self.templates = set(get_value(self.orig_data, "template"))
        if self.default_template:
            self.data = filter_data(
                self.orig_data, {"template": self.default_template}
            )
        else:
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
            self.data = filter_data(
                self.orig_data, {"template": fedora_template}
            )

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
        self.dispvm_api_tests_names_pretty = prettify_name(
            self.dispvm_api_tests_names
        )

        self.dispvm_tests = filter_data(
            self.data,
            {
                "non_dispvm": False,
                "admin_api": False,
                "concurrent": False,
                "extra_id": "",
            },
        )
        # TODO: is sorting still useful?
        # self.dispvm_tests = dict(
        #    sorted(self.dispvm_tests.items(), key=lambda item: (item[1]["preload_max"], item[1]["concurrent"]))
        # )
        self.dispvm_tests_means = get_value(self.dispvm_tests, "mean")
        self.dispvm_tests_names = get_value(self.dispvm_tests, "name")
        self.dispvm_tests_names_pretty = prettify_name(self.dispvm_tests_names)
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
            "dom": {"color": COLORS["Sub Gray"], "legend": "AppVM obj"},
            "disp": {"color": COLORS["Middle Gray"], "legend": "DispVM obj"},
            "exec": {"color": COLORS["Warning Orange"], "legend": "Execution"},
            "clean": {"color": COLORS["Icon Dark Gray"], "legend": "Cleanup"},
        }
        self.preload_stage_dict = {
            "dom": {"color": COLORS["Sub Gray"], "legend": "AppVM obj"},
            "disp": {"color": COLORS["Middle Gray"], "legend": "DispVM obj"},
            "exec": {"color": COLORS["Primary Blue"], "legend": "Execution"},
            "clean": {"color": COLORS["Icon Dark Gray"], "legend": "Cleanup"},
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

    def end(self, graph, plot) -> None:
        if self.output_dir:
            file = str(self.graph_index) + "_" + graph
            plot.savefig(os.path.join(self.output_dir, file))
        if self.show:
            plot.show()

    def graph_std_bar(self) -> None:
        normal_tests = filter_data(self.dispvm_tests, {"preload_max": 0})
        normal_tests_names_pretty = prettify_name(
            get_value(normal_tests, "name")
        )
        preload_tests = filter_data(
            self.dispvm_tests,
            {"preload_max": 1},
            {"preload_max": operator.ge},
        )

        colors = [
            COLORS["Sub Gray"],
            COLORS["Primary Blue"],
        ]
        tests_legend = ["Normal", "Preload", "Normal (GUI)", "Preload (GUI)"]

        for key in ["mean", "total"]:
            fig, axs = plt.subplots(figsize=(30, 15))
            label_array = np.arange(len(normal_tests_names_pretty))
            normal_values = get_value(normal_tests, key)
            preload_values = get_value(preload_tests, key)
            tests_values = [
                normal_values,
                preload_values,
            ]

            values_count = len(tests_values)
            width = 0.8 / values_count

            bars = []
            for i, values in enumerate(tests_values):
                positions = label_array + (i - (values_count - 1) / 2) * width
                bars.append(
                    axs.bar(
                        positions,
                        values,
                        width=width,
                        color=colors[i],
                        label=tests_legend[i],
                    )
                )
            for bar_plot in bars:
                plt.bar_label(bar_plot, fmt="%.2f", padding=0)

            ratio = np.divide(
                normal_values,
                preload_values,
                out=np.zeros_like(normal_values, dtype=float),
                where=preload_values != 0,
            )

            for i in range(len(normal_tests_names_pretty)):
                # This difference is the same when comparing the mean iteration
                # time and the total run time because the mean calculation is
                # the total run time divided by the total iterations.
                xpos = label_array[i]
                max_mean = max(normal_values[i], preload_values[i])
                min_mean = min(normal_values[i], preload_values[i])
                height = ((max_mean - min_mean) / 2) + min_mean
                if ratio[i] > 1:
                    color = COLORS["Success Green"]
                else:
                    color = COLORS["Danger Red"]
                axs.text(
                    xpos + 0.1,
                    height,
                    f"{ratio[i]:.2f}x",
                    color=color,
                    ha="left",
                    va="center",
                )

            axs.set_ylabel("Time (s)")
            axs.set_title(key.capitalize() + " run time per test")
            axs.set_xticks(label_array)
            axs.set_xticklabels(normal_tests_names_pretty)
            axs.legend()
            plt.subplots_adjust(left=0.1, right=0.9, top=0.9, bottom=0.2)
            caption = (
                "Compares user workflows of normal disposables and preloaded"
                + " ones. The first group shows vm-dispvm calls while the "
                + "second group shows dom0-dispvm calls."
            )
            fig.text(
                0.5,
                0.01,
                caption,
                wrap=True,
                ha="center",
                color=CAPTION_COLOR,
            )
            self.end("std-bar-" + key, plt)

    def graph_stage_dist(self) -> None:
        for stage in ["exec", "clean", "total"]:
            stage_values = []
            for _, test in self.dispvm_api_tests.items():
                stage_values.append(
                    test["api_results"]["stage"][stage]["values"]
                )
            fig, axs = plt.subplots(figsize=(30, 15))
            violin_parts = axs.violinplot(
                stage_values,
                showmeans=True,
                showmedians=True,
                showextrema=False,
            )
            axs.set_xticks(
                range(1, len(self.dispvm_api_tests_names_pretty) + 1),
                self.dispvm_api_tests_names_pretty,
            )
            median = violin_parts["cmedians"]
            median.set_color(COLORS["Alert Yellow"])
            median = violin_parts["cmeans"]
            median.set_color(COLORS["Alert Yellow"])
            median.set_linestyle("--")
            for violin, test in zip(
                violin_parts["bodies"], self.dispvm_api_tests.values()
            ):
                color = (
                    COLORS["Primary Blue"]
                    if test["preload_max"]
                    else COLORS["Light Gray"]
                )
                violin.set_facecolor(color)
                violin.set_alpha(0.8)
            axs.set_ylabel("Time (s)")
            axs.set_title(f"{stage.capitalize()} stage distribution per test")
            legend_handles = [
                Patch(color=COLORS["Light Gray"], label="Normal"),
                Patch(color=COLORS["Primary Blue"], label="Preload"),
                Line2D([0], [0], color=COLORS["Alert Yellow"], label="Mean"),
                Line2D(
                    [0],
                    [0],
                    color=COLORS["Alert Yellow"],
                    linestyle="--",
                    label="Median",
                ),
            ]
            axs.legend(handles=legend_handles)
            plt.subplots_adjust(left=0.1, right=0.9, top=0.9, bottom=0.2)
            caption = (
                f"Compares {stage} stage of API workflows of normal disposables "
                + "and preloaded ones using violin distribution to highlight "
                + " the density."
            )
            fig.text(
                0.5,
                0.01,
                caption,
                wrap=True,
                ha="center",
                color=CAPTION_COLOR,
            )
            self.end("stage-dist-" + stage, plt)

    def graph_stage_stack(self) -> None:
        tests = filter_data(self.dispvm_api_tests, {"preload_max": 0})
        tests_names_pretty = prettify_name(get_value(tests, "name"))
        preload_tests = filter_data(
            self.dispvm_api_tests,
            {"preload_max": 1},
            {"preload_max": operator.ge},
        )

        bottom = np.zeros(len(tests_names_pretty))
        bottom_preload = np.zeros(len(tests_names_pretty))
        fig, axs = plt.subplots(figsize=(30, 15))
        important_stages = ["exec", "clean", "total"]
        label_array = np.arange(len(tests_names_pretty))
        label_count = len(tests_names_pretty)
        width = 0.8 / label_count
        for stage in self.stages:
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
                    xpos = label_array[i]
                    max_mean = max(means_stage[i], preload_means_stage[i])
                    min_mean = min(means_stage[i], preload_means_stage[i])
                    height = ((max_mean - min_mean) / 2) + min_mean
                    if ratio[i] > 1:
                        color = COLORS["Success Green"]
                    else:
                        color = COLORS["Danger Red"]
                    axs.text(
                        xpos + 0.1,
                        height,
                        f"{ratio[i]:.2f}x {stage}",
                        color=color,
                    )
            if stage == "total":
                continue

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
                axs.bar_label(bars_normal, fmt="%.2f", label_type="center")
                axs.bar_label(bars_preload, fmt="%.2f", label_type="center")
            if stage == list(self.stage_dict.keys())[-1]:
                axs.bar_label(bars_normal, fmt="%.2f", label_type="edge")
                axs.bar_label(bars_preload, fmt="%.2f", label_type="edge")
        plt.xticks(label_array, tests_names_pretty)
        plt.ylabel("Time (s)")
        plt.title("Mean time per stage per test (Normal vs Preload)")
        legend_handles = [
            Patch(color=value["color"], label=value["legend"])
            for _, value in self.stage_dict.items()
        ]
        legend_handles.insert(
            -1,
            *[
                Patch(color=value["color"], label="Preload " + value["legend"])
                for key, value in self.preload_stage_dict.items()
                if key in ["exec"]
            ],
        )
        plt.legend(handles=legend_handles)
        plt.subplots_adjust(left=0.1, right=0.9, top=0.9, bottom=0.2)
        caption = (
            "Compares API workflows of normal disposables and preloaded"
            + " ones. Stages that compose a single call are stacked."
        )
        fig.text(
            0.5,
            0.01,
            caption,
            wrap=True,
            ha="center",
            color=CAPTION_COLOR,
        )
        self.end("stage-stack", plt)

    def graph_line(self) -> None:
        fig, axs = plt.subplots(figsize=(30, 15))
        tests = filter_data(self.dispvm_api_tests, {"gui": False})
        for test in tests.values():
            name = test["name"]
            iteration_data = test.get("api_results", {}).get("iteration", {})
            iterations = range(1, test["iterations"])
            exec_times = [iteration_data[str(it)]["exec"] for it in iterations]
            total_times = [
                iteration_data[str(it)]["total"] for it in iterations
            ]
            if test["preload_max"] > 0:
                exec_color = COLORS["Info Blue"]
                total_color = COLORS["Qubes Blue"]
            else:
                exec_color = COLORS["Alert Yellow"]
                total_color = COLORS["Warning Orange"]
            axs.plot(
                iterations,
                exec_times,
                label=f"{name} exec",
                linestyle="--",
                color=exec_color,
            )
            axs.plot(
                iterations,
                total_times,
                label=f"{name} total",
                linestyle="-",
                color=total_color,
            )
            for (xi, yi) in zip(iterations, exec_times):
                axs.text(xi, yi, str(round(yi, 1)), ha='center', va='bottom')
            for (xi, yi) in zip(iterations, total_times):
                axs.text(xi, yi, str(round(yi, 1)), ha='center', va='bottom')

        axs.set_xlabel("Iteration")
        axs.set_ylabel("Time (seconds)")
        axs.set_title("Mean time per iteration for selected groups")
        axs.set_xticks(iterations)
        axs.legend()
        plt.subplots_adjust(left=0.1, right=0.9, top=0.9, bottom=0.2)
        caption = (
            "Compares user workflows of normal disposables and preloaded"
            + " ones. The first group shows vm-dispvm calls while the "
            + "second group shows dom0-dispvm calls."
        )
        fig.text(
            0.5,
            0.01,
            caption,
            wrap=True,
            ha="center",
            color=CAPTION_COLOR,
        )
        self.end("line", plt)

    def run(self) -> None:
        graph_methods = {
            "std-bar": self.graph_std_bar,
            "stage-stack": self.graph_stage_stack,
            "stage-dist": self.graph_stage_dist,
            "line": self.graph_line,
        }
        for i, (graph, method) in enumerate(graph_methods.items()):
            self.graph_index = i
            if not self.graphs or graph in self.graphs:
                method()


def main() -> None:
    desc = "Reads dispvm performance tests from JSON and create graph"
    epilog = "Sample data at tests-data/dispvm_perf.json"
    avail_graphs = ["std-bar", "stage-dist", "stage-stack", "line"]
    avail_graphs_pretty = ", ".join(avail_graphs)
    template_desc = "Select template to analyze. Defaults to the newest fedora"
    graphs_desc = (
        "specify one or more graphs to show. Available options: "
        + avail_graphs_pretty
    )
    parser = argparse.ArgumentParser(description=desc, epilog=epilog)
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
        "file",
        metavar="FILE",
        type=argparse.FileType("r"),
        default="-",
        help="input file or '-' (or leave blank) for stdin",
    )
    args = parser.parse_args()
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

    data = json.load(args.file)
    graph = Graph(
        data,
        default_template=args.template,
        graphs=graphs,
        show=args.no_show,
        output_dir=args.output_dir,
    )
    graph.run()


if __name__ == "__main__":
    main()
