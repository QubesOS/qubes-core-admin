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
