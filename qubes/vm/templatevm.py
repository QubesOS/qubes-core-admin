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

''' This module contains the TemplateVM implementation '''

import warnings

import qubes
import qubes.config
import qubes.vm.qubesvm
import qubes.vm.mix.net
from qubes.config import defaults
from qubes.vm.qubesvm import QubesVM


class TemplateVM(QubesVM):
    '''Template for AppVM'''

    dir_path_prefix = qubes.config.system_path['qubes_templates_dir']

    @property
    def rootcow_img(self):
        '''COW image'''
        warnings.warn("rootcow_img is deprecated, use "
                      "volumes['root'].path_origin", DeprecationWarning)
        return self.volumes['root'].path_cow

    @property
    def appvms(self):
        ''' Returns a generator containing all domains based on the current
            TemplateVM.
        '''
        for vm in self.app.domains:
            if hasattr(vm, 'template') and vm.template is self:
                yield vm

    netvm = qubes.VMProperty('netvm', load_stage=4, allow_none=True,
        default=None,
        # pylint: disable=protected-access
        setter=qubes.vm.qubesvm.QubesVM.netvm._setter,
        doc='VM that provides network connection to this domain. When '
            '`None`, machine is disconnected.')

    def __init__(self, *args, **kwargs):
        assert 'template' not in kwargs, "A TemplateVM can not have a template"
        self.volume_config = {
            'root': {
                'name': 'root',
                'pool': 'default',
                'snap_on_start': False,
                'save_on_stop': True,
                'rw': True,
                'source': None,
                'size': defaults['root_img_size'],
            },
            'private': {
                'name': 'private',
                'pool': 'default',
                'snap_on_start': False,
                'save_on_stop': True,
                'rw': True,
                'source': None,
                'size': defaults['private_img_size'],
                'revisions_to_keep': 0,
            },
            'volatile': {
                'name': 'volatile',
                'pool': 'default',
                'size': defaults['root_img_size'],
                'snap_on_start': False,
                'save_on_stop': False,
                'rw': True,
            },
            'kernel': {
                'name': 'kernel',
                'pool': 'linux-kernel',
                'snap_on_start': False,
                'save_on_stop': False,
                'rw': False
            }
        }
        super(TemplateVM, self).__init__(*args, **kwargs)
