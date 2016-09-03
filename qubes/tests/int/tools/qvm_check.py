#!/usr/bin/python2 -O
# vim: fileencoding=utf-8
#
# The Qubes OS Project, https://www.qubes-os.org/
#
# Copyright (C) 2016  Marek Marczykowski-Górecki
#                                   <marmarek@invisiblethingslab.com>
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
import qubes.tools.qvm_check

import qubes.tests
import qubes.vm.appvm


class TC_00_qvm_check(qubes.tests.SystemTestsMixin, qubes.tests.QubesTestCase):
    def setUp(self):
        super(TC_00_qvm_check, self).setUp()
        self.init_default_template()

        self.sharedopts = ['--qubesxml', qubes.tests.XMLPATH]

        self.vm1 = self.app.add_new_vm(qubes.vm.appvm.AppVM,
            name=self.make_vm_name('vm1'),
            template=self.app.default_template,
            label='red')
        self.vm1.create_on_disk()
        self.app.save()

    def test_000_exists(self):
        self.assertEqual(0, qubes.tools.qvm_check.main(
            self.sharedopts + [self.vm1.name]))

        with self.assertRaises(SystemExit):
            qubes.tools.qvm_check.main(
                self.sharedopts + ['test-no-such-vm'])

    def test_001_running(self):
        self.assertEqual(1, qubes.tools.qvm_check.main(
            self.sharedopts + ['--running', self.vm1.name]))
        self.vm1.start()
        self.assertEqual(0, qubes.tools.qvm_check.main(
            self.sharedopts + ['--running', self.vm1.name]))

    def test_002_paused(self):
        self.assertEqual(1, qubes.tools.qvm_check.main(
            self.sharedopts + ['--paused', self.vm1.name]))
        self.vm1.start()
        self.assertEqual(1, qubes.tools.qvm_check.main(
            self.sharedopts + ['--paused', self.vm1.name]))
        self.vm1.pause()
        self.assertEqual(0, qubes.tools.qvm_check.main(
            self.sharedopts + ['--paused', self.vm1.name]))

    def test_003_template(self):
        self.assertEqual(1, qubes.tools.qvm_check.main(
            self.sharedopts + ['--template', self.vm1.name]))
        self.assertEqual(0, qubes.tools.qvm_check.main(
            self.sharedopts + ['--template', self.app.default_template.name]))
