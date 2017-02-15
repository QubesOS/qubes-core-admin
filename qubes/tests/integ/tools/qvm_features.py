#!/usr/bin/python2
# -*- encoding: utf8 -*-
#
# The Qubes OS Project, http://www.qubes-os.org
#
# Copyright (C) 2017 Marek Marczykowski-Górecki
#                               <marmarek@invisiblethingslab.com>
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
import qubes
import qubes.tools.qvm_features

import qubes.tests
import qubes.tests.tools
import qubes.vm.appvm


class TC_00_qvm_features(qubes.tests.SystemTestsMixin,
        qubes.tests.QubesTestCase):
    def setUp(self):
        super(TC_00_qvm_features, self).setUp()
        self.init_default_template()

        self.sharedopts = ['--qubesxml', qubes.tests.XMLPATH]

        self.vm1 = self.app.add_new_vm(qubes.vm.appvm.AppVM,
            name=self.make_vm_name('vm1'),
            template=self.app.default_template,
            label='red')
        self.app.save()

    def test_000_list(self):
        self.assertEqual(0, qubes.tools.qvm_features.main(
            self.sharedopts + [self.vm1.name]))

        with self.assertRaises(SystemExit):
            qubes.tools.qvm_features.main(
                self.sharedopts + ['test-no-such-vm'])

    def test_001_get_missing(self):
        self.assertEqual(1, qubes.tools.qvm_features.main(
            self.sharedopts + [self.vm1.name, 'no-such-feature']))

    def test_002_set_and_get(self):
        self.assertEqual(0, qubes.tools.qvm_features.main(
            self.sharedopts + [self.vm1.name, 'test-feature', 'true']))
        with qubes.tests.tools.StdoutBuffer() as buf:
            self.assertEqual(0, qubes.tools.qvm_features.main(
                self.sharedopts + [self.vm1.name, 'test-feature']))
            self.assertEqual('true\n', buf.getvalue())

    def test_003_set_and_list(self):
        self.assertEqual(0, qubes.tools.qvm_features.main(
            self.sharedopts + [self.vm1.name, 'test-feature', 'true']))
        with qubes.tests.tools.StdoutBuffer() as buf:
            self.assertEqual(0, qubes.tools.qvm_features.main(
                self.sharedopts + [self.vm1.name]))
            self.assertEqual('test-feature  true\n', buf.getvalue())
