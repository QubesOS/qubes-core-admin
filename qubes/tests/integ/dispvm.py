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

import os
import subprocess
import tempfile
import time
import unittest

from distutils import spawn

import asyncio

import qubes.tests

class TC_04_DispVM(qubes.tests.SystemTestCase):

    def setUp(self):
        super(TC_04_DispVM, self).setUp()
        self.init_default_template()
        self.disp_base = self.app.add_new_vm(qubes.vm.appvm.AppVM,
            name=self.make_vm_name('dvm'),
            label='red',
        )
        self.loop.run_until_complete(self.disp_base.create_on_disk())
        self.app.default_dispvm = self.disp_base
        self.testvm = self.app.add_new_vm(qubes.vm.appvm.AppVM,
            name=self.make_vm_name('vm'),
            label='red',
        )
        self.loop.run_until_complete(self.testvm.create_on_disk())
        self.app.save()

    @unittest.expectedFailure
    def test_002_cleanup(self):
        self.loop.run_until_complete(self.testvm.start())

        (stdout, _) = self.loop.run_until_complete(
            self.testvm.run_for_stdio("qvm-run --dispvm bash",
                input=b"echo test; qubesdb-read /name; echo ERROR\n"))
        lines = stdout.decode('ascii').splitlines()
        self.assertEqual(lines[0], "test")
        dispvm_name = lines[1]
        # wait for actual DispVM destruction
        time.sleep(1)
        self.assertNotIn(dispvm_name, self.app.domains)

    @unittest.expectedFailure
    def test_003_cleanup_destroyed(self):
        """
        Check if DispVM is properly removed even if it terminated itself (#1660)
        :return:
        """

        self.loop.run_until_complete(self.testvm.start())

        p = self.loop.run_until_complete(
            self.testvm.run("qvm-run --dispvm bash; true",
                stdin=subprocess.PIPE, stdout=subprocess.PIPE))
        p.stdin.write(b"qubesdb-read /name\n")
        p.stdin.write(b"echo ERROR\n")
        p.stdin.write(b"sudo poweroff\n")
        # do not close p.stdin on purpose - wait to automatic disconnect when
        #  domain is destroyed
        timeout = 30
        lines_task = asyncio.ensure_future(p.stdout.read())
        self.loop.run_until_complete(asyncio.wait_for(p.wait(), timeout))
        self.loop.run_until_complete(lines_task)
        lines = lines_task.result().splitlines()
        self.assertTrue(lines, 'No output received from DispVM')
        dispvm_name = lines[0]
        self.assertNotEquals(dispvm_name, b"ERROR")

        self.assertNotIn(dispvm_name, self.app.domains)

