#
# The Qubes OS Project, http://www.qubes-os.org
#
# Copyright (C) 2010  Rafal Wojtczuk  <rafal@invisiblethingslab.com>
# Copyright (C) 2013  Marek Marczykowski <marmarek@invisiblethingslab.com>
#
# This library is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 2.1 of the License, or (at your option) any later version.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with this library; if not, see <https://www.gnu.org/licenses/>.
#

import logging
from typing import Optional

# These defaults can be overridden by QMemmanServer with values from config
# file.
CACHE_FACTOR = 1.3
MIN_PREFMEM = 200 * 1024 * 1024
DOM0_MEM_BOOST = 350 * 1024 * 1024
# REQ_SAFETY_NET_FACTOR is a bit greater that 1. So that if the domain
# yields a bit less than requested, due to e.g. rounding errors, we will not
# get stuck. The surplus will return to the VM during "balance" call.
REQ_SAFETY_NET_FACTOR = 1.05

log = logging.getLogger("qmemman.daemon.algo")


def sanitize_and_parse_meminfo(untrusted_meminfo) -> Optional[int]:
    # Untrusted meminfo size is read from xenstore, thus its size is limited
    # and splits do not require excessive memory.
    if not untrusted_meminfo:
        return None
    if not untrusted_meminfo.isdigit():
        return None
    return int(untrusted_meminfo) * 1024


def refresh_meminfo_for_domain(dom, untrusted_xenstore_key) -> None:
    """
    Called when a domain updates its 'meminfo' xenstore key.
    """
    dom.mem_used = sanitize_and_parse_meminfo(untrusted_xenstore_key)


def pref_mem(dom) -> int:
    # As dom0 must have large cache for vbds, give it a special boost.
    mem_used = dom.mem_used * CACHE_FACTOR
    if dom.domid == "0":
        mem_used += DOM0_MEM_BOOST
        return int(min(mem_used, dom.mem_max))
    return int(max(min(mem_used, dom.mem_max), MIN_PREFMEM))


def needed_mem(dom) -> int:
    # Do not change. In balance(), "distribute total_available_mem
    # proportionally to pref_mem" relies on this exact formula.
    ret = pref_mem(dom) - dom.mem_actual
    return ret


# Prepare list of (dom, mem_target) pairs that need to be passed to "xm
# memset" equivalent in order to obtain "mem_size".
# Returns empty list when the request cannot be satisfied.
def balloon(mem_size, dom_dict) -> list:
    log.debug(
        "balloon(mem_size={!r}, dom_dict={!r})".format(mem_size, dom_dict)
    )
    donors = []
    request = []
    available = 0
    for domid, dom in dom_dict.items():
        if dom.mem_used is None or dom.no_progress:
            continue
        need = needed_mem(dom)
        if need < 0:
            log.info(
                "balloon: dom {} has actual memory {}".format(
                    domid, dom.mem_actual
                )
            )
            donors.append((domid, -need))
            available -= need

    log.info("req={} avail={} donors={!r}".format(mem_size, available, donors))

    if available < mem_size:
        return []
    scale = 1.0 * mem_size / available
    for donors_iter in donors:
        domid, mem = donors_iter
        mem_borrowed = mem * scale * REQ_SAFETY_NET_FACTOR
        log.info("borrow {} from {}".format(mem_borrowed, domid))
        mem_target = int(dom_dict[domid].mem_actual - mem_borrowed)
        request.append((domid, mem_target))
    return request


# Redistribute positive "total_available_mem" of memory between domains,
# proportionally to pref_mem.
def balance_when_enough_mem(
    dom_dict, xen_free_mem, total_mem_pref, total_available_mem
):
    log.info(
        "balance_when_enough_mem(xen_free_mem={!r}, "
        "total_mem_pref={!r}, total_available_mem={!r})".format(
            xen_free_mem, total_mem_pref, total_available_mem
        )
    )

    target_mem = {}
    # Memory not assigned because of static max.
    mem_left = 0
    acceptors_count = 0
    for domid, dom in dom_dict.items():
        if dom.mem_used is None or dom.no_progress:
            continue
        # Distribute total_available_mem proportionally to pref_mem.
        scale = 1.0 * pref_mem(dom) / total_mem_pref
        target_nonint = pref_mem(dom) + scale * total_available_mem
        # Prevent rounding errors.
        target = int(0.999 * target_nonint)
        # Do not try to give more memory than static max.
        if target > dom.mem_max:
            mem_left += target - dom.mem_max
            target = dom.mem_max
        else:
            # Count domains which can accept more memory.
            acceptors_count += 1
        target_mem[domid] = target
    # Distribute left memory across all acceptors.
    while mem_left > 0 and acceptors_count > 0:
        log.info(
            "mem_left={} acceptors_count={}".format(mem_left, acceptors_count)
        )

        new_mem_left = 0
        new_acceptors_count = acceptors_count
        for domid, target in target_mem.items():
            dom = dom_dict[domid]
            if target < dom.mem_max:
                mem_bonus = int(0.999 * (mem_left / acceptors_count))
                if target + mem_bonus >= dom.mem_max:
                    new_mem_left += target + mem_bonus - dom.mem_max
                    target = dom.mem_max
                    new_acceptors_count -= 1
                else:
                    target += mem_bonus
            target_mem[domid] = target
        mem_left = new_mem_left
        acceptors_count = new_acceptors_count
    # Split target_mem dictionary to donors and acceptors. This is needed to
    # first get memory from donors and only then give it to acceptors.
    donors_rq = []
    acceptors_rq = []
    for domid, target in target_mem.items():
        dom = dom_dict[domid]
        if target < dom.mem_actual:
            donors_rq.append((domid, target))
        else:
            acceptors_rq.append((domid, target))
    return donors_rq + acceptors_rq


