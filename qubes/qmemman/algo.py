# pylint: skip-file

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
import string

# This are only defaults - can be overridden by QMemmanServer with values from
# config file
CACHE_FACTOR = 1.3
MIN_PREFMEM = 200 * 1024 * 1024
DOM0_MEM_BOOST = 350 * 1024 * 1024

log = logging.getLogger('qmemman.daemon.algo')


# untrusted meminfo size is taken from xenstore key, thus its size is limited
# so splits do not require excessive memory
def sanitize_and_parse_meminfo(untrusted_meminfo):
    if not untrusted_meminfo:
        return None

    # new syntax - just one int
    try:
        if int(untrusted_meminfo) >= 0:
            return int(untrusted_meminfo) * 1024
    except ValueError:
        pass

    untrusted_meminfo = untrusted_meminfo.decode('ascii', errors='strict')
    # not new syntax - try the old one
    untrusted_dict = {}
    # split meminfo contents into lines
    untrusted_lines = untrusted_meminfo.split("\n")
    for untrusted_lines_iterator in untrusted_lines:
        # split a single meminfo line into words
        untrusted_words = untrusted_lines_iterator.split()
        if len(untrusted_words) >= 2:
            untrusted_dict[untrusted_words[0].rstrip(":")] = \
                untrusted_words[1]

    # sanitize start
    if not is_meminfo_suspicious(untrusted_dict):
        # sanitize end
        meminfo = untrusted_dict
        return (meminfo['MemTotal'] -
                meminfo['MemFree'] - meminfo['Cached'] - meminfo['Buffers'] +
                meminfo['SwapTotal'] - meminfo['SwapFree']) * 1024

    return None


def is_meminfo_suspicious(untrusted_meminfo):
    log.debug('is_meminfo_suspicious('
              'untrusted_meminfo={!r})'.format(untrusted_meminfo))
    ret = False

    # check whether the required keys exist and are not negative
    try:
        for i in ('MemTotal', 'MemFree', 'Buffers', 'Cached',
        'SwapTotal', 'SwapFree'):
            val = int(untrusted_meminfo[i])
            if val < 0:
                ret = True
            untrusted_meminfo[i] = val
    except:
        ret = True

    if untrusted_meminfo['SwapTotal'] < untrusted_meminfo['SwapFree']:
        ret = True
    if untrusted_meminfo['MemTotal'] < \
                            untrusted_meminfo['MemFree'] + \
                            untrusted_meminfo['Cached'] + untrusted_meminfo[
                'Buffers']:
        ret = True
    # we could also impose some limits on all the above values
    # but it has little purpose - all the domain can gain by passing e.g.
    # very large SwapTotal is that it will be assigned all free Xen memory
    # it can be achieved with legal values, too, and it will not allow to
    # starve existing domains, by design
    if ret:
        log.warning('suspicious meminfo untrusted_meminfo={!r}'.format(
            untrusted_meminfo))
    return ret


# called when a domain updates its 'meminfo' xenstore key
def refresh_meminfo_for_domain(domain, untrusted_xenstore_key):
    domain.mem_used = sanitize_and_parse_meminfo(untrusted_xenstore_key)


def prefmem(domain):
    # dom0 is special, as it must have large cache, for vbds. Thus, give it
    # a special boost
    if domain.id == '0':
        return min(domain.mem_used * CACHE_FACTOR + DOM0_MEM_BOOST,
            domain.memory_maximum)
    return max(min(domain.mem_used * CACHE_FACTOR, domain.memory_maximum),
        MIN_PREFMEM)


def memory_needed(domain):
    # do not change
    # in balance(), "distribute total_available_memory proportionally to
    # mempref" relies on this exact formula
    ret = prefmem(domain) - domain.memory_actual
    return ret


# prepare list of (domain, memory_target) pairs that need to be passed
# to "xm memset" equivalent in order to obtain "memsize" of memory
# return empty list when the request cannot be satisfied
def balloon(memsize, domain_dictionary):
    log.debug('balloon(memsize={!r}, domain_dictionary={!r})'.format(
        memsize, domain_dictionary))
    REQ_SAFETY_NET_FACTOR = 1.05
    donors = list()
    request = list()
    available = 0
    for i in domain_dictionary.keys():
        if domain_dictionary[i].mem_used is None:
            continue
        if domain_dictionary[i].no_progress:
            continue
        need = memory_needed(domain_dictionary[i])
        if need < 0:
            log.info('balloon: dom {} has actual memory {}'.format(i,
                domain_dictionary[i].memory_actual))
            donors.append((i, -need))
            available -= need

    log.info('req={} avail={} donors={!r}'.format(memsize, available, donors))

    if available < memsize:
        return ()
    scale = 1.0 * memsize / available
    for donors_iter in donors:
        dom_id, mem = donors_iter
        memborrowed = mem * scale * REQ_SAFETY_NET_FACTOR
        log.info('borrow {} from {}'.format(memborrowed, dom_id))
        memtarget = int(domain_dictionary[dom_id].memory_actual - memborrowed)
        request.append((dom_id, memtarget))
    return request


# REQ_SAFETY_NET_FACTOR is a bit greater that 1. So that if the domain
# yields a bit less than requested, due to e.g. rounding errors, we will not
# get stuck. The surplus will return to the VM during "balance" call.


