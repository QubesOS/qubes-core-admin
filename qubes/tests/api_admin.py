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

"""Tests for management calls endpoints"""

import asyncio
import operator
import os
import re
import shutil
import tempfile
import unittest.mock
import uuid

import libvirt
import copy

import pathlib

import qubes
import qubes.devices
import qubes.exc
import qubes.firewall
import qubes.api.admin
import qubes.api.internal
import qubes.tests
import qubes.storage

from qubes.device_protocol import (
    DeviceInfo,
    VirtualDevice,
    Port,
    DeviceAssignment,
)

# properties defined in API
volume_properties = [
    "pool",
    "vid",
    "size",
    "usage",
    "rw",
    "source",
    "path",
    "save_on_stop",
    "snap_on_start",
    "revisions_to_keep",
    "ephemeral",
]

_uuid_regex = re.compile(
    r"\Auuid:[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\Z"
)


class AdminAPITestCase(qubes.tests.QubesTestCase):
    def setUp(self):
        super().setUp()
        self.test_base_dir = "/tmp/qubes-test-dir"
        self.base_dir_patch = unittest.mock.patch.dict(
            qubes.config.system_path, {"qubes_base_dir": self.test_base_dir}
        )
        self.base_dir_patch2 = unittest.mock.patch(
            "qubes.config.qubes_base_dir", self.test_base_dir
        )
        self.base_dir_patch3 = unittest.mock.patch.dict(
            qubes.config.defaults["pool_configs"]["varlibqubes"],
            {"dir_path": self.test_base_dir},
        )
        self.skip_kernel_validation_patch = unittest.mock.patch(
            "qubes.app.validate_kernel", lambda obj, key, value: None
        )
        self.base_dir_patch.start()
        self.base_dir_patch2.start()
        self.base_dir_patch3.start()
        self.skip_kernel_validation_patch.start()
        app = qubes.Qubes("/tmp/qubes-test.xml", load=False)
        app.vmm = unittest.mock.Mock(spec=qubes.app.VMMConnection)
        app.load_initial_values()
        self.loop.run_until_complete(app.setup_pools())
        app.default_kernel = "1.0"
        app.default_netvm = None
        self.template = app.add_new_vm(
            "TemplateVM", label="black", name="test-template"
        )
        app.default_template = "test-template"
        with qubes.tests.substitute_entry_points(
            "qubes.storage", "qubes.tests.storage"
        ):
            self.loop.run_until_complete(app.add_pool("test", driver="test"))
        app.default_pool = "varlibqubes"
        app.save = unittest.mock.Mock()
        self.vm = app.add_new_vm(
            "AppVM", label="red", name="test-vm1", template="test-template"
        )
        self.uuid = b"uuid:" + str(self.vm.uuid).encode("ascii", "strict")
        self.app = app
        libvirt_attrs = {
            "libvirt_conn.lookupByUUID.return_value.isActive.return_value": False,
            "libvirt_conn.lookupByUUID.return_value.state.return_value": [
                libvirt.VIR_DOMAIN_SHUTOFF
            ],
        }
        app.vmm.configure_mock(**libvirt_attrs)

        self.emitter = qubes.tests.TestEmitter()
        self.app.domains[0].fire_event = self.emitter.fire_event

    def tearDown(self):
        self.base_dir_patch3.stop()
        self.base_dir_patch2.stop()
        self.base_dir_patch.stop()
        if os.path.exists(self.test_base_dir):
            shutil.rmtree(self.test_base_dir)
        try:
            del self.netvm
        except AttributeError:
            pass
        del self.vm
        del self.template
        self.app.close()
        del self.app
        del self.emitter
        super(AdminAPITestCase, self).tearDown()

    def call_mgmt_func(self, method, dest, arg=b"", payload=b""):
        mgmt_obj = qubes.api.admin.QubesAdminAPI(
            self.app, b"dom0", method, dest, arg
        )

        loop = asyncio.get_event_loop()
        response = loop.run_until_complete(
            mgmt_obj.execute(untrusted_payload=payload)
        )
        self.assertEventFired(
            self.emitter, "admin-permission:" + method.decode("ascii")
        )
        return response

    def call_internal_mgmt_func(self, method, dest, arg=b"", payload=b""):
        mgmt_obj = qubes.api.internal.QubesInternalAPI(
            self.app, b"dom0", method, dest, arg
        )
        loop = asyncio.get_event_loop()
        response = loop.run_until_complete(
            mgmt_obj.execute(untrusted_payload=payload)
        )
        return response


