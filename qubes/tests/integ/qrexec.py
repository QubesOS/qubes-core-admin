#
# The Qubes OS Project, https://www.qubes-os.org/
#
# Copyright (C) 2014-2020
#                   Marek Marczykowski-Górecki <marmarek@invisiblethingslab.com>
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

import asyncio
import contextlib
import os
import subprocess
import sys

import qubes.config
import qubes.devices
import qubes.tests
import qubes.vm.appvm
import qubes.vm.templatevm

TEST_DATA = b"0123456789" * 1024


class TC_00_QrexecMixin(object):
    def setUp(self):
        super().setUp()
        self.init_default_template(self.template)
        if self._testMethodName == "test_210_time_sync":
            self.init_networking()
        self.testvm1 = self.app.add_new_vm(
            qubes.vm.appvm.AppVM,
            label="red",
            name=self.make_vm_name("vm1"),
            template=self.app.domains[self.template],
        )
        self.loop.run_until_complete(self.testvm1.create_on_disk())
        self.testvm2 = self.app.add_new_vm(
            qubes.vm.appvm.AppVM,
            label="red",
            name=self.make_vm_name("vm2"),
            template=self.app.domains[self.template],
        )
        self.loop.run_until_complete(self.testvm2.create_on_disk())
        self.app.save()

    def tearDown(self):
        if not self.success():
            if self.testvm1.is_running():
                p = self.loop.run_until_complete(
                    self.testvm1.run("cat /home/user/.xsession-errors")
                )
                self.loop.run_until_complete(p.communicate())
            if self.testvm2.is_running():
                p = self.loop.run_until_complete(
                    self.testvm2.run("cat /home/user/.xsession-errors")
                )
                self.loop.run_until_complete(p.communicate())
        # socket-based qrexec tests:
        if os.path.exists("/etc/qubes-rpc/test.Socket"):
            os.unlink("/etc/qubes-rpc/test.Socket")
        if hasattr(self, "service_proc"):
            try:
                self.service_proc.terminate()
                self.loop.run_until_complete(self.service_proc.communicate())
            except ProcessLookupError:
                pass

        super().tearDown()

    def test_050_qrexec_simple_eof(self):
        """Test for data and EOF transmission dom0->VM"""

        # XXX is this still correct? this is no longer simple qrexec,
        # but qubes.VMShell

        self.loop.run_until_complete(self.testvm1.start())
        try:
            (stdout, stderr) = self.loop.run_until_complete(
                asyncio.wait_for(
                    self.testvm1.run_for_stdio("cat", input=TEST_DATA),
                    timeout=10,
                )
            )
        except asyncio.TimeoutError:
            self.fail(
                "Timeout, probably EOF wasn't transferred to the VM process"
            )

        self.assertEqual(
            stdout, TEST_DATA, "Received data differs from what was sent"
        )
        self.assertFalse(stderr, "Some data was printed to stderr")

    def test_051_qrexec_simple_eof_reverse(self):
        """Test for EOF transmission VM->dom0"""

        async def run(self):
            p = await self.testvm1.run(
                "echo test; exec >&-; cat > /dev/null",
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            # this will hang on test failure
            stdout = await asyncio.wait_for(p.stdout.read(), timeout=10)

            p.stdin.write(TEST_DATA)
            await p.stdin.drain()
            p.stdin.close()
            self.assertEqual(
                stdout.strip(),
                b"test",
                "Received data differs from what was expected",
            )
            # this may hang in some buggy cases
            self.assertFalse(
                (await p.stderr.read()), "Some data was printed to stderr"
            )

            try:
                await asyncio.wait_for(p.wait(), timeout=1)
            except asyncio.TimeoutError:
                self.fail(
                    "Timeout, "
                    "probably EOF wasn't transferred from the VM process"
                )

        self.loop.run_until_complete(self.testvm1.start())
        self.loop.run_until_complete(self.wait_for_session(self.testvm1))
        self.loop.run_until_complete(run(self))

    def test_052_qrexec_vm_service_eof(self):
        """Test for EOF transmission VM(src)->VM(dst)"""

        self.loop.run_until_complete(
            asyncio.gather(self.testvm1.start(), self.testvm2.start())
        )
        self.loop.run_until_complete(
            asyncio.gather(
                self.wait_for_session(self.testvm1),
                self.wait_for_session(self.testvm2),
            )
        )
        self.create_remote_file(
            self.testvm2, "/etc/qubes-rpc/test.EOF", "#!/bin/sh\n/bin/cat\n"
        )

        with self.qrexec_policy("test.EOF", self.testvm1, self.testvm2):
            try:
                stdout, _ = self.loop.run_until_complete(
                    asyncio.wait_for(
                        self.testvm1.run_for_stdio(
                            """\
                        /usr/lib/qubes/qrexec-client-vm {} test.EOF \
                            /bin/sh -c 'echo test; exec >&-; cat >&$SAVED_FD_1'
                    """.format(
                                self.testvm2.name
                            )
                        ),
                        timeout=10,
                    )
                )
            except subprocess.CalledProcessError as e:
                self.fail(
                    "{} exited with non-zero code {}; stderr: {}".format(
                        e.cmd, e.returncode, e.stderr
                    )
                )
            except asyncio.TimeoutError:
                self.fail("Timeout, probably EOF wasn't transferred")

        self.assertEqual(
            stdout, b"test\n", "Received data differs from what was expected"
        )

    def test_053_qrexec_vm_service_eof_reverse(self):
        """Test for EOF transmission VM(src)<-VM(dst)"""

        self.loop.run_until_complete(
            asyncio.gather(self.testvm1.start(), self.testvm2.start())
        )
        self.create_remote_file(
            self.testvm2,
            "/etc/qubes-rpc/test.EOF",
            "#!/bin/sh\n" "echo test; exec >&-; cat >/dev/null",
        )

        with self.qrexec_policy("test.EOF", self.testvm1, self.testvm2):
            try:
                stdout, _ = self.loop.run_until_complete(
                    asyncio.wait_for(
                        self.testvm1.run_for_stdio(
                            """\
                        /usr/lib/qubes/qrexec-client-vm {} test.EOF \
                            /bin/sh -c 'cat >&$SAVED_FD_1'
                        """.format(
                                self.testvm2.name
                            )
                        ),
                        timeout=10,
                    )
                )
            except subprocess.CalledProcessError as e:
                self.fail(
                    "{} exited with non-zero code {}; stderr: {}".format(
                        e.cmd, e.returncode, e.stderr
                    )
                )
            except asyncio.TimeoutError:
                self.fail("Timeout, probably EOF wasn't transferred")

        self.assertEqual(
            stdout, b"test\n", "Received data differs from what was expected"
        )

    def test_055_qrexec_dom0_service_abort(self):
        """
        Test if service abort (by dom0) is properly handled by source VM.

        If "remote" part of the service terminates, the source part should
        properly be notified. This includes closing its stdin (which is
        already checked by test_053_qrexec_vm_service_eof_reverse), but also
        its stdout - otherwise such service might hang on write(2) call.
        """

        self.loop.run_until_complete(self.testvm1.start())
        self.create_local_file("/etc/qubes-rpc/test.Abort", "sleep 1")

        with self.qrexec_policy("test.Abort", self.testvm1, "dom0"):
            try:
                # two possible exit codes, depending on when exactly dom0
                # service terminates:
                # exit code 141: EPIPE (no buffered data)
                # exit code 1: ECONNRESET (some buffered data remains)
                stdout, _ = self.loop.run_until_complete(
                    asyncio.wait_for(
                        self.testvm1.run_for_stdio(
                            """\
                        /usr/lib/qubes/qrexec-client-vm dom0 test.Abort \
                            /bin/sh -c 'cat /dev/zero; echo $? >/tmp/exit-code';
                            sleep 1;
                            e=$(cat /tmp/exit-code);
                            test $e -eq 141 -o $e -eq 1"""
                        ),
                        timeout=10,
                    )
                )
            except subprocess.CalledProcessError as e:
                self.fail(
                    "{} exited with non-zero code {}; stderr: {}".format(
                        e.cmd, e.returncode, e.stderr
                    )
                )
            except asyncio.TimeoutError:
                self.fail("Timeout, probably stdout wasn't closed")

    def test_060_qrexec_exit_code_dom0(self):
        self.loop.run_until_complete(self.testvm1.start())
        self.loop.run_until_complete(self.testvm1.run_for_stdio("exit 0"))
        with self.assertRaises(subprocess.CalledProcessError) as e:
            self.loop.run_until_complete(self.testvm1.run_for_stdio("exit 3"))
        self.assertEqual(e.exception.returncode, 3)

    def test_065_qrexec_exit_code_vm(self):
        self.loop.run_until_complete(
            asyncio.gather(self.testvm1.start(), self.testvm2.start())
        )

        with self.qrexec_policy("test.Retcode", self.testvm1, self.testvm2):
            self.create_remote_file(
                self.testvm2, "/etc/qubes-rpc/test.Retcode", "exit 0"
            )
            (stdout, stderr) = self.loop.run_until_complete(
                self.testvm1.run_for_stdio(
                    """\
                    /usr/lib/qubes/qrexec-client-vm {} test.Retcode;
                        echo $?""".format(
                        self.testvm2.name
                    ),
                    stderr=None,
                )
            )
            self.assertEqual(stdout, b"0\n")

            self.create_remote_file(
                self.testvm2, "/etc/qubes-rpc/test.Retcode", "exit 3"
            )
            (stdout, stderr) = self.loop.run_until_complete(
                self.testvm1.run_for_stdio(
                    """\
                    /usr/lib/qubes/qrexec-client-vm {} test.Retcode;
                        echo $?""".format(
                        self.testvm2.name
                    ),
                    stderr=None,
                )
            )
            self.assertEqual(stdout, b"3\n")

    def test_070_qrexec_vm_simultaneous_write(self):
        """Test for simultaneous write in VM(src)->VM(dst) connection

        This is regression test for #1347

        Check for deadlock when initially both sides writes a lot of data
        (and not read anything). When one side starts reading, it should
        get the data and the remote side should be possible to write then more.
        There was a bug where remote side was waiting on write(2) and not
        handling anything else.
        """

        self.loop.run_until_complete(
            asyncio.gather(self.testvm1.start(), self.testvm2.start())
        )

        self.create_remote_file(
            self.testvm2,
            "/etc/qubes-rpc/test.write",
            """\
            # first write a lot of data
            dd if=/dev/zero bs=993 count=10000 iflag=fullblock
            # and only then read something
            dd of=/dev/null bs=993 count=10000 iflag=fullblock
            """,
        )

        with self.qrexec_policy("test.write", self.testvm1, self.testvm2):
            try:
                self.loop.run_until_complete(
                    asyncio.wait_for(
                        # first write a lot of data to fill all the buffers
                        # then after some time start reading
                        self.testvm1.run_for_stdio(
                            """\
                        /usr/lib/qubes/qrexec-client-vm {} test.write \
                                /bin/sh -c '
                            dd if=/dev/zero bs=993 count=10000 iflag=fullblock &
                            sleep 1;
                            dd of=/dev/null bs=993 count=10000 iflag=fullblock;
                            wait'
                        """.format(
                                self.testvm2.name
                            )
                        ),
                        timeout=10,
                    )
                )
            except subprocess.CalledProcessError as e:
                self.fail(
                    "{} exited with non-zero code {}; stderr: {}".format(
                        e.cmd, e.returncode, e.stderr
                    )
                )
            except asyncio.TimeoutError:
                self.fail("Timeout, probably deadlock")

    def test_071_qrexec_dom0_simultaneous_write(self):
        """Test for simultaneous write in dom0(src)->VM(dst) connection

        Similar to test_070_qrexec_vm_simultaneous_write, but with dom0
        as a source.
        """

        self.loop.run_until_complete(self.testvm2.start())

        self.create_remote_file(
            self.testvm2,
            "/etc/qubes-rpc/test.write",
            """\
            # first write a lot of data
            dd if=/dev/zero bs=993 count=10000 iflag=fullblock
            # and only then read something
            dd of=/dev/null bs=993 count=10000 iflag=fullblock
            """,
        )

        # can't use subprocess.PIPE, because asyncio will claim those FDs
        pipe1_r, pipe1_w = os.pipe()
        pipe2_r, pipe2_w = os.pipe()
        try:
            local_proc = self.loop.run_until_complete(
                asyncio.create_subprocess_shell(
                    # first write a lot of data to fill all the buffers
                    "dd if=/dev/zero bs=993 count=10000 iflag=fullblock & "
                    # then after some time start reading
                    "sleep 1; "
                    "dd of=/dev/null bs=993 count=10000 iflag=fullblock; "
                    "wait",
                    stdin=pipe1_r,
                    stdout=pipe2_w,
                )
            )

            self.service_proc = self.loop.run_until_complete(
                self.testvm2.run_service(
                    "test.write", stdin=pipe2_r, stdout=pipe1_w
                )
            )
        finally:
            os.close(pipe1_r)
            os.close(pipe1_w)
            os.close(pipe2_r)
            os.close(pipe2_w)

        try:
            self.loop.run_until_complete(
                asyncio.wait_for(self.service_proc.wait(), timeout=10)
            )
        except asyncio.TimeoutError:
            self.fail("Timeout, probably deadlock")
        else:
            self.assertEqual(
                self.service_proc.returncode, 0, "Service call failed"
            )

    def test_072_qrexec_to_dom0_simultaneous_write(self):
        """Test for simultaneous write in dom0(src)<-VM(dst) connection

        Similar to test_071_qrexec_dom0_simultaneous_write, but with dom0
        as a "hanging" side.
        """

        self.loop.run_until_complete(self.testvm2.start())

        self.create_remote_file(
            self.testvm2,
            "/etc/qubes-rpc/test.write",
            """\
            # first write a lot of data
            dd if=/dev/zero bs=993 count=10000 iflag=fullblock &
            # and only then read something
            dd of=/dev/null bs=993 count=10000 iflag=fullblock
            sleep 1;
            wait
            """,
        )

        # can't use subprocess.PIPE, because asyncio will claim those FDs
        pipe1_r, pipe1_w = os.pipe()
        pipe2_r, pipe2_w = os.pipe()
        try:
            local_proc = self.loop.run_until_complete(
                asyncio.create_subprocess_shell(
                    # first write a lot of data to fill all the buffers
                    "dd if=/dev/zero bs=993 count=10000 iflag=fullblock & "
                    # then, only when all written, read something
                    "dd of=/dev/null bs=993 count=10000 iflag=fullblock; ",
                    stdin=pipe1_r,
                    stdout=pipe2_w,
                )
            )

            self.service_proc = self.loop.run_until_complete(
                self.testvm2.run_service(
                    "test.write", stdin=pipe2_r, stdout=pipe1_w
                )
            )
        finally:
            os.close(pipe1_r)
            os.close(pipe1_w)
            os.close(pipe2_r)
            os.close(pipe2_w)

        try:
            self.loop.run_until_complete(
                asyncio.wait_for(self.service_proc.wait(), timeout=10)
            )
        except asyncio.TimeoutError:
            self.fail("Timeout, probably deadlock")
        else:
            self.assertEqual(
                self.service_proc.returncode, 0, "Service call failed"
            )

    def test_080_qrexec_service_argument_allow_default(self):
        """Qrexec service call with argument"""

        self.loop.run_until_complete(
            asyncio.gather(self.testvm1.start(), self.testvm2.start())
        )

        self.create_remote_file(
            self.testvm2,
            "/etc/qubes-rpc/test.Argument",
            '/usr/bin/printf %s "$1"',
        )
        with self.qrexec_policy("test.Argument", self.testvm1, self.testvm2):
            stdout, stderr = self.loop.run_until_complete(
                self.testvm1.run_for_stdio(
                    "/usr/lib/qubes/qrexec-client-vm "
                    "{} test.Argument+argument".format(self.testvm2.name),
                    stderr=None,
                )
            )
            self.assertEqual(stdout, b"argument")

    def test_081_qrexec_service_argument_allow_specific(self):
        """Qrexec service call with argument - allow only specific value"""

        self.loop.run_until_complete(
            asyncio.gather(self.testvm1.start(), self.testvm2.start())
        )

        self.create_remote_file(
            self.testvm2,
            "/etc/qubes-rpc/test.Argument",
            '/usr/bin/printf %s "$1"',
        )

        with self.qrexec_policy("test.Argument", "$anyvm", "$anyvm", False):
            with self.qrexec_policy(
                "test.Argument+argument", self.testvm1.name, self.testvm2.name
            ):
                stdout, stderr = self.loop.run_until_complete(
                    self.testvm1.run_for_stdio(
                        "/usr/lib/qubes/qrexec-client-vm "
                        "{} test.Argument+argument".format(self.testvm2.name),
                        stderr=None,
                    )
                )
        self.assertEqual(stdout, b"argument")

    def test_082_qrexec_service_argument_deny_specific(self):
        """Qrexec service call with argument - deny specific value"""
        self.loop.run_until_complete(
            asyncio.gather(self.testvm1.start(), self.testvm2.start())
        )

        self.create_remote_file(
            self.testvm2,
            "/etc/qubes-rpc/test.Argument",
            '/usr/bin/printf %s "$1"',
        )
        with self.qrexec_policy("test.Argument", "$anyvm", "$anyvm"):
            with self.qrexec_policy(
                "test.Argument+argument",
                self.testvm1,
                self.testvm2,
                allow=False,
            ):
                with self.assertRaises(
                    subprocess.CalledProcessError,
                    msg="Service request should be denied",
                ):
                    self.loop.run_until_complete(
                        self.testvm1.run_for_stdio(
                            "/usr/lib/qubes/qrexec-client-vm {} "
                            "test.Argument+argument".format(self.testvm2.name),
                            stderr=None,
                        )
                    )

    def test_083_qrexec_service_argument_specific_implementation(self):
        """Qrexec service call with argument - argument specific
        implementatation"""
        self.loop.run_until_complete(
            asyncio.gather(self.testvm1.start(), self.testvm2.start())
        )

        self.create_remote_file(
            self.testvm2,
            "/etc/qubes-rpc/test.Argument",
            '/usr/bin/printf %s "$1"',
        )
        self.create_remote_file(
            self.testvm2,
            "/etc/qubes-rpc/test.Argument+argument",
            '/usr/bin/printf "specific: %s" "$1"',
        )

        with self.qrexec_policy("test.Argument", self.testvm1, self.testvm2):
            stdout, stderr = self.loop.run_until_complete(
                self.testvm1.run_for_stdio(
                    "/usr/lib/qubes/qrexec-client-vm "
                    "{} test.Argument+argument".format(self.testvm2.name),
                    stderr=None,
                )
            )

        self.assertEqual(stdout, b"specific: argument")

    def test_084_qrexec_service_argument_extra_env(self):
        """Qrexec service call with argument - extra env variables"""
        self.loop.run_until_complete(
            asyncio.gather(self.testvm1.start(), self.testvm2.start())
        )

        self.create_remote_file(
            self.testvm2,
            "/etc/qubes-rpc/test.Argument",
            '/usr/bin/printf "%s %s" '
            '"$QREXEC_SERVICE_FULL_NAME" "$QREXEC_SERVICE_ARGUMENT"',
        )

        with self.qrexec_policy("test.Argument", self.testvm1, self.testvm2):
            stdout, stderr = self.loop.run_until_complete(
                self.testvm1.run_for_stdio(
                    "/usr/lib/qubes/qrexec-client-vm "
                    "{} test.Argument+argument".format(self.testvm2.name),
                    stderr=None,
                )
            )

        self.assertEqual(stdout, b"test.Argument+argument argument")

    def test_090_qrexec_service_socket_dom0(self):
        """Basic test socket services (dom0) - data receive"""
        self.loop.run_until_complete(self.testvm1.start())

        self.service_proc = self.loop.run_until_complete(
            asyncio.create_subprocess_shell(
                "socat -u UNIX-LISTEN:/etc/qubes-rpc/test.Socket,mode=666 -",
                stdout=subprocess.PIPE,
                stdin=subprocess.PIPE,
            )
        )

        try:
            with self.qrexec_policy("test.Socket", self.testvm1, "@adminvm"):
                (stdout, stderr) = self.loop.run_until_complete(
                    asyncio.wait_for(
                        self.testvm1.run_for_stdio(
                            "qrexec-client-vm @adminvm test.Socket",
                            input=TEST_DATA,
                        ),
                        timeout=10,
                    )
                )
        except subprocess.CalledProcessError as e:
            self.fail(
                "{} exited with non-zero code {}; stderr: {}".format(
                    e.cmd, e.returncode, e.stderr
                )
            )
        except asyncio.TimeoutError:
            self.fail(
                "service timeout, probably EOF wasn't transferred to the VM process"
            )

        try:
            (service_stdout, service_stderr) = self.loop.run_until_complete(
                asyncio.wait_for(self.service_proc.communicate(), timeout=10)
            )
        except asyncio.TimeoutError:
            self.fail(
                "socat timeout, probably EOF wasn't transferred to the VM process"
            )

        service_descriptor = b"test.Socket+ test-inst-vm1 keyword adminvm\0"
        self.assertEqual(
            service_stdout,
            service_descriptor + TEST_DATA,
            "Received data differs from what was sent",
        )
        self.assertFalse(stderr, "Some data was printed to stderr")
        self.assertFalse(service_stderr, "Some data was printed to stderr")

    def test_091_qrexec_service_socket_dom0_send(self):
        """Basic test socket services (dom0) - data send"""
        self.loop.run_until_complete(self.testvm1.start())

        self.create_local_file("/tmp/service-input", TEST_DATA.decode())

        self.service_proc = self.loop.run_until_complete(
            asyncio.create_subprocess_shell(
                "socat -u OPEN:/tmp/service-input UNIX-LISTEN:/etc/qubes-rpc/test.Socket,mode=666"
            )
        )

        try:
            with self.qrexec_policy("test.Socket", self.testvm1, "@adminvm"):
                stdout, stderr = self.loop.run_until_complete(
                    asyncio.wait_for(
                        self.testvm1.run_for_stdio(
                            "qrexec-client-vm @adminvm test.Socket"
                        ),
                        timeout=10,
                    )
                )
        except subprocess.CalledProcessError as e:
            self.fail(
                "{} exited with non-zero code {}; stderr: {}".format(
                    e.cmd, e.returncode, e.stderr
                )
            )
        except asyncio.TimeoutError:
            self.fail(
                "service timeout, probably EOF wasn't transferred to the VM process"
            )

        try:
            (service_stdout, service_stderr) = self.loop.run_until_complete(
                asyncio.wait_for(self.service_proc.communicate(), timeout=10)
            )
        except asyncio.TimeoutError:
            self.fail(
                "socat timeout, probably EOF wasn't transferred to the VM process"
            )

        self.assertEqual(
            stdout, TEST_DATA, "Received data differs from what was sent"
        )
        self.assertFalse(stderr, "Some data was printed to stderr")
        self.assertFalse(service_stderr, "Some data was printed to stderr")

    def test_092_qrexec_service_socket_dom0_eof_reverse(self):
        """Test for EOF transmission dom0(socket)->VM"""

        self.loop.run_until_complete(self.testvm1.start())

        self.create_local_file(
            "/tmp/service_script",
            "#!/usr/bin/python3\n"
            "import socket, os, sys, time\n"
            "s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)\n"
            "os.umask(0)\n"
            's.bind("/etc/qubes-rpc/test.Socket")\n'
            "s.listen(1)\n"
            "conn, addr = s.accept()\n"
            'conn.send(b"test\\n")\n'
            "conn.shutdown(socket.SHUT_WR)\n"
            # wait longer than the timeout below
            "time.sleep(15)\n",
        )

        self.service_proc = self.loop.run_until_complete(
            asyncio.create_subprocess_shell(
                "python3 /tmp/service_script",
                stdout=subprocess.PIPE,
                stdin=subprocess.PIPE,
            )
        )

        try:
            with self.qrexec_policy("test.Socket", self.testvm1, "@adminvm"):
                p = self.loop.run_until_complete(
                    self.testvm1.run(
                        "qrexec-client-vm @adminvm test.Socket",
                        stdout=subprocess.PIPE,
                        stdin=subprocess.PIPE,
                    )
                )

                stdout = self.loop.run_until_complete(
                    asyncio.wait_for(p.stdout.read(), timeout=10)
                )
        except asyncio.TimeoutError:
            self.fail(
                "service timeout, probably EOF wasn't transferred from the VM process"
            )
        finally:
            with contextlib.suppress(ProcessLookupError):
                p.terminate()
            self.loop.run_until_complete(p.wait())

        self.assertEqual(
            stdout, b"test\n", "Received data differs from what was expected"
        )

    def test_093_qrexec_service_socket_dom0_eof(self):
        """Test for EOF transmission VM->dom0(socket)"""

        self.loop.run_until_complete(self.testvm1.start())

        self.create_local_file(
            "/tmp/service_script",
            "#!/usr/bin/python3\n"
            "import socket, os, sys, time\n"
            "s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)\n"
            "os.umask(0)\n"
            's.bind("/etc/qubes-rpc/test.Socket")\n'
            "s.listen(1)\n"
            "conn, addr = s.accept()\n"
            "buf = conn.recv(100)\n"
            "sys.stdout.buffer.write(buf)\n"
            "buf = conn.recv(10)\n"
            "sys.stdout.buffer.write(buf)\n"
            "sys.stdout.buffer.flush()\n"
            "os.close(1)\n"
            # wait longer than the timeout below
            "time.sleep(15)\n",
        )

        self.service_proc = self.loop.run_until_complete(
            asyncio.create_subprocess_shell(
                "python3 /tmp/service_script",
                stdout=subprocess.PIPE,
                stdin=subprocess.PIPE,
            )
        )

        try:
            with self.qrexec_policy("test.Socket", self.testvm1, "@adminvm"):
                p = self.loop.run_until_complete(
                    self.testvm1.run(
                        "qrexec-client-vm @adminvm test.Socket",
                        stdin=subprocess.PIPE,
                    )
                )

                p.stdin.write(b"test1test2")
                p.stdin.write_eof()

                service_stdout = self.loop.run_until_complete(
                    asyncio.wait_for(
                        self.service_proc.stdout.read(), timeout=10
                    )
                )
        except asyncio.TimeoutError:
            self.fail(
                "service timeout, probably EOF wasn't transferred from the VM process"
            )
        finally:
            with contextlib.suppress(ProcessLookupError):
                p.terminate()
            self.loop.run_until_complete(p.wait())

        service_descriptor = b"test.Socket+ test-inst-vm1 keyword adminvm\0"
        self.assertEqual(
            service_stdout,
            service_descriptor + b"test1test2",
            "Received data differs from what was expected",
        )

    def _wait_for_socket_setup(self):
        try:
            self.loop.run_until_complete(
                asyncio.wait_for(
                    self.testvm1.run_for_stdio(
                        "while ! test -e /etc/qubes-rpc/test.Socket; do sleep 0.1; done"
                    ),
                    timeout=10,
                )
            )
        except asyncio.TimeoutError:
            self.fail("waiting for /etc/qubes-rpc/test.Socket in VM timed out")

    def test_095_qrexec_service_socket_vm(self):
        """Basic test socket services (VM) - receive"""
        self.loop.run_until_complete(self.testvm1.start())

        self.service_proc = self.loop.run_until_complete(
            self.testvm1.run(
                "socat -u UNIX-LISTEN:/etc/qubes-rpc/test.Socket,mode=666 -",
                stdout=subprocess.PIPE,
                stdin=subprocess.PIPE,
                user="root",
            )
        )

        self._wait_for_socket_setup()

        try:
            (stdout, stderr) = self.loop.run_until_complete(
                asyncio.wait_for(
                    self.testvm1.run_service_for_stdio(
                        "test.Socket+", input=TEST_DATA
                    ),
                    timeout=10,
                )
            )
        except subprocess.CalledProcessError as e:
            self.fail(
                "{} exited with non-zero code {}; stderr: {}".format(
                    e.cmd, e.returncode, e.stderr
                )
            )
        except asyncio.TimeoutError:
            self.fail(
                "service timeout, probably EOF wasn't transferred to the VM process"
            )

        try:
            (service_stdout, service_stderr) = self.loop.run_until_complete(
                asyncio.wait_for(self.service_proc.communicate(), timeout=10)
            )
        except asyncio.TimeoutError:
            self.fail(
                "socat timeout, probably EOF wasn't transferred to the VM process"
            )

        service_descriptor = b"test.Socket+ dom0\0"
        self.assertEqual(
            service_stdout,
            service_descriptor + TEST_DATA,
            "Received data differs from what was sent",
        )
        self.assertFalse(stderr, "Some data was printed to stderr")
        self.assertFalse(service_stderr, "Some data was printed to stderr")

    def test_096_qrexec_service_socket_vm_send(self):
        """Basic test socket services (VM) - send"""
        self.loop.run_until_complete(self.testvm1.start())

        self.create_remote_file(
            self.testvm1, "/tmp/service-input", TEST_DATA.decode()
        )

        self.service_proc = self.loop.run_until_complete(
            self.testvm1.run(
                "socat -u OPEN:/tmp/service-input UNIX-LISTEN:/etc/qubes-rpc/test.Socket,mode=666",
                user="root",
            )
        )

        self._wait_for_socket_setup()

        try:
            (stdout, stderr) = self.loop.run_until_complete(
                asyncio.wait_for(
                    self.testvm1.run_service_for_stdio("test.Socket+"),
                    timeout=10,
                )
            )
        except subprocess.CalledProcessError as e:
            self.fail(
                "{} exited with non-zero code {}; stderr: {}".format(
                    e.cmd, e.returncode, e.stderr
                )
            )
        except asyncio.TimeoutError:
            self.fail(
                "service timeout, probably EOF wasn't transferred to the VM process"
            )

        try:
            (service_stdout, service_stderr) = self.loop.run_until_complete(
                asyncio.wait_for(self.service_proc.communicate(), timeout=10)
            )
        except asyncio.TimeoutError:
            self.fail(
                "socat timeout, probably EOF wasn't transferred to the VM process"
            )

        self.assertEqual(
            stdout, TEST_DATA, "Received data differs from what was sent"
        )
        self.assertFalse(stderr, "Some data was printed to stderr")
        self.assertFalse(service_stderr, "Some data was printed to stderr")

    def test_097_qrexec_service_socket_vm_eof_reverse(self):
        """Test for EOF transmission VM(socket)->dom0"""

        self.loop.run_until_complete(self.testvm1.start())

        self.create_remote_file(
            self.testvm1,
            "/tmp/service_script",
            "#!/usr/bin/python3\n"
            "import socket, os, sys, time\n"
            "s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)\n"
            "os.umask(0)\n"
            's.bind("/etc/qubes-rpc/test.Socket")\n'
            "s.listen(1)\n"
            "conn, addr = s.accept()\n"
            'conn.send(b"test\\n")\n'
            "conn.shutdown(socket.SHUT_WR)\n"
            # wait longer than the timeout below
            "time.sleep(15)\n",
        )

        self.service_proc = self.loop.run_until_complete(
            self.testvm1.run(
                "python3 /tmp/service_script",
                stdout=subprocess.PIPE,
                stdin=subprocess.PIPE,
                user="root",
            )
        )

        self._wait_for_socket_setup()

        try:
            p = self.loop.run_until_complete(
                self.testvm1.run_service(
                    "test.Socket+",
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                )
            )
            stdout = self.loop.run_until_complete(
                asyncio.wait_for(p.stdout.read(), timeout=10)
            )
        except asyncio.TimeoutError:
            p.terminate()
            self.fail(
                "service timeout, probably EOF wasn't transferred from the VM process"
            )
        finally:
            self.loop.run_until_complete(p.wait())

        self.assertEqual(
            stdout, b"test\n", "Received data differs from what was expected"
        )

    def test_098_qrexec_service_socket_vm_eof(self):
        """Test for EOF transmission dom0->VM(socket)"""

        self.loop.run_until_complete(self.testvm1.start())

        self.create_remote_file(
            self.testvm1,
            "/tmp/service_script",
            "#!/usr/bin/python3\n"
            "import socket, os, sys, time\n"
            "s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)\n"
            "os.umask(0)\n"
            's.bind("/etc/qubes-rpc/test.Socket")\n'
            "s.listen(1)\n"
            "conn, addr = s.accept()\n"
            "buf = conn.recv(100)\n"
            "sys.stdout.buffer.write(buf)\n"
            "buf = conn.recv(10)\n"
            "sys.stdout.buffer.write(buf)\n"
            "sys.stdout.buffer.flush()\n"
            "os.close(1)\n"
            # wait longer than the timeout below
            "time.sleep(15)\n",
        )

        self.service_proc = self.loop.run_until_complete(
            self.testvm1.run(
                "python3 /tmp/service_script",
                stdout=subprocess.PIPE,
                stdin=subprocess.PIPE,
                user="root",
            )
        )

        self._wait_for_socket_setup()

        try:
            p = self.loop.run_until_complete(
                self.testvm1.run_service(
                    "test.Socket+",
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                )
            )
            p.stdin.write(b"test1test2")
            self.loop.run_until_complete(
                asyncio.wait_for(p.stdin.drain(), timeout=10)
            )
            p.stdin.close()

            service_stdout = self.loop.run_until_complete(
                asyncio.wait_for(self.service_proc.stdout.read(), timeout=10)
            )
        except asyncio.TimeoutError:
            p.terminate()
            self.fail(
                "service timeout, probably EOF wasn't transferred to the VM process"
            )
        finally:
            self.loop.run_until_complete(p.wait())

        service_descriptor = b"test.Socket+ dom0\0"
        self.assertEqual(
            service_stdout,
            service_descriptor + b"test1test2",
            "Received data differs from what was expected",
        )

    def test_100_qrexec_service_force_user(self):
        self.loop.run_until_complete(self.testvm1.start())

        self.create_remote_file(
            self.testvm1,
            "/etc/qubes-rpc/test.User",
            "#!/bin/sh\n/usr/bin/id -u\n",
        )
        self.create_remote_file(
            self.testvm1,
            "/etc/qubes/rpc-config/test.User",
            "force-user='root'\n",
        )

        stdout, stderr = self.loop.run_until_complete(
            self.testvm1.run_service_for_stdio("test.User")
        )
        self.assertEqual(stdout.strip(), b"0")
        self.assertEqual(stderr.strip(), b"")


def create_testcases_for_templates():
    return qubes.tests.create_testcases_for_templates(
        "TC_00_Qrexec",
        TC_00_QrexecMixin,
        qubes.tests.SystemTestCase,
        module=sys.modules[__name__],
    )


def load_tests(loader, tests, pattern):
    tests.addTests(loader.loadTestsFromNames(create_testcases_for_templates()))
    return tests


qubes.tests.maybe_create_testcases_on_import(create_testcases_for_templates)
