#!/usr/bin/python2 -O
# coding=utf-8

#
# The Qubes OS Project, https://www.qubes-os.org/
#
# Copyright (C) 2014-2015
#       Marek Marczykowski-Górecki <marmarek@invisiblethingslab.com>
# Copyright (C) 2015  Wojtek Porczyk <woju@invisiblethingslab.com>
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

import multiprocessing
import os
import time
import unittest

import qubes.qubes
import qubes.tests
import subprocess


class TC_00_Regressions(qubes.tests.SystemTestsMixin, qubes.tests.QubesTestCase):
    # Bug: #906
    def test_000_bug_906_db_locking(self):
        def create_vm(vmname):
            qc = qubes.qubes.QubesVmCollection()
            qc.lock_db_for_writing()
            qc.load()
            time.sleep(1)
            qc.add_new_vm('QubesAppVm',
                name=vmname, template=qc.get_default_template())
            qc.save()
            qc.unlock_db()

        vmname1, vmname2 = map(self.make_vm_name, ('test1', 'test2'))
        t = multiprocessing.Process(target=create_vm, args=(vmname1,))
        t.start()
        create_vm(vmname2)
        t.join()

        qc = qubes.qubes.QubesVmCollection()
        qc.lock_db_for_reading()
        qc.load()
        qc.unlock_db()

        self.assertIsNotNone(qc.get_vm_by_name(vmname1))
        self.assertIsNotNone(qc.get_vm_by_name(vmname2))

    def test_bug_1389_dispvm_qubesdb_crash(self):
        """
        Sometimes QubesDB instance in DispVM crashes at startup.
        Unfortunately we don't have reliable way to reproduce it, so try twice
        :return:
        """
        self.qc.unlock_db()
        for try_no in xrange(2):
            p = subprocess.Popen(['/usr/lib/qubes/qfile-daemon-dvm',
                                  'qubes.VMShell', 'dom0', 'DEFAULT'],
                                 stdin=subprocess.PIPE,
                                 stdout=subprocess.PIPE,
                                 stderr=open(os.devnull, 'w'))
            p.stdin.write("qubesdb-read /name || echo ERROR\n")
            dispvm_name = p.stdout.readline()
            p.stdin.close()
            self.assertTrue(dispvm_name.startswith("disp"),
                                 "Try {} failed".format(try_no))
