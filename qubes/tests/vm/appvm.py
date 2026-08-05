# -*- encoding: utf-8 -*-
#
# The Qubes OS Project, http://www.qubes-os.org
#
# Copyright (C) 2017 Marek Marczykowski-Górecki
#                               <marmarek@invisiblethingslab.com>
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

from unittest import mock

import lxml.etree

import qubes.storage
import qubes.tests
import qubes.tests.vm.qubesvm
import qubes.vm.appvm
import qubes.vm.templatevm


class TestApp:
    # pylint: disable=too-few-public-methods
    labels = {1: qubes.Label(1, "0xcc0000", "red")}

    def __init__(self):
        self.domains = {}


class TestProp:
    # pylint: disable=too-few-public-methods
    __name__ = "testprop"


class TestVM:
    # pylint: disable=too-few-public-methods
    app = TestApp()

    def __init__(self, **kwargs):
        self.running = False
        self.installed_by_rpm = False
        for k, v in kwargs.items():
            setattr(self, k, v)

    def is_running(self):
        return self.running


class TestVolume(qubes.storage.Volume):
    def create(self):  # pylint: disable=invalid-overridden-method
        pass


class TestPool(qubes.storage.Pool):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._volumes = {}

    def init_volume(self, vm, volume_config):
        vid = "{}/{}".format(vm.name, volume_config["name"])
        assert volume_config.pop("pool", None) == self
        vol = TestVolume(vid=vid, pool=self, **volume_config)
        self._volumes[vid] = vol
        return vol

    def get_volume(self, vid):
        return self._volumes[vid]


def defer_tpl(self, qube, template_alt):
    assert not qube.template == template_alt
    template_orig = qube.template
    self.assertTrue(qube.property_is_default("active_template"))

    if getattr(qube, "auto_cleanup", False):
        with mock.patch.object(qube, "get_power_state") as mock_power:
            mock_power.return_value = "Running"
            # Change active template while qube is running.
            with self.assertRaises(qubes.exc.QubesVMNotHaltedError):
                qube.template = template_alt
            return

    with mock.patch.object(qube, "get_power_state") as mock_power:
        mock_power.return_value = "Running"
        # Change active template while qube is running.
        qube.template = template_alt
        self.assertNotEqual(qube.template, qube.active_template)
        self.assertEqual(qube.template, template_alt)
        self.assertEqual(qube.active_template, template_orig)
        self.assertFalse(qube.property_is_default("active_template"))

        # Get back to original template while qube is running.
        qube.template = template_orig
        self.assertEqual(qube.template, template_orig)
        self.assertEqual(qube.template, qube.active_template)
        self.assertTrue(qube.property_is_default("active_template"))

        # Change active template again.
        qube.template = template_alt
        self.assertNotEqual(qube.template, qube.active_template)
        self.assertEqual(qube.template, template_alt)
        self.assertEqual(qube.active_template, template_orig)
        self.assertFalse(qube.property_is_default("active_template"))

    with mock.patch.object(qube, "get_power_state") as mock_power:
        mock_power.return_value = "Halted"
        qubes.vm.appvm.apply_deferred_template(qube)
        self.assertEqual(qube.template, template_alt)
        self.assertEqual(qube.template, qube.active_template)
        self.assertTrue(qube.property_is_default("active_template"))

    with mock.patch.object(
        qubes.vm.appvm, "template_changed_update_storage"
    ) as mock_storage:
        with mock.patch.object(qube, "is_halted", return_value=False):
            qubes.vm.appvm.apply_deferred_template(qube)
            mock_storage.assert_not_called()
        with mock.patch.object(qube, "is_halted", return_value=True):
            self.assertEqual(qube.template, qube.active_template)
            qubes.vm.appvm.apply_deferred_template(qube)
            mock_storage.assert_not_called()

    with mock.patch.object(qube, "get_power_state") as mock_power:
        mock_power.return_value = "Running"
        # Change active template while qube is running.
        qube.template = template_orig
        self.assertNotEqual(qube.template, qube.active_template)
        self.assertEqual(qube.template, template_orig)
        self.assertEqual(qube.active_template, template_alt)
        self.assertFalse(qube.property_is_default("active_template"))

        with mock.patch.object(
            qubes.vm.appvm, "apply_deferred_template"
        ) as mock_apply:
            qube.fire_event("domain-load")
            mock_apply.assert_called_once_with(qube)
            mock_apply.reset_mock()


