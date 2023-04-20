#
# The Qubes OS Project, https://www.qubes-os.org/
#
# Copyright (C) 2014-2015  Joanna Rutkowska <joanna@invisiblethingslab.com>
# Copyright (C) 2014-2015  Wojtek Porczyk <woju@invisiblethingslab.com>
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
import subprocess
import unittest
import unittest.mock

import functools

import asyncio

import qubes
import qubes.exc
import qubes.vm
import qubes.vm.adminvm

import qubes.tests

class TC_00_AdminVM(qubes.tests.QubesTestCase):
    def setUp(self):
        super().setUp()
        try:
            self.app = qubes.tests.vm.TestApp()
            with unittest.mock.patch.object(
                    qubes.vm.adminvm.AdminVM, 'start_qdb_watch') as mock_qdb:
                self.vm = qubes.vm.adminvm.AdminVM(self.app,
                    xml=None)
                mock_qdb.assert_called_once_with()
                self.addCleanup(self.cleanup_adminvm)
        except:  # pylint: disable=bare-except
            if self.id().endswith('.test_000_init'):
                raise
            self.skipTest('setup failed')

    def tearDown(self) -> None:
        self.app.domains.clear()

    def add_vm(self, name, cls=qubes.vm.qubesvm.QubesVM, **kwargs):
        vm = cls(self.app, None,
                 qid=kwargs.pop('qid', 1), name=qubes.tests.VMPREFIX + name,
                 **kwargs)
        self.app.domains[vm.qid] = vm
        self.app.domains[vm.uuid] = vm
        self.app.domains[vm.name] = vm
        self.app.domains[vm] = vm
        self.addCleanup(vm.close)
        return vm

    async def coroutine_mock(self, mock, *args, **kwargs):
        return mock(*args, **kwargs)

    def cleanup_adminvm(self):
        self.vm.close()
        del self.vm

    def test_000_init(self):
        pass

    def test_001_property_icon(self):
        self.assertEqual(self.vm.icon, 'adminvm-black')

    def test_100_xid(self):
        self.assertEqual(self.vm.xid, 0)

    def test_101_libvirt_domain(self):
        with unittest.mock.patch.object(self.app, 'vmm') as mock_vmm:
            self.assertIsNotNone(self.vm.libvirt_domain)
            self.assertEqual(mock_vmm.mock_calls, [
                ('libvirt_conn.lookupByID', (0,), {}),
            ])

    def test_300_is_running(self):
        self.assertTrue(self.vm.is_running())

    def test_301_get_power_state(self):
        self.assertEqual(self.vm.get_power_state(), 'Running')

    def test_302_get_mem(self):
        self.assertGreater(self.vm.get_mem(), 0)

    @unittest.skip('mock object does not support this')
    def test_303_get_mem_static_max(self):
        self.assertGreater(self.vm.get_mem_static_max(), 0)

    def test_310_start(self):
        with self.assertRaises(qubes.exc.QubesException):
            self.vm.start()

    @unittest.skip('this functionality is undecided')
    def test_311_suspend(self):
        with self.assertRaises(qubes.exc.QubesException):
            self.vm.suspend()

    @unittest.mock.patch('asyncio.create_subprocess_exec')
    def test_700_run_service(self, mock_subprocess):
        self.add_vm('vm')

        with self.subTest('running'):
            self.loop.run_until_complete(self.vm.run_service('test.service'))
            mock_subprocess.assert_called_once_with(
                '/usr/lib/qubes/qubes-rpc-multiplexer',
                'test.service', 'dom0', 'name', 'dom0')

        mock_subprocess.reset_mock()
        with self.subTest('other_user'):
            self.loop.run_until_complete(
                self.vm.run_service('test.service', user='other'))
            mock_subprocess.assert_called_once_with(
                'runuser', '-u', 'other', '--',
                '/usr/lib/qubes/qubes-rpc-multiplexer',
                'test.service', 'dom0', 'name', 'dom0')

            mock_subprocess.reset_mock()
        with self.subTest('other_source'):
            self.loop.run_until_complete(
                self.vm.run_service('test.service', source='test-inst-vm'))
            mock_subprocess.assert_called_once_with(
                '/usr/lib/qubes/qubes-rpc-multiplexer',
                'test.service', 'test-inst-vm', 'name', 'dom0')

    @unittest.mock.patch('qubes.vm.adminvm.AdminVM.run_service')
    def test_710_run_service_for_stdio(self, mock_run_service):
        communicate_mock = mock_run_service.return_value.communicate
        communicate_mock.return_value = (b'stdout', b'stderr')
        mock_run_service.return_value.returncode = 0

        with self.subTest('default'):
            value = self.loop.run_until_complete(
                self.vm.run_service_for_stdio('test.service'))
            mock_run_service.assert_called_once_with(
                'test.service',
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.PIPE)
            communicate_mock.assert_called_once_with(input=None)
            self.assertEqual(value, (b'stdout', b'stderr'))

        mock_run_service.reset_mock()
        communicate_mock.reset_mock()
        with self.subTest('with_input'):
            value = self.loop.run_until_complete(
                self.vm.run_service_for_stdio('test.service', input=b'abc'))
            mock_run_service.assert_called_once_with(
                'test.service',
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.PIPE)
            communicate_mock.assert_called_once_with(input=b'abc')
            self.assertEqual(value, (b'stdout', b'stderr'))

        mock_run_service.reset_mock()
        communicate_mock.reset_mock()
        with self.subTest('error'):
            mock_run_service.return_value.returncode = 1
            with self.assertRaises(subprocess.CalledProcessError) as exc:
                self.loop.run_until_complete(
                    self.vm.run_service_for_stdio('test.service'))
            mock_run_service.assert_called_once_with(
                'test.service',
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.PIPE)
            communicate_mock.assert_called_once_with(input=None)
            self.assertEqual(exc.exception.returncode, 1)
            self.assertEqual(exc.exception.output, b'stdout')
            self.assertEqual(exc.exception.stderr, b'stderr')

    def test_711_adminvm_ordering(self):
        assert(self.vm < qubes.vm.qubesvm.QubesVM(self.app, None, qid=1, name="dom0"))
