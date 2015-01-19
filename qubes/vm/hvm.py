#!/usr/bin/python2 -O
# vim: fileencoding=utf-8

import qubes.vm.qubesvm

class HVM(qubes.vm.qubesvm.QubesVM):
    '''HVM'''
    def __init__(self, D):
        super(HVM, self).__init__(D)
