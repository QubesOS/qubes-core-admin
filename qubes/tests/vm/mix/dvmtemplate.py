# pylint: disable=protected-access

#
# The Qubes OS Project, https://www.qubes-os.org/
#
# Copyright (C) 2025  Benjamin Grande M. S. <ben.grande.b@gmail.com>
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

from unittest import mock

import qubes
import qubes.vm.qubesvm

import qubes.tests
import qubes.tests.vm
import qubes.tests.vm.appvm
import qubes.tests.vm.qubesvm
import qubes.vm.mix.dvmtemplate


class TestApp(qubes.tests.vm.TestApp):
    def __init__(self):
        super(TestApp, self).__init__()
        self.qid_counter = 0

    def add_new_vm(self, cls, **kwargs):
        qid = self.qid_counter
        if self.qid_counter == 0:
            self.qid_counter += 1
            vm = cls(self, None, **kwargs)
        else:
            self.qid_counter += 1
            vm = cls(self, None, qid=qid, **kwargs)
        self.domains[vm.name] = vm
        self.domains[vm] = vm
        return vm


class TC_00_DVMTemplateMixin(
    qubes.tests.vm.qubesvm.QubesVMTestsMixin,
    qubes.tests.QubesTestCase,
):
    def setUp(self):
        super(TC_00_DVMTemplateMixin, self).setUp()
        self.app = TestApp()
        self.app.save = mock.Mock()
        self.app.pools["default"] = qubes.tests.vm.appvm.TestPool(
            name="default"
        )
        self.app.pools["linux-kernel"] = qubes.tests.vm.appvm.TestPool(
            name="linux-kernel"
        )
        self.app.vmm.offline_mode = True
        self.adminvm = self.app.add_new_vm(qubes.vm.adminvm.AdminVM)
        self.addCleanup(self.cleanup_adminvm)
        self.template = self.app.add_new_vm(
            qubes.vm.templatevm.TemplateVM, name="test-template", label="red"
        )
        self.appvm = self.app.add_new_vm(
            qubes.vm.appvm.AppVM,
            name="test-vm",
            template=self.template,
            label="red",
        )
        self.appvm.template_for_dispvms = True
        self.appvm.features["qrexec"] = True
        self.appvm.features["gui"] = False
        self.appvm.features["supported-rpc.qubes.WaitForRunningSystem"] = True
        self.app.domains[self.appvm.name] = self.appvm
        self.app.domains[self.appvm] = self.appvm
        self.app.default_dispvm = self.appvm
        self.addCleanup(self.cleanup_dispvm)
        self.emitter = qubes.tests.TestEmitter()

    def tearDown(self):
        self.app.default_dispvm = None
        del self.emitter
        super(TC_00_DVMTemplateMixin, self).tearDown()

    def cleanup_adminvm(self):
        self.adminvm.close()
        del self.adminvm

    def cleanup_dispvm(self):
        if hasattr(self, "dispvm"):
            self.dispvm.close()
            del self.dispvm
        self.template.close()
        self.appvm.close()
        del self.template
        del self.appvm
        self.app.domains.clear()
        self.app.pools.clear()

    async def mock_coro(self, *args, **kwargs):
        pass

    def test_010_dvm_preload_get_max(self):
        cases = [
            (None, 0),
            (False, 0),
            ("0", 0),
            ("2", 2),
            ("10000", 10000),
        ]
        self.assertEqual(self.appvm.get_feat_preload_max(), 0)
        for value, expected_value in cases:
            with self.subTest(value=value, expected_value=expected_value):
                self.appvm.features["preload-dispvm-max"] = value
                self.assertEqual(
                    self.appvm.get_feat_preload_max(), expected_value
                )

        self.appvm.features["qrexec"] = False
        with self.assertRaises(qubes.exc.QubesValueError):
            self.appvm.features["preload-dispvm-max"] = "1"
        self.appvm.features["qrexec"] = True
        self.appvm.features["gui"] = False
        self.appvm.features["supported-rpc.qubes.WaitForRunningSystem"] = False
        with self.assertRaises(qubes.exc.QubesValueError):
            self.appvm.features["preload-dispvm-max"] = "1"
        self.appvm.features["supported-rpc.qubes.WaitForRunningSystem"] = True
        self.appvm.features["preload-dispvm-max"] = "1"
        cases_invalid = ["a", "-1", "1 1"]
        for value in cases_invalid:
            with self.subTest(value=value):
                with self.assertRaises(qubes.exc.QubesValueError):
                    self.appvm.features["preload-dispvm-max"] = value

        # Global setting from now on.
        if "preload-dispvm-max" in self.adminvm.features:
            del self.adminvm.features["preload-dispvm-max"]
        self.appvm.features["preload-dispvm-max"] = "1"
        self.assertEqual(self.appvm.get_feat_global_preload_max(), None)
        self.assertEqual(self.appvm.get_feat_preload_max(), 1)

        self.adminvm.features["preload-dispvm-max"] = ""
        self.appvm.features["preload-dispvm-max"] = "1"
        self.assertEqual(self.appvm.get_feat_global_preload_max(), 0)
        self.assertEqual(self.appvm.get_feat_preload_max(), 0)

        self.app.default_dispvm = None
        self.assertEqual(self.appvm.get_feat_global_preload_max(), 0)
        self.assertEqual(self.appvm.get_feat_preload_max(), 1)

    @mock.patch("os.symlink")
    @mock.patch("os.makedirs")
    @mock.patch("qubes.storage.Storage")
    def test_010_dvm_preload_get_list(
        self, mock_storage, mock_makedirs, mock_symlink
    ):
        mock_storage.return_value.create.side_effect = self.mock_coro
        mock_makedirs.return_value.create.side_effect = self.mock_coro
        mock_symlink.return_value.create.side_effect = self.mock_coro
        self.assertEqual(self.appvm.get_feat_preload(), [])
        orig_getitem = self.app.domains.__getitem__
        with mock.patch.object(
            self.app, "domains", wraps=self.app.domains
        ) as mock_domains:
            mock_qube = mock.Mock()
            mock_qube.template = self.appvm
            mock_domains.configure_mock(
                **{
                    "get_new_unused_dispid": mock.Mock(return_value=42),
                    "__contains__.return_value": True,
                    "__getitem__.side_effect": lambda key: (
                        mock_qube if key == "disp42" else orig_getitem(key)
                    ),
                }
            )
            self.appvm.features["preload-dispvm-max"] = "0"
            dispvm = self.loop.run_until_complete(
                qubes.vm.dispvm.DispVM.from_appvm(self.appvm)
            )
            with self.assertRaises(qubes.exc.QubesValueError):
                # over max
                self.appvm.features["preload-dispvm"] = f"{dispvm.name}"
            self.appvm.features["preload-dispvm-max"] = "2"
            cases_invalid = [
                f"{self.appvm}",  # not derived from wanted appvm
                f"{dispvm.name} {dispvm.name}",  # duplicate
            ]
            for value in cases_invalid:
                with self.subTest(value=value):
                    with self.assertRaises(qubes.exc.QubesValueError):
                        self.appvm.features["preload-dispvm"] = value

            cases = [
                (None, []),
                (False, []),
                ("", []),
                (f"{dispvm.name}", [dispvm.name]),
            ]
            for value, expected_value in cases:
                with self.subTest(value=value, expected_value=expected_value):
                    self.appvm.features["preload-dispvm"] = value
                    self.assertEqual(
                        self.appvm.get_feat_preload(), expected_value
                    )

    def test_010_dvm_preload_can(self):
        self.assertFalse(self.appvm.can_preload())
        self.appvm.features["preload-dispvm-max"] = 1
        cases = [
            ("", "", False),
            (0, "", False),
            (1, "", True),
        ]
        for preload_max, preload_list, expected_value in cases:
            with self.subTest(
                preload_max=preload_max,
                preload_list=preload_list,
                expected_value=expected_value,
            ):
                self.appvm.features["preload-dispvm-max"] = preload_max
                self.appvm.features["preload-dispvm"] = preload_list
                self.assertEqual(self.appvm.can_preload(), expected_value)

    @mock.patch(
        "qubes.vm.mix.dvmtemplate.DVMTemplateMixin.remove_preload_excess"
    )
    def test_011_dvm_preload_del_max(self, mock_remove_preload_excess):
        self.appvm.features["preload-dispvm-max"] = ""
        self.adminvm.features["preload-dispvm-max"] = ""
        del self.appvm.features["preload-dispvm-max"]
        mock_remove_preload_excess.assert_not_called()

        del self.adminvm.features["preload-dispvm-max"]
        self.appvm.features["preload-dispvm-max"] = ""
        del self.appvm.features["preload-dispvm-max"]
        mock_remove_preload_excess.assert_called_once_with(0)

    @mock.patch("qubes.events.Emitter.fire_event_async")
    def test_012_dvm_preload_set_max(self, mock_events):
        mock_events.side_effect = self.mock_coro
        self.appvm.features["preload-dispvm-max"] = "1"
        mock_events.assert_called_once_with(
            "domain-preload-dispvm-start", reason=mock.ANY
        )

    def test_013_dvm_preload_get_treshold(self):
        cases = [None, False, "0", "2", "1000"]
        self.assertEqual(self.appvm.get_feat_preload_threshold(), 0)
        for value in cases:
            with self.subTest(value=value):
                self.adminvm.features["preload-dispvm-threshold"] = value
                threshold = self.appvm.get_feat_preload_threshold()
                self.assertEqual(threshold, int(value or 0) * 1024**2)

    def test_100_get_preload_templates(self):
        print(qubes.vm.dispvm.get_preload_templates(self.app))
        self.appvm.features["supported-rpc.qubes.WaitForRunningSystem"] = True
        self.appvm.features["preload-dispvm-max"] = 1
        self.assertEqual(qubes.vm.dispvm.get_preload_max(self.appvm), 1)
