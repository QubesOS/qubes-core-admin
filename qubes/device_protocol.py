# -*- encoding: utf8 -*-
#
# The Qubes OS Project, http://www.qubes-os.org
#
# Copyright (C) 2010-2016  Joanna Rutkowska <joanna@invisiblethingslab.com>
# Copyright (C) 2015-2016  Wojtek Porczyk <woju@invisiblethingslab.com>
# Copyright (C) 2016       Bahtiar `kalkin-` Gadimov <bahtiar@gadimov.de>
# Copyright (C) 2017       Marek Marczykowski-Górecki
#                               <marmarek@invisiblethingslab.com>
# Copyright (C) 2024       Piotr Bartman-Szwarc
#                               <prbartman@invisiblethingslab.com>
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

"""
Common part of device API.

The same in `qubes-core-admin` and `qubes-core-admin-client`,
should be moved to one place.
"""


import string
import sys
from enum import Enum
from typing import Optional, Dict, Any, List, Union, Tuple

import qubes.utils

from qubes.exc import ProtocolError

QubesVM = 'qubes.vm.BaseVM'


class UnexpectedDeviceProperty(qubes.exc.QubesException, ValueError):
    """
    Device has unexpected property such as backend_domain, devclass etc.
    """


def qbool(value):
    return qubes.property.bool(None, None, value)


