#!/usr/bin/python2 -O

import qubes.vm.qubesvm

class AppVM(qubes.vm.qubesvm.QubesVM):
    def __init__(self, D):
        super(AppVM, self).__init__(D)
