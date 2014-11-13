#!/usr/bin/python2 -O

import qubes.vm.netvm

class ProxyVM(qubes.vm.netvm.NetVM):
    '''Proxy (firewall/VPN) VM'''
    def __init__(self, D):
        super(ProxyVM, self).__init__(D)
