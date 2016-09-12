#!/usr/bin/python
# vim: fileencoding=utf-8
# pylint: disable=invalid-name
#
# The Qubes OS Project, https://www.qubes-os.org/
#
# Copyright (C) 2014-2015
#                   Marek Marczykowski-Górecki <marmarek@invisiblethingslab.com>
# Copyright (C) 2015  Wojtek Porczyk <woju@invisiblethingslab.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
#
from distutils import spawn

import os
import subprocess
import tempfile
import time
import unittest

import qubes
import qubes.firewall
import qubes.tests
import qubes.vm.appvm
import qubes.vm.qubesvm
import qubes.vm.standalonevm
import qubes.vm.templatevm

import libvirt  # pylint: disable=import-error


class TC_00_Basic(qubes.tests.SystemTestsMixin, qubes.tests.QubesTestCase):
    def setUp(self):
        super(TC_00_Basic, self).setUp()
        self.init_default_template()

    def test_000_qubes_create(self):
        self.assertIsInstance(self.app, qubes.Qubes)

    def test_100_qvm_create(self):
        vmname = self.make_vm_name('appvm')

        vm = self.app.add_new_vm(qubes.vm.appvm.AppVM,
            name=vmname, template=self.app.default_template,
            label='red')

        self.assertIsNotNone(vm)
        self.assertEqual(vm.name, vmname)
        self.assertEqual(vm.template, self.app.default_template)
        vm.create_on_disk()

        with self.assertNotRaises(qubes.exc.QubesException):
            vm.storage.verify()


