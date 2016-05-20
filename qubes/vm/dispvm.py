#!/usr/bin/python2 -O
# vim: fileencoding=utf-8

import qubes.vm.qubesvm
import qubes.vm.appvm
import qubes.config

class DispVM(qubes.vm.qubesvm.QubesVM):
    '''Disposable VM'''

    template = qubes.VMProperty('template',
                                load_stage=4,
                                vmclass=qubes.vm.appvm.AppVM,
                                ls_width=31,
                                doc='AppVM, on which this DispVM is based.')

    dispid = qubes.property('dispid', type=int, write_once=True,
        clone=False,
        ls_width=3,
        doc='''Internal, persistent identifier of particular DispVM.''')

    def __init__(self, *args, **kwargs):
        self.volumes = {}
        self.volume_config = {
            'root': {
                'name': 'root',
                'pool': 'default',
                'volume_type': 'snapshot',
            },
            'private': {
                'name': 'private',
                'pool': 'default',
                'volume_type': 'snapshot',
            },
            'volatile': {
                'name': 'volatile',
                'pool': 'default',
                'volume_type': 'volatile',
                'size': qubes.config.defaults['root_img_size'] +
                        qubes.config.defaults['private_img_size'],
            },
            'kernel': {
                'name': 'kernel',
                'pool': 'linux-kernel',
                'volume_type': 'read-only',
            }
        }
        super(DispVM, self).__init__(*args, **kwargs)

    @qubes.events.handler('domain-load')
    def on_domain_loaded(self, event):
        # pylint: disable=unused-argument
        # Some additional checks for template based VM
        assert self.template
        # self.template.appvms.add(self) # XXX
