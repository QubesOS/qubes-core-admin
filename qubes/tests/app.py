# pylint: disable=protected-access,pointless-statement

#
# The Qubes OS Project, https://www.qubes-os.org/
#
# Copyright (C) 2014-2015  Joanna Rutkowska <joanna@invisiblethingslab.com>
# Copyright (C) 2014-2015  Wojtek Porczyk <woju@invisiblethingslab.com>
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

import os
import unittest.mock as mock

import lxml.etree

import qubes
import qubes.events

import qubes.tests
import qubes.tests.init
import qubes.tests.storage_reflink

import logging
import time


class TestApp(qubes.tests.TestEmitter):
    pass


class TC_20_QubesHost(qubes.tests.QubesTestCase):
    sample_xc_domain_getinfo = [
        {
            "paused": 0,
            "cpu_time": 243951379111104,
            "ssidref": 0,
            "hvm": 0,
            "shutdown_reason": 255,
            "dying": 0,
            "mem_kb": 3733212,
            "domid": 0,
            "max_vcpu_id": 7,
            "crashed": 0,
            "running": 1,
            "maxmem_kb": 3734236,
            "shutdown": 0,
            "online_vcpus": 8,
            "handle": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
            "cpupool": 0,
            "blocked": 0,
        },
        {
            "paused": 0,
            "cpu_time": 2849496569205,
            "ssidref": 0,
            "hvm": 0,
            "shutdown_reason": 255,
            "dying": 0,
            "mem_kb": 303916,
            "domid": 1,
            "max_vcpu_id": 0,
            "crashed": 0,
            "running": 0,
            "maxmem_kb": 308224,
            "shutdown": 0,
            "online_vcpus": 1,
            "handle": [
                116,
                174,
                229,
                207,
                17,
                1,
                79,
                39,
                191,
                37,
                41,
                186,
                205,
                158,
                219,
                8,
            ],
            "cpupool": 0,
            "blocked": 1,
        },
        {
            "paused": 0,
            "cpu_time": 249658663079978,
            "ssidref": 0,
            "hvm": 0,
            "shutdown_reason": 255,
            "dying": 0,
            "mem_kb": 3782668,
            "domid": 11,
            "max_vcpu_id": 7,
            "crashed": 0,
            "running": 0,
            "maxmem_kb": 3783692,
            "shutdown": 0,
            "online_vcpus": 8,
            "handle": [
                169,
                95,
                55,
                127,
                140,
                94,
                79,
                220,
                186,
                210,
                117,
                5,
                148,
                11,
                185,
                206,
            ],
            "cpupool": 0,
            "blocked": 1,
        },
    ]

    def setUp(self):
        super(TC_20_QubesHost, self).setUp()
        self.app = TestApp()
        self.app.vmm = mock.Mock()
        self.qubes_host = qubes.app.QubesHost(self.app)
        self.maxDiff = None

    def test_000_get_vm_stats_single(self):
        self.app.vmm.configure_mock(
            **{"xc.domain_getinfo.return_value": self.sample_xc_domain_getinfo}
        )

        info_time, info = self.qubes_host.get_vm_stats()
        self.assertEqual(
            self.app.vmm.mock_calls,
            [
                ("xc.domain_getinfo", (0, 1024), {}),
            ],
        )
        self.assertIsNotNone(info_time)
        expected_info = {
            0: {
                "cpu_time": 243951379111104,
                "cpu_usage": 0,
                "cpu_usage_raw": 0,
                "memory_kb": 3733212,
            },
            1: {
                "cpu_time": 2849496569205,
                "cpu_usage": 0,
                "cpu_usage_raw": 0,
                "memory_kb": 303916,
            },
            11: {
                "cpu_time": 249658663079978,
                "cpu_usage": 0,
                "cpu_usage_raw": 0,
                "memory_kb": 3782668,
            },
        }
        self.assertEqual(info, expected_info)

    def test_001_get_vm_stats_twice(self):
        self.app.vmm.configure_mock(
            **{"xc.domain_getinfo.return_value": self.sample_xc_domain_getinfo}
        )

        prev_time, prev_info = self.qubes_host.get_vm_stats()
        prev_time -= 1
        prev_info[0]["cpu_time"] -= 8 * 10**8  # 0.8s
        prev_info[1]["cpu_time"] -= 10**9  # 1s
        prev_info[11]["cpu_time"] -= 10**9  # 1s
        info_time, info = self.qubes_host.get_vm_stats(prev_time, prev_info)
        self.assertIsNotNone(info_time)
        expected_info = {
            0: {
                "cpu_time": 243951379111104,
                "cpu_usage": 10,
                "cpu_usage_raw": 80,
                "memory_kb": 3733212,
            },
            1: {
                "cpu_time": 2849496569205,
                "cpu_usage": 100,
                "cpu_usage_raw": 100,
                "memory_kb": 303916,
            },
            11: {
                "cpu_time": 249658663079978,
                "cpu_usage": 12,
                "cpu_usage_raw": 100,
                "memory_kb": 3782668,
            },
        }
        self.assertEqual(info, expected_info)
        self.assertEqual(
            self.app.vmm.mock_calls,
            [
                ("xc.domain_getinfo", (0, 1024), {}),
                ("xc.domain_getinfo", (0, 1024), {}),
            ],
        )

    def test_002_get_vm_stats_one_vm(self):
        self.app.vmm.configure_mock(
            **{
                "xc.domain_getinfo.return_value": [
                    self.sample_xc_domain_getinfo[1]
                ]
            }
        )

        vm = mock.Mock
        vm.xid = 1
        vm.name = "somevm"

        info_time, info = self.qubes_host.get_vm_stats(only_vm=vm)
        self.assertIsNotNone(info_time)
        self.assertEqual(
            self.app.vmm.mock_calls,
            [
                ("xc.domain_getinfo", (1, 1), {}),
            ],
        )

    def test_010_iommu_supported(self):
        self.app.vmm.configure_mock(
            **{
                "xc.physinfo.return_value": {
                    "hw_caps": "...",
                    "scrub_memory": 0,
                    "virt_caps": "hvm hvm_directio",
                    "nr_cpus": 4,
                    "threads_per_core": 1,
                    "cpu_khz": 3400001,
                    "nr_nodes": 1,
                    "free_memory": 234752,
                    "cores_per_socket": 4,
                    "total_memory": 16609720,
                }
            }
        )
        self.assertEqual(self.qubes_host.is_iommu_supported(), True)

    def test_011_iommu_supported(self):
        self.app.vmm.configure_mock(
            **{
                "xc.physinfo.return_value": {
                    "hw_caps": "...",
                    "scrub_memory": 0,
                    "virt_caps": "hvm hvm_directio pv pv_directio",
                    "nr_cpus": 4,
                    "threads_per_core": 1,
                    "cpu_khz": 3400001,
                    "nr_nodes": 1,
                    "free_memory": 234752,
                    "cores_per_socket": 4,
                    "total_memory": 16609720,
                }
            }
        )
        self.assertEqual(self.qubes_host.is_iommu_supported(), True)

    def test_012_iommu_supported(self):
        self.app.vmm.configure_mock(
            **{
                "xc.physinfo.return_value": {
                    "hw_caps": "...",
                    "scrub_memory": 0,
                    "virt_caps": "hvm pv",
                    "nr_cpus": 4,
                    "threads_per_core": 1,
                    "cpu_khz": 3400001,
                    "nr_nodes": 1,
                    "free_memory": 234752,
                    "cores_per_socket": 4,
                    "total_memory": 16609720,
                }
            }
        )
        self.assertEqual(self.qubes_host.is_iommu_supported(), False)


