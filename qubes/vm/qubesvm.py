#!/usr/bin/python2 -O

import qubes
import qubes.vm

class QubesVM(qubes.vm.BaseVM):
    '''Base functionality of Qubes VM shared between all VMs.'''

    label = qubes.property('label',
        setter=(lambda self, prop, value: self.app.labels[int(value.rsplit('-', 1)[1])]),
        doc='Colourful label assigned to VM. This is where you set the colour of the padlock.')

    netvm = qubes.property('netvm', load_stage=4,
        default=(lambda self: self.app.default_fw_netvm if self.provides_network
            else self.app.default_fw_netvm),
        doc='VM that provides network connection to this domain. '
            'When :py:obj:`False`, machine is disconnected. '
            'When :py:obj:`None` (or absent), domain uses default NetVM.')

    provides_network = qubes.property('provides_network',
        type=bool,
        doc=':py:obj:`True` if it is NetVM or ProxyVM, false otherwise')
