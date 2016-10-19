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

import os
import StringIO
import sys
import tempfile
import unittest

import qubes
import qubes.config
import qubes.tools.qvm_run
import qubes.vm

import qubes.tests


@qubes.tests.skipUnlessDom0
class TC_00_qvm_run(qubes.tests.SystemTestsMixin, qubes.tests.QubesTestCase):
    def setUp(self):
        super(TC_00_qvm_run, self).setUp()
        self.init_default_template()

        self.vm1 = self.app.add_new_vm(qubes.vm.appvm.AppVM,
            name=self.make_vm_name('vm1'),
            template=self.app.default_template,
            label='red')
        self.vm1.create_on_disk()

        self.vm1.start()
        self.app.save()

        self.sharedopts = ['--qubesxml', qubes.tests.XMLPATH]


    def tearDown(self):
        # clean up after testing --colour-output
        sys.stdout = sys.__stdout__


    @staticmethod
    def get_qvm_run_output(args):
        assert '--localcmd' not in args, \
            'get_qvm_run_output requires no --localcmd'

        outfile = tempfile.NamedTemporaryFile(prefix='qvm-run-output')
        args = list(args)
        args.insert(0, '--pass-io')
        args.insert(1, '--localcmd')
        args.insert(2, 'sh -c "dd of={}"'.format(outfile.name))

        qubes.tools.qvm_run.main(args)

        outfile.seek(0)
        output = outfile.read()
        outfile.close()

        return output


    def test_000_basic(self):
        self.assertEqual(0, qubes.tools.qvm_run.main(
            self.sharedopts + [self.vm1.name, 'true']))

    def test_001_passio_retcode(self):
        self.assertEqual(0, qubes.tools.qvm_run.main(
            self.sharedopts + ['--pass-io', self.vm1.name, 'true']))
        self.assertEqual(1, qubes.tools.qvm_run.main(
            self.sharedopts + ['--pass-io', self.vm1.name, 'false']))

    def test_002_passio_localcmd(self):
        self.assertEqual('aqq', self.get_qvm_run_output(
            self.sharedopts + [self.vm1.name, 'printf aqq']))

    def test_003_user(self):
        self.assertNotEqual('0\n', self.get_qvm_run_output(
            self.sharedopts + ['--user', 'user', self.vm1.name, 'id -u']))
        self.assertEqual('0\n', self.get_qvm_run_output(
            self.sharedopts + ['--user', 'root', self.vm1.name, 'id -u']))

    def test_004_autostart(self):
        vm2 = self.app.add_new_vm(qubes.vm.appvm.AppVM,
            name=self.make_vm_name('vm2'),
            template=qubes.tests.TEMPLATE,
            label='red')
        vm2.create_on_disk()
        self.app.save()
        # and do not start it
        self.assertEqual(-1, qubes.tools.qvm_run.main(
            self.sharedopts + [vm2.name, 'true']))
        self.assertEqual(0, qubes.tools.qvm_run.main(
            self.sharedopts + ['--autostart', vm2.name, 'true']))

    @unittest.skip('expected error')
    def test_005_colour_output(self):
        sys.stdout = StringIO.StringIO()
        qubes.tools.qvm_run.main(
            self.sharedopts + ['--colour-output', '32', self.vm1.name, 'true'])
        self.assertEqual('\033[0;32m\033[0m', sys.stdout.getvalue())

    def test_006_filter_esc(self):
        self.assertEqual('\033', self.get_qvm_run_output(
            self.sharedopts + ['--no-filter-escape-chars', self.vm1.name,
                r'printf \\033']))
        self.assertEqual('_', self.get_qvm_run_output(
            self.sharedopts + ['--filter-escape-chars', self.vm1.name,
                r'printf \\033']))


    def test_007_gui(self): # pylint: disable=no-self-use
        raise unittest.SkipTest('test not implemented')


#parser.add_argument('--gui',
#parser.add_argument('--no-gui', '--nogui',
