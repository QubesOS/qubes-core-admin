# pylint: disable=protected-access,pointless-statement

#
# The Qubes OS Project, https://www.qubes-os.org/
#
# Copyright (C) 2015-2016  Joanna Rutkowska <joanna@invisiblethingslab.com>
# Copyright (C) 2015-2016  Wojtek Porczyk <woju@invisiblethingslab.com>
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

import qubes.devices
from qubes.devices import DeviceInfo, DeviceCategory

import qubes.tests

class TestDevice(qubes.devices.DeviceInfo):
    # pylint: disable=too-few-public-methods
    pass


class TestVMCollection(dict):
    def __iter__(self):
        return iter(set(self.values()))


class TestApp(object):
    # pylint: disable=too-few-public-methods
    def __init__(self):
        self.domains = TestVMCollection()


class TestVM(qubes.tests.TestEmitter):
    def __init__(self, app, name, *args, **kwargs):
        super(TestVM, self).__init__(*args, **kwargs)
        self.app = app
        self.name = name
        self.device = TestDevice(self, 'testdev', 'Description')
        self.events_enabled = True
        self.devices = {
            'testclass': qubes.devices.DeviceCollection(self, 'testclass')
        }
        self.app.domains[name] = self
        self.app.domains[self] = self
        self.running = False

    def __str__(self):
        return self.name

    @qubes.events.handler('device-list-attached:testclass')
    def dev_testclass_list_attached(self, event, persistent = False):
        for vm in self.app.domains:
            if vm.device.data.get('test_frontend_domain', None) == self:
                yield (vm.device, {})

    @qubes.events.handler('device-list:testclass')
    def dev_testclass_list(self, event):
        yield self.device

    def is_halted(self):
        return not self.running

    def is_running(self):
        return self.running

    class log:
        @staticmethod
        def exception(message):
            pass


