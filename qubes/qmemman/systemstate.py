#
# The Qubes OS Project, https://www.qubes-os.org/
#
# Copyright (C) 2010  Rafal Wojtczuk  <rafal@invisiblethingslab.com>
# Copyright (C) 2013 Marek Marczykowski-Górecki
#                           <marmarek@invisiblethingslab.com>
#
# This library is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public
# License as published by the Free Software Foundation; either
# version 2 of the License, or (at your option) any later version.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU General Public
# License along with this library; if not, see <https://www.gnu.org/licenses/>.

import functools
import logging
import os
import time
import xen.lowlevel  # pylint: disable=import-error
from pathlib import Path
from typing import Optional

import qubes.qmemman
from qubes.qmemman.domainstate import DomainState

BALLOON_DELAY = 0.1
XEN_FREE_MEM_LEFT = 50 * 1024 * 1024
XEN_FREE_MEM_MIN = 25 * 1024 * 1024
# Overhead of per-page Xen structures, taken from OpenStack
# nova/virt/xenapi/driver.py
# see https://wiki.openstack.org/wiki/XenServer/Overhead
MEM_OVERHEAD_FACTOR = 1.0 / 1.00781
CHECK_PERIOD_S = 3
CHECK_MB_S = 100
MIN_TOTAL_MEMORY_TRANSFER = 150 * 1024 * 1024
MIN_MEM_CHANGE_WHEN_UNDER_PREF = 15 * 1024 * 1024


