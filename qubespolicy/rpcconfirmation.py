#!/usr/bin/python
#
# The Qubes OS Project, https://www.qubes-os.org/
#
# Copyright (C) 2017 boring-stuff <boring-stuff@users.noreply.github.com>
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
import os
from gi.repository import Gtk, Gdk, GLib  # pylint: disable=import-error
import pkg_resources

from qubespolicy.gtkhelpers import VMListModeler, FocusStealingHelper
from qubespolicy.utils import sanitize_domain_name, \
    sanitize_service_name


class RPCConfirmationWindow:
    # pylint: disable=too-few-public-methods
    _source_file = pkg_resources.resource_filename('qubespolicy',
        os.path.join('glade', "RPCConfirmationWindow.glade"))
    _source_id = {'window': "RPCConfirmationWindow",
                  'ok': "okButton",
                  'cancel': "cancelButton",
                  'source': "sourceEntry",
                  'rpc_label': "rpcLabel",
                  'target': "TargetCombo",
                  'error_bar': "ErrorBar",
                  'error_message': "ErrorMessage",
                  }

    def _clicked_ok(self, source):
        assert source is not None, \
               'Called the clicked ok callback from no source object'

        if self._can_perform_action():
            self._confirmed = True
            self._close()

    def _clicked_cancel(self, button):
        assert button == self._rpc_cancel_button, \
               'Called the clicked cancel callback through the wrong button'

        if self._can_perform_action():
            self._confirmed = False
            self._close()

    def _key_pressed(self, window, key):
        assert window == self._rpc_window, \
               'Key pressed callback called with wrong window'

        if self._can_perform_action():
            if key.keyval == Gdk.KEY_Escape:
                self._confirmed = False
                self._close()

    def _update_ok_button_sensitivity(self, data):
        valid = (data is not None)

        if valid:
            self._target_name = data
        else:
            self._target_name = None

        self._focus_helper.request_sensitivity(valid)

    def _show_error(self, error_message):
        self._error_message.set_text(error_message)
        self._error_bar.set_visible(True)

    def _close_error(self, error_bar, response):
        assert error_bar == self._error_bar, \
               'Closed the error bar with the wrong error bar as parameter'
        assert response is not None, \
            'Closed the error bar with None as a response'

        self._error_bar.set_visible(False)

    def _set_initial_target(self, source, target):
        if target is not None:
            if target == source:
                self._show_error(
                     "Source and target domains must not be the same.")
            else:
                model = self._rpc_combo_box.get_model()

                found = False
                for item in model:
                    if item[3] == target:
                        found = True

                        self._rpc_combo_box.set_active_iter(
                                    model.get_iter(item.path))

                        break

                if not found:
                    self._show_error("Domain '%s' doesn't exist." % target)

    def _can_perform_action(self):
        return self._focus_helper.can_perform_action()

    @staticmethod
    def _escape_and_format_rpc_text(rpc_operation):
        escaped = GLib.markup_escape_text(rpc_operation)

        partitioned = escaped.partition('.')
        formatted = partitioned[0] + partitioned[1]

        if partitioned[2]:
            formatted += "<b>" + partitioned[2] + "</b>"
        else:
            formatted = "<b>" + formatted + "</b>"

        return formatted

    def _connect_events(self):
        self._rpc_window.connect("key-press-event", self._key_pressed)
        self._rpc_ok_button.connect("clicked", self._clicked_ok)
        self._rpc_cancel_button.connect("clicked", self._clicked_cancel)

        self._error_bar.connect("response", self._close_error)

    def __init__(self, entries_info, source, rpc_operation, targets_list,
            target=None):
        sanitize_domain_name(source, assert_sanitized=True)
        sanitize_service_name(source, assert_sanitized=True)

        self._gtk_builder = Gtk.Builder()
        self._gtk_builder.add_from_file(self._source_file)
        self._rpc_window = self._gtk_builder.get_object(
                                            self._source_id['window'])
        self._rpc_ok_button = self._gtk_builder.get_object(
                                            self._source_id['ok'])
        self._rpc_cancel_button = self._gtk_builder.get_object(
                                            self._source_id['cancel'])
        self._rpc_label = self._gtk_builder.get_object(
                                            self._source_id['rpc_label'])
        self._source_entry = self._gtk_builder.get_object(
                                            self._source_id['source'])
        self._rpc_combo_box = self._gtk_builder.get_object(
                                            self._source_id['target'])
        self._error_bar = self._gtk_builder.get_object(
                                            self._source_id['error_bar'])
        self._error_message = self._gtk_builder.get_object(
                                            self._source_id['error_message'])
        self._target_name = None

        self._focus_helper = self._new_focus_stealing_helper()

        self._rpc_label.set_markup(
                    self._escape_and_format_rpc_text(rpc_operation))

        self._entries_info = entries_info
        list_modeler = self._new_vm_list_modeler()

        list_modeler.apply_model(self._rpc_combo_box, targets_list,
                    selection_trigger=self._update_ok_button_sensitivity,
                    activation_trigger=self._clicked_ok)

        self._source_entry.set_text(source)
        list_modeler.apply_icon(self._source_entry, source)

        self._confirmed = None

        self._set_initial_target(source, target)

        self._connect_events()

    def _close(self):
        self._rpc_window.close()

    def _show(self):
        self._rpc_window.set_keep_above(True)
        self._rpc_window.connect("delete-event", Gtk.main_quit)
        self._rpc_window.show_all()

        Gtk.main()

    def _new_vm_list_modeler(self):
        return VMListModeler(self._entries_info)

    def _new_focus_stealing_helper(self):
        return FocusStealingHelper(
                    self._rpc_window,
                    self._rpc_ok_button,
                    1)

    def confirm_rpc(self):
        self._show()

        if self._confirmed:
            return self._target_name
        return False


def confirm_rpc(entries_info, source, rpc_operation, targets_list, target=None):
    window = RPCConfirmationWindow(entries_info, source, rpc_operation,
        targets_list, target)

    return window.confirm_rpc()
