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

# This are only defaults - can be overridden by QMemmanServer with values from
# config file
CACHE_FACTOR = 1.3
MIN_PREFMEM = 200 * 1024 * 1024
DOM0_MEM_BOOST = 350 * 1024 * 1024
REQ_SAFETY_NET_FACTOR = 1.05

log = logging.getLogger("qmemman.daemon.algo")


def sanitize_and_parse_meminfo(untrusted_meminfo):
    # Untrusted meminfo size is read from xenstore, thus its size is limited
    # and splits do not require excessive memory.
    if not untrusted_meminfo:
        return None
    if not untrusted_meminfo.isdigit():
        return None
    return int(untrusted_meminfo) * 1024


# Called when a domain updates its 'meminfo' xenstore key.
def refresh_meminfo_for_domain(domain, untrusted_xenstore_key):
    domain.mem_used = sanitize_and_parse_meminfo(untrusted_xenstore_key)


def prefmem(domain):
    # As dom0 must have large cache for vbds, give it a special boost.
    mem_used = domain.mem_used * CACHE_FACTOR
    if domain.domid == "0":
        mem_used += DOM0_MEM_BOOST
        return int(min(mem_used, domain.memory_maximum))
    return int(max(min(mem_used, domain.memory_maximum), MIN_PREFMEM))


def memory_needed(domain):
    # Do not change. In balance(), "distribute total_available_memory
    # proportionally to mempref" relies on this exact formula.
    ret = prefmem(domain) - domain.memory_actual
    return ret


# Prepare list of (domain, memory_target) pairs that need to be passed to "xm
# memset" equivalent in order to obtain "memsize".
# Returns empty list when the request cannot be satisfied.
def balloon(memsize, domain_dictionary):
    log.debug(
        "balloon(memsize={!r}, domain_dictionary={!r})".format(
            memsize, domain_dictionary
        )
    )
    donors = []
    request = []
    available = 0
    for domid, dom in domain_dictionary.items():
        if dom.mem_used is None or dom.no_progress:
            continue
        need = memory_needed(dom)
        if need < 0:
            log.info(
                "balloon: dom {} has actual memory {}".format(
                    domid, dom.memory_actual
                )
            )
            donors.append((domid, -need))
            available -= need

    log.info("req={} avail={} donors={!r}".format(memsize, available, donors))

    if available < memsize:
        return []
    scale = 1.0 * memsize / available
    for donors_iter in donors:
        dom_id, mem = donors_iter
        memborrowed = mem * scale * REQ_SAFETY_NET_FACTOR
        log.info("borrow {} from {}".format(memborrowed, dom_id))
        memtarget = int(domain_dictionary[dom_id].memory_actual - memborrowed)
        request.append((dom_id, memtarget))
    return request


# REQ_SAFETY_NET_FACTOR is a bit greater that 1. So that if the domain
# yields a bit less than requested, due to e.g. rounding errors, we will not
# get stuck. The surplus will return to the VM during "balance" call.


# Redistribute positive "total_available_memory" of memory between domains,
# proportionally to prefmem.
def balance_when_enough_memory(
    domain_dictionary, xen_free_memory, total_mem_pref, total_available_memory
):
    log.info(
        "balance_when_enough_memory(xen_free_memory={!r}, "
        "total_mem_pref={!r}, total_available_memory={!r})".format(
            xen_free_memory, total_mem_pref, total_available_memory
        )
    )

    target_memory = {}
    # Memory not assigned because of static max.
    left_memory = 0
    acceptors_count = 0
    for domid, dom in domain_dictionary.items():
        if dom.mem_used is None or dom.no_progress:
            continue
        # Distribute total_available_memory proportionally to mempref.
        scale = 1.0 * prefmem(dom) / total_mem_pref
        target_nonint = prefmem(dom) + scale * total_available_memory
        # Prevent rounding errors.
        target = int(0.999 * target_nonint)
        # Do not try to give more memory than static max.
        if target > dom.memory_maximum:
            left_memory += target - dom.memory_maximum
            target = dom.memory_maximum
        else:
            # Count domains which can accept more memory.
            acceptors_count += 1
        target_memory[domid] = target
    # Distribute left memory across all acceptors.
    while left_memory > 0 and acceptors_count > 0:
        log.info(
            "left_memory={} acceptors_count={}".format(
                left_memory, acceptors_count
            )
        )

        new_left_memory = 0
        new_acceptors_count = acceptors_count
        for domid, target in target_memory.items():
            dom = domain_dictionary[domid]
            if target < dom.memory_maximum:
                memory_bonus = int(0.999 * (left_memory / acceptors_count))
                if target + memory_bonus >= dom.memory_maximum:
                    new_left_memory += (
                        target + memory_bonus - dom.memory_maximum
                    )
                    target = dom.memory_maximum
                    new_acceptors_count -= 1
                else:
                    target += memory_bonus
            target_memory[domid] = target
        left_memory = new_left_memory
        acceptors_count = new_acceptors_count
    # Split target_memory dictionary to donors and acceptors. This is needed to
    # first get memory from donors and only then give it to acceptors.
    donors_rq = []
    acceptors_rq = []
    for domid, target in target_memory.items():
        dom = domain_dictionary[domid]
        if target < dom.memory_actual:
            donors_rq.append((domid, target))
        else:
            acceptors_rq.append((domid, target))
    return donors_rq + acceptors_rq


