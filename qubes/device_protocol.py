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
from typing import Optional, Dict, Any, List, Union, Tuple, Callable
from typing import TYPE_CHECKING

from qubes.exc import ProtocolError, QubesValueError, UnexpectedDeviceProperty

if TYPE_CHECKING:
    from qubes.vm.qubesvm import QubesVM
else:
    QubesVM = "qubes.vm.qubesvm.QubesVM"


def qbool(value):
    """
    Property setter for boolean properties.

    It accepts (case-insensitive) ``'0'``, ``'no'`` and ``false`` as
    :py:obj:`False` and ``'1'``, ``'yes'`` and ``'true'`` as
    :py:obj:`True`.
    """

    if isinstance(value, str):
        lcvalue = value.lower()
        if lcvalue in ("0", "no", "false", "off"):
            return False
        if lcvalue in ("1", "yes", "true", "on"):
            return True
        raise QubesValueError(
            "Invalid literal for boolean property: {!r}".format(value))

    return bool(value)


class DeviceSerializer:
    """
    Group of method for serialization of device properties.
    """

    ALLOWED_CHARS_KEY = set(
        string.digits + string.ascii_letters + r"!#$%&()*+,-./:;<>?@[\]^_{|}~"
    )
    ALLOWED_CHARS_PARAM = ALLOWED_CHARS_KEY.union(set(string.punctuation + " "))

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
            "ascii", errors="strict"
        ).strip()

        properties: Dict[str, str] = {}
        options: Dict[str, str] = {}

        if not ut_decoded:
            return properties, options

        keys = []
        values = []
        ut_key, _, ut_rest = ut_decoded.partition("='")

        key = cls.sanitize_str(
            ut_key.strip(),
            cls.ALLOWED_CHARS_KEY,
            error_message="Invalid chars in property name: ",
        )
        keys.append(key)
        while "='" in ut_rest:
            ut_value_key, _, ut_rest = ut_rest.partition("='")
            ut_value, _, ut_key = ut_value_key.rpartition("' ")
            value = cls.sanitize_str(
                cls.deserialize_str(ut_value),
                cls.ALLOWED_CHARS_PARAM,
                error_message="Invalid chars in property value: ",
            )
            values.append(value)
            key = cls.sanitize_str(
                ut_key.strip(),
                cls.ALLOWED_CHARS_KEY,
                error_message="Invalid chars in property name: ",
            )
            keys.append(key)
        ut_value = ut_rest[:-1]  # ending '
        value = cls.sanitize_str(
            cls.deserialize_str(ut_value),
            cls.ALLOWED_CHARS_PARAM,
            error_message="Invalid chars in property value: ",
        )
        values.append(value)

        for key, value in zip(keys, values):
            if key.startswith("_"):
                # it's handled in cls.__init__
                options[key[1:]] = value
            else:
                properties[key] = value

        return properties, options

    @classmethod
    def pack_property(cls, key: str, value: Optional[str]):
        """
        Add property `key=value` to serialization.
        """
        if value is None:
            return b""
        key = cls.sanitize_str(
            key,
            cls.ALLOWED_CHARS_KEY,
            error_message="Invalid chars in property name: ",
        )
        value = cls.sanitize_str(
            cls.serialize_str(value),
            cls.ALLOWED_CHARS_PARAM,
            error_message="Invalid chars in property value: ",
        )
        return key.encode("ascii") + b"=" + value.encode("ascii")

    @staticmethod
    def parse_basic_device_properties(
        expected_device: "VirtualDevice", properties: Dict[str, Any]
    ):
        """
        Validates properties against an expected port configuration.

        Modifies `properties`.

        Raises:
            UnexpectedDeviceProperty: If any property does not match
            the expected values.
        """
        expected = expected_device.port
        exp_vm_name = expected.backend_name
        if properties.get("backend_domain", exp_vm_name) != exp_vm_name:
            raise UnexpectedDeviceProperty(
                f"Got device exposed by {properties['backend_domain']}"
                f"when expected devices from {exp_vm_name}."
            )
        properties.pop("backend_domain", None)

        if properties.get("port_id", expected.port_id) != expected.port_id:
            raise UnexpectedDeviceProperty(
                f"Got device from port: {properties['port_id']} "
                f"when expected port: {expected.port_id}."
            )
        properties.pop("port_id", None)

        if not expected.has_devclass:
            expected = Port(
                expected.backend_domain,
                expected.port_id,
                properties.get("devclass", None),
            )
        if properties.get("devclass", expected.devclass) != expected.devclass:
            raise UnexpectedDeviceProperty(
                f"Got {properties['devclass']} device "
                f"when expected {expected.devclass}."
            )
        properties.pop("devclass", None)

        expected_devid = expected_device.device_id
        # device id is optional
        if expected_devid != "*":
            if properties.get("device_id", expected_devid) != expected_devid:
                raise UnexpectedDeviceProperty(
                    f"Unrecognized device identity '{properties['device_id']}' "
                    f"expected '{expected_device.device_id}'"
                )
        properties["device_id"] = properties.get("device_id", expected_devid)

        properties["port"] = expected

    @staticmethod
    def serialize_str(value: str) -> str:
        """
        Serialize python string to ensure consistency.
        """
        return "'" + str(value).replace("'", r"\'") + "'"

    @staticmethod
    def deserialize_str(value: str) -> str:
        """
        Deserialize python string to ensure consistency.
        """
        return value.replace(r"\'", "'")

    @staticmethod
    def sanitize_str(
        untrusted_value: str,
        allowed_chars: set,
        replace_char: Optional[str] = None,
        error_message: str = "",
    ) -> str:
        """
        Sanitize given untrusted string.

        If `replace_char` is not None, ignore `error_message` and replace
        invalid characters with the string.
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


class Port:
    """
    Class of a *bus* device port with *port id* exposed by a *backend domain*.

    Attributes:
        backend_domain (QubesVM): The domain which exposes devices,
            e.g.`sys-usb`.
        port_id (str): A unique (in backend domain) identifier for the port.
        devclass (str): The class of the port (e.g., 'usb', 'pci').
    """

    def __init__(
        self,
        backend_domain: Optional[QubesVM],
        port_id: Optional[str],
        devclass: Optional[str],
    ):
        self.__backend_domain = backend_domain
        self.__port_id = port_id
        self.__devclass = devclass

    def __hash__(self):
        return hash((self.backend_name, self.port_id, self.devclass))

    def __eq__(self, other):
        if isinstance(other, Port):
            return (
                self.backend_name == other.backend_name
                and self.port_id == other.port_id
                and self.devclass == other.devclass
            )
        return False

    def __lt__(self, other):
        if isinstance(other, Port):
            return (self.backend_name, self.devclass, self.port_id) < (
                other.backend_name,
                other.devclass,
                other.port_id,
            )
        raise TypeError(
            f"Comparing instances of 'Port' and '{type(other)}' "
            "is not supported"
        )

    def __repr__(self):
        return f"{self.backend_name}+{self.port_id}"

    def __str__(self):
        return f"{self.backend_name}:{self.port_id}"

    @property
    def backend_name(self) -> str:
        # pylint: disable=missing-function-docstring
        if self.backend_domain is not None:
            return self.backend_domain.name
        return "*"

    @classmethod
    def from_qarg(
        cls, representation: str, devclass, domains, blind=False
    ) -> "Port":
        """
        Parse qrexec argument <back_vm>+<port_id> to retrieve Port.
        """
        if blind:
            get_domain = domains.get_blind
        else:
            get_domain = domains.__getitem__
        return cls._parse(representation, devclass, get_domain, "+")

    @classmethod
    def from_str(
        cls, representation: str, devclass, domains, blind=False
    ) -> "Port":
        """
        Parse string <back_vm>:<port_id> to retrieve Port.
        """
        if blind:
            get_domain = domains.get_blind
        else:
            get_domain = domains.__getitem__
        return cls._parse(representation, devclass, get_domain, ":")

    @classmethod
    def _parse(
        cls, representation: str, devclass: str, get_domain: Callable, sep: str
    ) -> "Port":
        """
        Parse string representation and return instance of Port.
        """
        backend_name, port_id = representation.split(sep, 1)
        backend = get_domain(backend_name)
        return cls(backend_domain=backend, port_id=port_id, devclass=devclass)

    @property
    def port_id(self) -> str:
        """
        Immutable port identifier.

        Unique for given domain and devclass.
        """
        if self.__port_id is not None:
            return self.__port_id
        return "*"

    @property
    def backend_domain(self) -> Optional[QubesVM]:
        """Which domain exposed this port. (immutable)"""
        return self.__backend_domain

    @property
    def devclass(self) -> str:
        """Immutable port class such like: 'usb', 'pci' etc.

        For unknown classes "peripheral" is returned.
        """
        if self.__devclass:
            return self.__devclass
        return "peripheral"

    @property
    def has_devclass(self):
        """Returns True if devclass is set."""
        return self.__devclass is not None


class AnyPort(Port):
    """Represents any port in virtual devices ("*")"""

    def __init__(self, devclass: str):
        super().__init__(None, "*", devclass)

    def __repr__(self):
        return "*"

    def __str__(self):
        return "*"


class VirtualDevice:
    """
    Class of a device connected to *port*.

    Attributes:
        port (Port): Peripheral device port exposed by vm.
        device_id (str): An identifier for the device.
    """

    def __init__(
        self,
        port: Optional[Port] = None,
        device_id: Optional[str] = None,
    ):
        assert not isinstance(port, AnyPort) or device_id is not None
        self.port: Optional[Port] = port  # type: ignore
        self._device_id = device_id

    def clone(self, **kwargs) -> "VirtualDevice":
        """
        Clone object and substitute attributes with explicitly given.
        """
        attr: Dict[str, Any] = {
            "port": self.port,
            "device_id": self.device_id,
        }
        attr.update(kwargs)
        return VirtualDevice(**attr)

    @property
    def port(self) -> Port:
        # pylint: disable=missing-function-docstring
        return self._port

    @port.setter
    def port(self, value: Union[Port, str, None]):
        # pylint: disable=missing-function-docstring
        if isinstance(value, Port):
            self._port = value
            return
        if isinstance(value, str) and value != "*":
            raise ValueError("Unsupported value for port")
        if self.device_id == "*":
            raise ValueError("Cannot set port to '*' if device_is is '*'")
        self._port = AnyPort(self.devclass)

    @property
    def device_id(self) -> str:
        # pylint: disable=missing-function-docstring
        if self._device_id is not None and self.is_device_id_set:
            return self._device_id
        return "*"

    @property
    def is_device_id_set(self) -> bool:
        """
        Check if `device_id` is explicitly set.
        """
        return self._device_id is not None

    @property
    def backend_domain(self) -> Optional[QubesVM]:
        # pylint: disable=missing-function-docstring
        return self.port.backend_domain

    @property
    def backend_name(self) -> str:
        """
        Return backend domain name if any or `*`.
        """
        return self.port.backend_name

    @property
    def port_id(self) -> str:
        # pylint: disable=missing-function-docstring
        return self.port.port_id

    @property
    def devclass(self) -> str:
        # pylint: disable=missing-function-docstring
        return self.port.devclass

    @property
    def description(self) -> str:
        """
        Return human-readable description of the device identity.
        """
        if not self.device_id or self.device_id == "*":
            return "any device"
        return self.device_id

    def __hash__(self):
        return hash((self.port, self.device_id))

    def __eq__(self, other):
        if isinstance(other, (VirtualDevice, DeviceAssignment)):
            result = (
                self.port == other.port and self.device_id == other.device_id
            )
            return result
        if isinstance(other, Port):
            return self.port == other and self.device_id == "*"
        return super().__eq__(other)

    def __lt__(self, other):
        """
        Desired order (important for auto-attachment):

        1. <portid>:<devid>
        2. <portid>:*
        3. *:<devid>
        4. *:*
        """
        if isinstance(other, (VirtualDevice, DeviceAssignment)):
            if isinstance(self.port, AnyPort) and not isinstance(
                other.port, AnyPort
            ):
                return True
            if not isinstance(self.port, AnyPort) and isinstance(
                other.port, AnyPort
            ):
                return False
            reprs = {self: [self.port], other: [other.port]}
            for obj, obj_repr in reprs.items():
                if obj.device_id != "*":
                    obj_repr.append(obj.device_id)
            return reprs[self] < reprs[other]
        if isinstance(other, Port):
            _other = VirtualDevice(other, "*")
            return self < _other
        raise TypeError(
            f"Comparing instances of {type(self)} and '{type(other)}' "
            "is not supported"
        )

    def __repr__(self):
        return f"{self.port!r}:{self.device_id}"

    def __str__(self):
        return f"{self.port}:{self.device_id}"

    @classmethod
    def from_qarg(
        cls,
        representation: str,
        devclass: Optional[str],
        domains,
        blind: bool = False,
        backend: Optional[QubesVM] = None,
    ) -> "VirtualDevice":
        """
        Parse qrexec argument <back_vm>+<port_id>:<device_id> to get device info
        """
        if backend is None:
            if blind:
                get_domain = domains.get_blind
            else:
                get_domain = domains.__getitem__
        else:
            get_domain = None
        return cls._parse(representation, devclass, get_domain, backend, "+")

    @classmethod
    def from_str(
        cls,
        representation: str,
        devclass: Optional[str],
        domains,
        blind: bool = False,
        backend: Optional[QubesVM] = None,
    ) -> "VirtualDevice":
        """
        Parse string <back_vm>+<port_id>:<device_id> to get device info
        """
        if backend is None:
            if blind:
                get_domain = domains.get_blind
            else:
                get_domain = domains.__getitem__
        else:
            get_domain = None
        return cls._parse(representation, devclass, get_domain, backend, ":")

    @classmethod
    def _parse(
        cls,
        representation: str,
        devclass: Optional[str],
        get_domain: Callable,
        backend: Optional[QubesVM],
        sep: str,
    ) -> "VirtualDevice":
        """
        Parse string representation and return instance of VirtualDevice.
        """
        if backend is None:
            backend_name, identity = representation.split(sep, 1)
            if backend_name != "*":
                backend = get_domain(backend_name)
        else:
            identity = representation

        port_id, _, devid = identity.partition(":")
        return cls(
            Port(backend_domain=backend, port_id=port_id, devclass=devclass),
            device_id=devid or None,
        )

    def serialize(self) -> bytes:
        """
        Serialize an object to be transmitted via Qubes API.
        """
        properties = b" ".join(
            DeviceSerializer.pack_property(key, value)
            for key, value in (
                ("device_id", self.device_id),
                ("port_id", self.port_id),
                ("devclass", self.devclass),
                ("backend_domain", self.backend_name),
            )
        )

        return properties


class DeviceCategory(Enum):
    """
    Category of a peripheral device.

    Arbitrarily selected interfaces that are important to users,
    thus deserving special recognition such as a custom icon, etc.
    """

    # pylint: disable=invalid-name
    Other = ("*******",)  # also matches all devices, if used to block

    # The following devices are used in GUI for blocks; take note when changing

    # modems, WiFi and Ethernet adapters
    Network = ("u02****", "p0703**", "p02****", "ue0****")
    Keyboard = ("u03**01", "p0900**")
    Mouse = ("u03**02", "p0902**")
    Input = ("u03****", "p09****")  # HID etc.
    Printer = ("u07****",)
    Camera = ("p0903**", "u06****", "u0e****")  # cameras and scanners

    Microphone = ("m******",)
    Audio = ("p0403**", "p0401**", "p0408**", "u01****", "m******")
    # Multimedia = Audio, Video, Displays etc.
    Multimedia = ("u10****", "p03****", "p04****")
    USB_Storage = ("u08****",)
    Block_Storage = ("b******",)
    Storage = ("b******", "u08****", "p01****")
    Bluetooth = ("ue00101", "p0d11**")
    Smart_Card_Readers = ("u0b****",)

    Display = ("p0300**", "p0380**")  # PCI screens?
    Memory = ("p05****",)
    PCI_Bridge = ("p06****",)
    Docking_Station = ("p0a****",)
    Processor = ("p0b****", "p40****")
    PCI_Serial_Bus = ("p0c****",)
    PCI_USB = ("p0c03**",)

    @staticmethod
    def from_str(interface_encoding: str) -> "DeviceCategory":
        """
        Returns `DeviceCategory` from data encoded in string.
        """
        result = DeviceCategory.Other
        if len(interface_encoding) != len(DeviceCategory.Other.value[0]):
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
        ifc_padded = interface_encoding.ljust(6, "*")
        if devclass:
            if len(ifc_padded) > 6:
                print(
                    f"{interface_encoding=} is too long "
                    f"(is {len(interface_encoding)}, expected max. 6) "
                    f"for given {devclass=}",
                    file=sys.stderr,
                )
            if not all(c in string.hexdigits + "*" for c in ifc_padded):
                raise ProtocolError("Invalid characters in interface encoding")
            devclass_code = devclass[0].lower()
            if devclass_code not in string.ascii_lowercase:
                raise ProtocolError("Invalid characters in devclass encoding")
            ifc_full = devclass_code + ifc_padded
        else:
            known_devclasses = {
                "p": "pci",
                "u": "usb",
                "b": "block",
                "m": "mic",
            }
            devclass = known_devclasses.get(interface_encoding[0], None)
            if len(ifc_padded) > 7:
                print(
                    f"{interface_encoding=} is too long "
                    f"(is {len(interface_encoding)}, expected max. 7)",
                    file=sys.stderr,
                )
                ifc_full = ifc_padded
            elif len(ifc_padded) == 6:
                ifc_full = "?" + ifc_padded
            else:
                ifc_full = ifc_padded

        self._devclass = devclass
        self._interface_encoding = ifc_full
        self._category = DeviceCategory.from_str(self._interface_encoding)

    @property
    def devclass(self) -> Optional[str]:
        """Immutable Device class such like: 'usb', 'pci' etc."""
        return self._devclass

    @property
    def category(self) -> DeviceCategory:
        """Immutable Device category such like: 'Mouse', 'Mass_Data' etc."""
        return self._category

    @classmethod
    def unknown(cls) -> "DeviceInterface":
        """Value for unknown device interface."""
        return cls("?******")

    @staticmethod
    def from_str_bulk(interfaces: Optional[str]) -> List["DeviceInterface"]:
        """Interprets string of interfaces as list of `DeviceInterface`.

        Examples:
        "cITERFC" -> [DeviceInterface("cITERFC")]
        "cITERFCcinterfc" -> [DeviceInterface("cITERFC"),
                              DeviceInterface("cinterfc")]
        """
        interfaces = interfaces or ""
        if len(interfaces) % 7 != 0:
            raise QubesValueError(
                f"Invalid length of {interfaces=} "
                f"(is {len(interfaces)}, expected multiple of 7)",
            )
        return [
            DeviceInterface(interfaces[i : i + 7])
            for i in range(0, len(interfaces), 7)
        ]

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
                self._interface_encoding[1:-2] + "**", None
            )
            if result is None or result.lower() in (
                "none",
                "no subclass",
                "unused",
                "undefined",
                "vendor specific subclass",
            ):
                # if not, try interface
                result = self._load_classes(self.devclass).get(
                    self._interface_encoding[1:], None
                )
            if result is None or result.lower() in (
                "none",
                "unused",
                "undefined",
            ):
                # if not, try class
                result = self._load_classes(self.devclass).get(
                    self._interface_encoding[1:-4] + "****", None
                )
            if result is None or result.lower() in (
                "none",
                "unused",
                "undefined",
                "vendor specific class",
            ):
                result = f"{self.devclass.upper()} device"
            return result
        if self.devclass == "mic":
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
        with open(
            f"/usr/share/hwdata/{bus}.ids", encoding="utf-8", errors="ignore"
        ) as pciids:
            # for `class_name` and `subclass_name`
            # pylint: disable=used-before-assignment
            class_id = None
            subclass_id = None
            for line in pciids.readlines():
                line = line.rstrip()
                if (
                    line.startswith("\t\t")
                    and class_id is not None
                    and subclass_id is not None
                ):
                    (progif_id, _, progif_name) = line[2:].split(" ", 2)
                    result[class_id + subclass_id + progif_id] = progif_name
                elif line.startswith("\t") and class_id:
                    (subclass_id, _, subclass_name) = line[1:].split(" ", 2)
                    # store both prog-if specific entry and generic one
                    result[class_id + subclass_id + "**"] = subclass_name
                elif line.startswith("C "):
                    (_, class_id, _, class_name) = line.split(" ", 3)
                    result[class_id + "****"] = class_name
                    subclass_id = None

        return result

    def matches(self, other: "DeviceInterface") -> bool:
        """
        Check if this `DeviceInterface` (pattern) matches given one.

        The matching is done character by character using the string
        representation (`repr`) of both objects. A wildcard character (`'*'`)
        in the pattern (i.e., `self`) can match any character in the candidate
        (i.e., `other`).
        The two representations must be of the same length.
        """
        pattern = repr(self)
        candidate = repr(other)
        if len(pattern) != len(candidate):
            return False
        for patt, cand in zip(pattern, candidate):
            if patt == "*":
                continue
            if patt != cand:
                return False
        return True


class DeviceInfo(VirtualDevice):
    """Holds all information about a device"""

    def __init__(
        self,
        port: Port,
        *,
        vendor: Optional[str] = None,
        product: Optional[str] = None,
        manufacturer: Optional[str] = None,
        name: Optional[str] = None,
        serial: Optional[str] = None,
        interfaces: Optional[List[DeviceInterface]] = None,
        parent: Optional["DeviceInfo"] = None,
        attachment: Optional[QubesVM] = None,
        device_id: Optional[str] = None,
        **kwargs,
    ):
        super().__init__(port, device_id)

        self._vendor = vendor
        self._product = product
        self._manufacturer = manufacturer
        self._name = name
        self._serial = serial
        self._interfaces = interfaces
        self._parent = parent
        self._attachment = attachment

        self.data = kwargs

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

        for interface in self.interfaces:
            if interface.category.name != "Other":
                cat = interface.category.name
                break
        else:
            for interface in self.interfaces:
                if str(interface) != f"{self.devclass.upper()} device":
                    cat = str(interface).replace("_", " ")
                    break
            else:
                cat = f"{self.devclass.upper()} device"
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
    def parent_device(self) -> Optional[VirtualDevice]:
        """
        The parent device, if any.

        If the device is part of another device (e.g., it's a single
        partition of a USB stick), the parent device id should be here.
        """
        return self._parent

    @property
    def subdevices(self) -> List[VirtualDevice]:
        """
        The list of children devices if any.

        If the device has subdevices (e.g., partitions of a USB stick),
        the subdevices id should be here.
        """
        if not self.backend_domain:
            return []
        return [
            dev
            for devclass in self.backend_domain.devices.keys()
            for dev in self.backend_domain.devices[devclass]
            if dev.parent_device.port.port_id == self.port_id
        ]

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
        properties = super().serialize()
        # 'attachment', 'interfaces', 'data', 'parent_device'
        # are not string, so they need special treatment
        default = DeviceInfo(self.port)
        default_attrs = {"vendor", "product", "manufacturer", "name", "serial"}
        properties += b" " + b" ".join(
            DeviceSerializer.pack_property(key, value)
            for key, value in (
                (key, getattr(self, key))
                for key in default_attrs
                if getattr(self, key) != getattr(default, key)
            )
        )

        if self.attachment:
            properties += b" " + DeviceSerializer.pack_property(
                "attachment", self.attachment.name
            )

        properties += b" " + DeviceSerializer.pack_property(
            "interfaces", "".join(repr(ifc) for ifc in self.interfaces)
        )

        if self.parent_device is not None:
            properties += b" " + DeviceSerializer.pack_property(
                "parent_port_id", self.parent_device.port_id
            )
            properties += b" " + DeviceSerializer.pack_property(
                "parent_devclass", self.parent_device.devclass
            )

        for key, value in self.data.items():
            properties += b" " + DeviceSerializer.pack_property(
                "_" + key, value
            )

        return properties

    @classmethod
    def deserialize(
        cls,
        serialization: bytes,
        expected_backend_domain: QubesVM,
        expected_devclass: Optional[str] = None,
    ) -> "DeviceInfo":
        """
        Recovers a serialized object, see: :py:meth:`serialize`.
        """
        head, _, rest = serialization.partition(b" ")
        device = VirtualDevice.from_str(
            head.decode("ascii", errors="ignore"),
            expected_devclass,
            domains=None,
            backend=expected_backend_domain,
        )

        try:
            device = cls._deserialize(rest, device)
            # pylint: disable=broad-exception-caught
        except Exception as exc:
            print(str(exc), file=sys.stderr)
            device = UnknownDevice.from_device(device)

        return device

    @classmethod
    def _deserialize(
        cls, untrusted_serialization: bytes, expected_device: VirtualDevice
    ) -> "DeviceInfo":
        """
        Actually deserializes the object.
        """
        properties, options = DeviceSerializer.unpack_properties(
            untrusted_serialization
        )
        properties.update(options)

        DeviceSerializer.parse_basic_device_properties(
            expected_device, properties
        )

        if "attachment" not in properties or not properties["attachment"]:
            properties["attachment"] = None
        elif expected_device.backend_domain:
            app = expected_device.backend_domain.app
            properties["attachment"] = app.domains.get_blind(
                properties["attachment"]
            )

        if "interfaces" in properties:
            interfaces = properties["interfaces"]
            properties["interfaces"] = DeviceInterface.from_str_bulk(interfaces)

        if "parent_port_id" in properties:
            properties["parent"] = Port(
                backend_domain=expected_device.backend_domain,
                port_id=properties["parent_port_id"],
                devclass=properties["parent_devclass"],
            )
            del properties["parent_port_id"]
            del properties["parent_devclass"]

        return cls(**properties)

    @property
    def device_id(self) -> str:
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
        if not self._device_id:
            return "0000:0000::?******"
        return self._device_id

    @device_id.setter
    def device_id(self, value):
        # Do not auto-override value like in super class
        self._device_id = value


class UnknownDevice(DeviceInfo):
    # pylint: disable=too-few-public-methods
    """Unknown device - for example, exposed by domain not running currently"""

    @staticmethod
    def from_device(device: VirtualDevice) -> "UnknownDevice":
        """
        Return `UnknownDevice` based on any virtual device.
        """
        return UnknownDevice(device.port, device_id=device.device_id)


class AssignmentMode(Enum):
    """
    Device assignment modes
    """

    MANUAL = "manual"
    ASK = "ask-to-attach"
    AUTO = "auto-attach"
    REQUIRED = "required"


class DeviceAssignment:
    """
    Maps a device to a frontend_domain.
    """

    def __init__(
        self,
        device: VirtualDevice,
        frontend_domain=None,
        options=None,
        mode: Union[str, AssignmentMode] = "manual",
    ):
        if isinstance(device, DeviceInfo):
            device = VirtualDevice(device.port, device.device_id)
        self.virtual_device = device
        self.__options = options or {}
        if isinstance(mode, AssignmentMode):
            self.mode = mode
        else:
            self.mode = AssignmentMode(mode)
        self.frontend_domain = frontend_domain

    @classmethod
    def new(
        cls,
        backend_domain: QubesVM,
        port_id: str,
        devclass: str,
        device_id: Optional[str] = None,
        *,
        frontend_domain: Optional[QubesVM] = None,
        options=None,
        mode: Union[str, AssignmentMode] = "manual",
    ) -> "DeviceAssignment":
        """Helper method to create a DeviceAssignment object."""
        return cls(
            VirtualDevice(Port(backend_domain, port_id, devclass), device_id),
            frontend_domain,
            options,
            mode,
        )

    def clone(self, **kwargs):
        """
        Clone object and substitute attributes with explicitly given.
        """
        attr = {
            "device": self.virtual_device,
            "options": self.options,
            "mode": self.mode,
            "frontend_domain": self.frontend_domain,
        }
        attr.update(kwargs)
        return self.__class__(**attr)

    def __repr__(self):
        return f"{self.virtual_device!r}"

    def __str__(self):
        return f"{self.virtual_device}"

    def __hash__(self):
        return hash(self.virtual_device)

    def __eq__(self, other):
        if isinstance(other, (VirtualDevice, DeviceAssignment)):
            result = (
                self.port == other.port and self.device_id == other.device_id
            )
            return result
        return False

    def __lt__(self, other):
        if isinstance(other, DeviceAssignment):
            return self.virtual_device < other.virtual_device
        if isinstance(other, VirtualDevice):
            return self.virtual_device < other
        raise TypeError(
            f"Comparing instances of {type(self)} and '{type(other)}' "
            "is not supported"
        )

    @property
    def backend_domain(self) -> Optional[QubesVM]:
        # pylint: disable=missing-function-docstring
        return self.virtual_device.backend_domain

    @property
    def backend_name(self) -> str:
        # pylint: disable=missing-function-docstring
        return self.virtual_device.backend_name

    @property
    def port_id(self) -> str:
        # pylint: disable=missing-function-docstring
        return self.virtual_device.port_id

    @property
    def devclass(self) -> str:
        # pylint: disable=missing-function-docstring
        return self.virtual_device.devclass

    @property
    def device_id(self) -> str:
        # pylint: disable=missing-function-docstring
        return self.virtual_device.device_id

    @property
    def devices(self) -> List[DeviceInfo]:
        """Get DeviceInfo objects corresponding to this DeviceAssignment"""
        result: List[DeviceInfo] = []
        if not self.backend_domain:
            return result
        if self.port_id != "*":
            dev = self.backend_domain.devices[self.devclass][self.port_id]
            if isinstance(dev, UnknownDevice) or (
                dev and self.device_id in (dev.device_id, "*")
            ):
                return [dev]
        if self.device_id == "0000:0000::?******":
            return result
        for dev in self.backend_domain.devices[self.devclass]:
            if self.matches(dev):
                result.append(dev)
        return result

    @property
    def device(self) -> DeviceInfo:
        """
        Get single DeviceInfo object or raise an error.

        If port id is set we have exactly one device
        since we can attach ony one device to one port.
        If assignment is more general we can get 0 or many devices.
        """
        devices = self.devices
        if len(devices) == 1:
            return devices[0]
        if len(devices) > 1:
            raise ProtocolError("Too many devices matches to assignment")
        raise ProtocolError("No devices matches to assignment")

    @property
    def port(self) -> Port:
        """
        Device port visible in Qubes.
        """
        return Port(self.backend_domain, self.port_id, self.devclass)

    @property
    def frontend_domain(self) -> Optional[QubesVM]:
        """Which domain the device is attached/assigned to."""
        return self.__frontend_domain

    @frontend_domain.setter
    def frontend_domain(self, frontend_domain: Optional[Union[str, QubesVM]]):
        """Which domain the device is attached/assigned to."""
        if isinstance(frontend_domain, str):
            if not self.backend_domain:
                raise ProtocolError("Cannot determine backend domain")
            self.__frontend_domain: Optional[QubesVM] = (
                self.backend_domain.app.domains[frontend_domain]
            )
        else:
            self.__frontend_domain = frontend_domain

    @property
    def attached(self) -> bool:
        """
        Is the device attached to the fronted domain?

        Returns False if device is attached to different domain
        """
        for device in self.devices:
            if device.attachment and device.attachment == self.frontend_domain:
                return True
        return False

    @property
    def required(self) -> bool:
        """
        Is the presence of this device required for the domain to start? If yes,
        it will be attached automatically.
        """
        return self.mode == AssignmentMode.REQUIRED

    @property
    def attach_automatically(self) -> bool:
        """
        Should this device automatically connect to the frontend domain when
        available and not connected to other qubes?
        """
        return self.mode in (
            AssignmentMode.AUTO,
            AssignmentMode.ASK,
            AssignmentMode.REQUIRED,
        )

    @property
    def options(self) -> Dict[str, Any]:
        """Device options (same as in the legacy API)."""
        return self.__options

    @options.setter
    def options(self, options: Optional[Dict[str, Any]]):
        """Device options (same as in the legacy API)."""
        self.__options = options or {}

    def serialize(self) -> bytes:
        """
        Serialize an object to be transmitted via Qubes API.
        """
        properties = self.virtual_device.serialize()
        properties += b" " + DeviceSerializer.pack_property(
            "mode", self.mode.value
        )
        if self.frontend_domain is not None:
            properties += b" " + DeviceSerializer.pack_property(
                "frontend_domain", self.frontend_domain.name
            )

        for key, value in self.options.items():
            properties += b" " + DeviceSerializer.pack_property(
                "_" + key, value
            )

        return properties

    @classmethod
    def deserialize(
        cls,
        serialization: bytes,
        expected_device: VirtualDevice,
    ) -> "DeviceAssignment":
        """
        Recovers a serialized object, see: :py:meth:`serialize`.
        """
        try:
            result = cls._deserialize(serialization, expected_device)
        except Exception as exc:
            raise ProtocolError(str(exc)) from exc
        return result

    @classmethod
    def _deserialize(
        cls,
        untrusted_serialization: bytes,
        expected_device: VirtualDevice,
    ) -> "DeviceAssignment":
        """
        Actually deserializes the object.
        """
        properties, options = DeviceSerializer.unpack_properties(
            untrusted_serialization
        )
        properties["options"] = options

        DeviceSerializer.parse_basic_device_properties(
            expected_device, properties
        )

        expected_device = expected_device.clone(
            device_id=properties["device_id"]
        )
        # we do not need port, we need device
        del properties["port"]
        del properties["device_id"]
        properties["device"] = expected_device

        return cls(**properties)

    def matches(self, device: VirtualDevice) -> bool:
        """
        Checks if the given device matches the assignment.
        """
        if self.devclass != device.devclass:
            return False
        if self.backend_domain != device.backend_domain:
            return False
        if self.port_id not in ("*", device.port_id):
            return False
        if self.device_id not in ("*", device.device_id):
            return False
        return True
