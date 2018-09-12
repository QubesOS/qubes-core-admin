# pylint: disable=invalid-name

#
# The Qubes OS Project, https://www.qubes-os.org/
#
# Copyright (C) 2014-2015
#                   Marek Marczykowski-Górecki <marmarek@invisiblethingslab.com>
# Copyright (C) 2015  Wojtek Porczyk <woju@invisiblethingslab.com>
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

from distutils import spawn

import asyncio
import os
import subprocess
import tempfile
import time
import unittest

import collections

import pkg_resources
import shutil

import sys

import qubes
import qubes.firewall
import qubes.tests
import qubes.storage
import qubes.vm.appvm
import qubes.vm.qubesvm
import qubes.vm.standalonevm
import qubes.vm.templatevm

import libvirt  # pylint: disable=import-error


class TC_00_Basic(qubes.tests.SystemTestCase):
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
        self.loop.run_until_complete(vm.create_on_disk())

        with self.assertNotRaises(qubes.exc.QubesException):
            self.loop.run_until_complete(vm.storage.verify())

    def test_040_qdb_watch(self):
        flag = set()

        def handler(vm, event, path):
            if path == '/test-watch-path':
                flag.add(True)

        vm = self.app.domains[0]
        vm.watch_qdb_path('/test-watch-path')
        vm.add_handler('domain-qdb-change:/test-watch-path', handler)
        self.assertFalse(flag)
        vm.untrusted_qdb.write('/test-watch-path', 'test-value')
        self.loop.run_until_complete(asyncio.sleep(0.1))
        self.assertTrue(flag)

    @unittest.skipUnless(
        spawn.find_executable('xdotool'), "xdotool not installed")
    def test_120_start_standalone_with_cdrom_dom0(self):
        vmname = self.make_vm_name('appvm')
        self.vm = self.app.add_new_vm('StandaloneVM', label='red', name=vmname)
        self.loop.run_until_complete(self.vm.create_on_disk())
        self.vm.kernel = None
        self.vm.virt_mode = 'hvm'

        iso_path = self.create_bootable_iso()
        # start the VM using qvm-start tool, to test --cdrom option there
        p = self.loop.run_until_complete(asyncio.create_subprocess_exec(
            'qvm-start', '--cdrom=dom0:' + iso_path, self.vm.name,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT))
        (stdout, _) = self.loop.run_until_complete(p.communicate())
        self.assertEqual(p.returncode, 0, stdout)
        # check if VM do not crash instantly
        self.loop.run_until_complete(asyncio.sleep(5))
        self.assertTrue(self.vm.is_running())
        # Type 'poweroff'
        subprocess.check_call(['xdotool', 'search', '--name', self.vm.name,
                               'type', 'poweroff\r'])
        self.loop.run_until_complete(asyncio.sleep(1))
        self.assertFalse(self.vm.is_running())

    def _test_200_on_domain_start(self, vm, event, **_kwargs):
        '''Simulate domain crash just after startup'''
        vm.libvirt_domain.destroy()

    def test_200_shutdown_event_race(self):
        '''Regression test for 3164'''
        vmname = self.make_vm_name('appvm')

        self.vm = self.app.add_new_vm(qubes.vm.appvm.AppVM,
            name=vmname, template=self.app.default_template,
            label='red')
        # help the luck a little - don't wait for qrexec to easier win the race
        self.vm.features['qrexec'] = False
        self.loop.run_until_complete(self.vm.create_on_disk())
        # another way to help the luck a little - make sure the private
        # volume is first in (normally unordered) dict - this way if any
        # volume action fails, it will be at or after private volume - not
        # before (preventing private volume action)
        old_volumes = self.vm.volumes
        self.vm.volumes = collections.OrderedDict()
        self.vm.volumes['private'] = old_volumes.pop('private')
        self.vm.volumes.update(old_volumes.items())
        del old_volumes

        self.loop.run_until_complete(self.vm.start())

        # kill it the way it does not give a chance for domain-shutdown it
        # execute
        self.vm.libvirt_domain.destroy()

        # now, lets try to start the VM again, before domain-shutdown event
        # got handled (#3164), and immediately trigger second domain-shutdown
        self.vm.add_handler('domain-start', self._test_200_on_domain_start)
        self.loop.run_until_complete(self.vm.start())

        # and give a chance for both domain-shutdown handlers to execute
        self.loop.run_until_complete(asyncio.sleep(1))
        with self.assertNotRaises(qubes.exc.QubesException):
            # if the above caused two domain-shutdown handlers being called
            # one after another, private volume is gone
            self.loop.run_until_complete(self.vm.storage.verify())

    def _test_201_on_domain_pre_start(self, vm, event, **_kwargs):
        '''Simulate domain crash just after startup'''
        if not self.domain_shutdown_handled and not self.test_failure_reason:
            self.test_failure_reason = \
                'domain-shutdown event was not dispatched before subsequent ' \
                'start'
        self.domain_shutdown_handled = False

    def _test_201_domain_shutdown_handler(self, vm, event, **kwargs):
        if self.domain_shutdown_handled and not self.test_failure_reason:
            self.test_failure_reason = 'domain-shutdown event received twice'
        self.domain_shutdown_handled = True

    def test_201_shutdown_event_race(self):
        '''Regression test for 3164 - pure events edition'''
        vmname = self.make_vm_name('appvm')

        self.vm = self.app.add_new_vm(qubes.vm.appvm.AppVM,
            name=vmname, template=self.app.default_template,
            label='red')
        # help the luck a little - don't wait for qrexec to easier win the race
        self.vm.features['qrexec'] = False
        self.loop.run_until_complete(self.vm.create_on_disk())

        # do not throw exception from inside event handler - test framework
        # will not recover from it (various objects leaks)
        self.test_failure_reason = None
        self.domain_shutdown_handled = False
        self.vm.add_handler('domain-shutdown',
            self._test_201_domain_shutdown_handler)

        self.loop.run_until_complete(self.vm.start())

        if self.test_failure_reason:
            self.fail(self.test_failure_reason)

        self.vm.add_handler('domain-pre-start',
            self._test_201_on_domain_pre_start)

        # kill it the way it does not give a chance for domain-shutdown it
        # execute
        self.vm.libvirt_domain.destroy()

        # now, lets try to start the VM again, before domain-shutdown event
        # got handled (#3164), and immediately trigger second domain-shutdown
        self.vm.add_handler('domain-start', self._test_200_on_domain_start)
        self.loop.run_until_complete(self.vm.start())

        if self.test_failure_reason:
            self.fail(self.test_failure_reason)

        # and give a chance for both domain-shutdown handlers to execute
        self.loop.run_until_complete(asyncio.sleep(1))

        if self.test_failure_reason:
            self.fail(self.test_failure_reason)

        self.assertTrue(self.domain_shutdown_handled,
            'second domain-shutdown event was not dispatched after domain '
            'shutdown')

    def _check_udev_for_uuid(self, uuid_value):
        udev_data_path = '/run/udev/data'
        for udev_item in os.listdir(udev_data_path):
            # check only block devices
            if not udev_item.startswith('b'):
                continue
            with open(os.path.join(udev_data_path, udev_item)) as udev_file:
                self.assertNotIn(uuid_value, udev_file.read(),
                    'udev parsed filesystem UUID! ' + udev_item)

    def assertVolumesExcludedFromUdev(self, vm):
        try:
            # first boot, mkfs private volume
            self.loop.run_until_complete(vm.start())
            # get private volume UUID
            private_uuid, _ = self.loop.run_until_complete(
                vm.run_for_stdio('blkid -o value /dev/xvdb', user='root'))
            private_uuid = private_uuid.decode().splitlines()[0]

            # now check if dom0 udev know about it - it shouldn't
            self._check_udev_for_uuid(private_uuid)

            # now restart the VM and check again
            self.loop.run_until_complete(vm.shutdown(wait=True))
            self.loop.run_until_complete(vm.start())

            self._check_udev_for_uuid(private_uuid)
        finally:
            del vm

    def test_202_udev_block_exclude_default(self):
        '''Check if VM images are excluded from udev parsing -
        default volume pool'''
        vmname = self.make_vm_name('appvm')

        self.vm = self.app.add_new_vm(qubes.vm.appvm.AppVM,
            name=vmname, template=self.app.default_template,
            label='red')
        self.loop.run_until_complete(self.vm.create_on_disk())
        self.assertVolumesExcludedFromUdev(self.vm)

    def test_203_udev_block_exclude_varlibqubes(self):
        '''Check if VM images are excluded from udev parsing -
        varlibqubes pool'''
        vmname = self.make_vm_name('appvm')

        self.vm = self.app.add_new_vm(qubes.vm.appvm.AppVM,
            name=vmname, template=self.app.default_template,
            label='red')
        self.loop.run_until_complete(self.vm.create_on_disk(
            pool=self.app.pools['varlibqubes']))
        self.assertVolumesExcludedFromUdev(self.vm)

    def test_204_udev_block_exclude_custom_file(self):
        '''Check if VM images are excluded from udev parsing -
        custom file pool'''
        vmname = self.make_vm_name('appvm')

        pool_path = tempfile.mkdtemp(
            prefix='qubes-pool-', dir='/var/tmp')
        self.addCleanup(shutil.rmtree, pool_path)
        pool = self.app.add_pool('test-filep', dir_path=pool_path,
            driver='file')

        self.vm = self.app.add_new_vm(qubes.vm.appvm.AppVM,
            name=vmname, template=self.app.default_template,
            label='red')
        self.loop.run_until_complete(self.vm.create_on_disk(
            pool=pool))
        self.assertVolumesExcludedFromUdev(self.vm)


