#!/usr/bin/python2 -O
# vim: fileencoding=utf-8

#
# The Qubes OS Project, https://www.qubes-os.org/
#
# Copyright (C) 2016  Marek Marczykowski-Górecki
#                              <marmarek@invisiblethingslab.com>
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

import qubes.events
import qubes.vm.qubesvm
import qubes.config

class StandaloneVM(qubes.vm.qubesvm.QubesVM):
    '''Standalone Application VM'''

    def __init__(self, *args, **kwargs):
        self.volume_config = {
            'root': {
                'name': 'root',
                'pool': 'default',
                'volume_type': 'origin',
                'size': qubes.config.defaults['root_img_size'],
            },
            'private': {
                'name': 'private',
                'pool': 'default',
                'volume_type': 'origin',
                'size': qubes.config.defaults['private_img_size'],
            },
            'volatile': {
                'name': 'volatile',
                'pool': 'default',
                'volume_type': 'volatile',
                'size': qubes.config.defaults['root_img_size'],
            },
            'kernel': {
                'name': 'kernel',
                'pool': 'linux-kernel',
                'volume_type': 'read-only',
            }
        }
        super(StandaloneVM, self).__init__(*args, **kwargs)
