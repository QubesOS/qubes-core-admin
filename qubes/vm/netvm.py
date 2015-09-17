#!/usr/bin/python2 -O
# vim: fileencoding=utf-8

import qubes.vm.qubesvm

class NetVM(qubes.vm.appvm.AppVM):
    '''Network interface VM'''

    netvm = qubes.property('netvm', setter=qubes.property.forbidden)

    def __init__(self, *args, **kwargs):
        super(NetVM, self).__init__(*args, **kwargs)

    def get_ip_for_vm(self, vm):
        return '10.137.{}.{}'.format(self.qid, vm.qid + 2)

    @property
    def gateway(self):
        return '10.137.{}.1'.format(self.qid)

    @property
    def secondary_dns(self):
        return '10.137.{}.254'.format(self.qid)

#   @property
#   def netmask(self):
#       return '255.255.255.0'
#
#   @property
#   def provides_network(self):
#       return True

    netmask = '255.255.255.0'
    provides_network = True
