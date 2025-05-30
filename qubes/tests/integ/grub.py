#!/usr/bin/python
# -*- coding: utf-8 -*-
#
# The Qubes OS Project, http://www.qubes-os.org
#
# Copyright (C) 2016 Marek Marczykowski-Górecki
#                                        <marmarek@invisiblethingslab.com>
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
#

import os
import subprocess
import sys
import unittest

import qubes.tests


class GrubBase(object):
    virt_mode = None
    kernel = None
    force_dracut = False

    def setUp(self):
        super(GrubBase, self).setUp()
        supported = False
        if self.template.startswith("fedora-"):
            supported = True
        elif self.template.startswith("debian-"):
            supported = True
        elif self.template.startswith("archlinux"):
            supported = True
        if not supported:
            self.skipTest(
                "Template {} not supported by this test".format(self.template)
            )
        if "dracut" in self.id() and not self.template.startswith("debian-"):
            self.skipTest("dracut already tested in default test for Fedora")

    def install_packages(self, vm):
        if os.environ.get("QUBES_TEST_SKIP_KERNEL_INSTALL") == "1":
            return
        else:
            print(
                "Installing kernel packages, you can skip by setting "
                "QUBES_TEST_SKIP_KERNEL_INSTALL=1 in environment"
            )
        if self.template.startswith("fedora-"):
            assert (
                not self.force_dracut
            ), "Fedora uses dracut by default already"
            cmd_install1 = (
                "dnf clean expire-cache && "
                "dnf install -y qubes-kernel-vm-support grub2-tools"
            )
            cmd_install2 = "dnf install -y kernel-core"
            cmd_update_grub = "grub2-mkconfig -o /boot/grub2/grub.cfg"
        elif self.template.startswith("debian-"):
            cmd_install1 = (
                "apt-get update && apt-get install -y "
                "qubes-kernel-vm-support grub2-common"
            )
            cmd_install2 = "apt-get install -y linux-image-amd64"
            if self.force_dracut:
                cmd_install1 += " dracut"
                cmd_install2 += " && dracut -f"
            cmd_update_grub = "mkdir -p /boot/grub && update-grub2"
        elif self.template.startswith("archlinux"):
            cmd_install1 = (
                "pacman -S --noconfirm linux grub && grub-install /dev/xvda"
            )
            cmd_install2 = "pacman -S --noconfirm qubes-vm-kernel-support"
            cmd_update_grub = "grub-mkconfig -o /boot/grub/grub.cfg"
        else:
            assert False, "Unsupported template?!"

        # wait for full VM startup first, to have functional network
        self.loop.run_until_complete(self.wait_for_session(vm))

        for cmd in [cmd_install1, cmd_install2, cmd_update_grub]:
            try:
                self.loop.run_until_complete(vm.run_for_stdio(cmd, user="root"))
            except subprocess.CalledProcessError as err:
                self.fail(
                    "Failed command: {}\nSTDOUT: {}\nSTDERR: {}".format(
                        cmd, err.stdout, err.stderr
                    )
                )

    def get_kernel_version(self, vm):
        if self.template.startswith("fedora-"):
            cmd_get_kernel_version = (
                "rpm -q kernel-core|sort -V|tail -1|" "cut -d - -f 3-"
            )
        elif self.template.startswith("debian-"):
            cmd_get_kernel_version = (
                "dpkg-query --showformat='${Package}\\n' --show "
                "'linux-image-*-amd64'|sort -V|tail -1|cut -d - -f 3-"
            )
        elif self.template.startswith("archlinux"):
            cmd_get_kernel_version = (
                "pacman -Q linux|sort -V|tail -1|cut -d ' ' -f 2"
                "|sed 's/\.arch/-arch/'"
            )
        else:
            raise RuntimeError("Unsupported template?!")

        kver, _ = self.loop.run_until_complete(
            vm.run_for_stdio(cmd_get_kernel_version, user="root")
        )
        return kver.strip()

    def assertXenScrubPagesEnabled(self, vm):
        enabled, _ = self.loop.run_until_complete(
            vm.run_for_stdio(
                "cat /sys/devices/system/xen_memory/xen_memory0/scrub_pages || "
                "echo 1"
            )
        )
        enabled = enabled.decode().strip()
        self.assertEqual(
            enabled, "1", "Xen scrub pages not enabled in {}".format(vm.name)
        )

    def test_000_standalone_vm(self):
        self.testvm1 = self.app.add_new_vm(
            "StandaloneVM", name=self.make_vm_name("vm1"), label="red"
        )
        self.testvm1.virt_mode = self.virt_mode
        self.testvm1.features.update(self.app.domains[self.template].features)
        self.testvm1.clone_properties(self.app.domains[self.template])
        self.loop.run_until_complete(
            self.testvm1.clone_disk_files(self.app.domains[self.template])
        )
        self.loop.run_until_complete(self.testvm1.start())
        self.install_packages(self.testvm1)
        kver = self.get_kernel_version(self.testvm1)
        self.loop.run_until_complete(self.testvm1.shutdown(wait=True))

        self.testvm1.kernel = self.kernel
        if self.virt_mode == "hvm":
            # HVM has disabled memory-hotplug, which means VM is started with
            # full maxmem and need extra memory for page structures for full
            # maxmem
            self.testvm1.memory = 450
        self.loop.run_until_complete(self.testvm1.start())
        (actual_kver, _) = self.loop.run_until_complete(
            self.testvm1.run_for_stdio("uname -r")
        )
        self.assertEqual(actual_kver.strip(), kver)

        self.assertXenScrubPagesEnabled(self.testvm1)

    def test_010_template_based_vm(self):
        self.test_template = self.app.add_new_vm(
            "TemplateVM", name=self.make_vm_name("template"), label="red"
        )
        self.test_template.virt_mode = self.virt_mode
        self.test_template.features.update(
            self.app.domains[self.template].features
        )
        self.test_template.clone_properties(self.app.domains[self.template])
        self.loop.run_until_complete(
            self.test_template.clone_disk_files(self.app.domains[self.template])
        )

        self.testvm1 = self.app.add_new_vm(
            "AppVM",
            template=self.test_template,
            name=self.make_vm_name("vm1"),
            label="red",
        )
        self.loop.run_until_complete(self.testvm1.create_on_disk())
        self.loop.run_until_complete(self.test_template.start())
        self.install_packages(self.test_template)
        kver = self.get_kernel_version(self.test_template)
        self.loop.run_until_complete(self.test_template.shutdown(wait=True))

        self.test_template.kernel = self.kernel
        if self.virt_mode == "hvm":
            # HVM has disabled memory-hotplug, which means VM is started with
            # full maxmem and need extra memory for page structures for full
            # maxmem
            self.test_template.memory = 450

        # Check if TemplateBasedVM boots and has the right kernel
        self.loop.run_until_complete(self.testvm1.start())
        (actual_kver, _) = self.loop.run_until_complete(
            self.testvm1.run_for_stdio("uname -r")
        )
        self.assertEqual(actual_kver.strip(), kver)

        self.assertXenScrubPagesEnabled(self.testvm1)

        # And the same for the TemplateVM itself
        self.loop.run_until_complete(self.test_template.start())
        (actual_kver, _) = self.loop.run_until_complete(
            self.test_template.run_for_stdio("uname -r")
        )
        self.assertEqual(actual_kver.strip(), kver)

        self.assertXenScrubPagesEnabled(self.test_template)

    def test_001_standalone_vm_dracut(self):
        self.force_dracut = True
        self.test_000_standalone_vm()

    def test_011_template_based_vm_dracut(self):
        self.force_dracut = True
        self.test_010_template_based_vm()