class Port:
    """
    Class of a *bus* device port with *ident* exposed by a *backend domain*.

    Attributes:
        backend_domain (QubesVM): The domain which exposes devices,
            e.g.`sys-usb`.
        ident (str): A unique identifier for the port within the backend domain.
        devclass (str): The class of the port (e.g., 'usb', 'pci').
    """
    ALLOWED_CHARS_KEY = set(
            string.digits + string.ascii_letters
            + r"!#$%&()*+,-./:;<>?@[\]^_{|}~")
    ALLOWED_CHARS_PARAM = ALLOWED_CHARS_KEY.union(set(string.punctuation + ' '))

    def __init__(self, backend_domain, ident, devclass):
        self.__backend_domain = backend_domain
        self.__ident = ident
        self.__devclass = devclass

    def __hash__(self):
        return hash((self.backend_domain.name, self.ident, self.devclass))

    def __eq__(self, other):
        if isinstance(other, Port):
            return (
                self.backend_domain == other.backend_domain and
                self.ident == other.ident and
                self.devclass == other.devclass
            )
        raise TypeError(f"Comparing instances of 'Port' and '{type(other)}' "
                        "is not supported")

    def __lt__(self, other):
        if isinstance(other, Port):
            return (self.backend_domain.name, self.devclass, self.ident) < \
                   (other.backend_domain.name, other.devclass, other.ident)
        raise TypeError(f"Comparing instances of 'Port' and '{type(other)}' "
                        "is not supported")

    def __repr__(self):
        return f"[{self.backend_domain.name}]:{self.devclass}:{self.ident}"

    def __str__(self):
        return f"{self.backend_domain.name}:{self.ident}"

    @property
    def ident(self) -> str:
        """
        Immutable port identifier.

        Unique for given domain and devclass.
        """
        return self.__ident

    @property
    def backend_domain(self) -> QubesVM:
        """ Which domain exposed this port. (immutable)"""
        return self.__backend_domain

    @property
    def devclass(self) -> str:
        """ Immutable port class such like: 'usb', 'pci' etc.

        For unknown classes "peripheral" is returned.
        """
        if self.__devclass:
            return self.__devclass
        return "peripheral"

    @classmethod
    def unpack_properties(
            cls, untrusted_serialization: bytes
    ) -> Tuple[Dict, Dict]:
        """
        Unpacks basic port properties from a serialized encoded string.

        Returns:
            tuple: A tuple containing two dictionaries, properties and options,
                extracted from the serialization.

        Raises:
            ValueError: If unexpected characters are found in property
                names or values.
        """
        ut_decoded = untrusted_serialization.decode(
            'ascii', errors='strict').strip()

        properties = {}
        options = {}

        if not ut_decoded:
            return properties, options

        keys = []
        values = []
        ut_key, _, ut_rest = ut_decoded.partition("='")

        key = sanitize_str(
            ut_key, cls.ALLOWED_CHARS_KEY,
            error_message='Invalid chars in property name: ')
        keys.append(key)
        while "='" in ut_rest:
            ut_value_key, _, ut_rest = ut_rest.partition("='")
            ut_value, _, ut_key = ut_value_key.rpartition("' ")
            value = sanitize_str(
                deserialize_str(ut_value), cls.ALLOWED_CHARS_PARAM,
                error_message='Invalid chars in property value: ')
            values.append(value)
            key = sanitize_str(
                ut_key, cls.ALLOWED_CHARS_KEY,
                error_message='Invalid chars in property name: ')
            keys.append(key)
        ut_value = ut_rest[:-1]  # ending '
        value = sanitize_str(
            deserialize_str(ut_value), cls.ALLOWED_CHARS_PARAM,
            error_message='Invalid chars in property value: ')
        values.append(value)

        for key, value in zip(keys, values):
            if key.startswith("_"):
                # it's handled in cls.__init__
                options[key[1:]] = value
            else:
                properties[key] = value

        return properties, options

    @classmethod
    def pack_property(cls, key: str, value: str):
        """
        Add property `key=value` to serialization.
        """
        key = sanitize_str(
            key, cls.ALLOWED_CHARS_KEY,
            error_message='Invalid chars in property name: ')
        value = sanitize_str(
            serialize_str(value), cls.ALLOWED_CHARS_PARAM,
            error_message='Invalid chars in property value: ')
        return key.encode('ascii') + b'=' + value.encode('ascii')

    @staticmethod
    def check_device_properties(
            expected_port: 'Port', properties: Dict[str, Any]):
        """
        Validates properties against an expected port configuration.

        Modifies `properties`.

        Raises:
            UnexpectedDeviceProperty: If any property does not match
            the expected values.
        """
        expected = expected_port
        exp_vm_name = expected.backend_domain.name
        if properties.get('backend_domain', exp_vm_name) != exp_vm_name:
            raise UnexpectedDeviceProperty(
                f"Got device exposed by {properties['backend_domain']}"
                f"when expected devices from {exp_vm_name}.")
        properties['backend_domain'] = expected.backend_domain

        if properties.get('ident', expected.ident) != expected.ident:
            raise UnexpectedDeviceProperty(
                f"Got device with id: {properties['ident']} "
                f"when expected id: {expected.ident}.")
        properties['ident'] = expected.ident

        if properties.get('devclass', expected.devclass) != expected.devclass:
            raise UnexpectedDeviceProperty(
                f"Got {properties['devclass']} device "
                f"when expected {expected.devclass}.")
        properties['devclass'] = expected.devclass


class DeviceCategory(Enum):
    """
    Category of a peripheral device.

    Arbitrarily selected interfaces that are important to users,
    thus deserving special recognition such as a custom icon, etc.
    """
    # pylint: disable=invalid-name
    Other = "*******"

    Communication = ("u02****", "p07****")  # eg. modems
    Input = ("u03****", "p09****")  # HID etc.
    Keyboard = ("u03**01", "p0900**")
    Mouse = ("u03**02", "p0902**")
    Printer = ("u07****",)
    Scanner = ("p0903**",)
    Microphone = ("m******",)
    # Multimedia = Audio, Video, Displays etc.
    Multimedia = ("u01****", "u0e****", "u06****", "u10****", "p03****",
                  "p04****")
    Wireless = ("ue0****", "p0d****")
    Bluetooth = ("ue00101", "p0d11**")
    Mass_Data = ("b******", "u08****", "p01****")
    Network = ("p02****",)
    Memory = ("p05****",)
    PCI_Bridge = ("p06****",)
    Docking_Station = ("p0a****",)
    Processor = ("p0b****", "p40****")
    PCI_Serial_Bus = ("p0c****",)
    PCI_USB = ("p0c03**",)

    @staticmethod
    def from_str(interface_encoding: str) -> 'DeviceCategory':
        """
        Returns `DeviceCategory` from data encoded in string.
        """
        result = DeviceCategory.Other
        if len(interface_encoding) != len(DeviceCategory.Other.value):
            return result
        best_score = 0

        for interface in DeviceCategory:
            for pattern in interface.value:
                score = 0
                for itf, pat in zip(interface_encoding, pattern):
                    if itf == pat:
                        score += 1
                    elif pat != "*":
                        score = -1  # inconsistent with a pattern
                        break

                if score > best_score:
                    best_score = score
                    result = interface

        return result


