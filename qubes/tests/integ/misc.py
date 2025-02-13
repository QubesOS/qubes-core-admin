#
# The Qubes OS Project, https://www.qubes-os.org/
#
# Copyright (C) 2025 Marek Marczykowski-Górecki
#                           <marmarek@invisiblethingslab.com>
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
import asyncio
import contextlib
import subprocess
import sys
import unittest
from distutils import spawn

import qubes


class TC_06_AppVMMixin(object):
    template = None

    def setUp(self):
        super(TC_06_AppVMMixin, self).setUp()
        self.init_default_template(self.template)

    def test_010_os_metadata(self):
        tpl = self.app.default_template
        if self.template.startswith("fedora-"):
            self.assertEqual(tpl.features.get("os-distribution"), "fedora")
            version = self.template.split("-")[1]
            self.assertEqual(tpl.features.get("os-version"), version)
            self.assertIsNotNone(tpl.features.get("os-eol"))
        elif self.template.startswith("debian-"):
            self.assertEqual(tpl.features.get("os-distribution"), "debian")
            version = self.template.split("-")[1]
            self.assertEqual(tpl.features.get("os-version"), version)
            self.assertIsNotNone(tpl.features.get("os-eol"))
        elif self.template.startswith("whonix-"):
            self.assertEqual(tpl.features.get("os-distribution"), "whonix")
            self.assertEqual(tpl.features.get("os-distribution-like"), "debian")
            version = self.template.split("-")[2]
            self.assertEqual(tpl.features.get("os-version"), version)
        elif self.template.startswith("kali-core"):
            self.assertEqual(tpl.features.get("os-distribution"), "kali")
            self.assertEqual(tpl.features.get("os-distribution-like"), "debian")

    def test_110_rescue_console(self):
        self.loop.run_until_complete(self._test_110_rescue_console())

    async def _test_110_rescue_console(self):
        self.testvm = self.app.add_new_vm(
            "AppVM", label="red", name=self.make_vm_name("vm")
        )
        await self.testvm.create_on_disk()
        self.testvm.kernelopts = "emergency"
        # avoid qrexec timeout
        self.testvm.features["qrexec"] = ""
        self.app.save()
        await self.testvm.start()
        # call admin.vm.Console via qrexec-client so it sets all the variables
        console_proc = await asyncio.create_subprocess_exec(
            "qrexec-client",
            "-d",
            "dom0",
            f"DEFAULT:QUBESRPC admin.vm.Console dom0 name {self.testvm.name}",
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
        )
        try:
            await asyncio.wait_for(
                self._interact_emergency_console(console_proc), 120
            )
        finally:
            with contextlib.suppress(ProcessLookupError):
                console_proc.terminate()
            await console_proc.communicate()

    async def _interact_emergency_console(
        self, console_proc: asyncio.subprocess.Process
    ):
        emergency_mode_found = False
        whoami_typed = False
        while True:
            try:
                line = await asyncio.wait_for(
                    console_proc.stdout.readline(), 30
                )
            except TimeoutError:
                break
            if b"emergency mode" in line:
                emergency_mode_found = True
            if emergency_mode_found and b"Press Enter" in line:
                console_proc.stdin.write(b"\n")
                await console_proc.stdin.drain()
                # shell prompt doesn't include newline, so the top loop won't
                # progress on it
                while True:
                    try:
                        line2 = await asyncio.wait_for(
                            console_proc.stdout.read(128), 5
                        )
                    except TimeoutError:
                        break
                    if b"bash" in line2 or b"root#" in line2:
                        break
                console_proc.stdin.write(b"echo $USER\n")
                await console_proc.stdin.drain()
                whoami_typed = True
            if whoami_typed and b"root" in line:
                return
        if whoami_typed:
            self.fail("Calling whoami failed, but emergency console started")
        if emergency_mode_found:
            self.fail("Emergency mode started, but didn't got shell")
        self.fail("Emergency mode not found")

    def test_111_rescue_console_initrd(self):
        if "minimal" in self.template:
            self.skipTest(
                "Test not relevant for minimal template - booting "
                "in-vm kernel not supported"
            )
        self.loop.run_until_complete(self._test_111_rescue_console_initrd())

    async def _test_111_rescue_console_initrd(self):
        self.testvm = self.app.add_new_vm(
            qubes.vm.standalonevm.StandaloneVM,
            name=self.make_vm_name("vm"),
            label="red",
        )
        self.testvm.kernel = None
        self.testvm.features.update(self.app.default_template.features)
        await self.testvm.clone_disk_files(self.app.default_template)
        self.app.save()

        await self.testvm.start()
        await self.testvm.run_for_stdio(
            "echo 'GRUB_CMDLINE_LINUX=\"$GRUB_CMDLINE_LINUX rd.emergency\"' >> "
            "/etc/default/grub",
            user="root",
        )
        await self.testvm.run_for_stdio(
            "update-grub2 || grub2-mkconfig -o /boot/grub2/grub.cfg",
            user="root",
        )
        await self.testvm.shutdown(wait=True)

        # avoid qrexec timeout
        self.testvm.features["qrexec"] = ""
        await self.testvm.start()
        # call admin.vm.Console via qrexec-client so it sets all the variables
        console_proc = await asyncio.create_subprocess_exec(
            "qrexec-client",
            "-d",
            "dom0",
            f"DEFAULT:QUBESRPC admin.vm.Console dom0 name {self.testvm.name}",
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
        )
        try:
            await asyncio.wait_for(
                self._interact_emergency_console(console_proc), 60
            )
        finally:
            with contextlib.suppress(ProcessLookupError):
                console_proc.terminate()
            await console_proc.communicate()

    @unittest.skipUnless(
        spawn.find_executable("xdotool"), "xdotool not installed"
    )
    def test_121_start_standalone_with_cdrom_vm(self):
        cdrom_vmname = self.make_vm_name("cdrom")
        self.cdrom_vm = self.app.add_new_vm(
            "AppVM", label="red", name=cdrom_vmname
        )
        self.loop.run_until_complete(self.cdrom_vm.create_on_disk())
        self.loop.run_until_complete(self.cdrom_vm.start())
        iso_path = self.create_bootable_iso()
        with open(iso_path, "rb") as iso_f:
            self.loop.run_until_complete(
                self.cdrom_vm.run_for_stdio(
                    "cat > /home/user/boot.iso", stdin=iso_f
                )
            )

        vmname = self.make_vm_name("appvm")
        self.vm = self.app.add_new_vm("StandaloneVM", label="red", name=vmname)
        self.loop.run_until_complete(self.vm.create_on_disk())
        self.vm.kernel = None
        self.vm.virt_mode = "hvm"

        # start the VM using qvm-start tool, to test --cdrom option there
        p = self.loop.run_until_complete(
            asyncio.create_subprocess_exec(
                "qvm-start",
                "--cdrom=" + cdrom_vmname + ":/home/user/boot.iso",
                self.vm.name,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
        )
        (stdout, _) = self.loop.run_until_complete(p.communicate())
        self.assertEqual(p.returncode, 0, stdout)
        # check if VM do not crash instantly
        self.loop.run_until_complete(asyncio.sleep(50))
        self.assertTrue(self.vm.is_running())
        # Type 'halt'
        subprocess.check_call(
            [
                "xdotool",
                "search",
                "--name",
                self.vm.name,
                "type",
                "--window",
                "%1",
                "halt\r",
            ]
        )
        for _ in range(10):
            if not self.vm.is_running():
                break
            self.loop.run_until_complete(asyncio.sleep(1))
        self.assertFalse(self.vm.is_running())


def create_testcases_for_templates():
    yield from qubes.tests.create_testcases_for_templates(
        "TC_06_AppVM",
        TC_06_AppVMMixin,
        qubes.tests.SystemTestCase,
        module=sys.modules[__name__],
    )

def load_tests(loader, tests, pattern):
    tests.addTests(loader.loadTestsFromNames(create_testcases_for_templates()))

    return tests


qubes.tests.maybe_create_testcases_on_import(create_testcases_for_templates)

# vim: ts=4 sw=4 et
