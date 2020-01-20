
#
# The Qubes OS Project, https://www.qubes-os.org/
#
# Copyright (C) 2020 Paweł Marczewski <pawel@invisiblethingslab.com>
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

import unittest
import tempfile
import shutil
import os
import subprocess


import qubes.tests


class TestRpcImport(qubes.tests.QubesTestCase):
    '''
    Tests for qubes-rpc/admin.vm.volume.Import script.

    It is a shell script that calls internal API methods via qubesd-query.
    These tests mock all the calls.
    '''


    QUBESD_QUERY = '''\
#!/bin/sh -e

method=$4
echo "$@" > command-$method
cat > payload-$method
cat response-$method
'''

    RPC_FILE_PATH = os.path.abspath(os.path.join(
        os.path.dirname(__file__),
        '../../qubes-rpc/admin.vm.volume.Import'))

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmpdir)
        with open(os.path.join(self.tmpdir, 'qubesd-query'), 'w') \
             as qubesd_query_f:
            qubesd_query_f.write(self.QUBESD_QUERY)
        os.chmod(os.path.join(self.tmpdir, 'qubesd-query'), 0o700)

        shutil.copy(
            self.RPC_FILE_PATH,
            os.path.join(self.tmpdir, 'admin.vm.volume.Import'))
        shutil.copy(
            self.RPC_FILE_PATH,
            os.path.join(self.tmpdir, 'admin.vm.volume.ImportWithSize'))

    # pylint:disable=invalid-name
    def mockMethod(self, method, response):
        with open(os.path.join(self.tmpdir, 'response-' + method), 'wb') \
             as response_f:
            response_f.write(response)

    # pylint:disable=invalid-name
    def assertMethodCalled(self, method, arg, expected_payload=b''):
        try:
            with open(os.path.join(self.tmpdir, 'command-' + method), 'rb') \
                 as command_f:
                command = command_f.read()
            with open(os.path.join(self.tmpdir, 'payload-' + method), 'rb') \
                 as payload_f:
                payload = payload_f.read()
        except FileNotFoundError:
            self.fail('{} was not called'.format(method))

        self.assertListEqual(command.decode().split(), [
            '-c', '/var/run/qubesd.internal.sock',
            'remote', method, 'target', arg
        ])
        self.assertEqual(payload, expected_payload)

    # pylint:disable=invalid-name
    def assertFileData(self, path, expected_data):
        with open(path, 'rb') as data_f:
            data = data_f.read()
        self.assertEquals(data, expected_data)

    def setup_import(self, size):
        self.target = os.path.join(self.tmpdir, 'target')
        os.mknod(self.target)

        self.mockMethod(
            'internal.vm.volume.ImportBegin',
            '\x30\x00{} {}'.format(size, self.target).encode())

        self.mockMethod(
            'internal.vm.volume.ImportEnd',
            b'\x30\x00import-end')

    def run_rpc(self, command, arg, data):
        with open(os.path.join(self.tmpdir, 'data'), 'w+b') as data_f:
            data_f.write(data)
            data_f.seek(0)
            env = {
                'PATH': self.tmpdir + ':' + os.getenv('PATH'),
                'QREXEC_REMOTE_DOMAIN': 'remote',
                'QREXEC_REQUESTED_TARGET': 'target',
            }
            output = subprocess.check_output(
                [command, arg],
                env=env,
                cwd=self.tmpdir,
                stdin=data_f
            )

        self.assertEqual(output, b'\x30\x00import-end')

    def test_00_import(self):
        data = b'abcd' * 1024
        size = len(data)
        self.setup_import(size)

        self.run_rpc('admin.vm.volume.Import', 'volume', data)

        self.assertMethodCalled('internal.vm.volume.ImportBegin', 'volume')
        self.assertMethodCalled('internal.vm.volume.ImportEnd', 'volume',
                                b'ok')
        self.assertFileData(self.target, data)

    def test_01_import_with_size(self):
        data = b'abcd' * 1024
        size = len(data)
        self.setup_import(size)

        self.run_rpc('admin.vm.volume.ImportWithSize', 'volume',
                     str(size).encode() + b'\n' + data)

        self.assertMethodCalled('internal.vm.volume.ImportBegin', 'volume',
                                str(size).encode())
        self.assertMethodCalled('internal.vm.volume.ImportEnd', 'volume',
                                b'ok')
        self.assertFileData(self.target, data)

    def test_02_import_not_enough_data(self):
        data = b'abcd' * 1024
        size = len(data) + 1
        self.setup_import(size)

        self.run_rpc('admin.vm.volume.Import', 'volume', data)

        self.assertMethodCalled('internal.vm.volume.ImportBegin', 'volume')
        self.assertMethodCalled(
            'internal.vm.volume.ImportEnd', 'volume',
            b'fail\n' +
            ('not enough data (copied {} bytes, expected {} bytes)'
             .format(len(data), size).encode()))

    def test_03_import_too_much_data(self):
        data = b'abcd' * 1024
        size = len(data) - 1
        self.setup_import(size)

        output = self.run_rpc('admin.vm.volume.Import', 'volume', data)

        self.assertMethodCalled('internal.vm.volume.ImportBegin', 'volume')
        self.assertMethodCalled(
            'internal.vm.volume.ImportEnd', 'volume',
            b'fail\n' +
            ('too much data (expected {} bytes)'
             .format(size).encode()))