class TC_30_VMCollection(qubes.tests.QubesTestCase):
    def setUp(self):
        super().setUp()
        self.app = TestApp()
        self.vms = qubes.app.VMCollection(self.app)
        self.app.log = logging.getLogger()

        self.testvm1 = qubes.tests.init.TestVM(
            None, None, qid=1, name="testvm1"
        )
        self.testvm2 = qubes.tests.init.TestVM(
            None, None, qid=2, name="testvm2"
        )

        self.addCleanup(self.cleanup_vmcollection)

    def cleanup_vmcollection(self):
        self.testvm1.close()
        self.testvm2.close()
        self.vms.close()
        del self.testvm1
        del self.testvm2
        del self.vms
        del self.app

    def test_000_contains(self):
        self.vms._dict = {1: self.testvm1}

        self.assertIn(1, self.vms)
        self.assertIn("testvm1", self.vms)
        self.assertIn(self.testvm1, self.vms)

        self.assertNotIn(2, self.vms)
        self.assertNotIn("testvm2", self.vms)
        self.assertNotIn(self.testvm2, self.vms)

    def test_001_getitem(self):
        self.vms._dict = {1: self.testvm1}

        self.assertIs(self.vms[1], self.testvm1)
        self.assertIs(self.vms["testvm1"], self.testvm1)
        self.assertIs(self.vms[self.testvm1], self.testvm1)

    def test_002_add(self):
        self.vms.add(self.testvm1)
        self.assertIn(1, self.vms)

        self.assertEventFired(
            self.app, "domain-add", kwargs={"vm": self.testvm1}
        )

        with self.assertRaises(TypeError):
            self.vms.add(object())

        testvm_qid_collision = qubes.tests.init.TestVM(
            None, None, name="testvm2", qid=1
        )
        testvm_name_collision = qubes.tests.init.TestVM(
            None, None, name="testvm1", qid=2
        )

        with self.assertRaises(ValueError):
            self.vms.add(testvm_qid_collision)
        with self.assertRaises(ValueError):
            self.vms.add(testvm_name_collision)

    def test_003_qids(self):
        self.vms.add(self.testvm1)
        self.vms.add(self.testvm2)

        self.assertCountEqual(self.vms.qids(), [1, 2])
        self.assertCountEqual(self.vms.keys(), [1, 2])

    def test_004_names(self):
        self.vms.add(self.testvm1)
        self.vms.add(self.testvm2)

        self.assertCountEqual(self.vms.names(), ["testvm1", "testvm2"])

    def test_005_vms(self):
        self.vms.add(self.testvm1)
        self.vms.add(self.testvm2)

        self.assertCountEqual(self.vms.vms(), [self.testvm1, self.testvm2])
        self.assertCountEqual(self.vms.values(), [self.testvm1, self.testvm2])

    def test_006_items(self):
        self.vms.add(self.testvm1)
        self.vms.add(self.testvm2)

        self.assertCountEqual(
            self.vms.items(), [(1, self.testvm1), (2, self.testvm2)]
        )

    def test_007_len(self):
        self.vms.add(self.testvm1)
        self.vms.add(self.testvm2)

        self.assertEqual(len(self.vms), 2)

    def test_008_delitem(self):
        self.vms.add(self.testvm1)
        self.vms.add(self.testvm2)

        del self.vms["testvm2"]

        self.assertCountEqual(self.vms.vms(), [self.testvm1])
        self.assertEventFired(
            self.app, "domain-delete", kwargs={"vm": self.testvm2}
        )

    def test_100_get_new_unused_qid(self):
        self.vms.add(self.testvm1)
        self.vms.add(self.testvm2)

        self.vms.get_new_unused_qid()

    def test_999999_get_new_unused_dispid(self):
        with mock.patch("random.SystemRandom") as random:
            random.return_value.randrange.side_effect = [11, 22, 33, 44, 55, 66]
            # Testing overal functionality
            self.assertEqual(self.vms.get_new_unused_dispid(), 11)
            self.assertEqual(self.vms.get_new_unused_dispid(), 22)
            self.assertEqual(self.vms.get_new_unused_dispid(), 33)
            # Testing no reuse
            self.vms._recent_dispids[44] = time.monotonic()
            self.assertNotEqual(self.vms.get_new_unused_dispid(), 44)
            # Testing reuse after safe period
            self.vms._recent_dispids[66] = (
                time.monotonic() - self.vms._no_dispid_reuse_period - 1
            )
            self.assertEqual(self.vms.get_new_unused_dispid(), 66)
            self.assertFalse(66 in self.vms._recent_dispids)