class TC_01_Properties(qubes.tests.SystemTestCase):
    # pylint: disable=attribute-defined-outside-init
    def setUp(self):
        super(TC_01_Properties, self).setUp()
        self.init_default_template()
        self.vmname = self.make_vm_name('appvm')
        self.vm = self.app.add_new_vm(qubes.vm.appvm.AppVM, name=self.vmname,
                                      template=self.app.default_template,
                                      label='red')
        self.loop.run_until_complete(self.vm.create_on_disk())
        self.addCleanup(self.cleanup_props)

    def cleanup_props(self):
        del self.vm

    def test_030_clone(self):
        try:
            testvm1 = self.app.add_new_vm(
                qubes.vm.appvm.AppVM,
                name=self.make_vm_name("vm"),
                template=self.app.default_template,
                label='red')
            self.loop.run_until_complete(testvm1.create_on_disk())
            testvm2 = self.app.add_new_vm(testvm1.__class__,
                                        name=self.make_vm_name("clone"),
                                        template=testvm1.template,
                                        label='red')
            testvm2.clone_properties(testvm1)
            testvm2.firewall.clone(testvm1.firewall)
            self.loop.run_until_complete(testvm2.clone_disk_files(testvm1))
            self.assertTrue(self.loop.run_until_complete(testvm1.storage.verify()))
            self.assertIn('source', testvm1.volumes['root'].config)
            self.assertNotEquals(testvm2, None)
            self.assertNotEquals(testvm2.volumes, {})
            self.assertIn('source', testvm2.volumes['root'].config)

            # qubes.xml reload
            self.app.save()
            testvm1 = self.app.domains[testvm1.qid]
            testvm2 = self.app.domains[testvm2.qid]

            self.assertEqual(testvm1.label, testvm2.label)
            self.assertEqual(testvm1.netvm, testvm2.netvm)
            self.assertEqual(testvm1.property_is_default('netvm'),
                            testvm2.property_is_default('netvm'))
            self.assertEqual(testvm1.kernel, testvm2.kernel)
            self.assertEqual(testvm1.kernelopts, testvm2.kernelopts)
            self.assertEqual(testvm1.property_is_default('kernel'),
                            testvm2.property_is_default('kernel'))
            self.assertEqual(testvm1.property_is_default('kernelopts'),
                            testvm2.property_is_default('kernelopts'))
            self.assertEqual(testvm1.memory, testvm2.memory)
            self.assertEqual(testvm1.maxmem, testvm2.maxmem)
            self.assertEqual(testvm1.devices, testvm2.devices)
            self.assertEqual(testvm1.include_in_backups,
                            testvm2.include_in_backups)
            self.assertEqual(testvm1.default_user, testvm2.default_user)
            self.assertEqual(testvm1.features, testvm2.features)
            self.assertEqual(testvm1.firewall.rules,
                            testvm2.firewall.rules)

            # now some non-default values
            testvm1.netvm = None
            testvm1.label = 'orange'
            testvm1.memory = 512
            firewall = testvm1.firewall
            firewall.rules = [
                qubes.firewall.Rule(None, action='accept', dsthost='1.2.3.0/24',
                    proto='tcp', dstports=22)]
            firewall.save()

            testvm3 = self.app.add_new_vm(testvm1.__class__,
                                        name=self.make_vm_name("clone2"),
                                        template=testvm1.template,
                                        label='red',)
            testvm3.clone_properties(testvm1)
            testvm3.firewall.clone(testvm1.firewall)
            self.loop.run_until_complete(testvm3.clone_disk_files(testvm1))

            # qubes.xml reload
            self.app.save()
            testvm1 = self.app.domains[testvm1.qid]
            testvm3 = self.app.domains[testvm3.qid]

            self.assertEqual(testvm1.label, testvm3.label)
            self.assertEqual(testvm1.netvm, testvm3.netvm)
            self.assertEqual(testvm1.property_is_default('netvm'),
                            testvm3.property_is_default('netvm'))
            self.assertEqual(testvm1.kernel, testvm3.kernel)
            self.assertEqual(testvm1.kernelopts, testvm3.kernelopts)
            self.assertEqual(testvm1.property_is_default('kernel'),
                            testvm3.property_is_default('kernel'))
            self.assertEqual(testvm1.property_is_default('kernelopts'),
                            testvm3.property_is_default('kernelopts'))
            self.assertEqual(testvm1.memory, testvm3.memory)
            self.assertEqual(testvm1.maxmem, testvm3.maxmem)
            self.assertEqual(testvm1.devices, testvm3.devices)
            self.assertEqual(testvm1.include_in_backups,
                            testvm3.include_in_backups)
            self.assertEqual(testvm1.default_user, testvm3.default_user)
            self.assertEqual(testvm1.features, testvm3.features)
            self.assertEqual(testvm1.firewall.rules,
                            testvm3.firewall.rules)
        finally:
            try:
                del firewall
            except NameError:
                pass
            try:
                del testvm1
            except NameError:
                pass
            try:
                del testvm2
            except NameError:
                pass
            try:
                del testvm3
            except NameError:
                pass

    def test_020_name_conflict_app(self):
        # TODO decide what exception should be here
        with self.assertRaises((qubes.exc.QubesException, ValueError)):
            self.vm2 = self.app.add_new_vm(qubes.vm.appvm.AppVM,
                name=self.vmname, template=self.app.default_template,
                label='red')
            self.loop.run_until_complete(self.vm2.create_on_disk())

    def test_021_name_conflict_template(self):
        # TODO decide what exception should be here
        with self.assertRaises((qubes.exc.QubesException, ValueError)):
            self.vm2 = self.app.add_new_vm(qubes.vm.templatevm.TemplateVM,
                name=self.vmname, label='red')
            self.loop.run_until_complete(self.vm2.create_on_disk())


