#!/usr/bin/python2 -O

import qubes.vm.qubesvm

class NetVM(qubes.vm.qubesvm.QubesVM):
    '''Network interface VM'''
    def __init__(self, D):
        super(NetVM, self).__init__(D)
