#!/usr/bin/python2 -O

import qubes
import qubes.vm.qubesvm

class TemplateVM(qubes.vm.qubesvm.QubesVM):
    '''Template for AppVM'''

    template = qubes.property('template',
        setter=qubes.property.forbidden)

    def __init__(self, D):
        super(TemplateVM, self).__init__(D)
