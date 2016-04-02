#!/usr/bin/python2 -O
# vim: fileencoding=utf-8

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
import qubes.tools.qvm_prefs

import qubes.tests

@qubes.tests.skipUnlessDom0
class TC_00_qvm_prefs(
        qubes.tests.SystemTestsMixin, qubes.tests.QubesTestCase):
    def test_000_list(self):
        self.assertEqual(0, qubes.tools.qvm_prefs.main([
            '--qubesxml', qubes.tests.XMLPATH, 'dom0']))

    def test_001_no_vm(self):
        with self.assertRaises(SystemExit):
            qubes.tools.qvm_prefs.main([
                '--qubesxml', qubes.tests.XMLPATH])

    def test_002_set_property(self):
        self.assertEqual(0, qubes.tools.qvm_prefs.main([
            '--qubesxml', qubes.tests.XMLPATH, 'dom0',
            'default_user', 'testuser']))

        self.assertEqual('testuser',
            qubes.Qubes(qubes.tests.XMLPATH).domains['dom0'].default_user)

    def test_003_invalid_property(self):
        with self.assertRaises(SystemExit):
            qubes.tools.qvm_prefs.main([
                '--qubesxml', qubes.tests.XMLPATH, 'dom0',
                'no_such_property'])

    def test_004_set_invalid_property(self):
        with self.assertRaises(SystemExit):
            qubes.tools.qvm_prefs.main([
                '--qubesxml', qubes.tests.XMLPATH, 'dom0',
                'no_such_property', 'value'])
