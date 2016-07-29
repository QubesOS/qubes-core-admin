#!/usr/bin/python
# vim: fileencoding=utf-8

#
# The Qubes OS Project, https://www.qubes-os.org/
#
# Copyright (C) 2014-2015
#                   Marek Marczykowski-Górecki <marmarek@invisiblethingslab.com>
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
from distutils import spawn

import multiprocessing
import os
import subprocess
import unittest
import time

from qubes.qubes import QubesVmCollection, defaults, QubesException

import qubes.tests
import re

TEST_DATA = "0123456789" * 1024

class TC_00_AppVMMixin(qubes.tests.SystemTestsMixin):
    def setUp(self):
        super(TC_00_AppVMMixin, self).setUp()
        self.testvm1 = self.qc.add_new_vm(
            "QubesAppVm",
            name=self.make_vm_name('vm1'),
            template=self.qc.get_vm_by_name(self.template))
        self.testvm1.create_on_disk(verbose=False)
        self.testvm2 = self.qc.add_new_vm(
            "QubesAppVm",
            name=self.make_vm_name('vm2'),
            template=self.qc.get_vm_by_name(self.template))
        self.testvm2.create_on_disk(verbose=False)
        self.save_and_reload_db()
        self.qc.unlock_db()
        self.testvm1 = self.qc[self.testvm1.qid]
        self.testvm2 = self.qc[self.testvm2.qid]

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

    @unittest.skipUnless(spawn.find_executable('xdotool'),
                         "xdotool not installed")
    def test_010_run_xterm(self):
        self.testvm1.start()
        self.assertEquals(self.testvm1.get_power_state(), "Running")
        self.testvm1.run("xterm")
        wait_count = 0
        title = 'user@{}'.format(self.testvm1.name)
        if self.template.count("whonix"):
            title = 'user@host'
        while subprocess.call(
                ['xdotool', 'search', '--name', title],
                stdout=open(os.path.devnull, 'w'),
                stderr=subprocess.STDOUT) > 0:
            wait_count += 1
            if wait_count > 100:
                self.fail("Timeout while waiting for xterm window")
            time.sleep(0.1)

        time.sleep(0.5)
        subprocess.check_call(
            ['xdotool', 'search', '--name', title,
             'windowactivate', 'type', 'exit\n'])

        wait_count = 0
        while subprocess.call(['xdotool', 'search', '--name', title],
                              stdout=open(os.path.devnull, 'w'),
                              stderr=subprocess.STDOUT) == 0:
            wait_count += 1
            if wait_count > 100:
                self.fail("Timeout while waiting for xterm "
                          "termination")
            time.sleep(0.1)

    @unittest.skipUnless(spawn.find_executable('xdotool'),
                         "xdotool not installed")
    def test_011_run_gnome_terminal(self):
        if "minimal" in self.template:
            self.skipTest("Minimal template doesn't have 'gnome-terminal'")
        self.testvm1.start()
        self.assertEquals(self.testvm1.get_power_state(), "Running")
        self.testvm1.run("gnome-terminal")
        title = 'user@{}'.format(self.testvm1.name)
        if self.template.count("whonix"):
            title = 'user@host'
        wait_count = 0
        while subprocess.call(
                ['xdotool', 'search', '--name', title],
                stdout=open(os.path.devnull, 'w'),
                stderr=subprocess.STDOUT) > 0:
            wait_count += 1
            if wait_count > 100:
                self.fail("Timeout while waiting for gnome-terminal window")
            time.sleep(0.1)

        time.sleep(0.5)
        subprocess.check_call(
            ['xdotool', 'search', '--name', title,
             'windowactivate', '--sync', 'type', 'exit\n'])

        wait_count = 0
        while subprocess.call(['xdotool', 'search', '--name', title],
                              stdout=open(os.path.devnull, 'w'),
                              stderr=subprocess.STDOUT) == 0:
            wait_count += 1
            if wait_count > 100:
                self.fail("Timeout while waiting for gnome-terminal "
                          "termination")
            time.sleep(0.1)

    @unittest.skipUnless(spawn.find_executable('xdotool'),
                         "xdotool not installed")
    def test_012_qubes_desktop_run(self):
        self.testvm1.start()
        self.assertEquals(self.testvm1.get_power_state(), "Running")
        xterm_desktop_path = "/usr/share/applications/xterm.desktop"
        # Debian has it different...
        xterm_desktop_path_debian = \
            "/usr/share/applications/debian-xterm.desktop"
        if self.testvm1.run("test -r {}".format(xterm_desktop_path_debian),
                            wait=True) == 0:
            xterm_desktop_path = xterm_desktop_path_debian
        self.testvm1.run("qubes-desktop-run {}".format(xterm_desktop_path))
        title = 'user@{}'.format(self.testvm1.name)
        if self.template.count("whonix"):
            title = 'user@host'
        wait_count = 0
        while subprocess.call(
                ['xdotool', 'search', '--name', title],
                stdout=open(os.path.devnull, 'w'),
                stderr=subprocess.STDOUT) > 0:
            wait_count += 1
            if wait_count > 100:
                self.fail("Timeout while waiting for xterm window")
            time.sleep(0.1)

        time.sleep(0.5)
        subprocess.check_call(
            ['xdotool', 'search', '--name', title,
             'windowactivate', '--sync', 'type', 'exit\n'])

        wait_count = 0
        while subprocess.call(['xdotool', 'search', '--name', title],
                              stdout=open(os.path.devnull, 'w'),
                              stderr=subprocess.STDOUT) == 0:
            wait_count += 1
            if wait_count > 100:
                self.fail("Timeout while waiting for xterm "
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
            elif p.poll() is None:
                time.sleep(1)
                if p.poll() is None:
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

    @unittest.expectedFailure
    def test_053_qrexec_vm_service_eof_reverse(self):
        """Test for EOF transmission VM(src)<-VM(dst)"""
        result = multiprocessing.Value('i', 0)

        def run(self, result):
            p = self.testvm1.run("/usr/lib/qubes/qrexec-client-vm %s test.EOF "
                                 "/bin/sh -c 'cat >&$SAVED_FD_1'"
                                 % self.testvm2.name,
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

    def test_055_qrexec_dom0_service_abort(self):
        """
        Test if service abort (by dom0) is properly handled by source VM.

        If "remote" part of the service terminates, the source part should
        properly be notified. This includes closing its stdin (which is
        already checked by test_053_qrexec_vm_service_eof_reverse), but also
        its stdout - otherwise such service might hang on write(2) call.
        """

        def run (src):
            p = src.run("/usr/lib/qubes/qrexec-client-vm dom0 "
                                 "test.Abort /bin/cat /dev/zero",
                                 passio_popen=True)

            p.communicate()
            p.wait()

        self.testvm1.start()
        service = open("/etc/qubes-rpc/test.Abort", "w")
        service.write("sleep 1")
        service.close()
        self.addCleanup(os.unlink, "/etc/qubes-rpc/test.Abort")
        policy = open("/etc/qubes-rpc/policy/test.Abort", "w")
        policy.write("%s dom0 allow" % (self.testvm1.name))
        policy.close()
        self.addCleanup(os.unlink, "/etc/qubes-rpc/policy/test.Abort")

        t = multiprocessing.Process(target=run, args=(self.testvm1,))
        t.start()
        t.join(timeout=10)
        if t.is_alive():
            t.terminate()
            self.fail("Timeout, probably stdout wasn't closed")


    def test_060_qrexec_exit_code_dom0(self):
        self.testvm1.start()

        p = self.testvm1.run("exit 0", passio_popen=True)
        p.wait()
        self.assertEqual(0, p.returncode)

        p = self.testvm1.run("exit 3", passio_popen=True)
        p.wait()
        self.assertEqual(3, p.returncode)

    @unittest.expectedFailure
    def test_065_qrexec_exit_code_vm(self):
        self.testvm1.start()
        self.testvm2.start()

        policy = open("/etc/qubes-rpc/policy/test.Retcode", "w")
        policy.write("%s %s allow" % (self.testvm1.name, self.testvm2.name))
        policy.close()
        self.addCleanup(os.unlink, "/etc/qubes-rpc/policy/test.Retcode")

        p = self.testvm2.run("cat > /etc/qubes-rpc/test.Retcode", user="root",
                             passio_popen=True)
        p.stdin.write("exit 0")
        p.stdin.close()
        p.wait()

        p = self.testvm1.run("/usr/lib/qubes/qrexec-client-vm %s test.Retcode "
                             "/bin/sh -c 'cat >/dev/null'; echo $?"
                             % self.testvm1.name,
                             passio_popen=True)
        (stdout, stderr) = p.communicate()
        self.assertEqual(stdout, "0\n")

        p = self.testvm2.run("cat > /etc/qubes-rpc/test.Retcode", user="root",
                             passio_popen=True)
        p.stdin.write("exit 3")
        p.stdin.close()
        p.wait()

        p = self.testvm1.run("/usr/lib/qubes/qrexec-client-vm %s test.Retcode "
                             "/bin/sh -c 'cat >/dev/null'; echo $?"
                             % self.testvm1.name,
                             passio_popen=True)
        (stdout, stderr) = p.communicate()
        self.assertEqual(stdout, "3\n")

    def test_070_qrexec_vm_simultaneous_write(self):
        """Test for simultaneous write in VM(src)->VM(dst) connection

            This is regression test for #1347

            Check for deadlock when initially both sides writes a lot of data
            (and not read anything). When one side starts reading, it should
            get the data and the remote side should be possible to write then more.
            There was a bug where remote side was waiting on write(2) and not
            handling anything else.
        """
        result = multiprocessing.Value('i', -1)

        def run(self):
            p = self.testvm1.run(
                "/usr/lib/qubes/qrexec-client-vm %s test.write "
                "/bin/sh -c '"
                # first write a lot of data to fill all the buffers
                "dd if=/dev/zero bs=993 count=10000 iflag=fullblock & "
                # then after some time start reading
                "sleep 1; "
                "dd of=/dev/null bs=993 count=10000 iflag=fullblock; "
                "wait"
                "'" % self.testvm2.name, passio_popen=True)
            p.communicate()
            result.value = p.returncode

        self.testvm1.start()
        self.testvm2.start()
        p = self.testvm2.run("cat > /etc/qubes-rpc/test.write", user="root",
                             passio_popen=True)
        # first write a lot of data
        p.stdin.write("dd if=/dev/zero bs=993 count=10000 iflag=fullblock\n")
        # and only then read something
        p.stdin.write("dd of=/dev/null bs=993 count=10000 iflag=fullblock\n")
        p.stdin.close()
        p.wait()
        policy = open("/etc/qubes-rpc/policy/test.write", "w")
        policy.write("%s %s allow" % (self.testvm1.name, self.testvm2.name))
        policy.close()
        self.addCleanup(os.unlink, "/etc/qubes-rpc/policy/test.write")

        t = multiprocessing.Process(target=run, args=(self,))
        t.start()
        t.join(timeout=10)
        if t.is_alive():
            t.terminate()
            self.fail("Timeout, probably deadlock")
        self.assertEqual(result.value, 0, "Service call failed")

    def test_071_qrexec_dom0_simultaneous_write(self):
        """Test for simultaneous write in dom0(src)->VM(dst) connection

            Similar to test_070_qrexec_vm_simultaneous_write, but with dom0
            as a source.
        """
        result = multiprocessing.Value('i', -1)

        def run(self):
            result.value = self.testvm2.run_service(
                "test.write", localcmd="/bin/sh -c '"
                # first write a lot of data to fill all the buffers
                "dd if=/dev/zero bs=993 count=10000 iflag=fullblock & "
                # then after some time start reading
                "sleep 1; "
                "dd of=/dev/null bs=993 count=10000 iflag=fullblock; "
                "wait"
                "'")

        self.testvm2.start()
        p = self.testvm2.run("cat > /etc/qubes-rpc/test.write", user="root",
                             passio_popen=True)
        # first write a lot of data
        p.stdin.write("dd if=/dev/zero bs=993 count=10000 iflag=fullblock\n")
        # and only then read something
        p.stdin.write("dd of=/dev/null bs=993 count=10000 iflag=fullblock\n")
        p.stdin.close()
        p.wait()
        policy = open("/etc/qubes-rpc/policy/test.write", "w")
        policy.write("%s %s allow" % (self.testvm1.name, self.testvm2.name))
        policy.close()
        self.addCleanup(os.unlink, "/etc/qubes-rpc/policy/test.write")

        t = multiprocessing.Process(target=run, args=(self,))
        t.start()
        t.join(timeout=10)
        if t.is_alive():
            t.terminate()
            self.fail("Timeout, probably deadlock")
        self.assertEqual(result.value, 0, "Service call failed")

    def test_072_qrexec_to_dom0_simultaneous_write(self):
        """Test for simultaneous write in dom0(src)<-VM(dst) connection

            Similar to test_071_qrexec_dom0_simultaneous_write, but with dom0
            as a "hanging" side.
        """
        result = multiprocessing.Value('i', -1)

        def run(self):
            result.value = self.testvm2.run_service(
                "test.write", localcmd="/bin/sh -c '"
                # first write a lot of data to fill all the buffers
                "dd if=/dev/zero bs=993 count=10000 iflag=fullblock "
                # then, only when all written, read something
                "dd of=/dev/null bs=993 count=10000 iflag=fullblock; "
                "'")

        self.testvm2.start()
        p = self.testvm2.run("cat > /etc/qubes-rpc/test.write", user="root",
                             passio_popen=True)
        # first write a lot of data
        p.stdin.write("dd if=/dev/zero bs=993 count=10000 iflag=fullblock &\n")
        # and only then read something
        p.stdin.write("dd of=/dev/null bs=993 count=10000 iflag=fullblock\n")
        p.stdin.write("sleep 1; \n")
        p.stdin.write("wait\n")
        p.stdin.close()
        p.wait()
        policy = open("/etc/qubes-rpc/policy/test.write", "w")
        policy.write("%s %s allow" % (self.testvm1.name, self.testvm2.name))
        policy.close()
        self.addCleanup(os.unlink, "/etc/qubes-rpc/policy/test.write")

        t = multiprocessing.Process(target=run, args=(self,))
        t.start()
        t.join(timeout=10)
        if t.is_alive():
            t.terminate()
            self.fail("Timeout, probably deadlock")
        self.assertEqual(result.value, 0, "Service call failed")

    def test_080_qrexec_service_argument_allow_default(self):
        """Qrexec service call with argument"""
        self.testvm1.start()
        self.testvm2.start()
        p = self.testvm2.run("cat > /etc/qubes-rpc/test.Argument", user="root",
                             passio_popen=True)
        p.communicate("/bin/echo $1")

        with open("/etc/qubes-rpc/policy/test.Argument", "w") as policy:
            policy.write("%s %s allow" % (self.testvm1.name, self.testvm2.name))
        self.addCleanup(os.unlink, "/etc/qubes-rpc/policy/test.Argument")

        p = self.testvm1.run("/usr/lib/qubes/qrexec-client-vm {} "
                             "test.Argument+argument".format(self.testvm2.name),
                             passio_popen=True)
        (stdout, stderr) = p.communicate()
        self.assertEqual(stdout, "argument\n")

    def test_081_qrexec_service_argument_allow_specific(self):
        """Qrexec service call with argument - allow only specific value"""
        self.testvm1.start()
        self.testvm2.start()
        p = self.testvm2.run("cat > /etc/qubes-rpc/test.Argument", user="root",
                             passio_popen=True)
        p.communicate("/bin/echo $1")

        with open("/etc/qubes-rpc/policy/test.Argument", "w") as policy:
            policy.write("$anyvm $anyvm deny")
        self.addCleanup(os.unlink, "/etc/qubes-rpc/policy/test.Argument")

        with open("/etc/qubes-rpc/policy/test.Argument+argument", "w") as \
                policy:
            policy.write("%s %s allow" % (self.testvm1.name, self.testvm2.name))
        self.addCleanup(os.unlink,
            "/etc/qubes-rpc/policy/test.Argument+argument")

        p = self.testvm1.run("/usr/lib/qubes/qrexec-client-vm {} "
                             "test.Argument+argument".format(self.testvm2.name),
                             passio_popen=True)
        (stdout, stderr) = p.communicate()
        self.assertEqual(stdout, "argument\n")

    def test_082_qrexec_service_argument_deny_specific(self):
        """Qrexec service call with argument - deny specific value"""
        self.testvm1.start()
        self.testvm2.start()
        p = self.testvm2.run("cat > /etc/qubes-rpc/test.Argument", user="root",
                             passio_popen=True)
        p.communicate("/bin/echo $1")

        with open("/etc/qubes-rpc/policy/test.Argument", "w") as policy:
            policy.write("$anyvm $anyvm allow")
        self.addCleanup(os.unlink, "/etc/qubes-rpc/policy/test.Argument")

        with open("/etc/qubes-rpc/policy/test.Argument+argument", "w") as \
                policy:
            policy.write("%s %s deny" % (self.testvm1.name, self.testvm2.name))
        self.addCleanup(os.unlink,
            "/etc/qubes-rpc/policy/test.Argument+argument")

        p = self.testvm1.run("/usr/lib/qubes/qrexec-client-vm {} "
                             "test.Argument+argument".format(self.testvm2.name),
                             passio_popen=True)
        (stdout, stderr) = p.communicate()
        self.assertEqual(stdout, "")
        self.assertEqual(p.returncode, 1, "Service request should be denied")

    def test_083_qrexec_service_argument_specific_implementation(self):
        """Qrexec service call with argument - argument specific
        implementatation"""
        self.testvm1.start()
        self.testvm2.start()
        p = self.testvm2.run("cat > /etc/qubes-rpc/test.Argument", user="root",
                             passio_popen=True)
        p.communicate("/bin/echo $1")

        p = self.testvm2.run("cat > /etc/qubes-rpc/test.Argument+argument",
            user="root", passio_popen=True)
        p.communicate("/bin/echo specific: $1")

        with open("/etc/qubes-rpc/policy/test.Argument", "w") as policy:
            policy.write("%s %s allow" % (self.testvm1.name, self.testvm2.name))
        self.addCleanup(os.unlink, "/etc/qubes-rpc/policy/test.Argument")

        p = self.testvm1.run("/usr/lib/qubes/qrexec-client-vm {} "
                             "test.Argument+argument".format(self.testvm2.name),
                             passio_popen=True)
        (stdout, stderr) = p.communicate()
        self.assertEqual(stdout, "specific: argument\n")

    def test_084_qrexec_service_argument_extra_env(self):
        """Qrexec service call with argument - extra env variables"""
        self.testvm1.start()
        self.testvm2.start()
        p = self.testvm2.run("cat > /etc/qubes-rpc/test.Argument", user="root",
                             passio_popen=True)
        p.communicate("/bin/echo $QREXEC_SERVICE_FULL_NAME "
                      "$QREXEC_SERVICE_ARGUMENT")

        with open("/etc/qubes-rpc/policy/test.Argument", "w") as policy:
            policy.write("%s %s allow" % (self.testvm1.name, self.testvm2.name))
        self.addCleanup(os.unlink, "/etc/qubes-rpc/policy/test.Argument")

        p = self.testvm1.run("/usr/lib/qubes/qrexec-client-vm {} "
                             "test.Argument+argument".format(self.testvm2.name),
                             passio_popen=True)
        (stdout, stderr) = p.communicate()
        self.assertEqual(stdout, "test.Argument+argument argument\n")

    def test_100_qrexec_filecopy(self):
        self.testvm1.start()
        self.testvm2.start()
        self.qrexec_policy('qubes.Filecopy', self.testvm1.name,
            self.testvm2.name)
        p = self.testvm1.run("qvm-copy-to-vm %s /etc/passwd" %
                             self.testvm2.name, passio_popen=True,
                             passio_stderr=True)
        p.wait()
        self.assertEqual(p.returncode, 0, "qvm-copy-to-vm failed: %s" %
                         p.stderr.read())
        retcode = self.testvm2.run("diff /etc/passwd "
                                   "/home/user/QubesIncoming/{}/passwd".format(
                                       self.testvm1.name),
                                   wait=True)
        self.assertEqual(retcode, 0, "file differs")

    def test_105_qrexec_filemove(self):
        self.testvm1.start()
        self.testvm2.start()
        self.qrexec_policy('qubes.Filecopy', self.testvm1.name,
            self.testvm2.name)
        retcode = self.testvm1.run("cp /etc/passwd passwd", wait=True)
        assert retcode == 0, "Failed to prepare source file"
        p = self.testvm1.run("qvm-move-to-vm %s passwd" %
                             self.testvm2.name, passio_popen=True,
                             passio_stderr=True)
        p.wait()
        self.assertEqual(p.returncode, 0, "qvm-move-to-vm failed: %s" %
                         p.stderr.read())
        retcode = self.testvm2.run("diff /etc/passwd "
                                   "/home/user/QubesIncoming/{}/passwd".format(
                                       self.testvm1.name),
                                   wait=True)
        self.assertEqual(retcode, 0, "file differs")
        retcode = self.testvm1.run("test -f passwd", wait=True)
        self.assertEqual(retcode, 1, "source file not removed")

    def test_101_qrexec_filecopy_with_autostart(self):
        self.testvm1.start()
        self.qrexec_policy('qubes.Filecopy', self.testvm1.name,
            self.testvm2.name)
        p = self.testvm1.run("qvm-copy-to-vm %s /etc/passwd" %
                             self.testvm2.name, passio_popen=True,
                             passio_stderr=True)
        p.wait()
        self.assertEqual(p.returncode, 0, "qvm-copy-to-vm failed: %s" %
                         p.stderr.read())
        # workaround for libvirt bug (domain ID isn't updated when is started
        #  from other application) - details in
        # QubesOS/qubes-core-libvirt@63ede4dfb4485c4161dd6a2cc809e8fb45ca664f
        self.testvm2._libvirt_domain = None
        self.assertTrue(self.testvm2.is_running())
        retcode = self.testvm2.run("diff /etc/passwd "
                                   "/home/user/QubesIncoming/{}/passwd".format(
                                       self.testvm1.name),
                                   wait=True)
        self.assertEqual(retcode, 0, "file differs")

    def test_110_qrexec_filecopy_deny(self):
        self.testvm1.start()
        self.testvm2.start()
        self.qrexec_policy('qubes.Filecopy', self.testvm1.name,
            self.testvm2.name, allow=False)
        p = self.testvm1.run("qvm-copy-to-vm %s /etc/passwd" %
                             self.testvm2.name, passio_popen=True)
        p.wait()
        self.assertNotEqual(p.returncode, 0, "qvm-copy-to-vm unexpectedly "
                            "succeeded")
        retcode = self.testvm1.run("ls /home/user/QubesIncoming/%s" %
                                   self.testvm1.name, wait=True,
                                   ignore_stderr=True)
        self.assertNotEqual(retcode, 0, "QubesIncoming exists although file "
                            "copy was denied")

    @unittest.skip("Xen gntalloc driver crashes when page is mapped in the "
                   "same domain")
    def test_120_qrexec_filecopy_self(self):
        self.testvm1.start()
        self.qrexec_policy('qubes.Filecopy', self.testvm1.name,
            self.testvm1.name)
        p = self.testvm1.run("qvm-copy-to-vm %s /etc/passwd" %
                             self.testvm1.name, passio_popen=True,
                             passio_stderr=True)
        p.wait()
        self.assertEqual(p.returncode, 0, "qvm-copy-to-vm failed: %s" %
                         p.stderr.read())
        retcode = self.testvm1.run(
            "diff /etc/passwd /home/user/QubesIncoming/{}/passwd".format(
                self.testvm1.name),
            wait=True)
        self.assertEqual(retcode, 0, "file differs")

    @unittest.skipUnless(spawn.find_executable('xdotool'),
                         "xdotool not installed")
    def test_130_qrexec_filemove_disk_full(self):
        self.testvm1.start()
        self.testvm2.start()
        self.qrexec_policy('qubes.Filecopy', self.testvm1.name,
            self.testvm2.name)
        # Prepare test file
        prepare_cmd = ("yes teststring | dd of=testfile bs=1M "
                       "count=50 iflag=fullblock")
        retcode = self.testvm1.run(prepare_cmd, wait=True)
        if retcode != 0:
            raise RuntimeError("Failed '{}' in {}".format(prepare_cmd,
                                                          self.testvm1.name))
        # Prepare target directory with limited size
        prepare_cmd = (
            "mkdir -p /home/user/QubesIncoming && "
            "chown user /home/user/QubesIncoming && "
            "mount -t tmpfs none /home/user/QubesIncoming -o size=48M"
        )
        retcode = self.testvm2.run(prepare_cmd, user="root", wait=True)
        if retcode != 0:
            raise RuntimeError("Failed '{}' in {}".format(prepare_cmd,
                                                          self.testvm2.name))
        p = self.testvm1.run("qvm-move-to-vm %s testfile" %
                             self.testvm2.name, passio_popen=True,
                             passio_stderr=True)
        # Close GUI error message
        self.enter_keys_in_window('Error', ['Return'])
        p.wait()
        self.assertNotEqual(p.returncode, 0, "qvm-move-to-vm should fail")
        retcode = self.testvm1.run("test -f testfile", wait=True)
        self.assertEqual(retcode, 0, "testfile should not be deleted in "
                                     "source VM")

    def test_200_timezone(self):
        """Test whether timezone setting is properly propagated to the VM"""
        if "whonix" in self.template:
            self.skipTest("Timezone propagation disabled on Whonix templates")

        self.testvm1.start()
        (vm_tz, _) = self.testvm1.run("date +%Z",
                                      passio_popen=True).communicate()
        (dom0_tz, _) = subprocess.Popen(["date", "+%Z"],
                                        stdout=subprocess.PIPE).communicate()
        self.assertEqual(vm_tz.strip(), dom0_tz.strip())

        # Check if reverting back to UTC works
        (vm_tz, _) = self.testvm1.run("TZ=UTC date +%Z",
                                      passio_popen=True).communicate()
        self.assertEqual(vm_tz.strip(), "UTC")

    def test_210_time_sync(self):
        """Test time synchronization mechanism"""
        if self.template.startswith('whonix-'):
            self.skipTest('qvm-sync-clock disabled for Whonix VMs')
        self.testvm1.start()
        self.testvm2.start()
        (start_time, _) = subprocess.Popen(["date", "-u", "+%s"],
                                           stdout=subprocess.PIPE).communicate()
        original_clockvm = self.qc.get_clockvm_vm()
        if original_clockvm:
            original_clockvm_name = original_clockvm.name
        else:
            original_clockvm_name = "none"
        try:
            # use qubes-prefs to not hassle with qubes.xml locking
            subprocess.check_call(["qubes-prefs", "-s", "clockvm",
                                   self.testvm1.name])
            # break vm and dom0 time, to check if qvm-sync-clock would fix it
            subprocess.check_call(["sudo", "date", "-s",
                                   "2001-01-01T12:34:56"],
                                  stdout=open(os.devnull, 'w'))
            retcode = self.testvm1.run("date -s 2001-01-01T12:34:56",
                                       user="root", wait=True)
            self.assertEquals(retcode, 0, "Failed to break the VM(1) time")
            retcode = self.testvm2.run("date -s 2001-01-01T12:34:56",
                                       user="root", wait=True)
            self.assertEquals(retcode, 0, "Failed to break the VM(2) time")
            retcode = subprocess.call(["qvm-sync-clock"])
            self.assertEquals(retcode, 0,
                              "qvm-sync-clock failed with code {}".
                              format(retcode))
            # qvm-sync-clock is asynchronous - it spawns qubes.SetDateTime
            # service, send it timestamp value and exists without waiting for
            # actual time set
            time.sleep(1)
            (vm_time, _) = self.testvm1.run("date -u +%s",
                                            passio_popen=True).communicate()
            self.assertAlmostEquals(int(vm_time), int(start_time), delta=30)
            (vm_time, _) = self.testvm2.run("date -u +%s",
                                            passio_popen=True).communicate()
            self.assertAlmostEquals(int(vm_time), int(start_time), delta=30)
            (dom0_time, _) = subprocess.Popen(["date", "-u", "+%s"],
                                              stdout=subprocess.PIPE
                                              ).communicate()
            self.assertAlmostEquals(int(dom0_time), int(start_time), delta=30)

        except:
            # reset time to some approximation of the real time
            subprocess.Popen(["sudo", "date", "-u", "-s", "@" + start_time])
            raise
        finally:
            subprocess.call(["qubes-prefs", "-s", "clockvm",
                             original_clockvm_name])

    def test_250_resize_private_img(self):
        """
        Test private.img resize, both offline and online
        :return:
        """
        # First offline test
        self.testvm1.resize_private_img(4*1024**3)
        self.testvm1.start()
        df_cmd = '( df --output=size /rw || df /rw | awk \'{print $2}\' )|' \
                 'tail -n 1'
        p = self.testvm1.run(df_cmd,
                             passio_popen=True)
        # new_size in 1k-blocks
        (new_size, _) = p.communicate()
        # some safety margin for FS metadata
        self.assertGreater(int(new_size.strip()), 3.8*1024**2)
        # Then online test
        self.testvm1.resize_private_img(6*1024**3)
        p = self.testvm1.run(df_cmd,
                             passio_popen=True)
        # new_size in 1k-blocks
        (new_size, _) = p.communicate()
        # some safety margin for FS metadata
        self.assertGreater(int(new_size.strip()), 5.8*1024**2)


def load_tests(loader, tests, pattern):
    try:
        qc = qubes.qubes.QubesVmCollection()
        qc.lock_db_for_reading()
        qc.load()
        qc.unlock_db()
        templates = [vm.name for vm in qc.values() if
                     isinstance(vm, qubes.qubes.QubesTemplateVm)]
    except OSError:
        templates = []
    for template in templates:
        tests.addTests(loader.loadTestsFromTestCase(
            type(
                'TC_00_AppVM_' + template,
                (TC_00_AppVMMixin, qubes.tests.QubesTestCase),
                {'template': template})))

    return tests
