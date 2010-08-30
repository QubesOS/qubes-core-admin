def is_suspicious(dom):
    ret = False
    if dom.meminfo['SwapTotal'] < dom.meminfo['SwapFree']:
        ret = True
    if dom.memory_actual < dom.meminfo['MemFree'] + dom.meminfo['Cached'] + dom.meminfo['Buffers']:
        ret = True
    if ret:
        print 'suspicious meminfo for domain', dom.id, 'mem actual', dom.memory_actual, dom.meminfo
    return ret

def recalc_mem_used(domdict):
    for domid in domdict.keys():
        dom = domdict[domid]
        if dom.meminfo_updated:
            dom.meminfo_updated = False
            if is_suspicious(dom):
                dom.meminfo = None
                dom.mem_used = None
            else:
                dom.mem_used =  dom.memory_actual - dom.meminfo['MemFree'] - dom.meminfo['Cached'] - dom.meminfo['Buffers'] + dom.meminfo['SwapTotal'] - dom.meminfo['SwapFree']

def prefmem(dom):
    if dom.meminfo_updated:
        raise AssertionError('meminfo_updated=True in prefmem')
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
    recalc_mem_used(domdict)
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
 
def balance(xenfree, domdict):
    total_memneeded = 0
    total_mem_pref = 0
    recalc_mem_used(domdict)
#pass 1: compute the above "total" values
    for i in domdict.keys():
        if domdict[i].meminfo is None:
            continue
        need = memneeded(domdict[i])
        print 'domain' , i, 'act/pref', domdict[i].memory_actual, prefmem(domdict[i]), 'need=', need
        total_memneeded += need
        total_mem_pref += prefmem(domdict[i])

    totalsum = xenfree - total_memneeded  

#pass 2: redistribute "totalsum" of memory between domains, proportionally to prefmem
    donors = list()
    acceptors = list()
    for i in domdict.keys():
        if domdict[i].meminfo is None:
            continue
#distribute totalsum proportionally to mempref
        scale = 1.0*prefmem(domdict[i])/total_mem_pref
        target_nonint = prefmem(domdict[i]) + scale*totalsum
#prevent rounding errors
        target = int(0.995*target_nonint)
        if (target < domdict[i].memory_actual):
            donors.append((i, target))
        else:
            acceptors.append((i, target))
    print 'balance: xenfree=', xenfree, 'requests:', donors + acceptors
    return donors + acceptors
    
    