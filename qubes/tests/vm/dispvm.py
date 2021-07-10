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

import unittest.mock as mock

import asyncio

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
        self.app.pools['default'] = qubes.tests.vm.appvm.TestPool(name='default')
        self.app.pools['linux-kernel'] = mock.Mock(**{
            'init_volume.return_value.pool': 'linux-kernel'})
        self.app.vmm.offline_mode = True
        self.template = self.app.add_new_vm(qubes.vm.templatevm.TemplateVM,
            name='test-template', label='red')
        self.appvm = self.app.add_new_vm(qubes.vm.appvm.AppVM,
            name='test-vm', template=self.template, label='red')
        self.app.domains[self.appvm.name] = self.appvm
        self.app.domains[self.appvm] = self.appvm
        self.addCleanup(self.cleanup_dispvm)

    def cleanup_dispvm(self):
        if hasattr(self, 'dispvm'):
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

    @mock.patch('os.symlink')
    @mock.patch('os.makedirs')
    @mock.patch('qubes.storage.Storage')
    def test_000_from_appvm(self, mock_storage, mock_makedirs, mock_symlink):
        mock_storage.return_value.create.side_effect = self.mock_coro
        self.appvm.template_for_dispvms = True
        orig_getitem = self.app.domains.__getitem__
        with mock.patch.object(self.app, 'domains', wraps=self.app.domains) \
                as mock_domains:
            mock_domains.configure_mock(**{
                'get_new_unused_dispid': mock.Mock(return_value=42),
                '__getitem__.side_effect': orig_getitem
            })
            dispvm = self.loop.run_until_complete(
                qubes.vm.dispvm.DispVM.from_appvm(self.appvm))
            mock_domains.get_new_unused_dispid.assert_called_once_with()
        self.assertEqual(dispvm.name, 'disp42')
        self.assertEqual(dispvm.template, self.appvm)
        self.assertEqual(dispvm.label, self.appvm.label)
        self.assertEqual(dispvm.label, self.appvm.label)
        self.assertEqual(dispvm.auto_cleanup, True)
        mock_makedirs.assert_called_once_with(
            '/var/lib/qubes/appvms/' + dispvm.name, mode=0o775, exist_ok=True)
        mock_symlink.assert_not_called()

    def test_001_from_appvm_reject_not_allowed(self):
        with self.assertRaises(qubes.exc.QubesException):
            dispvm = self.loop.run_until_complete(
                qubes.vm.dispvm.DispVM.from_appvm(self.appvm))

    def test_002_template_change(self):
        self.appvm.template_for_dispvms = True
        orig_getitem = self.app.domains.__getitem__
        with mock.patch.object(self.app, 'domains', wraps=self.app.domains) \
                as mock_domains:
            mock_domains.configure_mock(**{
                'get_new_unused_dispid': mock.Mock(return_value=42),
                '__getitem__.side_effect': orig_getitem
            })
            self.dispvm = self.app.add_new_vm(qubes.vm.dispvm.DispVM,
                name='test-dispvm', template=self.appvm)

            self.dispvm.template = self.appvm
            self.dispvm.start()
            if not self.app.vmm.offline_mode:
                assert not dispvm.is_halted()
                with self.assertRaises(qubes.exc.QubesVMNotHaltedError):
                    self.dispvm.template = self.appvm
            with self.assertRaises(qubes.exc.QubesValueError):
                self.dispvm.template = qubes.property.DEFAULT
            self.dispvm.kill()
            self.dispvm.template = self.appvm

    def test_003_dvmtemplate_template_change(self):
        self.appvm.template_for_dispvms = True
        orig_domains = self.app.domains
        with mock.patch.object(self.app, 'domains', wraps=self.app.domains) \
                as mock_domains:
            mock_domains.configure_mock(**{
                'get_new_unused_dispid': mock.Mock(return_value=42),
                '__getitem__.side_effect': orig_domains.__getitem__,
                '__iter__.side_effect': orig_domains.__iter__,
                '__setitem__.side_effect': orig_domains.__setitem__,
            })
            self.dispvm = self.app.add_new_vm(qubes.vm.dispvm.DispVM,
                name='test-dispvm', template=self.appvm)

            self.appvm.template = self.template
            with self.assertRaises(qubes.exc.QubesValueError):
                self.appvm.template = qubes.property.DEFAULT

    def test_004_dvmtemplate_allowed_change(self):
        self.appvm.template_for_dispvms = True
        orig_domains = self.app.domains
        with mock.patch.object(self.app, 'domains', wraps=self.app.domains) \
                as mock_domains:
            mock_domains.configure_mock(**{
                'get_new_unused_dispid': mock.Mock(return_value=42),
                '__getitem__.side_effect': orig_domains.__getitem__,
                '__iter__.side_effect': orig_domains.__iter__,
                '__setitem__.side_effect': orig_domains.__setitem__,
            })
            self.dispvm = self.app.add_new_vm(qubes.vm.dispvm.DispVM,
                name='test-dispvm', template=self.appvm)

            with self.assertRaises(qubes.exc.QubesVMInUseError):
                self.appvm.template_for_dispvms = False

    def test_010_create_direct(self):
        self.appvm.template_for_dispvms = True
        orig_getitem = self.app.domains.__getitem__
        with mock.patch.object(self.app, 'domains', wraps=self.app.domains) \
                as mock_domains:
            mock_domains.configure_mock(**{
                'get_new_unused_dispid': mock.Mock(return_value=42),
                '__getitem__.side_effect': orig_getitem
            })
            self.dispvm = self.app.add_new_vm(qubes.vm.dispvm.DispVM,
                name='test-dispvm', template=self.appvm)
            mock_domains.get_new_unused_dispid.assert_called_once_with()
        dispvm=self.dispvm
        self.assertEqual(dispvm.name, 'test-dispvm')
        self.assertEqual(dispvm.template, self.appvm)
        self.assertEqual(dispvm.label, self.appvm.label)
        self.assertEqual(dispvm.label, self.appvm.label)
        self.assertEqual(dispvm.auto_cleanup, False)

    def test_011_create_direct_generate_name(self):
        self.appvm.template_for_dispvms = True
        orig_getitem = self.app.domains.__getitem__
        with mock.patch.object(self.app, 'domains', wraps=self.app.domains) \
                as mock_domains:
            mock_domains.configure_mock(**{
                'get_new_unused_dispid': mock.Mock(return_value=42),
                '__getitem__.side_effect': orig_getitem
            })
            dispvm = self.app.add_new_vm(qubes.vm.dispvm.DispVM,
                template=self.appvm)
            mock_domains.get_new_unused_dispid.assert_called_once_with()
        self.assertEqual(dispvm.name, 'disp42')
        self.assertEqual(dispvm.template, self.appvm)
        self.assertEqual(dispvm.label, self.appvm.label)
        self.assertEqual(dispvm.auto_cleanup, False)

    def test_011_create_direct_reject(self):
        orig_getitem = self.app.domains.__getitem__
        with mock.patch.object(self.app, 'domains', wraps=self.app.domains) \
                as mock_domains:
            mock_domains.configure_mock(**{
                'get_new_unused_dispid': mock.Mock(return_value=42),
                '__getitem__.side_effect': orig_getitem
            })
            with self.assertRaises(qubes.exc.QubesException):
                self.app.add_new_vm(qubes.vm.dispvm.DispVM,
                    name='test-dispvm', template=self.appvm)
            self.assertFalse(mock_domains.get_new_unused_dispid.called)

    @mock.patch('os.symlink')
    @mock.patch('os.makedirs')
    def test_020_copy_storage_pool(self, mock_makedirs, mock_symlink):
        self.app.pools['alternative'] = qubes.tests.vm.appvm.TestPool(name='alternative')
        self.appvm.template_for_dispvms = True
        self.loop.run_until_complete(self.template.create_on_disk())
        self.loop.run_until_complete(self.appvm.create_on_disk(pool='alternative'))
        orig_getitem = self.app.domains.__getitem__
        with mock.patch.object(self.app, 'domains', wraps=self.app.domains) \
                as mock_domains:
            mock_domains.configure_mock(**{
                'get_new_unused_dispid': mock.Mock(return_value=42),
                '__getitem__.side_effect': orig_getitem
            })
            dispvm = self.app.add_new_vm(qubes.vm.dispvm.DispVM,
                name='test-dispvm', template=self.appvm)
            self.loop.run_until_complete(dispvm.create_on_disk())
        self.assertIs(dispvm.template, self.appvm)
        self.assertIs(dispvm.volumes['private'].pool,
                         self.appvm.volumes['private'].pool)
        self.assertIs(dispvm.volumes['root'].pool,
                         self.appvm.volumes['root'].pool)
        self.assertIs(dispvm.volumes['volatile'].pool,
                         self.appvm.volumes['volatile'].pool)

    def test_021_storage_template_change(self):
        self.appvm.template_for_dispvms = True
        orig_domains = self.app.domains
        with mock.patch.object(self.app, 'domains', wraps=self.app.domains) \
                as mock_domains:
            mock_domains.configure_mock(**{
                'get_new_unused_dispid': mock.Mock(return_value=42),
                '__getitem__.side_effect': orig_domains.__getitem__,
                '__iter__.side_effect': orig_domains.__iter__,
                '__setitem__.side_effect': orig_domains.__setitem__,
            })
            vm = self.dispvm = self.app.add_new_vm(qubes.vm.dispvm.DispVM,
                name='test-dispvm', template=self.appvm)
            self.assertIs(vm.volume_config['root']['source'],
                self.template.volumes['root'])
            # create new mock, so new template will get different volumes
            self.app.pools['default'] = mock.Mock(**{
                'init_volume.return_value.pool': 'default'})
            template2 = qubes.vm.templatevm.TemplateVM(self.app, None,
                qid=3, name=qubes.tests.VMPREFIX + 'template2')
            self.app.domains[template2.name] = template2
            self.app.domains[template2] = template2
            self.appvm.template = template2

        self.assertFalse(vm.volume_config['root']['save_on_stop'])
        self.assertTrue(vm.volume_config['root']['snap_on_start'])
        self.assertNotEqual(vm.volume_config['root']['source'],
            self.template.volumes['root'])
        self.assertIs(vm.volume_config['root']['source'],
            template2.volumes['root'])
        self.assertIs(vm.volume_config['root']['source'],
            self.appvm.volume_config['root']['source'])
        self.assertIs(vm.volume_config['private']['source'],
            self.appvm.volumes['private'])

    def test_022_storage_app_change(self):
        self.appvm.template_for_dispvms = True
        self.assertTrue(self.appvm.events_enabled)
        orig_domains = self.app.domains
        with mock.patch.object(self.app, 'domains', wraps=self.app.domains) \
                as mock_domains:
            mock_domains.configure_mock(**{
                'get_new_unused_dispid': mock.Mock(return_value=42),
                '__getitem__.side_effect': orig_domains.__getitem__,
                '__iter__.side_effect': orig_domains.__iter__,
                '__setitem__.side_effect': orig_domains.__setitem__,
            })
            vm = self.dispvm = self.app.add_new_vm(qubes.vm.dispvm.DispVM,
                name='test-dispvm', template=self.appvm)
            self.assertTrue(vm.events_enabled)
            # create new mock, so new template will get different volumes
            self.app.pools['default'] = mock.Mock(**{
                'init_volume.return_value.pool': 'default'})
            template2 = qubes.vm.templatevm.TemplateVM(self.app, None,
                qid=3, name=qubes.tests.VMPREFIX + 'template2')
            self.assertTrue(template2.events_enabled)
            self.app.domains[template2.name] = template2
            self.app.domains[template2] = template2
            app2 = qubes.vm.appvm.AppVM(self.app, None,
                qid=4, name=qubes.tests.VMPREFIX + 'app2', template=template2)
            self.assertTrue(app2.events_enabled)
            app2.template_for_dispvms = True
            self.app.domains[app2.name] = app2
            self.app.domains[app2] = app2
            self.dispvm.template = app2

        self.assertIs(vm, self.dispvm)
        self.assertFalse(vm.volume_config['root']['save_on_stop'])
        self.assertTrue(vm.volume_config['root']['snap_on_start'])
        self.assertFalse(vm.volume_config['private']['save_on_stop'])
        self.assertTrue(vm.volume_config['private']['snap_on_start'])
        self.assertNotEqual(vm.volume_config['root']['source'],
            self.template.volumes['root'])
        self.assertNotEqual(vm.volume_config['root']['source'],
            self.appvm.volumes['root'].source)
        self.assertNotEqual(vm.volume_config['private']['source'],
            self.appvm.volumes['private'])
        self.assertIs(vm.volume_config['root']['source'],
            template2.volumes['root'])
        self.assertIs(app2.volume_config['root']['source'],
            template2.volumes['root'])
        self.assertIs(vm.volume_config['private']['source'],
            app2.volumes['private'])
