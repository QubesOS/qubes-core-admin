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

import sys
import unittest

from qubespolicy.tests.gtkhelpers import GtkTestCase, FocusStealingHelperMock
from qubespolicy.tests.gtkhelpers import mock_domains_info, mock_whitelist

from qubespolicy.gtkhelpers import VMListModeler
from qubespolicy.rpcconfirmation import RPCConfirmationWindow


class MockRPCConfirmationWindow(RPCConfirmationWindow):
    def _new_vm_list_modeler(self):
        return VMListModeler(mock_domains_info)

    def _new_focus_stealing_helper(self):
        return FocusStealingHelperMock(
                    self._rpc_window,
                    self._rpc_ok_button,
                    self._focus_stealing_seconds)

    def __init__(self, source, rpc_operation, whitelist,
                 target=None, focus_stealing_seconds=1):
        self._focus_stealing_seconds = focus_stealing_seconds

        RPCConfirmationWindow.__init__(
            self, mock_domains_info, source, rpc_operation, whitelist,
            target)

    def is_error_visible(self):
        return self._error_bar.get_visible()

    def get_shown_domains(self):
        model = self._rpc_combo_box.get_model()
        model_iter = model.get_iter_first()
        domains = []

        while model_iter is not None:
            domain_name = model.get_value(model_iter, 1)

            domains += [domain_name]

            model_iter = model.iter_next(model_iter)

        return domains


