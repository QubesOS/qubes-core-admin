# pylint: skip-file

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
import configparser
import socketserver
import logging
import logging.handlers
import os
import socket
import sys
import threading

import xen.lowlevel.xs

import qubes.qmemman
import qubes.qmemman.algo
import qubes.utils

SOCK_PATH = '/var/run/qubes/qmemman.sock'
LOG_PATH = '/var/log/qubes/qmemman.log'

system_state = qubes.qmemman.SystemState()
global_lock = threading.Lock()
# If XS_Watcher will
# handle meminfo event before @introduceDomain, it will use
# incomplete domain list for that and may redistribute memory
# allocated to some VM, but not yet used (see #1389).
# To fix that, system_state should be updated (refresh domain
# list) before processing other changes, every time some process requested
# memory for a new VM, before releasing the lock. Then XS_Watcher will check
# this flag before processing other event.
force_refresh_domain_list = False

def only_in_first_list(l1, l2):
    ret = []
    for i in l1:
        if not i in l2:
            ret.append(i)
    return ret

def get_domain_meminfo_key(domain_id):
    return '/local/domain/'+domain_id+'/memory/meminfo'


class WatchType(object):
    def __init__(self, fn, param):
        self.fn = fn
        self.param = param

class XS_Watcher(object):
    def __init__(self):
        self.log = logging.getLogger('qmemman.daemon.xswatcher')
        self.log.debug('XS_Watcher()')

        self.handle = xen.lowlevel.xs.xs()
        self.handle.watch('@introduceDomain', WatchType(
            XS_Watcher.domain_list_changed, False))
        self.handle.watch('@releaseDomain', WatchType(
            XS_Watcher.domain_list_changed, False))
        self.watch_token_dict = {}

    def domain_list_changed(self, refresh_only=False):
        """
        Check if any domain was created/destroyed. If it was, update
        appropriate list. Then redistribute memory.

        :param refresh_only If True, only refresh domain list, do not
        redistribute memory. In this mode, caller must already hold
        global_lock.
        """
        self.log.debug('domain_list_changed(only_refresh={!r})'.format(
            refresh_only))

        got_lock = False
        if not refresh_only:
            self.log.debug('acquiring global_lock')
            global_lock.acquire()
            got_lock = True
            self.log.debug('global_lock acquired')
        try:
            curr = self.handle.ls('', '/local/domain')
            if curr is None:
                return

            # check if domain is really there, it may happen that some empty
            # directories are left in xenstore
            curr = list(filter(
                lambda x:
                self.handle.read('',
                                 '/local/domain/{}/domid'.format(x)
                                 ) is not None,
                curr
            ))
            self.log.debug('curr={!r}'.format(curr))

            for i in only_in_first_list(curr, self.watch_token_dict.keys()):
                # new domain has been created
                watch = WatchType(XS_Watcher.meminfo_changed, i)
                self.watch_token_dict[i] = watch
                self.handle.watch(get_domain_meminfo_key(i), watch)
                system_state.add_domain(i)

            for i in only_in_first_list(self.watch_token_dict.keys(), curr):
                # domain destroyed
                self.handle.unwatch(get_domain_meminfo_key(i), self.watch_token_dict[i])
                self.watch_token_dict.pop(i)
                system_state.del_domain(i)
        finally:
            if got_lock:
                global_lock.release()
                self.log.debug('global_lock released')

        if not refresh_only:
            system_state.do_balance()


    def meminfo_changed(self, domain_id):
        self.log.debug('meminfo_changed(domain_id={!r})'.format(domain_id))
        untrusted_meminfo_key = self.handle.read(
            '', get_domain_meminfo_key(domain_id))
        if untrusted_meminfo_key == None or untrusted_meminfo_key == '':
            return

        self.log.debug('acquiring global_lock')
        global_lock.acquire()
        self.log.debug('global_lock acquired')
        try:
            if force_refresh_domain_list:
                self.domain_list_changed(refresh_only=True)

            system_state.refresh_meminfo(domain_id, untrusted_meminfo_key)
        finally:
            global_lock.release()
            self.log.debug('global_lock released')


    def watch_loop(self):
        self.log.debug('watch_loop()')
        while True:
            result = self.handle.read_watch()
            self.log.debug('watch_loop result={!r}'.format(result))
            token = result[1]
            token.fn(self, token.param)


