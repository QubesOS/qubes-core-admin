#!/usr/bin/python2
# -*- coding: utf-8 -*-
#
# The Qubes OS Project, http://www.qubes-os.org
#
# Copyright (C) 2010  Rafal Wojtczuk  <rafal@invisiblethingslab.com>
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.
#
#
import SocketServer
import thread
import time
import xen.lowlevel.xs
import sys
import os
import socket
from qmemman import SystemState
import qmemman_algo
from ConfigParser import SafeConfigParser
from optparse import OptionParser
from qubesutils import parse_size

config_path = '/etc/qubes/qmemman.conf'
SOCK_PATH='/var/run/qubes/qmemman.sock'
LOG_PATH='/var/log/qubes/qmemman.log'

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


def start_server(server):
    server.serve_forever()

class QMemmanServer:
    @staticmethod          
    def main():
        usage = "usage: %prog [options]"
        parser = OptionParser(usage)
        parser.add_option("-c", "--config", action="store", dest="config", default=config_path)
        (options, args) = parser.parse_args()

        logfd = os.open(LOG_PATH, os.O_WRONLY|os.O_APPEND|os.O_CREAT, 0644)
        if logfd < 0:
            print sys.stderr, "ERROR: Failed to open log file (%s)" % LOG_PATH
            exit(1)
        # reinitialize python stdout/err
        sys.stdout.flush()
        sys.stderr.flush()
        os.dup2(logfd, 1)
        os.dup2(logfd, 2)
        os.close(logfd)
        devnull = os.open('/dev/null', os.O_RDONLY)
        os.dup2(devnull, 0)

        config = SafeConfigParser({
                'vm-min-mem': str(qmemman_algo.MIN_PREFMEM),
                'dom0-mem-boost': str(qmemman_algo.DOM0_MEM_BOOST),
                'cache-margin-factor': str(qmemman_algo.CACHE_FACTOR)
                })
        config.read(options.config)
        if config.has_section('global'):
            qmemman_algo.MIN_PREFMEM = parse_size(config.get('global', 'vm-min-mem'))
            qmemman_algo.DOM0_MEM_BOOST = parse_size(config.get('global', 'dom0-mem-boost'))
            qmemman_algo.CACHE_FACTOR = config.getfloat('global', 'cache-margin-factor')

        print "values: %s, %s, %s" % (str(qmemman_algo.MIN_PREFMEM), str(qmemman_algo.DOM0_MEM_BOOST), str(qmemman_algo.CACHE_FACTOR))

        try:
            os.unlink(SOCK_PATH)
        except:
            pass
        os.umask(0)
        server = SocketServer.UnixStreamServer(SOCK_PATH, QMemmanReqHandler)
        os.umask(077)
        # notify systemd
        nofity_socket = os.getenv('NOTIFY_SOCKET')
        if nofity_socket:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
            if nofity_socket.startswith('@'):
                nofity_socket = '\0%s' % nofity_socket[1:]
            s.connect(nofity_socket)
            s.sendall("READY=1")
            s.close()

        thread.start_new_thread(start_server, tuple([server]))
        XS_Watcher().watch_loop()
