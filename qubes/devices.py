#!/usr/bin/python2 -O
# vim: fileencoding=utf-8

#
# The Qubes OS Project, https://www.qubes-os.org/
#
# Copyright (C) 2010-2016  Joanna Rutkowska <joanna@invisiblethingslab.com>
# Copyright (C) 2015-2016  Wojtek Porczyk <woju@invisiblethingslab.com>
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

import re

import qubes.utils


class DeviceCollection(object):
    '''Bag for devices.

    Used as default value for :py:meth:`DeviceManager.__missing__` factory.

    :param vm: VM for which we manage devices
    :param class_: device class
    '''

    def __init__(self, vm, class_):
        self._vm = vm
        self._class = class_
        self._set = set()


    def attach(self, device):
        '''Attach (add) device to domain.

        :param str device: device identifier (format is class-dependent)
        '''

        try:
            devclass = qubes.utils.get_entry_point_one(
                'qubes.devices', self._class)
        except KeyError:
            devclass = str

        if not isinstance(device, devclass):
            device = devclass(device)

        if device in self:
            raise KeyError(
                'device {!r} of class {} already attached to {!r}'.format(
                    device, self._class, self._vm))
        self._vm.fire_event_pre('device-pre-attach:' + self._class, device)
        self._set.add(device)
        self._vm.fire_event('device-attach:' + self._class, device)


    def detach(self, device):
        '''Detach (remove) device from domain.

        :param str device: device identifier (format is class-dependent)
        '''

        if device not in self:
            raise KeyError(
                'device {!r} of class {} not attached to {!r}'.format(
                    device, self._class, self._vm))
        self._vm.fire_event_pre('device-pre-detach:' + self._class, device)
        self._set.remove(device)
        self._vm.fire_event('device-detach:' + self._class, device)


    def __iter__(self):
        return iter(self._set)


    def __contains__(self, item):
        return item in self._set


    def __len__(self):
        return len(self._set)


class DeviceManager(dict):
    '''Device manager that hold all devices by their classess.

    :param vm: VM for which we manage devices
    '''

    def __init__(self, vm):
        super(DeviceManager, self).__init__()
        self._vm = vm

    def __missing__(self, key):
        self[key] = DeviceCollection(self._vm, key)
        return self[key]


class RegexDevice(str):
    regex = None
    def __init__(self, *args, **kwargs):
        super(RegexDevice, self).__init__(*args, **kwargs)

        if self.regex is None:
            raise NotImplementedError(
                'You should overload .regex attribute in subclass')

        dev_match = self.regex.match(self)
        if not dev_match:
            raise ValueError('Invalid device identifier: {!r}'.format(self))

        for group in self.regex.groupindex:
            setattr(self, group, dev_match.group(group))


class PCIDevice(RegexDevice):
    regex = re.compile(
        r'^(?P<bus>[0-9a-f]+):(?P<device>[0-9a-f]+)\.(?P<function>[0-9a-f]+)$')

    @property
    def libvirt_name(self):
        return 'pci_0000_{}_{}_{}'.format(self.bus, self.device, self.function)


class BlockDevice(object):
    # pylint: disable=too-few-public-methods
    def __init__(self, path, name, script=None, rw=True, domain=None,
                 devtype='disk'):
        assert name, 'Missing device name'
        assert path, 'Missing device path'
        self.path = path
        self.name = name
        self.rw = rw
        self.script = script
        self.domain = domain
        self.devtype = devtype
