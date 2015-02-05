#!/usr/bin/python2 -O

#
# The Qubes OS Project, https://www.qubes-os.org/
#
# Copyright (C) 2014-2015
#       Marek Marczykowski-Górecki <marmarek@invisiblethingslab.com>
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

import multiprocessing
import time
import unittest

import qubes.qubes
import qubes.tests

class TC_00_Regressions(qubes.tests.SystemTestsMixin, unittest.TestCase):
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

