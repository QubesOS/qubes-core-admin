#!/usr/bin/python2 -O
# vim: fileencoding=utf-8

import qubes.vm.qubesvm

class AppVM(qubes.vm.qubesvm.QubesVM):
    '''Application VM'''

    template = qubes.VMProperty('template', load_stage=4,
        vmclass=qubes.vm.templatevm.TemplateVM,
        doc='Template, on which this AppVM is based.')

    def __init__(self, D):
        super(AppVM, self).__init__(D)

        # Some additional checks for template based VM
        assert self.template
        self.template.appvms.add(self)