# When not enough mem to make everyone be above pref_mem, make donors be at
# pref_mem, and redistribute anything left between acceptors.
def balance_when_low_on_mem(
    dom_dict,
    xen_free_mem,
    total_mem_pref_acceptors,
    donors,
    acceptors,
):
    log.info(
        "balance_when_low_on_mem(xen_free_mem={!r}, "
        "total_mem_pref_acceptors={!r}, donors={!r}, acceptors={!r})".format(
            xen_free_mem, total_mem_pref_acceptors, donors, acceptors
        )
    )
    donors_rq = []
    acceptors_rq = []
    squeezed_mem = xen_free_mem
    for domid in donors:
        dom = dom_dict[domid]
        avail = -needed_mem(dom)
        if avail < 10 * 1024 * 1024:
            # Probably we have already tried making it exactly at pref_mem, give
            # up.
            continue
        squeezed_mem -= avail
        donors_rq.append((domid, pref_mem(dom)))
    # The below condition can happen if initially xen free memory is below 50M.
    if squeezed_mem < 0:
        return donors_rq
    for domid in acceptors:
        dom = dom_dict[domid]
        scale = 1.0 * pref_mem(dom) / total_mem_pref_acceptors
        target_nonint = dom.mem_actual + scale * squeezed_mem
        # Do not try to give more memory than static max.
        target = min(int(0.999 * target_nonint), dom.mem_max)
        acceptors_rq.append((domid, target))
    return donors_rq + acceptors_rq


# Get memory information.
# Called before and after domain balances.
# Return a dictionary of various memory data points.
def mem_info(xen_free_mem, dom_dict) -> dict:
    log.debug(
        "mem_info(xen_free_mem={!r}, dom_dict={!r})".format(
            xen_free_mem, dom_dict
        )
    )

    # Sum of all memory requirements - in other words, the difference between
    # memory required to be added to domains (acceptors) to make them be at
    # their preferred memory, and memory that can be taken from domains
    # (donors) that can provide memory. So, it can be negative when plenty of
    # memory.
    total_needed_mem = 0

    # Sum of memory preferences of all domains.
    total_mem_pref = 0

    # Sum of memory preferences of all domains that require more memory.
    total_mem_pref_acceptors = 0

    donors = []
    acceptors = []
    # Pass 1: compute the above "total" values.
    for domid, dom in dom_dict.items():
        if dom.mem_used is None or dom.no_progress:
            continue
        need = needed_mem(dom)
        if need < 0 or dom.mem_actual >= dom.mem_max:
            donors.append(domid)
        else:
            acceptors.append(domid)
            total_mem_pref_acceptors += pref_mem(dom)
        total_needed_mem += need
        total_mem_pref += pref_mem(dom)

    total_available_mem = xen_free_mem - total_needed_mem

    mem_dict = {}
    mem_dict["dom_dict"] = dom_dict
    mem_dict["total_available_mem"] = total_available_mem
    mem_dict["xen_free_mem"] = xen_free_mem
    mem_dict["total_mem_pref"] = total_mem_pref
    mem_dict["total_mem_pref_acceptors"] = total_mem_pref_acceptors
    mem_dict["donors"] = donors
    mem_dict["acceptors"] = acceptors
    return mem_dict


# Redistribute memory across domains.
# Called when one of domains update its 'meminfo' xenstore key.
# Return the list of (domain, mem_target) pairs to be passed to "xm memset"
# equivalent
def balance(xen_free_mem, dom_dict) -> dict:
    log.debug(
        "balance(xen_free_mem={!r}, dom_dict={!r})".format(
            xen_free_mem, dom_dict
        )
    )
    mem_dict = mem_info(xen_free_mem, dom_dict)

    if mem_dict["total_available_mem"] > 0:
        return balance_when_enough_mem(
            mem_dict["dom_dict"],
            mem_dict["xen_free_mem"],
            mem_dict["total_mem_pref"],
            mem_dict["total_available_mem"],
        )
    return balance_when_low_on_mem(
        mem_dict["dom_dict"],
        mem_dict["xen_free_mem"],
        mem_dict["total_mem_pref_acceptors"],
        mem_dict["donors"],
        mem_dict["acceptors"],
    )
