#!/usr/bin/python2 -O
# vim: fileencoding=utf-8

import qubes.vm.netvm

class ProxyVM(qubes.vm.netvm.NetVM):
    '''Proxy (firewall/VPN) VM'''
    def __init__(self, D):
        super(ProxyVM, self).__init__(D)
