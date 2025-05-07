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

import unittest
import unittest.mock as mock

import asyncio

import qubes.events
import qubes.vm.dispvm
import qubes.vm.appvm
import qubes.vm.templatevm
import qubes.tests
import qubes.tests.vm
import qubes.tests.vm.appvm


class TestApp(qubes.tests.vm.TestApp):
    def __init__(self):
        super(TestApp, self).__init__()
        self.qid_counter = 1

    def add_new_vm(self, cls, **kwargs):
        qid = self.qid_counter
        self.qid_counter += 1
        vm = cls(self, None, qid=qid, **kwargs)
        self.domains[vm.name] = vm
        self.domains[vm] = vm
        return vm


class TC_00_DispVM(qubes.tests.QubesTestCase):
    def setUp(self):
        super(TC_00_DispVM, self).setUp()
        self.app = TestApp()
        self.app.save = mock.Mock()
        self.app.pools["default"] = qubes.tests.vm.appvm.TestPool(
            name="default"
        )
        self.app.pools["linux-kernel"] = qubes.tests.vm.appvm.TestPool(
            name="linux-kernel"
        )
        self.app.vmm.offline_mode = True
        self.template = self.app.add_new_vm(
            qubes.vm.templatevm.TemplateVM, name="test-template", label="red"
        )
        self.appvm = self.app.add_new_vm(
            qubes.vm.appvm.AppVM,
            name="test-vm",
            template=self.template,
            label="red",
        )
        self.app.domains[self.appvm.name] = self.appvm
        self.app.domains[self.appvm] = self.appvm
        self.addCleanup(self.cleanup_dispvm)
        self.emitter = qubes.tests.TestEmitter()

    def tearDown(self):
        del self.emitter
        super(TC_00_DispVM, self).tearDown()

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

    @mock.patch("os.symlink")
    @mock.patch("os.makedirs")
    @mock.patch("qubes.storage.Storage")
    def test_000_from_appvm(self, mock_storage, mock_makedirs, mock_symlink):
        mock_storage.return_value.create.side_effect = self.mock_coro
        self.appvm.template_for_dispvms = True
        orig_getitem = self.app.domains.__getitem__
        with mock.patch.object(
            self.app, "domains", wraps=self.app.domains
        ) as mock_domains:
            mock_domains.configure_mock(
                **{
                    "get_new_unused_dispid": mock.Mock(return_value=42),
                    "__getitem__.side_effect": orig_getitem,
                }
            )
            dispvm = self.loop.run_until_complete(
                qubes.vm.dispvm.DispVM.from_appvm(self.appvm)
            )
            mock_domains.get_new_unused_dispid.assert_called_once_with()
        self.assertEqual(dispvm.name, "disp42")
        self.assertEqual(dispvm.template, self.appvm)
        self.assertEqual(dispvm.label, self.appvm.label)
        self.assertEqual(dispvm.auto_cleanup, True)
        mock_makedirs.assert_called_once_with(
            "/var/lib/qubes/appvms/" + dispvm.name, mode=0o775, exist_ok=True
        )
        mock_symlink.assert_not_called()

    @mock.patch("qubes.storage.Storage")
    def test_000_from_appvm_preload_reject_max(self, mock_storage):
        mock_storage.return_value.create.side_effect = self.mock_coro
        self.appvm.template_for_dispvms = True
        orig_getitem = self.app.domains.__getitem__
        self.appvm.features["preload-dispvm-max"] = "0"
        with mock.patch.object(
            self.app, "domains", wraps=self.app.domains
        ) as mock_domains:
            mock_domains.configure_mock(
                **{
                    "get_new_unused_dispid": mock.Mock(return_value=42),
                    "__getitem__.side_effect": orig_getitem,
                }
            )
            with self.assertRaises(qubes.exc.QubesException):
                self.loop.run_until_complete(
                    qubes.vm.dispvm.DispVM.from_appvm(self.appvm, preload=True)
                )
            mock_domains.get_new_unused_dispid.assert_not_called()

    #@mock.patch("qubes.vm.dispvm.DispVM.start")
    #@mock.patch("qubes.vm.qubesvm.QubesVM.start")
    #@mock.patch("qubes.vm.dispvm.libvirt")

    @mock.patch("qubes.vm.dispvm.DispVM.create_qdb_entries")
    @mock.patch("qubes.vm.LocalVM.start_qdb_watch")
    @mock.patch("qubes.vm.qubesvm.QubesVM.start_qdb_watch")
    @mock.patch("qubes.vm.qubesvm.QubesVM.create_qdb_entries")
    @mock.patch("qubes.vm.qubesvm.QubesVM.untrusted_qdb")
    @mock.patch("qubes.vm.qubesvm.QubesVM.start_daemon")
    @mock.patch("qubes.vm.qubesvm.QubesVM.is_running")
    @mock.patch("qubes.vm.qubesvm.QubesVM.start_qubesdb")
    @mock.patch("qubes.vm.qubesvm.QubesVM.libvirt_domain")
    @mock.patch("qubes.vm.qubesvm.QubesVM._update_libvirt_domain")
    @mock.patch("qubes.vm.qubesvm.QubesVM.request_memory")

    #@mock.patch("qubes.vm.qubesvm.QubesVM.start")
    @mock.patch("os.symlink")
    @mock.patch("os.makedirs")
    @mock.patch("qubes.storage.Storage")
    def test_000_from_appvm_preload_only(
        self,
        mock_storage,
        mock_makedirs,
        mock_symlink,
        #mock_start,

        mock_req_mem,
        mock_update_libvirt_domain,
        mock_libvirt_domain,
        mock_start_qubesdb,
        mock_is_running,
        mock_start_daemon,
        mock_untrusted_qdb,
        mock_create_qdb_entries,
        mock_start_qdb_watch,
        mock_localvm_start_qdb_watch,
        mock_dispvm_create_qdb_entries,

        #mock_libvirt,
        #mock_start,
        #mock_dispvm_start,
    ):
        mock_storage.return_value.create.side_effect = self.mock_coro
        mock_storage.return_value.verify.side_effect = self.mock_coro
        mock_storage.return_value.start.side_effect = self.mock_coro
        mock_storage.return_value.stop.side_effect = self.mock_coro
        mock_storage.return_value.remove.side_effect = self.mock_coro

        #async def test_start(self, start_guid):
        #    await self.fire_event_async("domain-start", start_guid=start_guid)

        mock_req_mem.side_effect = self.mock_coro
        mock_update_libvirt_domain.side_effect = self.mock_coro
        mock_libvirt_domain.side_effect = self.mock_coro
        mock_start_qubesdb.side_effect = self.mock_coro
        mock_is_running.return_value = True
        mock_start_daemon.side_effect = self.mock_coro
        mock_untrusted_qdb.side_effect = True
        mock_create_qdb_entries.side_effect = self.mock_coro
        mock_start_qdb_watch.side_effect = self.mock_coro
        mock_localvm_start_qdb_watch.side_effect = self.mock_coro
        mock_dispvm_create_qdb_entries.side_effect = self.mock_coro

        #mock_dispvm_start.side_effect = self.mock_coro

        self.appvm.template_for_dispvms = True
        self.appvm.features["preload-dispvm-max"] = "1"

        orig_getitem = self.app.domains.__getitem__
        import libvirt
        with mock.patch.object(
            self.app, "domains", wraps=self.app.domains
        ) as mock_domains, \
        mock.patch.object(self.app.vmm, "offline_mode", True), \
        mock.patch.object(libvirt, "VIR_DOMAIN_START_PAUSED", True) \
        :
            # Circumvent checks made against self.app.domains.
            mock_qube = mock.Mock()
            mock_qube.template = self.appvm
            #mock_qube.start = test_start

            mock_domains.configure_mock(
                **{
                    "get_new_unused_dispid": mock.Mock(return_value=42),
                    "__contains__.return_value": True,
                    "__getitem__.side_effect": lambda key: mock_qube
                    if key == "disp42"
                    else orig_getitem(key),
                }
            )
            mock_qube.untrusted_qdb = False
            mock_qube.is_running = True
            dispvm = self.loop.run_until_complete(
                qubes.vm.dispvm.DispVM.from_appvm(self.appvm, preload=True)
            )
            mock_domains.get_new_unused_dispid.assert_called_once_with()
        self.assertTrue(dispvm.is_preloaded())
        self.assertTrue(dispvm.features.get("internal", False))
        self.assertEqual(self.appvm.get_feat_preload(), ["disp42"])
        self.assertEqual(dispvm.name, "disp42")
        self.assertEqual(dispvm.template, self.appvm)
        self.assertEqual(dispvm.label, self.appvm.label)
        self.assertEqual(dispvm.auto_cleanup, True)
        mock_makedirs.assert_called_once_with(
            "/var/lib/qubes/appvms/" + dispvm.name, mode=0o775, exist_ok=True
        )
        mock_symlink.assert_not_called()


    #@mock.patch("asyncio.wait_for")
    #@mock.patch("asyncio.sleep")
    #@mock.patch("qubes.vm.dispvm.DispVM.preload")
    #@mock.patch("qubes.vm.dispvm.DispVM.use_preloaded")
    #@mock.patch("qubes.events.Emitter.fire_event_async")
    #@mock.patch(
    #    "qubes.vm.mix.dvmtemplate.DVMTemplateMixin.on_domain_preloaded_dispvm_used"
    #)
    #@mock.patch("qubes.vm.qubesvm.QubesVM.unpause")
    #@mock.patch("qubes.vm.qubesvm.QubesVM.pause")
    #@mock.patch("qubes.vm.dispvm.DispVM.start")
    #@mock.patch("os.symlink")
    #@mock.patch("os.makedirs")
    #@mock.patch("qubes.storage.Storage")
    #def test_000_from_appvm_preload_use(
    #    self,
    #    mock_storage,
    #    mock_makedirs,
    #    mock_symlink,
    #    mock_dispvm_start,
    #    mock_pause,
    #    mock_unpause,
    #    mock_preloaded_used,
    #    mock_event_async,
    #    mock_use_preloaded,
    #    mock_preload,
    #    mock_asyncio_sleep,
    #    mock_asyncio_wait_for,
    #):
    #    mock_storage.return_value.create.side_effect = self.mock_coro
    #    mock_dispvm_start.side_effect = self.mock_coro
    #    mock_pause.side_effect = self.mock_coro
    #    mock_unpause.side_effect = self.mock_coro
    #    #mock_preloaded_used.side_effect = self.mock_coro
    #    #mock_event_async.side_effect = self.mock_coro
    #    #mock_use_preloaded.side_effect = self.mock_coro
    #    #mock_preload.side_effect = self.mock_coro
    #    mock_asyncio_sleep.side_effect = self.mock_coro
    #    mock_asyncio_wait_for.side_effect = self.mock_coro

    #    self.app.domains[self.appvm].fire_event = self.emitter.fire_event
    #    #self.appvm.fire_event_async = self.mock_coro
    #    self.appvm.template_for_dispvms = True
    #    self.appvm.features["preload-dispvm-max"] = "1"

    #    orig_getitem = self.app.domains.__getitem__
    #    with mock.patch.object(
    #        self.app, "domains", wraps=self.app.domains
    #    ) as mock_domains:
    #        # Circumvent checks made against self.app.domains.
    #        mock_qube = mock.Mock()
    #        mock_qube.template = self.appvm
    #        mock_domains.configure_mock(
    #            **{
    #                "get_new_unused_dispid": mock.Mock(return_value=42),
    #                "__contains__.return_value": True,
    #                "__getitem__.side_effect": lambda key: mock_qube
    #                if key == "disp42"
    #                else orig_getitem(key),
    #            }
    #        )
    #        dispvm = self.loop.run_until_complete(
    #            qubes.vm.dispvm.DispVM.from_appvm(self.appvm, preload=True)
    #        )
    #        mock_domains.get_new_unused_dispid.assert_called_once_with()

    #        #mock_domains.configure_mock(
    #        #    **{
    #        #        "get_new_unused_dispid": mock.Mock(return_value=42),
    #        #        "__getitem__.side_effect": orig_domains.__getitem__,
    #        #        "__iter__.side_effect": orig_domains.__iter__,
    #        #        "__setitem__.side_effect": orig_domains.__setitem__,
    #        #    }
    #        #)
    #        #dispvm = self.loop.run_until_complete(
    #        #    qubes.vm.dispvm.DispVM.from_appvm(self.appvm, preload=True)
    #        #)
    #        print(4)
    #        # TODO: ben: this fails on CI but not locally
    #        print("\n\n")
    #        print(f"DISPVM: {dispvm.name}")
    #        print(f"APPVM FEAT: {list(self.appvm.features.items())}")
    #        print("\n\n")
    #        mock_domains.get_new_unused_dispid.assert_called_once_with()

    #@mock.patch("qubes.vm.dispvm.DispVM.start")
    @mock.patch("qubes.vm.qubesvm.QubesVM.start")
    @mock.patch("os.symlink")
    @mock.patch("os.makedirs")
    @mock.patch("qubes.storage.Storage")
    def test_000_from_appvm_preload_use(
        self,
        mock_storage,
        mock_makedirs,
        mock_symlink,
        mock_dispvm_start,
    ):
        mock_storage.return_value.create.side_effect = self.mock_coro
        mock_dispvm_start.side_effect = self.mock_coro

        self.appvm.template_for_dispvms = True
        self.appvm.features["preload-dispvm-max"] = "1"

        orig_getitem = self.app.domains.__getitem__
        with mock.patch.object(
            self.app, "domains", wraps=self.app.domains
        ) as mock_domains:
            # Circumvent checks made against self.app.domains.
            mock_qube = mock.Mock()
            mock_qube.template = self.appvm
            mock_domains.configure_mock(
                **{
                    "get_new_unused_dispid": mock.Mock(return_value=42),
                    "__contains__.return_value": True,
                    "__getitem__.side_effect": lambda key: mock_qube
                    if key == "disp42"
                    else orig_getitem(key),
                }
            )
            dispvm = self.loop.run_until_complete(
                qubes.vm.dispvm.DispVM.from_appvm(self.appvm, preload=True)
            )
            self.assertEqual(self.appvm.get_feat_preload(), ["disp42"])
            self.assertTrue(dispvm.is_preloaded())
            self.loop.run_until_complete(dispvm.pause())

            print(f"STATE {dispvm.get_power_state()}")
            self.assertTrue(dispvm.is_paused())

            self.assertTrue(dispvm.features.get("internal", False))
            mock_qube.name = dispvm.name
            mock_qube.features = dispvm.features

            async def coroutine_mock(*args, **kwargs):
                await dispvm.unpause()
            mock_qube.unpause = coroutine_mock

            #unpause_mock = mock.Mock()
            #async def coroutine_mock(*args, **kwargs):
            #    return unpause_mock(*args, **kwargs)
            #mock_qube.unpause = coroutine_mock

            fresh_dispvm = self.loop.run_until_complete(
                qubes.vm.dispvm.DispVM.from_appvm(self.appvm)
            )
            mock_domains.get_new_unused_dispid.assert_called_once_with()

        mock_dispvm_start.assert_called_once_with()
        self.assertEqual(dispvm.name, fresh_dispvm.name)
        #unpause_mock.assert_called_once_with()
        #dispvm.on_domain_unpaused("domain-unpaused")
        print("\n\n")
        print(f"APP: {list(self.appvm.features.items())}")
        print(f"APP: {list(dispvm.features.items())}")
        print("\n\n")
        # TODO: ben: event not fired
        self.assertEventFired(self.emitter, "domain-preloaded-dispvm-used")
        self.assertFalse(dispvm.is_preloaded())
        self.assertFalse(dispvm.features.get("internal", False))
        self.assertEqual(self.appvm.get_feat_preload(), [])
        self.assertEqual(dispvm.name, "disp42")
        self.assertEqual(dispvm.template, self.appvm)
        self.assertEqual(dispvm.label, self.appvm.label)
        self.assertEqual(dispvm.auto_cleanup, True)
        mock_makedirs.assert_called_once_with(
            "/var/lib/qubes/appvms/" + dispvm.name, mode=0o775, exist_ok=True
        )
        mock_symlink.assert_not_called()

    def test_001_from_appvm_reject_not_allowed(self):
        with self.assertRaises(qubes.exc.QubesException):
            dispvm = self.loop.run_until_complete(
                qubes.vm.dispvm.DispVM.from_appvm(self.appvm)
            )

    @unittest.skip("test is broken")
    def test_002_template_change(self):
        self.appvm.template_for_dispvms = True
        orig_getitem = self.app.domains.__getitem__
        with mock.patch.object(
            self.app, "domains", wraps=self.app.domains
        ) as mock_domains:
            mock_domains.configure_mock(
                **{
                    "get_new_unused_dispid": mock.Mock(return_value=42),
                    "__getitem__.side_effect": orig_getitem,
                }
            )
            self.dispvm = self.app.add_new_vm(
                qubes.vm.dispvm.DispVM, name="test-dispvm", template=self.appvm
            )

            self.dispvm.template = self.appvm
            self.loop.run_until_complete(self.dispvm.start())
            if not self.app.vmm.offline_mode:
                assert not dispvm.is_halted()
                with self.assertRaises(qubes.exc.QubesVMNotHaltedError):
                    self.dispvm.template = self.appvm
            with self.assertRaises(qubes.exc.QubesValueError):
                self.dispvm.template = qubes.property.DEFAULT
            self.loop.run_until_complete(self.dispvm.kill())
            self.dispvm.template = self.appvm

    def test_003_dvmtemplate_template_change(self):
        self.appvm.template_for_dispvms = True
        orig_domains = self.app.domains
        with mock.patch.object(
            self.app, "domains", wraps=self.app.domains
        ) as mock_domains:
            mock_domains.configure_mock(
                **{
                    "get_new_unused_dispid": mock.Mock(return_value=42),
                    "__getitem__.side_effect": orig_domains.__getitem__,
                    "__iter__.side_effect": orig_domains.__iter__,
                    "__setitem__.side_effect": orig_domains.__setitem__,
                }
            )
            self.dispvm = self.app.add_new_vm(
                qubes.vm.dispvm.DispVM, name="test-dispvm", template=self.appvm
            )

            self.appvm.template = self.template
            with self.assertRaises(qubes.exc.QubesValueError):
                self.appvm.template = qubes.property.DEFAULT

    def test_004_dvmtemplate_allowed_change(self):
        self.appvm.template_for_dispvms = True
        orig_domains = self.app.domains
        with mock.patch.object(
            self.app, "domains", wraps=self.app.domains
        ) as mock_domains:
            mock_domains.configure_mock(
                **{
                    "get_new_unused_dispid": mock.Mock(return_value=42),
                    "__getitem__.side_effect": orig_domains.__getitem__,
                    "__iter__.side_effect": orig_domains.__iter__,
                    "__setitem__.side_effect": orig_domains.__setitem__,
                }
            )
            self.dispvm = self.app.add_new_vm(
                qubes.vm.dispvm.DispVM, name="test-dispvm", template=self.appvm
            )

            with self.assertRaises(qubes.exc.QubesVMInUseError):
                self.appvm.template_for_dispvms = False

    def test_010_create_direct(self):
        self.appvm.template_for_dispvms = True
        orig_getitem = self.app.domains.__getitem__
        with mock.patch.object(
            self.app, "domains", wraps=self.app.domains
        ) as mock_domains:
            mock_domains.configure_mock(
                **{
                    "get_new_unused_dispid": mock.Mock(return_value=42),
                    "__getitem__.side_effect": orig_getitem,
                }
            )
            self.dispvm = self.app.add_new_vm(
                qubes.vm.dispvm.DispVM, name="test-dispvm", template=self.appvm
            )
            mock_domains.get_new_unused_dispid.assert_called_once_with()
        dispvm = self.dispvm
        self.assertEqual(dispvm.name, "test-dispvm")
        self.assertEqual(dispvm.template, self.appvm)
        self.assertEqual(dispvm.label, self.appvm.label)
        self.assertEqual(dispvm.label, self.appvm.label)
        self.assertEqual(dispvm.auto_cleanup, False)

    def test_011_create_direct_generate_name(self):
        self.appvm.template_for_dispvms = True
        orig_getitem = self.app.domains.__getitem__
        with mock.patch.object(
            self.app, "domains", wraps=self.app.domains
        ) as mock_domains:
            mock_domains.configure_mock(
                **{
                    "get_new_unused_dispid": mock.Mock(return_value=42),
                    "__getitem__.side_effect": orig_getitem,
                }
            )
            dispvm = self.app.add_new_vm(
                qubes.vm.dispvm.DispVM, template=self.appvm
            )
            mock_domains.get_new_unused_dispid.assert_called_once_with()
        self.assertEqual(dispvm.name, "disp42")
        self.assertEqual(dispvm.template, self.appvm)
        self.assertEqual(dispvm.label, self.appvm.label)
        self.assertEqual(dispvm.auto_cleanup, False)

    def test_011_create_direct_reject(self):
        orig_getitem = self.app.domains.__getitem__
        with mock.patch.object(
            self.app, "domains", wraps=self.app.domains
        ) as mock_domains:
            mock_domains.configure_mock(
                **{
                    "get_new_unused_dispid": mock.Mock(return_value=42),
                    "__getitem__.side_effect": orig_getitem,
                }
            )
            with self.assertRaises(qubes.exc.QubesException):
                self.app.add_new_vm(
                    qubes.vm.dispvm.DispVM,
                    name="test-dispvm",
                    template=self.appvm,
                )
            self.assertFalse(mock_domains.get_new_unused_dispid.called)

    @mock.patch("os.symlink")
    @mock.patch("os.makedirs")
    def test_020_copy_storage_pool(self, mock_makedirs, mock_symlink):
        self.app.pools["alternative"] = qubes.tests.vm.appvm.TestPool(
            name="alternative"
        )
        self.appvm.template_for_dispvms = True
        self.loop.run_until_complete(self.template.create_on_disk())
        self.loop.run_until_complete(
            self.appvm.create_on_disk(pool="alternative")
        )
        orig_getitem = self.app.domains.__getitem__
        with mock.patch.object(
            self.app, "domains", wraps=self.app.domains
        ) as mock_domains:
            mock_domains.configure_mock(
                **{
                    "get_new_unused_dispid": mock.Mock(return_value=42),
                    "__getitem__.side_effect": orig_getitem,
                }
            )
            dispvm = self.app.add_new_vm(
                qubes.vm.dispvm.DispVM, name="test-dispvm", template=self.appvm
            )
            self.loop.run_until_complete(dispvm.create_on_disk())
        self.assertIs(dispvm.template, self.appvm)
        self.assertIs(
            dispvm.volumes["private"].pool, self.appvm.volumes["private"].pool
        )
        self.assertIs(
            dispvm.volumes["root"].pool, self.appvm.volumes["root"].pool
        )
        self.assertIs(
            dispvm.volumes["volatile"].pool,
            self.appvm.volumes["volatile"].pool,
        )
        self.assertFalse(dispvm.volumes["volatile"].ephemeral)

    def test_021_storage_template_change(self):
        self.appvm.template_for_dispvms = True
        orig_domains = self.app.domains
        with mock.patch.object(
            self.app, "domains", wraps=self.app.domains
        ) as mock_domains:
            mock_domains.configure_mock(
                **{
                    "get_new_unused_dispid": mock.Mock(return_value=42),
                    "__getitem__.side_effect": orig_domains.__getitem__,
                    "__iter__.side_effect": orig_domains.__iter__,
                    "__setitem__.side_effect": orig_domains.__setitem__,
                }
            )
            vm = self.dispvm = self.app.add_new_vm(
                qubes.vm.dispvm.DispVM, name="test-dispvm", template=self.appvm
            )
            self.assertIs(
                vm.volume_config["root"]["source"],
                self.template.volumes["root"],
            )
            # create new mock, so new template will get different volumes
            self.app.pools["default"] = mock.Mock(
                **{"init_volume.return_value.pool": "default"}
            )
            template2 = qubes.vm.templatevm.TemplateVM(
                self.app, None, qid=3, name=qubes.tests.VMPREFIX + "template2"
            )
            self.app.domains[template2.name] = template2
            self.app.domains[template2] = template2
            self.appvm.template = template2

        self.assertFalse(vm.volume_config["root"]["save_on_stop"])
        self.assertTrue(vm.volume_config["root"]["snap_on_start"])
        self.assertNotEqual(
            vm.volume_config["root"]["source"], self.template.volumes["root"]
        )
        self.assertIs(
            vm.volume_config["root"]["source"], template2.volumes["root"]
        )
        self.assertIs(
            vm.volume_config["root"]["source"],
            self.appvm.volume_config["root"]["source"],
        )
        self.assertIs(
            vm.volume_config["private"]["source"],
            self.appvm.volumes["private"],
        )

    def test_022_storage_app_change(self):
        self.appvm.template_for_dispvms = True
        self.assertTrue(self.appvm.events_enabled)
        orig_domains = self.app.domains
        with mock.patch.object(
            self.app, "domains", wraps=self.app.domains
        ) as mock_domains:
            mock_domains.configure_mock(
                **{
                    "get_new_unused_dispid": mock.Mock(return_value=42),
                    "__getitem__.side_effect": orig_domains.__getitem__,
                    "__iter__.side_effect": orig_domains.__iter__,
                    "__setitem__.side_effect": orig_domains.__setitem__,
                }
            )
            vm = self.dispvm = self.app.add_new_vm(
                qubes.vm.dispvm.DispVM, name="test-dispvm", template=self.appvm
            )
            self.assertTrue(vm.events_enabled)
            # create new mock, so new template will get different volumes
            self.app.pools["default"] = mock.Mock(
                **{"init_volume.return_value.pool": "default"}
            )
            template2 = qubes.vm.templatevm.TemplateVM(
                self.app, None, qid=3, name=qubes.tests.VMPREFIX + "template2"
            )
            self.assertTrue(template2.events_enabled)
            self.app.domains[template2.name] = template2
            self.app.domains[template2] = template2
            app2 = qubes.vm.appvm.AppVM(
                self.app,
                None,
                qid=4,
                name=qubes.tests.VMPREFIX + "app2",
                template=template2,
            )
            self.assertTrue(app2.events_enabled)
            app2.template_for_dispvms = True
            self.app.domains[app2.name] = app2
            self.app.domains[app2] = app2
            self.dispvm.template = app2

        self.assertIs(vm, self.dispvm)
        self.assertFalse(vm.volume_config["root"]["save_on_stop"])
        self.assertTrue(vm.volume_config["root"]["snap_on_start"])
        self.assertFalse(vm.volume_config["private"]["save_on_stop"])
        self.assertTrue(vm.volume_config["private"]["snap_on_start"])
        self.assertNotEqual(
            vm.volume_config["root"]["source"], self.template.volumes["root"]
        )
        self.assertNotEqual(
            vm.volume_config["root"]["source"],
            self.appvm.volumes["root"].source,
        )
        self.assertNotEqual(
            vm.volume_config["private"]["source"],
            self.appvm.volumes["private"],
        )
        self.assertIs(
            vm.volume_config["root"]["source"], template2.volumes["root"]
        )
        self.assertIs(
            app2.volume_config["root"]["source"], template2.volumes["root"]
        )
        self.assertIs(
            vm.volume_config["private"]["source"], app2.volumes["private"]
        )

    @mock.patch("os.symlink")
    @mock.patch("os.makedirs")
    def test_023_inherit_ephemeral(self, mock_makedirs, mock_symlink):
        self.app.pools["alternative"] = qubes.tests.vm.appvm.TestPool(
            name="alternative"
        )
        self.appvm.template_for_dispvms = True
        self.loop.run_until_complete(self.template.create_on_disk())
        self.loop.run_until_complete(self.appvm.create_on_disk())
        self.appvm.volumes["volatile"].ephemeral = True
        orig_getitem = self.app.domains.__getitem__
        with mock.patch.object(
            self.app, "domains", wraps=self.app.domains
        ) as mock_domains:
            mock_domains.configure_mock(
                **{
                    "get_new_unused_dispid": mock.Mock(return_value=42),
                    "__getitem__.side_effect": orig_getitem,
                }
            )
            dispvm = self.app.add_new_vm(
                qubes.vm.dispvm.DispVM, name="test-dispvm", template=self.appvm
            )
            self.loop.run_until_complete(dispvm.create_on_disk())
        self.assertIs(dispvm.template, self.appvm)
        self.assertTrue(dispvm.volumes["volatile"].ephemeral)