class TC_01_Properties(qubes.tests.SystemTestsMixin, qubes.tests.QubesTestCase):
    # pylint: disable=attribute-defined-outside-init
    def setUp(self):
        super(TC_01_Properties, self).setUp()
        self.init_default_template()
        self.vmname = self.make_vm_name('appvm')
        self.vm = self.app.add_new_vm(qubes.vm.appvm.AppVM, name=self.vmname,
                                      template=self.app.default_template,
                                      label='red')
        self.vm.create_on_disk()

    def save_and_reload_db(self):
        super(TC_01_Properties, self).save_and_reload_db()
        if hasattr(self, 'vm'):
            self.vm = self.app.domains[self.vm.qid]
        if hasattr(self, 'netvm'):
            self.netvm = self.app.domains[self.netvm.qid]

    def test_000_rename(self):
        newname = self.make_vm_name('newname')

        self.assertEqual(self.vm.name, self.vmname)
        self.vm.firewall.policy = 'drop'
        self.vm.firewall.rules = [
            qubes.firewall.Rule(None, action='accept', specialtarget='dns')
        ]
        self.vm.firewall.save()
        self.vm.autostart = True
        self.addCleanup(os.system,
                        'sudo systemctl -q disable qubes-vm@{}.service || :'.
                        format(self.vmname))
        pre_rename_firewall = self.vm.firewall.rules

        with self.assertNotRaises(
                (OSError, libvirt.libvirtError, qubes.exc.QubesException)):
            self.vm.name = newname
        self.assertEqual(self.vm.name, newname)
        self.assertEqual(self.vm.dir_path,
            os.path.join(
                qubes.config.system_path['qubes_base_dir'],
                qubes.config.system_path['qubes_appvms_dir'], newname))
        self.assertTrue(os.path.exists(
            os.path.join(self.vm.dir_path, "apps", newname + "-vm.directory")))
        # FIXME: set whitelisted-appmenus.list first
        self.assertTrue(os.path.exists(os.path.join(
            self.vm.dir_path, "apps", newname + "-firefox.desktop")))
        self.assertTrue(os.path.exists(
            os.path.join(os.getenv("HOME"), ".local/share/desktop-directories",
                newname + "-vm.directory")))
        self.assertTrue(os.path.exists(
            os.path.join(os.getenv("HOME"), ".local/share/applications",
                newname + "-firefox.desktop")))
        self.assertFalse(os.path.exists(
            os.path.join(os.getenv("HOME"), ".local/share/desktop-directories",
                self.vmname + "-vm.directory")))
        self.assertFalse(os.path.exists(
            os.path.join(os.getenv("HOME"), ".local/share/applications",
                self.vmname + "-firefox.desktop")))
        self.vm.firewall.load()
        self.assertEquals(pre_rename_firewall, self.vm.firewall.rules)
        with self.assertNotRaises((qubes.exc.QubesException, OSError)):
            self.vm.firewall.save()
        self.assertTrue(self.vm.autostart)
        self.assertTrue(os.path.exists(
            '/etc/systemd/system/multi-user.target.wants/'
            'qubes-vm@{}.service'.format(newname)))
        self.assertFalse(os.path.exists(
            '/etc/systemd/system/multi-user.target.wants/'
            'qubes-vm@{}.service'.format(self.vmname)))

    def test_001_rename_libvirt_undefined(self):
        self.vm.libvirt_domain.undefine()
        self.vm._libvirt_domain = None  # pylint: disable=protected-access

        newname = self.make_vm_name('newname')
        with self.assertNotRaises(
                (OSError, libvirt.libvirtError, qubes.exc.QubesException)):
            self.vm.name = newname

    def test_030_clone(self):
        testvm1 = self.app.add_new_vm(
            qubes.vm.appvm.AppVM,
            name=self.make_vm_name("vm"),
            template=self.app.default_template,
            label='red')
        testvm1.create_on_disk()
        testvm2 = self.app.add_new_vm(testvm1.__class__,
                                     name=self.make_vm_name("clone"),
                                     template=testvm1.template,
                                     label='red')
        testvm2.clone_properties(testvm1)
        testvm2.clone_disk_files(testvm1)
        self.assertTrue(testvm1.storage.verify())
        self.assertIn('source', testvm1.volumes['root'].config)
        self.assertNotEquals(testvm2, None)
        self.assertNotEquals(testvm2.volumes, {})
        self.assertIn('source', testvm2.volumes['root'].config)

        # qubes.xml reload
        self.save_and_reload_db()
        testvm1 = self.app.domains[testvm1.qid]
        testvm2 = self.app.domains[testvm2.qid]

        self.assertEquals(testvm1.label, testvm2.label)
        self.assertEquals(testvm1.netvm, testvm2.netvm)
        self.assertEquals(testvm1.property_is_default('netvm'),
                          testvm2.property_is_default('netvm'))
        self.assertEquals(testvm1.kernel, testvm2.kernel)
        self.assertEquals(testvm1.kernelopts, testvm2.kernelopts)
        self.assertEquals(testvm1.property_is_default('kernel'),
                          testvm2.property_is_default('kernel'))
        self.assertEquals(testvm1.property_is_default('kernelopts'),
                          testvm2.property_is_default('kernelopts'))
        self.assertEquals(testvm1.memory, testvm2.memory)
        self.assertEquals(testvm1.maxmem, testvm2.maxmem)
        self.assertEquals(testvm1.devices, testvm2.devices)
        self.assertEquals(testvm1.include_in_backups,
                          testvm2.include_in_backups)
        self.assertEquals(testvm1.default_user, testvm2.default_user)
        self.assertEquals(testvm1.features, testvm2.features)
        self.assertEquals(testvm1.firewall.rules,
                          testvm2.firewall.rules)

        # now some non-default values
        testvm1.netvm = None
        testvm1.label = 'orange'
        testvm1.memory = 512
        firewall = testvm1.firewall
        firewall.policy = 'drop'
        firewall.rules = [
            qubes.firewall.Rule(None, action='accept', dsthost='1.2.3.0/24',
                proto='tcp', dstports=22)]
        firewall.save()

        testvm3 = self.app.add_new_vm(testvm1.__class__,
                                     name=self.make_vm_name("clone2"),
                                     template=testvm1.template,
                                     label='red',)
        testvm3.clone_properties(testvm1)
        testvm3.clone_disk_files(testvm1)

        # qubes.xml reload
        self.save_and_reload_db()
        testvm1 = self.app.domains[testvm1.qid]
        testvm3 = self.app.domains[testvm3.qid]

        self.assertEquals(testvm1.label, testvm3.label)
        self.assertEquals(testvm1.netvm, testvm3.netvm)
        self.assertEquals(testvm1.property_is_default('netvm'),
                          testvm3.property_is_default('netvm'))
        self.assertEquals(testvm1.kernel, testvm3.kernel)
        self.assertEquals(testvm1.kernelopts, testvm3.kernelopts)
        self.assertEquals(testvm1.property_is_default('kernel'),
                          testvm3.property_is_default('kernel'))
        self.assertEquals(testvm1.property_is_default('kernelopts'),
                          testvm3.property_is_default('kernelopts'))
        self.assertEquals(testvm1.memory, testvm3.memory)
        self.assertEquals(testvm1.maxmem, testvm3.maxmem)
        self.assertEquals(testvm1.devices, testvm3.devices)
        self.assertEquals(testvm1.include_in_backups,
                          testvm3.include_in_backups)
        self.assertEquals(testvm1.default_user, testvm3.default_user)
        self.assertEquals(testvm1.features, testvm3.features)
        self.assertEquals(testvm1.firewall.rules,
                          testvm2.firewall.rules)

    def test_020_name_conflict_app(self):
        # TODO decide what exception should be here
        with self.assertRaises((qubes.exc.QubesException, ValueError)):
            self.vm2 = self.app.add_new_vm(qubes.vm.appvm.AppVM,
                name=self.vmname, template=self.app.default_template,
                label='red')
            self.vm2.create_on_disk()

    def test_021_name_conflict_template(self):
        # TODO decide what exception should be here
        with self.assertRaises((qubes.exc.QubesException, ValueError)):
            self.vm2 = self.app.add_new_vm(qubes.vm.templatevm.TemplateVM,
                name=self.vmname, label='red')
            self.vm2.create_on_disk()

    def test_030_rename_conflict_app(self):
        vm2name = self.make_vm_name('newname')

        self.vm2 = self.app.add_new_vm(qubes.vm.appvm.AppVM,
            name=vm2name, template=self.app.default_template, label='red')
        self.vm2.create_on_disk()

        with self.assertNotRaises(OSError):
            with self.assertRaises(qubes.exc.QubesException):
                self.vm2.name = self.vmname