# When not enough mem to make everyone be above prefmem, make donors be at
# prefmem, and redistribute anything left between acceptors.
def balance_when_low_on_memory(
    domain_dictionary,
    xen_free_memory,
    total_mem_pref_acceptors,
    donors,
    acceptors,
):
    log.info(
        "balance_when_low_on_memory(xen_free_memory={!r}, "
        "total_mem_pref_acceptors={!r}, donors={!r}, acceptors={!r})".format(
            xen_free_memory, total_mem_pref_acceptors, donors, acceptors
        )
    )
    donors_rq = []
    acceptors_rq = []
    squeezed_mem = xen_free_memory
    for domid in donors:
        dom = domain_dictionary[domid]
        avail = -memory_needed(dom)
        if avail < 10 * 1024 * 1024:
            # Probably we have already tried making it exactly at prefmem, give
            # up.
            continue
        squeezed_mem -= avail
        donors_rq.append((domid, prefmem(dom)))
    # The below condition can happen if initially xen free memory is below 50M.
    if squeezed_mem < 0:
        return donors_rq
    for domid in acceptors:
        dom = domain_dictionary[domid]
        scale = 1.0 * prefmem(dom) / total_mem_pref_acceptors
        target_nonint = dom.memory_actual + scale * squeezed_mem
        # Do not try to give more memory than static max.
        target = min(int(0.999 * target_nonint), dom.memory_maximum)
        acceptors_rq.append((domid, target))
    return donors_rq + acceptors_rq


# Get memory information.
# Called before and after domain balances.
# Return a dictionary of various memory data points.
def memory_info(xen_free_memory, domain_dictionary):
    log.debug(
        "memory_info(xen_free_memory={!r}, domain_dictionary={!r})".format(
            xen_free_memory, domain_dictionary
        )
    )

    # Sum of all memory requirements - in other words, the difference between
    # memory required to be added to domains (acceptors) to make them be at
    # their preferred memory, and memory that can be taken from domains
    # (donors) that can provide memory. So, it can be negative when plenty of
    # memory.
    total_memory_needed = 0

    # Sum of memory preferences of all domains.
    total_mem_pref = 0

    # Sum of memory preferences of all domains that require more memory.
    total_mem_pref_acceptors = 0

    donors = []
    acceptors = []
    # Pass 1: compute the above "total" values.
    for domid, dom in domain_dictionary.items():
        if dom.mem_used is None or dom.no_progress:
            continue
        need = memory_needed(dom)
        if need < 0 or dom.memory_actual >= dom.memory_maximum:
            donors.append(domid)
        else:
            acceptors.append(domid)
            total_mem_pref_acceptors += prefmem(dom)
        total_memory_needed += need
        total_mem_pref += prefmem(dom)

    total_available_memory = xen_free_memory - total_memory_needed

    mem_dictionary = {}
    mem_dictionary["domain_dictionary"] = domain_dictionary
    mem_dictionary["total_available_memory"] = total_available_memory
    mem_dictionary["xen_free_memory"] = xen_free_memory
    mem_dictionary["total_mem_pref"] = total_mem_pref
    mem_dictionary["total_mem_pref_acceptors"] = total_mem_pref_acceptors
    mem_dictionary["donors"] = donors
    mem_dictionary["acceptors"] = acceptors
    return mem_dictionary


# Redistribute memory across domains.
# Called when one of domains update its 'meminfo' xenstore key.
# Return the list of (domain, memory_target) pairs to be passed to "xm memset"
# equivalent
def balance(xen_free_memory, domain_dictionary):
    log.debug(
        "balance(xen_free_memory={!r}, domain_dictionary={!r})".format(
            xen_free_memory, domain_dictionary
        )
    )
    memory_dictionary = memory_info(xen_free_memory, domain_dictionary)

    if memory_dictionary["total_available_memory"] > 0:
        return balance_when_enough_memory(
            memory_dictionary["domain_dictionary"],
            memory_dictionary["xen_free_memory"],
            memory_dictionary["total_mem_pref"],
            memory_dictionary["total_available_memory"],
        )
    return balance_when_low_on_memory(
        memory_dictionary["domain_dictionary"],
        memory_dictionary["xen_free_memory"],
        memory_dictionary["total_mem_pref_acceptors"],
        memory_dictionary["donors"],
        memory_dictionary["acceptors"],
    )
