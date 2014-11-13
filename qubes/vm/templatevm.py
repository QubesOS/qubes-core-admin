#!/usr/bin/python2 -O

import qubes.vm.qubesvm

class TemplateVM(qubes.vm.qubesvm.QubesVM):
    '''Template for AppVM'''
    def __init__(self, D):
        super(TemplateVM, self).__init__(D)
