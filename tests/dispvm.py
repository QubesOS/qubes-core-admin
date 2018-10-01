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

from distutils import spawn
import qubes.tests
import subprocess
import tempfile
import unittest
import os
import time

class TC_04_DispVM(qubes.tests.SystemTestsMixin,
                   qubes.tests.QubesTestCase):

    @staticmethod
    def get_dispvm_template_name():
        vmdir = os.readlink('/var/lib/qubes/dvmdata/vmdir')
        return os.path.basename(vmdir)

    def test_000_firewall_propagation(self):
        """
        Check firewall propagation VM->DispVM, when VM have some firewall rules
        """

        # FIXME: currently qubes.xml doesn't contain this information...
        dispvm_template_name = self.get_dispvm_template_name()
        dispvm_template = self.qc.get_vm_by_name(dispvm_template_name)

        testvm1 = self.qc.add_new_vm("QubesAppVm",
                                     name=self.make_vm_name('vm1'),
                                     template=self.qc.get_default_template())
        testvm1.create_on_disk(verbose=False)
        firewall = testvm1.get_firewall_conf()
        firewall['allowDns'] = False
        firewall['allowYumProxy'] = False
        firewall['rules'] = [{'address': '1.2.3.4',
                              'netmask': 24,
                              'proto': 'tcp',
                              'portBegin': 22,
                              'portEnd': 22,
                              }]
        testvm1.write_firewall_conf(firewall)
        self.qc.save()
        self.qc.unlock_db()

        testvm1.start()

        p = testvm1.run("qvm-run --dispvm 'qubesdb-read /name; echo ERROR;"
                        " read x'",
                        passio_popen=True)

        dispvm_name = p.stdout.readline().strip()
        self.qc.lock_db_for_reading()
        self.qc.load()
        self.qc.unlock_db()
        dispvm = self.qc.get_vm_by_name(dispvm_name)
        self.assertIsNotNone(dispvm, "DispVM {} not found in qubes.xml".format(
            dispvm_name))
        # check if firewall was propagated to the DispVM
        self.assertEquals(testvm1.get_firewall_conf(),
                          dispvm.get_firewall_conf())
        # and only there (#1608)
        self.assertNotEquals(dispvm_template.get_firewall_conf(),
                             dispvm.get_firewall_conf())
        # then modify some rule
        firewall = dispvm.get_firewall_conf()
        firewall['rules'] = [{'address': '4.3.2.1',
                              'netmask': 24,
                              'proto': 'tcp',
                              'portBegin': 22,
                              'portEnd': 22,
                              }]
        dispvm.write_firewall_conf(firewall)
        # and check again if wasn't saved anywhere else (#1608)
        self.assertNotEquals(dispvm_template.get_firewall_conf(),
                             dispvm.get_firewall_conf())
        self.assertNotEquals(testvm1.get_firewall_conf(),
                             dispvm.get_firewall_conf())
        p.stdin.write('\n')
        p.wait()

    def test_001_firewall_propagation(self):
        """
        Check firewall propagation VM->DispVM, when VM have no firewall rules
        """
        testvm1 = self.qc.add_new_vm("QubesAppVm",
                                     name=self.make_vm_name('vm1'),
                                     template=self.qc.get_default_template())
        testvm1.create_on_disk(verbose=False)
        self.qc.save()
        self.qc.unlock_db()

        # FIXME: currently qubes.xml doesn't contain this information...
        dispvm_template_name = self.get_dispvm_template_name()
        dispvm_template = self.qc.get_vm_by_name(dispvm_template_name)
        original_firewall = None
        if os.path.exists(dispvm_template.firewall_conf):
            original_firewall = tempfile.TemporaryFile()
            with open(dispvm_template.firewall_conf) as f:
                original_firewall.write(f.read())
        try:

            firewall = dispvm_template.get_firewall_conf()
            firewall['allowDns'] = False
            firewall['allowYumProxy'] = False
            firewall['rules'] = [{'address': '1.2.3.4',
                                  'netmask': 24,
                                  'proto': 'tcp',
                                  'portBegin': 22,
                                  'portEnd': 22,
                                  }]
            dispvm_template.write_firewall_conf(firewall)

            testvm1.start()

            p = testvm1.run("qvm-run --dispvm 'qubesdb-read /name; echo ERROR;"
                            " read x'",
                            passio_popen=True)

            dispvm_name = p.stdout.readline().strip()
            self.qc.lock_db_for_reading()
            self.qc.load()
            self.qc.unlock_db()
            dispvm = self.qc.get_vm_by_name(dispvm_name)
            self.assertIsNotNone(dispvm, "DispVM {} not found in qubes.xml".format(
                dispvm_name))
            # check if firewall was propagated to the DispVM from the right VM
            self.assertEquals(testvm1.get_firewall_conf(),
                              dispvm.get_firewall_conf())
            # and only there (#1608)
            self.assertNotEquals(dispvm_template.get_firewall_conf(),
                                 dispvm.get_firewall_conf())
            # then modify some rule
            firewall = dispvm.get_firewall_conf()
            firewall['rules'] = [{'address': '4.3.2.1',
                                  'netmask': 24,
                                  'proto': 'tcp',
                                  'portBegin': 22,
                                  'portEnd': 22,
                                  }]
            dispvm.write_firewall_conf(firewall)
            # and check again if wasn't saved anywhere else (#1608)
            self.assertNotEquals(dispvm_template.get_firewall_conf(),
                                 dispvm.get_firewall_conf())
            self.assertNotEquals(testvm1.get_firewall_conf(),
                                 dispvm.get_firewall_conf())
            p.stdin.write('\n')
            p.wait()
        finally:
            if original_firewall:
                original_firewall.seek(0)
                with open(dispvm_template.firewall_conf, 'w') as f:
                    f.write(original_firewall.read())
                original_firewall.close()
            else:
                os.unlink(dispvm_template.firewall_conf)

    def test_002_cleanup(self):
        self.qc.unlock_db()
        p = subprocess.Popen(['/usr/lib/qubes/qfile-daemon-dvm',
                              'qubes.VMShell', 'dom0', 'DEFAULT'],
                             stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE,
                             stderr=open(os.devnull, 'w'))
        (stdout, _) = p.communicate(input="echo test; qubesdb-read /name; "
                                          "echo ERROR\n")
        self.assertEquals(p.returncode, 0)
        lines = stdout.splitlines()
        self.assertEqual(lines[0], "test")
        dispvm_name = lines[1]
        self.qc.lock_db_for_reading()
        self.qc.load()
        self.qc.unlock_db()
        dispvm = self.qc.get_vm_by_name(dispvm_name)
        self.assertIsNone(dispvm, "DispVM {} still exists in qubes.xml".format(
            dispvm_name))

    def test_003_cleanup_destroyed(self):
        """
        Check if DispVM is properly removed even if it terminated itself (#1660)
        :return:
        """
        self.qc.unlock_db()
        p = subprocess.Popen(['/usr/lib/qubes/qfile-daemon-dvm',
                              'qubes.VMShell', 'dom0', 'DEFAULT'],
                             stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE,
                             stderr=open(os.devnull, 'w'))
        p.stdin.write("qubesdb-read /name\n")
        p.stdin.write("echo ERROR\n")
        p.stdin.write("sudo poweroff\n")
        # do not close p.stdin on purpose - wait to automatic disconnect when
        #  domain is destroyed
        timeout = 30
        while timeout > 0:
            if p.poll():
                break
            time.sleep(1)
            timeout -= 1
        # includes check for None - timeout
        self.assertEquals(p.returncode, 0)
        lines = p.stdout.read().splitlines()
        dispvm_name = lines[0]
        self.assertNotEquals(dispvm_name, "ERROR")
        self.qc.lock_db_for_reading()
        self.qc.load()
        self.qc.unlock_db()
        dispvm = self.qc.get_vm_by_name(dispvm_name)
        self.assertIsNone(dispvm, "DispVM {} still exists in qubes.xml".format(
            dispvm_name))


