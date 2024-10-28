#
# The Qubes OS Project, https://www.qubes-os.org/
#
# Copyright (C) 2014-2015  Joanna Rutkowska <joanna@invisiblethingslab.com>
# Copyright (C) 2014-2015  Wojtek Porczyk <woju@invisiblethingslab.com>
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

'''Qubes extensions.

Extensions provide additional features (like application menus) found only on
some systems. They may be OS- or architecture-dependent or custom-developed for
particular customer.
'''
import collections
import importlib.metadata
import qubes.events


class Extension:
    '''Base class for all extensions'''
    # pylint: disable=too-few-public-methods

    def __new__(cls):
        if '_instance' not in cls.__dict__:
            cls._instance = super(Extension, cls).__new__(cls)

            for name in cls.__dict__:
                attr = getattr(cls._instance, name)
                if not qubes.events.ishandler(attr):
                    continue

                if attr.ha_vm is not None:
                    for event in attr.ha_events:
                        attr.ha_vm.__handlers__[event].add(attr)
                else:
                    # global hook
                    for event in attr.ha_events:
                        # pylint: disable=no-member
                        qubes.Qubes.__handlers__[event].add(attr)

        return cls._instance

    def __init__(self):
        #: This is to be implemented in extension handling devices
        self.devices_cache = collections.defaultdict(dict)

    #: This is to be implemented in extension handling devices
    def ensure_detach(self, vm, port):
        pass

def get_extensions():
    return set(ext.load()()
        for ext in importlib.metadata.entry_points(group='qubes.ext'))


def handler(*events, **kwargs):
    '''Event handler decorator factory.

    To hook an event, decorate a method in your plugin class with this
    decorator. You may hook both per-vm-class and global events.

    .. note::
        This decorator is intended only for extensions! For regular use in the
        core, see :py:func:`qubes.events.handler`.

    :param str event: event type
    :param type vm: VM to hook (leave as None to hook all VMs)
    :param bool system: when :py:obj:`True`, hook is system-wide (not attached \
        to any VM)
    '''

    def decorator(func):
        func.ha_events = events

        if kwargs.get('system', False):
            func.ha_vm = None
        elif 'vm' in kwargs:
            func.ha_vm = kwargs['vm']
        else:
            func.ha_vm = qubes.vm.BaseVM

        return func

    return decorator