class SystemState:
    def __init__(self) -> None:
        self.log = logging.getLogger("qmemman.systemstate")
        self.log.debug("SystemState()")

        self.dom_dict: dict[str, DomainState] = {}
        self.xc: xen.lowlevel.xc.xc = None
        self.xs: xen.lowlevel.xs.xs = None
        self.all_phys_mem: int = 0

    def init(self) -> None:
        self.xc = xen.lowlevel.xc.xc()
        self.xs = xen.lowlevel.xs.xs()
        # We divide total and free physical memory by this to get "assignable"
        # memory
        try:
            self.all_phys_mem = int(
                self.xc.physinfo()["total_memory"] * 1024 * MEM_OVERHEAD_FACTOR
            )
        except xen.lowlevel.xc.Error:
            pass

    def get_xs_path(self, domid, key) -> str:
        return "/local/domain/" + str(domid) + "/memory/" + key

    def add_domain(self, domid) -> None:
        self.log.debug("add_domain(domid={!r})".format(domid))
        self.dom_dict[domid] = DomainState(domid)
        # TODO: move to DomainState.__init__
        target_str = self.xs.read("", self.get_xs_path(domid, "target"))
        if target_str:
            self.dom_dict[domid].last_target = int(target_str) * 1024

    def del_domain(self, domid) -> None:
        self.log.debug("del_domain(domid={!r})".format(domid))
        self.dom_dict.pop(domid)

    def get_free_xen_mem(self) -> int:
        xen_free = int(
            self.xc.physinfo()["free_memory"] * 1024 * MEM_OVERHEAD_FACTOR
        )
        # Check for domains which have assigned more memory than really used -
        # do not count it as "free", because domain is free to use it at any
        # time. Assumption: self.refresh_mem_actual was called before (so
        # dom.mem_actual is up-to-date)
        assigned_but_unused = functools.reduce(
            lambda acc, dom: acc + max(0, dom.last_target - dom.mem_current),
            self.dom_dict.values(),
            0,
        )
        # If, at any time, Xen have less memory than XEN_FREE_MEM_MIN, it is a
        # failure of qmemman. Collect as much data as possible to debug it
        if xen_free < XEN_FREE_MEM_MIN:
            self.log.error(
                "Xen free = {!r} below acceptable value! "
                "assigned_but_unused={!r}, dom_dict={!r}".format(
                    xen_free, assigned_but_unused, self.dom_dict
                )
            )
        elif xen_free < assigned_but_unused + XEN_FREE_MEM_MIN:
            self.log.error(
                "Xen free = {!r} too small to satisfy assignments! "
                "assigned_but_unused={!r}, dom_dict={!r}".format(
                    xen_free, assigned_but_unused, self.dom_dict
                )
            )
        return xen_free - assigned_but_unused

    # Refresh information on memory assigned to all domains
    def refresh_mem_actual(self) -> None:
        for domain in self.xc.domain_getinfo():
            domid = str(domain["domid"])
            if domid in self.dom_dict:
                dom = self.dom_dict[domid]
                # Real memory usage
                dom.mem_current = domain["mem_kb"] * 1024
                # What VM is using or can use
                dom.mem_actual = max(
                    dom.mem_current,
                    dom.last_target,
                )
                hotplug_max = self.xs.read(
                    "", self.get_xs_path(domid, "hotplug-max")
                )
                static_max = self.xs.read(
                    "", self.get_xs_path(domid, "static-max")
                )
                if hotplug_max:
                    dom.mem_max = int(hotplug_max) * 1024
                    dom.use_hotplug = True
                elif static_max:
                    dom.mem_max = int(static_max) * 1024
                    dom.use_hotplug = False
                else:
                    dom.mem_max = self.all_phys_mem
                    # the previous line used to be
                    #   dom.mem_max = domain['maxmem_kb']*1024
                    # but domain['maxmem_kb'] changes in self.mem_set as well,
                    # and this results in the memory never increasing in fact,
                    # the only possible case of nonexisting memory/static-max
                    # is dom0, see #307

    def clear_outdated_error_markers(self) -> None:
        # Clear outdated errors.
        for dom in self.dom_dict.values():
            if dom.mem_used is None:
                continue
            # Clear markers excluding VM from memory balance, if:
            #  - VM have responded to previous request (with some safety margin)
            #  - VM request more memory than it has assigned
            # The second condition avoids starving a VM, even when there is
            # some free memory available.
            assert isinstance(dom.mem_actual, int)
            if (
                dom.mem_actual <= dom.last_target + XEN_FREE_MEM_LEFT / 2
                or dom.mem_actual < qubes.qmemman.algo.pref_mem(dom)
            ):
                dom.slow_memset_react = False
                dom.no_progress = False

    # The below works (and is fast), but then 'xm list' shows unchanged memory
    # value.
    def mem_set(self, domid, val) -> None:
        self.log.info("mem-set domain {} to {}".format(domid, val))
        dom = self.dom_dict[domid]
        dom.last_target = val
        # Can happen in the middle of domain shutdown apparently xc.lowlevel
        # throws exceptions too.
        try:
            self.xc.domain_setmaxmem(
                int(domid), int(val / 1024) + 1024
            )  # LIBXL_MAXMEM_CONSTANT=1024
            self.xc.domain_set_target_mem(int(domid), int(val / 1024))
        except Exception:
            pass
        # VM sees about 16MB memory less, so adjust for it here - qmemman
        #  handle Xen view of memory
        # handle Xen view of memory.
        self.xs.write(
            "",
            self.get_xs_path(domid, "target"),
            str(int(val / 1024 - 16 * 1024)),
        )
        if dom.use_hotplug:
            self.xs.write(
                "",
                self.get_xs_path(domid, "static-max"),
                str(int(val / 1024)),
            )

    # This is called at the end of ballooning, when we have Xen free mem
    # already, make sure that past mem_set will not decrease Xen free mem.
    def inhibit_balloon_up(self) -> None:
        self.log.debug("inhibit_balloon_up()")
        for domid, dom in self.dom_dict.items():
            if (
                dom.mem_actual is not None
                and dom.mem_actual + 200 * 1024 < dom.last_target
            ):
                self.log.info(
                    "Preventing balloon up to {}".format(dom.last_target)
                )
                self.mem_set(domid, dom.mem_actual)

    # Perform memory ballooning, across all domains, to add "mem_size" to Xen
    # free memory
    def do_balloon(self, mem_size) -> bool:
        self.log.info("do_balloon(mem_size={!r})".format(mem_size))
        niter = 0
        prev_mem_actual: dict[str, Optional[int]] = {}

        for dom in self.dom_dict.values():
            dom.no_progress = False

        #: number of loop iterations for CHECK_PERIOD_S seconds
        check_period = max(1, int((CHECK_PERIOD_S + 0.0) / BALLOON_DELAY))
        #: number of free memory bytes expected to get during CHECK_PERIOD_S
        #: seconds
        check_delta = CHECK_PERIOD_S * CHECK_MB_S * 1024 * 1024
        #: helper array for holding free memory size, CHECK_PERIOD_S seconds
        #: ago, at every loop iteration
        xenfree_ring = [0] * check_period

        while True:
            self.log.debug("niter={:2d}".format(niter))
            self.refresh_mem_actual()
            xenfree = self.get_free_xen_mem()
            self.log.info("xenfree={!r}".format(xenfree))
            if xenfree >= mem_size + XEN_FREE_MEM_MIN:
                self.inhibit_balloon_up()
                return True
            # fail the request if over past CHECK_PERIOD_S seconds,
            # we got less than CHECK_MB_S MB/s on average
            ring_slot = niter % check_period
            if (
                niter >= check_period
                and xenfree < xenfree_ring[ring_slot] + check_delta
            ):
                return False
            xenfree_ring[ring_slot] = xenfree
            for domid, prev_mem in prev_mem_actual.items():
                dom = self.dom_dict[domid]
                if prev_mem == dom.mem_actual:
                    # domain not responding to memset requests, remove it
                    #  from donors
                    dom.no_progress = True
                    self.log.info(
                        "domain {} stuck at {}".format(domid, dom.mem_actual)
                    )
            memset_reqs = qubes.qmemman.algo.balloon(
                mem_size + XEN_FREE_MEM_LEFT - xenfree, self.dom_dict
            )
            self.log.info("memset_reqs={!r}".format(memset_reqs))
            if len(memset_reqs) == 0:
                return False
            prev_mem_actual = {}
            for domid, memset in memset_reqs:
                self.mem_set(domid, memset)
                prev_mem_actual[domid] = self.dom_dict[domid].mem_actual
            self.log.debug("sleeping for {} s".format(BALLOON_DELAY))
            time.sleep(BALLOON_DELAY)
            niter = niter + 1

    def refresh_meminfo(self, domid, untrusted_meminfo_key) -> None:
        self.log.debug(
            "refresh_meminfo(domid={}, untrusted_meminfo_key={!r})".format(
                domid, untrusted_meminfo_key
            )
        )

        qubes.qmemman.algo.refresh_meminfo_for_domain(
            self.dom_dict[domid], untrusted_meminfo_key
        )
        self.do_balance()

    # Is the computed balance request big enough so that we do not trash with
    # small adjustments.
    def is_balance_req_significant(self, memset_reqs, xenfree) -> bool:
        self.log.debug(
            "is_balance_req_significant(memset_reqs={}, xenfree={})".format(
                memset_reqs, xenfree
            )
        )

        total_mem_transfer = 0

        # If xenfree to low, return immediately.
        if XEN_FREE_MEM_LEFT - xenfree > MIN_MEM_CHANGE_WHEN_UNDER_PREF:
            self.log.debug("xenfree is too low, returning")
            return True

        for domid, memset in memset_reqs:
            last_target = self.dom_dict[domid].last_target
            mem_change = memset - last_target
            total_mem_transfer += abs(mem_change)
            pref = qubes.qmemman.algo.pref_mem(self.dom_dict[domid])

            if (
                0 < last_target < pref
                and mem_change > MIN_MEM_CHANGE_WHEN_UNDER_PREF
            ):
                self.log.info(
                    "dom {} is below pref, allowing balance".format(domid)
                )
                return True

        ret = (
            total_mem_transfer + abs(xenfree - XEN_FREE_MEM_LEFT)
            > MIN_TOTAL_MEMORY_TRANSFER
        )
        self.log.debug("is_balance_req_significant return {}".format(ret))
        return ret

    def print_stats(self, xenfree, memset_reqs) -> None:
        for domid, dom in self.dom_dict.items():
            if dom.mem_used is not None:
                self.log.info(
                    "stat: dom {!r} act={} pref={} last_target={}"
                    "{}{}".format(
                        domid,
                        dom.mem_actual,
                        qubes.qmemman.algo.pref_mem(dom),
                        dom.last_target,
                        " no_progress" if dom.no_progress else "",
                        (" slow_memset_react" if dom.slow_memset_react else ""),
                    )
                )

        self.log.info(
            "stat: xenfree={} memset_reqs={}".format(xenfree, memset_reqs)
        )

    def debug_stuck_balance(
        self, stuck_domid, memset_reqs, prev_mem_actual
    ) -> None:
        for req in memset_reqs:
            domid, mem = req
            if domid == stuck_domid:
                # All donors have been processed.
                break
            dom = self.dom_dict[domid]
            # Allow some small margin.
            assert isinstance(dom.mem_actual, int)
            if dom.mem_actual > dom.last_target + XEN_FREE_MEM_LEFT / 4:
                # VM didn't react to memory request at all, remove from donors.
                if prev_mem_actual[domid] == dom.mem_actual:
                    self.log.warning(
                        "dom {!r} did not react to memory request (holds {}, "
                        "requested balloon down to {})".format(
                            domid,
                            dom.mem_actual,
                            mem,
                        )
                    )
                    dom.no_progress = True
                else:
                    self.log.warning(
                        "dom {!r} still holds more memory than assigned ({} > "
                        "{})".format(
                            domid,
                            dom.mem_actual,
                            mem,
                        )
                    )
                    dom.slow_memset_react = True

    def do_balance(self) -> None:
        self.log.debug("do_balance()")
        if os.path.isfile("/var/run/qubes/do-not-membalance"):
            self.log.debug("do-not-membalance file present, returning")
            return

        self.refresh_mem_actual()
        self.clear_outdated_error_markers()
        xenfree = self.get_free_xen_mem()
        memset_reqs = qubes.qmemman.algo.balance(
            xenfree - XEN_FREE_MEM_LEFT, self.dom_dict
        )
        if not self.is_balance_req_significant(memset_reqs, xenfree):
            return

        self.print_stats(xenfree, memset_reqs)

        prev_mem_actual: dict[str, Optional[int]] = {}
        for domid, dom in self.dom_dict.items():
            prev_mem_actual[domid] = dom.mem_actual
        for req in memset_reqs:
            domid, mem = req
            dom = self.dom_dict[domid]
            # Force to always have at least 0.9*XEN_FREE_MEM_LEFT (some margin
            # for rounding errors). Before giving memory to domain, ensure that
            # others have gave it back. If not, wait a little.
            ntries = 5
            while (
                self.get_free_xen_mem() - (mem - dom.mem_actual)
                < 0.9 * XEN_FREE_MEM_LEFT
            ):
                self.log.debug(
                    "do_balance dom={!r} sleeping ntries={}".format(
                        domid, ntries
                    )
                )
                time.sleep(BALLOON_DELAY)
                self.refresh_mem_actual()
                ntries -= 1
                if ntries <= 0:
                    # Waiting hasn't helped. Find which domain got stuck and
                    # abort balance (after distributing what we have).
                    self.debug_stuck_balance(
                        domid, memset_reqs, prev_mem_actual
                    )
                    assert isinstance(dom.mem_actual, int)
                    self.mem_set(
                        domid,
                        self.get_free_xen_mem()
                        + dom.mem_actual
                        - XEN_FREE_MEM_LEFT,
                    )
                    return

            self.mem_set(domid, mem)

        xenfree = self.get_free_xen_mem()
        mem_dict = qubes.qmemman.algo.mem_info(
            xenfree - XEN_FREE_MEM_LEFT, self.dom_dict
        )
        avail_mem_file = qubes.config.qmemman_avail_mem_file
        avail_mem_file_tmp = Path(avail_mem_file).with_suffix(".tmp")
        with open(avail_mem_file_tmp, "w", encoding="ascii") as file:
            file.write(str(mem_dict["total_available_mem"]))
        os.chmod(avail_mem_file_tmp, 0o644)
        os.replace(avail_mem_file_tmp, avail_mem_file)
