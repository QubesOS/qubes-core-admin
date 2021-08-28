#
# The Qubes OS Project, http://www.qubes-os.org
#
# Copyright (C) 2021 Rusty Bird <rustybird@net-c.com>
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

import qubes.tests


class TC_00_SelfTest(qubes.tests.QubesTestCase):
    def test_000_ignore_never_awaited(self):
        with qubes.tests.ignore_never_awaited():
            intentionally_never_awaited()

    @unittest.expectedFailure
    def test_001_raise_never_awaited_by_default(self):
        intentionally_never_awaited()

    def test_002_full_traceback_on_failure(self):
        self.assertTrue(callable(
            getattr(unittest.TestResult, '_is_relevant_tb_level', None)))


async def intentionally_never_awaited():
    pass
