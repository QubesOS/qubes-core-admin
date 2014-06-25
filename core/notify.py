# -*- coding: utf-8 -*-
#
# The Qubes OS Project, http://www.qubes-os.org
#
# Copyright (C) 2014 Marek Marczykowski-Górecki <marmarek@invisiblethingslab.com>
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.
#
#

import sys

system_bus = None
session_bus = None

notify_object = None

def tray_notify_init():
    import dbus
    global notify_object
    try:
        notify_object = dbus.SessionBus().get_object("org.freedesktop.Notifications", "/org/freedesktop/Notifications")
    except dbus.DBusException as ex:
        print >>sys.stderr, "WARNING: failed connect to tray notification service: %s" % str(ex)

def tray_notify(msg, label, timeout = 3000):
    if notify_object:
        if label:
            if not isinstance(label, str):
                label = label.icon
        notify_object.Notify("Qubes", 0, label, "Qubes", msg, [], [], timeout,
                             dbus_interface="org.freedesktop.Notifications")

def tray_notify_error(msg, timeout = 3000):
    if notify_object:
        notify_object.Notify("Qubes", 0, "dialog-error", "Qubes", msg, [], [],
                             timeout, dbus_interface="org.freedesktop.Notifications")

def notify_error_qubes_manager(name, message):
    import dbus
    global system_bus
    if system_bus is None:
        system_bus = dbus.SystemBus()

    try:
        qubes_manager = system_bus.get_object('org.qubesos.QubesManager',
                '/org/qubesos/QubesManager')
        qubes_manager.notify_error(name, message, dbus_interface='org.qubesos.QubesManager')
    except dbus.DBusException:
        # ignore the case when no qubes-manager is running
        pass

def clear_error_qubes_manager(name, message):
    import dbus
    global system_bus
    if system_bus is None:
        system_bus = dbus.SystemBus()

    try:
        qubes_manager = system_bus.get_object('org.qubesos.QubesManager',
                '/org/qubesos/QubesManager')
        qubes_manager.clear_error_exact(name, message, dbus_interface='org.qubesos.QubesManager')
    except dbus.DBusException:
        # ignore the case when no qubes-manager is running
        pass

