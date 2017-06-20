#!/usr/bin/python
# -*- coding: utf-8 -*-
#
# The Qubes OS Project, http://www.qubes-os.org
#
# Copyright (C) 2016 Marek Marczykowski-Górecki
#                                        <marmarek@invisiblethingslab.com>
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
#

import os
import unittest
import qubes.tests
@unittest.skipUnless(os.path.exists('/var/lib/qubes/vm-kernels/pvgrub2'),
                     'grub-xen package not installed')
class TC_40_PVGrub(qubes.tests.SystemTestsMixin):
    def setUp(self):
        super(TC_40_PVGrub, self).setUp()
        supported = False
        if self.template.startswith('fedora-'):
            supported = True
        elif self.template.startswith('debian-'):
            supported = True
        if not supported:
            self.skipTest("Template {} not supported by this test".format(
                self.template))

    def install_packages(self, vm):
        if self.template.startswith('fedora-'):
            cmd_install1 = 'dnf clean expire-cache && ' \
                'dnf install -y qubes-kernel-vm-support grub2-tools'
            cmd_install2 = 'dnf install -y kernel && ' \
                'KVER=$(rpm -q --qf %{VERSION}-%{RELEASE}.%{ARCH} kernel) && ' \
                'dnf install --allowerasing  -y kernel-devel-$KVER && ' \
                'dkms autoinstall -k $KVER'
            cmd_update_grub = 'grub2-mkconfig -o /boot/grub2/grub.cfg'
        elif self.template.startswith('debian-'):
            cmd_install1 = 'apt-get update && apt-get install -y ' \
                           'qubes-kernel-vm-support grub2-common'
            cmd_install2 = 'apt-get install -y linux-image-amd64'
            cmd_update_grub = 'mkdir /boot/grub && update-grub2'
        else:
            assert False, "Unsupported template?!"

        for cmd in [cmd_install1, cmd_install2, cmd_update_grub]:
            p = vm.run(cmd, user="root", passio_popen=True, passio_stderr=True)
            (stdout, stderr) = p.communicate()
            self.assertEquals(p.returncode, 0,
                              "Failed command: {}\nSTDOUT: {}\nSTDERR: {}"
                              .format(cmd, stdout, stderr))

    def get_kernel_version(self, vm):
        if self.template.startswith('fedora-'):
            cmd_get_kernel_version = 'rpm -q kernel|sort -n|tail -1|' \
                                     'cut -d - -f 2-'
        elif self.template.startswith('debian-'):
            cmd_get_kernel_version = \
                'dpkg-query --showformat=\'${Package}\\n\' --show ' \
                '\'linux-image-*-amd64\'|sort -n|tail -1|cut -d - -f 3-'
        else:
            raise RuntimeError("Unsupported template?!")

        p = vm.run(cmd_get_kernel_version, user="root", passio_popen=True)
        (kver, _) = p.communicate()
        self.assertEquals(p.returncode, 0,
                          "Failed command: {}".format(cmd_get_kernel_version))
        return kver.strip()

    def test_000_standalone_vm(self):
        testvm1 = self.qc.add_new_vm("QubesAppVm",
                                     template=None,
                                     name=self.make_vm_name('vm1'))
        testvm1.create_on_disk(verbose=False,
                               source_template=self.qc.get_vm_by_name(
                                   self.template))
        self.app.save()
        self.qc.unlock_db()
        testvm1 = self.qc[testvm1.qid]
        testvm1.start()
        self.install_packages(testvm1)
        kver = self.get_kernel_version(testvm1)
        self.shutdown_and_wait(testvm1)

        self.qc.lock_db_for_writing()
        self.qc.load()
        testvm1 = self.qc[testvm1.qid]
        testvm1.kernel = 'pvgrub2'
        self.app.save()
        self.qc.unlock_db()
        testvm1 = self.qc[testvm1.qid]
        testvm1.start()
        p = testvm1.run('uname -r', passio_popen=True)
        (actual_kver, _) = p.communicate()
        self.assertEquals(actual_kver.strip(), kver)

    def test_010_template_based_vm(self):
        test_template = self.qc.add_new_vm("QubesTemplateVm",
                                           template=None,
                                           name=self.make_vm_name('template'))
        test_template.clone_attrs(self.qc.get_vm_by_name(self.template))
        test_template.clone_disk_files(
            src_vm=self.qc.get_vm_by_name(self.template),
            verbose=False)

        testvm1 = self.qc.add_new_vm("QubesAppVm",
                                     template=test_template,
                                     name=self.make_vm_name('vm1'))
        testvm1.create_on_disk(verbose=False,
                               source_template=test_template)
        self.app.save()
        self.qc.unlock_db()
        test_template = self.qc[test_template.qid]
        testvm1 = self.qc[testvm1.qid]
        test_template.start()
        self.install_packages(test_template)
        kver = self.get_kernel_version(test_template)
        self.shutdown_and_wait(test_template)

        self.qc.lock_db_for_writing()
        self.qc.load()
        test_template = self.qc[test_template.qid]
        test_template.kernel = 'pvgrub2'
        testvm1 = self.qc[testvm1.qid]
        testvm1.kernel = 'pvgrub2'
        self.app.save()
        self.qc.unlock_db()

        # Check if TemplateBasedVM boots and has the right kernel
        testvm1 = self.qc[testvm1.qid]
        testvm1.start()
        p = testvm1.run('uname -r', passio_popen=True)
        (actual_kver, _) = p.communicate()
        self.assertEquals(actual_kver.strip(), kver)

        # And the same for the TemplateVM itself
        test_template = self.qc[test_template.qid]
        test_template.start()
        p = test_template.run('uname -r', passio_popen=True)
        (actual_kver, _) = p.communicate()
        self.assertEquals(actual_kver.strip(), kver)

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
                'TC_40_PVGrub_' + template,
                (TC_40_PVGrub, qubes.tests.QubesTestCase),
                {'template': template})))
    return tests
