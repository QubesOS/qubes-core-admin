import xmlrpclib
from xen.xm import XenAPI
import xen.lowlevel.xc
import string
import time
import qmemman_algo
import os

class XendSession(object):
    def __init__(self):
#        self.get_xend_session_old_api()
        self.get_xend_session_new_api()

#    def get_xend_session_old_api(self):
#        from xen.xend import XendClient
#        from xen.util.xmlrpcclient import ServerProxy
#        self.xend_server = ServerProxy(XendClient.uri)
#        if self.xend_server is None:
#            print "get_xend_session_old_api(): cannot open session!"


    def get_xend_session_new_api(self):
        xend_socket_uri = "httpu:///var/run/xend/xen-api.sock"
        self.session = XenAPI.Session (xend_socket_uri)
        self.session.login_with_password ("", "")
        if self.session is None:
            print "get_xend_session_new_api(): cannot open session!"

class DomainState:
    def __init__(self, id):
        self.meminfo = None
        self.memory_actual = None
        self.mem_used = None
        self.uuid = None
        self.id = id
        self.meminfo_updated = False

class SystemState:
    def __init__(self):
        self.xend_session = XendSession()
        self.domdict = {}
        self.xc = xen.lowlevel.xc.xc()
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
        update_uuid_info = False
        for domain in self.xc.domain_getinfo():
            id = str(domain['domid'])
            if self.domdict.has_key(id):
                self.domdict[id].memory_actual = domain['mem_kb']*1024
                if self.domdict[id].uuid is None:
                    update_uuid_info = True
        if not update_uuid_info:
            return
        dom_recs = self.xend_session.session.xenapi.VM.get_all_records()
#        dom_metrics_recs = self.xend_session.session.xenapi.VM_metrics.get_all_records()
        for dom_ref, dom_rec in dom_recs.items():
#            dom_metrics_rec = dom_metrics_recs[dom_rec['metrics']]
            id = dom_rec['domid']
#            mem = int(dom_metrics_rec['memory_actual'])/1024
            if (self.domdict.has_key(id)):
#                self.domdict[id].memory_actual = mem
                self.domdict[id].uuid = dom_rec['uuid']   

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
    def mem_set_alternative(self, id, val):
        os.system('xenstore-write /local/domain/' + id + '/memory/target ' + str(val/1024))
        self.xc.domain_set_target_mem(int(id), val/1024)
    
    def mem_set(self, id, val):
        uuid = self.domdict[id].uuid
        print 'mem-set domain', id, 'to', val
        self.xend_session.session.xenapi.VM.set_memory_dynamic_max_live(uuid, val)
        self.xend_session.session.xenapi.VM.set_memory_dynamic_min_live(uuid, val)

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

    def do_balance(self):
        if os.path.isfile('/etc/do-not-membalance'):
            return
        self.refresh_memactual()
        xenfree = self.get_free_xen_memory()
        memset_reqs = qmemman_algo.balance(xenfree, self.domdict)
        wait_before_first_inflate = False
        i = 0
        while i < len(memset_reqs):
            dom, mem = memset_reqs[i]
            memory_change = mem - self.domdict[dom].memory_actual
            if abs(memory_change) < 100*1024*1024:
                i = i + 1
                continue
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
