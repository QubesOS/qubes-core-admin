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
import contextlib
import grp
import os
import pwd
import subprocess
import tempfile
import time
import unittest
from contextlib import suppress

from distutils import spawn

import asyncio

import sys

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
        self.disp_base.template_for_dispvms = True
        self.app.default_dispvm = self.disp_base
        self.testvm = self.app.add_new_vm(qubes.vm.appvm.AppVM,
            name=self.make_vm_name('vm'),
            label='red',
        )
        self.loop.run_until_complete(self.testvm.create_on_disk())
        self.app.save()
        # used in test_01x
        self.startup_counter = 0

    def tearDown(self):
        self.app.default_dispvm = None
        super(TC_04_DispVM, self).tearDown()

    def wait_for_dispvm_destroy(self, dispvm_name):
        timeout = 20
        while dispvm_name in self.app.domains:
            self.loop.run_until_complete(asyncio.sleep(1))
            timeout -= 1
            if timeout <= 0:
                break

    def test_002_cleanup(self):
        self.loop.run_until_complete(self.testvm.start())

        try:
            (stdout, _) = self.loop.run_until_complete(
                self.testvm.run_for_stdio("qvm-run-vm --dispvm bash",
                    input=b"echo test; qubesdb-read /name; echo ERROR\n"))
        except subprocess.CalledProcessError as err:
            self.fail('qvm-run-vm failed with {} code, stderr: {}'.format(
                err.returncode, err.stderr))
        lines = stdout.decode('ascii').splitlines()
        self.assertEqual(lines[0], "test")
        dispvm_name = lines[1]
        # wait for actual DispVM destruction
        self.wait_for_dispvm_destroy(dispvm_name)
        self.assertNotIn(dispvm_name, self.app.domains)

    def test_003_cleanup_destroyed(self):
        """
        Check if DispVM is properly removed even if it terminated itself (#1660)
        :return:
        """

        self.loop.run_until_complete(self.testvm.start())

        p = self.loop.run_until_complete(
            self.testvm.run("qvm-run-vm --dispvm bash; true",
                stdin=subprocess.PIPE, stdout=subprocess.PIPE))
        p.stdin.write(b"qubesdb-read /name\n")
        p.stdin.write(b"echo ERROR\n")
        p.stdin.write(b"sudo poweroff\n")
        # do not close p.stdin on purpose - wait to automatic disconnect when
        #  domain is destroyed
        timeout = 80
        lines_task = asyncio.ensure_future(p.stdout.read())
        self.loop.run_until_complete(asyncio.wait_for(p.wait(), timeout))
        self.loop.run_until_complete(lines_task)
        lines = lines_task.result().splitlines()
        self.assertTrue(lines, 'No output received from DispVM')
        dispvm_name = lines[0]
        self.assertNotEquals(dispvm_name, b"ERROR")

        self.assertNotIn(dispvm_name, self.app.domains)

    def _count_dispvms(self, *args, **kwargs):
        self.startup_counter += 1

    def test_010_failed_start(self):
        """
        Check if DispVM doesn't (attempt to) start twice.
        :return:
        """
        self.app.add_handler('domain-add', self._count_dispvms)
        self.addCleanup(
            self.app.remove_handler, 'domain-add', self._count_dispvms)

        # make it fail to start
        self.app.default_dispvm.memory = self.app.host.memory_total * 2

        self.loop.run_until_complete(self.testvm.start())

        p = self.loop.run_until_complete(
            self.testvm.run("qvm-run-vm --dispvm true",
                stdin=subprocess.PIPE, stdout=subprocess.PIPE))
        timeout = 120
        self.loop.run_until_complete(asyncio.wait_for(p.communicate(), timeout))
        self.assertEqual(p.returncode, 126)
        self.assertEqual(self.startup_counter, 1)

    def test_011_failed_start_timeout(self):
        """
        Check if DispVM doesn't (attempt to) start twice.
        :return:
        """
        self.app.add_handler('domain-add', self._count_dispvms)
        self.addCleanup(
            self.app.remove_handler, 'domain-add', self._count_dispvms)

        # make it fail to start (timeout)
        self.app.default_dispvm.qrexec_timeout = 3

        self.loop.run_until_complete(self.testvm.start())

        p = self.loop.run_until_complete(
            self.testvm.run("qvm-run-vm --dispvm true",
                stdin=subprocess.PIPE, stdout=subprocess.PIPE))
        timeout = 120
        self.loop.run_until_complete(asyncio.wait_for(p.communicate(), timeout))
        self.assertEqual(p.returncode, 126)
        self.assertEqual(self.startup_counter, 1)