class TC_02_QvmPrefs(qubes.tests.SystemTestCase):
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
        self.loop.run_until_complete(self.testvm.create_on_disk())
        self.app.save()

    def setup_hvm(self):
        self.testvm = self.app.add_new_vm(
            qubes.vm.appvm.AppVM,
            name=self.make_vm_name("hvm"),
            label='red')
        self.testvm.virt_mode = 'hvm'
        self.loop.run_until_complete(self.testvm.create_on_disk())
        self.app.save()

    def pref_set(self, name, value, valid=True):
        self.loop.run_until_complete(self._pref_set(name, value, valid))

    @asyncio.coroutine
    def _pref_set(self, name, value, valid=True):
        cmd = ['qvm-prefs']
        if value != '-D':
            cmd.append('--')
        cmd.extend((self.testvm.name, name, value))
        p = yield from asyncio.create_subprocess_exec(*cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE)
        (stdout, stderr) = yield from p.communicate()
        if valid:
            self.assertEqual(p.returncode, 0,
                              "qvm-prefs .. '{}' '{}' failed: {}{}".format(
                                  name, value, stdout, stderr
                              ))
        else:
            self.assertNotEquals(p.returncode, 0,
                                 "qvm-prefs should reject value '{}' for "
                                 "property '{}'".format(value, name))

    def pref_get(self, name):
        self.loop.run_until_complete(self._pref_get(name))

    @asyncio.coroutine
    def _pref_get(self, name):
        p = yield from asyncio.create_subprocess_exec(
            'qvm-prefs', *self.sharedopts, '--', self.testvm.name, name,
            stdout=subprocess.PIPE)
        (stdout, _) = yield from p.communicate()
        self.assertEqual(p.returncode, 0)
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
                self.assertEqual(self.pref_get(name), expected)

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

