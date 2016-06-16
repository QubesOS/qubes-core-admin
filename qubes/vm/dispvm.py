#!/usr/bin/python2 -O
# vim: fileencoding=utf-8
#
# The Qubes OS Project, http://www.qubes-os.org
#
# Copyright (C) 2014-2016  Wojtek Porczyk <woju@invisiblethingslab.com>
# Copyright (C) 2016       Marek Marczykowski <marmarek@invisiblethingslab.com>)
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
#

''' A disposable vm implementation '''

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
        ''' When domain is loaded assert that this vm has a template.
        '''  # pylint: disable=unused-argument
        assert self.template

    @classmethod
    def from_appvm(cls, appvm, **kwargs):
        '''Create a new instance from given AppVM

        :param qubes.vm.appvm.AppVM appvm: template from which the VM should \
            be created (could also be name or qid)
        :returns: new disposable vm

        *kwargs* are passed to the newly created VM

        >>> import qubes.vm.dispvm.DispVM
        >>> dispvm = qubes.vm.dispvm.DispVM.from_appvm(appvm).start()
        >>> dispvm.run_service('qubes.VMShell', input='firefox')
        >>> dispvm.cleanup()

        This method modifies :file:`qubes.xml` file. In fact, the newly created
        vm belongs to other :py:class:`qubes.Qubes` instance than the *app*.
        The qube returned is not started.
        '''
        store = appvm.app.store if isinstance(appvm, qubes.vm.BaseVM) else None
        app = qubes.Qubes(store)
        dispvm = app.add_new_vm(
            cls,
            dispid=app.domains.get_new_unused_dispid(),
            template=app.domains[appvm],
            **kwargs)
        dispvm.create_on_disk()
        app.save()
        return dispvm

    def cleanup(self):
        '''Clean up after the DispVM

        This stops the disposable qube and removes it from the store.

        This method modifies :file:`qubes.xml` file.
        '''
        app = qubes.Qubes(self.app.store)
        self = app.domains[self.uuid]
        self.force_shutdown()
        self.remove_from_disk()
        del app.domains[self]
        app.save()
