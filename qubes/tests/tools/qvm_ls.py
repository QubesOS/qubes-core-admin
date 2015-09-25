#!/usr/bin/python2 -O
# vim: fileencoding=utf-8
# pylint: disable=protected-access,pointless-statement

#
# The Qubes OS Project, https://www.qubes-os.org/
#
# Copyright (C) 2015  Joanna Rutkowska <joanna@invisiblethingslab.com>
# Copyright (C) 2015  Wojtek Porczyk <woju@invisiblethingslab.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
#

import qubes
import qubes.vm.adminvm
import qubes.tools.qvm_ls

import qubes.tests
import qubes.tests.vm.adminvm

class TC_00_Column(qubes.tests.QubesTestCase):
    def test_000_collected(self):
        self.assertIn('NAME', qubes.tools.qvm_ls.Column.columns)

    def test_100_init(self):
        try:
            testcolumn = qubes.tools.qvm_ls.Column('TESTCOLUMN', width=50)
            self.assertEqual(testcolumn.ls_head, 'TESTCOLUMN')
            self.assertEqual(testcolumn.ls_width, 50)
        finally:
            try:
                qubes.tools.qvm_ls.Column.columns['TESTCOLUMN']
            except KeyError:
                pass

    def test_101_fix_width(self):
        try:
            testcolumn = qubes.tools.qvm_ls.Column('TESTCOLUMN', width=2)
            self.assertGreater(testcolumn.ls_width, len('TESTCOLUMN'))
        finally:
            try:
                qubes.tools.qvm_ls.Column.columns['TESTCOLUMN']
            except KeyError:
                pass


class TC_90_globals(qubes.tests.QubesTestCase):
#   @qubes.tests.skipUnlessDom0
    def test_100_simple_flag(self):
        flag = qubes.tools.qvm_ls.simple_flag(1, 'T', 'internal')

        # TODO after serious testing of QubesVM and Qubes app, this should be
        #      using normal components
        app = qubes.tests.vm.adminvm.TestApp()
        vm = qubes.vm.adminvm.AdminVM(app, None,
            qid=0, name='dom0', internal='False')

        self.assertFalse(flag(None, vm))
        vm.internal = 'True'
        self.assertTrue(flag(None, vm))


    def test_900_formats_columns(self):
        for fmt in qubes.tools.qvm_ls.formats:
            for col in qubes.tools.qvm_ls.formats[fmt]:
                self.assertIn(col.upper(), qubes.tools.qvm_ls.Column.columns)