class TC_03_QvmRevertTemplateChanges(qubes.tests.SystemTestCase):
    # pylint: disable=attribute-defined-outside-init

    def setUp(self):
        super(TC_03_QvmRevertTemplateChanges, self).setUp()
        self.init_default_template()

    def cleanup_template(self):
        del self.test_template

    def setup_template(self):
        self.test_template = self.app.add_new_vm(
            qubes.vm.templatevm.TemplateVM,
            name=self.make_vm_name("pv-clone"),
            label='red'
        )
        self.addCleanup(self.cleanup_template)
        self.test_template.clone_properties(self.app.default_template)
        self.test_template.features.update(self.app.default_template.features)
        self.test_template.tags.update(self.app.default_template.tags)
        self.loop.run_until_complete(
            self.test_template.clone_disk_files(self.app.default_template))
        self.test_template.volumes['root'].revisions_to_keep = 3
        self.app.save()

    def get_rootimg_checksum(self):
        return subprocess.check_output(
            ['sha1sum', self.test_template.volumes['root'].export()]).\
            decode().split(' ')[0]

    def _do_test(self):
        checksum_before = self.get_rootimg_checksum()
        self.loop.run_until_complete(self.test_template.start())
        self.shutdown_and_wait(self.test_template)
        checksum_changed = self.get_rootimg_checksum()
        if checksum_before == checksum_changed:
            self.log.warning("template not modified, test result will be "
                             "unreliable")
        self.assertNotEqual(self.test_template.volumes['root'].revisions, {})
        revert_cmd = ['qvm-volume', 'revert', self.test_template.name + ':root']
        p = self.loop.run_until_complete(asyncio.create_subprocess_exec(
            *revert_cmd))
        self.loop.run_until_complete(p.wait())
        self.assertEqual(p.returncode, 0)
        del p

        checksum_after = self.get_rootimg_checksum()
        self.assertEqual(checksum_before, checksum_after)

    def test_000_revert_linux(self):
        """
        Test qvm-revert-template-changes for PV template
        """
        self.setup_template()
        self._do_test()

    @unittest.skip('TODO: some non-linux system')
    def test_001_revert_non_linux(self):
        """
        Test qvm-revert-template-changes for HVM template
        """
        # TODO: have some system there, so the root.img will get modified
        self.setup_template()
        self._do_test()