class TC_90_AppVM(
    qubes.tests.vm.qubesvm.QubesVMTestsMixin, qubes.tests.QubesTestCase
):
    def setUp(self):
        super().setUp()
        self.app.pools["default"] = TestPool(name="default")
        self.app.pools["linux-kernel"] = mock.Mock(
            **{"init_volume.return_value.pool": "linux-kernel"}
        )
        self.template = qubes.vm.templatevm.TemplateVM(
            self.app, None, qid=1, name=qubes.tests.VMPREFIX + "template"
        )
        self.template_alt = qubes.vm.templatevm.TemplateVM(
            self.app, None, qid=20, name=qubes.tests.VMPREFIX + "template-alt"
        )

        for template in [self.template, self.template_alt]:
            self.app.domains[template.name] = template
            self.app.domains[template] = template
        self.addCleanup(self.cleanup_appvm)

    def cleanup_appvm(self):
        self.template.close()
        self.template_alt.close()
        del self.template
        del self.template_alt
        self.app.domains.clear()
        self.app.pools.clear()

    def get_vm(self, *_args, **kwargs):
        vm = qubes.vm.appvm.AppVM(
            self.app,
            None,
            qid=2,
            name=qubes.tests.VMPREFIX + "test",
            template=self.template,
            **kwargs
        )
        self.addCleanup(vm.close)
        return vm

    def test_000_init(self):
        self.get_vm()

    def test_001_storage_init(self):
        vm = self.get_vm()
        self.assertTrue(vm.volume_config["private"]["save_on_stop"])
        self.assertFalse(vm.volume_config["private"]["snap_on_start"])
        self.assertIsNone(vm.volume_config["private"].get("source", None))

        self.assertFalse(vm.volume_config["root"]["save_on_stop"])
        self.assertTrue(vm.volume_config["root"]["snap_on_start"])
        self.assertEqual(
            vm.volume_config["root"].get("source", None),
            self.template.volumes["root"],
        )

        self.assertFalse(
            vm.volume_config["volatile"].get("save_on_stop", False)
        )
        self.assertFalse(
            vm.volume_config["volatile"].get("snap_on_start", False)
        )
        self.assertIsNone(vm.volume_config["volatile"].get("source", None))

    def test_002_storage_template_change(self):
        vm = self.get_vm()
        # create new mock, so new template will get different volumes
        self.app.pools["default"] = mock.Mock(
            **{"init_volume.return_value.pool": "default"}
        )
        template2 = qubes.vm.templatevm.TemplateVM(
            self.app, None, qid=3, name=qubes.tests.VMPREFIX + "template2"
        )
        self.app.domains[template2.name] = template2
        self.app.domains[template2] = template2

        vm.template = template2
        self.assertFalse(vm.volume_config["root"]["save_on_stop"])
        self.assertTrue(vm.volume_config["root"]["snap_on_start"])
        self.assertNotEqual(
            vm.volume_config["root"].get("source", None),
            self.template.volumes["root"].source,
        )
        self.assertEqual(
            vm.volume_config["root"].get("source", None),
            template2.volumes["root"],
        )

    def test_003_template_change_running(self):
        vm = self.get_vm()
        self.assertEqual(vm.template, self.template)
        self.assertEqual(vm.template, vm.active_template)
        defer_tpl(self=self, qube=vm, template_alt=self.template_alt)

    def test_004_template_reset(self):
        vm = self.get_vm()
        with self.assertRaises(qubes.exc.QubesValueError):
            vm.template = qubes.property.DEFAULT
        self.app.default_template = self.template
        with self.assertRaises(qubes.exc.QubesValueError):
            vm.template = qubes.property.DEFAULT
        del self.app.default_template

    def test_500_property_migrate_template_for_dispvms(self):
        xml_template = """
        <domain class="AppVM" id="domain-1">
            <properties>
                <property name="qid">1</property>
                <property name="name">testvm</property>
                <property name="label" ref="label-1" />
                <property name="dispvm_allowed">{value}</property>
            </properties>
        </domain>
        """
        xml = lxml.etree.XML(xml_template.format(value="True"))
        vm = qubes.vm.appvm.AppVM(self.app, xml)
        self.assertEqual(vm.template_for_dispvms, True)
        with self.assertRaises(AttributeError):
            vm.dispvm_allowed  # pylint: disable=no-member,pointless-statement

        xml = lxml.etree.XML(xml_template.format(value="False"))
        vm = qubes.vm.appvm.AppVM(self.app, xml)
        self.assertEqual(vm.template_for_dispvms, False)
        with self.assertRaises(AttributeError):
            vm.dispvm_allowed  # pylint: disable=no-member,pointless-statement

    def test_600_load_volume_config(self):
        xml_template = """
        <domain class="AppVM" id="domain-1">
            <properties>
                <property name="qid">1</property>
                <property name="name">testvm</property>
                <property name="label" ref="label-1" />
            </properties>
            <volume-config>
                <volume name="root" pool="lvm" revisions_to_keep="3" rw="True"
                        size="1234" vid="qubes_dom0/vm-testvm-root" />
            </volume-config>
        </domain>
        """
        xml = lxml.etree.XML(xml_template)
        vm = qubes.vm.appvm.AppVM(self.app, xml)
        self.assertEqual(vm.volume_config["root"]["revisions_to_keep"], "3")
        self.assertEqual(vm.volume_config["root"]["rw"], True)
        self.assertEqual(vm.volume_config["root"]["size"], "1234")
        self.assertEqual(
            vm.volume_config["root"]["vid"], "qubes_dom0/vm-testvm-root"
        )
