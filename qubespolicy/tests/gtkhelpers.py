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

import time
import unittest

import gi  # isort:skip
gi.require_version('Gtk', '3.0')  # isort:skip
from gi.repository import Gtk  # isort:skip pylint:

from qubes.tests import skipUnlessEnv

from qubespolicy.gtkhelpers import VMListModeler, GtkOneTimerHelper, \
    FocusStealingHelper

mock_domains_info = {
    'dom0': {'icon': 'black', 'type': 'AdminVM'},
    'test-red1': {'icon': 'red', 'type': 'AppVM'},
    'test-red2': {'icon': 'red', 'type': 'AppVM'},
    'test-red3': {'icon': 'red', 'type': 'AppVM'},
    'test-source': {'icon': 'green', 'type': 'AppVM'},
    'test-target': {'icon': 'orange', 'type': 'AppVM'},
    '@dispvm:test-disp6': {'icon': 'red', 'type': 'DispVM'},
}

mock_whitelist = ["test-red1", "test-red2", "test-red3",
                  "test-target", "@dispvm:test-disp6"]

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


@skipUnlessEnv('DISPLAY')
class VMListModelerTest(VMListModeler, unittest.TestCase):
    def __init__(self, *args, **kwargs):
        unittest.TestCase.__init__(self, *args, **kwargs)
        VMListModeler.__init__(self, mock_domains_info)

    def test_entries_gets_loaded(self):
        self.assertIsNotNone(self._entries)

    def test_valid_qube_name(self):
        self.apply_model(Gtk.ComboBox(), list(mock_domains_info.keys()))

        for name in ["test-red1", "test-red2", "test-red3",
                     "test-target", "Disposable VM (test-disp6)"]:

            mock = MockComboEntry(name)
            self.assertEquals(name,
                self._get_valid_qube_name(mock, mock, mock_whitelist))
            self.assertEquals(name,
                self._get_valid_qube_name(None, mock, mock_whitelist))
            self.assertEquals(name,
                self._get_valid_qube_name(mock, None, mock_whitelist))
            self.assertIsNone(
                self._get_valid_qube_name(None, None, mock_whitelist))

    def test_valid_qube_name_whitelist(self):
        list_exc = ["@dispvm:test-disp6", "test-red2"]

        whitelist = [name for name in mock_whitelist if name not in list_exc]
        self.apply_model(Gtk.ComboBox(), whitelist)

        for name in list_exc:
            mock = MockComboEntry(name)
            self.assertIsNone(self._get_valid_qube_name(mock, mock, whitelist))
            self.assertIsNone(self._get_valid_qube_name(None, mock, whitelist))
            self.assertIsNone(self._get_valid_qube_name(mock, None, whitelist))

    def test_invalid_qube_name(self):
        self.apply_model(Gtk.ComboBox(), mock_whitelist)

        for name in ["test-nonexistant", None, "", 1]:

            mock = MockComboEntry(name)
            self.assertIsNone(
                self._get_valid_qube_name(mock, mock, mock_whitelist))
            self.assertIsNone(
                self._get_valid_qube_name(None, mock, mock_whitelist))
            self.assertIsNone(
                self._get_valid_qube_name(mock, None, mock_whitelist))

    def test_apply_model(self):
        new_object = Gtk.ComboBox()
        self.assertIsNone(new_object.get_model())

        self.apply_model(new_object, mock_whitelist)

        self.assertIsNotNone(new_object.get_model())

    def test_apply_model_with_entry(self):
        new_object = Gtk.ComboBox.new_with_entry()

        self.assertIsNone(new_object.get_model())

        self.apply_model(new_object, [])

        self.assertIsNotNone(new_object.get_model())

    def test_apply_model_only_combobox(self):
        invalid_types = [1, "One", u'1', {'1': "one"}, VMListModeler(
            mock_domains_info)]

        for invalid_type in invalid_types:
            with self.assertRaises(TypeError):
                self.apply_model(invalid_type, [])

    def test_apply_model_whitelist(self):
        combo = Gtk.ComboBox()

        self.apply_model(combo, list(mock_domains_info.keys()))
        self.assertEquals(7, len(combo.get_model()))

        names = [entry['api_name'] for entry in self._entries.values()]

        self.apply_model(combo, [names[0]])
        self.assertEquals(1, len(combo.get_model()))

        self.apply_model(combo, [names[0], names[1]])
        self.assertEquals(2, len(combo.get_model()))

    def test_apply_icon(self):
        new_object = Gtk.Entry()

        self.assertIsNone(
                new_object.get_icon_pixbuf(Gtk.EntryIconPosition.PRIMARY))

        self.apply_icon(new_object, "Disposable VM (test-disp6)")

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
                     "test-target", "Disposable VM (test-disp6)"]:
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


@skipUnlessEnv('DISPLAY')
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