class TC_30_Gui_daemon(qubes.tests.SystemTestCase):
    def setUp(self):
        super(TC_30_Gui_daemon, self).setUp()
        self.init_default_template()

    @unittest.skipUnless(
        spawn.find_executable('xdotool'),
                         "xdotool not installed")
    def test_000_clipboard(self):
        testvm1 = self.app.add_new_vm(qubes.vm.appvm.AppVM,
                                     name=self.make_vm_name('vm1'), label='red')
        self.loop.run_until_complete(testvm1.create_on_disk())
        testvm2 = self.app.add_new_vm(qubes.vm.appvm.AppVM,
                                     name=self.make_vm_name('vm2'), label='red')
        self.loop.run_until_complete(testvm2.create_on_disk())
        self.app.save()

        self.loop.run_until_complete(asyncio.wait([
            testvm1.start(),
            testvm2.start()]))
        self.loop.run_until_complete(asyncio.wait([
            self.wait_for_session(testvm1),
            self.wait_for_session(testvm2)]))
        window_title = 'user@{}'.format(testvm1.name)
        self.loop.run_until_complete(testvm1.run(
            'zenity --text-info --editable --title={}'.format(window_title)))

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
        self.assertEqual(clipboard_content, test_string,
                          "Clipboard copy operation failed - content")
        clipboard_source = \
            open('/var/run/qubes/qubes-clipboard.bin.source',
                 'r').read().strip()
        self.assertEqual(clipboard_source, testvm1.name,
                          "Clipboard copy operation failed - owner")

        # Then paste it to the other window
        window_title = 'user@{}'.format(testvm2.name)
        p = self.loop.run_until_complete(testvm2.run(
            'zenity --entry --title={} > /tmp/test.txt'.format(window_title)))
        self.wait_for_window(window_title)

        subprocess.check_call(['xdotool', 'key', '--delay', '100',
                               'ctrl+shift+v', 'ctrl+v', 'Return'])
        self.loop.run_until_complete(p.wait())

        # And compare the result
        (test_output, _) = self.loop.run_until_complete(
            testvm2.run_for_stdio('cat /tmp/test.txt'))
        self.assertEqual(test_string, test_output.strip().decode('ascii'))

        clipboard_content = \
            open('/var/run/qubes/qubes-clipboard.bin', 'r').read().strip()
        self.assertEqual(clipboard_content, "",
                          "Clipboard not wiped after paste - content")
        clipboard_source = \
            open('/var/run/qubes/qubes-clipboard.bin.source', 'r').\
            read().strip()
        self.assertEqual(clipboard_source, "",
                          "Clipboard not wiped after paste - owner")

