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

"""
Qubes OS exception hierarchy
"""


class QubesException(Exception):
    """Exception that can be shown to the user"""


class ProtocolError(AssertionError):
    """Raised deliberately by handlers to indicate a malformed client request.

    Client programming errors. The client made a request that it should have
    known better than to send in the first place. Includes things like passing
    an argument or payload to a service documented to not take one. The only
    way that a correctly behaving client can get ProtocolError is qubesd is
    either buggy or too old. In HTTP, this would be 400 Bad Request.

    It should not be used to reject requests that are valid, but which qubesd
    is refusing to process. Instead, raise a subclass of
    :py:class:`QubesException` with a useful error message.
    """


class PermissionDenied(PermissionError):
    """Raised deliberately by handlers to inform the request is prohibited.

    The request is valid, but the client does not have permission to perform
    the operation. Clients in dom0 should usually not get this error. It must
    only be raised by "admin-permission" events. In HTTP, this would be 403
    Forbidden.
    """


class QubesVMNotFoundError(QubesException, KeyError):
    """Domain cannot be found in the system"""

    def __init__(self, vmname):
        super().__init__("No such domain: {!r}".format(vmname))
        self.vmname = vmname

    def __str__(self):
        # KeyError overrides __str__ method
        return QubesException.__str__(self)


class QubesVMInvalidUUIDError(QubesException):
    """Domain UUID is invalid"""

    # pylint: disable = super-init-not-called
    def __init__(self, uuid: str) -> None:
        # QubesVMNotFoundError overrides __init__ method
        # pylint: disable = non-parent-init-called
        QubesException.__init__(self, f"VM UUID is not valid: {uuid!r}")
        self.vmname = uuid


class QubesVMError(QubesException):
    """Some problem with domain state."""

    def __init__(self, vm, msg):
        super().__init__(msg)
        self.vm = vm


class QubesVMInUseError(QubesVMError):
    """VM is in use, cannot remove."""

    def __init__(self, vm, msg=None):
        super().__init__(vm, msg or "Domain is in use: {!r}".format(vm.name))


class QubesVMNotStartedError(QubesVMError):
    """Domain is not started.

    This exception is thrown when machine is halted, but should be started
    (that is, either running or paused).
    """

    def __init__(self, vm, msg=None):
        super().__init__(
            vm, msg or "Domain is powered off: {!r}".format(vm.name)
        )


class QubesVMNotRunningError(QubesVMNotStartedError):
    """Domain is not running.

    This exception is thrown when machine should be running but is either
    halted or paused.
    """

    def __init__(self, vm, msg=None):
        super().__init__(
            vm,
            msg
            or "Domain not running (either powered off or paused): {!r}".format(
                vm.name
            ),
        )


class QubesVMNotPausedError(QubesVMNotStartedError):
    """Domain is not paused.

    This exception is thrown when machine should be paused, but is not.
    """

    def __init__(self, vm, msg=None):
        super().__init__(
            vm, msg or "Domain is not paused: {!r}".format(vm.name)
        )


class QubesVMCancelledPauseError(QubesVMError):
    """Cancelled pause during domain-pre-paused event.

    This exception is thrown when machine should skip pause as it doesn't make
    sense to pause anymore.
    """

    def __init__(self, vm, msg=None):
        super().__init__(
            vm, msg or "Domain won't be paused: {!r}".format(vm.name)
        )


class QubesVMNotSuspendedError(QubesVMError):
    """Domain is not suspended.

    This exception is thrown when machine should be suspended but is either
    halted or running.
    """

    def __init__(self, vm, msg=None):
        super().__init__(
            vm, msg or "Domain is not suspended: {!r}".format(vm.name)
        )


class QubesVMNotHaltedError(QubesVMError):
    """Domain is not halted.

    This exception is thrown when machine should be halted, but is not (either
    running or paused).
    """

    def __init__(self, vm, msg=None):
        super().__init__(
            vm, msg or "Domain is not powered off: {!r}".format(vm.name)
        )


class QubesVMShutdownTimeoutError(QubesVMError):
    """Domain shutdown timed out."""

    def __init__(self, vm, msg=None):
        super().__init__(
            vm, msg or "Domain shutdown timed out: {!r}".format(vm.name)
        )


class QubesNoTemplateError(QubesVMError):
    """Cannot start domain, because there is no template"""

    def __init__(self, vm, msg=None):
        super().__init__(
            vm, msg or "Template for the domain {!r} not found".format(vm.name)
        )


class QubesPoolInUseError(QubesException):
    """VM is in use, cannot remove."""

    def __init__(self, pool_name, msg=None):
        super().__init__(
            msg or "Storage pool is in use: {!r}".format(pool_name)
        )


