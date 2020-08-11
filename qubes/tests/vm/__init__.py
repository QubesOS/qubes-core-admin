# pylint: disable=protected-access,pointless-statement

#
# The Qubes OS Project, https://www.qubes-os.org/
#
# Copyright (C) 2015  Joanna Rutkowska <joanna@invisiblethingslab.com>
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
import jinja2
import unittest.mock

import qubes.tests

class TestVMM(object):
    # pylint: disable=too-few-public-methods
    def __init__(self, offline_mode=False):
        self.offline_mode = offline_mode
        self.xs = unittest.mock.Mock()

    @property
    def libvirt_conn(self):
        if self.offline_mode:
            import libvirt
            raise libvirt.libvirtError('phony error')
        else:
            libvirt_mock = unittest.mock.Mock()
            vm_mock = libvirt_mock.lookupByUUID.return_value
            vm_mock.isActive.return_value = False
            return libvirt_mock

class TestHost(object):
    # pylint: disable=too-few-public-methods
    def __init__(self):
        self.memory_total = 1000 * 1024
        self.no_cpus = 4
        self.cpu_family_model = (6, 6)

class TestVMsCollection(dict):
    def get_vms_connected_to(self, vm):
        return set()

    def close(self):
        self.clear()

    def __iter__(self):
        return iter(self.values())

class TestVolume(object):
    def __init__(self, pool):
        self.pool = pool
        self.size = 0
        self.source = None

class TestPool(object):
    def init_volume(self, *args, **kwargs):
        return TestVolume(self)

class TestApp(qubes.tests.TestEmitter):
    labels = {1: qubes.Label(1, '0xcc0000', 'red'),
              2: qubes.Label(2, '0x00cc00', 'green'),
              3: qubes.Label(3, '0x0000cc', 'blue'),
              4: qubes.Label(4, '0xcccccc', 'black')}
    check_updates_vm = False

    def get_label(self, label):
        # pylint: disable=unused-argument
        if label in self.labels:
            return self.labels[label]
        for l in self.labels.values():
            if l.name == label:
                return l
        raise KeyError(label)

    def get_pool(self, pool):
        return self.pools[pool]

    def __init__(self):
        super(TestApp, self).__init__()
        self.vmm = TestVMM()
        self.host = TestHost()
        default_pool = TestPool()
        self.pools = {
            'default': default_pool,
            default_pool: default_pool,
            'linux-kernel': TestPool(),
        }
        self.default_pool_volatile = 'default'
        self.default_pool_root = 'default'
        self.default_pool_private = 'default'
        self.default_pool_kernel = 'linux-kernel'
        self.default_qrexec_timeout = 60
        self.default_netvm = None
        self.default_guivm = None
        self.domains = TestVMsCollection()
        #: jinja2 environment for libvirt XML templates
        self.env = jinja2.Environment(
            loader=jinja2.FileSystemLoader([
                'templates',
                '/etc/qubes/templates',
                '/usr/share/qubes/templates',
            ]),
            undefined=jinja2.StrictUndefined)
