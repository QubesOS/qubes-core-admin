# -*- encoding: utf8 -*-
#
# The Qubes OS Project, http://www.qubes-os.org
#
# Copyright (C) 2017 Wojtek Porczyk <woju@invisiblethingslab.com>
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
# with this program; if not, see <http://www.gnu.org/licenses/>.

import qubes.api
import qubes.ext

class AdminExtension(qubes.ext.Extension):
    # pylint: disable=too-few-public-methods
    @qubes.ext.handler(
        'mgmt-permission:admin.vm.tag.Set',
        'mgmt-permission:admin.vm.tag.Remove')
    def on_tag_set_or_remove(self, vm, event, arg, **kwargs):
        '''Forbid changing specific tags'''
        # pylint: disable=no-self-use,unused-argument
        if arg.startswith('created-by-'):
            raise qubes.api.PermissionDenied(
                'changing this tag is prohibited by {}.{}'.format(
                    __name__, type(self).__name__))

    # TODO create that tag here (need to figure out how to pass mgmtvm name)