class TC_05_StandaloneVMMixin(object):
    def setUp(self):
        super(TC_05_StandaloneVMMixin, self).setUp()
        self.init_default_template(self.template)

    def test_000_create_start(self):
        self.testvm1 = self.app.add_new_vm(qubes.vm.standalonevm.StandaloneVM,
                                     name=self.make_vm_name('vm1'), label='red')
        self.testvm1.features.update(self.app.default_template.features)
        self.loop.run_until_complete(
            self.testvm1.clone_disk_files(self.app.default_template))
        self.app.save()
        self.loop.run_until_complete(self.testvm1.start())
        self.assertEqual(self.testvm1.get_power_state(), "Running")

    def test_100_resize_root_img(self):
        self.testvm1 = self.app.add_new_vm(qubes.vm.standalonevm.StandaloneVM,
                                     name=self.make_vm_name('vm1'), label='red')
        self.testvm1.features.update(self.app.default_template.features)
        self.loop.run_until_complete(
            self.testvm1.clone_disk_files(self.app.default_template))
        self.app.save()
        try:
            self.loop.run_until_complete(
                self.testvm1.storage.resize(self.testvm1.volumes['root'],
                    20 * 1024 ** 3))
        except (subprocess.CalledProcessError,
                qubes.storage.StoragePoolException) as e:
            # exception object would leak VM reference
            self.fail(str(e))
        self.assertEqual(self.testvm1.volumes['root'].size, 20 * 1024 ** 3)
        self.loop.run_until_complete(self.testvm1.start())
        # new_size in 1k-blocks
        (new_size, _) = self.loop.run_until_complete(
            self.testvm1.run_for_stdio('df --output=size /|tail -n 1'))
        # some safety margin for FS metadata
        self.assertGreater(int(new_size.strip()), 19 * 1024 ** 2)

    def test_101_resize_root_img_online(self):
        self.testvm1 = self.app.add_new_vm(qubes.vm.standalonevm.StandaloneVM,
                                     name=self.make_vm_name('vm1'), label='red')
        self.testvm1.features['qrexec'] = True
        self.loop.run_until_complete(
            self.testvm1.clone_disk_files(self.app.default_template))
        self.testvm1.features.update(self.app.default_template.features)
        self.app.save()
        self.loop.run_until_complete(self.testvm1.start())
        try:
            self.loop.run_until_complete(
                self.testvm1.storage.resize(self.testvm1.volumes['root'],
                    20 * 1024 ** 3))
        except (subprocess.CalledProcessError,
                qubes.storage.StoragePoolException) as e:
            # exception object would leak VM reference
            self.fail(str(e))
        self.assertEqual(self.testvm1.volumes['root'].size, 20 * 1024 ** 3)
        # new_size in 1k-blocks
        (new_size, _) = self.loop.run_until_complete(
            self.testvm1.run_for_stdio('df --output=size /|tail -n 1'))
        # some safety margin for FS metadata
        self.assertGreater(int(new_size.strip()), 19 * 1024 ** 2)

