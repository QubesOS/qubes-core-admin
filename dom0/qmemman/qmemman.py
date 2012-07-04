import xen.lowlevel.xc
import xen.lowlevel.xs
import string
import time
import qmemman_algo
import os

class DomainState:
    def __init__(self, id):
        self.meminfo = None		#dictionary of memory info read from client
        self.memory_actual = None	#the current memory size
        self.memory_maximum = None	#the maximum memory size
        self.mem_used = None		#used memory, computed based on meminfo
        self.id = id			#domain id
        self.last_target = 0		#the last memset target

class SystemState:
    def __init__(self):
        self.domdict = {}
        self.xc = xen.lowlevel.xc.xc()
        self.xs = xen.lowlevel.xs.xs()
        self.BALOON_DELAY = 0.1
        self.XEN_FREE_MEM_LEFT = 50*1024*1024
        self.XEN_FREE_MEM_MIN = 25*1024*1024
        self.ALL_PHYS_MEM = self.xc.physinfo()['total_memory']*1024

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

#refresh information on memory assigned to all domains
    def refresh_memactual(self):
        for domain in self.xc.domain_getinfo():
            id = str(domain['domid'])
            if self.domdict.has_key(id):
                self.domdict[id].memory_actual = domain['mem_kb']*1024
                self.domdict[id].memory_maximum = self.xs.read('', '/local/domain/%s/memory/static-max' % str(id))
                if not self.domdict[id].memory_maximum:
                    self.domdict[id].memory_maximum = self.ALL_PHYS_MEM
# the previous line used to be
#                    self.domdict[id].memory_maximum = domain['maxmem_kb']*1024
# but domain['maxmem_kb'] changes in self.mem_set as well, and this results in
# the memory never increasing
# in fact, the only possible case of nonexisting memory/static-max is dom0
# see #307

#the below works (and is fast), but then 'xm list' shows unchanged memory value
    def mem_set(self, id, val):
        print 'mem-set domain', id, 'to', val
        self.domdict[id].last_target = val
        self.xs.write('', '/local/domain/' + id + '/memory/target', str(val/1024))
#can happen in the middle of domain shutdown
#apparently xc.lowlevel throws exceptions too
        try:
            self.xc.domain_setmaxmem(int(id), val/1024 + 1024) # LIBXL_MAXMEM_CONSTANT=1024
            self.xc.domain_set_target_mem(int(id), val/1024)
        except:
            pass
    
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

# this is called at the end of ballooning, when we have Xen free mem already
# make sure that past mem_set will not decrease Xen free mem
    def inhibit_balloon_up(self):
        for i in self.domdict.keys():
            dom = self.domdict[i]
            if dom.memory_actual is not None and dom.memory_actual + 200*1024 < dom.last_target:
                print "Preventing balloon up to", dom.last_target
                self.mem_set(i, dom.memory_actual)

#perform memory ballooning, across all domains, to add "memsize" to Xen free memory
    def do_balloon(self, memsize):
        MAX_TRIES = 20
        niter = 0
        prev_memory_actual = None
        for i in self.domdict.keys():
            self.domdict[i].no_progress = False
        print "do_balloon start"
        while True:
            self.refresh_memactual()
            xenfree = self.get_free_xen_memory()
            print 'got xenfree=', xenfree
            if xenfree >= memsize + self.XEN_FREE_MEM_MIN:
                self.inhibit_balloon_up()
                return True
            if prev_memory_actual is not None:
                for i in prev_memory_actual.keys():
                    if prev_memory_actual[i] == self.domdict[i].memory_actual:
                        #domain not responding to memset requests, remove it from donors
                        self.domdict[i].no_progress = True
                        print 'domain', i, 'stuck at', self.domdict[i].memory_actual
            memset_reqs = qmemman_algo.balloon(memsize + self.XEN_FREE_MEM_LEFT - xenfree, self.domdict)
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

    def refresh_meminfo(self, domid, untrusted_meminfo_key):
        qmemman_algo.refresh_meminfo_for_domain(self.domdict[domid], untrusted_meminfo_key)
        self.do_balance()

#is the computed balance request big enough ?
#so that we do not trash with small adjustments
    def is_balance_req_significant(self, memset_reqs, xenfree):
        total_memory_transfer = 0
        MIN_TOTAL_MEMORY_TRANSFER = 150*1024*1024
        MIN_MEM_CHANGE_WHEN_UNDER_PREF = 15*1024*1024
        # If xenfree to low, return immediately
        if self.XEN_FREE_MEM_LEFT - xenfree > MIN_MEM_CHANGE_WHEN_UNDER_PREF:
            return True
        for rq in memset_reqs:
            dom, mem = rq
            last_target = self.domdict[dom].last_target
            memory_change = mem - last_target
            total_memory_transfer += abs(memory_change)
            pref = qmemman_algo.prefmem(self.domdict[dom])
            if last_target > 0 and last_target < pref and memory_change > MIN_MEM_CHANGE_WHEN_UNDER_PREF:
                print 'dom', dom, 'is below pref, allowing balance'
                return True
        return total_memory_transfer + abs(xenfree - self.XEN_FREE_MEM_LEFT) > MIN_TOTAL_MEMORY_TRANSFER

    def print_stats(self, xenfree, memset_reqs):
        for i in self.domdict.keys():
            if self.domdict[i].meminfo is not None:
                print 'dom' , i, 'act/pref', self.domdict[i].memory_actual, qmemman_algo.prefmem(self.domdict[i])
        print 'xenfree=', xenfree, 'balance req:', memset_reqs

    def do_balance(self):
        if os.path.isfile('/var/run/qubes/do-not-membalance'):
            return
        self.refresh_memactual()
        xenfree = self.get_free_xen_memory()
        memset_reqs = qmemman_algo.balance(xenfree - self.XEN_FREE_MEM_LEFT, self.domdict)
        if not self.is_balance_req_significant(memset_reqs, xenfree):
            return

        self.print_stats(xenfree, memset_reqs)

        for rq in memset_reqs:
            dom, mem = rq
            self.mem_set(dom, mem)

#        for i in self.domdict.keys():
#            print 'domain ', i, ' meminfo=', self.domdict[i].meminfo, 'actual mem', self.domdict[i].memory_actual
#            print 'domain ', i, 'actual mem', self.domdict[i].memory_actual
#        print 'xen free mem', self.get_free_xen_memory()
