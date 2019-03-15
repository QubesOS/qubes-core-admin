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

import itertools
# pylint: disable=import-error,wrong-import-position
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk, GdkPixbuf, GObject, GLib
# pylint: enable=import-error

from qubespolicy.utils import sanitize_domain_name
# pylint: enable=wrong-import-position

class VMListModeler:
    def __init__(self, domains_info=None):
        self._entries = {}
        self._domains_info = domains_info
        self._icons = {}
        self._icon_size = 16
        self._theme = Gtk.IconTheme.get_default()
        self._create_entries()

    def _get_icon(self, name):
        if name not in self._icons:
            try:
                icon = self._theme.load_icon(name, self._icon_size, 0)
            except GLib.Error:  # pylint: disable=catching-non-exception
                icon = self._theme.load_icon("edit-find", self._icon_size, 0)

            self._icons[name] = icon

        return self._icons[name]

    def _create_entries(self):
        for name, vm in self._domains_info.items():
            if name.startswith('@dispvm:'):
                vm_name = name[len('@dispvm:'):]
                dispvm = True
            else:
                vm_name = name
                dispvm = False
            sanitize_domain_name(vm_name, assert_sanitized=True)

            icon = self._get_icon(vm.get('icon', None))

            if dispvm:
                display_name = 'Disposable VM ({})'.format(vm_name)
            else:
                display_name = vm_name
            self._entries[display_name] = {
                                   'api_name': name,
                                   'icon': icon,
                                   'vm': vm}

    def _get_valid_qube_name(self, combo, entry_box, whitelist):
        name = None

        if combo and combo.get_active_id():
            selected = combo.get_active_id()

            if selected in self._entries and \
                    self._entries[selected]['api_name'] in whitelist:
                name = selected

        if not name and entry_box:
            typed = entry_box.get_text()

            if typed in self._entries and \
                    self._entries[typed]['api_name'] in whitelist:
                name = typed

        return name

    def _combo_change(self, selection_trigger, combo, entry_box, whitelist):
        data = None
        name = self._get_valid_qube_name(combo, entry_box, whitelist)

        if name:
            entry = self._entries[name]

            data = entry['api_name']

            if entry_box:
                entry_box.set_icon_from_pixbuf(
                    Gtk.EntryIconPosition.PRIMARY, entry['icon'])
        else:
            if entry_box:
                entry_box.set_icon_from_stock(
                    Gtk.EntryIconPosition.PRIMARY, "gtk-find")

        if selection_trigger:
            selection_trigger(data)

    def _entry_activate(self, activation_trigger, combo, entry_box, whitelist):
        name = self._get_valid_qube_name(combo, entry_box, whitelist)

        if name:
            activation_trigger(entry_box)

    def apply_model(self, destination_object, vm_list,
                    selection_trigger=None, activation_trigger=None):
        if isinstance(destination_object, Gtk.ComboBox):
            list_store = Gtk.ListStore(int, str, GdkPixbuf.Pixbuf, str)

            for entry_no, display_name in zip(itertools.count(),
                    sorted(self._entries)):
                entry = self._entries[display_name]
                if entry['api_name'] in vm_list:
                    list_store.append([
                        entry_no,
                        display_name,
                        entry['icon'],
                        entry['api_name'],
                    ])

            destination_object.set_model(list_store)
            destination_object.set_id_column(1)

            icon_column = Gtk.CellRendererPixbuf()
            destination_object.pack_start(icon_column, False)
            destination_object.add_attribute(icon_column, "pixbuf", 2)
            destination_object.set_entry_text_column(1)

            if destination_object.get_has_entry():
                entry_box = destination_object.get_child()

                area = Gtk.CellAreaBox()
                area.pack_start(icon_column, False, False, False)
                area.add_attribute(icon_column, "pixbuf", 2)

                completion = Gtk.EntryCompletion.new_with_area(area)
                completion.set_inline_selection(True)
                completion.set_inline_completion(True)
                completion.set_popup_completion(True)
                completion.set_popup_single_match(False)
                completion.set_model(list_store)
                completion.set_text_column(1)

                entry_box.set_completion(completion)
                if activation_trigger:
                    entry_box.connect("activate",
                        lambda entry: self._entry_activate(
                            activation_trigger,
                            destination_object,
                            entry,
                            vm_list))

                # A Combo with an entry has a text column already
                text_column = destination_object.get_cells()[0]
                destination_object.reorder(text_column, 1)
            else:
                entry_box = None

                text_column = Gtk.CellRendererText()
                destination_object.pack_start(text_column, False)
                destination_object.add_attribute(text_column, "text", 1)

            changed_function = lambda combo: self._combo_change(
                             selection_trigger,
                             combo,
                             entry_box,
                             vm_list)

            destination_object.connect("changed", changed_function)
            changed_function(destination_object)

        else:
            raise TypeError(
                    "Only expecting Gtk.ComboBox objects to want our model.")

    def apply_icon(self, entry, qube_name):
        if isinstance(entry, Gtk.Entry):
            if qube_name in self._entries:
                entry.set_icon_from_pixbuf(
                        Gtk.EntryIconPosition.PRIMARY,
                        self._entries[qube_name]['icon'])
            else:
                raise ValueError("The specified source qube does not exist!")
        else:
            raise TypeError(
                    "Only expecting Gtk.Entry objects to want our icon.")


class GtkOneTimerHelper:
    # pylint: disable=too-few-public-methods
    def __init__(self, wait_seconds):
        self._wait_seconds = wait_seconds
        self._current_timer_id = 0
        self._timer_completed = False

    def _invalidate_timer_completed(self):
        self._timer_completed = False

    def _invalidate_current_timer(self):
        self._current_timer_id += 1

    def _timer_check_run(self, timer_id):
        if self._current_timer_id == timer_id:
            self._timer_run(timer_id)
            self._timer_completed = True
        else:
            pass

    def _timer_run(self, timer_id):
        raise NotImplementedError("Not yet implemented")

    def _timer_schedule(self):
        self._invalidate_current_timer()
        GObject.timeout_add(int(round(self._wait_seconds * 1000)),
                            self._timer_check_run,
                            self._current_timer_id)

    def _timer_has_completed(self):
        return self._timer_completed


class FocusStealingHelper(GtkOneTimerHelper):
    def __init__(self, window, target_button, wait_seconds=1):
        GtkOneTimerHelper.__init__(self, wait_seconds)
        self._window = window
        self._target_button = target_button

        self._window.connect("window-state-event", self._window_state_event)

        self._target_sensitivity = False
        self._target_button.set_sensitive(self._target_sensitivity)

    def _window_changed_focus(self, window_is_focused):
        self._target_button.set_sensitive(False)
        self._invalidate_timer_completed()

        if window_is_focused:
            self._timer_schedule()
        else:
            self._invalidate_current_timer()

    def _window_state_event(self, window, event):
        assert window == self._window, \
               'Window state callback called with wrong window'

        changed_focus = event.changed_mask & Gdk.WindowState.FOCUSED
        window_focus = event.new_window_state & Gdk.WindowState.FOCUSED

        if changed_focus:
            self._window_changed_focus(window_focus != 0)

        # Propagate event further
        return False

    def _timer_run(self, timer_id):
        self._target_button.set_sensitive(self._target_sensitivity)

    def request_sensitivity(self, sensitivity):
        if self._timer_has_completed() or not sensitivity:
            self._target_button.set_sensitive(sensitivity)

        self._target_sensitivity = sensitivity

    def can_perform_action(self):
        return self._timer_has_completed()
