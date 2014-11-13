#!/usr/bin/python2 -O

import qubes.vm.hvm

class TemplateHVM(qubes.vm.hvm.HVM):
    def __init__(self, D):
        super(TemplateHVM, self).__init__(D)
