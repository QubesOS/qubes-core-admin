#
# The Qubes OS Project, http://www.qubes-os.org
#
# Copyright (C) 2014-2016  Wojtek Porczyk <woju@invisiblethingslab.com>
# Copyright (C) 2016       Marek Marczykowski <marmarek@invisiblethingslab.com>)
# Copyright (C) 2016       Bahtiar `kalkin-` Gadimov <bahtiar@gadimov.de>
#
# This library is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 2.1 of the License, or (at your option) any later version.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with this library; if not, see <https://www.gnu.org/licenses/>.
#

''' This module contains the TemplateVM implementation '''

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
                'snap_on_start': False,
                'save_on_stop': True,
                'rw': True,
                'source': None,
                'size': defaults['root_img_size'],
            },
            'private': {
                'name': 'private',
                'snap_on_start': False,
                'save_on_stop': True,
                'rw': True,
                'source': None,
                'size': defaults['private_img_size'],
                'revisions_to_keep': 0,
            },
            'volatile': {
                'name': 'volatile',
                'size': defaults['root_img_size'],
                'snap_on_start': False,
                'save_on_stop': False,
                'rw': True,
            },
            'kernel': {
                'name': 'kernel',
                'snap_on_start': False,
                'save_on_stop': False,
                'rw': False
            }
        }
        super(TemplateVM, self).__init__(*args, **kwargs)

    @qubes.events.handler('property-set:default_user',
                          'property-set:kernel',
                          'property-set:kernelopts',
                          'property-set:vcpus',
                          'property-set:memory',
                          'property-set:maxmem',
                          'property-set:qrexec_timeout',
                          'property-set:shutdown_timeout',
                          'property-set:management_dispvm')
    def on_property_set_child(self, _event, name, newvalue, oldvalue=None):
        """Send event about default value change to child VMs
           (which use default inherited from the template).

           This handler is supposed to be set for properties using
           `_default_with_template()` function for the default value.
           """
        if newvalue == oldvalue:
            return

        for vm in self.appvms:
            if not vm.property_is_default(name):
                continue
            vm.fire_event('property-reset:' + name, name=name)
