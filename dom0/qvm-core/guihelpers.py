#!/usr/bin/python2
#
# The Qubes OS Project, http://www.qubes-os.org
#
# Copyright (C) 2011  Marek Marczykowski <marmarek@invisiblethingslab.com>
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
from optparse import OptionParser
from PyQt4.QtCore import *
from PyQt4.QtGui import *
import dbus
from dbus import DBusException

app = None
system_bus = None

def prepare_app():
    global app
    app  = QApplication(sys.argv)
    app.setOrganizationName("The Qubes Project")
    app.setOrganizationDomain("http://qubes-os.org")
    app.setApplicationName("Qubes")

def ask(text, title="Question", yestoall=False):
    global app
    if app is None:
        prepare_app()

    buttons = QMessageBox.Yes | QMessageBox.No
    if yestoall:
        buttons |= QMessageBox.YesToAll

    reply = QMessageBox.question(None, title, text, buttons)
    if reply == QMessageBox.Yes:
        return 0
    elif reply == QMessageBox.No:
        return 1
    elif reply == QMessageBox.YesToAll:
        return 2
    else:
        #?!
        return 127

def notify_error_qubes_manager(name, message):
    global system_bus
    if system_bus is None:
        system_bus = dbus.SystemBus()

    try:
        qubes_manager = system_bus.get_object('org.qubesos.QubesManager',
                '/org/qubesos/QubesManager')
        qubes_manager.notify_error(name, message, dbus_interface='org.qubesos.QubesManager')
    except DBusException:
        # ignore the case when no qubes-manager is running
        pass

def clear_error_qubes_manager(name, message):
    global system_bus
    if system_bus is None:
        system_bus = dbus.SystemBus()

    try:
        qubes_manager = system_bus.get_object('org.qubesos.QubesManager',
                '/org/qubesos/QubesManager')
        qubes_manager.clear_error_exact(name, message, dbus_interface='org.qubesos.QubesManager')
    except DBusException:
        # ignore the case when no qubes-manager is running
        pass