class DeviceInterface:
    """
    Peripheral device interface wrapper.
    """

    def __init__(self, interface_encoding: str, devclass: Optional[str] = None):
        ifc_padded = interface_encoding.ljust(6, '*')
        if devclass:
            if len(ifc_padded) > 6:
                print(
                    f"{interface_encoding=} is too long "
                    f"(is {len(interface_encoding)}, expected max. 6) "
                    f"for given {devclass=}",
                    file=sys.stderr
                )
            ifc_full = devclass[0] + ifc_padded
        else:
            known_devclasses = {
                'p': 'pci', 'u': 'usb', 'b': 'block', 'm': 'mic'}
            devclass = known_devclasses.get(interface_encoding[0], None)
            if len(ifc_padded) > 7:
                print(
                    f"{interface_encoding=} is too long "
                    f"(is {len(interface_encoding)}, expected max. 7)",
                    file=sys.stderr
                )
                ifc_full = ifc_padded
            elif len(ifc_padded) == 6:
                ifc_full = '?' + ifc_padded
            else:
                ifc_full = ifc_padded

        self._devclass = devclass
        self._interface_encoding = ifc_full
        self._category = DeviceCategory.from_str(self._interface_encoding)

    @property
    def devclass(self) -> Optional[str]:
        """ Immutable Device class such like: 'usb', 'pci' etc. """
        return self._devclass

    @property
    def category(self) -> DeviceCategory:
        """ Immutable Device category such like: 'Mouse', 'Mass_Data' etc. """
        return self._category

    @classmethod
    def unknown(cls) -> 'DeviceInterface':
        """ Value for unknown device interface. """
        return cls("?******")

    def __repr__(self):
        return self._interface_encoding

    def __hash__(self):
        return hash(repr(self))

    def __eq__(self, other):
        if not isinstance(other, DeviceInterface):
            return False
        return repr(self) == repr(other)

    def __str__(self):
        if self.devclass == "block":
            return "Block Device"
        if self.devclass in ("usb", "pci"):
            # try subclass first as in `lspci`
            result = self._load_classes(self.devclass).get(
                self._interface_encoding[1:-2] + '**', None)
            if (result is None or result.lower()
                    in ('none', 'no subclass', 'unused', 'undefined')):
                # if not, try interface
                result = self._load_classes(self.devclass).get(
                    self._interface_encoding[1:], None)
            if (result is None or result.lower()
                    in ('none', 'no subclass', 'unused', 'undefined')):
                # if not, try class
                result = self._load_classes(self.devclass).get(
                    self._interface_encoding[1:-4] + '****', None)
            if result is None:
                result = f"Unclassified {self.devclass} device"
            return result
        if self.devclass == 'mic':
            return "Microphone"
        return repr(self)

    @staticmethod
    def _load_classes(bus: str):
        """
        List of known device classes, subclasses and programming interfaces.
        """
        # Syntax:
        # C class       class_name
        #       subclass        subclass_name           <-- single tab
        #               prog-if  prog-if_name   <-- two tabs
        result = {}
        with open(f'/usr/share/hwdata/{bus}.ids',
                  encoding='utf-8', errors='ignore') as pciids:
            # for `class_name` and `subclass_name`
            # pylint: disable=used-before-assignment
            class_id = None
            subclass_id = None
            for line in pciids.readlines():
                line = line.rstrip()
                if line.startswith('\t\t') \
                        and class_id is not None and subclass_id is not None:
                    (progif_id, _, progif_name) = line[2:].split(' ', 2)
                    result[class_id + subclass_id + progif_id] = \
                        progif_name
                elif line.startswith('\t') and class_id:
                    (subclass_id, _, subclass_name) = line[1:].split(' ', 2)
                    # store both prog-if specific entry and generic one
                    result[class_id + subclass_id + '**'] = \
                        subclass_name
                elif line.startswith('C '):
                    (_, class_id, _, class_name) = line.split(' ', 3)
                    result[class_id + '****'] = class_name
                    subclass_id = None

        return result


