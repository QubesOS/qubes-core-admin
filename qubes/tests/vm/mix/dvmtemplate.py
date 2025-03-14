# pylint: disable=protected-access

#
# The Qubes OS Project, https://www.qubes-os.org/
#
# Copyright (C) 2025  Benjamin Grande M. S. <ben.grande.b@gmail.com>
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

import unittest
import unittest.mock as mock

import qubes
import qubes.vm.qubesvm

import qubes.tests
import qubes.tests.vm
import qubes.tests.vm.appvm
import qubes.tests.vm.qubesvm
import qubes.vm.mix.dvmtemplate

# import (
#    get_feat_preload,
#    get_feat_preload_max,
#    can_preload,
# )


class TestApp(qubes.tests.vm.TestApp):
    def __init__(self):
        super(TestApp, self).__init__()
        self.qid_counter = 1

    def add_new_vm(self, cls, **kwargs):
        qid = self.qid_counter
        self.qid_counter += 1
        vm = cls(self, None, qid=qid, **kwargs)
        self.domains[vm.name] = vm
        self.domains[vm] = vm
        return vm


## TODO: finish
class TC_00_DVMTemplateMixin(
    qubes.tests.vm.qubesvm.QubesVMTestsMixin,
    qubes.tests.QubesTestCase,
    qubes.tests.TestEmitter,
):
    def setUp(self):
        super(TC_00_DVMTemplateMixin, self).setUp()
        self.app = qubes.tests.vm.TestApp()
        self.app = TestApp()
        self.app.save = mock.Mock()
        self.app.pools["default"] = qubes.tests.vm.appvm.TestPool(
            name="default"
        )
        self.app.pools["linux-kernel"] = qubes.tests.vm.appvm.TestPool(
            name="linux-kernel"
        )
        self.app.vmm.offline_mode = True
        self.template = self.app.add_new_vm(
            qubes.vm.templatevm.TemplateVM, name="test-template", label="red"
        )
        self.appvm = self.app.add_new_vm(
            qubes.vm.appvm.AppVM,
            name="test-vm",
            template=self.template,
            label="red",
        )
        self.app.domains[self.appvm.name] = self.appvm
        self.app.domains[self.appvm] = self.appvm
        self.addCleanup(self.cleanup_dispvm)
        self.emitter = qubes.tests.TestEmitter()
        # TODO: Ben: cleanup
        self.appvm_emitter = qubes.tests.TestEmitter()
        self.appvm.features = qubes.features.Features(self.appvm_emitter)
        self.app.domains[self.appvm].fire_event = self.emitter.fire_event

    def tearDown(self):
        del self.emitter
        del self.appvm_emitter
        super(TC_00_DVMTemplateMixin, self).tearDown()

    # def setup_dispvms(self, vm):
    #    # usage of QubesVM here means that those tests should be after
    #    # testing properties used here
    #    print(1)
    #    self.dvm = qubes.vm.qubesvm.QubesVM(
    #        self.app,
    #        None,
    #        qid=2,
    #        name=qubes.tests.VMPREFIX + "dvm",
    #        netvm=None,
    #    )
    #    self.app.domains = qubes.app.VMCollection(self.app)
    #    for domain in (vm, self.dvm):
    #        self.app.domains._dict[domain.qid] = domain
    #    self.app.default_dispvm = self.dvm
    #    self.addCleanup(self.cleanup_dispvm)

    def cleanup_dispvm(self):
        # self.dvm.close()
        # try:
        #    self.app.domains.close()
        # except AttributeError:
        #    pass
        # del self.dvm
        # del self.app.default_dispvm
        if hasattr(self, "dispvm"):
            self.dispvm.close()
            del self.dispvm
        self.template.close()
        self.appvm.close()
        del self.template
        del self.appvm
        self.app.domains.clear()
        self.app.pools.clear()

    def test_010_dvm_preload_get_max(self):
        # self.setup_dispvms(vm)
        self.appvm.template_for_dispvms = True
        self.assertFalse(self.appvm.can_preload())
        self.assertEqual(self.appvm.get_feat_preload_max(), 0)
        self.appvm.features["preload-dispvm-max"] = "1"
        self.assertEqual(self.appvm.get_feat_preload_max(), 1)
        self.assertTrue(self.appvm.can_preload())

    def test_010_dvm_preload_get_list(self):
        # self.setup_dispvms(vm)
        self.appvm.template_for_dispvms = True
        self.assertEqual(self.appvm.get_feat_preload(), [])
        self.appvm.features["preload-dispvm"] = "test1"
        self.assertEqual(self.appvm.get_feat_preload(), ["test1"])

        # self.assertEventFired(
        #    self.appvm_emitter,
        #    "domain-feature-pre-set:preload-dispvm-max",
        #    kwargs={"feature": "preload-dispvm-max", "value": "1"},
        # )

    def test_010_dvm_preload_feat_max_invalid(self):
        testcases = (
            (1),
            (-1),
            ("a"),
            ("1a"),
            ("a1"),
            (100000),
        )
        # for max_val in testcases:
        #    with self.subTest(str(max_val)):
        #        effect = loop.run_until_complete(self.emitter.fire_event("domain-feature-set"))
        # self.assertEqual(
        #    ipaddress.IPv4Address("1.1." + ip),
        #    vmid_to_ipv4("1.1", vmid),
        # )

    def test_010_dvm_preload_feat_list_invalid(self):
        # Preload qubes than lower the maximum.
        # Try to add qubes after that.
        pass
