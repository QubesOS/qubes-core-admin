#!/usr/bin/python2 -O
# vim: fileencoding=utf-8

import qubes.vm.hvm

class TemplateHVM(qubes.vm.hvm.HVM):
    '''Template for HVM'''
    def __init__(self, D):
        super(TemplateHVM, self).__init__(D)
