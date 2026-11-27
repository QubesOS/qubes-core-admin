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

from unittest import mock

import qubes.ext.gui
import qubes.tests


class TC_70_Gui(qubes.tests.QubesTestCase):
    def setUp(self):
        super().setUp()
        self.ext = qubes.ext.gui.GUI()
        self.guivm = mock.MagicMock()
        self.guivm.name = "sys-gui"
        self.client = mock.MagicMock()
        self.client.name = "client"

    def test_000_shutdown(self):
        self.ext.on_domain_pre_shutdown(
            self.guivm,
            "domain-pre-shutdown",
        )

    def test_000_shutdown_used(self):
        with mock.patch.object(
            self.ext, "attached_vms", return_value=[self.client]
        ), mock.patch.object(self.client, "is_running", return_value=True):
            with self.assertRaises(qubes.exc.QubesVMInUseError):
                self.ext.on_domain_pre_shutdown(
                    self.guivm,
                    "domain-pre-shutdown",
                )

    def test_000_shutdown_used_force(self):
        with mock.patch.object(
            self.ext, "attached_vms", return_value=[self.client]
        ), mock.patch.object(self.client, "is_running", return_value=True):
            self.ext.on_domain_pre_shutdown(
                self.guivm,
                "domain-pre-shutdown",
                force=True,
            )


class TC_71_GUIVM(qubes.tests.QubesTestCase):
    def setUp(self):
        super().setUp()
        self.ext = qubes.ext.gui.GUI()

    @staticmethod
    def _vm(name, guivm=None, default=False):
        vm = mock.MagicMock()
        vm.name = name
        vm.guivm = guivm
        vm.property_is_default.return_value = default
        return vm

    def _set(self, vm, guivm):
        self.ext.on_property_pre_set(
            vm, "property-pre-set:guivm", name="guivm", newvalue=guivm
        )

    def test_000_valid_chain(self):
        dom0 = mock.MagicMock(spec=qubes.vm.adminvm.AdminVM)
        sys_gui = self._vm("sys-gui", guivm=dom0)
        self._set(self._vm("work", guivm=sys_gui), sys_gui)
        self._set(self._vm("work"), None)

    def test_010_self(self):
        vm = self._vm("sys-gui")
        with self.assertRaises(qubes.exc.QubesValueError):
            self._set(vm, vm)

    def test_020_loop(self):
        gui_a = self._vm("gui-a")
        gui_b = self._vm("gui-b", guivm=gui_a)
        with self.assertRaises(qubes.exc.QubesValueError):
            self._set(gui_a, gui_b)
        gui_c = self._vm("gui-c", guivm=gui_b)
        with self.assertRaises(qubes.exc.QubesValueError):
            self._set(gui_a, gui_c)

    def test_030_existing_loop_elsewhere(self):
        gui_x = self._vm("gui-x")
        gui_y = self._vm("gui-y", guivm=gui_x)
        gui_x.guivm = gui_y
        with self.assertRaises(qubes.exc.QubesValueError):
            self._set(self._vm("work"), gui_x)

    def _set_default(self, value):
        self.ext.on_property_pre_set_default_guivm(
            "app",
            "property-pre-set:default_guivm",
            name="default_guivm",
            newvalue=value,
        )

    def test_040_loop_through_default(self):
        sys_gui = self._vm("sys-gui")
        work = self._vm("work", default=True)
        sys_gui.app.default_guivm = sys_gui
        with self.assertRaises(qubes.exc.QubesValueError):
            self._set(sys_gui, work)

    def _reset(self, vm):
        self.ext.on_property_pre_reset(
            vm, "property-pre-reset:guivm", name="guivm"
        )

    def test_050_reset(self):
        dom0 = mock.MagicMock(spec=qubes.vm.adminvm.AdminVM)
        vm = self._vm("sys-gui", guivm=dom0)
        vm.app.default_guivm = dom0
        self._reset(vm)
        vm.app.default_guivm = vm
        with self.assertRaises(qubes.exc.QubesValueError):
            self._reset(vm)
        other = self._vm("sys-gui-2", guivm=vm)
        vm.app.default_guivm = other
        with self.assertRaises(qubes.exc.QubesValueError):
            self._reset(vm)

    def test_100_default_guivm(self):
        self._set_default(None)
        self._set_default(mock.MagicMock(spec=qubes.vm.adminvm.AdminVM))
        self._set_default(self._vm("sys-gui"))
        with self.assertRaises(qubes.exc.QubesValueError):
            self._set_default(self._vm("sys-gui-2", default=True))

    def test_110_default_guivm_loop(self):
        gui_a = self._vm("gui-a", default=True)
        gui_b = self._vm("gui-b", guivm=gui_a)
        with self.assertRaises(qubes.exc.QubesValueError):
            self._set_default(gui_b)

    def _load(self, vm):
        self.ext.on_domain_load_guivm_loop_check(vm, "domain-load")

    def test_200_load_breaks_loop(self):
        gui_a = self._vm("gui-a")
        gui_b = self._vm("gui-b", guivm=gui_a)
        gui_a.guivm = gui_b
        self._load(gui_a)
        self.assertIsNone(gui_a.guivm)
        gui_a.log.error.assert_called_once_with(mock.ANY, "gui-a", gui_b)
        self._load(gui_b)
        self.assertIs(gui_b.guivm, gui_a)
        gui_b.log.error.assert_not_called()

    def test_210_load_breaks_default_loop(self):
        vm = self._vm("sys-gui", default=True)
        vm.guivm = vm
        vm.app.default_guivm = vm
        self._load(vm)
        self.assertIsNone(vm.guivm)

    def test_220_load_breaks_loop_elsewhere(self):
        gui_x = self._vm("gui-x")
        gui_y = self._vm("gui-y", guivm=gui_x)
        gui_x.guivm = gui_y
        work = self._vm("work", guivm=gui_x)
        self._load(work)
        self.assertIsNone(work.guivm)
        work.log.error.assert_called_once_with(mock.ANY, "work", gui_x)


