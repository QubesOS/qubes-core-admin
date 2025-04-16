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

    def test_020_custom_persist(self):
        self.testvm = self.app.add_new_vm(
            "AppVM",
            label="red",
            name=self.make_vm_name("vm"),
        )
        self.loop.run_until_complete(self.testvm.create_on_disk())
        self.testvm.features["service.custom-persist"] = "1"
        self.testvm.features["custom-persist.downloads"] = (
            "dir:user:user:0755:/home/user/Downloads"
        )
        self.testvm.features["custom-persist.local_lib"] = "/usr/local/lib"
        self.testvm.features["custom-persist.new_dir"] = (
            "dir:user:user:0755:/home/user/new_dir"
        )
        self.testvm.features["custom-persist.new_file"] = (
            "file:user:user:0644:/home/user/new_file"
        )
        self.app.save()

        # start first time,
        self.loop.run_until_complete(self.testvm.start())
        # do some changes
        try:
            self.loop.run_until_complete(
                self.testvm.run_for_stdio(
                    "ls -ld /home/user/Downloads &&"
                    "test $(stat -c %U /home/user/Downloads) = user &&"
                    "test $(stat -c %G /home/user/Downloads) = user &&"
                    "test $(stat -c %a /home/user/Downloads) = 755 &&"
                    "echo test1 > /home/user/Downloads/download.txt &&"
                    "ls -ld /home/user/new_dir &&"
                    "test $(stat -c %U /home/user/new_dir) = user &&"
                    "test $(stat -c %G /home/user/new_dir) = user &&"
                    "test $(stat -c %a /home/user/new_dir) = 755 &&"
                    "echo test2 > /home/user/new_dir/file_in_new_dir.txt &&"
                    "mkdir -p /home/user/Documents &&"
                    "chown user /home/user/Documents &&"
                    "echo test3 > /home/user/Documents/doc.txt &&"
                    "echo TEST4=test4 >> /home/user/.bashrc &&"
                    "test $(stat -c %U /home/user/new_file) = user &&"
                    "test $(stat -c %G /home/user/new_file) = user &&"
                    "test $(stat -c %a /home/user/new_file) = 644 &&"
                    "echo test5 > /home/user/new_file &&"
                    "mkdir -p /usr/local/bin &&"
                    "ln -s /bin/true /usr/local/bin/true-copy &&"
                    "mkdir -p /usr/local/lib/subdir &&"
                    "echo touch /etc/test5.flag >> /rw/config/rc.local",
                    user="root",
                )
            )
        except subprocess.CalledProcessError as e:
            self.fail(
                f"Calling '{e.cmd}' failed with {e.returncode}: "
                f"{e.stdout}{e.stderr}"
            )
        self.loop.run_until_complete(self.testvm.shutdown(wait=True))
        # and then start again to compare what survived
        self.loop.run_until_complete(self.testvm.start())
        try:
            self.loop.run_until_complete(
                self.testvm.run_for_stdio(
                    "grep test1 /home/user/Downloads/download.txt &&"
                    "grep test2 /home/user/new_dir/file_in_new_dir.txt &&"
                    "! ls -dl /home/user/Documents/doc.txt &&"
                    "! grep TEST4=test4 /home/user/.bashrc &&"
                    "grep test5 /home/user/new_file &&"
                    "! ls -l /usr/local/bin/true-copy &&"
                    "ls -dl /usr/local/lib/subdir &&"
                    "! ls -dl /etc/test5.flag",
                    user="root",
                )
            )
        except subprocess.CalledProcessError as e:
            self.fail(
                f"Too much / too little files persisted: {e.stdout}"
                f"{e.stderr}"
            )

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


class TC_10_RemoteVMMixin:
    def setUp(self):
        super().setUp()
        relay_name = self.make_vm_name("relay")
        self.relay_vm = self.app.add_new_vm(
            "AppVM", label="green", name=relay_name
        )
        self.loop.run_until_complete(self.relay_vm.create_on_disk())
        self.loop.run_until_complete(self.relay_vm.start())

        self.create_remote_file(
            self.relay_vm,
            "/etc/qubes-rpc/test.Relay",
            """#!/bin/sh

arg="$1"
target="${arg%%+*}"
target="${target%-remote}"
service="${arg#*+}"

exec qrexec-client-vm \\
    --source-qube="$QREXEC_REMOTE_DOMAIN-remote" -- \\
    "$target" "$service"
""",
        )

    def test_000_full_connect(self):
        """vm1 -> relay -> vm2"""
        # This system plays roles of both local and remove systems each VM is
        # duplicated - once as normal AppVM and then as RemoteVM, and the
        # relay service translates the names

        vm1_name = self.make_vm_name("vm1")
        self.vm1 = self.app.add_new_vm("AppVM", label="red", name=vm1_name)
        self.loop.run_until_complete(self.vm1.create_on_disk())
        self.vm1_remote = self.app.add_new_vm(
            "RemoteVM",
            label="red",
            name=vm1_name + "-remote",
            relayvm=self.relay_vm,
        )
        self.vm1_remote.transport_rpc = "test.Relay"

        vm2_name = self.make_vm_name("vm2")
        self.vm2 = self.app.add_new_vm("AppVM", label="red", name=vm2_name)
        self.loop.run_until_complete(self.vm2.create_on_disk())
        self.vm2_remote = self.app.add_new_vm(
            "RemoteVM",
            label="red",
            name=vm2_name + "-remote",
            relayvm=self.relay_vm,
        )
        self.vm2_remote.transport_rpc = "test.Relay"

        self.loop.run_until_complete(self.vm1.start())
        file_content = "this is test"
        self.create_remote_file(
            self.vm1, "/home/user/test-file.txt", file_content
        )

        # first policy allows the call "locally" and the second allows it
        # "remotely"
        with self.qrexec_policy(
            "qubes.Filecopy", vm1_name, vm2_name + "-remote"
        ), self.qrexec_policy("qubes.Filecopy", vm1_name + "-remote", vm2_name):
            self.loop.run_until_complete(
                self.vm1.run_for_stdio(
                    f"timeout {self.vm2.qrexec_timeout} qvm-copy-to-vm"
                    f" {vm2_name}-remote /home/user/test-file.txt"
                )
            )

        # check if that worked
        received_content, _ = self.loop.run_until_complete(
            self.vm2.run_for_stdio(
                f"cat /home/user/QubesIncoming/{vm1_name}-remote/test-file.txt"
            )
        )
        self.assertEqual(file_content, received_content.decode())


def create_testcases_for_templates():
    yield from qubes.tests.create_testcases_for_templates(
        "TC_06_AppVM",
        TC_06_AppVMMixin,
        qubes.tests.SystemTestCase,
        module=sys.modules[__name__],
    )
    yield from qubes.tests.create_testcases_for_templates(
        "TC_10_RemoteVM",
        TC_10_RemoteVMMixin,
        qubes.tests.SystemTestCase,
        module=sys.modules[__name__],
    )


def load_tests(loader, tests, pattern):
    tests.addTests(loader.loadTestsFromNames(create_testcases_for_templates()))

    return tests


qubes.tests.maybe_create_testcases_on_import(create_testcases_for_templates)

# vim: ts=4 sw=4 et
