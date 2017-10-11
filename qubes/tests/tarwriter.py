#
# The Qubes OS Project, http://www.qubes-os.org
#
# Copyright (C) 2016 Marek Marczykowski-Górecki
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
#

import os
import subprocess
import tempfile

import shutil

import qubes.tarwriter
import qubes.tests


class TC_00_TarWriter(qubes.tests.QubesTestCase):
    def setUp(self):
        super(TC_00_TarWriter, self).setUp()
        self.input_path = tempfile.mktemp()
        self.output_path = tempfile.mktemp()
        self.extract_dir = tempfile.mkdtemp()

    def tearDown(self):
        if os.path.exists(self.input_path):
            os.unlink(self.input_path)
        if os.path.exists(self.output_path):
            os.unlink(self.output_path)
        if os.path.exists(self.extract_dir):
            shutil.rmtree(self.extract_dir)
        return super(TC_00_TarWriter, self).tearDown()

    def assertTarExtractable(self, expected_name=None):
        if expected_name is None:
            expected_name = self.input_path
        with self.assertNotRaises(subprocess.CalledProcessError):
            tar_output = subprocess.check_output(
                ['tar', 'xvf', self.output_path],
                cwd=self.extract_dir,
                stderr=subprocess.STDOUT)
        expected_output = expected_name + '\n'
        if expected_name[0] == '/':
            expected_output = (
                'tar: Removing leading `/\' from member names\n' +
                expected_output)
        self.assertEqual(tar_output.decode(), expected_output)
        extracted_path = os.path.join(self.extract_dir,
            expected_name.lstrip('/'))
        with self.assertNotRaises(subprocess.CalledProcessError):
            subprocess.check_call(
                ['diff', '-q', self.input_path, extracted_path])
        # make sure the file is still sparse
        orig_stat = os.stat(self.input_path)
        extracted_stat = os.stat(extracted_path)
        self.assertEqual(orig_stat.st_blocks, extracted_stat.st_blocks)
        self.assertEqual(orig_stat.st_size, extracted_stat.st_size)

    def write_sparse_chunks(self, num_chunks):
        with open(self.input_path, 'w') as f:
            for i in range(num_chunks):
                f.seek(8192 * i)
                f.write('a' * 4096)

    def test_000_simple(self):
        self.write_sparse_chunks(1)
        with open(self.input_path, 'w') as f:
            f.write('a' * 4096)
        qubes.tarwriter.main([self.input_path, self.output_path])
        self.assertTarExtractable()

    def test_001_simple_sparse2(self):
        self.write_sparse_chunks(2)
        qubes.tarwriter.main([self.input_path, self.output_path])
        self.assertTarExtractable()

    def test_002_simple_sparse3(self):
        # tar header contains info about 4 chunks, check for off-by-one errors
        self.write_sparse_chunks(3)
        qubes.tarwriter.main([self.input_path, self.output_path])
        self.assertTarExtractable()

    def test_003_simple_sparse4(self):
        # tar header contains info about 4 chunks, check for off-by-one errors
        self.write_sparse_chunks(4)
        qubes.tarwriter.main([self.input_path, self.output_path])
        self.assertTarExtractable()

    def test_004_simple_sparse5(self):
        # tar header contains info about 4 chunks, check for off-by-one errors
        self.write_sparse_chunks(5)
        qubes.tarwriter.main([self.input_path, self.output_path])
        self.assertTarExtractable()

    def test_005_simple_sparse24(self):
        # tar header contains info about 4 chunks, next header contains 21 of
        # them, check for off-by-one errors
        self.write_sparse_chunks(24)
        qubes.tarwriter.main([self.input_path, self.output_path])
        self.assertTarExtractable()

    def test_006_simple_sparse25(self):
        # tar header contains info about 4 chunks, next header contains 21 of
        # them, check for off-by-one errors
        self.write_sparse_chunks(25)
        qubes.tarwriter.main([self.input_path, self.output_path])
        self.assertTarExtractable()

    def test_007_simple_sparse26(self):
        # tar header contains info about 4 chunks, next header contains 21 of
        # them, check for off-by-one errors
        self.write_sparse_chunks(26)
        qubes.tarwriter.main([self.input_path, self.output_path])
        self.assertTarExtractable()

    def test_010_override_name(self):
        self.write_sparse_chunks(1)
        qubes.tarwriter.main(['--override-name',
            'different-name', self.input_path, self.output_path])
        self.assertTarExtractable(expected_name='different-name')

    def test_011_empty(self):
        self.write_sparse_chunks(0)
        qubes.tarwriter.main([self.input_path, self.output_path])
        self.assertTarExtractable()

    def test_012_gzip(self):
        self.write_sparse_chunks(0)
        qubes.tarwriter.main([
            '--use-compress-program=gzip', self.input_path, self.output_path])
        with self.assertNotRaises(subprocess.CalledProcessError):
            subprocess.check_call(['gzip', '--test', self.output_path])
        self.assertTarExtractable()