#   def test_200_get_vms_based_on(self):
#       pass

#   def test_201_get_vms_connected_to(self):
#       pass


class TC_80_QubesInitialPools(qubes.tests.QubesTestCase):
    def setUp(self):
        super().setUp()
        self.app = qubes.Qubes(
            "/tmp/qubestest.xml", load=False, offline_mode=True
        )
        self.test_dir = "/var/tmp/test-varlibqubes"
        self.test_patch = mock.patch.dict(
            qubes.config.defaults["pool_configs"]["varlibqubes"],
            {"dir_path": self.test_dir},
        )
        self.test_patch.start()

    def tearDown(self):
        self.test_patch.stop()
        self.app.close()
        del self.app

    def get_driver(self, fs_type, accessible):
        qubes.tests.storage_reflink.mkdir_fs(
            self.test_dir,
            fs_type,
            accessible=accessible,
            cleanup_via=self.addCleanup,
        )
        self.app.load_initial_values()

        varlibqubes = self.app.pools["varlibqubes"]
        self.assertEqual(varlibqubes.dir_path, self.test_dir)
        return varlibqubes.driver

    def test_100_varlibqubes_btrfs_accessible(self):
        self.assertEqual(self.get_driver("btrfs", True), "file-reflink")

    def test_101_varlibqubes_btrfs_inaccessible(self):
        self.assertEqual(self.get_driver("btrfs", False), "file")

    def test_102_varlibqubes_ext4_accessible(self):
        self.assertEqual(self.get_driver("ext4", True), "file")

    def test_103_varlibqubes_ext4_inaccessible(self):
        self.assertEqual(self.get_driver("ext4", False), "file")


