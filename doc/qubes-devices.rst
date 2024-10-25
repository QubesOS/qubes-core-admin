:py:mod:`qubes.devices` -- Devices
==================================

The main concept is that a domain (backend) can expose (potentially multiple)
devices, each through a port, where only one device can be in one port at
any given time. Such devices can be connected to other domains (frontends).
Devices can be of different buses (like 'pci', 'usb', etc.). Each device bus
is implemented by an extension (see :py:mod:`qubes.ext`).

Devices are identified by a pair (`port`, `device_id`), where `port` is a pair
(backend domain, `port_id`). Both `port_id` and `device_id` are :py:class:`str`,
and in addition, port_id is unique per backend. More about the requirements
for `port_id` and `device_id` can be found in the sections below.

Classes
-------

:py:class:`qubes.device_protocol.Port`: a pair `<backend_domain>:<port_id>`
with `devclass` (e.g., `pci`, `usb`). In the previous version (before
QubesOS 4.3), this was referred to as `Device`, and `port_id` was named `ident`.

:py:class:`qubes.device_protocol.AnyPort`: A class used to handle cases where
any port is accepted.

:py:class:`qubes.device_protocol.VirtualDevice`: A pair `<port>:<device_id>`.
This class links a device identified by `device_id` to a specific port.
If both values are specified, the instance represents a device connected to
that particular port. If the port is of type `AnyPort`, it represents a device
identified by `device_id` that can be connected to any port. This is used by
:py:class:`qubes.device_protocol.DeviceInfo`, which describes what to do with
a device identified by `device_id` when connected anywhere. Similarly,
when `device_id` is `*`, the instance represents any potential device
connected to the given port. As a result, the device is considered "virtual"
meaning it may or may not represent an actual device in the system.
A device with `*:*` (any port and any device) is not permitted.

:py:class:`qubes.device_protocol.DeviceInfo`: Derived from `VirtualDevice`.
Extensions should assume that `Port` is provided, and based on that,
`device_id` should return the same string for the same device, regardless of
which port it is connected to. The `device_id` acts as a device hash
and *should* be "human-readable". It must contain only digits, ASCII letters,
spaces, and the following characters: `!#$%&()*+,-./:;<>?@[\]^_{|}~`.
It cannot be empty or equal to `*`.

:py:class:`qubes.device_protocol.DeviceAssignment`: Represents the relationship
between a `VirtualDevice` and a `frontend_domain`. There are four modes:
#. `manual` (attachment): The device is manually attached to `frontend_domain`.
This type of assignment does not persist across domain restarts.
#. `auto-attach`: Any device that matches a `VirtualDevice` will be
automatically attached to the `frontend_domain` when discovered
or during domain startup.
#. `ask-to-attach`: Functions like `auto-attach`, but prompts the user for
confirmation before attaching. If no GUI is available, the prompt is ignored.
#. `required`: The device must be available during `frontend_domain` startup and
will be attached before the domain is started.

:py:class:`qubes.device_protocol.DeviceInterface`: Represents device interfaces
as a 7-character code in the format `BCCSSII`, where `B` indicates the devclass
(e.g., `p` for PCI, `u` for USB, `?` for unknown), `CC` is the class code,
`SS` is the subclass code, and `II` represents the interface code.

:py:class:`qubes.device_protocol.DeviceCategory`: Provides an easy-to-use,
arbitrary subset of interfaces with names assigned to categories considered as
most relevant to users. When needed, the class should be extended with new
categories. This structure allows for quick identification of the device type
and can be useful when displaying devices to the end user.

Device Assignment vs Attachment
-------------------------------

For clarity let's us introduce two types of assignments:
*potential* and *real* (attachment). Attachment indicates that the device
has been attached by the Qubes backend to its frontend VM and is visible
from its perspective. Potential assignment, on the other hand,
has tree modes: `auto-attach`, `ask-to-attach` and `required`.
For detailed descriptions, take a look at
:py:class:`qubes.device_protocol.DeviceAssignment` documentation.
In general we refer to potential assignment as assignment
and real assignment as attachment. To check whether the device is currently
attached, we check :py:meth:`qubes.device_protocol.DeviceAssignment.attached`,
while to check whether an (potential) assignment exists,
we check :py:meth:`qubes.device_protocol.DeviceAssignment.attach_automatically`.
Potential and real connections may coexist at the same time,
in which case both values will be true.