@unittest.skipUnless(
    os.path.exists("/var/lib/qubes/vm-kernels/pvgrub2"),
    "grub-xen package not installed",
)
class TC_40_PVGrub(GrubBase):
    virt_mode = "pv"
    kernel = None

    def setUp(self):
        if "fedora" in self.template:
            # requires a zstd decompression filter in grub
            # (see grub_file_filter_id enum in grub sources)
            self.skipTest(
                "Fedora kernel is compressed with zstd "
                "which is not supported by pvgrub2"
            )
        if "archlinux" in self.template:
            # requires a zstd decompression filter in grub
            # (see grub_file_filter_id enum in grub sources)
            self.skipTest(
                "Archlinux kernel is compressed with zstd "
                "which is not supported by pvgrub2"
            )
        super().setUp()


class TC_41_HVMGrub(GrubBase):
    virt_mode = "hvm"
    kernel = None


@unittest.skipUnless(
    os.path.exists("/var/lib/qubes/vm-kernels/pvgrub2-pvh"),
    "grub2-xen-pvh package not installed",
)
class TC_42_PVHGrub(GrubBase):
    virt_mode = "pvh"
    kernel = None


def create_testcases_for_templates():
    yield from qubes.tests.create_testcases_for_templates(
        "TC_40_PVGrub",
        TC_40_PVGrub,
        qubes.tests.SystemTestCase,
        module=sys.modules[__name__],
    )
    yield from qubes.tests.create_testcases_for_templates(
        "TC_41_HVMGrub",
        TC_41_HVMGrub,
        qubes.tests.SystemTestCase,
        module=sys.modules[__name__],
    )
    yield from qubes.tests.create_testcases_for_templates(
        "TC_42_PVHGrub",
        TC_42_PVHGrub,
        qubes.tests.SystemTestCase,
        module=sys.modules[__name__],
    )


def load_tests(loader, tests, pattern):
    tests.addTests(loader.loadTestsFromNames(create_testcases_for_templates()))
    return tests


qubes.tests.maybe_create_testcases_on_import(create_testcases_for_templates)
