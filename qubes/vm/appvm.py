#!/usr/bin/python2 -O

import qubes.vm.qubesvm

class AppVM(qubes.vm.qubesvm.QubesVM):
    '''Application VM'''
    def __init__(self, D):
        super(AppVM, self).__init__(D)