class TC_02_QvmPrefs(qubes.tests.SystemTestsMixin, qubes.tests.QubesTestCase):
    # pylint: disable=attribute-defined-outside-init

    def setUp(self):
        super(TC_02_QvmPrefs, self).setUp()
        self.init_default_template()
        self.sharedopts = ['--qubesxml', qubes.tests.XMLPATH]

    def setup_appvm(self):
        self.testvm = self.app.add_new_vm(
            qubes.vm.appvm.AppVM,
            name=self.make_vm_name("vm"),
            label='red')
        self.testvm.create_on_disk()
        self.save_and_reload_db()

    def setup_hvm(self):
        self.testvm = self.app.add_new_vm(
            qubes.vm.appvm.AppVM,
            name=self.make_vm_name("hvm"),
            label='red')
        self.testvm.hvm = True
        self.testvm.create_on_disk()
        self.save_and_reload_db()

    def pref_set(self, name, value, valid=True):
        p = subprocess.Popen(
            ['qvm-prefs'] + self.sharedopts +
            (['--'] if value != '-D' else []) + [self.testvm.name, name, value],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        (stdout, stderr) = p.communicate()
        if valid:
            self.assertEquals(p.returncode, 0,
                              "qvm-prefs .. '{}' '{}' failed: {}{}".format(
                                  name, value, stdout, stderr
                              ))
        else:
            self.assertNotEquals(p.returncode, 0,
                                 "qvm-prefs should reject value '{}' for "
                                 "property '{}'".format(value, name))

    def pref_get(self, name):
        p = subprocess.Popen(['qvm-prefs'] + self.sharedopts +
            ['--', self.testvm.name, name], stdout=subprocess.PIPE)
        (stdout, _) = p.communicate()
        self.assertEquals(p.returncode, 0)
        return stdout.strip()

    bool_test_values = [
        ('true', 'True', True),
        ('False', 'False', True),
        ('0', 'False', True),
        ('1', 'True', True),
        ('invalid', '', False)
    ]

    def execute_tests(self, name, values):
        """
        Helper function, which executes tests for given property.
        :param values: list of tuples (value, expected, valid),
        where 'value' is what should be set and 'expected' is what should
        qvm-prefs returns as a property value and 'valid' marks valid and
        invalid values - if it's False, qvm-prefs should reject the value
        :return: None
        """
        for (value, expected, valid) in values:
            self.pref_set(name, value, valid)
            if valid:
                self.assertEquals(self.pref_get(name), expected)

    @unittest.skip('test not converted to core3 API')
    def test_006_template(self):
        templates = [tpl for tpl in self.app.domains.values() if
            isinstance(tpl, qubes.vm.templatevm.TemplateVM)]
        if not templates:
            self.skipTest("No templates installed")
        some_template = templates[0].name
        self.setup_appvm()
        self.execute_tests('template', [
            (some_template, some_template, True),
            ('invalid', '', False),
        ])

    @unittest.skip('test not converted to core3 API')
    def test_014_pcidevs(self):
        self.setup_appvm()
        self.execute_tests('pcidevs', [
            ('[]', '[]', True),
            ('[ "00:00.0" ]', "['00:00.0']", True),
            ('invalid', '', False),
            ('[invalid]', '', False),
            # TODO:
            # ('["12:12.0"]', '', False)
        ])

    @unittest.skip('test not converted to core3 API')
    def test_024_pv_reject_hvm_props(self):
        self.setup_appvm()
        self.execute_tests('guiagent_installed', [('False', '', False)])
        self.execute_tests('qrexec_installed', [('False', '', False)])
        self.execute_tests('drive', [('/tmp/drive.img', '', False)])
        self.execute_tests('timezone', [('localtime', '', False)])

    @unittest.skip('test not converted to core3 API')
    def test_025_hvm_reject_pv_props(self):
        self.setup_hvm()
        self.execute_tests('kernel', [('default', '', False)])
        self.execute_tests('kernelopts', [('default', '', False)])

class TC_03_QvmRevertTemplateChanges(qubes.tests.SystemTestsMixin,
                                     qubes.tests.QubesTestCase):
    # pylint: disable=attribute-defined-outside-init

    def setUp(self):
        super(TC_03_QvmRevertTemplateChanges, self).setUp()
        self.init_default_template()

    def setup_pv_template(self):
        self.test_template = self.app.add_new_vm(
            qubes.vm.templatevm.TemplateVM,
            name=self.make_vm_name("pv-clone"),
            label='red'
        )
        self.test_template.clone_properties(self.app.default_template)
        self.test_template.clone_disk_files(self.app.default_template)
        self.save_and_reload_db()

    def setup_hvm_template(self):
        self.test_template = self.app.add_new_vm(
            qubes.vm.templatevm.TemplateVM,
            name=self.make_vm_name("hvm"),
            label='red',
            hvm=True
        )
        self.test_template.create_on_disk()
        self.save_and_reload_db()

    def get_rootimg_checksum(self):
        p = subprocess.Popen(
            ['sha1sum', self.test_template.volumes['root'].path],
            stdout=subprocess.PIPE)
        return p.communicate()[0]

    def _do_test(self):
        checksum_before = self.get_rootimg_checksum()
        self.test_template.start()
        self.shutdown_and_wait(self.test_template)
        checksum_changed = self.get_rootimg_checksum()
        if checksum_before == checksum_changed:
            self.log.warning("template not modified, test result will be "
                             "unreliable")
        self.assertNotEqual(self.test_template.volumes['root'].revisions, {})
        with self.assertNotRaises(subprocess.CalledProcessError):
            pool_vid = repr(self.test_template.volumes['root']).strip("'")
            revert_cmd = ['qvm-block', 'revert', pool_vid]
            subprocess.check_call(revert_cmd)

        checksum_after = self.get_rootimg_checksum()
        self.assertEquals(checksum_before, checksum_after)

    @unittest.expectedFailure
    def test_000_revert_pv(self):
        """
        Test qvm-revert-template-changes for PV template
        """
        self.setup_pv_template()
        self._do_test()

    @unittest.skip('HVM not yet implemented')
    def test_000_revert_hvm(self):
        """
        Test qvm-revert-template-changes for HVM template
        """
        # TODO: have some system there, so the root.img will get modified
        self.setup_hvm_template()
        self._do_test()

class TC_30_Gui_daemon(qubes.tests.SystemTestsMixin, qubes.tests.QubesTestCase):
    def setUp(self):
        super(TC_30_Gui_daemon, self).setUp()
        self.init_default_template()

    @unittest.skipUnless(
        spawn.find_executable('xdotool'),
                         "xdotool not installed")
    def test_000_clipboard(self):
        testvm1 = self.app.add_new_vm(qubes.vm.appvm.AppVM,
                                     name=self.make_vm_name('vm1'), label='red')
        testvm1.create_on_disk()
        testvm2 = self.app.add_new_vm(qubes.vm.appvm.AppVM,
                                     name=self.make_vm_name('vm2'), label='red')
        testvm2.create_on_disk()
        self.app.save()

        testvm1.start()
        testvm2.start()

        window_title = 'user@{}'.format(testvm1.name)
        testvm1.run('zenity --text-info --editable --title={}'.format(
            window_title))

        self.wait_for_window(window_title)
        time.sleep(0.5)
        test_string = "test{}".format(testvm1.xid)

        # Type and copy some text
        subprocess.check_call(['xdotool', 'search', '--name', window_title,
                               'windowactivate', '--sync',
                               'type', test_string])
        # second xdotool call because type --terminator do not work (SEGV)
        # additionally do not use search here, so window stack will be empty
        # and xdotool will use XTEST instead of generating events manually -
        # this will be much better - at least because events will have
        # correct timestamp (so gui-daemon would not drop the copy request)
        subprocess.check_call(['xdotool',
                               'key', 'ctrl+a', 'ctrl+c', 'ctrl+shift+c',
                               'Escape'])

        clipboard_content = \
            open('/var/run/qubes/qubes-clipboard.bin', 'r').read().strip()
        self.assertEquals(clipboard_content, test_string,
                          "Clipboard copy operation failed - content")
        clipboard_source = \
            open('/var/run/qubes/qubes-clipboard.bin.source',
                 'r').read().strip()
        self.assertEquals(clipboard_source, testvm1.name,
                          "Clipboard copy operation failed - owner")

        # Then paste it to the other window
        window_title = 'user@{}'.format(testvm2.name)
        p = testvm2.run('zenity --entry --title={} > test.txt'.format(
                        window_title), passio_popen=True)
        self.wait_for_window(window_title)

        subprocess.check_call(['xdotool', 'key', '--delay', '100',
                               'ctrl+shift+v', 'ctrl+v', 'Return'])
        p.wait()

        # And compare the result
        (test_output, _) = testvm2.run('cat test.txt',
                                       passio_popen=True).communicate()
        self.assertEquals(test_string, test_output.strip())

        clipboard_content = \
            open('/var/run/qubes/qubes-clipboard.bin', 'r').read().strip()
        self.assertEquals(clipboard_content, "",
                          "Clipboard not wiped after paste - content")
        clipboard_source = \
            open('/var/run/qubes/qubes-clipboard.bin.source', 'r').\
            read().strip()
        self.assertEquals(clipboard_source, "",
                          "Clipboard not wiped after paste - owner")

class TC_05_StandaloneVM(qubes.tests.SystemTestsMixin, qubes.tests.QubesTestCase):
    def setUp(self):
        super(TC_05_StandaloneVM, self).setUp()
        self.init_default_template()

    def test_000_create_start(self):
        testvm1 = self.app.add_new_vm(qubes.vm.standalonevm.StandaloneVM,
                                     name=self.make_vm_name('vm1'), label='red')
        testvm1.clone_disk_files(self.app.default_template)
        self.app.save()
        testvm1.start()
        self.assertEquals(testvm1.get_power_state(), "Running")

    def test_100_resize_root_img(self):
        testvm1 = self.app.add_new_vm(qubes.vm.standalonevm.StandaloneVM,
                                     name=self.make_vm_name('vm1'), label='red')
        testvm1.clone_disk_files(self.app.default_template)
        self.app.save()
        testvm1.storage.resize(testvm1.volumes['root'], 20 * 1024 ** 3)
        self.assertEquals(testvm1.volumes['root'].size, 20 * 1024 ** 3)
        testvm1.start()
        p = testvm1.run('df --output=size /|tail -n 1',
                        passio_popen=True)
        # new_size in 1k-blocks
        (new_size, _) = p.communicate()
        # some safety margin for FS metadata
        self.assertGreater(int(new_size.strip()), 19 * 1024 ** 2)



# vim: ts=4 sw=4 et