class TC_20_DispVMMixin(object):

    def setUp(self):
        super(TC_20_DispVMMixin, self).setUp()
        if 'whonix-g' in self.template:
            self.skipTest('whonix gateway is not supported as DisposableVM Template')
        self.init_default_template(self.template)
        self.disp_base = self.app.add_new_vm(qubes.vm.appvm.AppVM,
            name=self.make_vm_name('dvm'),
            label='red', template_for_dispvms=True,
        )
        self.loop.run_until_complete(self.disp_base.create_on_disk())
        self.app.default_dispvm = self.disp_base
        self.app.save()

    def tearDown(self):
        self.app.default_dispvm = None
        super(TC_20_DispVMMixin, self).tearDown()

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
            self.loop.run_until_complete(self.wait_for_session(dispvm))
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
                # close xterm on Return, but after short delay, to allow
                # xdotool to send also keyup event
                p.stdin.write("xterm -e "
                    "\"sh -c 'echo \\\"\033]0;{}\007\\\";read x;"
                              "sleep 0.1;'\"\n".
                    format(window_title).encode())
                self.loop.run_until_complete(p.stdin.drain())
                self.wait_for_window(window_title)

                time.sleep(0.5)
                self.enter_keys_in_window(window_title, ['Return'])
                # Wait for window to close
                self.wait_for_window(window_title, show=False)
                p.stdin.close()
                self.loop.run_until_complete(
                    asyncio.wait_for(p.wait(), 30))
            except:
                with suppress(ProcessLookupError):
                    p.terminate()
                self.loop.run_until_complete(p.wait())
                raise
            finally:
                del p
        finally:
            self.loop.run_until_complete(dispvm.cleanup())
            dispvm_name = dispvm.name
            del dispvm

        # give it a time for shutdown + cleanup
        self.loop.run_until_complete(asyncio.sleep(5))

        self.assertNotIn(dispvm_name, self.app.domains,
                          "DispVM not removed from qubes.xml")

    def _handle_editor(self, winid, copy=False):
        (window_title, _) = subprocess.Popen(
            ['xdotool', 'getwindowname', winid], stdout=subprocess.PIPE).\
            communicate()
        window_title = window_title.decode().strip().\
            replace('(', '\(').replace(')', '\)')
        time.sleep(1)
        if "gedit" in window_title or 'KWrite' in window_title or \
                'Mousepad' in window_title or 'Geany' in window_title or \
                'Text Editor' in window_title:
            subprocess.check_call(
                ['xdotool', 'windowactivate', '--sync', winid])
            if copy:
                subprocess.check_call(['xdotool', 'key', '--window', winid,
                                       'key', 'ctrl+a', 'ctrl+c',
                                       'ctrl+shift+c'])
            else:
                subprocess.check_call(['xdotool', 'type', 'Test test 2'])
                subprocess.check_call(['xdotool', 'key', '--window', winid,
                                       'key', 'Return'])
                time.sleep(0.5)
                subprocess.check_call(['xdotool', 'key', 'ctrl+s'])
            time.sleep(0.5)
            subprocess.check_call(['xdotool', 'key', 'ctrl+q'])
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
            subprocess.check_call(
                ['xdotool', 'windowactivate', '--sync', winid])
            if copy:
                subprocess.check_call(['xdotool', 'key', '--window', winid,
                                       'key', 'ctrl+a', 'ctrl+c',
                                       'ctrl+shift+c'])
            else:
                subprocess.check_call(['xdotool', 'type', 'Test test 2'])
                subprocess.check_call(['xdotool', 'key', '--window', winid,
                                       'key', 'Return'])
                time.sleep(0.5)
                subprocess.check_call(['xdotool',
                                       'key', '--delay', '100', 'ctrl+s',
                                       'Return'])
            time.sleep(0.5)
            subprocess.check_call(['xdotool', 'key', 'ctrl+q'])
        elif "emacs" in window_title:
            subprocess.check_call(
                ['xdotool', 'windowactivate', '--sync', winid])
            if copy:
                subprocess.check_call(['xdotool',
                                       'key', 'ctrl+x', 'h', 'alt+w',
                                       'ctrl+shift+c'])
            else:
                subprocess.check_call(['xdotool', 'type', 'Test test 2'])
                subprocess.check_call(['xdotool', 'key', '--window', winid,
                                       'key', 'Return'])
                time.sleep(0.5)
                subprocess.check_call(['xdotool',
                                       'key', 'ctrl+x', 'ctrl+s'])
            time.sleep(0.5)
            subprocess.check_call(['xdotool',
                                   'key', 'ctrl+x', 'ctrl+c'])
        elif "vim" in window_title or "user@" in window_title:
            subprocess.check_call(
                ['xdotool', 'windowactivate', '--sync', winid])
            if copy:
                raise NotImplementedError('copy not implemented for vim')
            else:
                subprocess.check_call(
                    ['xdotool', 'key', 'i', 'type', 'Test test 2'])
                subprocess.check_call(['xdotool', 'key', '--window', winid,
                                       'key', 'Return'])
                subprocess.check_call(
                    ['xdotool',
                     'key', 'Escape', 'colon', 'w', 'q', 'Return'])
        else:
            raise KeyError(window_title)

    @unittest.skipUnless(spawn.find_executable('xdotool'),
                         "xdotool not installed")
    def test_030_edit_file(self):
        self.testvm1 = self.app.add_new_vm(qubes.vm.appvm.AppVM,
                                     name=self.make_vm_name('vm1'),
                                     label='red',
                                     template=self.app.domains[self.template])
        self.loop.run_until_complete(self.testvm1.create_on_disk())
        self.app.save()

        self.loop.run_until_complete(self.testvm1.start())
        self.loop.run_until_complete(
            self.testvm1.run_for_stdio("echo test1 > /home/user/test.txt"))

        p = self.loop.run_until_complete(
            self.testvm1.run("qvm-open-in-dvm /home/user/test.txt",
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT))

        # if first 5 windows isn't expected editor, there is no hope
        winid = None
        for _ in range(5):
            try:
                winid = self.wait_for_window('disp[0-9]*', search_class=True,
                                             include_tray=False,
                                             timeout=60)
            except Exception as e:
                try:
                    self.loop.run_until_complete(asyncio.wait_for(p.wait(), 1))
                except asyncio.TimeoutError:
                    raise e
                else:
                    stdout = self.loop.run_until_complete(p.stdout.read())
                    self.fail(
                        'qvm-open-in-dvm exited prematurely with {}: {}'.format(
                            p.returncode, stdout))
            # let the application initialize
            self.loop.run_until_complete(asyncio.sleep(1))
            try:
                self._handle_editor(winid)
                break
            except KeyError:
                winid = None
        if winid is None:
            self.fail('Timeout waiting for editor window')

        self.loop.run_until_complete(p.communicate())
        (test_txt_content, _) = self.loop.run_until_complete(
            self.testvm1.run_for_stdio("cat /home/user/test.txt"))
        # Drop BOM if added by editor
        if test_txt_content.startswith(b'\xef\xbb\xbf'):
            test_txt_content = test_txt_content[3:]
        self.assertEqual(test_txt_content, b"Test test 2\ntest1\n")

    def _get_open_script(self, application):
        """Generate a script to instruct *application* to open *filename*"""
        if application == 'org.gnome.Nautilus':
            return (
                "#!/usr/bin/python3\n"
                "import sys, os"
                "from dogtail import tree, config\n"
                "config.config.actionDelay = 1.0\n"
                "config.config.defaultDelay = 1.0\n"
                "config.config.searchCutoffCount = 10\n"
                "app = tree.root.application('org.gnome.Nautilus')\n"
                "app.child(os.path.basename(sys.argv[1])).doubleClick()\n"
            ).encode()
        if application in ('mozilla-thunderbird', 'thunderbird', 'org.mozilla.thunderbird'):
            with open('/usr/share/qubes/tests-data/'
                      'dispvm-open-thunderbird-attachment', 'rb') as f:
                return f.read()
        assert False

    def _get_apps_list(self, template):
        try:
            # get first user in the qubes group
            qubes_grp = grp.getgrnam("qubes")
            qubes_user = pwd.getpwnam(qubes_grp.gr_mem[0])
        except KeyError:
            self.skipTest('Cannot find a user in the qubes group')

        desktop_list = os.listdir(os.path.join(
            qubes_user.pw_dir,
            f'.local/share/qubes-appmenus/{template}/apps.templates'))
        return [l[:-len('.desktop')] for l in desktop_list
                if l.endswith('.desktop')]

    @unittest.skipUnless(spawn.find_executable('xdotool'),
                         "xdotool not installed")
    def test_100_open_in_dispvm(self):
        self.testvm1 = self.app.add_new_vm(qubes.vm.appvm.AppVM,
                                     name=self.make_vm_name('vm1'),
                                     label='red',
                                     template=self.app.domains[self.template])
        self.loop.run_until_complete(self.testvm1.create_on_disk())
        self.app.save()

        app_id = 'mozilla-thunderbird'
        if 'debian' in self.template or 'whonix' in self.template:
            app_id = 'thunderbird'
        # F40+ has org.mozilla.thunderbird
        if 'org.mozilla.thunderbird' in self._get_apps_list(self.template):
            app_id = 'org.mozilla.thunderbird'

        self.testvm1.features['service.app-dispvm.' + app_id] = '1'
        self.loop.run_until_complete(self.testvm1.start())
        self.loop.run_until_complete(self.wait_for_session(self.testvm1))
        self.loop.run_until_complete(
            self.testvm1.run_for_stdio("echo test1 > /home/user/test.txt"))

        self.loop.run_until_complete(
            self.testvm1.run_for_stdio("cat > /home/user/open-file",
                input=self._get_open_script(app_id)))
        self.loop.run_until_complete(
            self.testvm1.run_for_stdio("chmod +x /home/user/open-file"))

        # disable donation message as it messes with editor detection
        self.loop.run_until_complete(
            self.testvm1.run_for_stdio("cat > /etc/thunderbird/pref/test.js",
                input=b'pref("app.donation.eoy.version.viewed", 100);\n',
                user="root"))

        self.loop.run_until_complete(
            self.testvm1.run_for_stdio(
                'gsettings set org.gnome.desktop.interface '
                'toolkit-accessibility true'))

        app = self.loop.run_until_complete(
            self.testvm1.run_service("qubes.StartApp+" + app_id))
        # give application a bit of time to start
        self.loop.run_until_complete(asyncio.sleep(3))

        try:
            click_to_open = self.loop.run_until_complete(
                self.testvm1.run_for_stdio('./open-file test.txt',
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT))
        except subprocess.CalledProcessError as err:
            with contextlib.suppress(asyncio.TimeoutError):
                self.loop.run_until_complete(asyncio.wait_for(app.wait(), 30))
            if app.returncode == 127:
                self.skipTest('{} not installed'.format(app_id))
            self.fail("'./open-file test.txt' failed with {}: {}{}".format(
                err.cmd, err.returncode, err.stdout, err.stderr))

        # if first 5 windows isn't expected editor, there is no hope
        winid = None
        for _ in range(5):
            winid = self.wait_for_window('disp[0-9]*', search_class=True,
                                         include_tray=False,
                                         timeout=60)
            # let the application initialize
            self.loop.run_until_complete(asyncio.sleep(1))
            try:
                # copy, not modify - attachment is set as read-only
                self._handle_editor(winid, copy=True)
                break
            except KeyError:
                winid = None
        if winid is None:
            self.fail('Timeout waiting for editor window')

        self.loop.run_until_complete(
            self.wait_for_window_hide_coro("editor", winid))

        with open('/var/run/qubes/qubes-clipboard.bin', 'rb') as f:
            test_txt_content = f.read()
        self.assertEqual(test_txt_content.strip(), b"test1")


def create_testcases_for_templates():
    return qubes.tests.create_testcases_for_templates('TC_20_DispVM',
        TC_20_DispVMMixin, qubes.tests.SystemTestCase,
        module=sys.modules[__name__])

def load_tests(loader, tests, pattern):
    tests.addTests(loader.loadTestsFromNames(
        create_testcases_for_templates()))
    return tests

qubes.tests.maybe_create_testcases_on_import(create_testcases_for_templates)
