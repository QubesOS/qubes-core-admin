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

import time
import unittest

from gi.repository import Gtk

from qubespolicy.gtkhelpers import VMListModeler, GtkOneTimerHelper, \
    FocusStealingHelper


class VMListModelerMock(VMListModeler):
    def __init__(self):
        VMListModeler.__init__(self)

    def _get_list(self):
        return [
            MockVm(0, "dom0", "black"),
            MockVm(2, "test-red1", "red"),
            MockVm(4, "test-red2", "red"),
            MockVm(7, "test-red3", "red"),
            MockVm(8, "test-source", "green"),
            MockVm(10, "test-target", "orange"),
            MockVm(15, "test-disp6", "red", True)
        ]

    @staticmethod
    def get_name_whitelist():
        return ["test-red1", "test-red2", "test-red3",
                "test-target", "test-disp6"]


class MockVmLabel:
    def __init__(self, index, color, name, dispvm=False):
        self.index = index
        self.color = color
        self.name = name
        self.dispvm = dispvm
        self.icon = "gnome-foot"


class MockVm:
    def __init__(self, qid, name, color, dispvm=False):
        self.qid = qid
        self.name = name
        self.label = MockVmLabel(qid, 0x000000, color, dispvm)


class MockComboEntry:
    def __init__(self, text):
        self._text = text

    def get_active_id(self):
        return self._text

    def get_text(self):
        return self._text


class GtkTestCase(unittest.TestCase):
    def __init__(self, *args, **kwargs):
        unittest.TestCase.__init__(self, *args, **kwargs)
        self._smallest_wait = 0.01

    def flush_gtk_events(self, wait_seconds=0):
        start = time.time()
        iterations = 0
        remaining_wait = wait_seconds
        time_length = 0

        if wait_seconds < 0:
            raise ValueError("Only non-negative intervals are allowed.")

        while remaining_wait >= 0:
            while Gtk.events_pending():
                Gtk.main_iteration_do(blocking=False)
                iterations += 1

            time_length = time.time() - start
            remaining_wait = wait_seconds - time_length

            if remaining_wait > 0:
                time.sleep(self._smallest_wait)

        return iterations, time_length


class VMListModelerTest(VMListModelerMock, unittest.TestCase):
    def __init__(self, *args, **kwargs):
        unittest.TestCase.__init__(self, *args, **kwargs)
        VMListModelerMock.__init__(self)

    def test_entries_gets_loaded(self):
        self.assertIsNotNone(self._entries)

    def test_valid_qube_name(self):
        self.apply_model(Gtk.ComboBox())

        for name in ["test-red1", "test-red2", "test-red3",
                     "test-target", "test-disp6"]:

            mock = MockComboEntry(name)
            self.assertEquals(name, self._get_valid_qube_name(mock, mock, []))
            self.assertEquals(name, self._get_valid_qube_name(None, mock, []))
            self.assertEquals(name, self._get_valid_qube_name(mock, None, []))
            self.assertIsNone(self._get_valid_qube_name(None, None, []))

    def test_valid_qube_name_exceptions(self):
        list_exc = ["test-disp6", "test-red2"]

        self.apply_model(Gtk.ComboBox(),
            [VMListModeler.NameBlacklistFilter([list_exc[0], list_exc[1]])])

        for name in list_exc:
            mock = MockComboEntry(name)
            self.assertIsNone(self._get_valid_qube_name(mock, mock, list_exc))
            self.assertIsNone(self._get_valid_qube_name(None, mock, list_exc))
            self.assertIsNone(self._get_valid_qube_name(mock, None, list_exc))

    def test_invalid_qube_name(self):
        self.apply_model(Gtk.ComboBox())

        for name in ["test-nonexistant", None, "", 1]:

            mock = MockComboEntry(name)
            self.assertIsNone(self._get_valid_qube_name(mock, mock, []))
            self.assertIsNone(self._get_valid_qube_name(None, mock, []))
            self.assertIsNone(self._get_valid_qube_name(mock, None, []))

    def test_apply_model(self):
        new_object = Gtk.ComboBox()
        self.assertIsNone(new_object.get_model())

        self.apply_model(new_object)

        self.assertIsNotNone(new_object.get_model())

    def test_apply_model_with_entry(self):
        new_object = Gtk.ComboBox.new_with_entry()

        self.assertIsNone(new_object.get_model())

        self.apply_model(new_object)

        self.assertIsNotNone(new_object.get_model())

    def test_apply_model_only_combobox(self):
        invalid_types = [1, "One", u'1', {'1': "one"}, VMListModelerMock()]

        for invalid_type in invalid_types:
            with self.assertRaises(TypeError):
                self.apply_model(invalid_type)

    def test_apply_model_blacklist(self):
        combo = Gtk.ComboBox()

        self.apply_model(combo)
        self.assertEquals(7, len(combo.get_model()))

        self.apply_model(combo, [
            VMListModeler.NameBlacklistFilter([self._entries.keys()[0]])])
        self.assertEquals(6, len(combo.get_model()))

        self.apply_model(combo, [
            VMListModeler.NameBlacklistFilter([self._entries.keys()[0]]),
            VMListModeler.NameBlacklistFilter([self._entries.keys()[1]])])
        self.assertEquals(5, len(combo.get_model()))

        self.apply_model(combo, [VMListModeler.NameBlacklistFilter([
            self._entries.keys()[0],
            self._entries.keys()[1]
        ])])
        self.assertEquals(5, len(combo.get_model()))

    def test_apply_model_whitelist(self):
        combo = Gtk.ComboBox()

        self.apply_model(combo)
        self.assertEquals(7, len(combo.get_model()))

        self.apply_model(combo, [
            VMListModeler.NameWhitelistFilter([self._entries.keys()[0]])])
        self.assertEquals(1, len(combo.get_model()))

        self.apply_model(combo, [VMListModeler.NameWhitelistFilter([
                                        self._entries.keys()[0],
                                        self._entries.keys()[1]])])
        self.assertEquals(2, len(combo.get_model()))

    def test_apply_model_multiple_filters(self):
        combo = Gtk.ComboBox()

        self.apply_model(combo)
        self.assertEquals(7, len(combo.get_model()))

        self.apply_model(combo, [VMListModeler.NameWhitelistFilter([
                                        self._entries.keys()[0],
                                        self._entries.keys()[1],
                                        self._entries.keys()[2],
                                        self._entries.keys()[3],
                                        self._entries.keys()[4]]),
                                 VMListModeler.NameBlacklistFilter([
                                        self._entries.keys()[0],
                                        self._entries.keys()[1]])])
        self.assertEquals(3, len(combo.get_model()))

    def test_apply_icon(self):
        new_object = Gtk.Entry()

        self.assertIsNone(
                new_object.get_icon_pixbuf(Gtk.EntryIconPosition.PRIMARY))

        self.apply_icon(new_object, "test-disp6")

        self.assertIsNotNone(
                new_object.get_icon_pixbuf(Gtk.EntryIconPosition.PRIMARY))

    def test_apply_icon_only_entry(self):
        invalid_types = [1, "One", u'1', {'1': "one"}, Gtk.ComboBox()]

        for invalid_type in invalid_types:
            with self.assertRaises(TypeError):
                self.apply_icon(invalid_type, "test-disp6")

    def test_apply_icon_only_existing(self):
        new_object = Gtk.Entry()

        for name in ["test-red1", "test-red2", "test-red3",
                     "test-target", "test-disp6"]:
            self.apply_icon(new_object, name)

        for name in ["test-nonexistant", None, "", 1]:
            with self.assertRaises(ValueError):
                self.apply_icon(new_object, name)