class RPCConfirmationWindowTestBase(MockRPCConfirmationWindow, GtkTestCase):
    def __init__(self, test_method, source_name="test-source",
                 rpc_operation="test.Operation", whitelist=mock_whitelist,
                 target_name=None):
        GtkTestCase.__init__(self, test_method)
        self.test_source_name = source_name
        self.test_rpc_operation = rpc_operation
        self.test_target_name = target_name

        self._test_time = 0.1

        self.test_called_close = False
        self.test_called_show = False

        self.test_clicked_ok = False
        self.test_clicked_cancel = False

        MockRPCConfirmationWindow.__init__(self,
                                       self.test_source_name,
                                       self.test_rpc_operation,
                                       whitelist,
                                       self.test_target_name,
                                       focus_stealing_seconds=self._test_time)

    def _can_perform_action(self):
        return True

    def _close(self):
        self.test_called_close = True

    def _show(self):
        self.test_called_show = True

    def _clicked_ok(self, button):
        MockRPCConfirmationWindow._clicked_ok(self, button)
        self.test_clicked_ok = True

    def _clicked_cancel(self, button):
        MockRPCConfirmationWindow._clicked_cancel(self, button)
        self.test_clicked_cancel = True

    def test_has_linked_the_fields(self):
        self.assertIsNotNone(self._rpc_window)
        self.assertIsNotNone(self._rpc_ok_button)
        self.assertIsNotNone(self._rpc_cancel_button)
        self.assertIsNotNone(self._rpc_label)
        self.assertIsNotNone(self._source_entry)
        self.assertIsNotNone(self._rpc_combo_box)
        self.assertIsNotNone(self._error_bar)
        self.assertIsNotNone(self._error_message)

    def test_is_showing_source(self):
        self.assertTrue(self.test_source_name in self._source_entry.get_text())

    def test_is_showing_operation(self):
        self.assertTrue(self.test_rpc_operation in self._rpc_label.get_text())

    def test_escape_and_format_rpc_text(self):
        self.assertEquals("qubes.<b>Test</b>",
                          self._escape_and_format_rpc_text("qubes.Test"))
        self.assertEquals("custom.<b>Domain</b>",
                          self._escape_and_format_rpc_text("custom.Domain"))
        self.assertEquals("<b>nodomain</b>",
                          self._escape_and_format_rpc_text("nodomain"))
        self.assertEquals("domain.<b>Sub.Operation</b>",
                          self._escape_and_format_rpc_text("domain.Sub.Operation"))
        self.assertEquals("<b></b>",
                          self._escape_and_format_rpc_text(""))
        self.assertEquals("<b>.</b>",
                          self._escape_and_format_rpc_text("."))
        self.assertEquals("inject.<b>&lt;script&gt;</b>",
                          self._escape_and_format_rpc_text("inject.<script>"))
        self.assertEquals("&lt;script&gt;.<b>inject</b>",
                          self._escape_and_format_rpc_text("<script>.inject"))

    def test_lifecycle_open_select_ok(self):
        self._lifecycle_start(select_target=True)
        self._lifecycle_click(click_type="ok")

    def test_lifecycle_open_select_cancel(self):
        self._lifecycle_start(select_target=True)
        self._lifecycle_click(click_type="cancel")

    def test_lifecycle_open_select_exit(self):
        self._lifecycle_start(select_target=True)
        self._lifecycle_click(click_type="exit")

    def test_lifecycle_open_cancel(self):
        self._lifecycle_start(select_target=False)
        self._lifecycle_click(click_type="cancel")

    def test_lifecycle_open_exit(self):
        self._lifecycle_start(select_target=False)
        self._lifecycle_click(click_type="exit")

    def _lifecycle_click(self, click_type):
        if click_type == "ok":
            self._rpc_ok_button.clicked()

            self.assertTrue(self.test_clicked_ok)
            self.assertFalse(self.test_clicked_cancel)
            self.assertTrue(self._confirmed)
            self.assertIsNotNone(self._target_name)
        elif click_type == "cancel":
            self._rpc_cancel_button.clicked()

            self.assertFalse(self.test_clicked_ok)
            self.assertTrue(self.test_clicked_cancel)
            self.assertFalse(self._confirmed)
        elif click_type == "exit":
            self._close()

            self.assertFalse(self.test_clicked_ok)
            self.assertFalse(self.test_clicked_cancel)
            self.assertIsNone(self._confirmed)

        self.assertTrue(self.test_called_close)


    def _lifecycle_start(self, select_target):
        self.assertFalse(self.test_called_close)
        self.assertFalse(self.test_called_show)

        self.assert_initial_state(False)
        self.assertTrue(isinstance(self._focus_helper, FocusStealingHelperMock))

        # Need the following because of pylint's complaints
        if isinstance(self._focus_helper, FocusStealingHelperMock):
            FocusStealingHelperMock.simulate_focus(self._focus_helper)

        self.flush_gtk_events(self._test_time*2)
        self.assert_initial_state(True)

        try:
            # We expect the call to exit immediately, since no window is opened
            self.confirm_rpc()
        except Exception:
            pass

        self.assertFalse(self.test_called_close)
        self.assertTrue(self.test_called_show)

        self.assert_initial_state(True)

        if select_target:
            self._rpc_combo_box.set_active(1)

            self.assertTrue(self._rpc_ok_button.get_sensitive())

            self.assertIsNotNone(self._target_name)

        self.assertFalse(self.test_called_close)
        self.assertTrue(self.test_called_show)
        self.assertFalse(self.test_clicked_ok)
        self.assertFalse(self.test_clicked_cancel)
        self.assertFalse(self._confirmed)

    def assert_initial_state(self, after_focus_timer):
        self.assertIsNone(self._target_name)
        self.assertFalse(self.test_clicked_ok)
        self.assertFalse(self.test_clicked_cancel)
        self.assertFalse(self._confirmed)
        self.assertFalse(self._rpc_ok_button.get_sensitive())
        self.assertFalse(self._error_bar.get_visible())

        if after_focus_timer:
            self.assertTrue(self._focus_helper.can_perform_action())
        else:
            self.assertFalse(self._focus_helper.can_perform_action())


class RPCConfirmationWindowTestWithTarget(RPCConfirmationWindowTestBase):
    def __init__(self, test_method):
        RPCConfirmationWindowTestBase.__init__(self, test_method,
                 source_name="test-source", rpc_operation="test.Operation",
                 target_name="test-target")

    def test_lifecycle_open_ok(self):
        self._lifecycle_start(select_target=False)
        self._lifecycle_click(click_type="ok")

    def assert_initial_state(self, after_focus_timer):
        self.assertIsNotNone(self._target_name)
        self.assertFalse(self.test_clicked_ok)
        self.assertFalse(self.test_clicked_cancel)
        self.assertFalse(self._confirmed)
        if after_focus_timer:
            self.assertTrue(self._rpc_ok_button.get_sensitive())
            self.assertTrue(self._focus_helper.can_perform_action())
            self.assertEqual(self._target_name, 'test-target')
        else:
            self.assertFalse(self._rpc_ok_button.get_sensitive())
            self.assertFalse(self._focus_helper.can_perform_action())

    def _lifecycle_click(self, click_type):
        RPCConfirmationWindowTestBase._lifecycle_click(self, click_type)
        self.assertIsNotNone(self._target_name)


