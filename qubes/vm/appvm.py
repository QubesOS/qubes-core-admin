#!/usr/bin/python2 -O
# vim: fileencoding=utf-8
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

import qubes.events
import qubes.vm.qubesvm

from qubes.config import defaults


class AppVM(qubes.vm.qubesvm.QubesVM):
    '''Application VM'''

    template = qubes.VMProperty('template',
                                load_stage=4,
                                vmclass=qubes.vm.templatevm.TemplateVM,
                                ls_width=31,
                                doc='Template, on which this AppVM is based.')

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
                'volume_type': 'origin',
                'size': defaults['private_img_size'],
            },
            'volatile': {
                'name': 'volatile',
                'pool': 'default',
                'volume_type': 'volatile',
                'size': defaults['root_img_size'],
            },
            'kernel': {
                'name': 'kernel',
                'pool': 'linux-kernel',
                'volume_type': 'read-only',
            }
        }
        super(AppVM, self).__init__(*args, **kwargs)

    @qubes.events.handler('domain-load')
    def on_domain_loaded(self, event):
        ''' When domain is loaded assert that this vm has a template.
        '''  # pylint: disable=unused-argument
        assert self.template