class GtkOneTimerHelperTest(GtkOneTimerHelper, GtkTestCase):
    def __init__(self, *args, **kwargs):
        GtkTestCase.__init__(self, *args, **kwargs)

        self._test_time = 0.1

        GtkOneTimerHelper.__init__(self, self._test_time)
        self._run_timers = []

    def _timer_run(self, timer_id):
        self._run_timers.append(timer_id)

    def test_nothing_runs_automatically(self):
        self.flush_gtk_events(self._test_time*2)
        self.assertEquals([], self._run_timers)
        self.assertEquals(0, self._current_timer_id)
        self.assertFalse(self._timer_has_completed())

    def test_schedule_one_task(self):
        self._timer_schedule()
        self.flush_gtk_events(self._test_time*2)
        self.assertEquals([1], self._run_timers)
        self.assertEquals(1, self._current_timer_id)
        self.assertTrue(self._timer_has_completed())

    def test_invalidate_completed(self):
        self._timer_schedule()
        self.flush_gtk_events(self._test_time*2)
        self.assertEquals([1], self._run_timers)
        self.assertEquals(1, self._current_timer_id)

        self.assertTrue(self._timer_has_completed())
        self._invalidate_timer_completed()
        self.assertFalse(self._timer_has_completed())

    def test_schedule_and_cancel_one_task(self):
        self._timer_schedule()
        self._invalidate_current_timer()
        self.flush_gtk_events(self._test_time*2)
        self.assertEquals([], self._run_timers)
        self.assertEquals(2, self._current_timer_id)
        self.assertFalse(self._timer_has_completed())

    def test_two_tasks(self):
        self._timer_schedule()
        self.flush_gtk_events(self._test_time/4)
        self._timer_schedule()
        self.flush_gtk_events(self._test_time*2)
        self.assertEquals([2], self._run_timers)
        self.assertEquals(2, self._current_timer_id)
        self.assertTrue(self._timer_has_completed())

    def test_more_tasks(self):
        num = 0
        for num in range(1, 10):
            self._timer_schedule()
            self.flush_gtk_events(self._test_time/4)
        self.flush_gtk_events(self._test_time*1.75)
        self.assertEquals([num], self._run_timers)
        self.assertEquals(num, self._current_timer_id)
        self.assertTrue(self._timer_has_completed())

    def test_more_tasks_cancel(self):
        num = 0
        for num in range(1, 10):
            self._timer_schedule()
            self.flush_gtk_events(self._test_time/4)
        self._invalidate_current_timer()
        self.flush_gtk_events(int(self._test_time*1.75))
        self.assertEquals([], self._run_timers)
        self.assertEquals(num+1, self._current_timer_id)
        self.assertFalse(self._timer_has_completed())

    def test_subsequent_tasks(self):
        self._timer_schedule()  # 1
        self.flush_gtk_events(self._test_time*2)
        self.assertEquals([1], self._run_timers)
        self.assertEquals(1, self._current_timer_id)
        self.assertTrue(self._timer_has_completed())

        self._timer_schedule()  # 2
        self.flush_gtk_events(self._test_time*2)
        self.assertEquals([1, 2], self._run_timers)
        self.assertEquals(2, self._current_timer_id)
        self.assertTrue(self._timer_has_completed())

        self._invalidate_timer_completed()
        self._timer_schedule()  # 3
        self._invalidate_current_timer()  # 4
        self.flush_gtk_events(self._test_time*2)
        self.assertEquals([1, 2], self._run_timers)
        self.assertEquals(4, self._current_timer_id)
        self.assertFalse(self._timer_has_completed())

        self._timer_schedule()  # 5
        self.flush_gtk_events(self._test_time*2)
        self.assertEquals([1, 2, 5], self._run_timers)
        self.assertEquals(5, self._current_timer_id)
        self.assertTrue(self._timer_has_completed())


