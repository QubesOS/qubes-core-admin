#
# The Qubes OS Project, http://www.qubes-os.org
#
# Copyright (C) 2020 David Hobach <david@hobach.de>
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
''' Tests for the callback storage driver.

    They are mostly based upon the lvm storage driver tests.
'''
# pylint: disable=line-too-long

import os
import json
import subprocess
import qubes.tests
import qubes.tests.storage
import qubes.tests.storage_lvm
from qubes.tests.storage_lvm import skipUnlessLvmPoolExists
from qubes.storage.callback import CallbackPool, CallbackVolume

CB_CONF = '/etc/qubes_callback.json'
LOG_BIN = '/tmp/testCbLogArgs'

CB_DATA = {'utest-callback-01': {
                'bdriver': 'lvm_thin',
                'bdriver_args': {
                     'volume_group': qubes.tests.storage_lvm.DEFAULT_LVM_POOL.split('/')[0],
                     'thin_pool':    qubes.tests.storage_lvm.DEFAULT_LVM_POOL.split('/')[1]
                },
                'description': 'For unit testing of the callback pool driver.'
            },
            'utest-callback-02': {
                'bdriver': 'lvm_thin',
                'bdriver_args': {
                     'volume_group': qubes.tests.storage_lvm.DEFAULT_LVM_POOL.split('/')[0],
                     'thin_pool':    qubes.tests.storage_lvm.DEFAULT_LVM_POOL.split('/')[1]
                },
                'cmd': LOG_BIN,
                'description': 'For unit testing of the callback pool driver.'
            },
            'utest-callback-03': {
                'bdriver': 'lvm_thin',
                'bdriver_args': {
                     'volume_group': qubes.tests.storage_lvm.DEFAULT_LVM_POOL.split('/')[0],
                     'thin_pool':    qubes.tests.storage_lvm.DEFAULT_LVM_POOL.split('/')[1]
                },
                'cmd': 'exit 1',
                'post_ctor': LOG_BIN + ' post_ctor',
                'pre_sinit': LOG_BIN + ' pre_sinit',
                'pre_setup': LOG_BIN + ' pre_setup',
                'pre_volume_create': LOG_BIN + ' pre_volume_create',
                'pre_volume_import_data': LOG_BIN + ' pre_volume_import_data',
                'post_volume_import_data_end': LOG_BIN + ' post_volume_import_data_end',
                'post_volume_remove': LOG_BIN + ' post_volume_remove',
                'post_destroy': '-',
                'description': 'For unit testing of the callback pool driver.'
            },
            'testing-fail-missing-all': {
            },
            'testing-fail-missing-bdriver-args': {
                'bdriver': 'file',
                'description': 'For unit testing of the callback pool driver.'
            },
            'testing-fail-incorrect-bdriver': {
                'bdriver': 'nonexisting-bdriver',
                'bdriver_args': {
                     'foo': 'bar',
                     'bla': 'blub'
                },
                'cmd': 'echo foo',
                'description': 'For unit testing of the callback pool driver.'
            },
          }

class CallbackBase:
    ''' Mixin base class for callback tests. Has no base class. '''
    conf_id = None
    pool_name = 'test-callback'

    @classmethod
    def setUpClass(cls, conf_id='utest-callback-01'):
        conf = {'name': CallbackBase.pool_name,
                'driver': 'callback',
                'conf_id': conf_id}
        CallbackBase.conf_id = conf_id

        assert not(os.path.exists(CB_CONF)), '%s must NOT exist. Please delete it, if you do not need it.' % CB_CONF

        sudo = [] if os.getuid() == 0 else ['sudo']
        subprocess.run(sudo + ['install', '-m', '666', '/dev/null', CB_CONF], check=True)

        with open(CB_CONF, 'w') as outfile:
            json.dump(CB_DATA, outfile)
        super().setUpClass(pool_class=CallbackPool, volume_class=CallbackVolume, pool_conf=conf)

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()

        sudo = [] if os.getuid() == 0 else ['sudo']
        subprocess.run(sudo + ['rm', '-f', CB_CONF], check=True)

    def setUp(self, init_pool=True):
        super().setUp(init_pool=init_pool)
        if init_pool:
            #tests from other pools will assume that they're fully initialized after calling __init__()
            self.loop.run_until_complete(self.pool._assert_initialized())

    def test_000_000_callback_test_init(self):
        ''' Check whether the test init did work. '''
        if hasattr(self, 'pool'):
            self.assertIsInstance(self.pool, CallbackPool)
            self.assertEqual(self.pool.backend_class, qubes.storage.lvm.ThinPool)
        self.assertTrue(os.path.isfile(CB_CONF))

@skipUnlessLvmPoolExists
class TC_00_CallbackPool(CallbackBase, qubes.tests.storage_lvm.TC_00_ThinPool):
    pass

@skipUnlessLvmPoolExists
class TC_01_CallbackPool(CallbackBase, qubes.tests.storage_lvm.TC_01_ThinPool):
    pass

@skipUnlessLvmPoolExists
class TC_02_cb_StorageHelpers(CallbackBase, qubes.tests.storage_lvm.TC_02_StorageHelpers):
    pass