class RPCConfirmationWindowTestWithDispVMTarget(RPCConfirmationWindowTestBase):
    def __init__(self, test_method):
        RPCConfirmationWindowTestBase.__init__(self, test_method,
                 source_name="test-source", rpc_operation="test.Operation",
                 target_name="@dispvm:test-disp6")

    def test_lifecycle_open_ok(self):
        self._lifecycle_start(select_target=False)
        self._lifecycle_click(click_type="ok")

    def assert_initial_state(self, after_focus_timer):
        self.assertIsNotNone(self._target_name)
        self.assertFalse(self.test_clicked_ok)
        self.assertFalse(self.test_clicked_cancel)
        self.assertFalse(self._confirmed)
        if after_focus_timer:
            self.assertTrue(self._rpc_ok_button.get_sensitive())
            self.assertTrue(self._focus_helper.can_perform_action())
            self.assertEqual(self._target_name, '@dispvm:test-disp6')
        else:
            self.assertFalse(self._rpc_ok_button.get_sensitive())
            self.assertFalse(self._focus_helper.can_perform_action())


class RPCConfirmationWindowTestWithTargetInvalid(unittest.TestCase):
    def __init__(self, *args, **kwargs):
        unittest.TestCase.__init__(self, *args, **kwargs)

    def test_unknown(self):
        self.assert_raises_error(True, "test-source", "test-wrong-target")

    def test_empty(self):
        self.assert_raises_error(True, "test-source", "")

    def test_equals_source(self):
        self.assert_raises_error(True, "test-source", "test-source")

    def assert_raises_error(self, expect, source, target):
        rpcWindow = MockRPCConfirmationWindow(source, "test.Operation",
                                              mock_whitelist, target=target)
        self.assertEquals(expect, rpcWindow.is_error_visible())


class RPCConfirmationWindowTestWhitelist(unittest.TestCase):
    def __init__(self, *args, **kwargs):
        unittest.TestCase.__init__(self, *args, **kwargs)

    def test_no_domains(self):
        self._assert_whitelist([], [])

    def test_all_red_domains(self):
        self._assert_whitelist(["test-red1", "test-red2", "test-red3"],
                               ["test-red1", "test-red2", "test-red3"])

    def test_all_red_domains_plus_nonexistent(self):
        self._assert_whitelist(
            ["test-red1", "test-red2", "test-red3",
             "test-blue1", "test-blue2", "test-blue3"],
            ["test-red1", "test-red2", "test-red3"])

    def test_all_allowed_domains(self):
        self._assert_whitelist(
            ["test-red1", "test-red2", "test-red3",
             "test-target", "@dispvm:test-disp6", "test-source", "dom0"],
            ["test-red1", "test-red2", "test-red3",
             "test-target", "Disposable VM (test-disp6)", "test-source",
                "dom0"])

    def _assert_whitelist(self, whitelist, expected):
        rpcWindow = MockRPCConfirmationWindow(
            "test-source", "test.Operation", whitelist)

        domains = rpcWindow.get_shown_domains()

        self.assertCountEqual(domains, expected)

if __name__ == '__main__':
    test = False
    window = False

    if len(sys.argv) == 1 or sys.argv[1] == '-t':
        test = True
    elif sys.argv[1] == '-w':
        window = True
    else:
        print("Usage: " + __file__ + " [-t|-w]")

    if window:
        print(MockRPCConfirmationWindow("test-source",
                                        "qubes.Filecopy",
                                        mock_whitelist,
                                        "test-red1").confirm_rpc())
    elif test:
        unittest.main(argv=[sys.argv[0]])