class FocusStealingHelperMock(FocusStealingHelper):
    def simulate_focus(self):
        self._window_changed_focus(True)


class FocusStealingHelperTest(FocusStealingHelperMock, GtkTestCase):
    def __init__(self, *args, **kwargs):
        GtkTestCase.__init__(self, *args, **kwargs)

        self._test_time = 0.1
        self._test_button = Gtk.Button()
        self._test_window = Gtk.Window()

        FocusStealingHelperMock.__init__(self, self._test_window,
            self._test_button, self._test_time)

    def test_nothing_runs_automatically(self):
        self.assertFalse(self.can_perform_action())
        self.flush_gtk_events(self._test_time*2)
        self.assertFalse(self.can_perform_action())
        self.assertFalse(self._test_button.get_sensitive())

    def test_nothing_runs_automatically_with_request(self):
        self.request_sensitivity(True)
        self.assertFalse(self.can_perform_action())
        self.flush_gtk_events(self._test_time*2)
        self.assertFalse(self.can_perform_action())
        self.assertFalse(self._test_button.get_sensitive())

    def _simulate_focus(self, focused):
        self._window_changed_focus(focused)

    def test_focus_with_request(self):
        self.request_sensitivity(True)
        self._simulate_focus(True)
        self.flush_gtk_events(self._test_time*2)
        self.assertTrue(self.can_perform_action())
        self.assertTrue(self._test_button.get_sensitive())

    def test_focus_with_late_request(self):
        self._simulate_focus(True)
        self.flush_gtk_events(self._test_time*2)
        self.assertTrue(self.can_perform_action())
        self.assertFalse(self._test_button.get_sensitive())

        self.request_sensitivity(True)
        self.assertTrue(self._test_button.get_sensitive())

    def test_immediate_defocus(self):
        self.request_sensitivity(True)
        self._simulate_focus(True)
        self._simulate_focus(False)
        self.flush_gtk_events(self._test_time*2)
        self.assertFalse(self.can_perform_action())
        self.assertFalse(self._test_button.get_sensitive())

    def test_focus_then_unfocus(self):
        self.request_sensitivity(True)
        self._simulate_focus(True)
        self.flush_gtk_events(self._test_time*2)
        self.assertTrue(self.can_perform_action())
        self.assertTrue(self._test_button.get_sensitive())

        self._simulate_focus(False)
        self.assertFalse(self.can_perform_action())
        self.assertFalse(self._test_button.get_sensitive())

    def test_focus_cycle(self):
        self.request_sensitivity(True)

        self._simulate_focus(True)
        self.flush_gtk_events(self._test_time*2)
        self.assertTrue(self.can_perform_action())
        self.assertTrue(self._test_button.get_sensitive())

        self._simulate_focus(False)
        self.assertFalse(self.can_perform_action())
        self.assertFalse(self._test_button.get_sensitive())

        self._simulate_focus(True)
        self.assertFalse(self.can_perform_action())
        self.assertFalse(self._test_button.get_sensitive())

        self.flush_gtk_events(self._test_time*2)
        self.assertTrue(self.can_perform_action())
        self.assertTrue(self._test_button.get_sensitive())

        self.request_sensitivity(False)
        self.assertTrue(self.can_perform_action())
        self.assertFalse(self._test_button.get_sensitive())

        self._simulate_focus(False)
        self.assertFalse(self.can_perform_action())

        self._simulate_focus(True)
        self.assertFalse(self.can_perform_action())
        self.assertFalse(self._test_button.get_sensitive())

        self.flush_gtk_events(self._test_time*2)
        self.assertTrue(self.can_perform_action())
        self.assertFalse(self._test_button.get_sensitive())

if __name__ == '__main__':
    unittest.main()