class LoggingCallbackBase(CallbackBase):
    ''' Mixin base class that sets up LOG_BIN and removes `LoggingCallbackBase.test_log`, if needed. '''
    test_log = '/tmp/cb_tests.log'
    test_log_expected = None #dict: class + test name --> test index (int, 0..x) --> expected _additional_ log content
    volume_name = 'volume_name'
    xml_path = '/tmp/qubes-test-callback.xml'

    @classmethod
    def setUpClass(cls, conf_id=None, log_expected=None):
        script = """#!/bin/bash
i=1
for arg in "$@" ; do
    echo "$i: $arg" >> "LOG_OUT"
    (( i++))
done
exit 0
"""
        script = script.replace('LOG_OUT', LoggingCallbackBase.test_log)
        with open(LOG_BIN, 'w') as f:
            f.write(script)
        os.chmod(LOG_BIN, 0o775)

        LoggingCallbackBase.test_log_expected = log_expected
        super().setUpClass(conf_id=conf_id)

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        os.remove(LOG_BIN)

    def setUp(self, init_pool=False):
        assert not(os.path.exists(LoggingCallbackBase.test_log)), '%s must NOT exist. Please delete it, if you do not need it.' % LoggingCallbackBase.test_log
        self.maxDiff = None

        xml = """
        <qubes>
          <labels>
            <label color="0x000000" id="label-8">black</label>
          </labels>
          <pools>
            <pool dir_path="/var/lib/qubes" driver="file" name="varlibqubes" revisions_to_keep="1"/>
            <pool dir_path="/var/lib/qubes/vm-kernels" driver="linux-kernel" name="linux-kernel"/>
            <pool conf_id="CONF_ID" driver="callback" name="POOL_NAME"/>
          </pools>
          <properties>
            <property name="clockvm"></property>
            <property name="default_pool_kernel">linux-kernel</property>
            <property name="default_template"></property>
            <property name="updatevm"></property>
          </properties>
          <domains>
            <domain id="domain-0" class="AdminVM">
              <properties>
                <property name="label">black</property>
              </properties>
              <features/>
              <tags/>
            </domain>
          </domains>
        </qubes>
        """
        xml = xml.replace('CONF_ID', CallbackBase.conf_id)
        xml = xml.replace('POOL_NAME', CallbackBase.pool_name)
        with open(LoggingCallbackBase.xml_path, 'w') as f:
            f.write(xml)
        self.app = qubes.Qubes(LoggingCallbackBase.xml_path,
            clockvm=None,
            updatevm=None,
            offline_mode=True,
        )
        os.environ['QUBES_XML_PATH'] = LoggingCallbackBase.xml_path
        super().setUp(init_pool=init_pool)

    def tearDown(self):
        super().tearDown()
        os.unlink(self.app.store)
        self.app.close()
        del self.app
        for attr in dir(self):
            if isinstance(getattr(self, attr), qubes.vm.BaseVM):
                delattr(self, attr)

        if os.path.exists(LoggingCallbackBase.test_log):
            os.remove(LoggingCallbackBase.test_log)

        if os.path.exists(LoggingCallbackBase.xml_path):
            os.remove(LoggingCallbackBase.xml_path)

    def assertLogContent(self, expected):
        ''' Assert that the log matches the given string.
        :param expected: Expected content of the log file (String).
        '''
        try:
            with open(LoggingCallbackBase.test_log, 'r') as f:
                found = f.read()
        except FileNotFoundError:
            found = ''
        if expected != '':
            expected = expected + '\n'
        self.assertEqual(found, expected)

    def assertLog(self, test_name, ind=0):
        ''' Assert that the log matches the expected status.
        :param test_name: Name of the test.
        :param ind: Index inside `test_log_expected` to check against (Integer starting at 0).
        '''
        d = LoggingCallbackBase.test_log_expected[str(self.__class__) + test_name]
        expected = []
        for i in range(ind+1):
            expected = expected + [d[i]]
        expected = filter(None, expected)
        self.assertLogContent('\n'.join(expected))

    def test_001_callbacks(self):
        ''' create a lvm pool with additional callbacks '''
        config = {
            'name': LoggingCallbackBase.volume_name,
            'pool': CallbackBase.pool_name,
            'save_on_stop': True,
            'rw': True,
            'revisions_to_keep': 2,
            'size': qubes.config.defaults['root_img_size'],
        }
        new_size = 2 * qubes.config.defaults['root_img_size']

        test_name = 'test_001_callbacks'
        self.assertLog(test_name, 0)
        self.init_pool()
        self.assertFalse(self.created_pool)
        self.assertIsInstance(self.pool, CallbackPool)
        self.assertLog(test_name, 1)
        vm = qubes.tests.storage.TestVM(self)
        volume = self.app.get_pool(self.pool.name).init_volume(vm, config)
        self.assertLog(test_name, 2)
        self.loop.run_until_complete(volume.create())
        self.assertLog(test_name, 3)
        self.loop.run_until_complete(volume.import_data(new_size))
        self.assertLog(test_name, 4)
        self.loop.run_until_complete(volume.import_data_end(True))
        self.assertLog(test_name, 5)
        self.assertEqual(volume.size, new_size)
        self.loop.run_until_complete(volume.remove())
        self.assertLog(test_name, 6)