class DeviceInfo(Port):
    """ Holds all information about a device """

    def __init__(
            self,
            port: Port,
            vendor: Optional[str] = None,
            product: Optional[str] = None,
            manufacturer: Optional[str] = None,
            name: Optional[str] = None,
            serial: Optional[str] = None,
            interfaces: Optional[List[DeviceInterface]] = None,
            parent: Optional[Port] = None,
            attachment: Optional[QubesVM] = None,
            self_identity: Optional[str] = None,
            **kwargs
    ):
        super().__init__(port.backend_domain, port.ident, port.devclass)

        self._vendor = vendor
        self._product = product
        self._manufacturer = manufacturer
        self._name = name
        self._serial = serial
        self._interfaces = interfaces
        self._parent = parent
        self._attachment = attachment
        self._self_identity = self_identity

        self.data = kwargs

    def __hash__(self):
        return hash(self.port)# self.self_identity))

    def __eq__(self, other):
        if isinstance(other, DeviceInfo):
            return (
                self.port == other.port
                # and self.self_identity == other.self_identity
            )
        else:
            return super().__lt__(other)

    def __lt__(self, other):
        if isinstance(other, DeviceInfo):
            # return (self.port, self.self_identity) < \
            #        (other.port, other.self_identity)
            return self.port < other.port
        else:
            return super().__lt__(other)

    def __repr__(self):
        return f"{self.port!r}"#:{self.self_identity}"

    def __str__(self):
        return f"{self.port}"#:{self.self_identity}"

    @property
    def port(self) -> Port:
        """
        Device port visible in Qubes.
        """
        return Port(self.backend_domain, self.ident, self.devclass)

    @property
    def vendor(self) -> str:
        """
        Device vendor name from local database.

        Could be empty string or "unknown".

        Override this method to return proper name from `/usr/share/hwdata/*`.
        """
        if not self._vendor:
            return "unknown"
        return self._vendor

    @property
    def product(self) -> str:
        """
        Device name from local database.

        Could be empty string or "unknown".

        Override this method to return proper name from `/usr/share/hwdata/*`.
        """
        if not self._product:
            return "unknown"
        return self._product

    @property
    def manufacturer(self) -> str:
        """
        The name of the manufacturer of the device introduced by device itself.

        Could be empty string or "unknown".

        Override this method to return proper name directly from device itself.
        """
        if not self._manufacturer:
            return "unknown"
        return self._manufacturer

    @property
    def name(self) -> str:
        """
        The name of the device it introduced itself with.

        Could be empty string or "unknown".

        Override this method to return proper name directly from device itself.
        """
        if not self._name:
            return "unknown"
        return self._name

    @property
    def serial(self) -> str:
        """
        The serial number of the device it introduced itself with.

        Could be empty string or "unknown".

        Override this method to return proper name directly from device itself.
        """
        if not self._serial:
            return "unknown"
        return self._serial

    @property
    def description(self) -> str:
        """
        Short human-readable description.

        For unknown device returns `unknown device (unknown vendor)`.
        For unknown USB device returns `unknown usb device (unknown vendor)`.
        For unknown USB device with known serial number returns
            `<serial> (unknown vendor)`.
        """
        if self.product and self.product != "unknown":
            prod = self.product
        elif self.name and self.name != "unknown":
            prod = self.name
        elif self.serial and self.serial != "unknown":
            prod = self.serial
        elif self.parent_device is not None:
            return f"sub-device of {self.parent_device}"
        else:
            prod = f"unknown {self.devclass if self.devclass else ''} device"

        if self.vendor and self.vendor != "unknown":
            vendor = self.vendor
        elif self.manufacturer and self.manufacturer != "unknown":
            vendor = self.manufacturer
        else:
            vendor = "unknown vendor"

        cat = self.interfaces[0].category.name
        if cat == "Other":
            cat = str(self.interfaces[0])
        return f"{cat}: {vendor} {prod}"

    @property
    def interfaces(self) -> List[DeviceInterface]:
        """
        Non-empty list of device interfaces.

        Every device should have at least one interface.
        """
        if not self._interfaces:
            return [DeviceInterface.unknown()]
        return self._interfaces

    @property
    def parent_device(self) -> Optional[Port]:
        """
        The parent device, if any.

        If the device is part of another device (e.g., it's a single
        partition of a USB stick), the parent device id should be here.
        """
        return self._parent

    @property
    def subdevices(self) -> List['DeviceInfo']:
        """
        The list of children devices if any.

        If the device has subdevices (e.g., partitions of a USB stick),
        the subdevices id should be here.
        """
        return [dev for dev in self.backend_domain.devices[self.devclass]
                if dev.parent_device.ident == self.ident]

    @property
    def attachment(self) -> Optional[QubesVM]:
        """
        VM to which device is attached (frontend domain).
        """
        return self._attachment

    def serialize(self) -> bytes:
        """
        Serialize an object to be transmitted via Qubes API.
        """
        # 'backend_domain', 'attachment', 'interfaces', 'data', 'parent_device'
        # are not string, so they need special treatment
        default_attrs = {
            'ident', 'devclass', 'vendor', 'product', 'manufacturer', 'name',
            'serial', 'self_identity'}
        properties = b' '.join(
            self.pack_property(key, value)
            for key, value in ((key, getattr(self, key))
                               for key in default_attrs))

        properties += b' ' + self.pack_property(
            'backend_domain', self.backend_domain.name)

        if self.attachment:
            properties = self.pack_property(
                'attachment', self.attachment.name)

        properties += b' ' + self.pack_property(
            'interfaces',
            ''.join(repr(ifc) for ifc in self.interfaces))

        if self.parent_device is not None:
            properties += b' ' + self.pack_property(
                'parent_ident', self.parent_device.ident)
            properties += b' ' + self.pack_property(
                'parent_devclass', self.parent_device.devclass)

        for key, value in self.data.items():
            properties += b' ' + self.pack_property("_" + key, value)

        return properties

    @classmethod
    def deserialize(
            cls,
            serialization: bytes,
            expected_backend_domain: QubesVM,
            expected_devclass: Optional[str] = None,
    ) -> 'DeviceInfo':
        """
        Recovers a serialized object, see: :py:meth:`serialize`.
        """
        ident, _, rest = serialization.partition(b' ')
        ident = ident.decode('ascii', errors='ignore')
        device = UnknownDevice(
            backend_domain=expected_backend_domain,
            ident=ident,
            devclass=expected_devclass,
        )

        try:
            device = cls._deserialize(rest, device)
            # pylint: disable=broad-exception-caught
        except Exception as exc:
            print(exc, file=sys.stderr)

        return device

    @classmethod
    def _deserialize(
            cls,
            untrusted_serialization: bytes,
            expected_port: Port
    ) -> 'DeviceInfo':
        """
        Actually deserializes the object.
        """
        properties, options = cls.unpack_properties(untrusted_serialization)
        properties.update(options)

        cls.check_device_properties(expected_port, properties)

        if 'attachment' not in properties or not properties['attachment']:
            properties['attachment'] = None
        else:
            app = expected_port.backend_domain.app
            properties['attachment'] = app.domains.get_blind(
                properties['attachment'])

        if properties['devclass'] != expected_port.devclass:
            raise UnexpectedDeviceProperty(
                f"Got {properties['devclass']} device "
                f"when expected {expected_port.devclass}.")

        if 'interfaces' in properties:
            interfaces = properties['interfaces']
            interfaces = [
                DeviceInterface(interfaces[i:i + 7])
                for i in range(0, len(interfaces), 7)]
            properties['interfaces'] = interfaces

        if 'parent_ident' in properties:
            properties['parent'] = Port(
                backend_domain=expected_port.backend_domain,
                ident=properties['parent_ident'],
                devclass=properties['parent_devclass'],
            )
            del properties['parent_ident']
            del properties['parent_devclass']

        port = Port(
            properties['backend_domain'],
            properties['ident'],
            properties['devclass'])
        del properties['backend_domain']
        del properties['ident']
        del properties['devclass']

        return cls(port, **properties)

    @property
    def self_identity(self) -> str:
        """
        Get additional identification of device presented by device itself.

        For pci/usb we expect:
        <vendor_id>:<product_id>:<serial if any>:<interface1interface2...>
        For block devices:
        <parent_ident>:<interface number if any>

        In addition to the description returns presented interfaces.
        It is used to auto-attach usb devices, so an attacking device needs to
        mimic not only a name, but also interfaces of trusted device (and have
        to be plugged to the same port). For a common user it is all the data
        she uses to recognize the device.
        """
        if not self._self_identity:
            return "0000:0000::?******"
        return self._self_identity


