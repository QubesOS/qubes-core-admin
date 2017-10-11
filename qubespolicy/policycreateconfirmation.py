# -*- encoding: utf-8 -*-
#
# The Qubes OS Project, http://www.qubes-os.org
#
# Copyright (C) 2017 Marek Marczykowski-Górecki
#                               <marmarek@invisiblethingslab.com>
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

import os

import pkg_resources

# pylint: disable=import-error,wrong-import-position
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk
# pylint: enable=import-error

class PolicyCreateConfirmationWindow(object):
    # pylint: disable=too-few-public-methods
    _source_file = pkg_resources.resource_filename('qubespolicy',
        os.path.join('glade', "PolicyCreateConfirmationWindow.glade"))
    _source_id = {'window': "PolicyCreateConfirmationWindow",
                  'ok': "okButton",
                  'cancel': "cancelButton",
                  'source': "sourceEntry",
                  'service': "serviceEntry",
                  'confirm': "confirmEntry",
                  }

    def __init__(self, source, service):
        self._gtk_builder = Gtk.Builder()
        self._gtk_builder.add_from_file(self._source_file)
        self._window = self._gtk_builder.get_object(
            self._source_id['window'])
        self._rpc_ok_button = self._gtk_builder.get_object(
            self._source_id['ok'])
        self._rpc_cancel_button = self._gtk_builder.get_object(
            self._source_id['cancel'])
        self._service_entry = self._gtk_builder.get_object(
            self._source_id['service'])
        self._source_entry = self._gtk_builder.get_object(
            self._source_id['source'])
        self._confirm_entry = self._gtk_builder.get_object(
            self._source_id['confirm'])

        self._source_entry.set_text(source)
        self._service_entry.set_text(service)

        # make OK button the default
        ok_button = self._window.get_widget_for_response(Gtk.ResponseType.OK)
        ok_button.set_can_default(True)
        ok_button.grab_default()

    def run(self):
        self._window.set_keep_above(True)
        self._window.connect("delete-event", Gtk.main_quit)
        self._window.show_all()

        response = self._window.run()

        self._window.hide()
        if response == Gtk.ResponseType.OK:
            return self._confirm_entry.get_text() == 'YES'
        return False

def confirm(source, service):
    window = PolicyCreateConfirmationWindow(source, service)

    return window.run()
