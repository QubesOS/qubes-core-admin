#!/usr/bin/python2 -O

import qubes.vm.netvm

class ProxyVM(qubes.vm.netvm.NetVM):
    def __init__(self, D):
        super(ProxyVM, self).__init__(D)