class QMemmanReqHandler(socketserver.BaseRequestHandler):
    """
    The RequestHandler class for our server.

    It is instantiated once per connection to the server, and must
    override the handle() method to implement communication to the
    client.
    """

    def handle(self):
        self.log = logging.getLogger('qmemman.daemon.reqhandler')

        got_lock = False
        try:
            # self.request is the TCP socket connected to the client
            while True:
                self.data = self.request.recv(1024).strip()
                self.log.debug('data={!r}'.format(self.data))
                if len(self.data) == 0:
                    self.log.info('EOF')
                    if got_lock:
                        global force_refresh_domain_list
                        force_refresh_domain_list = True
                    return

                # XXX something is wrong here: return without release?
                if got_lock:
                    self.log.warning('Second request over qmemman.sock?')
                    return

                self.log.debug('acquiring global_lock')
                global_lock.acquire()
                self.log.debug('global_lock acquired')

                got_lock = True
                if system_state.do_balloon(int(self.data.decode('ascii'))):
                    resp = b"OK\n"
                else:
                    resp = b"FAIL\n"
                self.log.debug('resp={!r}'.format(resp))
                self.request.send(resp)
        except BaseException as e:
            self.log.exception(
                "exception while handling request: {!r}".format(e))
        finally:
            if got_lock:
                global_lock.release()
                self.log.debug('global_lock released')


parser = qubes.tools.QubesArgumentParser(want_app=False)

parser.add_argument('--config', '-c', metavar='FILE',
    action='store', default='/etc/qubes/qmemman.conf',
    help='qmemman config file')

parser.add_argument('--foreground',
    action='store_true', default=False,
    help='do not close stdio')


def main():
    args = parser.parse_args()

    # setup logging
    ha_syslog = logging.handlers.SysLogHandler('/dev/log')
    ha_syslog.setFormatter(
        logging.Formatter('%(name)s[%(process)d]: %(message)s'))
    logging.root.addHandler(ha_syslog)

    # leave log for backwards compatibility
    ha_file = logging.FileHandler(LOG_PATH)
    ha_file.setFormatter(
        logging.Formatter('%(asctime)s %(name)s[%(process)d]: %(message)s'))
    logging.root.addHandler(ha_file)

    if args.foreground:
        ha_stderr = logging.StreamHandler(sys.stderr)
        ha_file.setFormatter(
            logging.Formatter('%(asctime)s %(name)s[%(process)d]: %(message)s'))
        logging.root.addHandler(ha_stderr)
    else:
        # close io
        sys.stdout.close()
        sys.stderr.close()

    sys.stdin.close()

    logging.root.setLevel(parser.get_loglevel_from_verbosity(args))

    log = logging.getLogger('qmemman.daemon')

    config = configparser.SafeConfigParser({
            'vm-min-mem': str(qubes.qmemman.algo.MIN_PREFMEM),
            'dom0-mem-boost': str(qubes.qmemman.algo.DOM0_MEM_BOOST),
            'cache-margin-factor': str(qubes.qmemman.algo.CACHE_FACTOR)
            })
    config.read(args.config)

    if config.has_section('global'):
        qubes.qmemman.algo.MIN_PREFMEM = \
            qubes.utils.parse_size(config.get('global', 'vm-min-mem'))
        qubes.qmemman.algo.DOM0_MEM_BOOST = \
            qubes.utils.parse_size(config.get('global', 'dom0-mem-boost'))
        qubes.qmemman.algo.CACHE_FACTOR = \
            config.getfloat('global', 'cache-margin-factor')

    log.info('MIN_PREFMEM={algo.MIN_PREFMEM}'
        ' DOM0_MEM_BOOST={algo.DOM0_MEM_BOOST}'
        ' CACHE_FACTOR={algo.CACHE_FACTOR}'.format(
            algo=qubes.qmemman.algo))

    try:
        os.unlink(SOCK_PATH)
    except:
        pass

    log.debug('instantiating server')
    os.umask(0)
    server = socketserver.UnixStreamServer(SOCK_PATH, QMemmanReqHandler)
    os.umask(0o077)

    # notify systemd
    nofity_socket = os.getenv('NOTIFY_SOCKET')
    if nofity_socket:
        log.debug('notifying systemd')
        s = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        if nofity_socket.startswith('@'):
            nofity_socket = '\0%s' % nofity_socket[1:]
        s.connect(nofity_socket)
        s.sendall(b"READY=1")
        s.close()

    threading.Thread(target=server.serve_forever).start()
    XS_Watcher().watch_loop()