class TC_06_AppVMMixin(object):
    template = None

    def setUp(self):
        super(TC_06_AppVMMixin, self).setUp()
        self.init_default_template(self.template)

    @unittest.skipUnless(
        spawn.find_executable('xdotool'), "xdotool not installed")
    def test_121_start_standalone_with_cdrom_vm(self):
        cdrom_vmname = self.make_vm_name('cdrom')
        self.cdrom_vm = self.app.add_new_vm('AppVM', label='red',
            name=cdrom_vmname)
        self.loop.run_until_complete(self.cdrom_vm.create_on_disk())
        self.loop.run_until_complete(self.cdrom_vm.start())
        iso_path = self.create_bootable_iso()
        with open(iso_path, 'rb') as iso_f:
            self.loop.run_until_complete(
                self.cdrom_vm.run_for_stdio('cat > /home/user/boot.iso',
                stdin=iso_f))

        vmname = self.make_vm_name('appvm')
        self.vm = self.app.add_new_vm('StandaloneVM', label='red', name=vmname)
        self.loop.run_until_complete(self.vm.create_on_disk())
        self.vm.kernel = None
        self.vm.virt_mode = 'hvm'

        # start the VM using qvm-start tool, to test --cdrom option there
        p = self.loop.run_until_complete(asyncio.create_subprocess_exec(
            'qvm-start', '--cdrom=' + cdrom_vmname + ':/home/user/boot.iso',
            self.vm.name,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT))
        (stdout, _) = self.loop.run_until_complete(p.communicate())
        self.assertEqual(p.returncode, 0, stdout)
        # check if VM do not crash instantly
        self.loop.run_until_complete(asyncio.sleep(5))
        self.assertTrue(self.vm.is_running())
        # Type 'poweroff'
        subprocess.check_call(['xdotool', 'search', '--name', self.vm.name,
                               'type', 'poweroff\r'])
        self.loop.run_until_complete(asyncio.sleep(1))
        self.assertFalse(self.vm.is_running())


def load_tests(loader, tests, pattern):
    tests.addTests(loader.loadTestsFromNames(
        qubes.tests.create_testcases_for_templates('TC_05_StandaloneVM',
            TC_05_StandaloneVMMixin, qubes.tests.SystemTestCase,
            module=sys.modules[__name__])))
    tests.addTests(loader.loadTestsFromNames(
        qubes.tests.create_testcases_for_templates('TC_06_AppVM',
            TC_06_AppVMMixin, qubes.tests.SystemTestCase,
            module=sys.modules[__name__])))

    return tests

# vim: ts=4 sw=4 et
