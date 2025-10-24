# pylint: disable=protected-access

#
# The Qubes OS Project, https://www.qubes-os.org/
#
# Copyright (C) 2014-2016  Joanna Rutkowska <joanna@invisiblethingslab.com>
# Copyright (C) 2014-2016  Wojtek Porczyk <woju@invisiblethingslab.com>
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
import ipaddress
import unittest
from unittest.mock import patch

import qubes
import qubes.vm.qubesvm

import qubes.tests
import qubes.tests.vm.qubesvm
from qubes.vm.mix.net import vmid_to_ipv4


class TC_00_NetVMMixin(
    qubes.tests.vm.qubesvm.QubesVMTestsMixin, qubes.tests.QubesTestCase
):
    def setUp(self):
        super(TC_00_NetVMMixin, self).setUp()
        self.app = qubes.tests.vm.TestApp()
        self.app.vmm.offline_mode = True

    def setup_netvms(self, vm):
        # usage of QubesVM here means that those tests should be after
        # testing properties used here
        self.netvm1 = qubes.vm.qubesvm.QubesVM(
            self.app,
            None,
            qid=2,
            name=qubes.tests.VMPREFIX + "netvm1",
            provides_network=True,
            netvm=None,
        )
        self.netvm2 = qubes.vm.qubesvm.QubesVM(
            self.app,
            None,
            qid=3,
            name=qubes.tests.VMPREFIX + "netvm2",
            provides_network=True,
            netvm=None,
        )
        self.nonetvm = qubes.vm.qubesvm.QubesVM(
            self.app, None, qid=4, name=qubes.tests.VMPREFIX + "nonet"
        )
        self.app.domains = qubes.app.VMCollection(self.app)
        for domain in (vm, self.netvm1, self.netvm2, self.nonetvm):
            self.app.domains._dict[domain.qid] = domain
        self.app.default_netvm = self.netvm1
        self.app.default_fw_netvm = self.netvm1
        self.addCleanup(self.cleanup_netvms)

    def cleanup_netvms(self):
        self.netvm1.close()
        self.netvm2.close()
        self.nonetvm.close()
        try:
            self.app.domains.close()
        except AttributeError:
            pass
        del self.netvm1
        del self.netvm2
        del self.nonetvm
        del self.app.default_netvm
        del self.app.default_fw_netvm

    @qubes.tests.skipUnlessDom0
    def test_140_netvm(self):
        vm = self.get_vm()
        self.setup_netvms(vm)
        self.assertPropertyDefaultValue(vm, "netvm", self.app.default_netvm)
        self.assertPropertyValue(
            vm, "netvm", self.netvm2, self.netvm2, self.netvm2.name
        )
        del vm.netvm
        self.assertPropertyDefaultValue(vm, "netvm", self.app.default_netvm)
        self.assertPropertyValue(
            vm, "netvm", self.netvm2.name, self.netvm2, self.netvm2.name
        )
        self.assertPropertyValue(vm, "netvm", None, None, "")

    def test_141_netvm_invalid(self):
        vm = self.get_vm()
        self.setup_netvms(vm)
        self.assertPropertyInvalidValue(vm, "netvm", "invalid")
        self.assertPropertyInvalidValue(vm, "netvm", 123)

    def test_142_netvm_netvm(self):
        vm = self.get_vm()
        self.setup_netvms(vm)
        self.assertPropertyInvalidValue(vm, "netvm", self.nonetvm)

    def test_143_netvm_loopback(self):
        vm = self.get_vm()
        self.app.domains = {1: vm, vm: vm}
        self.addCleanup(self.app.domains.clear)
        self.assertPropertyInvalidValue(vm, "netvm", vm)

    def test_144_netvm_loopback2(self):
        vm = self.get_vm()
        self.setup_netvms(vm)
        vm.netvm = None
        self.netvm2.netvm = self.netvm1
        vm.provides_network = True
        self.netvm1.netvm = vm
        self.assertPropertyInvalidValue(vm, "netvm", self.netvm2)

    def test_145_netvm_change(self):
        vm = self.get_vm()
        self.setup_netvms(vm)
        with (
            patch("qubes.vm.qubesvm.QubesVM.is_running", lambda x: True),
            patch("qubes.vm.mix.net.NetVMMixin.attach_network") as mock_attach,
            patch("qubes.vm.mix.net.NetVMMixin.detach_network") as mock_detach,
            patch("qubes.vm.qubesvm.QubesVM.create_qdb_entries"),
        ):

            with self.subTest("setting netvm to none"):
                vm.netvm = None
                mock_detach.assert_called_once()
                mock_attach.assert_not_called()
                mock_detach.reset_mock()

            with self.subTest("connecting netvm again"):
                vm.netvm = self.netvm1
                mock_detach.assert_not_called()
                mock_attach.assert_called_once()
                mock_attach.reset_mock()

            with self.subTest("changing netvm"):
                vm.netvm = self.netvm2
                mock_detach.assert_called_once()
                mock_attach.assert_called_once()
                mock_detach.reset_mock()
                mock_attach.reset_mock()

            with self.subTest("resetting netvm to default"):
                del vm.netvm
                mock_detach.assert_called_once()
                mock_attach.assert_called_once()
                mock_detach.reset_mock()
                mock_attach.reset_mock()

    def test_146_netvm_defer(self):
        vm = self.get_vm()
        self.setup_netvms(vm)
        with (
            patch("qubes.vm.qubesvm.QubesVM.is_running", lambda x: True),
            patch("qubes.vm.qubesvm.QubesVM.is_paused", lambda x: True),
            patch("qubes.vm.mix.net.NetVMMixin.attach_network") as mock_attach,
            patch("qubes.vm.mix.net.NetVMMixin.detach_network") as mock_detach,
            patch("qubes.vm.qubesvm.QubesVM.create_qdb_entries"),
            patch("qubes.vm.qubesvm.QubesVM.run_service_for_stdio"),
        ):

            with self.subTest("try to apply deferred netvm when not set"):
                with patch(
                    "qubes.vm.qubesvm.QubesVM.is_paused", lambda x: False
                ):
                    self.loop.run_until_complete(vm.apply_deferred_netvm())
                    mock_detach.assert_not_called()
                    mock_attach.assert_not_called()

            mock_detach.reset_mock()
            mock_attach.reset_mock()
            with self.subTest("changing netvm and restoring original netvm"):
                original_netvm = vm.netvm.name
                vm.netvm = self.netvm2
                mock_detach.assert_not_called()
                mock_attach.assert_not_called()
                self.assertEqual(
                    vm.features.get("deferred-netvm-original", None),
                    original_netvm,
                )
                vm.netvm = original_netvm
                self.assertEqual(
                    vm.features.get("deferred-netvm-original", None), None
                )
                mock_detach.assert_not_called()
                mock_attach.assert_not_called()

            mock_detach.reset_mock()
            mock_attach.reset_mock()
            with self.subTest(
                "changing netvm and restoring original netvm from none"
            ):
                original_netvm = vm.netvm.name
                with patch(
                    "qubes.vm.qubesvm.QubesVM.is_paused", lambda x: False
                ):
                    vm.netvm = None
                mock_detach.reset_mock()
                mock_attach.reset_mock()
                vm.netvm = original_netvm
                mock_detach.assert_not_called()
                mock_attach.assert_not_called()
                self.assertEqual(
                    vm.features.get("deferred-netvm-original", None),
                    "",
                )
                vm.netvm = None
                self.assertEqual(
                    vm.features.get("deferred-netvm-original", None), None
                )
                mock_detach.assert_not_called()
                mock_attach.assert_not_called()
                with patch(
                    "qubes.vm.qubesvm.QubesVM.is_paused", lambda x: False
                ):
                    vm.netvm = original_netvm

            mock_detach.reset_mock()
            mock_attach.reset_mock()
            with self.subTest("changing netvm"):
                original_netvm = vm.netvm.name
                vm.netvm = self.netvm2
                mock_detach.assert_not_called()
                mock_attach.assert_not_called()
                self.assertEqual(
                    vm.features.get("deferred-netvm-original", None),
                    original_netvm,
                )
                with patch(
                    "qubes.vm.qubesvm.QubesVM.is_paused", lambda x: False
                ):
                    self.loop.run_until_complete(vm.apply_deferred_netvm())
                self.assertEqual(
                    vm.features.get("deferred-netvm-original", None), None
                )
                mock_detach.assert_called()
                mock_attach.assert_called()

            mock_detach.reset_mock()
            mock_attach.reset_mock()
            with self.subTest("setting netvm to none"):
                original_netvm = vm.netvm.name
                vm.netvm = None
                mock_detach.assert_not_called()
                mock_attach.assert_not_called()
                self.assertEqual(
                    vm.features.get("deferred-netvm-original", None),
                    original_netvm,
                )
                with patch(
                    "qubes.vm.qubesvm.QubesVM.is_paused", lambda x: False
                ):
                    self.loop.run_until_complete(vm.apply_deferred_netvm())
                self.assertEqual(
                    vm.features.get("deferred-netvm-original", None), None
                )
                mock_detach.assert_called()
                mock_attach.assert_not_called()

            mock_detach.reset_mock()
            mock_attach.reset_mock()
            with self.subTest("resetting netvm to default"):
                original_netvm = vm.netvm.name if vm.netvm else ""
                del vm.netvm
                mock_detach.assert_not_called()
                mock_attach.assert_not_called()
                self.assertEqual(
                    vm.features.get("deferred-netvm-original", None),
                    original_netvm,
                )
                with patch(
                    "qubes.vm.qubesvm.QubesVM.is_paused", lambda x: False
                ):
                    self.loop.run_until_complete(vm.apply_deferred_netvm())
                self.assertEqual(
                    vm.features.get("deferred-netvm-original", None), None
                )
                mock_detach.assert_called()
                mock_attach.assert_called_once()

            mock_detach.reset_mock()
            mock_attach.reset_mock()
            with self.subTest("skip apply of preload"):
                original_netvm = vm.netvm.name
                vm.is_preload = True
                vm.netvm = self.netvm2
                mock_detach.assert_not_called()
                mock_attach.assert_not_called()
                self.assertEqual(
                    vm.features.get("deferred-netvm-original", None),
                    original_netvm,
                )
                with patch(
                    "qubes.vm.qubesvm.QubesVM.is_paused", lambda x: False
                ):
                    self.loop.run_until_complete(vm.apply_deferred_netvm())
                self.assertEqual(
                    vm.features.get("deferred-netvm-original", None),
                    original_netvm,
                )
                mock_detach.assert_not_called()
                mock_attach.assert_not_called()
            vm.is_preload = False
            del vm.features["deferred-netvm-original"]

    def test_150_ip(self):
        vm = self.get_vm()
        self.setup_netvms(vm)
        self.assertPropertyDefaultValue(
            vm, "ip", ipaddress.IPv4Address("10.137.0." + str(vm.qid))
        )
        vm.ip = "192.168.1.1"
        self.assertEqual(vm.ip, ipaddress.IPv4Address("192.168.1.1"))

    def test_151_ip_invalid(self):
        vm = self.get_vm()
        self.setup_netvms(vm)
        self.assertPropertyInvalidValue(vm, "ip", "abcd")
        self.assertPropertyInvalidValue(vm, "ip", "a.b.c.d")
        self.assertPropertyInvalidValue(vm, "ip", "1111.2222.3333.4444")
        # TODO: implement and add here: 0.0.0.0, 333.333.333.333

    def test_160_ip6(self):
        vm = self.get_vm()
        self.setup_netvms(vm)
        self.assertPropertyDefaultValue(vm, "ip6", None)
        vm.netvm.features["ipv6"] = True
        self.assertPropertyDefaultValue(
            vm,
            "ip6",
            ipaddress.IPv6Address(
                "{}::a89:{:x}".format(qubes.config.qubes_ipv6_prefix, vm.qid)
            ),
        )
        vm.ip6 = "abcd:efff::1"
        self.assertEqual(vm.ip6, ipaddress.IPv6Address("abcd:efff::1"))

    def test_161_ip6_invalid(self):
        vm = self.get_vm()
        self.setup_netvms(vm)
        vm.netvm.features["ipv6"] = True
        self.assertPropertyInvalidValue(vm, "ip", "zzzz")
        self.assertPropertyInvalidValue(
            vm, "ip", "1:2:3:4:5:6:7:8:0:a:b:c:d:e:f:0"
        )

    def test_170_provides_network_netvm(self):
        vm = self.get_vm()
        vm2 = self.get_vm("test2", qid=3)
        self.assertPropertyDefaultValue(vm, "provides_network", False)
        self.assertPropertyInvalidValue(vm2, "netvm", vm)
        self.assertPropertyValue(vm, "provides_network", True, True, "True")
        self.assertPropertyValue(vm2, "netvm", vm, vm, "test-inst-test")
        # used by other vm
        self.assertPropertyInvalidValue(vm, "provides_network", False)
        self.assertPropertyValue(vm2, "netvm", None, None, "")
        self.assertPropertyValue(vm2, "netvm", "", None, "")
        self.assertPropertyValue(vm, "provides_network", False, False, "False")

    @patch("qubes.vm.qubesvm.QubesVM.libvirt_domain")
    @patch("qubes.vm.qubesvm.QubesVM.is_halted", return_value=False)
    def test_180_shutdown(self, mock_halted, mock_shutdown):
        # pylint: disable=unused-argument
        vm = self.get_vm()
        self.setup_netvms(vm)
        with patch.object(vm, "is_running", return_value=True):
            vm.is_preload = False
            with self.assertRaises(qubes.exc.QubesVMInUseError):
                self.loop.run_until_complete(vm.netvm.shutdown())
            vm.is_preload = True
            self.loop.run_until_complete(vm.netvm.shutdown())

    def test_200_vmid_to_ipv4(self):
        testcases = (
            (1, "0.1"),
            (2, "0.2"),
            (254, "0.254"),
            (255, "1.1"),
            (256, "1.2"),
            (257, "1.3"),
            (508, "1.254"),
            (509, "2.1"),
            (510, "2.2"),
            (511, "2.3"),
            (512, "2.4"),
            (513, "2.5"),
        )
        for vmid, ip in testcases:
            with self.subTest(str(vmid)):
                self.assertEqual(
                    ipaddress.IPv4Address("1.1." + ip),
                    vmid_to_ipv4("1.1", vmid),
                )
