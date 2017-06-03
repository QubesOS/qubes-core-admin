#
# The Qubes OS Project, http://www.qubes-os.org
#
# Copyright (C) 2014-2016  Wojtek Porczyk <woju@invisiblethingslab.com>
# Copyright (C) 2016       Marek Marczykowski <marmarek@invisiblethingslab.com>)
# Copyright (C) 2016       Bahtiar `kalkin-` Gadimov <bahtiar@gadimov.de>
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
''' This module contains the AppVM implementation '''

import copy

import qubes.events
import qubes.vm.qubesvm
from qubes.config import defaults


class AppVM(qubes.vm.qubesvm.QubesVM):
    '''Application VM'''

    template = qubes.VMProperty('template',
                                load_stage=4,
                                vmclass=qubes.vm.templatevm.TemplateVM,
                                doc='Template, on which this AppVM is based.')

    dispvm_allowed = qubes.property('dispvm_allowed',
        type=bool,
        default=False,
        doc='Should this VM be allowed to start as Disposable VM'
    )

    def __init__(self, app, xml, template=None, **kwargs):
        self.volume_config = {
            'root': {
                'name': 'root',
                'pool': 'default',
                'snap_on_start': True,
                'save_on_stop': False,
                'rw': False,
                'internal': True
            },
            'private': {
                'name': 'private',
                'pool': 'default',
                'snap_on_start': False,
                'save_on_stop': True,
                'rw': True,
                'source': None,
                'size': defaults['private_img_size'],
                'internal': True
            },
            'volatile': {
                'name': 'volatile',
                'pool': 'default',
                'size': defaults['root_img_size'],
                'internal': True,
                'rw': True,
            },
            'kernel': {
                'name': 'kernel',
                'pool': 'linux-kernel',
                'snap_on_start': True,
                'rw': False,
                'internal': True
            }
        }

        if template is not None:
            # template is only passed if the AppVM is created, in other cases we
            # don't need to patch the volume_config because the config is
            # coming from XML, already as we need it

            for name, conf in self.volume_config.items():
                tpl_volume = template.volumes[name]

                self.config_volume_from_source(conf, tpl_volume)

            for name, config in template.volume_config.items():
                # in case the template vm has more volumes add them to own
                # config
                if name not in self.volume_config:
                    self.volume_config[name] = copy.deepcopy(config)
                    if 'vid' in self.volume_config[name]:
                        del self.volume_config[name]['vid']

        super(AppVM, self).__init__(app, xml, **kwargs)
        if not hasattr(self, 'template') and template is not None:
            self.template = template
        if 'source' not in self.volume_config['root']:
            msg = 'missing source for root volume'
            raise qubes.exc.QubesException(msg)

    @qubes.events.handler('domain-load')
    def on_domain_loaded(self, event):
        ''' When domain is loaded assert that this vm has a template.
        '''  # pylint: disable=unused-argument
        assert self.template
