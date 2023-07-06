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
                               'type', '--window', '%1', 'poweroff\r'])
        for _ in range(10):
            if not self.vm.is_running():
                break
            self.loop.run_until_complete(asyncio.sleep(1))
        self.assertFalse(self.vm.is_running())

    def test_130_autostart_disable_on_remove(self):
        vm = self.app.add_new_vm(qubes.vm.appvm.AppVM,
            name=self.make_vm_name('vm'),
            template=self.app.default_template,
            label='red')

        self.assertIsNotNone(vm)
        self.loop.run_until_complete(vm.create_on_disk())
        vm.autostart = True
        self.assertTrue(os.path.exists(
            '/etc/systemd/system/multi-user.target.wants/'
            'qubes-vm@{}.service'.format(vm.name)),
            "systemd service not enabled by autostart=True")
        del self.app.domains[vm]
        self.loop.run_until_complete(vm.remove_from_disk())
        self.assertFalse(os.path.exists(
            '/etc/systemd/system/multi-user.target.wants/'
            'qubes-vm@{}.service'.format(vm.name)),
            "systemd service not disabled on domain remove")

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

        while self.vm.get_power_state() != 'Halted':
            self.loop.run_until_complete(asyncio.sleep(1))
        # and give a chance for both domain-shutdown handlers to execute
        self.loop.run_until_complete(asyncio.sleep(3))
        # wait for running shutdown handler to complete
        self.loop.run_until_complete(self.vm._domain_stopped_lock.acquire())
        self.vm._domain_stopped_lock.release()

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
            self.loop.run_until_complete(self.wait_for_session(vm))
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

    def _test_140_on_domain_paused(self, vm, event, **kwargs):
        self.domain_paused_received = True

    def test_140_libvirt_events_reconnect(self):
        vmname = self.make_vm_name('vm')

        self.vm = self.app.add_new_vm(qubes.vm.appvm.AppVM,
            name=vmname, template=self.app.default_template,
            label='red')
        self.loop.run_until_complete(self.vm.create_on_disk())
        self.loop.run_until_complete(self.vm.start())
        p = self.loop.run_until_complete(asyncio.create_subprocess_exec(
            'systemctl', 'restart', 'libvirtd'))
        self.loop.run_until_complete(p.communicate())
        # check if events still works
        self.domain_paused_received = False
        self.vm.add_handler('domain-paused', self._test_140_on_domain_paused)
        self.loop.run_until_complete(self.vm.pause())
        self.loop.run_until_complete(self.vm.kill())
        self.loop.run_until_complete(asyncio.sleep(1))
        self.assertTrue(self.domain_paused_received,
            'event not received after libvirt restart')

    def test_141_libvirt_objects_reconnect(self):
        vmname = self.make_vm_name('vm')

        # make sure libvirt object is cached
        self.app.domains[0].libvirt_domain.isActive()
        p = self.loop.run_until_complete(asyncio.create_subprocess_exec(
            'systemctl', 'restart', 'libvirtd'))
        self.loop.run_until_complete(p.communicate())
        # trigger reconnect
        with self.assertNotRaises(libvirt.libvirtError):
            self.app.vmm.libvirt_conn.getHostname()

        # check if vm object still works
        with self.assertNotRaises(libvirt.libvirtError):
            self.app.domains[0].libvirt_domain.isActive()

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
        pool = self.loop.run_until_complete(
            self.app.add_pool('test-filep', dir_path=pool_path, driver='file'))

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


class TC_03_QvmRevertTemplateChanges(qubes.tests.SystemTestCase):
    # pylint: disable=attribute-defined-outside-init

    def setUp(self):
        super(TC_03_QvmRevertTemplateChanges, self).setUp()
        if self.app.default_pool.driver == 'file':
            self.skipTest('file pool does not support reverting')
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
        path = self.loop.run_until_complete(
            self.test_template.storage.export('root'))
        try:
            return subprocess.check_output(['sha1sum', path]).\
                decode().split(' ')[0]
        finally:
            self.loop.run_until_complete(
                self.test_template.storage.export_end('root', path))

    def _do_test(self):
        checksum_before = self.get_rootimg_checksum()
        self.loop.run_until_complete(self.test_template.start())
        self.loop.run_until_complete(self.wait_for_session(self.test_template))
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

        self.loop.run_until_complete(asyncio.gather(
            testvm1.start(),
            testvm2.start()))
        self.loop.run_until_complete(asyncio.gather(
            self.wait_for_session(testvm1),
            self.wait_for_session(testvm2)))
        window_title = 'user@{}'.format(testvm1.name)
        self.loop.run_until_complete(testvm1.run(
            'zenity --text-info --editable --title={}'.format(window_title)))

        self.wait_for_window(window_title)
        self.loop.run_until_complete(asyncio.sleep(5))
        test_string = "test{}".format(testvm1.xid)

        # Type and copy some text
        subprocess.check_call(['xdotool', 'search', '--name', window_title,
                               'windowactivate', '--sync',
                               'type', test_string])
        self.loop.run_until_complete(asyncio.sleep(5))
        # second xdotool call because type --terminator do not work (SEGV)
        # additionally do not use search here, so window stack will be empty
        # and xdotool will use XTEST instead of generating events manually -
        # this will be much better - at least because events will have
        # correct timestamp (so gui-daemon would not drop the copy request)
        subprocess.check_call(['xdotool',
                               'key', 'ctrl+a', 'ctrl+c', 'ctrl+shift+c',
                               'Escape'])

        self.wait_for_window(window_title, show=False)

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
                               'ctrl+shift+v', 'ctrl+v', 'Return', 'alt+o'])
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
                               'type', '--window', '%1', 'poweroff\r'])
        for _ in range(10):
            if not self.vm.is_running():
                break
            self.loop.run_until_complete(asyncio.sleep(1))
        self.assertFalse(self.vm.is_running())

def create_testcases_for_templates():
    yield from qubes.tests.create_testcases_for_templates('TC_05_StandaloneVM',
            TC_05_StandaloneVMMixin, qubes.tests.SystemTestCase,
            module=sys.modules[__name__])
    yield from qubes.tests.create_testcases_for_templates('TC_06_AppVM',
            TC_06_AppVMMixin, qubes.tests.SystemTestCase,
            module=sys.modules[__name__])

def load_tests(loader, tests, pattern):
    tests.addTests(loader.loadTestsFromNames(
        create_testcases_for_templates()))

    return tests

qubes.tests.maybe_create_testcases_on_import(create_testcases_for_templates)

# vim: ts=4 sw=4 et