class TC_20_DispVMMixin(object):

    def setUp(self):
        super(TC_20_DispVMMixin, self).setUp()
        self.init_default_template(self.template)
        self.disp_base = self.app.add_new_vm(qubes.vm.appvm.AppVM,
            name=self.make_vm_name('dvm'),
            label='red', template_for_dispvms=True,
        )
        self.loop.run_until_complete(self.disp_base.create_on_disk())
        self.app.default_dispvm = self.disp_base
        self.app.save()

    def test_010_simple_dvm_run(self):
        dispvm = self.loop.run_until_complete(
            qubes.vm.dispvm.DispVM.from_appvm(self.disp_base))
        try:
            self.loop.run_until_complete(dispvm.start())
            (stdout, _) = self.loop.run_until_complete(
                dispvm.run_service_for_stdio('qubes.VMShell',
                    input=b"echo test"))
            self.assertEqual(stdout, b"test\n")
        finally:
            self.loop.run_until_complete(dispvm.cleanup())

    @unittest.skipUnless(spawn.find_executable('xdotool'),
                         "xdotool not installed")
    def test_020_gui_app(self):
        dispvm = self.loop.run_until_complete(
            qubes.vm.dispvm.DispVM.from_appvm(self.disp_base))
        try:
            self.loop.run_until_complete(dispvm.start())
            p = self.loop.run_until_complete(
                dispvm.run_service('qubes.VMShell',
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE))
            # wait for DispVM startup:
            p.stdin.write(b"echo test\n")
            self.loop.run_until_complete(p.stdin.drain())
            l = self.loop.run_until_complete(p.stdout.readline())
            self.assertEqual(l, b"test\n")

            self.assertTrue(dispvm.is_running())
            try:
                window_title = 'user@%s' % (dispvm.name,)
                p.stdin.write("xterm -e "
                    "\"sh -c 'echo \\\"\033]0;{}\007\\\";read x;'\"\n".
                    format(window_title).encode())
                self.wait_for_window(window_title)

                time.sleep(0.5)
                self.enter_keys_in_window(window_title, ['Return'])
                # Wait for window to close
                self.wait_for_window(window_title, show=False)
            finally:
                p.stdin.close()
        finally:
            self.loop.run_until_complete(dispvm.cleanup())

        self.assertNotIn(dispvm.name, self.app.domains,
                          "DispVM not removed from qubes.xml")

    def _handle_editor(self, winid):
        (window_title, _) = subprocess.Popen(
            ['xdotool', 'getwindowname', winid], stdout=subprocess.PIPE).\
            communicate()
        window_title = window_title.decode().strip().\
            replace('(', '\(').replace(')', '\)')
        time.sleep(1)
        if "gedit" in window_title:
            subprocess.check_call(['xdotool', 'windowactivate', '--sync', winid,
                                   'type', 'Test test 2'])
            subprocess.check_call(['xdotool', 'key', '--window', winid,
                                   'key', 'Return'])
            time.sleep(0.5)
            subprocess.check_call(['xdotool',
                                   'key', 'ctrl+s', 'ctrl+q'])
        elif "LibreOffice" in window_title:
            # wait for actual editor (we've got splash screen)
            search = subprocess.Popen(['xdotool', 'search', '--sync',
                '--onlyvisible', '--all', '--name', '--class', 'disp*|Writer'],
                stdout=subprocess.PIPE,
                                  stderr=open(os.path.devnull, 'w'))
            retcode = search.wait()
            if retcode == 0:
                winid = search.stdout.read().strip()
            time.sleep(0.5)
            subprocess.check_call(['xdotool', 'windowactivate', '--sync', winid,
                                   'type', 'Test test 2'])
            subprocess.check_call(['xdotool', 'key', '--window', winid,
                                   'key', 'Return'])
            time.sleep(0.5)
            subprocess.check_call(['xdotool',
                                   'key', '--delay', '100', 'ctrl+s',
                'Return', 'ctrl+q'])
        elif "emacs" in window_title:
            subprocess.check_call(['xdotool', 'windowactivate', '--sync', winid,
                                   'type', 'Test test 2'])
            subprocess.check_call(['xdotool', 'key', '--window', winid,
                                   'key', 'Return'])
            time.sleep(0.5)
            subprocess.check_call(['xdotool',
                                   'key', 'ctrl+x', 'ctrl+s'])
            subprocess.check_call(['xdotool',
                                   'key', 'ctrl+x', 'ctrl+c'])
        elif "vim" in window_title or "user@" in window_title:
            subprocess.check_call(['xdotool', 'windowactivate', '--sync', winid,
                                   'key', 'i', 'type', 'Test test 2'])
            subprocess.check_call(['xdotool', 'key', '--window', winid,
                                   'key', 'Return'])
            subprocess.check_call(
                ['xdotool',
                 'key', 'Escape', 'colon', 'w', 'q', 'Return'])
        else:
            self.fail("Unknown editor window: {}".format(window_title))

    @unittest.skipUnless(spawn.find_executable('xdotool'),
                         "xdotool not installed")
    @unittest.expectedFailure
    def test_030_edit_file(self):
        testvm1 = self.app.add_new_vm(qubes.vm.appvm.AppVM,
                                     name=self.make_vm_name('vm1'),
                                     label='red',
                                     template=self.app.domains[self.template])
        self.loop.run_until_complete(testvm1.create_on_disk())
        self.app.save()

        self.loop.run_until_complete(testvm1.start())
        self.loop.run_until_complete(
            testvm1.run_for_stdio("echo test1 > /home/user/test.txt"))

        p = self.loop.run_until_complete(
            testvm1.run("qvm-open-in-dvm /home/user/test.txt"))

        wait_count = 0
        winid = None
        while True:
            search = self.loop.run_until_complete(
                asyncio.create_subprocess_exec(
                    'xdotool', 'search', '--onlyvisible', '--class', 'disp*',
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL))
            stdout, _ = self.loop.run_until_complete(search.communicate())
            if p.returncode == 0:
                winid = stdout.strip()
                # get window title
                (window_title, _) = subprocess.Popen(
                    ['xdotool', 'getwindowname', winid], stdout=subprocess.PIPE). \
                    communicate()
                window_title = window_title.decode().strip()
                # ignore LibreOffice splash screen and window with no title
                # set yet
                if window_title and not window_title.startswith("LibreOffice")\
                        and not window_title == 'VMapp command':
                    break
            wait_count += 1
            if wait_count > 100:
                self.fail("Timeout while waiting for editor window")
            self.loop.run_until_complete(asyncio.sleep(0.3))

        time.sleep(0.5)
        self._handle_editor(winid)
        self.loop.run_until_complete(p.wait())
        (test_txt_content, _) = self.loop.run_until_complete(
            testvm1.run_for_stdio("cat /home/user/test.txt"))
        # Drop BOM if added by editor
        if test_txt_content.startswith(b'\xef\xbb\xbf'):
            test_txt_content = test_txt_content[3:]
        self.assertEqual(test_txt_content, b"Test test 2\ntest1\n")

def load_tests(loader, tests, pattern):
    for template in qubes.tests.list_templates():
        tests.addTests(loader.loadTestsFromTestCase(
            type(
                'TC_20_DispVM_' + template,
                (TC_20_DispVMMixin, qubes.tests.SystemTestCase),
                {'template': template})))

    return tests
