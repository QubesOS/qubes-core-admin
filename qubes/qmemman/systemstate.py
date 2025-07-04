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

import qubes.qmemman
from qubes.qmemman.domainstate import DomainState

BALOON_DELAY = 0.1
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

no_progress_msg = "VM refused to give back requested memory"
slow_memset_react_msg = "VM didn't give back all requested memory"


class SystemState:
    def __init__(self):
        self.log = logging.getLogger("qmemman.systemstate")
        self.log.debug("SystemState()")

        self.domdict = {}
        self.xc = None
        self.xs = None
        self.all_phys_mem = 0

    def init(self):
        self.xc = xen.lowlevel.xc.xc()
        self.xs = xen.lowlevel.xs.xs()
        # we divide total and free physical memory by this to get
        # "assignable" memory
        try:
            self.all_phys_mem = int(
                self.xc.physinfo()["total_memory"] * 1024 * MEM_OVERHEAD_FACTOR
            )
        except xen.lowlevel.xc.Error:
            pass

    def add_domain(self, domid):
        self.log.debug("add_domain(domid={!r})".format(domid))
        self.domdict[domid] = DomainState(domid)
        # TODO: move to DomainState.__init__
        target_str = self.xs.read(
            "", "/local/domain/" + domid + "/memory/target"
        )
        if target_str:
            self.domdict[domid].last_target = int(target_str) * 1024

    def del_domain(self, domid):
        self.log.debug("del_domain(domid={!r})".format(domid))
        self.domdict.pop(domid)

    def get_free_xen_memory(self):
        xen_free = int(
            self.xc.physinfo()["free_memory"] * 1024 * MEM_OVERHEAD_FACTOR
        )
        # now check for domains which have assigned more memory than really
        # used - do not count it as "free", because domain is free to use it
        # at any time
        # assumption: self.refresh_memactual was called before
        # (so dom.memory_actual is up-to-date)
        assigned_but_unused = functools.reduce(
            lambda acc, dom: acc + max(0, dom.last_target - dom.memory_current),
            self.domdict.values(),
            0,
        )
        # If, at any time, Xen have less memory than XEN_FREE_MEM_MIN,
        # it is a failure of qmemman. Collect as much data as possible to
        # debug it
        if xen_free < XEN_FREE_MEM_MIN:
            self.log.error(
                "Xen free = {!r} below acceptable value! "
                "assigned_but_unused={!r}, domdict={!r}".format(
                    xen_free, assigned_but_unused, self.domdict
                )
            )
        elif xen_free < assigned_but_unused + XEN_FREE_MEM_MIN:
            self.log.error(
                "Xen free = {!r} too small to satisfy assignments! "
                "assigned_but_unused={!r}, domdict={!r}".format(
                    xen_free, assigned_but_unused, self.domdict
                )
            )
        return xen_free - assigned_but_unused

    # refresh information on memory assigned to all domains
    def refresh_memactual(self):
        for domain in self.xc.domain_getinfo():
            domid = str(domain["domid"])
            if domid in self.domdict:
                dom = self.domdict[domid]
                # real memory usage
                dom.memory_current = domain["mem_kb"] * 1024
                # what VM is using or can use
                dom.memory_actual = max(
                    dom.memory_current,
                    dom.last_target,
                )
                hotplug_max = self.xs.read(
                    "", "/local/domain/%s/memory/hotplug-max" % str(domid)
                )
                static_max = self.xs.read(
                    "", "/local/domain/%s/memory/static-max" % str(domid)
                )
                if hotplug_max:
                    dom.memory_maximum = int(hotplug_max) * 1024
                    dom.use_hotplug = True
                elif static_max:
                    dom.memory_maximum = int(static_max) * 1024
                    dom.use_hotplug = False
                else:
                    dom.memory_maximum = self.all_phys_mem
                    # the previous line used to be
                    #   dom.memory_maximum = domain['maxmem_kb']*1024
                    # but domain['maxmem_kb'] changes in self.mem_set as well,
                    # and this results in the memory never increasing
                    # in fact, the only possible case of nonexisting
                    # memory/static-max is dom0
                    # see #307

    def clear_outdated_error_markers(self):
        # Clear outdated errors
        for dom in self.domdict.values():
            if dom.mem_used is None:
                continue
            # clear markers excluding VM from memory balance, if:
            #  - VM have responded to previous request (with some safety margin)
            #  - VM request more memory than it has assigned
            # The second condition avoids starving a VM, even when there is
            # some free memory available
            if (
                dom.memory_actual <= dom.last_target + XEN_FREE_MEM_LEFT / 2
                or dom.memory_actual < qubes.qmemman.algo.prefmem(dom)
            ):
                dom.slow_memset_react = False
                dom.no_progress = False

    # the below works (and is fast), but then 'xm list' shows unchanged
    # memory value
    def mem_set(self, domid, val):
        self.log.info("mem-set domain {} to {}".format(domid, val))
        dom = self.domdict[domid]
        dom.last_target = val
        # can happen in the middle of domain shutdown
        # apparently xc.lowlevel throws exceptions too
        try:
            self.xc.domain_setmaxmem(
                int(domid), int(val / 1024) + 1024
            )  # LIBXL_MAXMEM_CONSTANT=1024
            self.xc.domain_set_target_mem(int(domid), int(val / 1024))
        except Exception:
            pass
        # VM sees about 16MB memory less, so adjust for it here - qmemman
        #  handle Xen view of memory
        self.xs.write(
            "",
            "/local/domain/" + domid + "/memory/target",
            str(int(val / 1024 - 16 * 1024)),
        )
        if dom.use_hotplug:
            self.xs.write(
                "",
                "/local/domain/" + domid + "/memory/static-max",
                str(int(val / 1024)),
            )

    # this is called at the end of ballooning, when we have Xen free mem already
    # make sure that past mem_set will not decrease Xen free mem
    def inhibit_balloon_up(self):
        self.log.debug("inhibit_balloon_up()")
        for domid, dom in self.domdict.items():
            if (
                dom.memory_actual is not None
                and dom.memory_actual + 200 * 1024 < dom.last_target
            ):
                self.log.info(
                    "Preventing balloon up to {}".format(dom.last_target)
                )
                self.mem_set(domid, dom.memory_actual)

    # perform memory ballooning, across all domains, to add "memsize" to Xen
    #  free memory
    def do_balloon(self, memsize):
        self.log.info("do_balloon(memsize={!r})".format(memsize))
        niter = 0
        prev_memory_actual = None

        for dom in self.domdict.values():
            dom.no_progress = False

        #: number of loop iterations for CHECK_PERIOD_S seconds
        check_period = max(1, int((CHECK_PERIOD_S + 0.0) / BALOON_DELAY))
        #: number of free memory bytes expected to get during CHECK_PERIOD_S
        #: seconds
        check_delta = CHECK_PERIOD_S * CHECK_MB_S * 1024 * 1024
        #: helper array for holding free memory size, CHECK_PERIOD_S seconds
        #: ago, at every loop iteration
        xenfree_ring = [0] * check_period

        while True:
            self.log.debug("niter={:2d}".format(niter))
            self.refresh_memactual()
            xenfree = self.get_free_xen_memory()
            self.log.info("xenfree={!r}".format(xenfree))
            if xenfree >= memsize + XEN_FREE_MEM_MIN:
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
            if prev_memory_actual is not None:
                for domid, prev_mem in prev_memory_actual.items():
                    dom = self.domdict[domid]
                    if prev_mem == dom.memory_actual:
                        # domain not responding to memset requests, remove it
                        #  from donors
                        dom.no_progress = True
                        self.log.info(
                            "domain {} stuck at {}".format(
                                domid, dom.memory_actual
                            )
                        )
            memset_reqs = qubes.qmemman.algo.balloon(
                memsize + XEN_FREE_MEM_LEFT - xenfree, self.domdict
            )
            self.log.info("memset_reqs={!r}".format(memset_reqs))
            if len(memset_reqs) == 0:
                return False
            prev_memory_actual = {}
            for req in memset_reqs:
                dom, mem = req
                self.mem_set(dom, mem)
                prev_memory_actual[dom] = self.domdict[dom].memory_actual
            self.log.debug("sleeping for {} s".format(BALOON_DELAY))
            time.sleep(BALOON_DELAY)
            niter = niter + 1

    def refresh_meminfo(self, domid, untrusted_meminfo_key):
        self.log.debug(
            "refresh_meminfo(domid={}, untrusted_meminfo_key={!r})".format(
                domid, untrusted_meminfo_key
            )
        )

        qubes.qmemman.algo.refresh_meminfo_for_domain(
            self.domdict[domid], untrusted_meminfo_key
        )
        self.do_balance()

    # is the computed balance request big enough ?
    # so that we do not trash with small adjustments
    def is_balance_req_significant(self, memset_reqs, xenfree):
        self.log.debug(
            "is_balance_req_significant(memset_reqs={}, xenfree={})".format(
                memset_reqs, xenfree
            )
        )

        total_memory_transfer = 0

        # If xenfree to low, return immediately
        if XEN_FREE_MEM_LEFT - xenfree > MIN_MEM_CHANGE_WHEN_UNDER_PREF:
            self.log.debug("xenfree is too low, returning")
            return True

        for req in memset_reqs:
            dom, mem = req
            last_target = self.domdict[dom].last_target
            memory_change = mem - last_target
            total_memory_transfer += abs(memory_change)
            pref = qubes.qmemman.algo.prefmem(self.domdict[dom])

            if (
                0 < last_target < pref
                and memory_change > MIN_MEM_CHANGE_WHEN_UNDER_PREF
            ):
                self.log.info(
                    "dom {} is below pref, allowing balance".format(dom)
                )
                return True

        ret = (
            total_memory_transfer + abs(xenfree - XEN_FREE_MEM_LEFT)
            > MIN_TOTAL_MEMORY_TRANSFER
        )
        self.log.debug("is_balance_req_significant return {}".format(ret))
        return ret

    def print_stats(self, xenfree, memset_reqs):
        for domid, dom in self.domdict.items():
            if dom.mem_used is not None:
                self.log.info(
                    "stat: dom {!r} act={} pref={} last_target={}"
                    "{}{}".format(
                        domid,
                        dom.memory_actual,
                        qubes.qmemman.algo.prefmem(dom),
                        dom.last_target,
                        " no_progress" if dom.no_progress else "",
                        (" slow_memset_react" if dom.slow_memset_react else ""),
                    )
                )

        self.log.info(
            "stat: xenfree={} memset_reqs={}".format(xenfree, memset_reqs)
        )

    def debug_stuck_balance(self, domid, memset_reqs, prev_memactual):
        for rq2 in memset_reqs:
            domid2, mem2 = rq2
            if domid2 == domid:
                # All donors have been processed
                break
            dom2 = self.domdict[domid2]
            # allow some small margin
            if dom2.memory_actual > dom2.last_target + XEN_FREE_MEM_LEFT / 4:
                # VM didn't react to memory request at all,
                # remove from donors
                if prev_memactual[domid2] == dom2.memory_actual:
                    self.log.warning(
                        "dom {!r} did not react to memory request"
                        " (holds {}, requested balloon down to {})".format(
                            domid2,
                            dom2.memory_actual,
                            mem2,
                        )
                    )
                    dom2.no_progress = True
                else:
                    self.log.warning(
                        "dom {!r} still holds more"
                        " memory than assigned ({} > {})".format(
                            domid2,
                            dom2.memory_actual,
                            mem2,
                        )
                    )
                    dom2.slow_memset_react = True

    def do_balance(self):
        self.log.debug("do_balance()")
        if os.path.isfile("/var/run/qubes/do-not-membalance"):
            self.log.debug("do-not-membalance file present, returning")
            return

        self.refresh_memactual()
        self.clear_outdated_error_markers()
        xenfree = self.get_free_xen_memory()
        memset_reqs = qubes.qmemman.algo.balance(
            xenfree - XEN_FREE_MEM_LEFT, self.domdict
        )
        if not self.is_balance_req_significant(memset_reqs, xenfree):
            return

        self.print_stats(xenfree, memset_reqs)

        prev_memactual = {}
        for domid, dom in self.domdict.items():
            prev_memactual[domid] = dom.memory_actual
        for req in memset_reqs:
            domid, mem = req
            dom = self.domdict[domid]
            # Force to always have at least 0.9*XEN_FREE_MEM_LEFT (some
            # margin for rounding errors). Before giving memory to
            # domain, ensure that others have gave it back.
            # If not - wait a little.
            ntries = 5
            while (
                self.get_free_xen_memory() - (mem - dom.memory_actual)
                < 0.9 * XEN_FREE_MEM_LEFT
            ):
                self.log.debug(
                    "do_balance dom={!r} sleeping ntries={}".format(
                        domid, ntries
                    )
                )
                time.sleep(BALOON_DELAY)
                self.refresh_memactual()
                ntries -= 1
                if ntries <= 0:
                    # Waiting haven't helped; Find which domain get stuck and
                    # abort balance (after distributing what we have)
                    self.debug_stuck_balance(domid, memset_reqs, prev_memactual)
                    self.mem_set(
                        domid,
                        self.get_free_xen_memory()
                        + dom.memory_actual
                        - XEN_FREE_MEM_LEFT,
                    )
                    return

            self.mem_set(domid, mem)

        xenfree = self.get_free_xen_memory()
        memory_dictionary = qubes.qmemman.algo.memory_info(
            xenfree - XEN_FREE_MEM_LEFT, self.domdict
        )
        avail_mem_file = qubes.config.qmemman_avail_mem_file
        avail_mem_file_tmp = Path(avail_mem_file).with_suffix(".tmp")
        with open(avail_mem_file_tmp, "w", encoding="ascii") as file:
            file.write(str(memory_dictionary["total_available_memory"]))
        os.chmod(avail_mem_file_tmp, 0o644)
        os.replace(avail_mem_file_tmp, avail_mem_file)

        # pylint: disable=line-too-long
        # for i in self.domdict.keys():
        #     print 'domain ', i, ' meminfo=', dom.mem_used, 'actual mem', dom.memory_actual
        #     print 'domain ', i, 'actual mem', dom.memory_actual
        # print 'xen free mem', self.get_free_xen_memory()
