#!/usr/bin/python
#
# The Qubes OS Project, https://www.qubes-os.org/
#
# Copyright (C) 2017 boring-stuff <boring-stuff@users.noreply.github.com>
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

import gi
import os
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk, GdkPixbuf, GObject, GLib
import qubes
from qubespolicy.utils import sanitize_domain_name

glade_directory = os.path.join(os.path.dirname(__file__), "glade")


class GtkIconGetter:
    def __init__(self, size):
        self._icons = {}
        self._size = size
        self._theme = Gtk.IconTheme.get_default()

    def get_icon(self, name):
        if name not in self._icons:
            try:
                icon = self._theme.load_icon(name, self._size, 0)
            except GLib.Error:
                icon = self._theme.load_icon("gnome-foot", self._size, 0)

            self._icons[name] = icon

        return self._icons[name]


class VMListModeler:
    def __init__(self):
        self._icon_getter = GtkIconGetter(16)

        self._entries = {}
        self._create_entries()


    def _get_icon(self, vm):
        return self._icon_getter.get_icon(vm.label.icon)

    def _get_list(self):
        collection = qubes.QubesVmCollection()
        try:
            collection.lock_db_for_reading()

            collection.load()

            return [vm for vm in collection.values()]
        finally:
            collection.unlock_db()

    def _create_entries(self):
        for vm in self._get_list():
            sanitize_domain_name(vm.name, assert_sanitized=True)

            icon = self._get_icon(vm)

            self._entries[vm.name] = {'qid': vm.qid,
                                      'icon': icon,
                                      'vm': vm}


    def _get_valid_qube_name(self, combo, entry_box, exclusions):
        name = None

        if combo and combo.get_active_id():
            selected = combo.get_active_id()

            if selected in self._entries and selected not in exclusions:
                name = selected

        if not name and entry_box:
            typed = entry_box.get_text()

            if typed in self._entries and typed not in exclusions:
                name = typed

        return name

    def _combo_change(self, selection_trigger, combo, entry_box, exclusions):
        data = None
        name = self._get_valid_qube_name(combo, entry_box, exclusions)

        if name:
            entry = self._entries[name]

            data = (entry['qid'], name)

            if entry_box:
                entry_box.set_icon_from_pixbuf(
                    Gtk.EntryIconPosition.PRIMARY, entry['icon'])
        else:
            if entry_box:
                entry_box.set_icon_from_stock(
                    Gtk.EntryIconPosition.PRIMARY, "gtk-find")

        if selection_trigger:
            selection_trigger(data)

    def _entry_activate(self, activation_trigger, combo, entry_box, exclusions):
        name = self._get_valid_qube_name(combo, entry_box, exclusions)

        if name:
            activation_trigger(entry_box)

    def apply_model(self, destination_object, vm_filter_list=None,
                    selection_trigger=None, activation_trigger=None):
        if isinstance(destination_object, Gtk.ComboBox):
            list_store = Gtk.ListStore(int, str, GdkPixbuf.Pixbuf)

            exclusions = []
            for vm_name in sorted(self._entries.keys()):
                entry = self._entries[vm_name]

                matches = True

                if vm_filter_list:
                    for vm_filter in vm_filter_list:
                        if not vm_filter.matches(entry['vm']):
                            matches = False
                            break

                if matches:
                    list_store.append([entry['qid'], vm_name, entry['icon']])
                else:
                    exclusions += [vm_name]

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
                            exclusions))

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
                             exclusions)

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

    class NameBlacklistFilter:
        def __init__(self, avoid_names_list):
            self._avoid_names_list = avoid_names_list

        def matches(self, vm):
            return vm.name not in self._avoid_names_list

    class NameWhitelistFilter:
        def __init__(self, allowed_names_list):
            self._allowed_names_list = allowed_names_list

        def matches(self, vm):
            return vm.name in self._allowed_names_list


class GtkOneTimerHelper:
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