class TC_89_QubesEmpty(qubes.tests.QubesTestCase):
    def tearDown(self):
        try:
            os.unlink("/tmp/qubestest.xml")
        except:
            pass
        try:
            self.app.close()
            del self.app
        except AttributeError:
            pass
        super().tearDown()

    @qubes.tests.skipUnlessDom0
    def test_000_init_empty(self):
        # pylint: disable=unused-variable,bare-except
        try:
            os.unlink("/tmp/qubestest.xml")
        except FileNotFoundError:
            pass
        qubes.Qubes.create_empty_store("/tmp/qubestest.xml").close()

    def test_100_property_migrate_default_fw_netvm(self):
        xml_template = """<?xml version="1.0" encoding="utf-8" ?>
        <qubes version="3.0">
            <properties>
                <property name="default_netvm">{default_netvm}</property>
                <property name="default_fw_netvm">{default_fw_netvm}</property>
            </properties>
            <labels>
                <label id="label-1" color="#cc0000">red</label>
            </labels>
            <pools>
              <pool driver="file" dir_path="/tmp/qubes-test" name="default"/>
            </pools>
            <domains>
                <domain class="StandaloneVM" id="domain-1">
                    <properties>
                        <property name="qid">1</property>
                        <property name="name">sys-net</property>
                        <property name="provides_network">True</property>
                        <property name="label" ref="label-1" />
                        <property name="netvm"></property>
                        <property name="uuid">2fcfc1f4-b2fe-4361-931a-c5294b35edfa</property>
                    </properties>
                    <features/>
                    <devices class="pci"/>
                </domain>

                <domain class="StandaloneVM" id="domain-2">
                    <properties>
                        <property name="qid">2</property>
                        <property name="name">sys-firewall</property>
                        <property name="provides_network">True</property>
                        <property name="label" ref="label-1" />
                        <property name="uuid">9a6d9689-25f7-48c9-a15f-8205d6c5b7c6</property>
                    </properties>
                </domain>

                <domain class="StandaloneVM" id="domain-3">
                    <properties>
                        <property name="qid">3</property>
                        <property name="name">appvm</property>
                        <property name="label" ref="label-1" />
                        <property name="uuid">1d6aab41-3262-400a-b3d3-21aae8fdbec8</property>
                    </properties>
                </domain>
            </domains>
        </qubes>
        """
        with self.subTest("default_setup"):
            with open("/tmp/qubestest.xml", "w") as xml_file:
                xml_file.write(
                    xml_template.format(
                        default_netvm="sys-firewall", default_fw_netvm="sys-net"
                    )
                )
            self.app = qubes.Qubes("/tmp/qubestest.xml", offline_mode=True)
            self.assertEqual(self.app.domains["sys-net"].netvm, None)
            self.assertEqual(
                self.app.domains["sys-firewall"].netvm,
                self.app.domains["sys-net"],
            )
            # property is no longer "default"
            self.assertFalse(
                self.app.domains["sys-firewall"].property_is_default("netvm")
            )
            # verify that appvm.netvm is unaffected
            self.assertTrue(
                self.app.domains["appvm"].property_is_default("netvm")
            )
            self.assertEqual(
                self.app.domains["appvm"].netvm,
                self.app.domains["sys-firewall"],
            )
            with self.assertRaises(AttributeError):
                self.app.default_fw_netvm

            self.app.close()
            del self.app

        with self.subTest("same"):
            with open("/tmp/qubestest.xml", "w") as xml_file:
                xml_file.write(
                    xml_template.format(
                        default_netvm="sys-net", default_fw_netvm="sys-net"
                    )
                )
            self.app = qubes.Qubes("/tmp/qubestest.xml", offline_mode=True)
            self.assertEqual(self.app.domains["sys-net"].netvm, None)
            self.assertEqual(
                self.app.domains["sys-firewall"].netvm,
                self.app.domains["sys-net"],
            )
            self.assertTrue(
                self.app.domains["sys-firewall"].property_is_default("netvm")
            )
            # verify that appvm.netvm is unaffected
            self.assertTrue(
                self.app.domains["appvm"].property_is_default("netvm")
            )
            self.assertEqual(
                self.app.domains["appvm"].netvm, self.app.domains["sys-net"]
            )
            with self.assertRaises(AttributeError):
                self.app.default_fw_netvm

            self.app.close()
            del self.app

        with self.subTest("loop"):
            with open("/tmp/qubestest.xml", "w") as xml_file:
                xml_file.write(
                    xml_template.format(
                        default_netvm="sys-firewall",
                        default_fw_netvm="sys-firewall",
                    )
                )
            self.app = qubes.Qubes("/tmp/qubestest.xml", offline_mode=True)
            self.assertEqual(self.app.domains["sys-net"].netvm, None)
            # this was netvm loop, better set to none, to not crash qubesd
            self.assertEqual(self.app.domains["sys-firewall"].netvm, None)
            self.assertFalse(
                self.app.domains["sys-firewall"].property_is_default("netvm")
            )
            # verify that appvm.netvm is unaffected
            self.assertTrue(
                self.app.domains["appvm"].property_is_default("netvm")
            )
            self.assertEqual(
                self.app.domains["appvm"].netvm,
                self.app.domains["sys-firewall"],
            )
            with self.assertRaises(AttributeError):
                self.app.default_fw_netvm

            self.app.close()
            del self.app

    def test_101_property_migrate_label(self):
        xml_template = """<?xml version="1.0" encoding="utf-8" ?>
        <qubes version="3.0">
            <labels>
                <label id="label-1" color="{old_gray}">gray</label>
            </labels>
            <pools>
              <pool driver="file" dir_path="/tmp/qubes-test" name="default"/>
            </pools>
            <domains>
                <domain class="StandaloneVM" id="domain-1">
                    <properties>
                        <property name="qid">1</property>
                        <property name="name">sys-net</property>
                        <property name="provides_network">True</property>
                        <property name="label" ref="label-1" />
                        <property name="netvm"></property>
                        <property name="uuid">2fcfc1f4-b2fe-4361-931a-c5294b35edfa</property>
                    </properties>
                    <features/>
                    <devices class="pci"/>
                </domain>
            </domains>
        </qubes>
        """
        with self.subTest("replace_label"):
            with open("/tmp/qubestest.xml", "w") as xml_file:
                xml_file.write(xml_template.format(old_gray="0x555753"))
            self.app = qubes.Qubes("/tmp/qubestest.xml", offline_mode=True)
            self.assertEqual(self.app.get_label("gray").color, "0x555555")
            self.app.close()
            del self.app

        with self.subTest("dont_replace_label"):
            with open("/tmp/qubestest.xml", "w") as xml_file:
                xml_file.write(xml_template.format(old_gray="0x123456"))
            self.app = qubes.Qubes("/tmp/qubestest.xml", offline_mode=True)
            self.assertEqual(self.app.get_label("gray").color, "0x123456")
            self.app.close()
            del self.app