Understanding Device Identity
-----------------------------

It is important to understand that :py:class:`qubes.device_protocol.Port` does not
correspond to the device itself, but rather to the *port* to which the device
is connected. Therefore, when assigning a device to a VM, such as
`sys-usb:1-1.1`, the port `1-1.1` is actually assigned, and thus
*every* devices connected to it will be automatically attached.
Similarly, when assigning `vm:sda`, every block device with the name `sda`
will be automatically attached. We can limit this using
:py:meth:`qubes.device_protocol.DeviceInfo.device_id`, which returns a string
containing information presented by the device, such as for example
`vendor_id`, `product_id`, `serial_number`, and encoded interfaces.
In the case of block devices, `device_id` consists of the parent's `device_id`
to which the device is connected (if any) and the interface/partition number.
In practice, this means that, a partition on a USB drive will only
be automatically attached to a frontend domain if the parent presents
the correct serial number etc.

Actions
-------

The `assign` action means that a device will be assigned to the frontend VM
in a potential form (this does not change the current system state).
This will result in an attempt to automatically attach the device
upon the next VM startup. If `mode=required`, and the device cannot be attached,
the VM startup will fail. Additionally, upon device detection (`device-added`),
an attempt will be made to attach the device. However, at any time
(unless `mode=required`), the user can manually modify this state by performing
`attach` or `detach` on the device, changing the current system state.
This will not alter the assignment, and automatic attachment attempts
will still be made in the future. To remove the assignment the user
need to perform `unassign` (see next section).

Assignment Management
---------------------

Assignments can be edited at any time: regardless of whether the VM is running
or the device is currently attached. Removing the assignment does not change
the real system state, so if the device is currently attached and the user
remove the assignment, it will not be detached, but it will not be
automatically attached in the future. Similarly, it works the other way
around with `assign`.

Proper Assignment States
------------------------

In short, we can think of device assignment in terms of three flags:
#. `attached` - indicating whether the device is currently assigned,
#. `attach_automatically` - indicating whether the device will be
automatically attached by the system daemon,
#. `required` - determining whether the failure of automatic attachment should
result in the domain startup being interrupted.

Then the possible states of assignment
(`attached`, `automatically_attached`, `required`) are as follow:
#. `(True, False, False)` -> domain is running, device is manually attached
and could be manually detach any time.
#. `(True, True, False)` -> domain is running, device is attached
and could be manually detach any time (see 4.),
but in the future will be auto-attached again.
#. `(True, True, True)`   -> domain is running, device is attached
and couldn't be detached.
#. `(False, True, False)` -> device is assigned to domain, but not attached
because either (i) domain is halted, device (ii) manually detached or
(iii) attach to different domain.
#. `(False, True, True)`  -> domain is halted, device assigned to domain
and required to start domain.

Note that if `required=True` then `automatically_attached=True`.

Conflicted Assignments
----------------------

If a connected device has multiple assignments to different `frontend_domain`
instances, the user will be asked to choose which domain connect the device to.
If no GUI client is available, the device will not be connected to any domain.
If multiple assignments exist for a connected device with different options but
to the same `frontend_domain`, the most specific assignment will take
precedence, according to the following order (from highest to lowest priority):
#. Assignment specifies both `port` and `device_id`.
#. Assignment specifies only the `port`.
#. Assignment specifies only the `device_id`.

It is important to note that only one matching assignment can exist within
each of the categories listed above.

Port Assignment
---------------

It is possible to not assign a specific device but rather a port,
(e.g., we can use the `--port` flag in the client). In this case,
the value `*` will appear in the `identity` field of the `qubes.xml` file.
This indicates that the identity presented by the devices will be ignored,
and all connected devices will be automatically attached.


PCI Devices
-----------

PCI devices cannot be manually attached to a VM at any time.
We must first create an assignment (`assign`) as required
(in client we can use `--required` flag). Then, it will be automatically
attached upon each VM startup. However, if a PCI device is currently in use
by another VM, the startup of the second VM will fail.

Microphone
----------

The microphone cannot be assigned with the `mode=required` to any VM.

USB Devices
-----------

The USB devices cannot be assigned with the `mode=required` to any VM.


.. automodule:: qubes.devices
   :members:
   :show-inheritance:

.. vim: ts=3 sw=3 et