class TC_00_DeviceCollection(qubes.tests.QubesTestCase):
    def setUp(self):
        super().setUp()
        self.app = TestApp()
        self.emitter = TestVM(self.app, 'vm')
        self.app.domains['vm'] = self.emitter
        self.device = self.emitter.device
        self.collection = self.emitter.devices['testclass']
        self.assignment = qubes.devices.DeviceAssignment(
            backend_domain=self.device.backend_domain,
            ident=self.device.ident,
            persistent=True
        )

    def test_000_init(self):
        self.assertFalse(self.collection._set)

    def test_001_attach(self):
        self.loop.run_until_complete(self.collection.attach(self.assignment))
        self.assertEventFired(self.emitter, 'device-pre-attach:testclass')
        self.assertEventFired(self.emitter, 'device-attach:testclass')
        self.assertEventNotFired(self.emitter, 'device-pre-detach:testclass')
        self.assertEventNotFired(self.emitter, 'device-detach:testclass')

    def test_002_detach(self):
        self.loop.run_until_complete(self.collection.attach(self.assignment))
        self.loop.run_until_complete(self.collection.detach(self.assignment))
        self.assertEventFired(self.emitter, 'device-pre-attach:testclass')
        self.assertEventFired(self.emitter, 'device-attach:testclass')
        self.assertEventFired(self.emitter, 'device-pre-detach:testclass')
        self.assertEventFired(self.emitter, 'device-detach:testclass')

    def test_010_empty_detach(self):
        with self.assertRaises(LookupError):
            self.loop.run_until_complete(
                self.collection.detach(self.assignment))

    def test_011_double_attach(self):
        self.loop.run_until_complete(self.collection.attach(self.assignment))

        with self.assertRaises(qubes.devices.DeviceAlreadyAttached):
            self.loop.run_until_complete(
                self.collection.attach(self.assignment))

    def test_012_double_detach(self):
        self.loop.run_until_complete(self.collection.attach(self.assignment))
        self.loop.run_until_complete(self.collection.detach(self.assignment))

        with self.assertRaises(qubes.devices.DeviceNotAttached):
            self.loop.run_until_complete(
                self.collection.detach(self.assignment))

    def test_013_list_attached_persistent(self):
        self.assertEqual(set([]), set(self.collection.get_assigned_devices()))
        self.loop.run_until_complete(self.collection.attach(self.assignment))
        self.assertEventFired(self.emitter, 'device-list-attached:testclass')
        self.assertEqual({self.device}, set(self.collection.get_assigned_devices()))
        self.assertEqual(set([]),
                         set(self.collection.get_attached_devices()))

    def test_014_list_attached_non_persistent(self):
        self.assignment.persistent = False
        self.emitter.running = True
        self.loop.run_until_complete(self.collection.attach(self.assignment))
        # device-attach event not implemented, so manipulate object manually
        self.device.data['test_frontend_domain'] = self.emitter
        self.assertEqual({self.device},
                         set(self.collection.get_attached_devices()))
        self.assertEqual(set([]),
                         set(self.collection.get_assigned_devices()))
        self.assertEqual({self.device},
                         set(self.collection.get_attached_devices()))
        self.assertEventFired(self.emitter, 'device-list-attached:testclass')

    def test_015_list_available(self):
        self.assertEqual({self.device}, set(self.collection))
        self.assertEventFired(self.emitter, 'device-list:testclass')

    def test_020_update_persistent_to_false(self):
        self.emitter.running = True
        self.assertEqual(set([]), set(self.collection.get_assigned_devices()))
        self.loop.run_until_complete(self.collection.attach(self.assignment))
        # device-attach event not implemented, so manipulate object manually
        self.device.data['test_frontend_domain'] = self.emitter
        self.assertEqual({self.device}, set(self.collection.get_assigned_devices()))
        self.assertEqual({self.device}, set(self.collection.get_attached_devices()))
        self.assertEqual({self.device}, set(self.collection.get_assigned_devices()))
        self.assertEqual({self.device}, set(self.collection.get_attached_devices()))
        self.collection.update_assignment(self.device, False)
        self.assertEqual(set(), set(self.collection.get_assigned_devices()))
        self.assertEqual({self.device}, set(self.collection.get_attached_devices()))

    def test_021_update_persistent_to_true(self):
        self.assignment.persistent = False
        self.emitter.running = True
        self.assertEqual(set([]), set(self.collection.get_assigned_devices()))
        self.loop.run_until_complete(self.collection.attach(self.assignment))
        # device-attach event not implemented, so manipulate object manually
        self.device.data['test_frontend_domain'] = self.emitter
        self.assertEqual(set(), set(self.collection.get_assigned_devices()))
        self.assertEqual({self.device}, set(self.collection.get_attached_devices()))
        self.assertEqual(set(), set(self.collection.get_assigned_devices()))
        self.assertEqual({self.device}, set(self.collection.get_attached_devices()))
        self.collection.update_assignment(self.device, True)
        self.assertEqual({self.device}, set(self.collection.get_assigned_devices()))
        self.assertEqual({self.device}, set(self.collection.get_attached_devices()))

    def test_022_update_persistent_reject_not_running(self):
        self.assertEqual(set([]), set(self.collection.get_assigned_devices()))
        self.loop.run_until_complete(self.collection.attach(self.assignment))
        self.assertEqual({self.device}, set(self.collection.get_assigned_devices()))
        self.assertEqual(set(), set(self.collection.get_attached_devices()))
        with self.assertRaises(qubes.exc.QubesVMNotStartedError):
            self.collection.update_assignment(self.device, False)

    def test_023_update_persistent_reject_not_attached(self):
        self.assertEqual(set(), set(self.collection.get_assigned_devices()))
        self.assertEqual(set(), set(self.collection.get_attached_devices()))
        self.emitter.running = True
        with self.assertRaises(qubes.exc.QubesValueError):
            self.collection.update_assignment(self.device, True)
        with self.assertRaises(qubes.exc.QubesValueError):
            self.collection.update_assignment(self.device, False)