class TC_90_Qubes(qubes.tests.QubesTestCase):
    def tearDown(self):
        try:
            os.unlink("/tmp/qubestest.xml")
        except:
            pass
        super().tearDown()

    def setUp(self):
        super(TC_90_Qubes, self).setUp()
        self.app = qubes.Qubes(
            "/tmp/qubestest.xml", load=False, offline_mode=True
        )
        self.app.default_kernel = "dummy"
        self.addCleanup(self.cleanup_qubes)
        self.app.load_initial_values()
        self.template = self.app.add_new_vm(
            "TemplateVM", name="test-template", label="green"
        )

    def cleanup_qubes(self):
        self.app.close()
        del self.app
        try:
            del self.template
        except AttributeError:
            pass

    def test_100_clockvm(self):
        appvm = self.app.add_new_vm(
            "AppVM", name="test-vm", template=self.template, label="red"
        )
        self.assertIsNone(self.app.clockvm)
        self.assertNotIn("service.clocksync", appvm.features)
        self.assertNotIn("service.clocksync", self.template.features)
        self.app.clockvm = appvm
        self.assertIn("service.clocksync", appvm.features)
        self.assertTrue(appvm.features["service.clocksync"])
        self.app.clockvm = self.template
        self.assertNotIn("service.clocksync", appvm.features)
        self.assertIn("service.clocksync", self.template.features)
        self.assertTrue(self.template.features["service.clocksync"])

    def test_110_netvm_loop(self):
        """Netvm loop through default_netvm"""
        netvm = self.app.add_new_vm(
            "AppVM", name="test-net", template=self.template, label="red"
        )
        try:
            self.app.default_netvm = None
            netvm.netvm = qubes.property.DEFAULT
            with self.assertRaises(ValueError):
                self.app.default_netvm = netvm
        finally:
            del netvm

    def test_111_netvm_loop(self):
        """Netvm loop through default_netvm"""
        netvm = self.app.add_new_vm(
            "AppVM", name="test-net", template=self.template, label="red"
        )
        try:
            netvm.netvm = None
            self.app.default_netvm = netvm
            with self.assertRaises(ValueError):
                netvm.netvm = qubes.property.DEFAULT
        finally:
            del netvm

    def test_112_default_guivm(self):
        class MyTestHolder(qubes.tests.TestEmitter, qubes.PropertyHolder):
            default_guivm = qubes.property(
                "default_guivm", default=(lambda self: "dom0")
            )

        holder = MyTestHolder(None)
        guivm = self.app.add_new_vm(
            "AppVM",
            name="sys-gui",
            guivm="dom0",
            template=self.template,
            label="red",
        )
        appvm = self.app.add_new_vm(
            "AppVM", name="test-vm", template=self.template, label="red"
        )
        holder.default_guivm = "sys-gui"
        self.assertEqual(holder.default_guivm, "sys-gui")
        self.assertIsNotNone(self.app.default_guivm)
        self.assertTrue(appvm.property_is_default("guivm"))
        self.app.default_guivm = guivm
        self.assertEventFired(
            holder,
            "property-set:default_guivm",
            kwargs={"name": "default_guivm", "newvalue": "sys-gui"},
        )

        self.assertIn("guivm-sys-gui", appvm.tags)

    def test_113_guivm(self):
        class MyTestHolder(qubes.tests.TestEmitter, qubes.PropertyHolder):
            guivm = qubes.property("guivm", default=(lambda self: "dom0"))

        holder = MyTestHolder(None)
        guivm = self.app.add_new_vm(
            "AppVM",
            name="sys-gui",
            guivm="dom0",
            template=self.template,
            label="red",
        )
        vncvm = self.app.add_new_vm(
            "AppVM",
            name="sys-vnc",
            guivm="dom0",
            template=self.template,
            label="red",
        )
        appvm = self.app.add_new_vm(
            "AppVM",
            name="test-vm",
            guivm="dom0",
            template=self.template,
            label="red",
        )
        holder.guivm = "sys-gui"
        self.assertEqual(holder.guivm, "sys-gui")
        self.assertEventFired(
            holder,
            "property-set:guivm",
            kwargs={"name": "guivm", "newvalue": "sys-gui"},
        )

        # Set GuiVM
        self.assertFalse(appvm.property_is_default("guivm"))
        appvm.guivm = guivm
        self.assertIn("guivm-sys-gui", appvm.tags)

        # Change GuiVM
        appvm.guivm = vncvm
        self.assertIn("guivm-sys-vnc", appvm.tags)
        self.assertNotIn("guivm-sys-gui", appvm.tags)

        # Empty GuiVM
        del appvm.guivm
        self.assertNotIn("guivm-sys-vnc", appvm.tags)
        self.assertNotIn("guivm-sys-gui", appvm.tags)
        self.assertNotIn("guivm-", appvm.tags)

    def test_114_default_audiovm(self):
        class MyTestHolder(qubes.tests.TestEmitter, qubes.PropertyHolder):
            default_audiovm = qubes.property(
                "default_audiovm", default=(lambda self: "dom0")
            )

        holder = MyTestHolder(None)
        audiovm = self.app.add_new_vm(
            "AppVM",
            name="sys-audio",
            audiovm="dom0",
            template=self.template,
            label="red",
        )
        appvm = self.app.add_new_vm(
            "AppVM", name="test-vm", template=self.template, label="red"
        )
        holder.default_audiovm = "sys-audio"
        self.assertEqual(holder.default_audiovm, "sys-audio")
        self.assertIsNotNone(self.app.default_audiovm)
        self.assertTrue(appvm.property_is_default("audiovm"))
        self.app.default_audiovm = audiovm
        self.assertEventFired(
            holder,
            "property-set:default_audiovm",
            kwargs={"name": "default_audiovm", "newvalue": "sys-audio"},
        )

        self.assertIn("audiovm-sys-audio", appvm.tags)

    def test_115_audiovm(self):
        class MyTestHolder(qubes.tests.TestEmitter, qubes.PropertyHolder):
            audiovm = qubes.property("audiovm", default=(lambda self: "dom0"))

        holder = MyTestHolder(None)
        audiovm = self.app.add_new_vm(
            "AppVM",
            name="sys-audio",
            audiovm="dom0",
            template=self.template,
            label="red",
        )
        guivm = self.app.add_new_vm(
            "AppVM",
            name="sys-gui",
            audiovm="dom0",
            template=self.template,
            label="red",
        )
        appvm = self.app.add_new_vm(
            "AppVM",
            name="test-vm",
            audiovm="dom0",
            template=self.template,
            label="red",
        )
        holder.audiovm = "sys-audio"
        self.assertEqual(holder.audiovm, "sys-audio")

        self.assertEventFired(
            holder,
            "property-set:audiovm",
            kwargs={"name": "audiovm", "newvalue": "sys-audio"},
        )

        # Set AudioVM
        self.assertFalse(appvm.property_is_default("audiovm"))
        appvm.audiovm = audiovm
        self.assertIn("audiovm-sys-audio", appvm.tags)

        # Change AudioVM
        appvm.audiovm = guivm
        self.assertIn("audiovm-sys-gui", appvm.tags)
        self.assertNotIn("audiovm-sys-audio", appvm.tags)

        # Empty AudioVM
        del appvm.audiovm
        self.assertNotIn("audiovm-sys-gui", appvm.tags)
        self.assertNotIn("audiovm-sys-audio", appvm.tags)
        self.assertNotIn("audiovm-", appvm.tags)

    def test_116_remotevm_add_and_remove(self):
        remotevm1 = self.app.add_new_vm(
            "RemoteVM", name="remote-vm1", label="blue"
        )
        remotevm2 = self.app.add_new_vm(
            "RemoteVM", name="remote-vm2", label="gray"
        )
        qubesvm1 = self.app.add_new_vm(
            "AppVM",
            name="test-vm",
            template=self.template,
            label="red",
        )

        assert remotevm1 in self.app.domains
        del self.app.domains["remote-vm1"]

        self.assertCountEqual(
            {d.name for d in self.app.domains},
            {"dom0", "test-template", "test-vm", "remote-vm2"},
        )

    def test_117_remotevm_status(self):
        remotevm1 = self.app.add_new_vm(
            "RemoteVM", name="remote-vm1", label="blue"
        )
        assert [
            remotevm1.get_power_state(),
            remotevm1.get_cputime(),
            remotevm1.get_mem(),
        ] == ["Running", 0, 0]

    def test_200_remove_template(self):
        appvm = self.app.add_new_vm(
            "AppVM", name="test-vm", template=self.template, label="red"
        )
        with mock.patch.object(self.app, "vmm"):
            with self.assertRaises(qubes.exc.QubesException):
                del self.app.domains[self.template]

    def test_201_remove_netvm(self):
        netvm = self.app.add_new_vm(
            "AppVM",
            name="test-netvm",
            template=self.template,
            provides_network=True,
            label="red",
        )
        appvm = self.app.add_new_vm(
            "AppVM", name="test-vm", template=self.template, label="red"
        )
        appvm.netvm = netvm
        with mock.patch.object(self.app, "vmm"):
            with self.assertRaises(qubes.exc.QubesVMInUseError):
                del self.app.domains[netvm]

    def test_202_remove_default_netvm(self):
        netvm = self.app.add_new_vm(
            "AppVM",
            name="test-netvm",
            template=self.template,
            provides_network=True,
            label="red",
        )
        netvm.netvm = None
        self.app.default_netvm = netvm
        with mock.patch.object(self.app, "vmm"):
            with self.assertRaises(qubes.exc.QubesVMInUseError):
                del self.app.domains[netvm]

    def test_203_remove_default_dispvm(self):
        appvm = self.app.add_new_vm(
            "AppVM", name="test-appvm", template=self.template, label="red"
        )
        self.app.default_dispvm = appvm
        with mock.patch.object(self.app, "vmm"):
            with self.assertRaises(qubes.exc.QubesVMInUseError):
                del self.app.domains[appvm]

    def test_204_remove_appvm_dispvm(self):
        dispvm = self.app.add_new_vm(
            "AppVM", name="test-appvm", template=self.template, label="red"
        )
        appvm = self.app.add_new_vm(
            "AppVM",
            name="test-appvm2",
            template=self.template,
            default_dispvm=dispvm,
            label="red",
        )
        with mock.patch.object(self.app, "vmm"):
            with self.assertRaises(qubes.exc.QubesVMInUseError):
                del self.app.domains[dispvm]

    def test_205_remove_appvm_dispvm(self):
        appvm = self.app.add_new_vm(
            "AppVM",
            name="test-appvm",
            template=self.template,
            template_for_dispvms=True,
            label="red",
        )
        dispvm = self.app.add_new_vm(
            "DispVM", name="test-dispvm", template=appvm, label="red"
        )
        with mock.patch.object(self.app, "vmm"):
            with self.assertRaises(qubes.exc.QubesVMInUseError):
                del self.app.domains[appvm]

    def test_206_remove_attached(self):
        # See also qubes.tests.api_admin.
        vm = self.app.add_new_vm(
            "AppVM", name="test-vm", template=self.template, label="red"
        )
        assignment = mock.Mock(port_id="1234")
        vm.get_provided_assignments = lambda: [assignment]
        with self.assertRaises(qubes.exc.QubesVMInUseError):
            del self.app.domains[vm]

    def test_207_default_kernel(self):
        with self.assertRaises(qubes.exc.QubesPropertyValueError):
            # invalid path check
            self.app.default_kernel = "unittest_Evil_Maid_Kernel"
        with self.assertRaises(qubes.exc.QubesPropertyValueError):
            # vmlinuz check
            with mock.patch("os.path.exists") as existence:
                existence.side_effect = [True, False]
                self.app.default_kernel = "unittest_GNU_Hurd_1.0.0"

    @qubes.tests.skipUnlessGit
    def test_900_example_xml_in_doc(self):
        self.assertXMLIsValid(
            lxml.etree.parse(
                open(os.path.join(qubes.tests.in_git, "doc/example.xml"), "rb")
            ),
            "qubes.rng",
        )
