#!/usr/bin/python2 -O

import qubes
import qubes.vm.qubesvm

class TemplateVM(qubes.vm.qubesvm.QubesVM):
    '''Template for AppVM'''

    def __init__(self, D):
        super(TemplateVM, self).__init__(D)

        # Some additional checks for template based VM
        assert self.root_img is not None, "Missing root_img for standalone VM!"