class TC_01_DeviceManager(qubes.tests.QubesTestCase):
    def setUp(self):
        super().setUp()
        self.app = TestApp()
        self.emitter = TestVM(self.app, 'vm')
        self.manager = qubes.devices.DeviceManager(self.emitter)

    def test_000_init(self):
        self.assertEqual(self.manager, {})

    def test_001_missing(self):
        device = TestDevice(self.emitter.app.domains['vm'], 'testdev')
        assignment = qubes.devices.DeviceAssignment(
            backend_domain=device.backend_domain,
            ident=device.ident,
            persistent=True)
        self.loop.run_until_complete(
            self.manager['testclass'].attach(assignment))
        self.assertEventFired(self.emitter, 'device-attach:testclass')


class TC_02_DeviceInfo(qubes.tests.QubesTestCase):
    def setUp(self):
        super().setUp()
        self.app = TestApp()
        self.vm = TestVM(self.app, 'vm')

    def test_001_init(self):
        pass  # TODO

    def test_010_serialize(self):
        device = DeviceInfo(
            backend_domain=self.vm,
            ident="1-1.1.1",
            devclass="bus",
            vendor="ITL",
            product="Qubes",
            manufacturer="",
            name="Some untrusted garbage",
            serial=None,
            interfaces=[DeviceCategory.Other, DeviceCategory.USB_HID],
            # additional_info="",  # TODO
            # date="06.12.23",  # TODO
        )
        actual = sorted(device.serialize().split(b' '))
        expected = [
            b'YmFja2VuZF9kb21haW49dm0=', b'ZGV2Y2xhc3M9YnVz',
            b'aW50ZXJmYWNlcz0qKioqKiowMyoqKio=', b'aWRlbnQ9MS0xLjEuMQ==',
            b'bWFudWZhY3R1cmVyPXVua25vd24=',
            b'bmFtZT1Tb21lIHVudHJ1c3RlZCBnYXJiYWdl',
            b'c2VyaWFsPXVua25vd24=', b'cHJvZHVjdD1RdWJlcw==',
            b'dmVuZG9yPUlUTA==']
        self.assertEqual(actual, expected)

    def test_020_deserialize(self):
        expected = [
            b'YmFja2VuZF9kb21haW49dm0=', b'ZGV2Y2xhc3M9YnVz',
            b'aW50ZXJmYWNlcz0qKioqKiowMyoqKio=', b'aWRlbnQ9MS0xLjEuMQ==',
            b'bWFudWZhY3R1cmVyPXVua25vd24=',
            b'bmFtZT1Tb21lIHVudHJ1c3RlZCBnYXJiYWdl',
            b'c2VyaWFsPXVua25vd24=', b'cHJvZHVjdD1RdWJlcw==',
            b'dmVuZG9yPUlUTA==']
        actual = DeviceInfo.deserialize(b' '.join(expected), self.vm)
        expected = DeviceInfo(
            backend_domain=self.vm,
            ident="1-1.1.1",
            devclass="bus",
            vendor="ITL",
            product="Qubes",
            manufacturer="",
            name="Some untrusted garbage",
            serial=None,
            interfaces=[DeviceCategory.Other, DeviceCategory.USB_HID],
            # additional_info="",  # TODO
            # date="06.12.23",  # TODO
        )

        self.assertEqual(actual.backend_domain, expected.backend_domain)
        self.assertEqual(actual.ident, expected.ident)
        self.assertEqual(actual.devclass, expected.devclass)
        self.assertEqual(actual.vendor, expected.vendor)
        self.assertEqual(actual.product, expected.product)
        self.assertEqual(actual.manufacturer, expected.manufacturer)
        self.assertEqual(actual.name, expected.name)
        self.assertEqual(actual.serial, expected.serial)
        self.assertEqual(actual.interfaces, expected.interfaces)
        # self.assertEqual(actual.data, expected.data)  # TODO

