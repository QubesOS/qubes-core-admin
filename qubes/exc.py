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


class DestinationNotDom0Error(QubesException):
    def __init__(self, vmname):
        super().__init__(f"Destination must be dom0, not {vmname!r}")
        self.vmname = vmname


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

    def __init__(self, pool, msg=None):
        super().__init__(
            msg or "Storage pool is in use: {!r}".format(pool.name)
        )


class QubesValueError(QubesException, ValueError):
    """Cannot set some value, because it is invalid, out of bounds, etc."""


class QubesArgumentNotAllowedError(QubesValueError):
    """Method does not take an argument."""

    def __init__(self, method_name: str, arg: str):
        super().__init__(
            f"API method {method_name} does not take an argument (got {arg})"
        )
        self.method_name = method_name
        self.arg = arg


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


class ProtocolError(AssertionError):
    """Raised when something is wrong with data received"""


class PermissionDenied(Exception):
    """Raised deliberately by handlers when we decide not to cooperate"""
