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

import string  # pylint: disable=deprecated-module

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
        safe_set = set(string.letters + string.digits + string.punctuation)
        allowed_attributes = {'desc': string.printable,
                              'mode': string.letters,
                              'size': string.digits}
        if not self.vm.is_running():
            return []
        untrusted_qubes_devices = qdb.list('/qubes-block-devices/')
        # because we get each path 3 x times as
        # /qubes-block-devices/foo/{desc,mode,size} we need to merge this
        devices = {}
        for untrusted_device_path in untrusted_qubes_devices:
            if not all(c in safe_set for c in untrusted_device_path):
                msg = ("%s vm's device path name contains unsafe characters. "
                       "Skipping it.")
                self.vm.log.warning(msg % self.vm.name)
                continue

            # name can be trusted because it was checked as a part of
            # untrusted_device_path check above
            _, _, name, untrusted_atr = untrusted_device_path.split('/', 4)

            if untrusted_atr in allowed_attributes.keys():
                atr = untrusted_atr
            else:
                msg = ('{!s} has an unknown qubes-block-device atr {!s} '
                       'Skipping it')
                self.vm.log.error(msg.format(self.vm.name, untrusted_atr))
                continue

            untrusted_value = qdb.read(untrusted_device_path)
            allowed_characters = allowed_attributes[atr]
            if all(c in allowed_characters for c in untrusted_value):
                value = untrusted_value
            else:
                msg = ("{!s} vm's device path {!s} contains unsafe characters")
                self.vm.log.error(msg.format(self.vm.name, atr))
                continue

            if name not in devices.keys():
                devices[name] = {}

            devices[name][atr] = value

        return [DomainVolume(n, self.vm, self.name, **atrs)
                for n, atrs in devices.items()]

    def clone(self, source, target):
        raise NotImplementedError

    def __xml__(self):
        return None


class DomainVolume(Volume):
    ''' A volume provided by a block device in an domain '''

    def __init__(self, vm, name, pool, desc, mode, **kwargs):
        rw = (mode == 'w')

        super(DomainVolume, self).__init__(desc, pool, vid=name, removable=True,
                                           rw=rw, **kwargs)
        self.domain = vm

    @property
    def revisions(self):
        return {}
