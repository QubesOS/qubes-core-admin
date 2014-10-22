#!/usr/bin/python
# -*- coding: utf-8 -*-
#
# The Qubes OS Project, http://www.qubes-os.org
#
# Copyright (C) 2014 Marek Marczykowski-Górecki <marmarek@invisiblethingslab.com>
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
import os
import subprocess
import unittest
import time
from qubes.qubes import QubesVmCollection, defaults

VM_PREFIX = "test-"

class VmRunningTests(unittest.TestCase):
    def setUp(self):
        self.qc = QubesVmCollection()
        self.qc.lock_db_for_writing()
        self.qc.load()
        self.testvm = self.qc.add_new_vm("QubesAppVm",
                                         name="%stestvm" % VM_PREFIX,
                                         template=self.qc.get_default_template())
        self.testvm.create_on_disk(verbose=False)
        self.qc.save()
        self.qc.unlock_db()

    def remove_vms(self, vms):
        self.qc.lock_db_for_writing()
        self.qc.load()

        for vm in vms:
            if isinstance(vm, str):
                vm = self.qc.get_vm_by_name(vm)
            else:
                vm = self.qc[vm.qid]
            if vm.is_running():
                try:
                    vm.force_shutdown()
                except:
                    pass
            try:
                vm.remove_from_disk()
            except OSError:
                pass
            self.qc.pop(vm.qid)
        self.qc.save()
        self.qc.unlock_db()

    def tearDown(self):
        vmlist = [vm for vm in self.qc.values() if vm.name.startswith(
            VM_PREFIX)]
        self.remove_vms(vmlist)

    def test_000_start_shutdown(self):
        self.testvm.start()
        self.assertEquals(self.testvm.get_power_state(), "Running")
        self.testvm.shutdown()

        shutdown_counter = 0
        while self.testvm.is_running():
            if shutdown_counter > defaults["shutdown_counter_max"]:
                self.fail("VM hanged during shutdown")
            shutdown_counter += 1
            time.sleep(1)
        time.sleep(1)
        self.assertEquals(self.testvm.get_power_state(), "Halted")

    def test_010_run_gui_app(self):
        self.testvm.start()
        self.assertEquals(self.testvm.get_power_state(), "Running")
        self.testvm.run("gnome-terminal")
        wait_count = 0
        while subprocess.call(['xdotool', 'search', '--name', 'user@%s' %
                self.testvm.name]) > 0:
            wait_count += 1
            if wait_count > 100:
                self.fail("Timeout while waiting for gnome-terminal window")
            time.sleep(0.1)

        subprocess.check_call(['xdotool', 'search', '--name', 'user@%s' %
                self.testvm.name, 'windowactivate', 'type', 'exit\n'])

        wait_count = 0
        while subprocess.call(['xdotool', 'search', '--name', 'user@%s' %
                self.testvm.name], stdout=open(os.path.devnull, 'w'),
                              stderr=subprocess.STDOUT) == 0:
            wait_count += 1
            if wait_count > 100:
                self.fail("Timeout while waiting for gnome-terminal "
                          "termination")
            time.sleep(0.1)

    def test_100_qrexec_filecopy(self):
        self.testvm.start()
        p = self.testvm.run("qvm-copy-to-vm %s /etc/passwd" %
                            self.testvm.name, passio_popen=True,
                            passio_stderr=True)
        # Confirm transfer
        subprocess.check_call(['xdotool', 'search', '--sync', '--name', 'Question',
                             'key', 'y'])
        p.wait()
        self.assertEqual(p.returncode, 0, "qvm-copy-to-vm failed: %s" %
                         p.stderr.read())
        retcode = self.testvm.run("diff /etc/passwd "
                         "/home/user/QubesIncoming/%s/passwd" % self.testvm.name, wait=True)
        self.assertEqual(retcode, 0, "file differs")

    def test_110_qrexec_filecopy_deny(self):
        self.testvm.start()
        p = self.testvm.run("qvm-copy-to-vm %s /etc/passwd" %
                            self.testvm.name, passio_popen=True)
        # Deny transfer
        subprocess.check_call(['xdotool', 'search', '--sync', '--name', 'Question',
                             'key', 'n'])
        p.wait()
        self.assertEqual(p.returncode, 1, "qvm-copy-to-vm unexpectedly "
                                          "succeeded")
        retcode = self.testvm.run("ls /home/user/QubesIncoming/%s" %
                                  self.testvm.name, wait=True,
                                  ignore_stderr=True)
        self.assertEqual(retcode, 2, "QubesIncoming exists although file copy was "
                                     "denied")