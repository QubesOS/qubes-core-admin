#!/usr/bin/python2 -O

import qubes.vm

class QubesVM(qubes.vm.BaseVM):
    def __init__(self, D):
        super(QubesVM, self).__init__(D)