class TC_20_DispVMMixin(qubes.tests.SystemTestsMixin):
    def test_000_prepare_dvm(self):
        self.qc.unlock_db()
        retcode = subprocess.call(['/usr/bin/qvm-create-default-dvm',
                                   self.template],
                                  stderr=open(os.devnull, 'w'))
        self.assertEqual(retcode, 0)
        self.qc.lock_db_for_writing()
        self.qc.load()
        self.assertIsNotNone(self.qc.get_vm_by_name(
            self.template + "-dvm"))
        # TODO: check mtime of snapshot file

    def test_010_simple_dvm_run(self):
        self.qc.unlock_db()
        p = subprocess.Popen(['/usr/lib/qubes/qfile-daemon-dvm',
                              'qubes.VMShell', 'dom0', 'DEFAULT'],
                             stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE,
                             stderr=open(os.devnull, 'w'))
        (stdout, _) = p.communicate(input="echo test")
        self.assertEqual(stdout, "test\n")
        # TODO: check if DispVM is destroyed

    @unittest.skipUnless(spawn.find_executable('xdotool'),
                         "xdotool not installed")
    def test_020_gui_app(self):
        self.qc.unlock_db()
        p = subprocess.Popen(['/usr/lib/qubes/qfile-daemon-dvm',
                              'qubes.VMShell', 'dom0', 'DEFAULT'],
                             stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE,
                             stderr=open(os.devnull, 'w'))

        # wait for DispVM startup:
        p.stdin.write("echo test\n")
        p.stdin.flush()
        l = p.stdout.readline()
        self.assertEqual(l, "test\n")

        # potential race condition, but our tests are supposed to be
        # running on dedicated machine, so should not be a problem
        self.qc.lock_db_for_reading()
        self.qc.load()
        self.qc.unlock_db()

        max_qid = 0
        for vm in self.qc.values():
            if not vm.is_disposablevm():
                continue
            if vm.qid > max_qid:
                max_qid = vm.qid
        dispvm = self.qc[max_qid]
        self.assertNotEqual(dispvm.qid, 0, "DispVM not found in qubes.xml")
        self.assertTrue(dispvm.is_running())
        try:
            window_title = 'user@%s' % (dispvm.template.name + "-dvm")
            p.stdin.write("xterm -e "
                "\"sh -c 'echo \\\"\033]0;{}\007\\\";read x;'\"\n".
                format(window_title))
            self.wait_for_window(window_title)

            time.sleep(0.5)
            self.enter_keys_in_window(window_title, ['Return'])
            # Wait for window to close
            self.wait_for_window(window_title, show=False)
        finally:
            p.stdin.close()

        wait_count = 0
        while dispvm.is_running():
            wait_count += 1
            if wait_count > 100:
                self.fail("Timeout while waiting for DispVM destruction")
            time.sleep(0.1)
        wait_count = 0
        while p.poll() is None:
            wait_count += 1
            if wait_count > 100:
                self.fail("Timeout while waiting for qfile-daemon-dvm "
                          "termination")
            time.sleep(0.1)
        self.assertEqual(p.returncode, 0)

        self.qc.lock_db_for_reading()
        self.qc.load()
        self.qc.unlock_db()
        self.assertIsNone(self.qc.get_vm_by_name(dispvm.name),
                          "DispVM not removed from qubes.xml")

    def _handle_editor(self, winid):
        (window_title, _) = subprocess.Popen(
            ['xdotool', 'getwindowname', winid], stdout=subprocess.PIPE).\
            communicate()
        window_title = window_title.strip().\
            replace('(', '\(').replace(')', '\)')
        time.sleep(1)
        if "gedit" in window_title or 'KWrite' in window_title:
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
    def test_030_edit_file(self):
        testvm1 = self.qc.add_new_vm("QubesAppVm",
                                     name=self.make_vm_name('vm1'),
                                     template=self.qc.get_vm_by_name(
                                         self.template))
        testvm1.create_on_disk(verbose=False)
        self.qc.save()

        testvm1.start()
        testvm1.run("echo test1 > /home/user/test.txt", wait=True)

        self.qc.unlock_db()
        p = testvm1.run("qvm-open-in-dvm /home/user/test.txt",
                        passio_popen=True)

        wait_count = 0
        winid = None
        while True:
            search = subprocess.Popen(['xdotool', 'search',
                                       '--onlyvisible', '--class', 'disp*'],
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

        time.sleep(0.5)
        self._handle_editor(winid)
        p.wait()
        p = testvm1.run("cat /home/user/test.txt",
                        passio_popen=True)
        (test_txt_content, _) = p.communicate()
        # Drop BOM if added by editor
        if test_txt_content.startswith('\xef\xbb\xbf'):
            test_txt_content = test_txt_content[3:]
        self.assertEqual(test_txt_content, "Test test 2\ntest1\n")

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
                'TC_20_DispVM_' + template,
                (TC_20_DispVMMixin, qubes.tests.QubesTestCase),
                {'template': template})))

    return tests