def serialize_str(value: str):
    """
    Serialize python string to ensure consistency.
    """
    return "'" + str(value).replace("'", r"\'") + "'"


def deserialize_str(value: str):
    """
    Deserialize python string to ensure consistency.
    """
    return value.replace(r"\'", "'")


def sanitize_str(
        untrusted_value: str,
        allowed_chars: set,
        replace_char: str = None,
        error_message: str = ""
) -> str:
    """
    Sanitize given untrusted string.

    If `replace_char` is not None, ignore `error_message` and replace invalid
    characters with the string.
    """
    if replace_char is None:
        not_allowed_chars = set(untrusted_value) - allowed_chars
        if not_allowed_chars:
            raise ProtocolError(error_message + repr(not_allowed_chars))
        return untrusted_value
    result = ""
    for char in untrusted_value:
        if char in allowed_chars:
            result += char
        else:
            result += replace_char
    return result


class UnknownDevice(DeviceInfo):
    # pylint: disable=too-few-public-methods
    """Unknown device - for example, exposed by domain not running currently"""

    def __init__(self, backend_domain, ident, *, devclass, **kwargs):
        port = Port(backend_domain, ident, devclass)
        super().__init__(port, **kwargs)


class DeviceAssignment(Port):
    """ Maps a device to a frontend_domain.

    There are 3 flags `attached`, `automatically_attached` and `required`.
    The meaning of valid combinations is as follows:
    1. (True, False, False) -> domain is running, device is manually attached
                               and could be manually detach any time.
    2. (True, True, False)  -> domain is running, device is attached
                               and could be manually detach any time (see 4.),
                               but in the future will be auto-attached again.
    3. (True, True, True)   -> domain is running, device is attached
                               and couldn't be detached.
    4. (False, Ture, False) -> device is assigned to domain, but not attached
                               because either (i) domain is halted,
                               device (ii) manually detached or
                               (iii) attach to different domain.
    5. (False, True, True)  -> domain is halted, device assigned to domain
                               and required to start domain.
    """

    class AssignmentType(Enum):
        MANUAL = 0
        ASK = 1
        AUTO = 2
        REQUIRED = 3

    def __init__(
            self,
            port: Port,
            frontend_domain=None,
            options=None,
            required=False,
            attach_automatically=False
    ):
        super().__init__(port.backend_domain, port.ident, port.devclass)
        self.__options = options or {}
        if required:
            assert attach_automatically
            self.type = DeviceAssignment.AssignmentType.REQUIRED
        elif attach_automatically:
            self.type = DeviceAssignment.AssignmentType.AUTO
        else:
            self.type = DeviceAssignment.AssignmentType.MANUAL
        self.frontend_domain = frontend_domain

    def clone(self, **kwargs):
        """
        Clone object and substitute attributes with explicitly given.
        """
        attr = {
            "options": self.options,
            "required": self.required,
            "attach_automatically": self.attach_automatically,
            "frontend_domain": self.frontend_domain,
        }
        attr.update(kwargs)
        return self.__class__(
            Port(self.backend_domain, self.ident, self.devclass), **attr)

    @property
    def device(self) -> DeviceInfo:
        """Get DeviceInfo object corresponding to this DeviceAssignment"""
        return self.backend_domain.devices[self.devclass][self.ident]

    @property
    def frontend_domain(self) -> Optional[QubesVM]:
        """ Which domain the device is attached/assigned to. """
        return self.__frontend_domain

    @frontend_domain.setter
    def frontend_domain(
        self, frontend_domain: Optional[Union[str, QubesVM]]
    ):
        """ Which domain the device is attached/assigned to. """
        if isinstance(frontend_domain, str):
            frontend_domain = self.backend_domain.app.domains[frontend_domain]
        self.__frontend_domain = frontend_domain

    @property
    def attached(self) -> bool:
        """
        Is the device attached to the fronted domain?

        Returns False if device is attached to different domain
        """
        return self.device.attachment == self.frontend_domain

    @property
    def required(self) -> bool:
        """
        Is the presence of this device required for the domain to start? If yes,
        it will be attached automatically.
        """
        return self.type == DeviceAssignment.AssignmentType.REQUIRED

    @required.setter
    def required(self, required: bool):
        self.type = DeviceAssignment.AssignmentType.REQUIRED

    @property
    def attach_automatically(self) -> bool:
        """
        Should this device automatically connect to the frontend domain when
        available and not connected to other qubes?
        """
        return self.type in (
            DeviceAssignment.AssignmentType.AUTO,
            DeviceAssignment.AssignmentType.REQUIRED
        )

    @attach_automatically.setter
    def attach_automatically(self, attach_automatically: bool):
        self.type = DeviceAssignment.AssignmentType.AUTO

    @property
    def options(self) -> Dict[str, Any]:
        """ Device options (same as in the legacy API). """
        return self.__options

    @options.setter
    def options(self, options: Optional[Dict[str, Any]]):
        """ Device options (same as in the legacy API). """
        self.__options = options or {}

    def serialize(self) -> bytes:
        """
        Serialize an object to be transmitted via Qubes API.
        """
        properties = b' '.join(
            self.pack_property(key, value)
            for key, value in (
                ('required', 'yes' if self.required else 'no'),
                ('attach_automatically',
                 'yes' if self.attach_automatically else 'no'),
                ('ident', self.ident),
                ('devclass', self.devclass)))

        properties += b' ' + self.pack_property(
            'backend_domain', self.backend_domain.name)

        if self.frontend_domain is not None:
            properties += b' ' + self.pack_property(
                'frontend_domain', self.frontend_domain.name)

        for key, value in self.options.items():
            properties += b' ' + self.pack_property("_" + key, value)

        return properties

    @classmethod
    def deserialize(
            cls,
            serialization: bytes,
            expected_port: Port,
    ) -> 'DeviceAssignment':
        """
        Recovers a serialized object, see: :py:meth:`serialize`.
        """
        try:
            result = cls._deserialize(serialization, expected_port)
        except Exception as exc:
            raise ProtocolError() from exc
        return result

    @classmethod
    def _deserialize(
            cls,
            untrusted_serialization: bytes,
            expected_port: Port,
    ) -> 'DeviceAssignment':
        """
        Actually deserializes the object.
        """
        properties, options = cls.unpack_properties(untrusted_serialization)
        properties['options'] = options

        cls.check_device_properties(expected_port, properties)
        del properties['backend_domain']
        del properties['ident']
        del properties['devclass']

        properties['attach_automatically'] = qbool(
            properties.get('attach_automatically', 'no'))
        properties['required'] = qbool(properties.get('required', 'no'))

        return cls(expected_port, **properties)
