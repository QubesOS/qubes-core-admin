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
from distutils import spawn
import os
import re
import subprocess
import time
import unittest

import qubes.tests
import qubes.qubes
from qubes.qubes import QubesVmCollection

@unittest.skipUnless(
    spawn.find_executable('xprop') and
    spawn.find_executable('xdotool') and
    spawn.find_executable('wmctrl'),
    "xprop or xdotool or wmctrl not installed")
class TC_50_MimeHandlers(qubes.tests.SystemTestsMixin):
    @classmethod
    def setUpClass(cls):
        if cls.template == 'whonix-gw' or 'minimal' in cls.template:
            raise unittest.SkipTest(
                'Template {} not supported by this test'.format(cls.template))

        if cls.template == 'whonix-ws':
            # TODO remove when Whonix-based DispVMs will work (Whonix 13?)
            raise unittest.SkipTest(
                'Template {} not supported by this test'.format(cls.template))

        qc = QubesVmCollection()

        cls._kill_test_vms(qc, prefix=qubes.tests.CLSVMPREFIX)

        qc.lock_db_for_writing()
        qc.load()

        cls._remove_test_vms(qc, qubes.qubes.vmm.libvirt_conn,
                            prefix=qubes.tests.CLSVMPREFIX)

        cls.source_vmname = cls.make_vm_name('source', True)
        source_vm = qc.add_new_vm("QubesAppVm",
                                  template=qc.get_vm_by_name(cls.template),
                                  name=cls.source_vmname)
        source_vm.create_on_disk(verbose=False)

        cls.target_vmname = cls.make_vm_name('target', True)
        target_vm = qc.add_new_vm("QubesAppVm",
                                  template=qc.get_vm_by_name(cls.template),
                                  name=cls.target_vmname)
        target_vm.create_on_disk(verbose=False)

        qc.save()
        qc.unlock_db()
        source_vm.start()
        target_vm.start()

        # make sure that DispVMs will be started of the same template
        retcode = subprocess.call(['/usr/bin/qvm-create-default-dvm',
                                   cls.template],
                                  stderr=open(os.devnull, 'w'))
        assert retcode == 0, "Error preparing DispVM"

    def setUp(self):
        super(TC_50_MimeHandlers, self).setUp()
        self.source_vm = self.qc.get_vm_by_name(self.source_vmname)
        self.target_vm = self.qc.get_vm_by_name(self.target_vmname)

    def get_window_class(self, winid, dispvm=False):
        (vm_winid, _) = subprocess.Popen(
            ['xprop', '-id', winid, '_QUBES_VMWINDOWID'],
            stdout=subprocess.PIPE
        ).communicate()
        vm_winid = vm_winid.split("#")[1].strip('\n" ')
        if dispvm:
            (vmname, _) = subprocess.Popen(
                ['xprop', '-id', winid, '_QUBES_VMNAME'],
                stdout=subprocess.PIPE
            ).communicate()
            vmname = vmname.split("=")[1].strip('\n" ')
            window_class = None
            while window_class is None:
                # XXX to use self.qc.get_vm_by_name would require reloading
                # qubes.xml, so use qvm-run instead
                xprop = subprocess.Popen(
                    ['qvm-run', '-p', vmname, 'xprop -id {} WM_CLASS'.format(
                        vm_winid)], stdout=subprocess.PIPE)
                (window_class, _) = xprop.communicate()
                if xprop.returncode != 0:
                    self.skipTest("xprop failed, not installed?")
                if 'not found' in window_class:
                    # WM_CLASS not set yet, wait a little
                    time.sleep(0.1)
                    window_class = None
        else:
            window_class = None
            while window_class is None:
                xprop = self.target_vm.run(
                    'xprop -id {} WM_CLASS'.format(vm_winid),
                    passio_popen=True)
                (window_class, _) = xprop.communicate()
                if xprop.returncode != 0:
                    self.skipTest("xprop failed, not installed?")
                if 'not found' in window_class:
                    # WM_CLASS not set yet, wait a little
                    time.sleep(0.1)
                    window_class = None
        # output: WM_CLASS(STRING) = "gnome-terminal-server", "Gnome-terminal"
        try:
            window_class = window_class.split("=")[1].split(",")[0].strip('\n" ')
        except IndexError:
            raise Exception(
                "Unexpected output from xprop: '{}'".format(window_class))

        return window_class

    def open_file_and_check_viewer(self, filename, expected_app_titles,
                                   expected_app_classes, dispvm=False):
        self.qc.unlock_db()
        if dispvm:
            p = self.source_vm.run("qvm-open-in-dvm {}".format(filename),
                                   passio_popen=True)
            vmpattern = "disp*"
        else:
            self.qrexec_policy('qubes.OpenInVM', self.source_vm.name,
                self.target_vmname)
            self.qrexec_policy('qubes.OpenURL', self.source_vm.name,
                self.target_vmname)
            p = self.source_vm.run("qvm-open-in-vm {} {}".format(
                self.target_vmname, filename), passio_popen=True)
            vmpattern = self.target_vmname
        wait_count = 0
        winid = None
        window_title = None
        while True:
            search = subprocess.Popen(['xdotool', 'search',
                                       '--onlyvisible', '--class', vmpattern],
                                      stdout=subprocess.PIPE,
                                      stderr=open(os.path.devnull, 'w'))
            retcode = search.wait()
            if retcode == 0:
                winid = search.stdout.read().strip()
                # get window title
                (window_title, _) = subprocess.Popen(
                    ['xdotool', 'getwindowname', winid], stdout=subprocess.PIPE). \
                    communicate()
                window_title = window_title.strip()
                # ignore LibreOffice splash screen and window with no title
                # set yet
                if window_title and not window_title.startswith("LibreOffice")\
                        and not window_title == 'VMapp command':
                    break
            wait_count += 1
            if wait_count > 100:
                self.fail("Timeout while waiting for editor window")
            time.sleep(0.3)

        # get window class
        window_class = self.get_window_class(winid, dispvm)
        # close the window - we've got the window class, it is no longer needed
        subprocess.check_call(['wmctrl', '-i', '-c', winid])
        p.wait()
        self.wait_for_window(window_title, show=False)

        def check_matches(obj, patterns):
            return any((pat.search(obj) if isinstance(pat, type(re.compile('')))
                        else pat in obj) for pat in patterns)

        if not check_matches(window_title, expected_app_titles) and \
                not check_matches(window_class, expected_app_classes):
            self.fail("Opening file {} resulted in window '{} ({})', which is "
                      "none of {!r} ({!r})".format(
                          filename, window_title, window_class,
                          expected_app_titles, expected_app_classes))

    def prepare_txt(self, filename):
        p = self.source_vm.run("cat > {}".format(filename), passio_popen=True)
        p.stdin.write("This is test\n")
        p.stdin.close()
        retcode = p.wait()
        assert retcode == 0, "Failed to write {} file".format(filename)

    def prepare_pdf(self, filename):
        self.prepare_txt("/tmp/source.txt")
        cmd = "convert /tmp/source.txt {}".format(filename)
        retcode = self.source_vm.run(cmd, wait=True)
        assert retcode == 0, "Failed to run '{}'".format(cmd)

    def prepare_doc(self, filename):
        self.prepare_txt("/tmp/source.txt")
        cmd = "unoconv -f doc -o {} /tmp/source.txt".format(filename)
        retcode = self.source_vm.run(cmd, wait=True)
        if retcode != 0:
            self.skipTest("Failed to run '{}', not installed?".format(cmd))

    def prepare_pptx(self, filename):
        self.prepare_txt("/tmp/source.txt")
        cmd = "unoconv -f pptx -o {} /tmp/source.txt".format(filename)
        retcode = self.source_vm.run(cmd, wait=True)
        if retcode != 0:
            self.skipTest("Failed to run '{}', not installed?".format(cmd))

    def prepare_png(self, filename):
        self.prepare_txt("/tmp/source.txt")
        cmd = "convert /tmp/source.txt {}".format(filename)
        retcode = self.source_vm.run(cmd, wait=True)
        if retcode != 0:
            self.skipTest("Failed to run '{}', not installed?".format(cmd))

    def prepare_jpg(self, filename):
        self.prepare_txt("/tmp/source.txt")
        cmd = "convert /tmp/source.txt {}".format(filename)
        retcode = self.source_vm.run(cmd, wait=True)
        if retcode != 0:
            self.skipTest("Failed to run '{}', not installed?".format(cmd))

    def test_000_txt(self):
        filename = "/home/user/test_file.txt"
        self.prepare_txt(filename)
        self.open_file_and_check_viewer(filename, ["vim", "user@"],
                                        ["gedit", "emacs", "libreoffice"])

    def test_001_pdf(self):
        filename = "/home/user/test_file.pdf"
        self.prepare_pdf(filename)
        self.open_file_and_check_viewer(filename, [],
                                        ["evince"])

    def test_002_doc(self):
        filename = "/home/user/test_file.doc"
        self.prepare_doc(filename)
        self.open_file_and_check_viewer(filename, [],
                                        ["libreoffice", "abiword"])

    def test_003_pptx(self):
        filename = "/home/user/test_file.pptx"
        self.prepare_pptx(filename)
        self.open_file_and_check_viewer(filename, [],
                                        ["libreoffice"])

    def test_004_png(self):
        filename = "/home/user/test_file.png"
        self.prepare_png(filename)
        self.open_file_and_check_viewer(filename, [],
                                        ["shotwell", "eog", "display"])

    def test_005_jpg(self):
        filename = "/home/user/test_file.jpg"
        self.prepare_jpg(filename)
        self.open_file_and_check_viewer(filename, [],
                                        ["shotwell", "eog", "display"])

    def test_006_jpeg(self):
        filename = "/home/user/test_file.jpeg"
        self.prepare_jpg(filename)
        self.open_file_and_check_viewer(filename, [],
                                        ["shotwell", "eog", "display"])

    def test_010_url(self):
        self.open_file_and_check_viewer("https://www.qubes-os.org/", [],
                                        ["Firefox", "Iceweasel", "Navigator"])

    def test_100_txt_dispvm(self):
        filename = "/home/user/test_file.txt"
        self.prepare_txt(filename)
        self.open_file_and_check_viewer(filename, ["vim", "user@"],
                                        ["gedit", "emacs", "libreoffice"],
                                        dispvm=True)

    def test_101_pdf_dispvm(self):
        filename = "/home/user/test_file.pdf"
        self.prepare_pdf(filename)
        self.open_file_and_check_viewer(filename, [],
                                        ["evince"],
                                        dispvm=True)

    def test_102_doc_dispvm(self):
        filename = "/home/user/test_file.doc"
        self.prepare_doc(filename)
        self.open_file_and_check_viewer(filename, [],
                                        ["libreoffice", "abiword"],
                                        dispvm=True)

    def test_103_pptx_dispvm(self):
        filename = "/home/user/test_file.pptx"
        self.prepare_pptx(filename)
        self.open_file_and_check_viewer(filename, [],
                                        ["libreoffice"],
                                        dispvm=True)

    def test_104_png_dispvm(self):
        filename = "/home/user/test_file.png"
        self.prepare_png(filename)
        self.open_file_and_check_viewer(filename, [],
                                        ["shotwell", "eog", "display"],
                                        dispvm=True)

    def test_105_jpg_dispvm(self):
        filename = "/home/user/test_file.jpg"
        self.prepare_jpg(filename)
        self.open_file_and_check_viewer(filename, [],
                                        ["shotwell", "eog", "display"],
                                        dispvm=True)

    def test_106_jpeg_dispvm(self):
        filename = "/home/user/test_file.jpeg"
        self.prepare_jpg(filename)
        self.open_file_and_check_viewer(filename, [],
                                        ["shotwell", "eog", "display"],
                                        dispvm=True)

    def test_110_url_dispvm(self):
        self.open_file_and_check_viewer("https://www.qubes-os.org/", [],
                                        ["Firefox", "Iceweasel", "Navigator"],
                                        dispvm=True)

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
                'TC_50_MimeHandlers_' + template,
                (TC_50_MimeHandlers, qubes.tests.QubesTestCase),
                {'template': template})))
    return tests