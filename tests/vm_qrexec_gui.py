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
import multiprocessing
import os
import subprocess
import unittest
import time

from qubes.qubes import QubesVmCollection, defaults


VM_PREFIX = "test-"

TEST_DATA = "0123456789" * 1024

class VmRunningTests(unittest.TestCase):
    def setUp(self):
        self.qc = QubesVmCollection()
        self.qc.lock_db_for_writing()
        self.qc.load()
        self.testvm1 = self.qc.add_new_vm("QubesAppVm",
                                         name="%svm1" % VM_PREFIX,
                                         template=self.qc.get_default_template())
        self.testvm1.create_on_disk(verbose=False)
        self.testvm2 = self.qc.add_new_vm("QubesAppVm",
                                         name="%svm2" % VM_PREFIX,
                                         template=self.qc.get_default_template())
        self.testvm2.create_on_disk(verbose=False)
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
        self.testvm1.start()
        self.assertEquals(self.testvm1.get_power_state(), "Running")
        self.testvm1.shutdown()

        shutdown_counter = 0
        while self.testvm1.is_running():
            if shutdown_counter > defaults["shutdown_counter_max"]:
                self.fail("VM hanged during shutdown")
            shutdown_counter += 1
            time.sleep(1)
        time.sleep(1)
        self.assertEquals(self.testvm1.get_power_state(), "Halted")

    def test_010_run_gui_app(self):
        self.testvm1.start()
        self.assertEquals(self.testvm1.get_power_state(), "Running")
        self.testvm1.run("gnome-terminal")
        wait_count = 0
        while subprocess.call(['xdotool', 'search', '--name', 'user@%s' %
                self.testvm1.name], stdout=open(os.path.devnull, 'w'),
                              stderr=subprocess.STDOUT) > 0:
            wait_count += 1
            if wait_count > 100:
                self.fail("Timeout while waiting for gnome-terminal window")
            time.sleep(0.1)

        time.sleep(0.5)
        subprocess.check_call(['xdotool', 'search', '--name', 'user@%s' %
                self.testvm1.name, 'windowactivate', 'type', 'exit\n'])

        wait_count = 0
        while subprocess.call(['xdotool', 'search', '--name', 'user@%s' %
                self.testvm1.name], stdout=open(os.path.devnull, 'w'),
                              stderr=subprocess.STDOUT) == 0:
            wait_count += 1
            if wait_count > 100:
                self.fail("Timeout while waiting for gnome-terminal "
                          "termination")
            time.sleep(0.1)

    def test_050_qrexec_simple_eof(self):
        """Test for data and EOF transmission dom0->VM"""
        result = multiprocessing.Value('i', 0)
        def run(self, result):
            p = self.testvm1.run("cat", passio_popen=True,
                            passio_stderr=True)

            (stdout, stderr) = p.communicate(TEST_DATA)
            if stdout != TEST_DATA:
                result.value = 1
            if len(stderr) > 0:
                result.value = 2

        self.testvm1.start()

        t = multiprocessing.Process(target=run, args=(self, result))
        t.start()
        t.join(timeout=10)
        if t.is_alive():
            t.terminate()
            self.fail("Timeout, probably EOF wasn't transferred to the VM "
                      "process")
        if result.value == 1:
            self.fail("Received data differs from what was sent")
        elif result.value == 2:
            self.fail("Some data was printed to stderr")

    def test_051_qrexec_simple_eof_reverse(self):
        """Test for EOF transmission VM->dom0"""
        result = multiprocessing.Value('i', 0)
        def run(self, result):
            p = self.testvm1.run("echo test; exec >&-; cat > /dev/null",
                                 passio_popen=True, passio_stderr=True)
            # this will hang on test failure
            stdout = p.stdout.read()
            p.stdin.write(TEST_DATA)
            p.stdin.close()
            if stdout.strip() != "test":
                result.value = 1
            # this may hang in some buggy cases
            elif len(p.stderr.read()) > 0:
                result.value = 2
            elif p.pull() is None:
                result.value = 3

        self.testvm1.start()

        t = multiprocessing.Process(target=run, args=(self, result))
        t.start()
        t.join(timeout=10)
        if t.is_alive():
            t.terminate()
            self.fail("Timeout, probably EOF wasn't transferred from the VM "
                      "process")
        if result.value == 1:
            self.fail("Received data differs from what was expected")
        elif result.value == 2:
            self.fail("Some data was printed to stderr")
        elif result.value == 3:
            self.fail("VM proceess didn't terminated on EOF")

    def test_052_qrexec_vm_service_eof(self):
        """Test for EOF transmission VM(src)->VM(dst)"""
        result = multiprocessing.Value('i', 0)
        def run(self, result):
            p = self.testvm1.run("/usr/lib/qubes/qrexec-client-vm %s test.EOF "
                                 "/bin/sh -c 'echo test; exec >&-; cat "
                                 ">&$SAVED_FD_1'" % self.testvm2.name,
                                 passio_popen=True)
            (stdout, stderr) = p.communicate()
            if stdout != "test\n":
                result.value = 1

        self.testvm1.start()
        self.testvm2.start()
        p = self.testvm2.run("cat > /etc/qubes-rpc/test.EOF", user="root",
                             passio_popen=True)
        p.stdin.write("/bin/cat")
        p.stdin.close()
        p.wait()
        policy = open("/etc/qubes-rpc/policy/test.EOF", "w")
        policy.write("%s %s allow" % (self.testvm1.name, self.testvm2.name))
        policy.close()
        self.addCleanup(os.unlink, "/etc/qubes-rpc/policy/test.EOF")

        t = multiprocessing.Process(target=run, args=(self, result))
        t.start()
        t.join(timeout=10)
        if t.is_alive():
            t.terminate()
            self.fail("Timeout, probably EOF wasn't transferred")
        if result.value == 1:
            self.fail("Received data differs from what was expected")

    def test_053_qrexec_vm_service_eof_reverse(self):
        """Test for EOF transmission VM(src)<-VM(dst)"""
        result = multiprocessing.Value('i', 0)
        def run(self, result):
            p = self.testvm1.run("/usr/lib/qubes/qrexec-client-vm %s test.EOF "
                                 "/bin/sh -c 'cat >&$SAVED_FD_1'"
                                 % self.testvm1.name,
                                 passio_popen=True)
            (stdout, stderr) = p.communicate()
            if stdout != "test\n":
                result.value = 1

        self.testvm1.start()
        self.testvm2.start()
        p = self.testvm2.run("cat > /etc/qubes-rpc/test.EOF", user="root",
                             passio_popen=True)
        p.stdin.write("echo test; exec >&-; cat >/dev/null")
        p.stdin.close()
        p.wait()
        policy = open("/etc/qubes-rpc/policy/test.EOF", "w")
        policy.write("%s %s allow" % (self.testvm1.name, self.testvm2.name))
        policy.close()
        self.addCleanup(os.unlink, "/etc/qubes-rpc/policy/test.EOF")

        t = multiprocessing.Process(target=run, args=(self, result))
        t.start()
        t.join(timeout=10)
        if t.is_alive():
            t.terminate()
            self.fail("Timeout, probably EOF wasn't transferred")
        if result.value == 1:
            self.fail("Received data differs from what was expected")

    def test_100_qrexec_filecopy(self):
        self.testvm1.start()
        self.testvm2.start()
        p = self.testvm1.run("qvm-copy-to-vm %s /etc/passwd" %
                            self.testvm2.name, passio_popen=True,
                            passio_stderr=True)
        # Confirm transfer
        subprocess.check_call(['xdotool', 'search', '--sync', '--name', 'Question',
                             'key', 'y'])
        p.wait()
        self.assertEqual(p.returncode, 0, "qvm-copy-to-vm failed: %s" %
                         p.stderr.read())
        retcode = self.testvm2.run("diff /etc/passwd "
                         "/home/user/QubesIncoming/%s/passwd" % self.testvm1.name, wait=True)
        self.assertEqual(retcode, 0, "file differs")

    def test_110_qrexec_filecopy_deny(self):
        self.testvm1.start()
        self.testvm2.start()
        p = self.testvm1.run("qvm-copy-to-vm %s /etc/passwd" %
                            self.testvm2.name, passio_popen=True)
        # Deny transfer
        subprocess.check_call(['xdotool', 'search', '--sync', '--name', 'Question',
                             'key', 'n'])
        p.wait()
        self.assertEqual(p.returncode, 1, "qvm-copy-to-vm unexpectedly "
                                          "succeeded")
        retcode = self.testvm1.run("ls /home/user/QubesIncoming/%s" %
                                  self.testvm1.name, wait=True,
                                  ignore_stderr=True)
        self.assertEqual(retcode, 2, "QubesIncoming exists although file copy was "
                                     "denied")

    def test_120_qrexec_filecopy_self(self):
        self.testvm1.start()
        p = self.testvm1.run("qvm-copy-to-vm %s /etc/passwd" %
                            self.testvm1.name, passio_popen=True,
                            passio_stderr=True)
        # Confirm transfer
        subprocess.check_call(['xdotool', 'search', '--sync', '--name', 'Question',
                             'key', 'y'])
        p.wait()
        self.assertEqual(p.returncode, 0, "qvm-copy-to-vm failed: %s" %
                         p.stderr.read())
        retcode = self.testvm1.run("diff /etc/passwd "
                         "/home/user/QubesIncoming/%s/passwd" % self.testvm1.name, wait=True)
        self.assertEqual(retcode, 0, "file differs")

