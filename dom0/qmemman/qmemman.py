import xen.lowlevel.xc
import xen.lowlevel.xs
import string
import time
import qmemman_algo
import os

class DomainState:
    def __init__(self, id):
        self.meminfo = None
        self.memory_actual = None
        self.mem_used = None
        self.id = id
        self.meminfo_updated = False

class SystemState:
    def __init__(self):
        self.domdict = {}
        self.xc = xen.lowlevel.xc.xc()
        self.xs = xen.lowlevel.xs.xs()
        self.BALOON_DELAY = 0.1

    def add_domain(self, id):
        self.domdict[id] = DomainState(id)

    def del_domain(self, id):
        self.domdict.pop(id)

    def get_free_xen_memory(self):
        return self.xc.physinfo()['free_memory']*1024
#        hosts = self.xend_session.session.xenapi.host.get_all()
#        host_record = self.xend_session.session.xenapi.host.get_record(hosts[0])
#        host_metrics_record = self.xend_session.session.xenapi.host_metrics.get_record(host_record["metrics"])
#        ret = host_metrics_record["memory_free"]
#        return long(ret)

    def refresh_memactual(self):
        for domain in self.xc.domain_getinfo():
            id = str(domain['domid'])
            if self.domdict.has_key(id):
                self.domdict[id].memory_actual = domain['mem_kb']*1024

    def parse_meminfo(self, meminfo):
        dict = {}
        l1 = string.split(meminfo,"\n")
        for i in l1:
            l2 = string.split(i)
            if len(l2) >= 2:
                dict[string.rstrip(l2[0], ":")] = l2[1]

        try:
            for i in ('MemFree', 'Buffers', 'Cached', 'SwapTotal', 'SwapFree'):
                val = int(dict[i])*1024
                if (val < 0):
                    return None
                dict[i] = val
        except:
            return None

        if dict['SwapTotal'] < dict['SwapFree']:
            return None
        return dict

#the below works (and is fast), but then 'xm list' shows unchanged memory value
    def mem_set(self, id, val):
        print 'mem-set domain', id, 'to', val
        self.xs.write('', '/local/domain/' + id + '/memory/target', str(val/1024))
        self.xc.domain_set_target_mem(int(id), val/1024)
    
    def mem_set_obsolete(self, id, val):
        uuid = self.domdict[id].uuid
        if val >= 2**31:
            print 'limiting memory from ', val, 'to maxint because of xml-rpc lameness'
            val = 2**31 - 1
        print 'mem-set domain', id, 'to', val
        try:
            self.xend_session.session.xenapi.VM.set_memory_dynamic_max_live(uuid, val)
            self.xend_session.session.xenapi.VM.set_memory_dynamic_min_live(uuid, val)
#can happen in the middle of domain shutdown
        except XenAPI.Failure:
            pass

    def do_balloon(self, memsize):
        MAX_TRIES = 20
        niter = 0
        prev_memory_actual = None
        for i in self.domdict.keys():
            self.domdict[i].no_progress = False
        while True:
            xenfree = self.get_free_xen_memory()
            print 'got xenfree=', xenfree
            if xenfree >= memsize:
                return True
            self.refresh_memactual()
            if prev_memory_actual is not None:
                for i in prev_memory_actual.keys():
                    if prev_memory_actual[i] == self.domdict[i].memory_actual:
                        self.domdict[i].no_progress = True
                        print 'domain', i, 'stuck at', self.domdict[i].memory_actual
            memset_reqs = qmemman_algo.balloon(memsize-xenfree, self.domdict)
            print 'requests:', memset_reqs
            if niter > MAX_TRIES or len(memset_reqs) == 0:
                return False
            prev_memory_actual = {}
            for i in memset_reqs:
                dom, mem = i
                self.mem_set(dom, mem)
                prev_memory_actual[dom] = self.domdict[dom].memory_actual
            time.sleep(self.BALOON_DELAY)
            niter = niter + 1
            
    def refresh_meminfo(self, domid, val):
        self.domdict[domid].meminfo = self.parse_meminfo(val)
        self.domdict[domid].meminfo_updated = True

    def adjust_inflates_to_xenfree(self, reqs, idx):
        i = idx
        memory_needed = 0
        while i < len(reqs):
            dom, mem = reqs[i]
            memory_needed += mem - self.domdict[dom].memory_actual
            i = i + 1
        scale = 1.0*self.get_free_xen_memory()/memory_needed
        dom, mem = reqs[idx]
        scaled_req = self.domdict[dom].memory_actual + scale*(mem - self.domdict[dom].memory_actual)
        return int(scaled_req)

    def is_balance_req_significant(self, memset_reqs):
        total_memory_transfer = 0
        MIN_TOTAL_MEMORY_TRANSFER = 150*1024*1024
        for rq in memset_reqs:
            dom, mem = rq
            memory_change = mem - self.domdict[dom].memory_actual
            total_memory_transfer += abs(memory_change)
        return total_memory_transfer > MIN_TOTAL_MEMORY_TRANSFER

    def do_balance(self):
        if os.path.isfile('/etc/do-not-membalance'):
            return
        self.refresh_memactual()
        xenfree = self.get_free_xen_memory()
        memset_reqs = qmemman_algo.balance(xenfree, self.domdict)
        if not self.is_balance_req_significant(memset_reqs):
            return
            
        wait_before_first_inflate = False
        i = 0
        while i < len(memset_reqs):
            dom, mem = memset_reqs[i]
            memory_change = mem - self.domdict[dom].memory_actual
            if memory_change < 0:
                wait_before_first_inflate = True
            else:
                if wait_before_first_inflate:
                    time.sleep(self.BALOON_DELAY)
                    wait_before_first_inflate = False
                #the following is called before _each_ inflate, to account for possibility that
                #previously triggered memory release is in progress
                mem = self.adjust_inflates_to_xenfree(memset_reqs, i)
            self.mem_set(dom, mem)
            i = i + 1

#        for i in self.domdict.keys():
#            print 'domain ', i, ' meminfo=', self.domdict[i].meminfo, 'actual mem', self.domdict[i].memory_actual
#            print 'domain ', i, 'actual mem', self.domdict[i].memory_actual
#        print 'xen free mem', self.get_free_xen_memory()
