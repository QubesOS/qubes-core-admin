#!/usr/bin/python2 -O

import qubes.vm.qubesvm

class HVM(qubes.vm.qubesvm.QubesVM):
    def __init__(self, D):
        super(HVM, self).__init__(D)