class TC_72_DPIScale(qubes.tests.QubesTestCase):
    def setUp(self):
        super().setUp()
        self.ext = qubes.ext.gui.GUI()
        self.features = {}
        self.domains = {}
        specs = {
            "features.get.side_effect": self.features.get,
            "app.domains.__getitem__.side_effect": self.domains.__getitem__,
            "app.domains.__iter__.side_effect": self.domains.values().__iter__,
        }
        vmspecs = {
            **specs,
            **{
                "name": "test-vm",
                "is_running.return_value": True,
            },
        }
        dom0specs = {
            **specs,
            **{
                "name": "dom0",
                "klass": "AdminVM",
                "guivm": None,
                "is_running.return_value": True,
            },
        }
        self.vm = mock.MagicMock()
        self.vm.configure_mock(**vmspecs)
        self.dom0 = mock.MagicMock()
        self.dom0.configure_mock(**dom0specs)
        self.domains["dom0"] = self.dom0
        self.domains["test-vm"] = self.vm

    def test_000_feature_set(self):
        self.features["dpi.scale"] = "2"
        self.ext.on_domain_feature_set_dpi_scale(
            self.dom0, "domain-feature-set:dpi.scale", "dpi.scale", "2"
        )
        self.assertEqual(
            self.vm.untrusted_qdb.mock_calls,
            [("write", ("/dpi/scale", "2"), {})],
        )

    def test_001_feature_set_halted(self):
        self.vm.is_running.return_value = False
        self.features["dpi.scale"] = "2"
        self.ext.on_domain_feature_set_dpi_scale(
            self.dom0, "domain-feature-set:dpi.scale", "dpi.scale", "2"
        )
        self.assertEqual(self.vm.untrusted_qdb.mock_calls, [])

    def test_002_feature_set_not_dom0(self):
        self.features["dpi.scale"] = "2"
        self.ext.on_domain_feature_set_dpi_scale(
            self.vm, "domain-feature-set:dpi.scale", "dpi.scale", "2"
        )
        self.assertEqual(self.vm.untrusted_qdb.mock_calls, [])

    def test_010_feature_delete(self):
        self.ext.on_domain_feature_delete(
            self.dom0, "domain-feature-delete:dpi.scale", "dpi.scale"
        )
        self.assertEqual(
            self.vm.untrusted_qdb.mock_calls,
            [("write", ("/dpi/scale", "1"), {})],
        )

    def test_020_domain_load(self):
        self.features["dpi.scale"] = "2"
        with mock.patch(
            "qubes.ext.gui.open", mock.mock_open(), create=True
        ) as mock_file:
            self.ext.on_domain_init_load(self.dom0, "domain-load")
        mock_file.assert_called_once_with(
            "/var/run/qubes_dpi_scale", "w", encoding="ascii"
        )
        mock_file.return_value.write.assert_called_once_with("2")
