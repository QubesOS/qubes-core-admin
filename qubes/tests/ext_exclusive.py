# -*- encoding: utf-8 -*-
#
# The Qubes OS Project, http://www.qubes-os.org
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

import qubes.exc
import qubes.ext.exclusive
import qubes.tests
import qubes.vm.adminvm


class TC_00_Exclusive(qubes.tests.QubesTestCase):
    def setUp(self):
        super().setUp()
        self.ext = qubes.ext.exclusive.ExclusiveExtension()
        self.app = mock.MagicMock()
        self.app.domains = []

    def tearDown(self):
        # drop the mocked qubes (one is an AdminVM) before the leak check
        del self.app
        super().tearDown()

    def add_vm(self, name, state="Halted", tags=(), features=None, cls=None):
        vm = mock.MagicMock(spec=cls) if cls else mock.MagicMock()
        vm.name = name
        vm.app = self.app
        vm.tags = set(tags)
        vm.features = dict(features or {})
        vm.get_power_state.return_value = state
        self.app.domains.append(vm)
        return vm

    def start(self, vm):
        self.ext.on_domain_pre_start(vm, "domain-pre-start", start_guid=True)

    def test_000_no_feature(self):
        vm = self.add_vm("personal", tags=["work"])
        self.add_vm("work", "Running", tags=["work"])
        self.start(vm)

    def test_001_excluded_tag_running(self):
        vm = self.add_vm("personal", features={"exclusive-with": "work"})
        self.add_vm("work", "Running", tags=["work"])
        with self.assertRaisesRegex(qubes.exc.QubesVMError, "work"):
            self.start(vm)

    def test_002_excluded_tag_halted(self):
        vm = self.add_vm("personal", features={"exclusive-with": "work"})
        self.add_vm("work", "Halted", tags=["work"])
        self.start(vm)

    def test_003_reverse(self):
        vm = self.add_vm("work", tags=["work"])
        self.add_vm("personal", "Running", features={"exclusive-with": "work"})
        with self.assertRaisesRegex(qubes.exc.QubesVMError, "personal"):
            self.start(vm)

    def test_004_states(self):
        for state in ("Transient", "Paused", "Suspended", "Halting"):
            with self.subTest(state=state):
                self.app.domains = []
                vm = self.add_vm("a", features={"exclusive-with": "x"})
                self.add_vm("b", state, tags=["x"])
                with self.assertRaises(qubes.exc.QubesVMError):
                    self.start(vm)

    def test_005_multiple_tags_and_names(self):
        vm = self.add_vm("a", features={"exclusive-with": "x  y"})
        self.add_vm("c", "Running", tags=["y"])
        self.add_vm("b", "Running", tags=["x"])
        self.add_vm("d", "Running", tags=["z"])
        with self.assertRaisesRegex(
            qubes.exc.QubesVMError, "same time as: b, c "
        ):
            self.start(vm)

    def test_006_self_ignored(self):
        # a qube with its own excluded tag only conflicts with others
        vm = self.add_vm("a", tags=["x"], features={"exclusive-with": "x"})
        self.start(vm)
        self.add_vm("b", "Running", tags=["x"])
        with self.assertRaisesRegex(qubes.exc.QubesVMError, "same time as: b "):
            self.start(vm)

    def test_007_adminvm_ignored(self):
        vm = self.add_vm("a", features={"exclusive-with": "x"})
        self.add_vm("dom0", "Running", tags=["x"], cls=qubes.vm.adminvm.AdminVM)
        self.start(vm)

    def test_008_empty_feature(self):
        vm = self.add_vm("a", tags=["x"], features={"exclusive-with": ""})
        self.add_vm("b", "Running", tags=[""], features={"exclusive-with": ""})
        self.start(vm)