# redistribute positive "total_available_memory" of memory between domains,
# proportionally to prefmem
def balance_when_enough_memory(domain_dictionary,
        xen_free_memory, total_mem_pref, total_available_memory):
    log.info('balance_when_enough_memory(xen_free_memory={!r}, '
             'total_mem_pref={!r}, total_available_memory={!r})'.format(
        xen_free_memory, total_mem_pref, total_available_memory))

    target_memory = {}
    # memory not assigned because of static max
    left_memory = 0
    acceptors_count = 0
    for i in domain_dictionary.keys():
        if domain_dictionary[i].mem_used is None:
            continue
        if domain_dictionary[i].no_progress:
            continue
        # distribute total_available_memory proportionally to mempref
        scale = 1.0 * prefmem(domain_dictionary[i]) / total_mem_pref
        target_nonint = prefmem(
            domain_dictionary[i]) + scale * total_available_memory
        # prevent rounding errors
        target = int(0.999 * target_nonint)
        # do not try to give more memory than static max
        if target > domain_dictionary[i].memory_maximum:
            left_memory += target - domain_dictionary[i].memory_maximum
            target = domain_dictionary[i].memory_maximum
        else:
            # count domains which can accept more memory
            acceptors_count += 1
        target_memory[i] = target
    # distribute left memory across all acceptors
    while left_memory > 0 and acceptors_count > 0:
        log.info('left_memory={} acceptors_count={}'.format(
            left_memory, acceptors_count))

        new_left_memory = 0
        new_acceptors_count = acceptors_count
        for i in target_memory.keys():
            target = target_memory[i]
            if target < domain_dictionary[i].memory_maximum:
                memory_bonus = int(0.999 * (left_memory / acceptors_count))
                if target + memory_bonus >= domain_dictionary[i].memory_maximum:
                    new_left_memory += target + memory_bonus - \
                                       domain_dictionary[i].memory_maximum
                    target = domain_dictionary[i].memory_maximum
                    new_acceptors_count -= 1
                else:
                    target += memory_bonus
            target_memory[i] = target
        left_memory = new_left_memory
        acceptors_count = new_acceptors_count
    # split target_memory dictionary to donors and acceptors
    # this is needed to first get memory from donors and only then give it
    # to acceptors
    donors_rq = list()
    acceptors_rq = list()
    for i in target_memory.keys():
        target = target_memory[i]
        if target < domain_dictionary[i].memory_actual:
            donors_rq.append((i, target))
        else:
            acceptors_rq.append((i, target))

    # print 'balance(enough): xen_free_memory=', xen_free_memory, \
    #  'requests:', donors_rq + acceptors_rq
    return donors_rq + acceptors_rq


# when not enough mem to make everyone be above prefmem, make donors be at
# prefmem, and redistribute anything left between acceptors
def balance_when_low_on_memory(domain_dictionary,
        xen_free_memory, total_mem_pref_acceptors, donors, acceptors):
    log.debug('balance_when_low_on_memory(xen_free_memory={!r}, '
        'total_mem_pref_acceptors={!r}, donors={!r}, acceptors={!r})'.format(
         xen_free_memory, total_mem_pref_acceptors, donors, acceptors))
    donors_rq = list()
    acceptors_rq = list()
    squeezed_mem = xen_free_memory
    for i in donors:
        avail = -memory_needed(domain_dictionary[i])
        if avail < 10 * 1024 * 1024:
            # probably we have already tried making it exactly at prefmem,
            # give up
            continue
        squeezed_mem -= avail
        donors_rq.append((i, prefmem(domain_dictionary[i])))
    # the below can happen if initially xen free memory is below 50M
    if squeezed_mem < 0:
        return donors_rq
    for i in acceptors:
        scale = 1.0 * prefmem(domain_dictionary[i]) / total_mem_pref_acceptors
        target_nonint = \
            domain_dictionary[i].memory_actual + scale * squeezed_mem
        # do not try to give more memory than static max
        target = \
            min(int(0.999 * target_nonint), domain_dictionary[i].memory_maximum)
        acceptors_rq.append((i, target))
    # print 'balance(low): xen_free_memory=', xen_free_memory, 'requests:',
    # donors_rq + acceptors_rq
    return donors_rq + acceptors_rq


# redistribute memory across domains
# called when one of domains update its 'meminfo' xenstore key
# return the list of (domain, memory_target) pairs to be passed to
# "xm memset" equivalent
def balance(xen_free_memory, domain_dictionary):
    log.debug('balance(xen_free_memory={!r}, domain_dictionary={!r})'.format(
        xen_free_memory, domain_dictionary))

    # sum of all memory requirements - in other words, the difference between
    # memory required to be added to domains (acceptors) to make them be
    # at their preferred memory, and memory that can be taken from domains
    # (donors) that can provide memory. So, it can be negative when plenty
    # of memory.
    total_memory_needed = 0

    # sum of memory preferences of all domains
    total_mem_pref = 0

    # sum of memory preferences of all domains that require more memory
    total_mem_pref_acceptors = 0

    donors = list()  # domains that can yield memory
    acceptors = list()  # domains that require more memory
    # pass 1: compute the above "total" values
    for i in domain_dictionary.keys():
        if domain_dictionary[i].mem_used is None:
            continue
        if domain_dictionary[i].no_progress:
            continue
        need = memory_needed(domain_dictionary[i])
        # print 'domain' , i, 'act/pref', \
        #  domain_dictionary[i].memory_actual, prefmem(domain_dictionary[i]), \
        #  'need=', need
        if need < 0 or domain_dictionary[i].memory_actual >= \
                domain_dictionary[i].memory_maximum:
            donors.append(i)
        else:
            acceptors.append(i)
            total_mem_pref_acceptors += prefmem(domain_dictionary[i])
        total_memory_needed += need
        total_mem_pref += prefmem(domain_dictionary[i])

    total_available_memory = xen_free_memory - total_memory_needed
    if total_available_memory > 0:
        return balance_when_enough_memory(domain_dictionary, xen_free_memory,
            total_mem_pref, total_available_memory)
    else:
        return balance_when_low_on_memory(domain_dictionary, xen_free_memory,
            total_mem_pref_acceptors, donors, acceptors)
