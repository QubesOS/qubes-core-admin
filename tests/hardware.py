#!/usr/bin/python2
# -*- coding: utf-8 -*-
#
# The Qubes OS Project, http://www.qubes-os.org
#
# Copyright (C) 2016  Marek Marczykowski-Górecki
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

import qubes.tests
import time
import subprocess
from unittest import expectedFailure


class TC_00_HVM(qubes.tests.SystemTestsMixin, qubes.tests.QubesTestCase):
    def setUp(self):
        super(TC_00_HVM, self).setUp()
        self.vm = self.qc.add_new_vm("QubesHVm",
            name=self.make_vm_name('vm1'))
        self.vm.create_on_disk(verbose=False)

    @expectedFailure
    def test_000_pci_passthrough_presence(self):
        pcidev = os.environ.get('QUBES_TEST_PCIDEV', None)
        if pcidev is None:
            self.skipTest('Specify PCI device with QUBES_TEST_PCIDEV '
                          'environment variable')
        self.vm.pcidevs = [pcidev]
        self.vm.pci_strictreset = False
        self.qc.save()
        self.qc.unlock_db()

        init_script = (
            "#!/bin/sh\n"
            "set -e\n"
            "lspci -n > /dev/xvdb\n"
            "poweroff\n"
        )

        self.prepare_hvm_system_linux(self.vm, init_script,
            ['/usr/sbin/lspci'])
        self.vm.start()
        timeout = 60
        while timeout > 0:
            if not self.vm.is_running():
                break
            time.sleep(1)
            timeout -= 1
        if self.vm.is_running():
            self.fail("Timeout while waiting for VM shutdown")

        with open(self.vm.storage.private_img, 'r') as f:
            lspci_vm = f.read(512).strip('\0')
        p = subprocess.Popen(['lspci', '-ns', pcidev], stdout=subprocess.PIPE)
        (lspci_host, _) = p.communicate()
        # strip BDF, as it is different in VM
        pcidev_desc = ' '.join(lspci_host.strip().split(' ')[1:])
        self.assertIn(pcidev_desc, lspci_vm)
