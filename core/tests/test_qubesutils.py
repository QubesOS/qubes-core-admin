#!/usr/bin/python -O

#
# The Qubes OS Project, http://www.qubes-os.org
#
# Copyright (C) 2014  Wojciech Porczyk <wojciech@porczyk.eu>
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.
#

import subprocess
import unittest

import qubes.qubesutils


class TestCaseFunctionsAndConstants(unittest.TestCase):
    def check_output_int(self, cmd):
        return int(subprocess.check_output(cmd).strip().split(None, 1)[0])

    def test_00_BLKSIZE(self):
        # this may fail on systems without st_blocks
        self.assertEqual(qubes.qubesutils.BLKSIZE, self.check_output_int(['stat', '-c%B', '.']))

    def test_01_get_size_one(self):
        # this may fail on systems without st_blocks
        self.assertEqual(qubes.qubesutils.get_disk_usage_one(os.stat('.')),
            self.check_output_int(['stat', '-c%b', '.']) * qubes.qubesutils.BLKSIZE)

    def test_02_get_size(self):
        self.assertEqual(qubes.qubesutils.get_disk_usage('.'),
            self.check_output_int(['du', '-s', '--block-size=1', '.']))


if __name__ == '__main__':
    unittest.main()
