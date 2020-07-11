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

    They are mostly identical to the lvm storage driver tests.
'''
# pylint: disable=line-too-long

import os
import json
import subprocess
import qubes.tests
import qubes.tests.storage
import qubes.tests.storage_lvm
from qubes.tests.storage_lvm import skipUnlessLvmPoolExists
import qubes.storage.callback

POOL_CLASS = qubes.storage.callback.CallbackPool
VOLUME_CLASS = qubes.storage.callback.CallbackVolume
POOL_CONF = {'name': 'test-callback',
             'driver': 'callback',
             'conf_id': 'utest-callback'}

CB_CONF = '/etc/qubes_callback.json'

CB_DATA = {'utest-callback': {
                'bdriver': 'lvm_thin',
                'bdriver_args': {
                     'volume_group': qubes.tests.storage_lvm.DEFAULT_LVM_POOL.split('/')[0],
                     'thin_pool':    qubes.tests.storage_lvm.DEFAULT_LVM_POOL.split('/')[1]
                },
                'description': 'For unit testing of the callback pool driver.'
              }
          }

class CallbackBase:
    ''' Mixin base class for callback tests. Has no base class. '''
    bak_pool_class = None
    bak_volume_class = None
    bak_pool_conf = None

    @classmethod
    def setUpClass(cls):
        CallbackBase.bak_pool_class = qubes.tests.storage_lvm.POOL_CLASS
        CallbackBase.bak_volume_class = qubes.tests.storage_lvm.VOLUME_CLASS
        CallbackBase.bak_pool_conf = qubes.tests.storage_lvm.POOL_CONF
        qubes.tests.storage_lvm.POOL_CLASS = POOL_CLASS
        qubes.tests.storage_lvm.VOLUME_CLASS = VOLUME_CLASS
        qubes.tests.storage_lvm.POOL_CONF = POOL_CONF

        assert not(os.path.exists(CB_CONF)), '%s must NOT exist. Please delete it, if you do not need it.' % CB_CONF

        sudo = [] if os.getuid() == 0 else ['sudo']
        subprocess.run(sudo + ['install', '-m', '666', '/dev/null', CB_CONF], check=True)

        with open(CB_CONF, 'w') as outfile:
            json.dump(CB_DATA, outfile)
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        if CallbackBase.bak_pool_class:
            qubes.tests.storage_lvm.POOL_CLASS = CallbackBase.bak_pool_class
        if CallbackBase.bak_volume_class:
            qubes.tests.storage_lvm.VOLUME_CLASS = CallbackBase.bak_volume_class
        if CallbackBase.bak_pool_conf:
            qubes.tests.storage_lvm.POOL_CONF = CallbackBase.bak_pool_conf

        sudo = [] if os.getuid() == 0 else ['sudo']
        subprocess.run(sudo + ['rm', '-f', CB_CONF], check=True)

    def setUp(self):
        super().setUp()
        #tests from other pools will assume that they're fully initialized after calling __init__()
        self.loop.run_until_complete(self.pool._assert_initialized())

    def test_000_000_callback_test_init(self):
        ''' Check whether the test init did work. '''
        self.assertIsInstance(self.pool, qubes.storage.callback.CallbackPool)
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
