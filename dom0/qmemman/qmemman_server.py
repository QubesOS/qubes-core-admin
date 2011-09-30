#!/usr/bin/python
import SocketServer
import thread
import time
import xen.lowlevel.xs
import sys
import os
from qmemman import SystemState

system_state = SystemState()
global_lock = thread.allocate_lock()

def only_in_first_list(l1, l2):
    ret=[]
    for i in l1:
        if not i in l2:
            ret.append(i)
    return ret

def get_domain_meminfo_key(domain_id):
    return '/local/domain/'+domain_id+'/memory/meminfo'

                    
class WatchType:
    def __init__(self, fn, param):
        self.fn = fn
        self.param = param

class XS_Watcher:
    def __init__(self):
        self.handle = xen.lowlevel.xs.xs()
        self.handle.watch('@introduceDomain', WatchType(XS_Watcher.domain_list_changed, None))
        self.handle.watch('@releaseDomain', WatchType(XS_Watcher.domain_list_changed, None))
        self.watch_token_dict = {}

    def domain_list_changed(self, param):
        curr = self.handle.ls('', '/local/domain')
        if curr == None:
            return
        global_lock.acquire()
        for i in only_in_first_list(curr, self.watch_token_dict.keys()):
#new domain has been created
            watch = WatchType(XS_Watcher.meminfo_changed, i)
            self.watch_token_dict[i] = watch
            self.handle.watch(get_domain_meminfo_key(i), watch)
            system_state.add_domain(i)
        for i in only_in_first_list(self.watch_token_dict.keys(), curr):
#domain destroyed
            self.handle.unwatch(get_domain_meminfo_key(i), self.watch_token_dict[i])
            self.watch_token_dict.pop(i)
            system_state.del_domain(i)
        global_lock.release()
        system_state.do_balance()

    def meminfo_changed(self, domain_id):
        untrusted_meminfo_key = self.handle.read('', get_domain_meminfo_key(domain_id))
        if untrusted_meminfo_key == None or untrusted_meminfo_key == '':
            return
        global_lock.acquire()
        system_state.refresh_meminfo(domain_id, untrusted_meminfo_key)
        global_lock.release()

    def watch_loop(self):
#        sys.stderr = file('/var/log/qubes/qfileexchgd.errors', 'a')
        while True:
            result = self.handle.read_watch()
            token = result[1]
            token.fn(self, token.param)


class QMemmanReqHandler(SocketServer.BaseRequestHandler):
    """
    The RequestHandler class for our server.

    It is instantiated once per connection to the server, and must
    override the handle() method to implement communication to the
    client.
    """

    def handle(self):
        got_lock = False
        # self.request is the TCP socket connected to the client
        while True:
            self.data = self.request.recv(1024).strip()
            if len(self.data) == 0:
                print 'EOF'
                if got_lock:
                    global_lock.release()
                return
            if got_lock:
                print 'Second request over qmemman.sock ?'
                return
            global_lock.acquire()
            got_lock = True
            if system_state.do_balloon(int(self.data)):
                resp = "OK\n"
            else:
                resp = "FAIL\n"
            self.request.send(resp)


def start_server():
    SOCK_PATH='/var/run/qubes/qmemman.sock'
    try:
        os.unlink(SOCK_PATH)
    except:
        pass
    os.umask(0)
    server = SocketServer.UnixStreamServer(SOCK_PATH, QMemmanReqHandler)
    os.umask(077)
    server.serve_forever()

class QMemmanServer:
    @staticmethod          
    def main():
        thread.start_new_thread(start_server, tuple([]))
        XS_Watcher().watch_loop()
