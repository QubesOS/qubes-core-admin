#!/usr/bin/env python2
# -*- encoding: utf8 -*-
#
# The Qubes OS Project, http://www.qubes-os.org
#
# Copyright (C) 2016 Bahtiar `kalkin-` Gadimov <bahtiar@gadimov.de>
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
''' Manages block devices in a domain '''

from qubes.storage import Pool, Volume


class DomainPool(Pool):
    ''' This pool manages all the block devices of a domain.

        The devices are queried through :py:module:`qubesdb`
    '''

    driver = 'domain'

    def __init__(self, vm):
        self.vm = vm
        super(DomainPool, self).__init__(name='p_' + vm.name)

    @property
    def volumes(self):
        ''' Queries qubesdb and returns volumes for `self.vm` '''

        qdb = self.vm.qdb
        if not self.vm.is_running():
            return []
        untrusted_qubes_devices = qdb.list('/qubes-block-devices/')
        # because we get each path 3 x times as
        # /qubes-block-devices/foo/{desc,mode,size} we need to merge this
        untrusted_devices = {}
        for untrusted_device_path in untrusted_qubes_devices:
            _, _, untrusted_name, untrusted_atr = untrusted_device_path.split(
                '/', 4)
            if untrusted_name not in untrusted_devices.keys():
                untrusted_devices[untrusted_name] = {
                    untrusted_atr: qdb.read(untrusted_device_path)
                }
            else:
                untrusted_devices[untrusted_name][untrusted_atr] = qdb.read(
                    untrusted_device_path)

        return [DomainVolume(untrusted_n, self.name, **untrusted_atrs)
                for untrusted_n, untrusted_atrs in untrusted_devices.items()]

    def clone(self, source, target):
        raise NotImplementedError


class DomainVolume(Volume):
    ''' A volume provided by a block device in an domain '''

    def __init__(self, name, pool, desc, mode, size):
        if mode == 'w':
            volume_type = 'read-write'
        else:
            volume_type = 'read-only'

        super(DomainVolume, self).__init__(desc,
                                           pool,
                                           volume_type,
                                           vid=name,
                                           size=size,
                                           removable=True)
