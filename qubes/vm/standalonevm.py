#
# The Qubes OS Project, https://www.qubes-os.org/
#
# Copyright (C) 2016  Marek Marczykowski-Górecki
#                              <marmarek@invisiblethingslab.com>
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

import qubes.events
import qubes.vm.mix.dvmtemplate
import qubes.vm.qubesvm
import qubes.config

class StandaloneVM(qubes.vm.mix.dvmtemplate.DVMTemplateMixin,
        qubes.vm.qubesvm.QubesVM):
    '''Standalone Application VM'''

    def __init__(self, *args, **kwargs):
        self.volume_config = {
            'root': {
                'name': 'root',
                'snap_on_start': False,
                'save_on_stop': True,
                'rw': True,
                'source': None,
                'size': qubes.config.defaults['root_img_size'],
            },
            'private': {
                'name': 'private',
                'snap_on_start': False,
                'save_on_stop': True,
                'rw': True,
                'source': None,
                'size': qubes.config.defaults['private_img_size'],
            },
            'volatile': {
                'name': 'volatile',
                'snap_on_start': False,
                'save_on_stop': False,
                'rw': True,
                'size': qubes.config.defaults['root_img_size'],
            },
            'kernel': {
                'name': 'kernel',
                'snap_on_start': False,
                'save_on_stop': False,
                'rw': False,
            }
        }
        super().__init__(*args, **kwargs)
