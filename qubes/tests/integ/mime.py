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
from distutils import spawn
import re
import subprocess
import time
import unittest

import itertools

import asyncio

import sys

import qubes.tests
import qubes

@unittest.skipUnless(
    spawn.find_executable('xprop') and
    spawn.find_executable('xdotool') and
    spawn.find_executable('wmctrl'),
    "xprop or xdotool or wmctrl not installed")
class TC_50_MimeHandlers:
    def setUp(self):
        super(TC_50_MimeHandlers, self).setUp()
        if self.template.startswith('whonix-gw') or 'minimal' in self.template:
            raise unittest.SkipTest(
                'Template {} not supported by this test'.format(self.template))

        self.source_vmname = self.make_vm_name('source')
        self.source_vm = self.app.add_new_vm("AppVM",
            template=self.template,
            name=self.source_vmname,
            label='red')
        self.loop.run_until_complete(self.source_vm.create_on_disk())

        self.target_vmname = self.make_vm_name('target')
        self.target_vm = self.app.add_new_vm("AppVM",
            template=self.template,
            name=self.target_vmname,
            label='red')
        self.loop.run_until_complete(self.target_vm.create_on_disk())

        self.target_vm.template_for_dispvms = True
        self.source_vm.default_dispvm = self.target_vm

        self.loop.run_until_complete(asyncio.gather(
            self.source_vm.start(),
            self.target_vm.start()))


    def get_window_class(self, winid, dispvm=False):
        (vm_winid, _) = subprocess.Popen(
            ['xprop', '-id', winid, '_QUBES_VMWINDOWID'],
            stdout=subprocess.PIPE
        ).communicate()
        vm_winid = vm_winid.decode().split("#")[1].strip('\n" ')
        if dispvm:
            (vmname, _) = subprocess.Popen(
                ['xprop', '-id', winid, '_QUBES_VMNAME'],
                stdout=subprocess.PIPE
            ).communicate()
            vmname = vmname.decode().split("=")[1].strip('\n" ')
            vm = self.app.domains[vmname]
        else:
            vm = self.target_vm
        window_class = None
        while window_class is None:
            try:
                window_class, _ = self.loop.run_until_complete(
                    vm.run_for_stdio('xprop -id {} WM_CLASS'.format(vm_winid)))
            except subprocess.CalledProcessError as e:
                if e.returncode == 127:
                    self.skipTest('xprop not installed')
                self.fail(
                    "xprop -id {} WM_CLASS failed: {}".format(
                        vm_winid, e.stderr.decode()))
            if b'not found' in window_class:
                # WM_CLASS not set yet, wait a little
                time.sleep(0.1)
                window_class = None

        # output: WM_CLASS(STRING) = "gnome-terminal-server", "Gnome-terminal"
        try:
            window_class = window_class.decode()
            window_class = window_class.split("=")[1].split(",")[0].strip('\n" ')
        except IndexError:
            raise Exception(
                "Unexpected output from xprop: '{}'".format(window_class))

        return window_class

    def open_file_and_check_viewer(self, filename, expected_app_titles,
                                   expected_app_classes, dispvm=False):
        if dispvm:
            p = self.loop.run_until_complete(self.source_vm.run(
                "qvm-open-in-dvm {}".format(filename), stdout=subprocess.PIPE))
            vmpattern = "disp[0-9]*"
        else:
            p = self.loop.run_until_complete(self.source_vm.run(
                "qvm-open-in-vm {} {}".format(self.target_vmname, filename),
                stdout=subprocess.PIPE))
            vmpattern = self.target_vmname
        wait_count = 0
        winid = None
        with self.qrexec_policy('qubes.OpenInVM', self.source_vm.name,
                self.target_vmname):
            with self.qrexec_policy('qubes.OpenURL', self.source_vm.name,
                    self.target_vmname):
                while True:
                    search = subprocess.Popen(['xdotool', 'search',
                                               '--onlyvisible', '--class', vmpattern],
                                              stdout=subprocess.PIPE,
                                              stderr=subprocess.DEVNULL)
                    retcode = search.wait()
                    if retcode == 0:
                        winid = search.stdout.read().strip()
                        # get window title
                        (window_title, _) = subprocess.Popen(
                            ['xdotool', 'getwindowname', winid], stdout=subprocess.PIPE). \
                            communicate()
                        window_title = window_title.decode('utf8').strip()
                        # ignore LibreOffice splash screen and window with no title
                        # set yet
                        if window_title and \
                                not window_title.startswith("LibreOffice") and\
                                not window_title.startswith("NetworkManager") and\
                                not window_title == 'VMapp command':
                            break
                    wait_count += 1
                    if wait_count > 100:
                        self.fail("Timeout while waiting for editor window")
                    self.loop.run_until_complete(asyncio.sleep(0.3))

        # get window class
        window_class = self.get_window_class(winid, dispvm)
        # close the window - we've got the window class, it is no longer needed
        subprocess.check_call(['wmctrl', '-i', '-c', winid])
        # confirm quit for example for Firefox
        self.loop.run_until_complete(asyncio.sleep(1))
        subprocess.call(['xdotool', 'search', '--onlyvisible', '--name',
            'Quit', 'windowfocus', 'key', 'Return'])
        try:
            self.loop.run_until_complete(asyncio.wait_for(p.wait(), 30))
        except asyncio.TimeoutError:
            self.fail('qvm-open-in-vm did not exited')
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
        self.loop.run_until_complete(
            self.source_vm.run_for_stdio("cat > {}".format(filename),
            input=b'This is test\n'))

    def prepare_pdf(self, filename):
        self.prepare_txt("/tmp/source.txt")
        cmd = "convert text:/tmp/source.txt {}".format(filename)
        try:
            self.loop.run_until_complete(
                self.source_vm.run_for_stdio(cmd))
        except subprocess.CalledProcessError as e:
            self.fail('{} failed: {}'.format(cmd, e.stderr.decode()))

    def prepare_doc(self, filename):
        self.prepare_txt("/tmp/source.txt")
        cmd = "unoconv -f doc -o {} /tmp/source.txt".format(filename)
        try:
            self.loop.run_until_complete(
                self.source_vm.run_for_stdio(cmd))
        except subprocess.CalledProcessError as e:
            if e.returncode == 127:
                self.skipTest("unoconv not installed".format(cmd))
            self.skipTest("Failed to run '{}': {}".format(cmd,
                e.stderr.decode()))

    def prepare_pptx(self, filename):
        self.prepare_txt("/tmp/source.txt")
        cmd = "unoconv -f pptx -o {} /tmp/source.txt".format(filename)
        try:
            self.loop.run_until_complete(
                self.source_vm.run_for_stdio(cmd))
        except subprocess.CalledProcessError as e:
            if e.returncode == 127:
                self.skipTest("unoconv not installed".format(cmd))
            self.skipTest("Failed to run '{}': {}".format(cmd,
                e.stderr.decode()))

    def prepare_png(self, filename):
        self.prepare_txt("/tmp/source.txt")
        cmd = "convert text:/tmp/source.txt {}".format(filename)
        try:
            self.loop.run_until_complete(
                self.source_vm.run_for_stdio(cmd))
        except subprocess.CalledProcessError as e:
            if e.returncode == 127:
                self.skipTest("convert not installed".format(cmd))
            self.skipTest("Failed to run '{}': {}".format(cmd,
                e.stderr.decode()))

    def prepare_jpg(self, filename):
        self.prepare_txt("/tmp/source.txt")
        cmd = "convert text:/tmp/source.txt {}".format(filename)
        try:
            self.loop.run_until_complete(
                self.source_vm.run_for_stdio(cmd))
        except subprocess.CalledProcessError as e:
            if e.returncode == 127:
                self.skipTest("convert not installed".format(cmd))
            self.skipTest("Failed to run '{}': {}".format(cmd,
                e.stderr.decode()))

    def test_000_txt(self):
        filename = "/home/user/test_file.txt"
        self.prepare_txt(filename)
        self.open_file_and_check_viewer(
            filename, ["vim", "user@"],
            ["gedit", "emacs", "libreoffice", "gnome-text-editor"])

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
        self.open_file_and_check_viewer(
            filename, ["vim", "user@"],
            ["gedit", "emacs", "libreoffice", "gnome-text-editor"],
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

def create_testcases_for_templates():
    return qubes.tests.create_testcases_for_templates('TC_50_MimeHandlers',
        TC_50_MimeHandlers, qubes.tests.SystemTestCase,
        module=sys.modules[__name__])

def load_tests(loader, tests, pattern):
    tests.addTests(loader.loadTestsFromNames(
        create_testcases_for_templates()))
    return tests

qubes.tests.maybe_create_testcases_on_import(create_testcases_for_templates)
