#!/usr/bin/python2 -O

import qubes.vm.qubesvm

class DispVM(qubes.vm.qubesvm.QubesVM):
    '''Disposable VM'''
    def __init__(self, D):
        super(DispVM, self).__init__(D)
