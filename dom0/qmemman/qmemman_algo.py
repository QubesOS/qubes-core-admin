import string

#untrusted meminfo size is taken from xenstore key, thus its size is limited
#so splits do not require excessive memory
def parse_meminfo(untrusted_meminfo):
    untrusted_dict = {}
#split meminfo contents into lines
    untrusted_lines = string.split(untrusted_meminfo,"\n")
    for untrusted_lines_iterator in untrusted_lines:
#split a single meminfo line into words
        untrusted_words = string.split(untrusted_lines_iterator)
        if len(untrusted_words) >= 2:
            untrusted_dict[string.rstrip(untrusted_words[0], ":")] = untrusted_words[1]

    return untrusted_dict

def is_meminfo_suspicious(dom, untrusted_meminfo):
    ret = False
    
#check whether the required keys exist and are not negative
    try:
        for i in ('MemTotal', 'MemFree', 'Buffers', 'Cached', 'SwapTotal', 'SwapFree'):
            val = int(untrusted_meminfo[i])*1024
            if (val < 0):
                ret = True
            untrusted_meminfo[i] = val
    except:
        ret = True

    if not ret and untrusted_meminfo['SwapTotal'] < untrusted_meminfo['SwapFree']:
        ret = True
    if not ret and untrusted_meminfo['MemTotal'] < untrusted_meminfo['MemFree'] + untrusted_meminfo['Cached'] + untrusted_meminfo['Buffers']:
        ret = True
#we could also impose some limits on all the above values
#but it has little purpose - all the domain can gain by passing e.g. 
#very large SwapTotal is that it will be assigned all free Xen memory
#it can be achieved with legal values, too, and it will not allow to
#starve existing domains, by design
    if ret:
        print 'suspicious meminfo for domain', dom.id, 'mem actual', dom.memory_actual, untrusted_meminfo
    return ret

def refresh_meminfo_for_domain(dom, untrusted_xenstore_key):
    untrusted_meminfo = parse_meminfo(untrusted_xenstore_key)
    if untrusted_meminfo is None:
        dom.meminfo = None
        return
#sanitize start
    if is_meminfo_suspicious(dom, untrusted_meminfo):
#sanitize end
        dom.meminfo = None
        dom.mem_used = None
    else:
#sanitized, can assign
        dom.meminfo = untrusted_meminfo
        dom.mem_used =  dom.meminfo['MemTotal'] - dom.meminfo['MemFree'] - dom.meminfo['Cached'] - dom.meminfo['Buffers'] + dom.meminfo['SwapTotal'] - dom.meminfo['SwapFree']
                        
def prefmem(dom):
    CACHE_FACTOR = 1.3
#dom0 is special, as it must have large cache, for vbds. Thus, give it a special boost
    if dom.id == '0':
        return dom.mem_used*CACHE_FACTOR + 350*1024*1024
    return dom.mem_used*CACHE_FACTOR

def memneeded(dom):
#do not change
#in balance(), "distribute totalsum proportionally to mempref" relies on this exact formula
    ret = prefmem(dom) - dom.memory_actual
    return ret
    
    
def balloon(memsize, domdict):
    REQ_SAFETY_NET_FACTOR = 1.05
    donors = list()
    request = list()
    available = 0
    for i in domdict.keys():
        if domdict[i].meminfo is None:
            continue
        if domdict[i].no_progress:
            continue
        need = memneeded(domdict[i])
        if need < 0:
            print 'balloon: dom' , i, 'has actual memory', domdict[i].memory_actual
            donors.append((i,-need))
            available-=need   
    print 'req=', memsize, 'avail=', available, 'donors', donors
    if available<memsize:
        return ()
    scale = 1.0*memsize/available
    for donors_iter in donors:
        id, mem = donors_iter
        memborrowed = mem*scale*REQ_SAFETY_NET_FACTOR
        print 'borrow' , memborrowed, 'from', id
        memtarget = int(domdict[id].memory_actual - memborrowed)
        request.append((id, memtarget))
    return request
# REQ_SAFETY_NET_FACTOR is a bit greater that 1. So that if the domain yields a bit less than requested, due
# to e.g. rounding errors, we will not get stuck. The surplus will return to the VM during "balance" call.


#redistribute positive "totalsum" of memory between domains, proportionally to prefmem
def balance_when_enough_memory(domdict, xenfree, total_mem_pref, totalsum):
    donors_rq = list()
    acceptors_rq = list()
    for i in domdict.keys():
        if domdict[i].meminfo is None:
            continue
#distribute totalsum proportionally to mempref
        scale = 1.0*prefmem(domdict[i])/total_mem_pref
        target_nonint = prefmem(domdict[i]) + scale*totalsum
#prevent rounding errors
        target = int(0.999*target_nonint)
        if (target < domdict[i].memory_actual):
            donors_rq.append((i, target))
        else:
            acceptors_rq.append((i, target))
#    print 'balance(enough): xenfree=', xenfree, 'requests:', donors_rq + acceptors_rq
    return donors_rq + acceptors_rq

#when not enough mem to make everyone be above prefmem, make donors be at prefmem, and 
#redistribute anything left between acceptors
def balance_when_low_on_memory(domdict, xenfree, total_mem_pref_acceptors, donors, acceptors):
    donors_rq = list()
    acceptors_rq = list()
    squeezed_mem = xenfree
    for i in donors:
        avail = -memneeded(domdict[i])
        if avail < 10*1024*1024:
            #probably we have already tried making it exactly at prefmem, give up
            continue
        squeezed_mem -= avail
        donors_rq.append((i, prefmem(domdict[i])))
#the below can happen if initially xen free memory is below 50M
    if squeezed_mem < 0:
        return donors_rq
    for i in acceptors:
        scale = 1.0*prefmem(domdict[i])/total_mem_pref_acceptors
        target_nonint = domdict[i].memory_actual + scale*squeezed_mem
        acceptors_rq.append((i, int(target_nonint)))       
#    print 'balance(low): xenfree=', xenfree, 'requests:', donors_rq + acceptors_rq
    return donors_rq + acceptors_rq
 
def balance(xenfree, domdict):
    total_memneeded = 0
    total_mem_pref = 0
    total_mem_pref_acceptors = 0
    
    donors = list()
    acceptors = list()
#pass 1: compute the above "total" values
    for i in domdict.keys():
        if domdict[i].meminfo is None:
            continue
        need = memneeded(domdict[i])
#        print 'domain' , i, 'act/pref', domdict[i].memory_actual, prefmem(domdict[i]), 'need=', need
        if need < 0:
            donors.append(i)
        else:
            acceptors.append(i)
            total_mem_pref_acceptors += prefmem(domdict[i])
        total_memneeded += need
        total_mem_pref += prefmem(domdict[i])

    totalsum = xenfree - total_memneeded  
    if totalsum > 0:
        return balance_when_enough_memory(domdict, xenfree, total_mem_pref, totalsum)
    else:
        return balance_when_low_on_memory(domdict, xenfree, total_mem_pref_acceptors, donors, acceptors)