class QubesValueError(ProtocolError, ValueError):
    """Cannot set some value, because it is invalid, out of bounds, etc."""


class QubesPropertyValueError(QubesValueError):
    """
    Cannot set value of qubes.property, because user-supplied value is wrong.
    """

    def __init__(self, holder, prop, value, msg=None):
        super().__init__(
            msg
            or "Invalid value {!r} for property {!r} of {!r}".format(
                value, prop.__name__, holder
            )
        )
        self.holder = holder
        self.prop = prop
        self.value = value


class QubesNoSuchPropertyError(QubesException, AttributeError):
    """Requested property does not exist"""

    def __init__(self, holder, prop_name, msg=None):
        super().__init__(
            msg or "Invalid property {!r} of {!s}".format(prop_name, holder)
        )
        self.holder = holder
        self.prop = prop_name


class QubesNotImplementedError(QubesException, NotImplementedError):
    """Thrown at user when some feature is not implemented"""

    def __init__(self, msg=None):
        super().__init__(msg or "This feature is not available")


class BackupCancelledError(QubesException):
    """Thrown at user when backup was manually cancelled"""

    def __init__(self, msg=None):
        super().__init__(msg or "Backup cancelled")


class BackupAlreadyRunningError(QubesException):
    """Thrown at user when they try to run the same backup twice at
    the same time"""

    def __init__(self, msg=None):
        super().__init__(msg or "Backup already running")


class QubesMemoryError(QubesVMError, MemoryError):
    """Cannot start domain, because not enough memory is available"""

    def __init__(self, vm, msg=None):
        super().__init__(
            vm, msg or "Not enough memory to start domain {!r}".format(vm.name)
        )


class QubesFeatureNotFoundError(QubesException, KeyError):
    """Feature not set for a given domain"""

    def __init__(self, domain, feature):
        super().__init__(
            "Feature not set for domain {}: {}".format(domain, feature)
        )
        self.feature = feature
        self.vm = domain

    def __str__(self):
        # KeyError overrides __str__ method
        return QubesException.__str__(self)


class QubesTagNotFoundError(QubesException, KeyError):
    """Tag not set for a given domain"""

    def __init__(self, domain, tag):
        super().__init__("Tag not set for domain {}: {}".format(domain, tag))
        self.vm = domain
        self.tag = tag

    def __str__(self):
        # KeyError overrides __str__ method
        return QubesException.__str__(self)


class QubesLabelNotFoundError(QubesException, KeyError):
    """Label does not exists"""

    def __init__(self, label):
        super().__init__("Label does not exist: {}".format(label))
        self.label = label

    def __str__(self):
        # KeyError overrides __str__ method
        return QubesException.__str__(self)


class DeviceNotAssigned(QubesException, KeyError):
    """
    Trying to unassign not assigned device.
    """


class DeviceNotFound(QubesException, KeyError):
    """
    Non-existing device.
    """


class DeviceAlreadyAttached(QubesException, KeyError):
    """
    Trying to attach already attached device.
    """


class DeviceAlreadyAssigned(QubesException, KeyError):
    """
    Trying to assign already assigned device.
    """


class UnrecognizedDevice(QubesException, ValueError):
    """
    Device identity is not as expected.
    """


class UnexpectedDeviceProperty(QubesException, ValueError):
    """
    Device has unexpected property such as backend_domain, devclass etc.
    """


class StoragePoolException(QubesException):
    """A general storage exception"""


class QubesVolumeCopyTokenNotFoundError(ProtocolError, KeyError):
    """Domain volume copy did not specify a configured token."""

    def __init__(self, msg=None):
        super().__init__(msg or "Token to clone volume of qube was not found")


class QubesVolumeCopyInUseError(QubesException):
    """Domain volume is already being cloned."""

    def __init__(self, vm, volume, msg=None):
        super().__init__(
            vm,
            msg
            or "Domain volume is being cloned already: {!r}:{!r}".format(
                vm.name, volume
            ),
        )


class QubesVolumeRevisionNotFoundError(KeyError):
    """Specified revision not found in qube volume."""


class QubesPoolNotFoundError(KeyError):
    """Pool does not exist."""


class QubesVolumeNotFoundError(KeyError):
    """Pool does not exist."""


class QubesInvalidLabelError(QubesValueError):
    """Domain label is invalid."""


class QubesLabelInUseError(QubesException):
    """Cannot remove or add label as it is still in use."""

    def __init__(self, label, msg=None):
        super().__init__(
            msg or "Label is still in use: {!r}".format(label),
        )
