#
# The Qubes OS Project, https://www.qubes-os.org/
#
# Copyright (C) 2014-2015  Joanna Rutkowska <joanna@invisiblethingslab.com>
# Copyright (C) 2014       Marek Marczykowski-Górecki
#                               <marmarek@invisiblethingslab.com>
# Copyright (C) 2015       Wojtek Porczyk <woju@invisiblethingslab.com>
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

'''Qubes Manager hooks.

.. warning:: API defined here is not declared stable.
'''

import dbus
import qubes.ext


class QubesManager(qubes.ext.Extension):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        try:
            self._system_bus = dbus.SystemBus()
        except dbus.exceptions.DBusException:
            # we can't access Qubes() object here to check for offline mode,
            # so lets assume it is this case...
            self._system_bus = None

    # pylint: disable=no-self-use,unused-argument,too-few-public-methods

    @qubes.ext.handler('status:error')
    def on_status_error(self, vm, event, status, message):
        if self._system_bus is None:
            return
        try:
            qubes_manager = self._system_bus.get_object(
                'org.qubesos.QubesManager',
                '/org/qubesos/QubesManager')
            qubes_manager.notify_error(vm.name, message,
                dbus_interface='org.qubesos.QubesManager')
        except dbus.DBusException:
            # ignore the case when no qubes-manager is running
            pass

    @qubes.ext.handler('status:no-error')
    def on_status_no_error(self, vm, event, status, message):
        if self._system_bus is None:
            return
        try:
            qubes_manager = self._system_bus.get_object(
                'org.qubesos.QubesManager',
                '/org/qubesos/QubesManager')
            qubes_manager.clear_error_exact(vm.name, message,
                dbus_interface='org.qubesos.QubesManager')
        except dbus.DBusException:
            # ignore the case when no qubes-manager is running
            pass
