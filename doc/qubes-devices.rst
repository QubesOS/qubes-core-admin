:py:mod:`qubes.devices` -- Devices
===================================

Main concept is that some domain (backend) may expose (potentially multiple)
devices, which can be attached to other domains (frontend). Devices can be of
different buses (like 'pci', 'usb', etc.). Each device bus is implemented by
an extension (see :py:mod:`qubes.ext`).

Devices are identified by pair of (backend domain, `ident`), where `ident` is
:py:class:`str` and can contain only characters from `[a-zA-Z0-9._-]` set.


Device Assignment vs Attachment
-------------------------------

:py:class:`qubes.devices.DeviceAssignment` describes the assignment of a device
to a frontend VM. For clarity let's us introduce two types of assignments:
*potential* and *real* (attachment). Attachment indicates that the device
has been attached by the Qubes backend to its frontend VM and is visible
from its perspective. Potential assignment, on the other hand,
has two additional options: `automatically_attach` and `required`.
For detailed descriptions, refer to the `DeviceAssignment` documentation.
In general we refer to potential assignment as assignment
and real assignment as attachment. To check whether the device is currently
attached, we check :py:meth:`qubes.devices.DeviceAssignment.attached`,
while to check whether an (potential) assignment exists,
we check :py:meth:`qubes.devices.DeviceAssignment.attach_automatically`.
Potential and real connections may coexist at the same time,
in which case both values will be true.


Actions
-------

The `assign` action signifies that a device will be assigned to the frontend VM
in a potential form (this does not change the current system state).
This will result in an attempt to automatically attach the device
upon the next VM startup. If `required=True`, and the device cannot be attached,
the VM startup will fail. Additionally, upon device detection (`device-added`),
an attempt will be made to attach the device. However, at any time
(unless `required=True`), the user can manually modify this state by performing
`attach` or `detach` on the device, changing the current system state.
This will not alter the assignment, and automatic attachment attempts
will still be made in the future. To remove the assignment the user
need to perform `unassign` (see next section).

Assignment Management
---------------------

Assignments can be edited at any time: regardless of whether the VM is running
or the device is currently attached. An exception is `required=True`,
in which case the VM must be shut down. Removing the assignment does not change the real system state, so if the device is currently attached
and the user remove the assignment, it will not be detached,
but it will not be automatically attached in the future.
Similarly, it works the other way around with `assign`.

Proper Assignment States
------------------------

In short, we can think of device assignment in terms of three flags:
#. `attached` - indicating whether the device is currently assigned,
#.  `attach_automatically` - indicating whether the device will be
automatically attached by the system daemon,
#. `required` - determining whether the failure of automatic attachment should
result in the domain startup being interrupted.

Then the proper states of assignment
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


PCI Devices
-----------

PCI devices cannot be manually attached to a VM at any time.
We must first create an assignment (`assign`) as required
(in client we can use `--required` flag) while the VM is turned off.
Then, it will be automatically attached upon each VM startup.
However, if a PCI device is currently in use by another VM,
the startup of the second VM will fail.
PCI devices can only be assigned with the `required=True`, which does not
allow for manual modification of the state during VM operation (attach/detach).

Microphone
----------

The microphone cannot be assigned (potentially) to any VM (attempting to attach the microphone during VM startup fails).

Understanding Device Self Identity
----------------------------------

It is important to understand that :py:class:`qubes.devices.Device` does not
correspond to the device itself, but rather to the *port* to which the device
is connected. Therefore, when assigning a device to a VM, such as
`sys-usb:1-1.1`, the port `1-1.1` is actually assigned, and thus
*every* devices connected to it will be automatically attached.
Similarly, when assigning `vm:sda`, every block device with the name `sda`
will be automatically attached. We can limit this using :py:meth:`qubes.devices.DeviceInfo.self_identity`, which returns a string containing information
presented by the device, such as, `vendor_id`, `product_id`, `serial_number`,
and encoded interfaces. In the case of block devices, `self_identity`
consists of the parent port to which the device is connected (if any),
the parent's `self_identity`, and the interface/partition number.
In practice, this means that, a partition on a USB drive will only be
automatically attached to a frontend domain if the parent presents
the correct serial number etc., and is connected to a specific port.

Port Assignment
---------------

It is possible to not assign a specific device but rather a port,
(e.g., we can use the `--port` flag in the client). In this case,
the value `any` will appear in the `identity` field of the `qubes.xml` file.
This indicates that the identity presented by the devices will be ignored,
and all connected devices will be automatically attached. Note that to create
an assignment, *any* device must currently be connected to the port.


.. automodule:: qubes.devices
   :members:
   :show-inheritance:

.. vim: ts=3 sw=3 et