@skipUnlessLvmPoolExists
class TC_91_CallbackPool(LoggingCallbackBase, qubes.tests.storage_lvm.ThinPoolBase):
    ''' Tests for the actual callback functionality.
        conf_id = utest-callback-02
    '''

    @classmethod
    def setUpClass(cls):
        conf_id = 'utest-callback-02'
        name = CallbackBase.pool_name
        bdriver = (CB_DATA[conf_id])['bdriver']
        ctor_params = json.dumps(CB_DATA[conf_id], sort_keys=True, indent=2)
        vname = LoggingCallbackBase.volume_name
        vid = '{0}/vm-test-inst-appvm-{1}'.format(qubes.tests.storage_lvm.DEFAULT_LVM_POOL.split('/')[0], vname)
        vsize = 2 * qubes.config.defaults['root_img_size']
        log_expected = \
            {str(cls) + 'test_001_callbacks':
                {0: '1: {0}\n2: {1}\n3: post_ctor\n4: {2}'.format(name, bdriver, ctor_params),
                 1: '',
                 2: '',
                 3: '1: {0}\n2: {1}\n3: pre_sinit\n4: {2}\n1: {0}\n2: {1}\n3: pre_volume_create\n4: {2}\n5: {3}\n6: {4}\n7: None'.format(name, bdriver, ctor_params, vname, vid),
                 4: '1: {0}\n2: {1}\n3: pre_volume_import_data\n4: {2}\n5: {3}\n6: {4}\n7: None\n8: {5}'.format(name, bdriver, ctor_params, vname, vid, vsize),
                 5: '1: {0}\n2: {1}\n3: post_volume_import_data_end\n4: {2}\n5: {3}\n6: {4}\n7: None\n8: {5}'.format(name, bdriver, ctor_params, vname, vid, True),
                 6: '1: {0}\n2: {1}\n3: post_volume_remove\n4: {2}\n5: {3}\n6: {4}\n7: None'.format(name, bdriver, ctor_params, vname, vid),
                 }
            }
        super().setUpClass(conf_id=conf_id, log_expected=log_expected)

@skipUnlessLvmPoolExists
class TC_92_CallbackPool(LoggingCallbackBase, qubes.tests.storage_lvm.ThinPoolBase):
    ''' Tests for the actual callback functionality.
        conf_id = utest-callback-03
    '''

    @classmethod
    def setUpClass(cls):
        log_expected = \
            {str(cls) + 'test_001_callbacks':
                {0: '1: post_ctor',
                 1: '',
                 2: '',
                 3: '1: pre_sinit\n1: pre_volume_create',
                 4: '1: pre_volume_import_data',
                 5: '1: post_volume_import_data_end',
                 6: '1: post_volume_remove',
                 }
            }
        super().setUpClass(conf_id='utest-callback-03', log_expected=log_expected)

    def test_002_failing_callback(self):
        ''' Make sure that we check the exit code of executed callbacks. '''
        config = {
            'name': LoggingCallbackBase.volume_name,
            'pool': CallbackBase.pool_name,
            'save_on_stop': True,
            'rw': True,
            'revisions_to_keep': 2,
            'size': qubes.config.defaults['root_img_size'],
        }
        self.init_pool()
        vm = qubes.tests.storage.TestVM(self)
        volume = self.app.get_pool(self.pool.name).init_volume(vm, config)
        with self.assertRaises(subprocess.CalledProcessError) as cm:
            #should trigger the `exit 1` of `cmd`
            self.loop.run_until_complete(volume.start())
        self.assertTrue('exit status 1' in str(cm.exception))

    def test_003_errors(self):
        ''' Make sure we error out on common user & dev mistakes. '''
        #missing conf_id
        with self.assertRaises(qubes.storage.StoragePoolException):
            cb = CallbackPool(name='some-name', conf_id='')

        #invalid conf_id
        with self.assertRaises(qubes.storage.StoragePoolException):
            cb = CallbackPool(name='some-name', conf_id='nonexisting-id')

        #incorrect backend driver
        with self.assertRaises(qubes.storage.StoragePoolException):
            cb = CallbackPool(name='some-name', conf_id='testing-fail-incorrect-bdriver')

        #missing config entries
        with self.assertRaises(qubes.storage.StoragePoolException):
            cb = CallbackPool(name='some-name', conf_id='testing-fail-missing-all')

        #missing bdriver args
        with self.assertRaises(TypeError):
            cb = CallbackPool(name='some-name', conf_id='testing-fail-missing-bdriver-args')

class TC_93_CallbackPool(qubes.tests.QubesTestCase):
    def test_001_missing_conf(self):
        ''' A missing config file must cause errors. '''
        with self.assertRaises(FileNotFoundError):
            cb = CallbackPool(name='some-name', conf_id='nonexisting-id')
