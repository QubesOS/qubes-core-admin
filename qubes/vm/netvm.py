#!/usr/bin/python2 -O

import qubes.vm.qubesvm

class NetVM(qubes.vm.qubesvm.QubesVM):
    def __init__(self, D):
        super(NetVM, self).__init__(D)