# noinspection PyUnresolvedReferences
class TC_00_VMs(AdminAPITestCase):
    def _test_event_handler(
        self, vm, event, *args, **kwargs
    ):  # pylint: disable=unused-argument
        if not hasattr(self, "event_handler"):
            self.event_handler = {}
        self.event_handler.setdefault(vm.name, {})[event] = True

    def _test_event_was_handled(self, vm, event):
        if not hasattr(self, "event_handler"):
            self.event_handler = {}
        return self.event_handler.get(vm, {}).get(event)

    def test_000_vm_list(self):
        value = self.call_mgmt_func(b"admin.vm.List", b"dom0")
        self.assertEqual(
            value,
            "dom0 class=AdminVM state=Running "
            "uuid=00000000-0000-0000-0000-000000000000\n"
            "test-template class=TemplateVM state=Halted "
            f"uuid={self.template.uuid}\n"
            f"test-vm1 class=AppVM state=Halted uuid={self.vm.uuid}\n",
        )

    def test_001_vm_list_single(self):
        value = self.call_mgmt_func(b"admin.vm.List", b"test-vm1")
        self.assertEqual(
            value, f"test-vm1 class=AppVM state=Halted uuid={self.vm.uuid}\n"
        )

    def test_001_vm_list_single_uuid(self):
        value = self.call_mgmt_func(b"admin.vm.List", self.uuid)
        self.assertEqual(
            value, f"test-vm1 class=AppVM state=Halted uuid={self.vm.uuid}\n"
        )

    def test_001_vm_list_single_invalid_name(self):
        with self.assertRaisesRegex(
            qubes.exc.QubesValueError,
            r"\AVM name cannot start with hyphen, underscore, dot or numbers\Z",
        ):
            self.call_mgmt_func(b"admin.vm.CreateDisposable", b".test-vm1")
        self.assertFalse(self.app.save.called)

    def test_001_vm_list_single_invalid_uuid(self):
        with self.assertRaisesRegex(
            qubes.exc.QubesVMInvalidUUIDError, r"\AVM UUID is not valid: ''\Z"
        ):
            self.call_mgmt_func(b"admin.vm.CreateDisposable", b"uuid:")
        self.assertFalse(self.app.save.called)

    def test_002_vm_list_filter(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = pathlib.Path(tmpdir)
            with unittest.mock.patch(
                "qubes.ext.admin.AdminExtension._instance.policy_cache.paths",
                [pathlib.Path(tmpdir)],
            ):
                with (tmpdir / "admin.policy").open("w") as f:
                    f.write("admin.vm.List * @anyvm @adminvm allow\n")
                    f.write("admin.vm.List * @anyvm test-vm1 allow")
                mgmt_obj = qubes.api.admin.QubesAdminAPI(
                    self.app, b"test-vm1", b"admin.vm.List", b"dom0", b""
                )
                loop = asyncio.get_event_loop()
                value = loop.run_until_complete(
                    mgmt_obj.execute(untrusted_payload=b"")
                )
                self.assertEqual(
                    value,
                    "dom0 class=AdminVM state=Running "
                    "uuid=00000000-0000-0000-0000-000000000000\n"
                    f"test-vm1 class=AppVM state=Halted uuid={self.vm.uuid}\n",
                )

    def test_010_vm_property_list(self):
        # this test is kind of stupid, but at least check if appropriate
        # admin-permission event is fired
        value = self.call_mgmt_func(b"admin.vm.property.List", b"test-vm1")
        properties = self.app.domains["test-vm1"].property_list()
        self.assertEqual(
            value, "".join("{}\n".format(prop.__name__) for prop in properties)
        )

    def test_020_vm_property_get_str(self):
        value = self.call_mgmt_func(
            b"admin.vm.property.Get", b"test-vm1", b"name"
        )
        self.assertEqual(value, "default=False type=str test-vm1")

    def test_021_vm_property_get_int(self):
        value = self.call_mgmt_func(
            b"admin.vm.property.Get", b"test-vm1", b"vcpus"
        )
        self.assertEqual(value, "default=True type=int 2")
        # check also if type is preserved on stateless property
        value = self.call_mgmt_func(
            b"admin.vm.property.Get", b"test-vm1", b"xid"
        )
        self.assertEqual(value, "default=True type=int -1")

    def test_022_vm_property_get_bool(self):
        value = self.call_mgmt_func(
            b"admin.vm.property.Get", b"test-vm1", b"provides_network"
        )
        self.assertEqual(value, "default=True type=bool False")

    def test_023_vm_property_get_label(self):
        value = self.call_mgmt_func(
            b"admin.vm.property.Get", b"test-vm1", b"label"
        )
        self.assertEqual(value, "default=False type=label red")

    def test_024_vm_property_get_vm(self):
        value = self.call_mgmt_func(
            b"admin.vm.property.Get", b"test-vm1", b"template"
        )
        self.assertEqual(value, "default=False type=vm test-template")

    def test_025_vm_property_get_vm_none(self):
        value = self.call_mgmt_func(
            b"admin.vm.property.Get", b"test-vm1", b"netvm"
        )
        self.assertEqual(value, "default=True type=vm ")

    def test_025_vm_property_get_default_vm_none(self):
        value = self.call_mgmt_func(
            b"admin.vm.property.GetDefault", b"test-vm1", b"template"
        )
        self.assertEqual(value, None)

    def test_026_vm_property_get_default_bool(self):
        self.vm.provides_network = True
        value = self.call_mgmt_func(
            b"admin.vm.property.GetDefault", b"test-vm1", b"provides_network"
        )
        self.assertEqual(value, "type=bool False")

    def test_027_vm_property_get_all(self):
        # any string property, test \n encoding
        self.vm.kernelopts = "opt1\nopt2\nopt3\\opt4"
        # let it have 'dns' property
        self.vm.provides_network = True
        with unittest.mock.patch.object(self.vm, "property_list") as list_mock:
            list_mock.return_value = [
                self.vm.property_get_def("name"),
                self.vm.property_get_def("default_user"),
                self.vm.property_get_def("netvm"),
                self.vm.property_get_def("klass"),
                self.vm.property_get_def("debug"),
                self.vm.property_get_def("label"),
                self.vm.property_get_def("kernelopts"),
                self.vm.property_get_def("qrexec_timeout"),
                self.vm.property_get_def("qid"),
                self.vm.property_get_def("updateable"),
                self.vm.property_get_def("dns"),
            ]
            value = self.call_mgmt_func(
                b"admin.vm.property.GetAll", b"test-vm1"
            )
        self.maxDiff = None
        expected = """debug default=True type=bool False
default_user default=True type=str user
dns default=True type=str 10.139.1.1 10.139.1.2
klass default=True type=str AppVM
label default=False type=label red
name default=False type=str test-vm1
qid default=False type=int 2
qrexec_timeout default=True type=int 60
updateable default=True type=bool False
kernelopts default=False type=str opt1\\nopt2\\nopt3\\\\opt4
netvm default=True type=vm \n"""
        self.assertEqual(value, expected)

    def test_028_vm_property_get_list(self):
        self.vm.provides_network = True
        value = self.call_mgmt_func(
            b"admin.vm.property.Get", b"test-vm1", b"dns"
        )
        self.assertEqual(value, "default=True type=str 10.139.1.1 10.139.1.2")

    def test_029_vm_property_get_list_none(self):
        value = self.call_mgmt_func(
            b"admin.vm.property.Get", b"test-vm1", b"dns"
        )
        self.assertEqual(value, "default=True type=str ")

    def test_029_vm_property_get_list_default(self):
        self.vm.provides_network = True
        value = self.call_mgmt_func(
            b"admin.vm.property.GetDefault", b"test-vm1", b"dns"
        )
        self.assertEqual(value, "type=str 10.139.1.1 10.139.1.2")

    def test_030_vm_property_set_vm(self):
        netvm = self.app.add_new_vm(
            "AppVM",
            label="red",
            name="test-net",
            template="test-template",
            provides_network=True,
        )

        with unittest.mock.patch("qubes.vm.VMProperty.__set__") as mock:
            value = self.call_mgmt_func(
                b"admin.vm.property.Set", b"test-vm1", b"netvm", b"test-net"
            )
            self.assertIsNone(value)
            mock.assert_called_once_with(self.vm, "test-net")
        self.app.save.assert_called_once_with()

    def test_031_vm_property_set_vm_none(self):
        netvm = self.app.add_new_vm(
            "AppVM",
            label="red",
            name="test-net",
            template="test-template",
            provides_network=True,
        )

        with unittest.mock.patch("qubes.vm.VMProperty.__set__") as mock:
            value = self.call_mgmt_func(
                b"admin.vm.property.Set", b"test-vm1", b"netvm", b""
            )
            self.assertIsNone(value)
            mock.assert_called_once_with(self.vm, "")
        self.app.save.assert_called_once_with()

    def test_032_vm_property_set_vm_invalid1(self):
        with unittest.mock.patch("qubes.vm.VMProperty.__set__") as mock:
            with self.assertRaises(qubes.exc.QubesValueError):
                self.call_mgmt_func(
                    b"admin.vm.property.Set",
                    b"test-vm1",
                    b"netvm",
                    b"forbidden-chars/../!",
                )
            self.assertFalse(mock.called)
        self.assertFalse(self.app.save.called)

    def test_033_vm_property_set_vm_invalid2(self):
        with unittest.mock.patch("qubes.vm.VMProperty.__set__") as mock:
            with self.assertRaises(qubes.exc.QubesValueError):
                self.call_mgmt_func(
                    b"admin.vm.property.Set",
                    b"test-vm1",
                    b"netvm",
                    b"\x80\x90\xa0",
                )
            self.assertFalse(mock.called)
        self.assertFalse(self.app.save.called)

    def test_034_vm_propert_set_bool_true(self):
        with unittest.mock.patch("qubes.property.__set__") as mock:
            value = self.call_mgmt_func(
                b"admin.vm.property.Set", b"test-vm1", b"autostart", b"True"
            )
            self.assertIsNone(value)
            mock.assert_called_once_with(self.vm, True)
        self.app.save.assert_called_once_with()

    def test_035_vm_propert_set_bool_false(self):
        with unittest.mock.patch("qubes.property.__set__") as mock:
            value = self.call_mgmt_func(
                b"admin.vm.property.Set", b"test-vm1", b"autostart", b"False"
            )
            self.assertIsNone(value)
            mock.assert_called_once_with(self.vm, False)
        self.app.save.assert_called_once_with()

    def test_036_vm_propert_set_bool_invalid1(self):
        with unittest.mock.patch("qubes.property.__set__") as mock:
            with self.assertRaises(qubes.exc.QubesValueError):
                self.call_mgmt_func(
                    b"admin.vm.property.Set",
                    b"test-vm1",
                    b"autostart",
                    b"some string",
                )
            self.assertFalse(mock.called)
        self.assertFalse(self.app.save.called)

    def test_037_vm_propert_set_bool_invalid2(self):
        with unittest.mock.patch("qubes.property.__set__") as mock:
            with self.assertRaises(qubes.exc.QubesValueError):
                self.call_mgmt_func(
                    b"admin.vm.property.Set",
                    b"test-vm1",
                    b"autostart",
                    b"\x80\x90@#$%^&*(",
                )
            self.assertFalse(mock.called)
        self.assertFalse(self.app.save.called)

    def test_038_vm_propert_set_str(self):
        with unittest.mock.patch("qubes.property.__set__") as mock:
            value = self.call_mgmt_func(
                b"admin.vm.property.Set", b"test-vm1", b"kernel", b"1.0"
            )
            self.assertIsNone(value)
            mock.assert_called_once_with(self.vm, "1.0")
        self.app.save.assert_called_once_with()

    def test_039_vm_propert_set_str_invalid1(self):
        with unittest.mock.patch("qubes.property.__set__") as mock:
            with self.assertRaises(qubes.exc.QubesValueError):
                self.call_mgmt_func(
                    b"admin.vm.property.Set",
                    b"test-vm1",
                    b"kernel",
                    b"some, non-ASCII: \x80\xd2",
                )
            self.assertFalse(mock.called)
        self.assertFalse(self.app.save.called)

    def test_040_vm_propert_set_int(self):
        with unittest.mock.patch("qubes.property.__set__") as mock:
            value = self.call_mgmt_func(
                b"admin.vm.property.Set", b"test-vm1", b"maxmem", b"1024000"
            )
            self.assertIsNone(value)
            mock.assert_called_once_with(self.vm, 1024000)
        self.app.save.assert_called_once_with()

    def test_041_vm_propert_set_int_invalid1(self):
        with unittest.mock.patch("qubes.property.__set__") as mock:
            with self.assertRaises(qubes.exc.QubesValueError):
                self.call_mgmt_func(
                    b"admin.vm.property.Set",
                    b"test-vm1",
                    b"maxmem",
                    b"fourty two",
                )
            self.assertFalse(mock.called)
        self.assertFalse(self.app.save.called)

    def test_042_vm_propert_set_label(self):
        with unittest.mock.patch("qubes.property.__set__") as mock:
            value = self.call_mgmt_func(
                b"admin.vm.property.Set", b"test-vm1", b"label", b"green"
            )
            self.assertIsNone(value)
            mock.assert_called_once_with(self.vm, "green")
        self.app.save.assert_called_once_with()

    def test_043_vm_propert_set_label_invalid1(self):
        with unittest.mock.patch("qubes.property.__set__") as mock:
            with self.assertRaises(qubes.exc.QubesValueError):
                self.call_mgmt_func(
                    b"admin.vm.property.Set",
                    b"test-vm1",
                    b"maxmem",
                    b"some, non-ASCII: \x80\xd2",
                )
            self.assertFalse(mock.called)
        self.assertFalse(self.app.save.called)

    @unittest.skip("label existence not checked before actual setter yet")
    def test_044_vm_propert_set_label_invalid2(self):
        with unittest.mock.patch("qubes.property.__set__") as mock:
            with self.assertRaises(qubes.exc.QubesValueError):
                self.call_mgmt_func(
                    b"admin.vm.property.Set",
                    b"test-vm1",
                    b"maxmem",
                    b"non-existing-color",
                )
            self.assertFalse(mock.called)
        self.assertFalse(self.app.save.called)

    def test_050_vm_property_help(self):
        value = self.call_mgmt_func(
            b"admin.vm.property.Help", b"test-vm1", b"label"
        )
        self.assertEqual(
            value,
            "Colourful label assigned to VM. This is where the colour of the "
            "padlock is set.",
        )
        self.assertFalse(self.app.save.called)

    def test_052_vm_property_help_invalid_property(self):
        with self.assertRaises(qubes.exc.QubesNoSuchPropertyError):
            self.call_mgmt_func(
                b"admin.vm.property.Help", b"test-vm1", b"no-such-property"
            )

        self.assertFalse(self.app.save.called)

    def test_060_vm_property_reset(self):
        with unittest.mock.patch("qubes.property.__delete__") as mock:
            value = self.call_mgmt_func(
                b"admin.vm.property.Reset", b"test-vm1", b"default_user"
            )
            mock.assert_called_with(self.vm)
        self.assertIsNone(value)
        self.app.save.assert_called_once_with()

    def test_062_vm_property_reset_invalid_property(self):
        with unittest.mock.patch("qubes.property.__delete__") as mock:
            with self.assertRaises(qubes.exc.QubesNoSuchPropertyError):
                self.call_mgmt_func(
                    b"admin.vm.property.Help", b"test-vm1", b"no-such-property"
                )
            self.assertFalse(mock.called)
        self.assertFalse(self.app.save.called)

    def test_070_vm_volume_list(self):
        self.vm.volumes = unittest.mock.Mock()
        volumes_conf = {
            "keys.return_value": ["root", "private", "volatile", "kernel"]
        }
        self.vm.volumes.configure_mock(**volumes_conf)
        value = self.call_mgmt_func(b"admin.vm.volume.List", b"test-vm1")
        self.assertEqual(value, "root\nprivate\nvolatile\nkernel\n")
        # check if _only_ keys were accessed
        self.assertEqual(
            self.vm.volumes.mock_calls, [unittest.mock.call.keys()]
        )

    def test_080_vm_volume_info(self):
        self.vm.volumes = unittest.mock.MagicMock()
        volumes_conf = {
            "keys.return_value": ["root", "private", "volatile", "kernel"]
        }
        for prop in volume_properties:
            volumes_conf["__getitem__.return_value.{}".format(prop)] = (
                prop + "-value"
            )
        volumes_conf["__getitem__.return_value.is_outdated.return_value"] = (
            False
        )
        self.vm.volumes.configure_mock(**volumes_conf)
        value = self.call_mgmt_func(
            b"admin.vm.volume.Info", b"test-vm1", b"private"
        )
        self.assertEqual(
            value,
            "".join("{p}={p}-value\n".format(p=p) for p in volume_properties)
            + "is_outdated=False\n",
        )
        self.assertEqual(
            self.vm.volumes.mock_calls,
            [
                unittest.mock.call.keys(),
                unittest.mock.call.__getattr__("__getitem__")("private"),
                unittest.mock.call.__getattr__("__getitem__")().is_outdated(),
            ],
        )

    def test_081_vm_volume_info_unsupported_is_outdated(self):
        self.vm.volumes = unittest.mock.MagicMock()
        volumes_conf = {
            "keys.return_value": ["root", "private", "volatile", "kernel"]
        }
        for prop in volume_properties:
            volumes_conf["__getitem__.return_value.{}".format(prop)] = (
                prop + "-value"
            )
        volumes_conf["__getitem__.return_value.is_outdated.side_effect"] = (
            NotImplementedError
        )
        self.vm.volumes.configure_mock(**volumes_conf)
        value = self.call_mgmt_func(
            b"admin.vm.volume.Info", b"test-vm1", b"private"
        )
        self.assertEqual(
            value,
            "".join("{p}={p}-value\n".format(p=p) for p in volume_properties),
        )
        self.assertEqual(
            self.vm.volumes.mock_calls,
            [
                unittest.mock.call.keys(),
                unittest.mock.call.__getattr__("__getitem__")("private"),
                unittest.mock.call.__getattr__("__getitem__")().is_outdated(),
            ],
        )

    def test_080_vm_volume_info_invalid_volume(self):
        self.vm.volumes = unittest.mock.MagicMock()
        volumes_conf = {
            "keys.return_value": ["root", "private", "volatile", "kernel"]
        }
        self.vm.volumes.configure_mock(**volumes_conf)
        with self.assertRaises(qubes.exc.PermissionDenied):
            self.call_mgmt_func(
                b"admin.vm.volume.Info", b"test-vm1", b"no-such-volume"
            )
        self.assertEqual(
            self.vm.volumes.mock_calls, [unittest.mock.call.keys()]
        )

    def test_090_vm_volume_listsnapshots(self):
        self.vm.volumes = unittest.mock.MagicMock()
        volumes_conf = {
            "keys.return_value": ["root", "private", "volatile", "kernel"],
            "__getitem__.return_value.revisions": {
                "rev2": "2018-02-22T22:22:22",
                "rev1": "2018-01-11T11:11:11",
            },
        }
        self.vm.volumes.configure_mock(**volumes_conf)
        value = self.call_mgmt_func(
            b"admin.vm.volume.ListSnapshots", b"test-vm1", b"private"
        )
        self.assertEqual(value, "rev1\nrev2\n")
        self.assertEqual(
            self.vm.volumes.mock_calls,
            [
                unittest.mock.call.keys(),
                unittest.mock.call.__getattr__("__getitem__")("private"),
            ],
        )

    def test_090_vm_volume_listsnapshots_invalid_volume(self):
        self.vm.volumes = unittest.mock.MagicMock()
        volumes_conf = {
            "keys.return_value": ["root", "private", "volatile", "kernel"]
        }
        self.vm.volumes.configure_mock(**volumes_conf)
        with self.assertRaises(qubes.exc.PermissionDenied):
            self.call_mgmt_func(
                b"admin.vm.volume.ListSnapshots",
                b"test-vm1",
                b"no-such-volume",
            )
        self.assertEqual(
            self.vm.volumes.mock_calls, [unittest.mock.call.keys()]
        )

    @unittest.skip("method not implemented yet")
    def test_100_vm_volume_snapshot(self):
        pass

    @unittest.skip("method not implemented yet")
    def test_100_vm_volume_snapshot_invalid_volume(self):
        self.vm.volumes = unittest.mock.MagicMock()
        volumes_conf = {
            "keys.return_value": ["root", "private", "volatile", "kernel"],
            "__getitem__.return_value.revisions": {
                "rev2": "2018-02-22T22:22:22",
                "rev1": "2018-01-11T11:11:11",
            },
        }
        self.vm.volumes.configure_mock(**volumes_conf)
        with self.assertRaises(qubes.exc.PermissionDenied):
            self.call_mgmt_func(
                b"admin.vm.volume.Snapshots", b"test-vm1", b"no-such-volume"
            )
        self.assertEqual(
            self.vm.volumes.mock_calls, [unittest.mock.call.keys()]
        )

    @unittest.skip("method not implemented yet")
    def test_100_vm_volume_snapshot_invalid_revision(self):
        self.vm.volumes = unittest.mock.MagicMock()
        volumes_conf = {
            "keys.return_value": ["root", "private", "volatile", "kernel"]
        }
        self.vm.volumes.configure_mock(**volumes_conf)
        with self.assertRaises(qubes.exc.PermissionDenied):
            self.call_mgmt_func(
                b"admin.vm.volume.Snapshots",
                b"test-vm1",
                b"private",
                b"no-such-rev",
            )
        self.assertEqual(
            self.vm.volumes.mock_calls,
            [
                unittest.mock.call.keys(),
                unittest.mock.call.__getattr__("__getitem__")("private"),
            ],
        )

    def test_110_vm_volume_revert(self):
        self.vm.volumes = unittest.mock.MagicMock()
        volumes_conf = {
            "keys.return_value": ["root", "private", "volatile", "kernel"],
            "__getitem__.return_value.revisions": {
                "rev2": "2018-02-22T22:22:22",
                "rev1": "2018-01-11T11:11:11",
            },
        }
        self.vm.volumes.configure_mock(**volumes_conf)
        del self.vm.volumes["private"].revert("rev1")._is_coroutine
        self.vm.storage = unittest.mock.Mock()
        value = self.call_mgmt_func(
            b"admin.vm.volume.Revert", b"test-vm1", b"private", b"rev1"
        )
        self.assertIsNone(value)
        self.assertEqual(
            self.vm.volumes.mock_calls,
            [
                ("__getitem__", ("private",), {}),
                ("__getitem__().revert", ("rev1",), {}),
                ("keys", (), {}),
                ("__getitem__", ("private",), {}),
                ("__getitem__().__hash__", (), {}),
                ("__getitem__().revert", ("rev1",), {}),
            ],
        )
        self.assertEqual(self.vm.storage.mock_calls, [])

    def test_110_vm_volume_revert_invalid_rev(self):
        self.vm.volumes = unittest.mock.MagicMock()
        volumes_conf = {
            "keys.return_value": ["root", "private", "volatile", "kernel"],
            "__getitem__.return_value.revisions": {
                "rev2": "2018-02-22T22:22:22",
                "rev1": "2018-01-11T11:11:11",
            },
        }
        self.vm.volumes.configure_mock(**volumes_conf)
        self.vm.storage = unittest.mock.Mock()
        with self.assertRaises(qubes.exc.PermissionDenied):
            self.call_mgmt_func(
                b"admin.vm.volume.Revert",
                b"test-vm1",
                b"private",
                b"no-such-rev",
            )
        self.assertEqual(
            self.vm.volumes.mock_calls,
            [
                unittest.mock.call.keys(),
                unittest.mock.call.__getattr__("__getitem__")("private"),
            ],
        )
        self.assertFalse(self.vm.storage.called)

    def test_120_vm_volume_resize(self):
        self.vm.volumes = unittest.mock.MagicMock()
        volumes_conf = {
            "keys.return_value": ["root", "private", "volatile", "kernel"],
        }
        self.vm.volumes.configure_mock(**volumes_conf)
        self.vm.storage = unittest.mock.Mock()
        self.vm.storage.resize.side_effect = self.dummy_coro
        value = self.call_mgmt_func(
            b"admin.vm.volume.Resize", b"test-vm1", b"private", b"1024000000"
        )
        self.assertIsNone(value)
        self.assertEqual(
            self.vm.volumes.mock_calls, [unittest.mock.call.keys()]
        )
        self.assertEqual(
            self.vm.storage.mock_calls,
            [unittest.mock.call.resize("private", 1024000000)],
        )

    def test_120_vm_volume_resize_zero(self):
        self.vm.volumes = unittest.mock.MagicMock()
        volumes_conf = {
            "keys.return_value": ["root", "private", "volatile", "kernel"],
        }
        self.vm.volumes.configure_mock(**volumes_conf)
        self.vm.storage = unittest.mock.Mock()
        self.vm.storage.resize.side_effect = self.dummy_coro
        value = self.call_mgmt_func(
            b"admin.vm.volume.Resize", b"test-vm1", b"private", b"0"
        )
        self.assertIsNone(value)
        self.assertEqual(
            self.vm.volumes.mock_calls, [unittest.mock.call.keys()]
        )
        self.assertEqual(
            self.vm.storage.mock_calls,
            [unittest.mock.call.resize("private", 0)],
        )

    def test_120_vm_volume_resize_invalid_size1(self):
        self.vm.volumes = unittest.mock.MagicMock()
        volumes_conf = {
            "keys.return_value": ["root", "private", "volatile", "kernel"],
        }
        self.vm.volumes.configure_mock(**volumes_conf)
        self.vm.storage = unittest.mock.Mock()
        self.vm.storage.resize.side_effect = self.dummy_coro
        with self.assertRaises(qubes.exc.ProtocolError):
            self.call_mgmt_func(
                b"admin.vm.volume.Resize",
                b"test-vm1",
                b"private",
                b"no-int-size",
            )
        self.assertEqual(
            self.vm.volumes.mock_calls, [unittest.mock.call.keys()]
        )
        self.assertFalse(self.vm.storage.called)

    def test_120_vm_volume_resize_invalid_size2(self):
        self.vm.volumes = unittest.mock.MagicMock()
        volumes_conf = {
            "keys.return_value": ["root", "private", "volatile", "kernel"],
        }
        self.vm.volumes.configure_mock(**volumes_conf)
        self.vm.storage = unittest.mock.Mock()
        self.vm.storage.resize.side_effect = self.dummy_coro
        with self.assertRaises(qubes.exc.ProtocolError):
            self.call_mgmt_func(
                b"admin.vm.volume.Resize", b"test-vm1", b"private", b"-1"
            )
        self.assertEqual(
            self.vm.volumes.mock_calls, [unittest.mock.call.keys()]
        )
        self.assertFalse(self.vm.storage.called)

    def test_120_vm_volume_resize_invalid_size3(self):
        self.vm.volumes = unittest.mock.MagicMock()
        volumes_conf = {
            "keys.return_value": ["root", "private", "volatile", "kernel"],
        }
        self.vm.volumes.configure_mock(**volumes_conf)
        self.vm.storage = unittest.mock.Mock()
        self.vm.storage.resize.side_effect = self.dummy_coro
        with self.assertRaises(qubes.exc.ProtocolError):
            self.call_mgmt_func(
                b"admin.vm.volume.Resize",
                b"test-vm1",
                b"private",
                b"10000000000000000000",
            )
        self.assertEqual(
            self.vm.volumes.mock_calls, [unittest.mock.call.keys()]
        )
        self.assertFalse(self.vm.storage.called)

    def test_120_vm_volume_resize_invalid_size4(self):
        self.vm.volumes = unittest.mock.MagicMock()
        volumes_conf = {
            "keys.return_value": ["root", "private", "volatile", "kernel"],
        }
        self.vm.volumes.configure_mock(**volumes_conf)
        self.vm.storage = unittest.mock.Mock()
        self.vm.storage.resize.side_effect = self.dummy_coro
        with self.assertRaises(qubes.exc.ProtocolError):
            self.call_mgmt_func(
                b"admin.vm.volume.Resize", b"test-vm1", b"private", b"01"
            )
        self.assertEqual(
            self.vm.volumes.mock_calls, [unittest.mock.call.keys()]
        )
        self.assertFalse(self.vm.storage.called)

    def test_130_pool_list(self):
        self.app.pools = ["file", "lvm"]
        value = self.call_mgmt_func(b"admin.pool.List", b"dom0")
        self.assertEqual(value, "file\nlvm\n")
        self.assertFalse(self.app.save.called)

    @unittest.mock.patch("qubes.storage.pool_drivers")
    @unittest.mock.patch("qubes.storage.driver_parameters")
    def test_140_pool_listdrivers(self, mock_parameters, mock_drivers):
        self.app.pools = ["file", "lvm"]

        mock_drivers.return_value = ["driver1", "driver2"]
        mock_parameters.side_effect = lambda driver: {
            "driver1": ["param1", "param2"],
            "driver2": ["param3", "param4"],
        }[driver]

        value = self.call_mgmt_func(b"admin.pool.ListDrivers", b"dom0")
        self.assertEqual(
            value, "driver1 param1 param2\ndriver2 param3 param4\n"
        )
        self.assertEqual(mock_drivers.mock_calls, [unittest.mock.call()])
        self.assertEqual(
            mock_parameters.mock_calls,
            [unittest.mock.call("driver1"), unittest.mock.call("driver2")],
        )
        self.assertFalse(self.app.save.called)

    def test_150_pool_info(self):
        self.app.pools = {
            "pool1": unittest.mock.Mock(
                config={"param1": "value1", "param2": "value2"},
                usage=102400,
                size=204800,
            )
        }
        self.app.pools["pool1"].included_in.return_value = None
        value = self.call_mgmt_func(b"admin.pool.Info", b"dom0", b"pool1")

        self.assertEqual(
            value, "param1=value1\nparam2=value2\nsize=204800\nusage=102400\n"
        )
        self.assertFalse(self.app.save.called)

    def test_151_pool_info_unsupported_size(self):
        self.app.pools = {
            "pool1": unittest.mock.Mock(
                config={"param1": "value1", "param2": "value2"},
                size=None,
                usage=None,
                usage_details={},
            ),
        }
        self.app.pools["pool1"].included_in.return_value = None
        value = self.call_mgmt_func(b"admin.pool.Info", b"dom0", b"pool1")

        self.assertEqual(value, "param1=value1\nparam2=value2\n")
        self.assertFalse(self.app.save.called)

    def test_152_pool_info_included_in(self):
        self.app.pools = {
            "pool1": unittest.mock.MagicMock(
                config={"param1": "value1", "param2": "value2"},
                usage=102400,
                size=204800,
            )
        }
        self.app.pools["pool1"].included_in.return_value = self.app.pools[
            "pool1"
        ]
        self.app.pools["pool1"].__str__.return_value = "pool1"
        value = self.call_mgmt_func(b"admin.pool.Info", b"dom0", b"pool1")

        self.assertEqual(
            value,
            "param1=value1\nparam2=value2\nsize=204800\nusage=102400"
            "\nincluded_in=pool1\n",
        )
        self.assertFalse(self.app.save.called)

    def test_153_pool_usage(self):
        self.app.pools = {
            "pool1": unittest.mock.Mock(
                config={"param1": "value1", "param2": "value2"},
                usage_details={
                    "data_usage": 102400,
                    "data_size": 204800,
                    "metadata_size": 1024,
                    "metadata_usage": 50,
                },
            )
        }
        self.app.pools["pool1"].included_in.return_value = None
        value = self.call_mgmt_func(
            b"admin.pool.UsageDetails", b"dom0", b"pool1"
        )

        self.assertEqual(
            value,
            "data_size=204800\ndata_usage=102400\nmetadata_size=1024\nmetadata_usage=50\n",
        )
        self.assertFalse(self.app.save.called)

    @unittest.mock.patch("qubes.storage.pool_drivers")
    @unittest.mock.patch("qubes.storage.driver_parameters")
    def test_160_pool_add(self, mock_parameters, mock_drivers):
        self.app.pools = {
            "file": unittest.mock.Mock(),
            "lvm": unittest.mock.Mock(),
        }

        mock_drivers.return_value = ["driver1", "driver2"]
        mock_parameters.side_effect = lambda driver: {
            "driver1": ["param1", "param2"],
            "driver2": ["param3", "param4"],
        }[driver]

        add_pool_mock, self.app.add_pool = self.coroutine_mock()

        value = self.call_mgmt_func(
            b"admin.pool.Add",
            b"dom0",
            b"driver1",
            b"name=test-pool\nparam1=some-value\n",
        )
        self.assertIsNone(value)
        self.assertEqual(mock_drivers.mock_calls, [unittest.mock.call()])
        self.assertEqual(
            mock_parameters.mock_calls, [unittest.mock.call("driver1")]
        )
        self.assertEqual(
            add_pool_mock.mock_calls,
            [
                unittest.mock.call(
                    name="test-pool", driver="driver1", param1="some-value"
                )
            ],
        )
        self.assertTrue(self.app.save.called)

    @unittest.mock.patch("qubes.storage.pool_drivers")
    @unittest.mock.patch("qubes.storage.driver_parameters")
    def test_160_pool_add_invalid_driver(self, mock_parameters, mock_drivers):
        self.app.pools = {
            "file": unittest.mock.Mock(),
            "lvm": unittest.mock.Mock(),
        }

        mock_drivers.return_value = ["driver1", "driver2"]
        mock_parameters.side_effect = lambda driver: {
            "driver1": ["param1", "param2"],
            "driver2": ["param3", "param4"],
        }[driver]

        add_pool_mock, self.app.add_pool = self.coroutine_mock()

        with self.assertRaises(qubes.exc.QubesException):
            self.call_mgmt_func(
                b"admin.pool.Add",
                b"dom0",
                b"no-such-driver",
                b"name=test-pool\nparam1=some-value\n",
            )
        self.assertEqual(mock_drivers.mock_calls, [unittest.mock.call()])
        self.assertEqual(mock_parameters.mock_calls, [])
        self.assertEqual(add_pool_mock.mock_calls, [])
        self.assertFalse(self.app.save.called)

    @unittest.mock.patch("qubes.storage.pool_drivers")
    @unittest.mock.patch("qubes.storage.driver_parameters")
    def test_160_pool_add_invalid_param(self, mock_parameters, mock_drivers):
        self.app.pools = {
            "file": unittest.mock.Mock(),
            "lvm": unittest.mock.Mock(),
        }

        mock_drivers.return_value = ["driver1", "driver2"]
        mock_parameters.side_effect = lambda driver: {
            "driver1": ["param1", "param2"],
            "driver2": ["param3", "param4"],
        }[driver]

        add_pool_mock, self.app.add_pool = self.coroutine_mock()

        with self.assertRaises(qubes.exc.QubesException):
            self.call_mgmt_func(
                b"admin.pool.Add",
                b"dom0",
                b"driver1",
                b"name=test-pool\nparam3=some-value\n",
            )
        self.assertEqual(mock_drivers.mock_calls, [unittest.mock.call()])
        self.assertEqual(
            mock_parameters.mock_calls, [unittest.mock.call("driver1")]
        )
        self.assertEqual(add_pool_mock.mock_calls, [])
        self.assertFalse(self.app.save.called)

    @unittest.mock.patch("qubes.storage.pool_drivers")
    @unittest.mock.patch("qubes.storage.driver_parameters")
    def test_160_pool_add_missing_name(self, mock_parameters, mock_drivers):
        self.app.pools = {
            "file": unittest.mock.Mock(),
            "lvm": unittest.mock.Mock(),
        }

        mock_drivers.return_value = ["driver1", "driver2"]
        mock_parameters.side_effect = lambda driver: {
            "driver1": ["param1", "param2"],
            "driver2": ["param3", "param4"],
        }[driver]

        add_pool_mock, self.app.add_pool = self.coroutine_mock()

        with self.assertRaises(qubes.exc.PermissionDenied):
            self.call_mgmt_func(
                b"admin.pool.Add",
                b"dom0",
                b"driver1",
                b"param1=value\nparam2=some-value\n",
            )
        self.assertEqual(mock_drivers.mock_calls, [unittest.mock.call()])
        self.assertEqual(mock_parameters.mock_calls, [])
        self.assertEqual(add_pool_mock.mock_calls, [])
        self.assertFalse(self.app.save.called)

    @unittest.mock.patch("qubes.storage.pool_drivers")
    @unittest.mock.patch("qubes.storage.driver_parameters")
    def test_160_pool_add_existing_pool(self, mock_parameters, mock_drivers):
        self.app.pools = {
            "file": unittest.mock.Mock(),
            "lvm": unittest.mock.Mock(),
        }

        mock_drivers.return_value = ["driver1", "driver2"]
        mock_parameters.side_effect = lambda driver: {
            "driver1": ["param1", "param2"],
            "driver2": ["param3", "param4"],
        }[driver]

        add_pool_mock, self.app.add_pool = self.coroutine_mock()

        with self.assertRaises(qubes.exc.PermissionDenied):
            self.call_mgmt_func(
                b"admin.pool.Add",
                b"dom0",
                b"driver1",
                b"name=file\nparam1=value\nparam2=some-value\n",
            )
        self.assertEqual(mock_drivers.mock_calls, [unittest.mock.call()])
        self.assertEqual(mock_parameters.mock_calls, [])
        self.assertEqual(add_pool_mock.mock_calls, [])
        self.assertFalse(self.app.save.called)

    @unittest.mock.patch("qubes.storage.pool_drivers")
    @unittest.mock.patch("qubes.storage.driver_parameters")
    def test_160_pool_add_invalid_config_format(
        self, mock_parameters, mock_drivers
    ):
        self.app.pools = {
            "file": unittest.mock.Mock(),
            "lvm": unittest.mock.Mock(),
        }

        mock_drivers.return_value = ["driver1", "driver2"]
        mock_parameters.side_effect = lambda driver: {
            "driver1": ["param1", "param2"],
            "driver2": ["param3", "param4"],
        }[driver]

        add_pool_mock, self.app.add_pool = self.coroutine_mock()

        with self.assertRaises(qubes.exc.PermissionDenied):
            self.call_mgmt_func(
                b"admin.pool.Add",
                b"dom0",
                b"driver1",
                b"name=test-pool\nparam 1=value\n_param2\n",
            )
        self.assertEqual(mock_drivers.mock_calls, [unittest.mock.call()])
        self.assertEqual(mock_parameters.mock_calls, [])
        self.assertEqual(add_pool_mock.mock_calls, [])
        self.assertFalse(self.app.save.called)

    def test_170_pool_remove(self):
        self.app.pools = {
            "file": unittest.mock.Mock(),
            "lvm": unittest.mock.Mock(),
            "test-pool": unittest.mock.Mock(),
        }
        remove_pool_mock, self.app.remove_pool = self.coroutine_mock()
        value = self.call_mgmt_func(b"admin.pool.Remove", b"dom0", b"test-pool")
        self.assertIsNone(value)
        self.assertEqual(
            remove_pool_mock.mock_calls, [unittest.mock.call("test-pool")]
        )
        self.assertTrue(self.app.save.called)

    def test_170_pool_remove_invalid_pool(self):
        self.app.pools = {
            "file": unittest.mock.Mock(),
            "lvm": unittest.mock.Mock(),
            "test-pool": unittest.mock.Mock(),
        }
        remove_pool_mock, self.app.remove_pool = self.coroutine_mock()
        with self.assertRaises(qubes.exc.PermissionDenied):
            self.call_mgmt_func(b"admin.pool.Remove", b"dom0", b"no-such-pool")
        self.assertEqual(remove_pool_mock.mock_calls, [])
        self.assertFalse(self.app.save.called)

    def test_180_label_list(self):
        value = self.call_mgmt_func(b"admin.label.List", b"dom0")
        self.assertEqual(
            value,
            "".join("{}\n".format(l.name) for l in self.app.labels.values()),
        )
        self.assertFalse(self.app.save.called)

    def test_190_label_get(self):
        self.app.get_label = unittest.mock.Mock()
        self.app.get_label.configure_mock(**{"return_value.color": "0xff0000"})
        value = self.call_mgmt_func(b"admin.label.Get", b"dom0", b"red")
        self.assertEqual(value, "0xff0000")
        self.assertEqual(
            self.app.get_label.mock_calls, [unittest.mock.call("red")]
        )
        self.assertFalse(self.app.save.called)

    def test_195_label_index(self):
        self.app.get_label = unittest.mock.Mock()
        self.app.get_label.configure_mock(**{"return_value.index": 1})
        value = self.call_mgmt_func(b"admin.label.Index", b"dom0", b"red")
        self.assertEqual(value, "1")
        self.assertEqual(
            self.app.get_label.mock_calls, [unittest.mock.call("red")]
        )
        self.assertFalse(self.app.save.called)

    def test_200_label_create(self):
        self.app.get_label = unittest.mock.Mock()
        self.app.get_label.side_effect = KeyError
        self.app.labels = unittest.mock.MagicMock()
        labels_config = {
            "keys.return_value": range(1, 9),
        }
        self.app.labels.configure_mock(**labels_config)
        value = self.call_mgmt_func(
            b"admin.label.Create", b"dom0", b"cyan", b"0x00ffff"
        )
        self.assertIsNone(value)
        self.assertEqual(
            self.app.get_label.mock_calls, [unittest.mock.call("cyan")]
        )
        self.assertEqual(
            self.app.labels.mock_calls,
            [
                unittest.mock.call.keys(),
                unittest.mock.call.__getattr__("__setitem__")(
                    9, qubes.Label(9, "0x00ffff", "cyan")
                ),
            ],
        )
        self.assertTrue(self.app.save.called)

    def test_200_label_create_invalid_color(self):
        self.app.get_label = unittest.mock.Mock()
        self.app.get_label.side_effect = KeyError
        self.app.labels = unittest.mock.MagicMock()
        labels_config = {
            "keys.return_value": range(1, 9),
        }
        self.app.labels.configure_mock(**labels_config)
        with self.assertRaises(qubes.exc.PermissionDenied):
            self.call_mgmt_func(
                b"admin.label.Create", b"dom0", b"cyan", b"abcd"
            )
        self.assertEqual(
            self.app.get_label.mock_calls, [unittest.mock.call("cyan")]
        )
        self.assertEqual(self.app.labels.mock_calls, [])
        self.assertFalse(self.app.save.called)

    def test_200_label_create_invalid_name(self):
        self.app.get_label = unittest.mock.Mock()
        self.app.get_label.side_effect = KeyError
        self.app.labels = unittest.mock.MagicMock()
        labels_config = {
            "keys.return_value": range(1, 9),
        }
        self.app.labels.configure_mock(**labels_config)
        with self.assertRaises(qubes.exc.PermissionDenied):
            self.call_mgmt_func(
                b"admin.label.Create", b"dom0", b"01", b"0xff0000"
            )
        with self.assertRaises(qubes.exc.PermissionDenied):
            self.call_mgmt_func(
                b"admin.label.Create", b"dom0", b"../xxx", b"0xff0000"
            )
        with self.assertRaises(qubes.exc.PermissionDenied):
            self.call_mgmt_func(
                b"admin.label.Create",
                b"dom0",
                b"strange-name!@#$",
                b"0xff0000",
            )

        self.assertEqual(self.app.get_label.mock_calls, [])
        self.assertEqual(self.app.labels.mock_calls, [])
        self.assertFalse(self.app.save.called)

    def test_200_label_create_already_exists(self):
        self.app.get_label = unittest.mock.Mock(wraps=self.app.get_label)
        with self.assertRaises(qubes.exc.QubesValueError):
            self.call_mgmt_func(b"admin.label.Create", b"dom0", b"red", b"abcd")
        self.assertEqual(
            self.app.get_label.mock_calls, [unittest.mock.call("red")]
        )
        self.assertFalse(self.app.save.called)

    def test_210_label_remove(self):
        label = qubes.Label(9, "0x00ffff", "cyan")
        self.app.labels[9] = label
        self.app.get_label = unittest.mock.Mock(**{"return_value.index": 9})
        self.app.labels = unittest.mock.MagicMock(wraps=self.app.labels)
        value = self.call_mgmt_func(b"admin.label.Remove", b"dom0", b"cyan")
        self.assertIsNone(value)
        self.assertEqual(
            self.app.get_label.mock_calls, [unittest.mock.call("cyan")]
        )
        self.assertEqual(
            self.app.labels.mock_calls, [unittest.mock.call.__delitem__(9)]
        )
        self.assertTrue(self.app.save.called)

    def test_210_label_remove_invalid_label(self):
        with self.assertRaises(qubes.exc.QubesValueError):
            self.call_mgmt_func(
                b"admin.label.Remove", b"dom0", b"no-such-label"
            )
        self.assertFalse(self.app.save.called)

    def test_210_label_remove_default_label(self):
        self.app.labels = unittest.mock.MagicMock(wraps=self.app.labels)
        self.app.get_label = unittest.mock.Mock(**{"return_value.index": 6})
        with self.assertRaises(qubes.exc.PermissionDenied):
            self.call_mgmt_func(b"admin.label.Remove", b"dom0", b"blue")
        self.assertEqual(self.app.labels.mock_calls, [])
        self.assertFalse(self.app.save.called)

    def test_210_label_remove_in_use(self):
        self.app.labels = unittest.mock.MagicMock(wraps=self.app.labels)
        self.app.get_label = unittest.mock.Mock(**{"return_value.index": 1})
        with self.assertRaises(qubes.exc.PermissionDenied):
            self.call_mgmt_func(b"admin.label.Remove", b"dom0", b"red")
        self.assertEqual(self.app.labels.mock_calls, [])
        self.assertFalse(self.app.save.called)

    def test_220_start(self):
        func_mock = unittest.mock.Mock()

        async def coroutine_mock(*args, **kwargs):
            return func_mock(*args, **kwargs)

        self.vm.start = coroutine_mock
        value = self.call_mgmt_func(b"admin.vm.Start", b"test-vm1")
        self.assertIsNone(value)
        func_mock.assert_called_once_with()

    def test_230_shutdown(self):
        func_mock = unittest.mock.Mock()

        async def coroutine_mock(*args, **kwargs):
            return func_mock(*args, **kwargs)

        self.vm.shutdown = coroutine_mock
        value = self.call_mgmt_func(b"admin.vm.Shutdown", b"test-vm1")
        self.assertIsNone(value)
        func_mock.assert_called_once_with(force=False, wait=False)

    def test_231_shutdown_force(self):
        func_mock = unittest.mock.Mock()

        async def coroutine_mock(*args, **kwargs):
            return func_mock(*args, **kwargs)

        self.vm.shutdown = coroutine_mock
        value = self.call_mgmt_func(b"admin.vm.Shutdown", b"test-vm1", b"force")
        self.assertIsNone(value)
        func_mock.assert_called_once_with(force=True, wait=False)

    def test_232_shutdown_wait(self):
        func_mock = unittest.mock.Mock()

        async def coroutine_mock(*args, **kwargs):
            return func_mock(*args, **kwargs)

        self.vm.shutdown = coroutine_mock
        value = self.call_mgmt_func(b"admin.vm.Shutdown", b"test-vm1", b"wait")
        self.assertIsNone(value)
        func_mock.assert_called_once_with(force=False, wait=True)

    def test_233_shutdown_wait_force(self):
        func_mock = unittest.mock.Mock()

        async def coroutine_mock(*args, **kwargs):
            return func_mock(*args, **kwargs)

        self.vm.shutdown = coroutine_mock
        value = self.call_mgmt_func(
            b"admin.vm.Shutdown", b"test-vm1", b"wait+force"
        )
        self.assertIsNone(value)
        func_mock.assert_called_once_with(force=True, wait=True)

    def test_234_shutdown_force_wait(self):
        func_mock = unittest.mock.Mock()

        async def coroutine_mock(*args, **kwargs):
            return func_mock(*args, **kwargs)

        self.vm.shutdown = coroutine_mock
        value = self.call_mgmt_func(
            b"admin.vm.Shutdown", b"test-vm1", b"force+wait"
        )
        self.assertIsNone(value)
        func_mock.assert_called_once_with(force=True, wait=True)

    def test_234_shutdown_force_wait_invalid(self):
        func_mock = unittest.mock.Mock()

        async def coroutine_mock(*args, **kwargs):
            return func_mock(*args, **kwargs)

        self.vm.shutdown = coroutine_mock
        with self.assertRaises(qubes.exc.PermissionDenied):
            self.call_mgmt_func(b"admin.vm.Shutdown", b"test-vm1", b"forcewait")
        func_mock.assert_not_called()

    def test_240_pause(self):
        func_mock = unittest.mock.Mock()

        async def coroutine_mock(*args, **kwargs):
            return func_mock(*args, **kwargs)

        self.vm.pause = coroutine_mock
        value = self.call_mgmt_func(b"admin.vm.Pause", b"test-vm1")
        self.assertIsNone(value)
        func_mock.assert_called_once_with()

    def test_241_suspend(self):
        func_mock = unittest.mock.Mock()

        async def coroutine_mock(*args, **kwargs):
            return func_mock(*args, **kwargs)

        self.vm.suspend = coroutine_mock
        value = self.call_mgmt_func(b"admin.vm.Suspend", b"test-vm1")
        self.assertIsNone(value)
        func_mock.assert_called_once_with()

    def test_250_unpause(self):
        func_mock = unittest.mock.Mock()

        async def coroutine_mock(*args, **kwargs):
            return func_mock(*args, **kwargs)

        self.vm.unpause = coroutine_mock
        value = self.call_mgmt_func(b"admin.vm.Unpause", b"test-vm1")
        self.assertIsNone(value)
        func_mock.assert_called_once_with()

    def test_251_resume(self):
        func_mock = unittest.mock.Mock()

        async def coroutine_mock(*args, **kwargs):
            return func_mock(*args, **kwargs)

        self.vm.resume = coroutine_mock
        value = self.call_mgmt_func(b"admin.vm.Resume", b"test-vm1")
        self.assertIsNone(value)
        func_mock.assert_called_once_with()

    def test_260_kill(self):
        func_mock = unittest.mock.Mock()

        async def coroutine_mock(*args, **kwargs):
            return func_mock(*args, **kwargs)

        self.vm.kill = coroutine_mock
        value = self.call_mgmt_func(b"admin.vm.Kill", b"test-vm1")
        self.assertIsNone(value)
        func_mock.assert_called_once_with()

    def test_270_events(self):
        send_event = unittest.mock.Mock(spec=[])
        mgmt_obj = qubes.api.admin.QubesAdminAPI(
            self.app,
            b"dom0",
            b"admin.Events",
            b"dom0",
            b"",
            send_event=send_event,
        )

        async def fire_event():
            self.vm.fire_event("test-event", arg1="abc")
            mgmt_obj.cancel()

        loop = asyncio.get_event_loop()
        execute_task = asyncio.ensure_future(
            mgmt_obj.execute(untrusted_payload=b"")
        )
        asyncio.ensure_future(fire_event())
        loop.run_until_complete(execute_task)
        self.assertIsNone(execute_task.result())
        self.assertEventFired(
            self.emitter, "admin-permission:" + "admin.Events"
        )
        self.assertEqual(
            send_event.mock_calls,
            [
                unittest.mock.call(self.app, "connection-established"),
                unittest.mock.call(self.vm, "test-event", arg1="abc"),
            ],
        )

    def test_271_events_add_vm(self):
        send_event = unittest.mock.Mock(spec=[])
        mgmt_obj = qubes.api.admin.QubesAdminAPI(
            self.app,
            b"dom0",
            b"admin.Events",
            b"dom0",
            b"",
            send_event=send_event,
        )

        async def fire_event():
            self.vm.fire_event("test-event", arg1="abc")
            # add VM _after_ starting admin.Events call
            vm = self.app.add_new_vm(
                "AppVM", label="red", name="test-vm2", template="test-template"
            )
            vm.fire_event("test-event2", arg1="abc")
            mgmt_obj.cancel()
            return vm

        loop = asyncio.get_event_loop()
        execute_task = asyncio.ensure_future(
            mgmt_obj.execute(untrusted_payload=b"")
        )
        event_task = asyncio.ensure_future(fire_event())
        loop.run_until_complete(execute_task)
        vm2 = event_task.result()
        self.assertIsNone(execute_task.result())
        self.assertEventFired(
            self.emitter, "admin-permission:" + "admin.Events"
        )
        self.assertEqual(
            send_event.mock_calls,
            [
                unittest.mock.call(self.app, "connection-established"),
                unittest.mock.call(self.vm, "test-event", arg1="abc"),
                unittest.mock.call(self.app, "domain-add", vm=vm2),
                unittest.mock.call(vm2, "test-event2", arg1="abc"),
            ],
        )

    def test_272_events_filter(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = pathlib.Path(tmpdir)
            with unittest.mock.patch(
                "qubes.ext.admin.AdminExtension._instance.policy_cache.paths",
                [pathlib.Path(tmpdir)],
            ):
                with (tmpdir / "admin.policy").open("w") as f:
                    f.write("admin.Events * @anyvm @adminvm allow\n")
                    f.write("admin.Events * @anyvm test-vm1 allow")

                send_event = unittest.mock.Mock(spec=[])
                mgmt_obj = qubes.api.admin.QubesAdminAPI(
                    self.app,
                    b"test-vm1",
                    b"admin.Events",
                    b"dom0",
                    b"",
                    send_event=send_event,
                )

                async def fire_event():
                    # add VM _after_ starting admin.Events call
                    vm = self.app.add_new_vm(
                        "AppVM",
                        label="red",
                        name="test-vm2",
                        template="test-template",
                    )
                    vm.fire_event("test-event2", arg1="abc")
                    self.vm.fire_event("test-event", arg1="abc")
                    mgmt_obj.cancel()
                    return vm

                loop = asyncio.get_event_loop()
                execute_task = asyncio.ensure_future(
                    mgmt_obj.execute(untrusted_payload=b"")
                )
                event_task = asyncio.ensure_future(fire_event())
                loop.run_until_complete(execute_task)
                event_task.result()
                self.assertIsNone(execute_task.result())
                self.assertEqual(
                    send_event.mock_calls,
                    [
                        unittest.mock.call(self.app, "connection-established"),
                        unittest.mock.call(self.vm, "test-event", arg1="abc"),
                    ],
                )

    def test_280_feature_list(self):
        self.vm.features["test-feature"] = "some-value"
        value = self.call_mgmt_func(b"admin.vm.feature.List", b"test-vm1")
        self.assertEqual(value, "test-feature\n")
        self.assertFalse(self.app.save.called)

    def test_290_feature_get(self):
        self.vm.features["test-feature"] = "some-value"
        value = self.call_mgmt_func(
            b"admin.vm.feature.Get", b"test-vm1", b"test-feature"
        )
        self.assertEqual(value, "some-value")
        self.assertFalse(self.app.save.called)

    def test_291_feature_get_none(self):
        with self.assertRaises(qubes.exc.QubesFeatureNotFoundError):
            self.call_mgmt_func(
                b"admin.vm.feature.Get", b"test-vm1", b"test-feature"
            )
        self.assertFalse(self.app.save.called)

    def test_300_feature_remove(self):
        self.vm.features["test-feature"] = "some-value"
        value = self.call_mgmt_func(
            b"admin.vm.feature.Remove", b"test-vm1", b"test-feature"
        )
        self.assertIsNone(value, None)
        self.assertNotIn("test-feature", self.vm.features)
        self.assertTrue(self.app.save.called)

    def test_301_feature_remove_none(self):
        with self.assertRaises(qubes.exc.QubesFeatureNotFoundError):
            self.call_mgmt_func(
                b"admin.vm.feature.Remove", b"test-vm1", b"test-feature"
            )
        self.assertFalse(self.app.save.called)

    def test_310_feature_checkwithtemplate(self):
        self.vm.features["test-feature"] = "some-value"
        value = self.call_mgmt_func(
            b"admin.vm.feature.CheckWithTemplate", b"test-vm1", b"test-feature"
        )
        self.assertEqual(value, "some-value")
        self.assertFalse(self.app.save.called)

    def test_311_feature_checkwithtemplate_tpl(self):
        self.template.features["test-feature"] = "some-value"
        value = self.call_mgmt_func(
            b"admin.vm.feature.CheckWithTemplate", b"test-vm1", b"test-feature"
        )
        self.assertEqual(value, "some-value")
        self.assertFalse(self.app.save.called)

    def test_312_feature_checkwithtemplate_none(self):
        with self.assertRaises(qubes.exc.QubesFeatureNotFoundError):
            self.call_mgmt_func(
                b"admin.vm.feature.CheckWithTemplate",
                b"test-vm1",
                b"test-feature",
            )
        self.assertFalse(self.app.save.called)

    def test_315_feature_checkwithnetvm(self):
        self.vm.features["test-feature"] = "some-value"
        value = self.call_mgmt_func(
            b"admin.vm.feature.CheckWithNetvm", b"test-vm1", b"test-feature"
        )
        self.assertEqual(value, "some-value")
        self.assertFalse(self.app.save.called)

    def test_316_feature_checkwithnetvm_netvm(self):
        self.netvm = self.app.add_new_vm(
            "AppVM",
            label="red",
            name="test-netvm1",
            template="test-template",
            provides_network=True,
        )
        self.vm.netvm = self.netvm
        self.netvm.features["test-feature"] = "some-value"
        value = self.call_mgmt_func(
            b"admin.vm.feature.CheckWithNetvm", b"test-vm1", b"test-feature"
        )
        self.assertEqual(value, "some-value")
        self.assertFalse(self.app.save.called)

    def test_317_feature_checkwithnetvm_none(self):
        with self.assertRaises(qubes.exc.QubesFeatureNotFoundError):
            self.call_mgmt_func(
                b"admin.vm.feature.CheckWithNetvm",
                b"test-vm1",
                b"test-feature",
            )
        self.assertFalse(self.app.save.called)

    def test_318_feature_checkwithadminvm(self):
        self.app.domains["dom0"].features["test-feature"] = "some-value"
        value = self.call_mgmt_func(
            b"admin.vm.feature.CheckWithAdminVM", b"test-vm1", b"test-feature"
        )
        self.assertEqual(value, "some-value")
        self.assertFalse(self.app.save.called)

    def test_319_feature_checkwithtpladminvm(self):
        self.app.domains["dom0"].features["test-feature"] = "some-value"
        value = self.call_mgmt_func(
            b"admin.vm.feature.CheckWithTemplateAndAdminVM",
            b"test-vm1",
            b"test-feature",
        )
        self.assertEqual(value, "some-value")

        self.template.features["test-feature"] = "some-value2"
        value = self.call_mgmt_func(
            b"admin.vm.feature.CheckWithTemplateAndAdminVM",
            b"test-vm1",
            b"test-feature",
        )
        self.assertEqual(value, "some-value2")

        self.assertFalse(self.app.save.called)

    def test_320_feature_set(self):
        value = self.call_mgmt_func(
            b"admin.vm.feature.Set",
            b"test-vm1",
            b"test-feature",
            b"some-value",
        )
        self.assertIsNone(value)
        self.assertEqual(self.vm.features["test-feature"], "some-value")
        self.assertTrue(self.app.save.called)

    def test_321_feature_set_empty(self):
        value = self.call_mgmt_func(
            b"admin.vm.feature.Set", b"test-vm1", b"test-feature", b""
        )
        self.assertIsNone(value)
        self.assertEqual(self.vm.features["test-feature"], "")
        self.assertTrue(self.app.save.called)

    def test_322_feature_set_invalid(self):
        with self.assertRaises(UnicodeDecodeError):
            self.call_mgmt_func(
                b"admin.vm.feature.Set",
                b"test-vm1",
                b"test-feature",
                b"\x02\x03\xffsome-value",
            )
        self.assertNotIn("test-feature", self.vm.features)
        self.assertFalse(self.app.save.called)

    def test_323_feature_set_service_too_long(self):
        with self.assertRaises(qubes.exc.QubesValueError):
            self.call_mgmt_func(
                b"admin.vm.feature.Set",
                b"test-vm1",
                b"service." + b"a" * 49,
                b"1",
            )
        self.assertNotIn("test-feature", self.vm.features)
        self.assertFalse(self.app.save.called)

    def test_325_feature_set_service_empty_name(self):
        with self.assertRaises(qubes.exc.QubesValueError):
            self.call_mgmt_func(
                b"admin.vm.feature.Set", b"test-vm1", b"service."
            )
        self.assertNotIn("test-feature", self.vm.features)
        self.assertFalse(self.app.save.called)

    async def dummy_coro(self, *args, **kwargs):
        pass

    def coroutine_mock(self):
        func_mock = unittest.mock.Mock()

        async def coroutine_mock(*args, **kwargs):
            return func_mock(*args, **kwargs)

        return func_mock, coroutine_mock

    @unittest.mock.patch("qubes.storage.Storage.create")
    def test_330_vm_create_standalone(self, storage_mock):
        storage_mock.side_effect = self.dummy_coro
        self.call_mgmt_func(
            b"admin.vm.Create.StandaloneVM",
            b"dom0",
            b"",
            b"name=test-vm2 label=red",
        )

        self.assertIn("test-vm2", self.app.domains)
        vm = self.app.domains["test-vm2"]
        self.assertIsInstance(vm, qubes.vm.standalonevm.StandaloneVM)
        self.assertEqual(vm.label, self.app.get_label("red"))
        self.assertEqual(
            storage_mock.mock_calls,
            [unittest.mock.call(self.app.domains["test-vm2"]).create()],
        )
        self.assertTrue(
            os.path.exists(
                os.path.join(self.test_base_dir, "appvms", "test-vm2")
            )
        )

        self.assertTrue(self.app.save.called)

    @unittest.mock.patch("qubes.storage.Storage.create")
    def test_331_vm_create_standalone_spurious_template(self, storage_mock):
        storage_mock.side_effect = self.dummy_coro
        with self.assertRaises(qubes.exc.QubesValueError):
            self.call_mgmt_func(
                b"admin.vm.Create.StandaloneVM",
                b"dom0",
                b"test-template",
                b"name=test-vm2 label=red",
            )

        self.assertNotIn("test-vm2", self.app.domains)
        self.assertEqual(storage_mock.mock_calls, [])
        self.assertFalse(
            os.path.exists(
                os.path.join(self.test_base_dir, "appvms", "test-vm2")
            )
        )

        self.assertNotIn("test-vm2", self.app.domains)
        self.assertFalse(self.app.save.called)

    @unittest.mock.patch("qubes.storage.Storage.create")
    def test_332_vm_create_app(self, storage_mock):
        storage_mock.side_effect = self.dummy_coro
        self.call_mgmt_func(
            b"admin.vm.Create.AppVM",
            b"dom0",
            b"test-template",
            b"name=test-vm2 label=red",
        )

        self.assertIn("test-vm2", self.app.domains)
        vm = self.app.domains["test-vm2"]
        self.assertEqual(vm.label, self.app.get_label("red"))
        self.assertEqual(vm.template, self.app.domains["test-template"])
        self.assertEqual(
            storage_mock.mock_calls,
            [unittest.mock.call(self.app.domains["test-vm2"]).create()],
        )
        self.assertTrue(
            os.path.exists(
                os.path.join(self.test_base_dir, "appvms", "test-vm2")
            )
        )

        self.assertTrue(self.app.save.called)

    @unittest.mock.patch("qubes.storage.Storage.create")
    def test_333_vm_create_app_default_template(self, storage_mock):
        storage_mock.side_effect = self.dummy_coro
        self.call_mgmt_func(
            b"admin.vm.Create.AppVM", b"dom0", b"", b"name=test-vm2 label=red"
        )

        self.assertEqual(
            storage_mock.mock_calls,
            [unittest.mock.call(self.app.domains["test-vm2"]).create()],
        )

        self.assertIn("test-vm2", self.app.domains)
        self.assertEqual(
            self.app.domains["test-vm2"].template, self.app.default_template
        )
        self.assertTrue(self.app.save.called)

    @unittest.mock.patch("qubes.storage.Storage.create")
    def test_334_vm_create_invalid_name(self, storage_mock):
        storage_mock.side_effect = self.dummy_coro
        with self.assertRaises(qubes.exc.QubesValueError):
            self.call_mgmt_func(
                b"admin.vm.Create.AppVM",
                b"dom0",
                b"test-template",
                b"name=test-###",
            )

        self.assertNotIn("test-###", self.app.domains)
        self.assertFalse(self.app.save.called)

        with self.assertRaises(qubes.exc.QubesValueError):
            self.call_mgmt_func(
                b"admin.vm.Create.AppVM",
                b"dom0",
                b"test-template",
                b"name=--helpVM",
            )
        self.assertNotIn("--helpVM", self.app.domains)
        self.assertFalse(self.app.save.called)

        with self.assertRaises(qubes.exc.QubesValueError):
            self.call_mgmt_func(
                b"admin.vm.Create.AppVM",
                b"dom0",
                b"test-template",
                b"name=1stVM",
            )
        self.assertNotIn("1stVM", self.app.domains)
        self.assertFalse(self.app.save.called)

    @unittest.mock.patch("qubes.storage.Storage.create")
    def test_335_vm_create_missing_name(self, storage_mock):
        storage_mock.side_effect = self.dummy_coro
        with self.assertRaises(qubes.exc.ProtocolError):
            self.call_mgmt_func(
                b"admin.vm.Create.AppVM",
                b"dom0",
                b"test-template",
                b"label=red",
            )

        self.assertFalse(self.app.save.called)

    @unittest.mock.patch("qubes.storage.Storage.create")
    def test_336_vm_create_spurious_pool(self, storage_mock):
        storage_mock.side_effect = self.dummy_coro
        with self.assertRaises(qubes.exc.ProtocolError):
            self.call_mgmt_func(
                b"admin.vm.Create.AppVM",
                b"dom0",
                b"test-template",
                b"name=test-vm2 label=red pool=default",
            )

        self.assertNotIn("test-vm2", self.app.domains)
        self.assertFalse(self.app.save.called)

    @unittest.mock.patch("qubes.storage.Storage.create")
    def test_337_vm_create_duplicate_name(self, storage_mock):
        storage_mock.side_effect = self.dummy_coro
        with self.assertRaises(qubes.exc.QubesException):
            self.call_mgmt_func(
                b"admin.vm.Create.AppVM",
                b"dom0",
                b"test-template",
                b"name=test-vm1 label=red",
            )

        self.assertFalse(self.app.save.called)

    @unittest.mock.patch("qubes.storage.Storage.create")
    def test_338_vm_create_name_twice(self, storage_mock):
        storage_mock.side_effect = self.dummy_coro
        with self.assertRaises(qubes.exc.ProtocolError):
            self.call_mgmt_func(
                b"admin.vm.Create.AppVM",
                b"dom0",
                b"test-template",
                b"name=test-vm2 name=test-vm3 label=red",
            )

        self.assertNotIn("test-vm2", self.app.domains)
        self.assertNotIn("test-vm3", self.app.domains)
        self.assertFalse(self.app.save.called)

    @unittest.mock.patch("qubes.storage.Storage.create")
    def test_340_vm_create_in_pool_app(self, storage_mock):
        storage_mock.side_effect = self.dummy_coro
        self.call_mgmt_func(
            b"admin.vm.CreateInPool.AppVM",
            b"dom0",
            b"test-template",
            b"name=test-vm2 label=red " b"pool=test",
        )

        self.assertIn("test-vm2", self.app.domains)
        vm = self.app.domains["test-vm2"]
        self.assertEqual(vm.label, self.app.get_label("red"))
        self.assertEqual(vm.template, self.app.domains["test-template"])
        # setting pool= affect only volumes actually created for this VM,
        # not used from a template or so
        self.assertEqual(
            vm.volume_config["root"]["pool"],
            self.template.volumes["root"].pool,
        )
        self.assertEqual(vm.volume_config["private"]["pool"], "test")
        self.assertEqual(vm.volume_config["volatile"]["pool"], "test")
        self.assertEqual(vm.volume_config["kernel"]["pool"], "linux-kernel")
        self.assertEqual(
            storage_mock.mock_calls,
            [unittest.mock.call(self.app.domains["test-vm2"]).create()],
        )
        self.assertTrue(
            os.path.exists(
                os.path.join(self.test_base_dir, "appvms", "test-vm2")
            )
        )

        self.assertTrue(self.app.save.called)

    @unittest.mock.patch("qubes.storage.Storage.create")
    def test_341_vm_create_in_pool_private(self, storage_mock):
        storage_mock.side_effect = self.dummy_coro
        self.call_mgmt_func(
            b"admin.vm.CreateInPool.AppVM",
            b"dom0",
            b"test-template",
            b"name=test-vm2 label=red " b"pool:private=test",
        )

        self.assertIn("test-vm2", self.app.domains)
        vm = self.app.domains["test-vm2"]
        self.assertEqual(vm.label, self.app.get_label("red"))
        self.assertEqual(vm.template, self.app.domains["test-template"])
        self.assertEqual(
            vm.volume_config["root"]["pool"],
            self.template.volumes["root"].pool,
        )
        self.assertEqual(vm.volume_config["private"]["pool"], "test")
        self.assertEqual(
            vm.volume_config["volatile"]["pool"],
            self.app.default_pool_volatile,
        )
        self.assertEqual(vm.volume_config["kernel"]["pool"], "linux-kernel")
        self.assertEqual(
            storage_mock.mock_calls,
            [unittest.mock.call(self.app.domains["test-vm2"]).create()],
        )
        self.assertTrue(
            os.path.exists(
                os.path.join(self.test_base_dir, "appvms", "test-vm2")
            )
        )

        self.assertTrue(self.app.save.called)

    @unittest.mock.patch("qubes.storage.Storage.create")
    def test_342_vm_create_in_pool_invalid_pool(self, storage_mock):
        storage_mock.side_effect = self.dummy_coro
        with self.assertRaises(qubes.exc.QubesException):
            self.call_mgmt_func(
                b"admin.vm.CreateInPool.AppVM",
                b"dom0",
                b"test-template",
                b"name=test-vm2 label=red " b"pool=no-such-pool",
            )

        self.assertFalse(self.app.save.called)

    @unittest.mock.patch("qubes.storage.Storage.create")
    def test_343_vm_create_in_pool_invalid_pool2(self, storage_mock):
        storage_mock.side_effect = self.dummy_coro
        with self.assertRaises(qubes.exc.QubesException):
            self.call_mgmt_func(
                b"admin.vm.CreateInPool.AppVM",
                b"dom0",
                b"test-template",
                b"name=test-vm2 label=red " b"pool:private=no-such-pool",
            )

        self.assertNotIn("test-vm2", self.app.domains)
        self.assertFalse(self.app.save.called)

    @unittest.mock.patch("qubes.storage.Storage.create")
    def test_344_vm_create_in_pool_invalid_volume(self, storage_mock):
        storage_mock.side_effect = self.dummy_coro
        with self.assertRaises(qubes.exc.PermissionDenied):
            self.call_mgmt_func(
                b"admin.vm.CreateInPool.AppVM",
                b"dom0",
                b"test-template",
                b"name=test-vm2 label=red " b"pool:invalid=test",
            )

        self.assertNotIn("test-vm2", self.app.domains)
        self.assertFalse(self.app.save.called)

    @unittest.mock.patch("qubes.storage.Storage.create")
    def test_345_vm_create_in_pool_app_root(self, storage_mock):
        # setting custom pool for 'root' volume of AppVM should not be
        # allowed - this volume belongs to the template
        storage_mock.side_effect = self.dummy_coro
        with self.assertRaises(qubes.exc.QubesException):
            self.call_mgmt_func(
                b"admin.vm.CreateInPool.AppVM",
                b"dom0",
                b"test-template",
                b"name=test-vm2 label=red " b"pool:root=test",
            )

        self.assertNotIn("test-vm2", self.app.domains)
        self.assertFalse(self.app.save.called)

    @unittest.mock.patch("qubes.storage.Storage.create")
    def test_346_vm_create_in_pool_duplicate_pool(self, storage_mock):
        # setting custom pool for 'root' volume of AppVM should not be
        # allowed - this volume belongs to the template
        storage_mock.side_effect = self.dummy_coro
        with self.assertRaises(qubes.exc.ProtocolError):
            self.call_mgmt_func(
                b"admin.vm.CreateInPool.AppVM",
                b"dom0",
                b"test-template",
                b"name=test-vm2 label=red " b"pool=test pool:root=test",
            )

        self.assertNotIn("test-vm2", self.app.domains)
        self.assertFalse(self.app.save.called)

    def test_400_property_list(self):
        # actual function tested for admin.vm.property.* already
        # this test is kind of stupid, but at least check if appropriate
        # admin-permission event is fired
        value = self.call_mgmt_func(b"admin.property.List", b"dom0")
        properties = self.app.property_list()
        self.assertEqual(
            value, "".join("{}\n".format(prop.__name__) for prop in properties)
        )

    def test_410_property_get_str(self):
        # actual function tested for admin.vm.property.* already
        value = self.call_mgmt_func(
            b"admin.property.Get", b"dom0", b"default_kernel"
        )
        self.assertEqual(value, "default=False type=str 1.0")

    def test_420_propert_set_str(self):
        # actual function tested for admin.vm.property.* already
        with unittest.mock.patch("qubes.property.__set__") as mock:
            value = self.call_mgmt_func(
                b"admin.property.Set", b"dom0", b"default_kernel", b"1.0"
            )
            self.assertIsNone(value)
            mock.assert_called_once_with(self.app, "1.0")
        self.app.save.assert_called_once_with()

    def test_440_property_help(self):
        # actual function tested for admin.vm.property.* already
        value = self.call_mgmt_func(b"admin.property.Help", b"dom0", b"clockvm")
        self.assertEqual(
            value, "Which VM to use as NTP proxy for updating AdminVM"
        )
        self.assertFalse(self.app.save.called)

    def test_450_property_reset(self):
        # actual function tested for admin.vm.property.* already
        with unittest.mock.patch("qubes.property.__delete__") as mock:
            value = self.call_mgmt_func(
                b"admin.property.Reset", b"dom0", b"clockvm"
            )
            mock.assert_called_with(self.app)
        self.assertIsNone(value)
        self.app.save.assert_called_once_with()

    def test_notes_get(self):
        notes = "For Your Eyes Only"
        self.app.domains["test-vm1"].get_notes = unittest.mock.Mock()
        self.app.domains["test-vm1"].get_notes.configure_mock(
            **{"return_value": notes}
        )
        value = self.call_mgmt_func(b"admin.vm.notes.Get", b"test-vm1")
        self.assertEqual(value, notes)
        self.app.domains["test-vm1"].get_notes.configure_mock(
            **{"side_effect": qubes.exc.QubesException()}
        )
        with self.assertRaises(qubes.exc.QubesException):
            self.call_mgmt_func(b"admin.vm.notes.Get", b"test-vm1")
        self.assertEqual(
            self.app.domains["test-vm1"].get_notes.mock_calls,
            [unittest.mock.call(), unittest.mock.call()],
        )
        self.assertFalse(self.app.save.called)

    def test_notes_set(self):
        self.app.domains["test-vm1"].set_notes = unittest.mock.Mock()

        # Acceptable note
        payload = b"For Your Eyes Only"
        self.call_mgmt_func(
            b"admin.vm.notes.Set",
            b"test-vm1",
            payload=payload,
        )
        self.app.domains["test-vm1"].set_notes.assert_called_with(
            payload.decode()
        )

        # Note with new-line & tab characters
        payload = b"def python_example_function():\n\tpass"
        self.call_mgmt_func(
            b"admin.vm.notes.Set",
            b"test-vm1",
            payload=payload,
        )
        self.app.domains["test-vm1"].set_notes.assert_called_with(
            payload.decode()
        )

        # Note with un-acceptable character (backspace, non-breaking space, ...)
        payload = "\b\xa0\u200b\u200c\u200d".encode()
        self.call_mgmt_func(
            b"admin.vm.notes.Set",
            b"test-vm1",
            payload=payload,
        )
        self.app.domains["test-vm1"].set_notes.assert_called_with("_____")

        # Invalid UTF8 sequence
        with self.assertRaises(qubes.exc.ProtocolError):
            payload = b"\xd8"
            self.call_mgmt_func(
                b"admin.vm.notes.Set",
                b"test-vm1",
                payload=payload,
            )

        # Unacceptable oversized note
        with self.assertRaises(qubes.exc.ProtocolError):
            payload = ("x" * 256001).encode()
            self.call_mgmt_func(
                b"admin.vm.notes.Set",
                b"test-vm1",
                payload=payload,
            )

    def device_list_testclass(self, vm, event):
        if vm is not self.vm:
            return
        dev = DeviceInfo(
            Port(self.vm, "1234", "testclass"), product="Some device"
        )
        dev.extra_prop = "xx"
        yield dev
        dev = DeviceInfo(
            Port(self.vm, "4321", "testclass"), product="Some other device"
        )
        yield dev

    def assertSerializedEqual(self, actual, expected):
        """
        Works only for props without spaces!
        """
        actual = sorted(actual.split(" "))
        expected = sorted(expected.split(" "))
        self.assertEqual(actual, expected)

    def test_460_vm_device_available(self):
        self.vm.add_handler("device-list:testclass", self.device_list_testclass)
        value = self.call_mgmt_func(
            b"admin.vm.device.testclass.Available", b"test-vm1"
        )
        # the only props with sapces
        value = value.replace("'Some device'", "'Some_device'")
        value = value.replace("'Some other device'", "'Some_other_device'")
        self.assertSerializedEqual(
            value,
            "1234:0000:0000::?****** "
            "device_id='0000:0000::?******' "
            "devclass='testclass' product='Some_device' port_id='1234' "
            "backend_domain='test-vm1' interfaces='?******'\n"
            "4321:0000:0000::?****** "
            "device_id='0000:0000::?******' "
            "devclass='testclass' product='Some_other_device' "
            "port_id='4321' backend_domain='test-vm1' "
            "interfaces='?******'\n",
        )
        self.assertFalse(self.app.save.called)

    def test_461_vm_device_available_specific(self):
        self.vm.add_handler("device-list:testclass", self.device_list_testclass)
        value = self.call_mgmt_func(
            b"admin.vm.device.testclass.Available", b"test-vm1", b"4321"
        )
        value = value.replace("'Some other device'", "'Some_other_device'")
        self.assertSerializedEqual(
            value,
            "4321:0000:0000::?****** "
            "device_id='0000:0000::?******' "
            "devclass='testclass' product='Some_other_device' "
            "port_id='4321' backend_domain='test-vm1' "
            "interfaces='?******'\n",
        )
        self.assertFalse(self.app.save.called)

    def test_462_vm_device_available_invalid(self):
        self.vm.add_handler("device-list:testclass", self.device_list_testclass)
        value = self.call_mgmt_func(
            b"admin.vm.device.testclass.Available",
            b"test-vm1",
            b"no-such-device",
        )
        self.assertEqual(value, "")
        self.assertFalse(self.app.save.called)

    def test_470_vm_device_list_assigned(self):
        assignment = DeviceAssignment(
            VirtualDevice(Port(self.vm, "1234", "testclass")), mode="required"
        )
        self.loop.run_until_complete(
            self.vm.devices["testclass"].assign(assignment)
        )
        value = self.call_mgmt_func(
            b"admin.vm.device.testclass.Assigned", b"test-vm1"
        )
        self.assertEqual(
            value,
            "test-vm1+1234:* device_id='*' port_id='1234' "
            "devclass='testclass' backend_domain='test-vm1' mode='required'\n",
        )
        self.assertFalse(self.app.save.called)

    def test_471_vm_device_list_assigned_options(self):
        assignment = DeviceAssignment(
            VirtualDevice(Port(self.vm, "1234", "testclass")),
            mode="required",
            options={"opt1": "value"},
        )
        self.loop.run_until_complete(
            self.vm.devices["testclass"].assign(assignment)
        )
        assignment = DeviceAssignment(
            VirtualDevice(Port(self.vm, "4321", "testclass")), mode="required"
        )
        self.loop.run_until_complete(
            self.vm.devices["testclass"].assign(assignment)
        )
        value = self.call_mgmt_func(
            b"admin.vm.device.testclass.Assigned", b"test-vm1"
        )
        self.assertEqual(
            value,
            "test-vm1+1234:* device_id='*' port_id='1234' "
            "devclass='testclass' backend_domain='test-vm1' mode='required' "
            "_opt1='value'\n"
            "test-vm1+4321:* device_id='*' port_id='4321' "
            "devclass='testclass' backend_domain='test-vm1' mode='required'\n",
        )
        self.assertFalse(self.app.save.called)

    def device_list_single_attached_testclass(self, vm, event, **kwargs):
        if vm is not self.vm:
            return
        dev = qubes.device_protocol.DeviceInfo(
            Port(self.vm, "1234", devclass="testclass")
        )
        yield (dev, {"attach_opt": "value"})

    def test_472_vm_device_list_attached(self):
        self.vm.add_handler(
            "device-list-attached:testclass",
            self.device_list_single_attached_testclass,
        )
        value = self.call_mgmt_func(
            b"admin.vm.device.testclass.Attached", b"test-vm1"
        )
        self.assertEqual(
            value,
            "test-vm1+1234:0000:0000::?****** "
            "device_id='0000:0000::?******' port_id='1234' "
            "devclass='testclass' backend_domain='test-vm1' mode='manual' "
            "frontend_domain='test-vm1' _attach_opt='value'\n",
        )
        self.assertFalse(self.app.save.called)

    def test_473_vm_device_list_assigned_specific(self):
        assignment = DeviceAssignment(
            VirtualDevice(Port(self.vm, "1234", "testclass")), mode="required"
        )
        self.loop.run_until_complete(
            self.vm.devices["testclass"].assign(assignment)
        )
        assignment = DeviceAssignment(
            VirtualDevice(Port(self.vm, "4321", "testclass")), mode="required"
        )
        self.loop.run_until_complete(
            self.vm.devices["testclass"].assign(assignment)
        )
        value = self.call_mgmt_func(
            b"admin.vm.device.testclass.Assigned",
            b"test-vm1",
            b"test-vm1+1234",
        )
        self.assertEqual(
            value,
            "test-vm1+1234:* device_id='*' port_id='1234' "
            "devclass='testclass' backend_domain='test-vm1' mode='required'\n",
        )
        self.assertFalse(self.app.save.called)

    def device_list_multiple_attached_testclass(self, vm, event, **kwargs):
        if vm is not self.vm:
            return
        dev = qubes.device_protocol.DeviceInfo(
            Port(self.vm, "1234", devclass="testclass")
        )
        yield (dev, {"attach_opt": "value"})
        dev = qubes.device_protocol.DeviceInfo(
            Port(self.vm, "4321", devclass="testclass")
        )
        yield (dev, {"attach_opt": "value"})

    def test_474_vm_device_list_attached_specific(self):
        self.vm.add_handler(
            "device-list-attached:testclass",
            self.device_list_multiple_attached_testclass,
        )
        value = self.call_mgmt_func(
            b"admin.vm.device.testclass.Attached",
            b"test-vm1",
            b"test-vm1+1234",
        )
        self.assertEqual(
            value,
            "test-vm1+1234:0000:0000::?****** "
            "device_id='0000:0000::?******' port_id='1234' "
            "devclass='testclass' backend_domain='test-vm1' "
            "mode='manual' frontend_domain='test-vm1' _attach_opt='value'\n",
        )
        self.assertFalse(self.app.save.called)

    def get_dev(self, *args, **kwargs):
        yield DeviceInfo(
            Port(self.vm, "1234", "testclass"),
            device_id="0000:0000::t000000",
        )

    def test_480_vm_device_attach(self):
        self.vm.add_handler("device-list:testclass", self.device_list_testclass)
        self.vm.add_handler("device-get:testclass", self.get_dev)
        mock_action = unittest.mock.Mock()
        mock_action.return_value = None
        del mock_action._is_coroutine
        self.vm.add_handler(f"device-attach:testclass", mock_action)
        with unittest.mock.patch.object(
            qubes.vm.qubesvm.QubesVM, "is_halted", lambda _: False
        ):
            value = self.call_mgmt_func(
                b"admin.vm.device.testclass.Attach",
                b"test-vm1",
                b"test-vm1+1234:0000:0000::t000000",
            )
        self.assertIsNone(value)
        mock_action.assert_called_once_with(
            self.vm,
            f"device-attach:testclass",
            device=self.vm.devices["testclass"]["1234"],
            options={},
        )
        self.assertEqual(
            len(list(self.vm.devices["testclass"].get_assigned_devices())), 0
        )
        self.assertFalse(self.app.save.called)

    def test_481_vm_device_assign(self):
        self.vm.add_handler("device-list:testclass", self.device_list_testclass)
        mock_action = unittest.mock.Mock()
        mock_action.return_value = None
        del mock_action._is_coroutine
        self.vm.add_handler(f"device-assign:testclass", mock_action)
        with unittest.mock.patch.object(
            qubes.vm.qubesvm.QubesVM, "is_halted", lambda _: False
        ):
            value = self.call_mgmt_func(
                b"admin.vm.device.testclass.Assign",
                b"test-vm1",
                b"test-vm1+1234:0000:0000::?******",
                b"mode='auto-attach'",
            )
        self.assertIsNone(value)
        mock_action.assert_called_once_with(
            self.vm,
            f"device-assign:testclass",
            device=self.vm.devices["testclass"]["1234"],
            options={},
        )
        self.assertEqual(
            len(list(self.vm.devices["testclass"].get_assigned_devices())), 1
        )
        self.app.save.assert_called_once_with()

    def test_483_vm_device_assign_required(self):
        self.vm.add_handler("device-list:testclass", self.device_list_testclass)
        mock_action = unittest.mock.Mock()
        mock_action.return_value = None
        del mock_action._is_coroutine
        self.vm.add_handler(f"device-assign:testclass", mock_action)
        with unittest.mock.patch.object(
            qubes.vm.qubesvm.QubesVM, "is_halted", lambda _: False
        ):
            value = self.call_mgmt_func(
                b"admin.vm.device.testclass.Assign",
                b"test-vm1",
                b"test-vm1+1234:0000:0000::?******",
                b"mode='required'",
            )
        self.assertIsNone(value)
        mock_action.assert_called_once_with(
            self.vm,
            f"device-assign:testclass",
            device=self.vm.devices["testclass"]["1234"],
            options={},
        )
        self.assertEqual(
            len(list(self.vm.devices["testclass"].get_assigned_devices())), 1
        )
        self.app.save.assert_called_once_with()

    def test_484_vm_device_attach_not_running(self):
        self.vm.add_handler("device-list:testclass", self.device_list_testclass)
        mock_action = unittest.mock.Mock()
        del mock_action._is_coroutine
        self.vm.add_handler("device-attach:testclass", mock_action)
        with self.assertRaises(qubes.exc.QubesVMNotRunningError):
            self.call_mgmt_func(
                b"admin.vm.device.testclass.Attach",
                b"test-vm1",
                b"test-vm1+1234:0000:0000::?******",
            )
        self.assertFalse(mock_action.called)
        self.assertEqual(
            len(list(self.vm.devices["testclass"].get_assigned_devices())), 0
        )
        self.assertFalse(self.app.save.called)

    def test_485_vm_device_assign_not_running(self):
        self.vm.add_handler("device-list:testclass", self.device_list_testclass)
        mock_action = unittest.mock.Mock()
        mock_action.return_value = None
        del mock_action._is_coroutine
        self.vm.add_handler("device-assign:testclass", mock_action)
        with unittest.mock.patch.object(
            qubes.vm.qubesvm.QubesVM, "is_halted", lambda _: False
        ):
            self.call_mgmt_func(
                b"admin.vm.device.testclass.Assign",
                b"test-vm1",
                b"test-vm1+1234:0000:0000::?******",
                b"mode='auto-attach'",
            )
        mock_action.assert_called_once_with(
            self.vm,
            f"device-assign:testclass",
            device=self.vm.devices["testclass"]["1234"],
            options={},
        )
        self.assertEqual(
            len(list(self.vm.devices["testclass"].get_assigned_devices())), 1
        )
        self.app.save.assert_called_once_with()

    def test_486_vm_device_assign_required_not_running(self):
        self.vm.add_handler("device-list:testclass", self.device_list_testclass)
        mock_action = unittest.mock.Mock()
        mock_action.return_value = None
        del mock_action._is_coroutine
        self.vm.add_handler("device-assign:testclass", mock_action)
        with unittest.mock.patch.object(
            qubes.vm.qubesvm.QubesVM, "is_halted", lambda _: False
        ):
            self.call_mgmt_func(
                b"admin.vm.device.testclass.Assign",
                b"test-vm1",
                b"test-vm1+1234:0000:0000::?******",
                b"mode='required'",
            )
        mock_action.assert_called_once_with(
            self.vm,
            f"device-assign:testclass",
            device=self.vm.devices["testclass"]["1234"],
            options={},
        )
        self.assertEqual(
            len(list(self.vm.devices["testclass"].get_assigned_devices())), 1
        )
        self.app.save.assert_called_once_with()

    def test_487_vm_device_attach_options(self):
        self.vm.add_handler("device-list:testclass", self.device_list_testclass)
        self.vm.add_handler("device-get:testclass", self.get_dev)
        mock_attach = unittest.mock.Mock()
        mock_attach.return_value = None
        del mock_attach._is_coroutine
        self.vm.add_handler("device-attach:testclass", mock_attach)
        with unittest.mock.patch.object(
            qubes.vm.qubesvm.QubesVM, "is_halted", lambda _: False
        ):
            value = self.call_mgmt_func(
                b"admin.vm.device.testclass.Attach",
                b"test-vm1",
                b"test-vm1+1234:0000:0000::t000000",
                b"_option1='value2'",
            )
        self.assertIsNone(value)
        dev = self.vm.devices["testclass"]["1234"]
        mock_attach.assert_called_once_with(
            self.vm,
            "device-attach:testclass",
            device=dev,
            options={"option1": "value2"},
        )
        self.assertFalse(self.app.save.called)

    def test_488_vm_device_assign_options(self):
        self.vm.add_handler("device-list:testclass", self.device_list_testclass)
        mock_attach = unittest.mock.Mock()
        mock_attach.return_value = None
        del mock_attach._is_coroutine
        self.vm.add_handler("device-assign:testclass", mock_attach)
        with unittest.mock.patch.object(
            qubes.vm.qubesvm.QubesVM, "is_halted", lambda _: False
        ):
            value = self.call_mgmt_func(
                b"admin.vm.device.testclass.Assign",
                b"test-vm1",
                b"test-vm1+1234:0000:0000::?******",
                b"mode='auto-attach' _option1='value2'",
            )
        self.assertIsNone(value)
        dev = self.vm.devices["testclass"]["1234"]
        mock_attach.assert_called_once_with(
            self.vm,
            "device-assign:testclass",
            device=dev,
            options={"option1": "value2"},
        )
        self.app.save.assert_called_once_with()

    def test_489_vm_multiple_device_one_port_assign(self):
        self.vm.add_handler("device-list:testclass", self.device_list_testclass)
        mock_action = unittest.mock.Mock()
        mock_action.return_value = None
        del mock_action._is_coroutine
        self.vm.add_handler(f"device-assign:testclass", mock_action)
        with unittest.mock.patch.object(
            qubes.vm.qubesvm.QubesVM, "is_halted", lambda _: False
        ):
            self.call_mgmt_func(
                b"admin.vm.device.testclass.Assign",
                b"test-vm1",
                b"test-vm1+1234:dead",
                b"mode='auto-attach'",
            )
            mock_action.assert_called_with(
                self.vm,
                f"device-assign:testclass",
                device=VirtualDevice(
                    Port(self.vm, "1234", "testclass"), device_id="dead"
                ),
                options={},
            )
            self.call_mgmt_func(
                b"admin.vm.device.testclass.Assign",
                b"test-vm1",
                b"test-vm1+1234:beef",
                b"mode='auto-attach'",
            )
            mock_action.assert_called_with(
                self.vm,
                f"device-assign:testclass",
                device=VirtualDevice(
                    Port(self.vm, "1234", "testclass"), device_id="beef"
                ),
                options={},
            )

        self.assertEqual(
            len(list(self.vm.devices["testclass"].get_assigned_devices())), 2
        )
        self.app.save.assert_called()

    def test_4890_vm_overlapping_assignments(self):
        self.vm.add_handler("device-list:testclass", self.device_list_testclass)
        mock_action = unittest.mock.Mock()
        mock_action.return_value = None
        del mock_action._is_coroutine
        self.vm.add_handler(f"device-assign:testclass", mock_action)
        with unittest.mock.patch.object(
            qubes.vm.qubesvm.QubesVM, "is_halted", lambda _: False
        ):
            self.call_mgmt_func(
                b"admin.vm.device.testclass.Assign",
                b"test-vm1",
                b"test-vm1+1234:dead",
                b"mode='auto-attach'",
            )
            mock_action.assert_called_with(
                self.vm,
                f"device-assign:testclass",
                device=VirtualDevice(
                    Port(self.vm, "1234", "testclass"), device_id="dead"
                ),
                options={},
            )
            self.call_mgmt_func(
                b"admin.vm.device.testclass.Assign",
                b"test-vm1",
                b"test-vm1+1234:*",
                b"mode='auto-attach'",
            )
            mock_action.assert_called_with(
                self.vm,
                f"device-assign:testclass",
                device=VirtualDevice(
                    Port(self.vm, "1234", "testclass"), device_id="*"
                ),
                options={},
            )
            self.call_mgmt_func(
                b"admin.vm.device.testclass.Assign",
                b"test-vm1",
                b"test-vm1+*:dead",
                b"mode='auto-attach'",
            )
            mock_action.assert_called_with(
                self.vm,
                f"device-assign:testclass",
                device=VirtualDevice(
                    Port(self.vm, "*", "testclass"), device_id="dead"
                ),
                options={},
            )

        self.assertEqual(
            len(list(self.vm.devices["testclass"].get_assigned_devices())), 3
        )
        self.app.save.assert_called()

    def test_490_vm_device_unassign_from_running(self):
        assignment = DeviceAssignment(
            VirtualDevice(
                Port(self.vm, "1234", "testclass"), device_id="dead:beef:cafe"
            ),
            mode="auto-attach",
            options={"opt1": "value"},
        )
        self.loop.run_until_complete(
            self.vm.devices["testclass"].assign(assignment)
        )
        mock_action = unittest.mock.Mock()
        mock_action.return_value = None
        del mock_action._is_coroutine
        self.vm.add_handler("device-unassign:testclass", mock_action)
        with unittest.mock.patch.object(
            qubes.vm.qubesvm.QubesVM, "is_halted", lambda _: False
        ):
            value = self.call_mgmt_func(
                b"admin.vm.device.testclass.Unassign",
                b"test-vm1",
                b"test-vm1+1234:dead:beef:cafe",
            )
        self.assertIsNone(value)
        mock_action.assert_called_once_with(
            self.vm,
            "device-unassign:testclass",
            device=assignment.virtual_device,
        )
        self.app.save.assert_called_once_with()

    def test_491_vm_device_unassign_required_from_running(self):
        assignment = DeviceAssignment(
            VirtualDevice(
                Port(self.vm, "1234", "testclass"), device_id="dead:beef:cafe"
            ),
            mode="required",
            options={"opt1": "value"},
        )
        self.loop.run_until_complete(
            self.vm.devices["testclass"].assign(assignment)
        )
        mock_action = unittest.mock.Mock()
        mock_action.return_value = None
        del mock_action._is_coroutine
        self.vm.add_handler("device-unassign:testclass", mock_action)
        with unittest.mock.patch.object(
            qubes.vm.qubesvm.QubesVM, "is_halted", lambda _: False
        ):
            value = self.call_mgmt_func(
                b"admin.vm.device.testclass.Unassign",
                b"test-vm1",
                b"test-vm1+1234:dead:beef:cafe",
            )
        self.assertIsNone(value)
        mock_action.assert_called_once_with(
            self.vm,
            "device-unassign:testclass",
            device=assignment.virtual_device,
        )
        self.app.save.assert_called_once_with()

    def test_492_vm_device_unassign_from_halted(self):
        assignment = DeviceAssignment(
            VirtualDevice(
                Port(self.vm, "1234", "testclass"), device_id="dead:beef:cafe"
            ),
            mode="required",
            options={"opt1": "value"},
        )
        self.loop.run_until_complete(
            self.vm.devices["testclass"].assign(assignment)
        )
        mock_action = unittest.mock.Mock()
        mock_action.return_value = None
        del mock_action._is_coroutine
        self.vm.add_handler("device-unassign:testclass", mock_action)
        self.call_mgmt_func(
            b"admin.vm.device.testclass.Unassign",
            b"test-vm1",
            b"test-vm1+1234:dead:beef:cafe",
        )
        mock_action.assert_called_once_with(
            self.vm,
            "device-unassign:testclass",
            device=assignment.virtual_device,
        )
        self.app.save.assert_called_once_with()

    def test_493_vm_device_unassign_required_from_halted(self):
        assignment = DeviceAssignment(
            VirtualDevice(
                Port(self.vm, "1234", "testclass"), device_id="dead:beef:cafe"
            ),
            mode="required",
            options={"opt1": "value"},
        )
        self.loop.run_until_complete(
            self.vm.devices["testclass"].assign(assignment)
        )
        mock_action = unittest.mock.Mock()
        mock_action.return_value = None
        del mock_action._is_coroutine
        self.vm.add_handler("device-unassign:testclass", mock_action)
        self.call_mgmt_func(
            b"admin.vm.device.testclass.Unassign",
            b"test-vm1",
            b"test-vm1+1234:dead:beef:cafe",
        )
        mock_action.assert_called_once_with(
            self.vm,
            "device-unassign:testclass",
            device=assignment.virtual_device,
        )
        self.app.save.assert_called_once_with()

    def test_494_vm_device_unassign_attached(self):
        self.vm.add_handler("device-list:testclass", self.device_list_testclass)
        self.vm.add_handler(
            "device-list-attached:testclass",
            self.device_list_single_attached_testclass,
        )
        assignment = DeviceAssignment(
            VirtualDevice(
                Port(self.vm, "1234", "testclass"), device_id="dead:beef:cafe"
            ),
            mode="auto-attach",
            options={"opt1": "value"},
        )
        self.loop.run_until_complete(
            self.vm.devices["testclass"].assign(assignment)
        )
        mock_action = unittest.mock.Mock()
        mock_action.return_value = None
        del mock_action._is_coroutine
        self.vm.add_handler("device-unassign:testclass", mock_action)
        self.call_mgmt_func(
            b"admin.vm.device.testclass.Unassign",
            b"test-vm1",
            b"test-vm1+1234:dead:beef:cafe",
        )
        mock_action.assert_called_once_with(
            self.vm,
            "device-unassign:testclass",
            device=assignment.virtual_device,
        )
        self.app.save.assert_called_once_with()

    def test_495_vm_device_unassign_not_assigned(self):
        mock_detach = unittest.mock.Mock()
        mock_detach.return_value = None
        del mock_detach._is_coroutine
        self.vm.add_handler("device-detach:testclass", mock_detach)
        with unittest.mock.patch.object(
            qubes.vm.qubesvm.QubesVM, "is_halted", lambda _: False
        ):
            with self.assertRaises(qubes.exc.DeviceNotAssigned):
                self.call_mgmt_func(
                    b"admin.vm.device.testclass.Detach",
                    b"test-vm1",
                    b"test-vm1+1234:*",
                )
        self.assertFalse(mock_detach.called)
        self.assertFalse(self.app.save.called)

    def test_496_vm_device_detach(self):
        self.vm.add_handler("device-list:testclass", self.device_list_testclass)
        self.vm.add_handler(
            "device-list-attached:testclass",
            self.device_list_single_attached_testclass,
        )
        mock_detach = unittest.mock.Mock()
        mock_detach.return_value = None
        del mock_detach._is_coroutine
        self.vm.add_handler("device-detach:testclass", mock_detach)
        with unittest.mock.patch.object(
            qubes.vm.qubesvm.QubesVM, "is_halted", lambda _: False
        ):
            value = self.call_mgmt_func(
                b"admin.vm.device.testclass.Detach",
                b"test-vm1",
                b"test-vm1+1234:*",
            )
        self.assertIsNone(value)
        mock_detach.assert_called_once_with(
            self.vm,
            "device-detach:testclass",
            port=self.vm.devices["testclass"]["1234"].port,
        )
        self.assertFalse(self.app.save.called)

    def test_497_vm_device_detach_not_attached(self):
        mock_detach = unittest.mock.Mock()
        mock_detach.return_value = None
        del mock_detach._is_coroutine
        self.vm.add_handler("device-detach:testclass", mock_detach)
        with unittest.mock.patch.object(
            qubes.vm.qubesvm.QubesVM, "is_halted", lambda _: False
        ):
            with self.assertRaises(qubes.exc.DeviceNotAssigned):
                self.call_mgmt_func(
                    b"admin.vm.device.testclass.Detach",
                    b"test-vm1",
                    b"test-vm1+1234",
                )
        self.assertFalse(mock_detach.called)
        self.assertFalse(self.app.save.called)

    @unittest.mock.patch("qubes.storage.Storage.remove")
    @unittest.mock.patch("shutil.rmtree")
    def test_500_vm_remove(self, mock_rmtree, mock_remove):
        mock_remove.side_effect = self.dummy_coro
        value = self.call_mgmt_func(b"admin.vm.Remove", b"test-vm1")
        self.assertIsNone(value)
        mock_rmtree.assert_called_once_with(
            "/tmp/qubes-test-dir/appvms/test-vm1"
        )
        mock_remove.assert_called_once_with()
        self.app.save.assert_called_once_with()

    @unittest.mock.patch("qubes.storage.Storage.remove")
    @unittest.mock.patch("shutil.rmtree")
    def test_501_vm_remove_running(self, mock_rmtree, mock_remove):
        mock_remove.side_effect = self.dummy_coro
        with unittest.mock.patch.object(
            self.vm, "get_power_state", lambda: "Running"
        ):
            with self.assertRaises(qubes.exc.QubesVMNotHaltedError):
                self.call_mgmt_func(b"admin.vm.Remove", b"test-vm1")
        self.assertFalse(mock_rmtree.called)
        self.assertFalse(mock_remove.called)
        self.assertFalse(self.app.save.called)

    @unittest.mock.patch("qubes.storage.Storage.remove")
    @unittest.mock.patch("shutil.rmtree")
    def test_502_vm_remove_attached(self, mock_rmtree, mock_remove):
        self.setup_for_clone()
        assignment = DeviceAssignment(
            VirtualDevice(Port(self.vm, "1234", "testclass")), mode="required"
        )
        self.loop.run_until_complete(
            self.vm2.devices["testclass"].assign(assignment)
        )

        mock_remove.side_effect = self.dummy_coro
        with self.assertRaises(qubes.exc.QubesVMInUseError):
            self.call_mgmt_func(b"admin.vm.Remove", b"test-vm1")
        self.assertFalse(mock_rmtree.called)
        self.assertFalse(mock_remove.called)
        self.assertFalse(self.app.save.called)

    @unittest.mock.patch("qubes.storage.Storage.remove")
    @unittest.mock.patch("shutil.rmtree")
    def test_503_vm_remove_dom0(self, mock_rmtree, mock_remove):
        mock_remove.side_effect = self.dummy_coro
        with self.assertRaises(qubes.exc.QubesVMInUseError):
            self.call_mgmt_func(b"admin.vm.Remove", b"dom0")
        self.assertFalse(mock_rmtree.called)
        self.assertFalse(mock_remove.called)
        self.assertFalse(self.app.save.called)

    # Import tests
    # (internal methods, normally called from qubes-rpc script)

    def test_510_vm_volume_import(self):
        value = self.call_internal_mgmt_func(
            b"internal.vm.volume.ImportBegin", b"test-vm1", b"private"
        )
        self.assertEqual(
            value,
            "{} {}".format(
                2 * 2**30,
                "/tmp/qubes-test-dir/appvms/test-vm1/private-import.img",
            ),
        )
        self.assertFalse(self.app.save.called)

    def test_511_vm_volume_import_running(self):
        with unittest.mock.patch.object(
            self.vm, "get_power_state", lambda: "Running"
        ):
            with self.assertRaises(qubes.exc.QubesVMNotHaltedError):
                self.call_internal_mgmt_func(
                    b"internal.vm.volume.ImportBegin", b"test-vm1", b"private"
                )

    def test_512_vm_volume_import_with_size(self):
        new_size = 4 * 2**30
        file_name = "/tmp/qubes-test-dir/appvms/test-vm1/private-import.img"

        value = self.call_internal_mgmt_func(
            b"internal.vm.volume.ImportBegin",
            b"test-vm1",
            b"private",
            payload=str(new_size).encode(),
        )
        self.assertEqual(value, "{} {}".format(new_size, file_name))
        self.assertFalse(self.app.save.called)

        self.assertEqual(os.stat(file_name).st_size, new_size)

    def test_515_vm_volume_import_fire_event(self):
        self.call_internal_mgmt_func(
            b"internal.vm.volume.ImportBegin", b"test-vm1", b"private"
        )
        self.assertEventFired(
            self.emitter, "admin-permission:admin.vm.volume.Import"
        )

    def test_516_vm_volume_import_fire_event_with_size(self):
        self.call_internal_mgmt_func(
            b"internal.vm.volume.ImportBegin", b"test-vm1", b"private", b"123"
        )
        self.assertEventFired(
            self.emitter, "admin-permission:admin.vm.volume.ImportWithSize"
        )

    def test_510_vm_volume_import_end_success(self):
        (
            import_data_end_mock,
            self.vm.storage.import_data_end,
        ) = self.coroutine_mock()
        self.call_internal_mgmt_func(
            b"internal.vm.volume.ImportEnd",
            b"test-vm1",
            b"private",
            payload=b"ok",
        )
        self.assertEqual(
            import_data_end_mock.mock_calls,
            [unittest.mock.call("private", success=True)],
        )

    def test_510_vm_volume_import_end_failure(self):
        (
            import_data_end_mock,
            self.vm.storage.import_data_end,
        ) = self.coroutine_mock()
        with self.assertRaisesRegex(qubes.exc.QubesException, "error message"):
            self.call_internal_mgmt_func(
                b"internal.vm.volume.ImportEnd",
                b"test-vm1",
                b"private",
                payload=b"fail\nerror message",
            )
        self.assertEqual(
            import_data_end_mock.mock_calls,
            [unittest.mock.call("private", success=False)],
        )

    def setup_for_clone(self):
        self.pool = unittest.mock.MagicMock()
        self.app.pools["test"] = self.pool
        self.vm2 = self.app.add_new_vm(
            "AppVM",
            label="red",
            name="test-vm2",
            template="test-template",
            kernel="",
        )
        self.pool.configure_mock(
            **{
                "volumes": qubes.storage.VolumesCollection(self.pool),
                "init_volume.return_value.pool": self.pool,
                "__str__.return_value": "test",
                "get_volume.side_effect": (
                    lambda vid: (
                        self.vm.volumes["private"]
                        if vid is self.vm.volumes["private"].vid
                        else self.vm2.volumes["private"]
                    )
                ),
            }
        )
        self.loop.run_until_complete(self.vm.create_on_disk(pool="test"))
        self.loop.run_until_complete(self.vm2.create_on_disk(pool="test"))

        # the call replaces self.vm.volumes[...] with result of import
        # operation - make sure it stays as the same object
        self.vm.volumes["private"].import_volume.return_value = self.vm.volumes[
            "private"
        ]
        self.vm2.volumes["private"].import_volume.return_value = (
            self.vm2.volumes["private"]
        )

        self.addCleanup(self.cleanup_for_clone)

    def cleanup_for_clone(self):
        del self.vm2
        del self.pool

    def test_520_vm_volume_clone(self):
        self.setup_for_clone()

        self.vm.volumes["private"].is_running = lambda: False
        self.vm.storage.get_volume = lambda x: x
        self.vm2.storage.get_volume = lambda x: x

        token = self.call_mgmt_func(
            b"admin.vm.volume.CloneFrom", b"test-vm1", b"private", b""
        )
        # token
        self.assertEqual(len(token), 32)
        self.assertFalse(self.app.save.called)
        value = self.call_mgmt_func(
            b"admin.vm.volume.CloneTo", b"test-vm2", b"private", token.encode()
        )
        self.assertIsNone(value)
        self.vm2.volumes["private"].import_volume.assert_called_once_with(
            self.vm.volumes["private"]
        )
        self.vm2.volumes["private"].import_volume.assert_called_once_with(
            self.vm2.volumes["private"]
        )
        self.app.save.assert_called_once_with()

    def test_521_vm_volume_clone_invalid_volume(self):
        self.setup_for_clone()

        self.vm.volumes["private"].is_running = lambda: False
        self.vm.storage.get_volume = lambda x: x
        self.vm2.storage.get_volume = lambda x: x

        with self.assertRaises(qubes.exc.PermissionDenied):
            self.call_mgmt_func(
                b"admin.vm.volume.CloneFrom", b"test-vm1", b"private123", b""
            )
        self.assertNotIn(
            "init_volume().import_volume",
            map(operator.itemgetter(0), self.pool.mock_calls),
        )
        self.assertFalse(self.app.save.called)

    def test_522_vm_volume_clone_invalid_volume2(self):
        self.setup_for_clone()

        self.vm.volumes["private"].is_running = lambda: False
        self.vm.storage.get_volume = lambda x: x
        self.vm2.storage.get_volume = lambda x: x

        token = self.call_mgmt_func(
            b"admin.vm.volume.CloneFrom", b"test-vm1", b"private", b""
        )
        with self.assertRaises(qubes.exc.PermissionDenied):
            self.call_mgmt_func(
                b"admin.vm.volume.CloneTo",
                b"test-vm1",
                b"private123",
                token.encode(),
            )
        self.assertNotIn(
            "init_volume().import_volume",
            map(operator.itemgetter(0), self.pool.mock_calls),
        )
        self.assertFalse(self.app.save.called)

    def test_523_vm_volume_clone_removed_volume(self):
        self.setup_for_clone()

        self.vm.volumes["private"].is_running = lambda: False
        self.vm.storage.get_volume = lambda x: x
        self.vm2.storage.get_volume = lambda x: x

        token = self.call_mgmt_func(
            b"admin.vm.volume.CloneFrom", b"test-vm1", b"private", b""
        )

        def get_volume(vid):
            if vid == self.vm.volumes["private"]:
                raise KeyError(vid)
            else:
                return unittest.mock.DEFAULT

        self.pool.get_volume.side_effect = get_volume
        with self.assertRaises(qubes.exc.PermissionDenied):
            self.call_mgmt_func(
                b"admin.vm.volume.CloneTo",
                b"test-vm1",
                b"private",
                token.encode(),
            )
        self.assertNotIn(
            "init_volume().import_volume",
            map(operator.itemgetter(0), self.pool.mock_calls),
        )
        self.assertFalse(self.app.save.called)

    def test_524_vm_volume_clone_invlid_token(self):
        self.setup_for_clone()

        self.vm.volumes["private"].is_running = lambda: False
        self.vm.storage.get_volume = lambda x: x
        self.vm2.storage.get_volume = lambda x: x

        with self.assertRaises(qubes.exc.PermissionDenied):
            self.call_mgmt_func(
                b"admin.vm.volume.CloneTo",
                b"test-vm1",
                b"private",
                b"no-such-token",
            )
        self.assertNotIn(
            "init_volume().import_volume",
            map(operator.itemgetter(0), self.pool.mock_calls),
        )
        self.assertFalse(self.app.save.called)

    def test_525_vm_volume_clone_snapshots_disabled(self):
        self.setup_for_clone()

        self.vm.volumes["private"].revisions_to_keep = -1
        self.vm.volumes["private"].is_running = lambda: True
        self.vm.storage.get_volume = lambda x: x
        self.vm2.storage.get_volume = lambda x: x

        token = self.call_mgmt_func(
            b"admin.vm.volume.CloneFrom", b"test-vm1", b"private", b""
        )

        with self.assertRaises(qubes.storage.StoragePoolException):
            self.call_mgmt_func(
                b"admin.vm.volume.CloneTo",
                b"test-vm2",
                b"private",
                token.encode(),
            )

    def test_530_tag_list(self):
        self.vm.tags.add("tag1")
        self.vm.tags.add("tag2")
        value = self.call_mgmt_func(b"admin.vm.tag.List", b"test-vm1")
        self.assertEqual(value, "audiovm-dom0\nguivm-dom0\ntag1\ntag2\n")
        self.assertFalse(self.app.save.called)

    def test_540_tag_get(self):
        self.vm.tags.add("tag1")
        value = self.call_mgmt_func(b"admin.vm.tag.Get", b"test-vm1", b"tag1")
        self.assertEqual(value, "1")
        self.assertFalse(self.app.save.called)

    def test_541_tag_get_absent(self):
        value = self.call_mgmt_func(b"admin.vm.tag.Get", b"test-vm1", b"tag1")
        self.assertEqual(value, "0")
        self.assertFalse(self.app.save.called)

    def test_550_tag_remove(self):
        self.vm.tags.add("tag1")
        value = self.call_mgmt_func(
            b"admin.vm.tag.Remove", b"test-vm1", b"tag1"
        )
        self.assertIsNone(value, None)
        self.assertNotIn("tag1", self.vm.tags)
        self.assertTrue(self.app.save.called)

    def test_551_tag_remove_absent(self):
        with self.assertRaises(qubes.exc.QubesTagNotFoundError):
            self.call_mgmt_func(b"admin.vm.tag.Remove", b"test-vm1", b"tag1")
        self.assertFalse(self.app.save.called)

    def test_560_tag_set(self):
        value = self.call_mgmt_func(b"admin.vm.tag.Set", b"test-vm1", b"tag1")
        self.assertIsNone(value)
        self.assertIn("tag1", self.vm.tags)
        self.assertTrue(self.app.save.called)

    def test_561_tag_set_invalid(self):
        with self.assertRaises(ValueError):
            self.call_mgmt_func(b"admin.vm.tag.Set", b"test-vm1", b"+.some-tag")
        self.assertNotIn("+.some-tag", self.vm.tags)
        self.assertFalse(self.app.save.called)

    def test_570_firewall_get(self):
        self.vm.firewall.save = unittest.mock.Mock()
        value = self.call_mgmt_func(b"admin.vm.firewall.Get", b"test-vm1", b"")
        self.assertEqual(value, "action=accept\n")
        self.assertFalse(self.vm.firewall.save.called)
        self.assertFalse(self.app.save.called)

    def test_571_firewall_get_non_default(self):
        self.vm.firewall.save = unittest.mock.Mock()
        self.vm.firewall.rules = [
            qubes.firewall.Rule(
                action="accept", proto="tcp", dstports="1-1024"
            ),
            qubes.firewall.Rule(action="drop", proto="icmp", comment="No ICMP"),
            # should not output expired rule
            qubes.firewall.Rule(
                action="drop", proto="udp", expire="1499450306"
            ),
            qubes.firewall.Rule(
                action="drop", proto="udp", expire="2099450306"
            ),
            qubes.firewall.Rule(action="accept"),
        ]
        value = self.call_mgmt_func(b"admin.vm.firewall.Get", b"test-vm1", b"")
        self.assertEqual(
            value,
            "action=accept proto=tcp dstports=1-1024\n"
            "action=drop proto=icmp comment=No ICMP\n"
            "action=drop expire=2099450306 proto=udp\n"
            "action=accept\n",
        )
        self.assertFalse(self.vm.firewall.save.called)
        self.assertFalse(self.app.save.called)

    def test_580_firewall_set_simple(self):
        self.vm.firewall.save = unittest.mock.Mock()
        value = self.call_mgmt_func(
            b"admin.vm.firewall.Set", b"test-vm1", b"", b"action=accept\n"
        )
        self.assertEqual(self.vm.firewall.rules, ["action=accept"])
        self.assertTrue(self.vm.firewall.save.called)
        self.assertFalse(self.app.save.called)

    def test_581_firewall_set_multi(self):
        self.vm.firewall.save = unittest.mock.Mock()
        rules = [
            qubes.firewall.Rule(
                action="accept", proto="tcp", dstports="1-1024"
            ),
            qubes.firewall.Rule(action="drop", proto="icmp", comment="No ICMP"),
            qubes.firewall.Rule(
                action="drop", proto="udp", expire="1499450306"
            ),
            qubes.firewall.Rule(action="accept"),
        ]
        rules_txt = (
            "action=accept proto=tcp dstports=1-1024\n"
            "action=drop proto=icmp comment=No ICMP\n"
            "action=drop expire=1499450306 proto=udp\n"
            "action=accept\n"
        )
        value = self.call_mgmt_func(
            b"admin.vm.firewall.Set", b"test-vm1", b"", rules_txt.encode()
        )
        self.assertEqual(self.vm.firewall.rules, rules)
        self.assertTrue(self.vm.firewall.save.called)
        self.assertFalse(self.app.save.called)

    def test_582_firewall_set_invalid(self):
        self.vm.firewall.save = unittest.mock.Mock()
        rules_txt = (
            "action=accept protoxyz=tcp dst4=127.0.0.1\n" "action=drop\n"
        )
        with self.assertRaises(ValueError):
            self.call_mgmt_func(
                b"admin.vm.firewall.Set", b"test-vm1", b"", rules_txt.encode()
            )
        self.assertEqual(
            self.vm.firewall.rules, [qubes.firewall.Rule(action="accept")]
        )
        self.assertFalse(self.vm.firewall.save.called)
        self.assertFalse(self.app.save.called)

    def test_583_firewall_set_invalid(self):
        self.vm.firewall.save = unittest.mock.Mock()
        rules_txt = "proto=tcp dstports=1-1024\n" "action=drop\n"
        with self.assertRaises(ValueError):
            self.call_mgmt_func(
                b"admin.vm.firewall.Set", b"test-vm1", b"", rules_txt.encode()
            )
        self.assertEqual(
            self.vm.firewall.rules, [qubes.firewall.Rule(action="accept")]
        )
        self.assertFalse(self.vm.firewall.save.called)
        self.assertFalse(self.app.save.called)

    def test_584_firewall_set_invalid(self):
        self.vm.firewall.save = unittest.mock.Mock()
        rules_txt = "action=accept proto=tcp dstports=1-1024 " "action=drop\n"
        with self.assertRaises(ValueError):
            self.call_mgmt_func(
                b"admin.vm.firewall.Set", b"test-vm1", b"", rules_txt.encode()
            )
        self.assertEqual(
            self.vm.firewall.rules, [qubes.firewall.Rule(action="accept")]
        )
        self.assertFalse(self.vm.firewall.save.called)
        self.assertFalse(self.app.save.called)

    def test_585_firewall_set_invalid(self):
        self.vm.firewall.save = unittest.mock.Mock()
        rules_txt = (
            "action=accept dstports=1-1024 comment=ążźł\n" "action=drop\n"
        )
        with self.assertRaises(UnicodeDecodeError):
            self.call_mgmt_func(
                b"admin.vm.firewall.Set", b"test-vm1", b"", rules_txt.encode()
            )
        self.assertEqual(
            self.vm.firewall.rules, [qubes.firewall.Rule(action="accept")]
        )
        self.assertFalse(self.vm.firewall.save.called)
        self.assertFalse(self.app.save.called)

    def test_590_firewall_reload(self):
        self.vm.firewall.save = unittest.mock.Mock()
        self.app.domains["test-vm1"].fire_event = self.emitter.fire_event
        value = self.call_mgmt_func(
            b"admin.vm.firewall.Reload", b"test-vm1", b""
        )
        self.assertIsNone(value)
        self.assertEventFired(self.emitter, "firewall-changed")
        self.assertFalse(self.vm.firewall.save.called)
        self.assertFalse(self.app.save.called)

    def test_600_backup_info(self):
        backup_profile = (
            "include:\n"
            " - test-vm1\n"
            "destination_vm: test-vm1\n"
            "destination_path: /var/tmp\n"
            "passphrase_text: test\n"
        )
        expected_info = (
            "------------------+--------------+--------------+\n"
            "               VM |         type |         size |\n"
            "------------------+--------------+--------------+\n"
            "         test-vm1 |           VM |            0 |\n"
            "------------------+--------------+--------------+\n"
            "      Total size: |                           0 |\n"
            "------------------+--------------+--------------+\n"
            "VMs not selected for backup:\n"
            " - dom0\n"
            " - test-template\n"
        )
        with tempfile.TemporaryDirectory() as profile_dir:
            with open(
                os.path.join(profile_dir, "testprofile.conf"), "w"
            ) as profile_file:
                profile_file.write(backup_profile)
            with unittest.mock.patch(
                "qubes.config.backup_profile_dir", profile_dir
            ):
                result = self.call_mgmt_func(
                    b"admin.backup.Info", b"dom0", b"testprofile"
                )
            self.assertEqual(result, expected_info)

    def test_601_backup_info_profile_missing_destination_path(self):
        backup_profile = (
            "include:\n"
            " - test-vm1\n"
            "destination_vm: test-vm1\n"
            "passphrase_text: test\n"
        )
        with tempfile.TemporaryDirectory() as profile_dir:
            with open(
                os.path.join(profile_dir, "testprofile.conf"), "w"
            ) as profile_file:
                profile_file.write(backup_profile)
            with unittest.mock.patch(
                "qubes.config.backup_profile_dir", profile_dir
            ):
                with self.assertRaises(qubes.exc.QubesException):
                    self.call_mgmt_func(
                        b"admin.backup.Info", b"dom0", b"testprofile"
                    )

    def test_602_backup_info_profile_missing_destination_vm(self):
        backup_profile = (
            "include:\n"
            " - test-vm1\n"
            "destination_path: /home/user\n"
            "passphrase_text: test\n"
        )
        with tempfile.TemporaryDirectory() as profile_dir:
            with open(
                os.path.join(profile_dir, "testprofile.conf"), "w"
            ) as profile_file:
                profile_file.write(backup_profile)
            with unittest.mock.patch(
                "qubes.config.backup_profile_dir", profile_dir
            ):
                with self.assertRaises(qubes.exc.QubesException):
                    self.call_mgmt_func(
                        b"admin.backup.Info", b"dom0", b"testprofile"
                    )

    def test_610_backup_cancel_not_running(self):
        with self.assertRaises(qubes.exc.QubesException):
            self.call_mgmt_func(b"admin.backup.Cancel", b"dom0", b"testprofile")

    def test_611_backup_already_running(self):
        if not hasattr(self.app, "api_admin_running_backups"):
            self.app.api_admin_running_backups = {}

        self.app.api_admin_running_backups["testprofile"] = "test"
        self.addCleanup(self.app.api_admin_running_backups.pop, "testprofile")

        backup_profile = (
            "include:\n"
            " - test-vm1\n"
            "destination_vm: test-vm1\n"
            "destination_path: /home/user\n"
            "passphrase_text: test\n"
        )

        with tempfile.TemporaryDirectory() as profile_dir:
            with open(
                os.path.join(profile_dir, "testprofile.conf"), "w"
            ) as profile_file:
                profile_file.write(backup_profile)
            with unittest.mock.patch(
                "qubes.config.backup_profile_dir", profile_dir
            ):
                with self.assertRaises(qubes.exc.BackupAlreadyRunningError):
                    self.call_mgmt_func(
                        b"admin.backup.Execute", b"dom0", b"testprofile"
                    )

    def test_612_backup_when_vm_with_disabled_snapshots_is_running(self):
        backup_profile = (
            "include:\n"
            " - test-vm1\n"
            "destination_vm: test-vm1\n"
            "destination_path: /var/tmp\n"
            "passphrase_text: test\n"
        )
        expected_info = (
            "------------------+--------------+--------------+\n"
            "               VM |         type |         size |\n"
            "------------------+--------------+--------------+\n"
            "         test-vm1 |           VM |            0 | <-- The VM is \
running and private volume snapshots are disabled. Backup will fail!\n"
            "------------------+--------------+--------------+\n"
            "      Total size: |                           0 |\n"
            "------------------+--------------+--------------+\n"
            "VMs not selected for backup:\n"
            " - dom0\n"
            " - test-template\n"
        )
        with tempfile.TemporaryDirectory() as profile_dir:
            with open(
                os.path.join(profile_dir, "testprofile.conf"), "w"
            ) as profile_file:
                profile_file.write(backup_profile)
            self.vm.is_running = lambda: True
            self.vm.volumes["private"].revisions_to_keep = -1
            with unittest.mock.patch(
                "qubes.config.backup_profile_dir", profile_dir
            ):
                result = self.call_mgmt_func(
                    b"admin.backup.Info", b"dom0", b"testprofile"
                )
            self.assertEqual(result, expected_info)

    @unittest.mock.patch("qubes.backup.Backup")
    def test_620_backup_execute(self, mock_backup):
        backup_profile = (
            "include:\n"
            " - test-vm1\n"
            "destination_vm: test-vm1\n"
            "destination_path: /home/user\n"
            "passphrase_text: test\n"
        )
        mock_backup.return_value.backup_do.side_effect = self.dummy_coro
        with tempfile.TemporaryDirectory() as profile_dir:
            with open(
                os.path.join(profile_dir, "testprofile.conf"), "w"
            ) as profile_file:
                profile_file.write(backup_profile)
            with unittest.mock.patch(
                "qubes.config.backup_profile_dir", profile_dir
            ):
                result = self.call_mgmt_func(
                    b"admin.backup.Execute", b"dom0", b"testprofile"
                )
        self.assertIsNone(result)
        mock_backup.assert_called_once_with(
            self.app,
            {self.vm},
            set(),
            target_vm=self.vm,
            target_dir="/home/user",
            compressed=True,
            passphrase="test",
        )
        mock_backup.return_value.backup_do.assert_called_once_with()

    @unittest.mock.patch("qubes.backup.Backup")
    def test_621_backup_execute_passphrase_service(self, mock_backup):
        backup_profile = (
            "include:\n"
            " - test-vm1\n"
            "destination_vm: test-vm1\n"
            "destination_path: /home/user\n"
            "passphrase_vm: test-vm1\n"
        )

        async def service_passphrase(*args, **kwargs):
            return (b"pass-from-vm", None)

        mock_backup.return_value.backup_do.side_effect = self.dummy_coro
        self.vm.run_service_for_stdio = unittest.mock.Mock(
            side_effect=service_passphrase
        )
        with tempfile.TemporaryDirectory() as profile_dir:
            with open(
                os.path.join(profile_dir, "testprofile.conf"), "w"
            ) as profile_file:
                profile_file.write(backup_profile)
            with unittest.mock.patch(
                "qubes.config.backup_profile_dir", profile_dir
            ):
                result = self.call_mgmt_func(
                    b"admin.backup.Execute", b"dom0", b"testprofile"
                )
        self.assertIsNone(result)
        mock_backup.assert_called_once_with(
            self.app,
            {self.vm},
            set(),
            target_vm=self.vm,
            target_dir="/home/user",
            compressed=True,
            passphrase=b"pass-from-vm",
        )
        mock_backup.return_value.backup_do.assert_called_once_with()
        self.vm.run_service_for_stdio.assert_called_with(
            "qubes.BackupPassphrase+testprofile"
        )

    @unittest.mock.patch("qubes.backup.Backup")
    def test_622_backup_execute_when_disable_snapshot_vm_running(
        self, mock_backup
    ):
        backup_profile = (
            "include:\n"
            " - test-vm1\n"
            "destination_vm: test-vm1\n"
            "destination_path: /home/user\n"
            "passphrase_text: test\n"
        )
        mock_backup.return_value.backup_do.side_effect = self.dummy_coro
        with tempfile.TemporaryDirectory() as profile_dir:
            with open(
                os.path.join(profile_dir, "testprofile.conf"), "w"
            ) as profile_file:
                profile_file.write(backup_profile)
            with unittest.mock.patch(
                "qubes.config.backup_profile_dir", profile_dir
            ):
                result = self.call_mgmt_func(
                    b"admin.backup.Execute", b"dom0", b"testprofile"
                )
        self.assertIsNone(result)
        mock_backup.assert_called_once_with(
            self.app,
            {self.vm},
            set(),
            target_vm=self.vm,
            target_dir="/home/user",
            compressed=True,
            passphrase="test",
        )
        mock_backup.return_value.backup_do.assert_called_once_with()

    def test_630_vm_stats(self):
        send_event = unittest.mock.Mock(spec=[])

        stats1 = {
            0: {
                "cpu_time": 243951379111104 // 8,
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
        }
        stats2 = copy.deepcopy(stats1)
        stats2[0]["cpu_time"] += 100000000
        stats2[0]["cpu_usage"] = 10
        stats2[0]["cpu_usage_raw"] = 10
        stats2[1]["cpu_usage"] = 5
        stats2[1]["cpu_usage_raw"] = 5
        self.app.host.get_vm_stats = unittest.mock.Mock()
        self.app.host.get_vm_stats.side_effect = [
            (0, stats1),
            (1, stats2),
        ]
        self.app.stats_interval = 1
        mgmt_obj = qubes.api.admin.QubesAdminAPI(
            self.app,
            b"dom0",
            b"admin.vm.Stats",
            b"dom0",
            b"",
            send_event=send_event,
        )

        def cancel_call():
            mgmt_obj.cancel()

        class MockVM(object):
            def __init__(self, name):
                self._name = name

            def name(self):
                return self._name

        loop = asyncio.get_event_loop()
        self.app.vmm.libvirt_conn.lookupByID.side_effect = lambda xid: {
            0: MockVM("Domain-0"),
            1: MockVM("test-template"),
            2: MockVM("test-vm1"),
        }[xid]
        execute_task = asyncio.ensure_future(
            mgmt_obj.execute(untrusted_payload=b"")
        )
        loop.call_later(1.1, cancel_call)
        loop.run_until_complete(execute_task)
        self.assertIsNone(execute_task.result())
        self.assertEventFired(
            self.emitter, "admin-permission:" + "admin.vm.Stats"
        )
        self.assertEqual(
            self.app.host.get_vm_stats.mock_calls,
            [
                unittest.mock.call(None, None, only_vm=None),
                unittest.mock.call(0, stats1, only_vm=None),
            ],
        )
        self.assertEqual(
            send_event.mock_calls,
            [
                unittest.mock.call(self.app, "connection-established"),
                unittest.mock.call(
                    "dom0",
                    "vm-stats",
                    cpu_time=stats1[0]["cpu_time"] // 1000000,
                    cpu_usage=stats1[0]["cpu_usage"],
                    cpu_usage_raw=stats1[0]["cpu_usage_raw"],
                    memory_kb=stats1[0]["memory_kb"],
                ),
                unittest.mock.call(
                    "test-template",
                    "vm-stats",
                    cpu_time=stats1[1]["cpu_time"] // 1000000,
                    cpu_usage=stats1[1]["cpu_usage"],
                    cpu_usage_raw=stats1[1]["cpu_usage_raw"],
                    memory_kb=stats1[1]["memory_kb"],
                ),
                unittest.mock.call(
                    "dom0",
                    "vm-stats",
                    cpu_time=stats2[0]["cpu_time"] // 1000000,
                    cpu_usage=stats2[0]["cpu_usage"],
                    cpu_usage_raw=stats2[0]["cpu_usage_raw"],
                    memory_kb=stats2[0]["memory_kb"],
                ),
                unittest.mock.call(
                    "test-template",
                    "vm-stats",
                    cpu_time=stats2[1]["cpu_time"] // 1000000,
                    cpu_usage=stats2[1]["cpu_usage"],
                    cpu_usage_raw=stats2[1]["cpu_usage_raw"],
                    memory_kb=stats2[1]["memory_kb"],
                ),
            ],
        )

    def test_631_vm_stats_single_vm(self):
        send_event = unittest.mock.Mock(spec=[])

        stats1 = {
            2: {
                "cpu_time": 2849496569205,
                "cpu_usage": 0,
                "cpu_usage_raw": 0,
                "memory_kb": 303916,
            },
        }
        stats2 = copy.deepcopy(stats1)
        stats2[2]["cpu_usage"] = 5
        stats2[2]["cpu_usage_raw"] = 5
        self.app.host.get_vm_stats = unittest.mock.Mock()
        self.app.host.get_vm_stats.side_effect = [
            (0, stats1),
            (1, stats2),
        ]
        self.app.stats_interval = 1
        mgmt_obj = qubes.api.admin.QubesAdminAPI(
            self.app,
            b"dom0",
            b"admin.vm.Stats",
            b"test-vm1",
            b"",
            send_event=send_event,
        )

        def cancel_call():
            mgmt_obj.cancel()

        class MockVM(object):
            def __init__(self, name):
                self._name = name

            def name(self):
                return self._name

        loop = asyncio.get_event_loop()
        self.app.vmm.libvirt_conn.lookupByID.side_effect = lambda xid: {
            0: MockVM("Domain-0"),
            1: MockVM("test-template"),
            2: MockVM("test-vm1"),
        }[xid]
        execute_task = asyncio.ensure_future(
            mgmt_obj.execute(untrusted_payload=b"")
        )
        loop.call_later(1.1, cancel_call)
        loop.run_until_complete(execute_task)
        self.assertIsNone(execute_task.result())
        self.assertEventFired(
            self.emitter, "admin-permission:" + "admin.vm.Stats"
        )
        self.assertEqual(
            self.app.host.get_vm_stats.mock_calls,
            [
                unittest.mock.call(None, None, only_vm=self.vm),
                unittest.mock.call(0, stats1, only_vm=self.vm),
            ],
        )
        self.assertEqual(
            send_event.mock_calls,
            [
                unittest.mock.call(self.app, "connection-established"),
                unittest.mock.call(
                    "test-vm1",
                    "vm-stats",
                    cpu_time=stats1[2]["cpu_time"] // 1000000,
                    cpu_usage=stats1[2]["cpu_usage"],
                    cpu_usage_raw=stats1[2]["cpu_usage_raw"],
                    memory_kb=stats1[2]["memory_kb"],
                ),
                unittest.mock.call(
                    "test-vm1",
                    "vm-stats",
                    cpu_time=stats2[2]["cpu_time"] // 1000000,
                    cpu_usage=stats2[2]["cpu_usage"],
                    cpu_usage_raw=stats2[2]["cpu_usage_raw"],
                    memory_kb=stats2[2]["memory_kb"],
                ),
            ],
        )

    @unittest.mock.patch("qubes.storage.Storage.create")
    def test_640_vm_create_disposable(self, mock_storage):
        mock_storage.side_effect = self.dummy_coro
        self.vm.template_for_dispvms = True
        retval = self.call_mgmt_func(b"admin.vm.CreateDisposable", b"test-vm1")
        self.assertTrue(retval.startswith("disp"))
        self.assertIn(retval, self.app.domains)
        dispvm = self.app.domains[retval]
        self.assertEqual(dispvm.template, self.vm)
        mock_storage.assert_called_once_with()
        self.assertTrue(self.app.save.called)

    @unittest.mock.patch("qubes.storage.Storage.create")
    def test_640_vm_create_disposable_uuid(self, mock_storage):
        mock_storage.side_effect = self.dummy_coro
        self.vm.template_for_dispvms = True
        retval = self.call_mgmt_func(
            b"admin.vm.CreateDisposable", b"test-vm1", payload=b"uuid"
        )
        self.assertRegex(retval, _uuid_regex)
        found = False
        for i in self.app.domains:
            print(i.uuid)
            if i.uuid == uuid.UUID(retval):
                found = True
            self.assertIsInstance(i.uuid, uuid.UUID)
        self.assertTrue(found)
        self.assertIn(uuid.UUID(retval), self.app.domains)
        dispvm = self.app.domains[uuid.UUID(retval)]
        self.assertEqual(dispvm.template, self.vm)
        mock_storage.assert_called_once_with()
        self.assertTrue(self.app.save.called)

    @unittest.mock.patch("qubes.storage.Storage.create")
    def test_641_vm_create_disposable_default(self, mock_storage):
        mock_storage.side_effect = self.dummy_coro
        self.vm.template_for_dispvms = True
        self.app.default_dispvm = self.vm
        retval = self.call_mgmt_func(b"admin.vm.CreateDisposable", b"dom0")
        self.assertTrue(retval.startswith("disp"))
        mock_storage.assert_called_once_with()
        self.assertTrue(self.app.save.called)

    @unittest.mock.patch("qubes.storage.Storage.create")
    def test_642_vm_create_disposable_not_allowed(self, storage_mock):
        storage_mock.side_effect = self.dummy_coro
        with self.assertRaises(qubes.exc.QubesException):
            self.call_mgmt_func(b"admin.vm.CreateDisposable", b"test-vm1")
        self.assertFalse(self.app.save.called)

    @unittest.mock.patch("qubes.vm.dispvm.DispVM._bare_cleanup")
    @unittest.mock.patch("qubes.vm.dispvm.DispVM.start")
    @unittest.mock.patch("qubes.storage.Storage.verify")
    @unittest.mock.patch("qubes.storage.Storage.create")
    def test_643_vm_create_disposable_preload_autostart(
        self,
        mock_storage_create,
        mock_storage_verify,
        mock_dispvm_start,
        mock_bare_cleanup,
    ):
        mock_storage_create.side_effect = self.dummy_coro
        mock_storage_verify.side_effect = self.dummy_coro
        mock_dispvm_start.side_effect = self.dummy_coro
        mock_bare_cleanup.side_effect = self.dummy_coro
        self.vm.template_for_dispvms = True
        self.app.default_dispvm = self.vm
        self.vm.add_handler(
            "domain-preload-dispvm-autostart", self._test_event_handler
        )
        self.vm.features["qrexec"] = "1"
        self.vm.features["supported-rpc.qubes.WaitForRunningSystem"] = "1"
        self.vm.features["preload-dispvm-max"] = "1"
        for _ in range(10):
            if len(self.vm.get_feat_preload()) == 1:
                break
            self.loop.run_until_complete(asyncio.sleep(1))
        else:
            self.fail("didn't preload in time")
        old_preload = self.vm.get_feat_preload()
        retval = self.call_mgmt_func(
            b"admin.vm.CreateDisposable", b"dom0", arg=b"preload-autostart"
        )
        self.assertTrue(
            self._test_event_was_handled(
                self.vm.name, "domain-preload-dispvm-autostart"
            )
        )
        for _ in range(10):
            if (
                old_preload != self.vm.get_feat_preload()
                and self.vm.get_feat_preload() != []
            ):
                break
            self.loop.run_until_complete(asyncio.sleep(1))
        else:
            self.fail("didn't preload again in time")
        dispvm_preload = self.vm.get_feat_preload()
        self.assertEqual(len(dispvm_preload), 1)
        self.assertIsNone(retval)
        self.assertEqual(2, mock_storage_create.call_count)
        self.assertEqual(2, mock_dispvm_start.call_count)
        self.assertTrue(self.app.save.called)

    def test_650_vm_device_set_mode_required(self):
        assignment = DeviceAssignment(
            VirtualDevice(Port(self.vm, "1234", "testclass"), device_id="bee"),
            mode="auto-attach",
            options={"opt1": "value"},
        )
        self.loop.run_until_complete(
            self.vm.devices["testclass"].assign(assignment)
        )
        mock_action = unittest.mock.Mock()
        mock_action.return_value = None
        del mock_action._is_coroutine
        self.vm.add_handler(f"device-assignment-changed:testclass", mock_action)

        with unittest.mock.patch.object(
            qubes.vm.qubesvm.QubesVM, "is_halted", lambda _: False
        ):
            value = self.call_mgmt_func(
                b"admin.vm.device.testclass.Set.assignment",
                b"test-vm1",
                b"test-vm1+1234:bee",
                b"required",
            )

        self.assertIsNone(value)
        dev = DeviceInfo(Port(self.vm, "1234", "testclass"), device_id="bee")
        required = list(
            self.vm.devices["testclass"].get_assigned_devices(
                required_only=True
            )
        )
        self.assertIn(dev, required)
        self.assertEqual(required[0].mode.value, "required")
        self.assertEventFired(
            self.emitter,
            "admin-permission:admin.vm.device.testclass.Set.assignment",
        )
        mock_action.assert_called_once_with(
            self.vm,
            f"device-assignment-changed:testclass",
            device=assignment.virtual_device,
        )
        self.app.save.assert_called_once_with()

    def test_651_vm_device_set_mode_ask(self):
        assignment = DeviceAssignment(
            VirtualDevice(Port(self.vm, "1234", "testclass"), device_id="bee"),
            mode="required",
            options={"opt1": "value"},
        )
        self.loop.run_until_complete(
            self.vm.devices["testclass"].assign(assignment)
        )
        mock_action = unittest.mock.Mock()
        mock_action.return_value = None
        del mock_action._is_coroutine
        self.vm.add_handler(f"device-assignment-changed:testclass", mock_action)

        with unittest.mock.patch.object(
            qubes.vm.qubesvm.QubesVM, "is_halted", lambda _: False
        ):
            value = self.call_mgmt_func(
                b"admin.vm.device.testclass.Set.assignment",
                b"test-vm1",
                b"test-vm1+1234:bee",
                b"ask-to-attach",
            )

        self.assertIsNone(value)
        dev = DeviceInfo(Port(self.vm, "1234", "testclass"), device_id="bee")
        required = self.vm.devices["testclass"].get_assigned_devices(
            required_only=True
        )
        self.assertNotIn(dev, required)
        assignments = list(self.vm.devices["testclass"].get_assigned_devices())
        self.assertEqual(assignments[0].mode.value, "ask-to-attach")
        self.assertEventFired(
            self.emitter,
            "admin-permission:admin.vm.device.testclass.Set.assignment",
        )
        mock_action.assert_called_once_with(
            self.vm,
            f"device-assignment-changed:testclass",
            device=assignment.virtual_device,
        )
        self.app.save.assert_called_once_with()

    def test_652_vm_device_set_mode_auto(self):
        assignment = DeviceAssignment(
            VirtualDevice(Port(self.vm, "1234", "testclass"), device_id="bee"),
            mode="required",
            options={"opt1": "value"},
        )
        self.loop.run_until_complete(
            self.vm.devices["testclass"].assign(assignment)
        )
        mock_action = unittest.mock.Mock()
        mock_action.return_value = None
        del mock_action._is_coroutine
        self.vm.add_handler(f"device-assignment-changed:testclass", mock_action)

        with unittest.mock.patch.object(
            qubes.vm.qubesvm.QubesVM, "is_halted", lambda _: False
        ):
            value = self.call_mgmt_func(
                b"admin.vm.device.testclass.Set.assignment",
                b"test-vm1",
                b"test-vm1+1234:bee",
                b"auto-attach",
            )

        self.assertIsNone(value)
        dev = DeviceInfo(Port(self.vm, "1234", "testclass"), device_id="bee")
        required = self.vm.devices["testclass"].get_assigned_devices(
            required_only=True
        )
        self.assertNotIn(dev, required)
        assignments = list(self.vm.devices["testclass"].get_assigned_devices())
        self.assertEqual(assignments[0].mode.value, "auto-attach")
        self.assertEventFired(
            self.emitter,
            "admin-permission:admin.vm.device.testclass.Set.assignment",
        )
        mock_action.assert_called_once_with(
            self.vm,
            f"device-assignment-changed:testclass",
            device=assignment.virtual_device,
        )
        self.app.save.assert_called_once_with()

    def test_653_vm_device_set_mode_unchanged(self):
        assignment = DeviceAssignment(
            VirtualDevice(Port(self.vm, "1234", "testclass"), device_id="bee"),
            mode="required",
            options={"opt1": "value"},
        )
        self.loop.run_until_complete(
            self.vm.devices["testclass"].assign(assignment)
        )
        with unittest.mock.patch.object(
            qubes.vm.qubesvm.QubesVM, "is_halted", lambda _: False
        ):
            value = self.call_mgmt_func(
                b"admin.vm.device.testclass.Set.assignment",
                b"test-vm1",
                b"test-vm1+1234:bee",
                b"required",
            )
        self.assertIsNone(value)
        dev = DeviceInfo(Port(self.vm, "1234", "testclass"), device_id="bee")
        required = self.vm.devices["testclass"].get_assigned_devices(
            required_only=True
        )
        self.assertIn(dev, required)
        self.app.save.assert_called_once_with()

    def test_654_vm_device_set_mode_not_assigned(self):
        self.vm.add_handler("device-list:testclass", self.device_list_testclass)
        with unittest.mock.patch.object(
            qubes.vm.qubesvm.QubesVM, "is_halted", lambda _: False
        ):
            with self.assertRaises(qubes.exc.QubesValueError):
                self.call_mgmt_func(
                    b"admin.vm.device.testclass.Set.assignment",
                    b"test-vm1",
                    b"test-vm1+1234",
                    b"required",
                )
        dev = qubes.device_protocol.DeviceInfo(
            Port(self.vm, "1234", "testclass")
        )
        self.assertNotIn(
            dev, self.vm.devices["testclass"].get_assigned_devices()
        )
        self.assertFalse(self.app.save.called)

    def test_655_vm_device_set_mode_invalid_value(self):
        self.vm.add_handler("device-list:testclass", self.device_list_testclass)
        with unittest.mock.patch.object(
            qubes.vm.qubesvm.QubesVM, "is_halted", lambda _: False
        ):
            with self.assertRaises(qubes.exc.PermissionDenied):
                self.call_mgmt_func(
                    b"admin.vm.device.testclass.Set.assignment",
                    b"test-vm1",
                    b"test-vm1+1234",
                    b"True",
                )
        dev = qubes.device_protocol.DeviceInfo(
            Port(self.vm, "1234", "testclass")
        )
        self.assertNotIn(
            dev, self.vm.devices["testclass"].get_assigned_devices()
        )
        self.assertFalse(self.app.save.called)

    def test_660_vm_device_denied_list_empty(self):
        actual = self.call_mgmt_func(
            b"admin.vm.device.denied.List", b"test-vm1"
        )
        self.assertEqual(actual, "")
        self.assertFalse(self.app.save.called)

    def test_661_vm_device_denied_list(self):
        self.vm.devices_denied = "b******p012345pff**2*"
        actual = self.call_mgmt_func(
            b"admin.vm.device.denied.List", b"test-vm1"
        )
        self.assertEqual(actual, "b******\np012345\npff**2*")
        self.assertFalse(self.app.save.called)

    def test_662_vm_device_denied_add(self):
        self.vm.devices_denied = "b******p012345p53**2*"
        self.call_mgmt_func(
            b"admin.vm.device.denied.Add", b"test-vm1", b"", b"uabcdef"
        )
        self.assertEqual(self.vm.devices_denied, "b******p012345p53**2*uabcdef")
        self.assertTrue(self.app.save.called)

    def test_663_vm_device_denied_add_multiple(self):
        self.vm.devices_denied = "b******p012345p53**2*"
        self.call_mgmt_func(
            b"admin.vm.device.denied.Add", b"test-vm1", b"", b"uabcdefm******"
        )
        self.assertEqual(
            self.vm.devices_denied, "b******m******p012345p53**2*uabcdef"
        )
        self.assertTrue(self.app.save.called)

    def test_664_vm_device_denied_add_repeated(self):
        self.vm.devices_denied = "b******p012345p53**2*"
        with self.assertRaises(qubes.exc.QubesValueError):
            self.call_mgmt_func(
                b"admin.vm.device.denied.Add",
                b"test-vm1",
                b"",
                b"u112233u112233",
            )
        self.assertEqual(self.vm.devices_denied, "b******p012345p53**2*")
        self.assertFalse(self.app.save.called)

    def test_665_vm_device_denied_add_present(self):
        self.vm.devices_denied = "b******p012345p53**2*"
        self.call_mgmt_func(
            b"admin.vm.device.denied.Add", b"test-vm1", b"", b"b******"
        )
        self.assertEqual(self.vm.devices_denied, "b******p012345p53**2*")
        self.assertFalse(self.app.save.called)

    def test_666_vm_device_denied_add_nothing(self):
        self.vm.devices_denied = "b******p012345p53**2*"
        self.call_mgmt_func(
            b"admin.vm.device.denied.Add", b"test-vm1", b"", b""
        )
        self.assertEqual(self.vm.devices_denied, "b******p012345p53**2*")
        self.assertFalse(self.app.save.called)

    def test_670_vm_device_denied_remove(self):
        self.vm.devices_denied = "b******p012345p53**2*"
        self.call_mgmt_func(
            b"admin.vm.device.denied.Remove", b"test-vm1", b"", b"b******"
        )
        self.assertEqual(self.vm.devices_denied, "p012345p53**2*")
        self.assertTrue(self.app.save.called)

    def test_671_vm_device_denied_remove_repeated(self):
        self.vm.devices_denied = "b******p012345p53**2*"
        with self.assertRaises(qubes.exc.QubesValueError):
            self.call_mgmt_func(
                b"admin.vm.device.denied.Remove",
                b"test-vm1",
                b"",
                b"b******b******",
            )
        self.assertEqual(self.vm.devices_denied, "b******p012345p53**2*")
        self.assertFalse(self.app.save.called)

    def test_672_vm_device_denied_remove_all(self):
        self.vm.devices_denied = "b******p012345p53**2*"
        self.call_mgmt_func(
            b"admin.vm.device.denied.Remove", b"test-vm1", b"", b"all"
        )
        self.assertEqual(self.vm.devices_denied, "")
        self.assertTrue(self.app.save.called)

    def test_673_vm_device_denied_remove_missing(self):
        self.vm.devices_denied = "b******p012345p53**2*"
        self.call_mgmt_func(
            b"admin.vm.device.denied.Remove", b"test-vm1", b"", b"m******"
        )
        self.assertEqual(self.vm.devices_denied, "b******p012345p53**2*")
        self.assertFalse(self.app.save.called)

    def test_673_vm_device_denied_remove_missing_and_present(self):
        self.vm.devices_denied = "b******p012345p53**2*"
        self.call_mgmt_func(
            b"admin.vm.device.denied.Remove",
            b"test-vm1",
            b"",
            b"m******p53**2*",
        )
        self.assertEqual(self.vm.devices_denied, "b******p012345")
        self.assertTrue(self.app.save.called)

    def test_674_vm_device_denied_remove_nothing(self):
        self.vm.devices_denied = "b******p012345p53**2*"
        self.call_mgmt_func(
            b"admin.vm.device.denied.Remove", b"test-vm1", b"", b""
        )
        self.assertEqual(self.vm.devices_denied, "b******p012345p53**2*")
        self.assertFalse(self.app.save.called)

    def test_700_pool_set_revisions_to_keep(self):
        self.app.pools["test-pool"] = unittest.mock.Mock()
        value = self.call_mgmt_func(
            b"admin.pool.Set.revisions_to_keep", b"dom0", b"test-pool", b"2"
        )
        self.assertIsNone(value)
        self.assertEqual(self.app.pools["test-pool"].mock_calls, [])
        self.assertEqual(self.app.pools["test-pool"].revisions_to_keep, 2)
        self.app.save.assert_called_once_with()

    def test_701_pool_set_revisions_to_keep_negative(self):
        self.app.pools["test-pool"] = unittest.mock.Mock()
        with self.assertRaises(qubes.exc.ProtocolError):
            self.call_mgmt_func(
                b"admin.pool.Set.revisions_to_keep",
                b"dom0",
                b"test-pool",
                b"-2",
            )
        self.assertEqual(self.app.pools["test-pool"].mock_calls, [])
        self.assertFalse(self.app.save.called)

    def test_702_pool_set_revisions_to_keep_not_a_number(self):
        self.app.pools["test-pool"] = unittest.mock.Mock()
        with self.assertRaises(qubes.exc.ProtocolError):
            self.call_mgmt_func(
                b"admin.pool.Set.revisions_to_keep",
                b"dom0",
                b"test-pool",
                b"abc",
            )
        self.assertEqual(self.app.pools["test-pool"].mock_calls, [])
        self.assertFalse(self.app.save.called)

    def test_703_pool_set_ephemeral(self):
        self.app.pools["test-pool"] = unittest.mock.Mock()
        value = self.call_mgmt_func(
            b"admin.pool.Set.ephemeral_volatile",
            b"dom0",
            b"test-pool",
            b"true",
        )
        self.assertIsNone(value)
        self.assertEqual(self.app.pools["test-pool"].mock_calls, [])
        self.assertEqual(self.app.pools["test-pool"].ephemeral_volatile, True)
        self.app.save.assert_called_once_with()

    def test_704_pool_set_ephemeral_not_a_boolean(self):
        self.app.pools["test-pool"] = unittest.mock.Mock()
        with self.assertRaises(qubes.exc.ProtocolError):
            self.call_mgmt_func(
                b"admin.pool.Set.ephemeral_volatile",
                b"dom0",
                b"test-pool",
                b"abc",
            )
        self.assertEqual(self.app.pools["test-pool"].mock_calls, [])
        self.assertFalse(self.app.save.called)

    def test_710_vm_volume_set_revisions_to_keep(self):
        self.vm.volumes = unittest.mock.MagicMock()
        volumes_conf = {
            "keys.return_value": ["root", "private", "volatile", "kernel"],
        }
        self.vm.volumes.configure_mock(**volumes_conf)
        value = self.call_mgmt_func(
            b"admin.vm.volume.Set.revisions_to_keep",
            b"test-vm1",
            b"private",
            b"2",
        )
        self.assertIsNone(value)
        self.assertIn(
            ("__getitem__", ("private",), {}), self.vm.volumes.mock_calls
        )
        self.assertEqual(self.vm.volumes["private"].revisions_to_keep, 2)
        self.app.save.assert_called_once_with()

    def test_711_vm_volume_set_revisions_to_keep_negative(self):
        self.vm.volumes = unittest.mock.MagicMock()
        volumes_conf = {
            "keys.return_value": ["root", "private", "volatile", "kernel"],
        }
        self.vm.volumes.configure_mock(**volumes_conf)
        with self.assertRaises(qubes.exc.QubesValueError):
            self.call_mgmt_func(
                b"admin.vm.volume.Set.revisions_to_keep",
                b"test-vm1",
                b"private",
                b"-2",
            )

    def test_712_vm_volume_set_revisions_to_keep_not_a_number(self):
        self.vm.volumes = unittest.mock.MagicMock()
        volumes_conf = {
            "keys.return_value": ["root", "private", "volatile", "kernel"],
        }
        self.vm.volumes.configure_mock(**volumes_conf)
        with self.assertRaises(qubes.api.ProtocolError):
            self.call_mgmt_func(
                b"admin.vm.volume.Set.revisions_to_keep",
                b"test-vm1",
                b"private",
                b"abc",
            )

    def test_713_vm_volume_disable_snapshots_while_running(self):
        self.vm.volumes = unittest.mock.MagicMock()
        volumes_conf = {
            "keys.return_value": ["root", "private", "volatile", "kernel"],
        }
        self.vm.volumes.configure_mock(**volumes_conf)
        with unittest.mock.patch.object(self.vm, "is_running") as _mock:
            _mock.return_value = True
            with self.assertRaises(qubes.exc.QubesVMNotHaltedError):
                self.call_mgmt_func(
                    b"admin.vm.volume.Set.revisions_to_keep",
                    b"test-vm1",
                    b"private",
                    b"-1",
                )

    def test_714_vm_volume_re_enable_snapshots_while_running(self):
        self.vm.volumes = unittest.mock.MagicMock()
        volumes_conf = {
            "keys.return_value": ["root", "private", "volatile", "kernel"],
        }
        self.vm.volumes.configure_mock(**volumes_conf)
        self.vm.volumes["private"].revisions_to_keep = -1
        with unittest.mock.patch.object(self.vm, "is_running") as _mock:
            _mock.return_value = True
            with self.assertRaises(qubes.exc.QubesVMNotHaltedError):
                self.call_mgmt_func(
                    b"admin.vm.volume.Set.revisions_to_keep",
                    b"test-vm1",
                    b"private",
                    b"2",
                )

    def test_715_start_volume_sourcing_running_volume_without_snapshot(self):
        self.vm.volumes = {
            "root": unittest.mock.Mock(),
            "private": unittest.mock.Mock(),
            "volatile": unittest.mock.Mock(),
            "kernel": unittest.mock.Mock(),
        }
        self.vm.volumes["private"].source = unittest.mock.Mock()
        self.vm.volumes["private"].source.snapshots_disabled = True
        self.vm.volumes["private"].source.is_running.return_value = True
        with self.assertRaises(qubes.exc.QubesVMError):
            self.loop.run_until_complete(
                asyncio.wait_for(self.vm.storage.start(), 1)
            )

    def test_716_enable_or_disable_snapshots_while_dispvm_running(self):
        self.vm.volumes = unittest.mock.MagicMock()
        volumes_conf = {
            "keys.return_value": ["root", "private", "volatile", "kernel"],
        }
        self.vm.volumes.configure_mock(**volumes_conf)
        self.vm.volumes["private"].revisions_to_keep = 2

        fake_running_dispvm = unittest.mock.MagicMock()
        fake_running_dispvm.is_running.return_value = True
        type(self.vm).dispvms = unittest.mock.PropertyMock(
            return_value=[fake_running_dispvm]
        )

        # Trying to disable snapshot on a VM having a running DispVM based on
        # it and currently running
        with self.assertRaises(qubes.exc.QubesVMNotHaltedError):
            self.call_mgmt_func(
                b"admin.vm.volume.Set.revisions_to_keep",
                b"test-vm1",
                b"private",
                b"-1",
            )

        # Trying to renable snapshot on a VM having a running DispVM based on
        # it and currently running
        self.vm.volumes["private"].revisions_to_keep = -1
        with self.assertRaises(qubes.exc.QubesVMNotHaltedError):
            self.call_mgmt_func(
                b"admin.vm.volume.Set.revisions_to_keep",
                b"test-vm1",
                b"private",
                b"1",
            )

        # Changing the number of revisions should work
        self.vm.volumes["private"].revisions_to_keep = 1
        self.call_mgmt_func(
            b"admin.vm.volume.Set.revisions_to_keep",
            b"test-vm1",
            b"private",
            b"2",
        )

    def test_720_vm_volume_set_rw(self):
        self.vm.volumes = unittest.mock.MagicMock()
        volumes_conf = {
            "keys.return_value": ["root", "private", "volatile", "kernel"],
        }
        self.vm.volumes.configure_mock(**volumes_conf)
        self.vm.storage = unittest.mock.Mock()
        value = self.call_mgmt_func(
            b"admin.vm.volume.Set.rw", b"test-vm1", b"private", b"True"
        )
        self.assertIsNone(value)
        self.assertEqual(
            self.vm.volumes.mock_calls,
            [unittest.mock.call.keys(), ("__getitem__", ("private",), {})],
        )
        self.assertEqual(self.vm.volumes["private"].rw, True)
        self.app.save.assert_called_once_with()

    def test_721_vm_volume_set_rw_invalid(self):
        self.vm.volumes = unittest.mock.MagicMock()
        volumes_conf = {
            "keys.return_value": ["root", "private", "volatile", "kernel"],
        }
        self.vm.volumes.configure_mock(**volumes_conf)
        self.vm.storage = unittest.mock.Mock()
        with self.assertRaises(qubes.exc.ProtocolError):
            self.call_mgmt_func(
                b"admin.vm.volume.Set.rw", b"test-vm1", b"private", b"abc"
            )
        self.assertFalse(self.app.save.called)

    def test_725_vm_volume_set_ephemeral(self):
        self.vm.volumes = unittest.mock.MagicMock()
        volumes_conf = {
            "keys.return_value": ["root", "private", "volatile", "kernel"],
        }
        self.vm.volumes.configure_mock(**volumes_conf)
        self.vm.storage = unittest.mock.Mock()
        value = self.call_mgmt_func(
            b"admin.vm.volume.Set.ephemeral", b"test-vm1", b"volatile", b"True"
        )
        self.assertIsNone(value)
        self.assertEqual(
            self.vm.volumes.mock_calls,
            [unittest.mock.call.keys(), ("__getitem__", ("volatile",), {})],
        )
        self.assertEqual(self.vm.volumes["volatile"].ephemeral, True)
        self.app.save.assert_called_once_with()

    def test_726_vm_volume_set_ephemeral_invalid(self):
        self.vm.volumes = unittest.mock.MagicMock()
        volumes_conf = {
            "keys.return_value": ["root", "private", "volatile", "kernel"],
        }
        self.vm.volumes.configure_mock(**volumes_conf)
        self.vm.storage = unittest.mock.Mock()
        with self.assertRaises(qubes.exc.ProtocolError):
            self.call_mgmt_func(
                b"admin.vm.volume.Set.ephemeral",
                b"test-vm1",
                b"volatile",
                b"abc",
            )
        self.assertFalse(self.app.save.called)

    def test_730_vm_console(self):
        self.vm._libvirt_domain = unittest.mock.Mock()
        xml_desc = (
            "<domain type='xen' id='42'>\n"
            "<name>test-vm1</name>\n"
            "<devices>\n"
            "<console type='pty' tty='/dev/pts/42'>\n"
            "<source path='/dev/pts/42'/>\n"
            "<target type='xen' port='0'/>\n"
            "</console>\n"
            "</devices>\n"
            "</domain>\n"
        )
        self.vm._libvirt_domain.configure_mock(
            **{"XMLDesc.return_value": xml_desc, "isActive.return_value": True}
        )
        self.app.vmm.configure_mock(offline_mode=False)
        value = self.call_mgmt_func(b"admin.vm.Console", b"test-vm1")
        self.assertEqual(value, "/dev/pts/42")

    def test_731_vm_console_not_running(self):
        self.vm._libvirt_domain = unittest.mock.Mock()
        xml_desc = (
            "<domain type='xen' id='42'>\n"
            "<name>test-vm1</name>\n"
            "<devices>\n"
            "<console type='pty' tty='/dev/pts/42'>\n"
            "<source path='/dev/pts/42'/>\n"
            "<target type='xen' port='0'/>\n"
            "</console>\n"
            "</devices>\n"
            "</domain>\n"
        )
        self.vm._libvirt_domain.configure_mock(
            **{
                "XMLDesc.return_value": xml_desc,
                "isActive.return_value": False,
            }
        )
        with self.assertRaises(qubes.exc.QubesVMNotRunningError):
            self.call_mgmt_func(b"admin.vm.Console", b"test-vm1")

    def test_800_pool_volume_list(self):
        self.app.pools = {
            "pool1": unittest.mock.Mock(
                config={"param1": "value1", "param2": "value2"},
                usage=102400,
                size=204800,
                volumes={
                    "vol1": unittest.mock.Mock(),
                    "vol2": unittest.mock.Mock(),
                },
            )
        }
        value = self.call_mgmt_func(
            b"admin.pool.volume.List", b"dom0", b"pool1"
        )
        self.assertEqual(value, "vol1\nvol2\n")

    def test_810_vm_volume_clear(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpfile = os.path.join(tmpdir, "testfile")

            async def coroutine_mock(*args, **kwargs):
                return tmpfile

            self.vm.volumes = unittest.mock.MagicMock()
            volumes_conf = {
                "keys.return_value": ["root", "private", "volatile", "kernel"],
                "__getitem__.return_value.size": 0xDEADBEEF,
            }
            self.vm.volumes.configure_mock(**volumes_conf)
            self.vm.storage = unittest.mock.Mock()
            storage_conf = {
                "import_data.side_effect": coroutine_mock,
                "import_data_end.side_effect": self.dummy_coro,
            }
            self.vm.storage.configure_mock(**storage_conf)
            self.app.domains["test-vm1"].fire_event = self.emitter.fire_event
            value = self.call_mgmt_func(
                b"admin.vm.volume.Clear", b"test-vm1", b"private"
            )
            self.assertIsNone(value)
            self.assertTrue(os.path.exists(tmpfile))
            self.assertEqual(
                self.vm.volumes.mock_calls,
                [
                    unittest.mock.call.keys(),
                    unittest.mock.call.__getattr__("__getitem__")("private"),
                ],
            )
            self.assertEqual(
                self.vm.storage.mock_calls,
                [
                    unittest.mock.call.import_data("private", 0xDEADBEEF),
                    unittest.mock.call.import_data_end("private", True),
                ],
            )
            self.assertEventFired(
                self.emitter, "admin-permission:admin.vm.volume.Clear"
            )
            self.assertEventFired(self.emitter, "domain-volume-import-begin")
            self.assertEventFired(self.emitter, "domain-volume-import-end")

    def test_900_current_state_default(self):
        value = self.call_mgmt_func(b"admin.vm.CurrentState", b"test-vm1")
        self.assertEqual(
            value, "mem=0 mem_static_max=0 cputime=0 power_state=Halted"
        )

    def test_901_current_state_changed(self):
        self.vm.get_mem = lambda: 512
        self.vm.get_mem_static_max = lambda: 1024
        self.vm.get_cputime = lambda: 100
        self.vm.get_power_state = lambda: "Running"
        value = self.call_mgmt_func(b"admin.vm.CurrentState", b"test-vm1")
        self.assertEqual(
            value,
            "mem=512 mem_static_max=1024 cputime=100 power_state=Running",
        )

    def test_990_vm_unexpected_payload(self):
        methods_with_no_payload = [
            b"admin.vm.List",
            b"admin.vm.Remove",
            b"admin.vm.property.List",
            b"admin.vm.property.Get",
            b"admin.vm.property.Help",
            # b"admin.vm.property.HelpRst",
            b"admin.vm.property.Reset",
            b"admin.vm.feature.List",
            b"admin.vm.feature.Get",
            b"admin.vm.feature.CheckWithTemplate",
            b"admin.vm.feature.Remove",
            b"admin.vm.tag.List",
            b"admin.vm.tag.Get",
            b"admin.vm.tag.Remove",
            b"admin.vm.tag.Set",
            b"admin.vm.firewall.Get",
            b"admin.vm.firewall.Reload",
            b"admin.deviceclass.List",
            b"admin.vm.device.pci.Available",
            b"admin.vm.device.pci.Assigned",
            b"admin.vm.device.pci.Attached",
            b"admin.vm.device.pci.Unassign",
            b"admin.vm.device.pci.Detach",
            b"admin.vm.device.denied.List",
            b"admin.vm.volume.ListSnapshots",
            b"admin.vm.volume.List",
            b"admin.vm.volume.Info",
            b"admin.vm.Start",
            b"admin.vm.Shutdown",
            b"admin.vm.Pause",
            b"admin.vm.Unpause",
            b"admin.vm.Kill",
            b"admin.vm.Console",
            b"admin.Events",
            b"admin.vm.feature.List",
            b"admin.vm.feature.Get",
            b"admin.vm.feature.Remove",
            b"admin.vm.feature.CheckWithTemplate",
        ]
        # make sure also no methods on actual VM gets called
        vm_mock = unittest.mock.MagicMock()
        vm_mock.name = self.vm.name
        vm_mock.qid = self.vm.qid
        vm_mock.__lt__ = lambda x, y: x.qid < y.qid
        self.app.domains._dict[self.vm.qid] = vm_mock
        for method in methods_with_no_payload:
            # should reject payload regardless of having argument or not
            with self.subTest(method.decode("ascii")):
                with self.assertRaises(qubes.exc.ProtocolError):
                    self.call_mgmt_func(
                        method, b"test-vm1", b"", b"unexpected-payload"
                    )
                self.assertFalse(vm_mock.called)
                self.assertFalse(self.app.save.called)

            with self.subTest(method.decode("ascii") + "+arg"):
                with self.assertRaises(qubes.exc.ProtocolError):
                    self.call_mgmt_func(
                        method, b"test-vm1", b"some-arg", b"unexpected-payload"
                    )
                self.assertFalse(vm_mock.called)
                self.assertFalse(self.app.save.called)

    def test_991_vm_unexpected_argument(self):
        methods_with_no_argument = [
            b"admin.vm.List",
            b"admin.vm.Remove",
            b"admin.vm.property.List",
            b"admin.vm.feature.List",
            b"admin.vm.tag.List",
            b"admin.vm.firewall.Get",
            b"admin.vm.firewall.Set",
            b"admin.vm.firewall.Reload",
            b"admin.deviceclass.List",
            b"admin.vm.device.denied.List",
            b"admin.vm.volume.List",
            b"admin.vm.Start",
            b"admin.vm.Pause",
            b"admin.vm.Unpause",
            b"admin.vm.Kill",
            b"admin.vm.Console",
            b"admin.Events",
            b"admin.vm.feature.List",
        ]
        # make sure also no methods on actual VM gets called
        vm_mock = unittest.mock.MagicMock()
        vm_mock.name = self.vm.name
        vm_mock.qid = self.vm.qid
        vm_mock.__lt__ = lambda x, y: x.qid < y.qid
        self.app.domains._dict[self.vm.qid] = vm_mock
        exceptions = (qubes.exc.PermissionDenied, qubes.exc.ProtocolError)
        for method in methods_with_no_argument:
            # should reject argument regardless of having payload or not
            with self.subTest(method.decode("ascii")):
                with self.assertRaises(qubes.exc.PermissionDenied):
                    self.call_mgmt_func(method, b"test-vm1", b"some-arg", b"")
                self.assertFalse(vm_mock.called)
                self.assertFalse(self.app.save.called)

            with self.subTest(method.decode("ascii") + "+payload"):
                with self.assertRaises(exceptions):
                    self.call_mgmt_func(
                        method, b"test-vm1", b"unexpected-arg", b"some-payload"
                    )
                self.assertFalse(vm_mock.called)
                self.assertFalse(self.app.save.called)

    def test_992_dom0_unexpected_payload(self):
        methods_with_no_payload = [
            b"admin.deviceclass.List",
            b"admin.vmclass.List",
            b"admin.vm.List",
            b"admin.pool.volume.List",
            b"admin.label.List",
            b"admin.label.Get",
            b"admin.label.Remove",
            b"admin.property.List",
            b"admin.property.Get",
            b"admin.property.Help",
            # b"admin.property.HelpRst",
            b"admin.property.Reset",
            b"admin.pool.List",
            b"admin.pool.ListDrivers",
            b"admin.pool.Info",
            b"admin.pool.Remove",
            b"admin.backup.Execute",
            b"admin.Events",
        ]
        # make sure also no methods on actual VM gets called
        vm_mock = unittest.mock.MagicMock()
        vm_mock.name = self.vm.name
        vm_mock.qid = self.vm.qid
        vm_mock.__lt__ = lambda x, y: x.qid < y.qid
        self.app.domains._dict[self.vm.qid] = vm_mock
        for method in methods_with_no_payload:
            # should reject payload regardless of having argument or not
            with self.subTest(method.decode("ascii")):
                with self.assertRaises(qubes.exc.ProtocolError):
                    self.call_mgmt_func(
                        method, b"dom0", b"", b"unexpected-payload"
                    )
                self.assertFalse(vm_mock.called)
                self.assertFalse(self.app.save.called)

            with self.subTest(method.decode("ascii") + "+arg"):
                with self.assertRaises(qubes.exc.ProtocolError):
                    self.call_mgmt_func(
                        method, b"dom0", b"some-arg", b"unexpected-payload"
                    )
                self.assertFalse(vm_mock.called)
                self.assertFalse(self.app.save.called)

    def test_993_dom0_unexpected_argument(self):
        methods_with_no_argument = [
            b"admin.deviceclass.List",
            b"admin.vmclass.List",
            b"admin.vm.List",
            b"admin.label.List",
            b"admin.property.List",
            b"admin.pool.List",
            b"admin.pool.ListDrivers",
            b"admin.Events",
        ]
        # make sure also no methods on actual VM gets called
        vm_mock = unittest.mock.MagicMock()
        vm_mock.name = self.vm.name
        vm_mock.qid = self.vm.qid
        vm_mock.__lt__ = lambda x, y: x.qid < y.qid
        self.app.domains._dict[self.vm.qid] = vm_mock
        exceptions = (qubes.exc.PermissionDenied, qubes.exc.ProtocolError)
        for method in methods_with_no_argument:
            # should reject argument regardless of having payload or not
            with self.subTest(method.decode("ascii")):
                with self.assertRaises(qubes.exc.PermissionDenied):
                    self.call_mgmt_func(method, b"dom0", b"some-arg", b"")
                self.assertFalse(vm_mock.called)
                self.assertFalse(self.app.save.called)

            with self.subTest(method.decode("ascii") + "+payload"):
                with self.assertRaises(exceptions):
                    self.call_mgmt_func(
                        method, b"dom0", b"unexpected-arg", b"some-payload"
                    )
                self.assertFalse(vm_mock.called)
                self.assertFalse(self.app.save.called)

    def test_994_dom0_only_calls(self):
        # TODO set some better arguments, to make sure the call was rejected
        # because of invalid destination, not invalid arguments
        methods_for_dom0_only = [
            b"admin.deviceclass.List",
            b"admin.vmclass.List",
            b"admin.vm.Create.AppVM",
            b"admin.vm.CreateInPool.AppVM",
            b"admin.label.List",
            b"admin.label.Create",
            b"admin.label.Get",
            b"admin.label.Remove",
            b"admin.pool.volume.List",
            b"admin.property.List",
            b"admin.property.Get",
            b"admin.property.Set",
            b"admin.property.Help",
            # b"admin.property.HelpRst",
            b"admin.property.Reset",
            b"admin.pool.List",
            b"admin.pool.ListDrivers",
            b"admin.pool.Info",
            b"admin.pool.Add",
            b"admin.pool.Remove",
            # b"admin.pool.volume.List",
            # b"admin.pool.volume.Info",
            # b"admin.pool.volume.ListSnapshots",
            # b"admin.pool.volume.Snapshot",
            # b"admin.pool.volume.Revert",
            # b"admin.pool.volume.Resize",
            b"admin.backup.Execute",
            b"admin.backup.Info",
        ]
        # make sure also no methods on actual VM gets called
        vm_mock = unittest.mock.MagicMock()
        vm_mock.name = self.vm.name
        vm_mock.qid = self.vm.qid
        vm_mock.__lt__ = lambda x, y: x.qid < y.qid
        self.app.domains._dict[self.vm.qid] = vm_mock
        exceptions = (qubes.exc.PermissionDenied, qubes.exc.ProtocolError)
        for method in methods_for_dom0_only:
            # should reject call regardless of having payload or not
            with self.subTest(method.decode("ascii")):
                with self.assertRaises(exceptions):
                    self.call_mgmt_func(method, b"test-vm1", b"", b"")
                self.assertFalse(vm_mock.called)
                self.assertFalse(self.app.save.called)

            with self.subTest(method.decode("ascii") + "+arg"):
                with self.assertRaises(exceptions):
                    self.call_mgmt_func(method, b"test-vm1", b"some-arg", b"")
                self.assertFalse(vm_mock.called)
                self.assertFalse(self.app.save.called)

            with self.subTest(method.decode("ascii") + "+payload"):
                with self.assertRaises(exceptions):
                    self.call_mgmt_func(method, b"test-vm1", b"", b"payload")
                self.assertFalse(vm_mock.called)
                self.assertFalse(self.app.save.called)

            with self.subTest(method.decode("ascii") + "+arg+payload"):
                with self.assertRaises(exceptions):
                    self.call_mgmt_func(
                        method, b"test-vm1", b"some-arg", b"some-payload"
                    )
                self.assertFalse(vm_mock.called)
                self.assertFalse(self.app.save.called)

    @unittest.skip("undecided")
    def test_995_vm_only_calls(self):
        # XXX is it really a good idea to prevent those calls this early?
        # TODO set some better arguments, to make sure the call was rejected
        # because of invalid destination, not invalid arguments
        methods_for_vm_only = [
            b"admin.vm.Clone",
            b"admin.vm.Remove",
            b"admin.vm.property.List",
            b"admin.vm.property.Get",
            b"admin.vm.property.Set",
            b"admin.vm.property.Help",
            b"admin.vm.property.HelpRst",
            b"admin.vm.property.Reset",
            b"admin.vm.feature.List",
            b"admin.vm.feature.Get",
            b"admin.vm.feature.Set",
            b"admin.vm.feature.CheckWithTemplate",
            b"admin.vm.feature.Remove",
            b"admin.vm.tag.List",
            b"admin.vm.tag.Get",
            b"admin.vm.tag.Remove",
            b"admin.vm.tag.Set",
            b"admin.vm.firewall.Get",
            b"admin.vm.firewall.Set",
            b"admin.vm.firewall.Reload",
            b"admin.vm.device.pci.Attach",
            b"admin.vm.device.pci.Detach",
            b"admin.vm.device.pci.List",
            b"admin.vm.device.pci.Available",
            b"admin.vm.microphone.Attach",
            b"admin.vm.microphone.Detach",
            b"admin.vm.microphone.Status",
            b"admin.vm.volume.ListSnapshots",
            b"admin.vm.volume.List",
            b"admin.vm.volume.Info",
            b"admin.vm.volume.Revert",
            b"admin.vm.volume.Resize",
            b"admin.vm.volume.Clear",
            b"admin.vm.Start",
            b"admin.vm.Shutdown",
            b"admin.vm.Pause",
            b"admin.vm.Unpause",
            b"admin.vm.Kill",
            b"admin.vm.feature.List",
            b"admin.vm.feature.Get",
            b"admin.vm.feature.Set",
            b"admin.vm.feature.Remove",
            b"admin.vm.feature.CheckWithTemplate",
        ]
        # make sure also no methods on actual VM gets called
        vm_mock = unittest.mock.MagicMock()
        vm_mock.name = self.vm.name
        vm_mock.qid = self.vm.qid
        vm_mock.__lt__ = lambda x, y: x.qid < y.qid
        self.app.domains._dict[self.vm.qid] = vm_mock
        exceptions = (qubes.exc.PermissionDenied, qubes.exc.ProtocolError)
        for method in methods_for_vm_only:
            # should reject payload regardless of having argument or not
            # should reject call regardless of having payload or not
            with self.subTest(method.decode("ascii")):
                with self.assertRaises(exceptions):
                    self.call_mgmt_func(method, b"dom0", b"", b"")
                self.assertFalse(vm_mock.called)
                self.assertFalse(self.app.save.called)

            with self.subTest(method.decode("ascii") + "+arg"):
                with self.assertRaises(exceptions):
                    self.call_mgmt_func(method, b"dom0", b"some-arg", b"")
                self.assertFalse(vm_mock.called)
                self.assertFalse(self.app.save.called)

            with self.subTest(method.decode("ascii") + "+payload"):
                with self.assertRaises(exceptions):
                    self.call_mgmt_func(method, b"dom0", b"", b"payload")
                self.assertFalse(vm_mock.called)
                self.assertFalse(self.app.save.called)

            with self.subTest(method.decode("ascii") + "+arg+payload"):
                with self.assertRaises(exceptions):
                    self.call_mgmt_func(
                        method, b"dom0", b"some-arg", b"some-payload"
                    )
                self.assertFalse(vm_mock.called)
                self.assertFalse(self.app.save.called)
