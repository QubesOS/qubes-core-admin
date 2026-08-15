#
# The Qubes OS Project, https://www.qubes-os.org/
#
# Copyright (C) 2013-2015  Joanna Rutkowska <joanna@invisiblethingslab.com>
# Copyright (C) 2013-2015  Marek Marczykowski-Górecki
#                              <marmarek@invisiblethingslab.com>
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

"""Qubes storage system"""

import functools
import inspect
import os
import os.path
import string
import subprocess
from datetime import datetime, timezone

import asyncio
from typing import Dict, Tuple, Union

import lxml.etree
import importlib.metadata
import qubes
import qubes.exc
import qubes.utils
from qubes.exc import StoragePoolException

STORAGE_ENTRY_POINT = "qubes.storage"
VOLUME_STATE_DIR = "/var/run/qubes/"
VOLUME_STATE_PREFIX = "volume-running-"
_am_root = os.getuid() == 0

BYTES_TO_ZERO = 1 << 16
_big_buffer = b"\0" * BYTES_TO_ZERO

# LUKS2 header / data-offset reservation used when encrypting an existing
# volume in place.  cryptsetup reencrypt --reduce-device-size takes this
# much from the end of the device so the guest-visible size stays the same
# after the header is written.  32 MiB matches cryptsetup's recommended
# default for LUKS2.
LUKS2_HEADER_SIZE = 32 << 20
LUKS_PASSPHRASE_MAX = 512


def _coerce_passphrase(passphrase):
    """Validate and normalize a LUKS passphrase to ``bytes``."""
    if isinstance(passphrase, str):
        passphrase = passphrase.encode("utf-8")
    elif isinstance(passphrase, bytearray):
        passphrase = bytes(passphrase)
    if not passphrase:
        raise qubes.exc.QubesValueError("Empty passphrase")
    if b"\n" in passphrase:
        raise qubes.exc.QubesValueError(
            "Passphrase must not contain newline character"
        )
    if len(passphrase) > LUKS_PASSPHRASE_MAX:
        raise qubes.exc.QubesValueError(
            "Passphrase longer than {} bytes".format(LUKS_PASSPHRASE_MAX)
        )
    return passphrase


def snapshot_consumers(app, volume):
    """Yield ``(vm, vol)`` for volumes that snapshot *volume*.

    Comparison uses :py:meth:`Volume.__eq__` (pool + vid), not identity.
    """
    domains = getattr(app, "domains", None)
    if not domains:
        return
    for vm in domains:
        volumes = getattr(vm, "volumes", None)
        if not volumes:
            continue
        try:
            others = list(volumes.values())
        except (TypeError, AttributeError):
            continue
        for other in others:
            source = getattr(other, "source", None)
            if source is not None and source == volume:
                yield vm, other


class BlockDevice:
    """Represents a storage block device."""

    # pylint: disable=too-few-public-methods
    def __init__(
        self, path, name, script=None, rw=True, domain=None, devtype="disk"
    ):
        assert name, "Missing device name"
        assert path, "Missing device path"
        assert script is None, "block scripts are obsolete"
        self.path = path
        self.name = name
        self.rw = rw
        self.domain = domain
        self.devtype = devtype


class Volume:
    """Encapsulates all data about a volume for serialization to qubes.xml and
    libvirt config.


    Keep in mind!
    volatile        = not snap_on_start and not save_on_stop
    snapshot        =     snap_on_start and not save_on_stop
    origin          = not snap_on_start and     save_on_stop
    origin_snapshot =     snap_on_start and     save_on_stop
    """

    devtype = "disk"
    domain = None
    path = None
    #: disk space used by this volume, can be smaller than :py:attr:`size`
    #: for sparse volumes
    usage = 0

    def __init__(
        self,
        name,
        pool,
        vid,
        *,
        revisions_to_keep=0,
        rw=False,
        save_on_stop=False,
        size=0,
        snap_on_start=False,
        source=None,
        ephemeral=None,
        encrypted=None,
        **kwargs,
    ):
        """Initialize a volume.

        :param str name: The name of the volume inside owning domain
        :param Pool pool: The pool object
        :param str vid:  Volume identifier needs to be unique in pool
        :param int revisions_to_keep: Amount of revisions to keep around
        :param bool rw: If true volume will be mounted read-write
        :param bool snap_on_start: Create a snapshot from source on
            start, instead of using volume own data
        :param bool save_on_stop: Write changes to the volume in
            vm.stop(), otherwise - discard
        :param Volume source: other volume in same pool to make snapshot
            from, required if *snap_on_start*=`True`
        :param ephemeral: encrypt volume with an ephemeral key
        :param encrypted: encrypt persistent volume with LUKS2
        :param str/int size: Size of the volume

        """

        super().__init__(**kwargs)
        assert isinstance(pool, Pool)
        assert source is None or (
            isinstance(source, Volume) and source.pool == pool
        )

        if snap_on_start and source is None:
            msg = "snap_on_start specified on {!r} but no volume source set"
            msg = msg.format(name)
            raise StoragePoolException(msg)
        if not snap_on_start and source is not None:
            msg = "source specified on {!r} but no snap_on_start set"
            msg = msg.format(name)
            raise StoragePoolException(msg)
        if (
            snap_on_start
            and source is not None
            and getattr(source, "encrypted", False)
        ):
            raise StoragePoolException(
                "Cannot create a snapshot volume from an encrypted source"
            )

        #: Name of the volume in a domain it's attached to (like `root` or
        #: `private`).
        self.name = str(name)
        #: :py:class:`Pool` instance owning this volume
        self.pool = pool
        #: How many revisions of the volume to keep. Each revision is created
        #  at :py:meth:`stop`, if :py:attr:`save_on_stop` is True
        self.revisions_to_keep = int(revisions_to_keep)
        #: Should this volume be writable by domain.
        self.rw = rw
        #: Should volume state be saved or discarded at :py:meth:`stop`
        self.save_on_stop = save_on_stop
        self._size = int(size)
        #: Should the volume be encrypted with an ephemeral key;
        #  None means the default value
        self._ephemeral = ephemeral
        #: Persistent LUKS2 encryption (passphrase kept only in memory)
        self._encrypted = False
        #: In-memory LUKS passphrase; never serialized to XML or disk
        self._passphrase = None
        #: True once setup_luks has started mutating the backing device
        self._luks_device_mutated = False
        #: Should the volume state be initialized with a snapshot of
        #: same-named volume of domain's template.
        self.snap_on_start = snap_on_start
        #: source volume for :py:attr:`snap_on_start` volumes
        self.source = source
        #: Volume unique (inside given pool) identifier
        self.vid = vid
        #: Asynchronous lock for @Volume.locked decorator
        self._lock = asyncio.Lock()
        if encrypted not in (None, False, "False"):
            # Validate through the setter once the other fields are set.
            self.encrypted = True

    def __eq__(self, other):
        if isinstance(other, Volume):
            return other.pool == self.pool and other.vid == self.vid
        return NotImplemented

    def __hash__(self):
        return hash("%s:%s" % (self.pool, self.vid))

    def __neq__(self, other):
        return not self.__eq__(other)

    def __repr__(self):
        return "{!r}".format(str(self.pool) + ":" + self.vid)

    def __str__(self):
        return str(self.vid)

    def __xml__(self):
        config = _sanitize_config(self.config)
        return lxml.etree.Element("volume", **config)

    @property
    def ephemeral(self):
        """Should this volume be encrypted with an ephemeral key in dom0
        (if enabled with encrypted_volatile property)?
        """
        if self._ephemeral is not None:
            return self._ephemeral
        # default value
        if (
            self.snap_on_start
            or self.save_on_stop
            or self.domain is not None
            or not self.rw
        ):
            return False
        return self.pool.ephemeral_volatile

    @ephemeral.setter
    def ephemeral(self, value):
        if not value:
            self._ephemeral = False
            return
        if self.encrypted:
            raise qubes.exc.QubesValueError(
                "Cannot enable ephemeral on encrypted volume"
            )
        if (
            self.snap_on_start
            or self.save_on_stop
            or self.domain is not None
            or not self.rw
        ):
            raise qubes.exc.QubesValueError(
                "Cannot enable ephemeral on snap_on_start or save_on_stop or "
                "non-dom0 or not writable volume"
            )
        self._ephemeral = bool(value)

    @property
    def encrypted(self):
        """Persistent LUKS2 encryption of this volume.

        Allowed only on writable, save_on_stop, non-snapshot, dom0-backed
        volumes (private on AppVM/StandaloneVM, root on TemplateVM /
        StandaloneVM).  Mutually exclusive with :py:attr:`ephemeral`.
        The passphrase is never stored on disk; see
        :py:meth:`set_passphrase`.
        """
        return bool(self._encrypted)

    @encrypted.setter
    def encrypted(self, value):
        if not value:
            if self._encrypted:
                raise qubes.exc.QubesValueError(
                    "Disabling persistent encryption is not implemented"
                )
            self._encrypted = False
            return
        if self.ephemeral:
            raise qubes.exc.QubesValueError(
                "Cannot enable encryption on ephemeral volume"
            )
        if (
            self.snap_on_start
            or not self.save_on_stop
            or self.domain is not None
            or not self.rw
        ):
            raise qubes.exc.QubesValueError(
                "Cannot enable encryption on snap_on_start or "
                "non-save_on_stop or non-dom0 or not writable volume"
            )
        self._encrypted = True

    def is_encryptable(self):
        """True if this volume may have persistent LUKS2 enabled."""
        return (
            not self.snap_on_start
            and bool(self.save_on_stop)
            and self.domain is None
            and bool(self.rw)
            and not self.ephemeral
        )

    def has_passphrase(self):
        """True if an in-memory LUKS passphrase is currently set."""
        return bool(self._passphrase)

    def set_passphrase(self, passphrase):
        """Store a LUKS passphrase in memory only.

        The value is never written to the filesystem or serialized into
        qubes.xml.  An empty passphrase or one containing a newline is
        rejected (newline is reserved as the Admin API separator for
        ``ChangePassphrase``).
        """
        passphrase = _coerce_passphrase(passphrase)
        self.clear_passphrase()
        # bytearray so clear_passphrase() can overwrite the buffer
        self._passphrase = bytearray(passphrase)

    def clear_passphrase(self):
        """Overwrite and drop the in-memory passphrase."""
        if self._passphrase:
            self._passphrase[:] = b"\0" * len(self._passphrase)
        self._passphrase = None

    def _luks_backend_path(self):
        """Path of the LUKS container (the offline origin, not the mapper).

        Drivers that expose a real container (file, LVM) set :py:attr:`path`.
        Others (ZFS) only have a block device; fall back to that.
        """
        if self.path:
            return self.path
        try:
            bdev = self.block_device()
        except Exception:  # pylint: disable=broad-except
            bdev = None
        if bdev is not None and getattr(bdev, "path", None):
            return bdev.path
        raise StoragePoolException(
            "Volume {!s} has no path for LUKS setup".format(self.vid)
        )

    def _volume_has_data(self):
        """Best-effort check whether the volume already contains data.

        Used to decide between ``luksFormat`` (empty) and in-place
        ``reencrypt --encrypt`` (keep existing contents).  A dirty
        volume is *not* treated as encryptable here; see
        :py:meth:`_assert_safe_to_encrypt`.
        """
        if self.usage:
            return True
        path = None
        try:
            path = self._luks_backend_path()
        except StoragePoolException:
            path = self.path
        if path and os.path.exists(path):
            try:
                with open(path, "rb") as fh:
                    chunk = fh.read(4096)
                return bool(chunk) and chunk != b"\x00" * len(chunk)
            except OSError:
                pass
        return False

    def _assert_safe_to_encrypt(self):
        """Refuse in-place encryption when it would leak or lose data."""
        try:
            if self.is_dirty():
                raise StoragePoolException(
                    "Cannot encrypt a dirty volume; shut it down cleanly first"
                )
        except NotImplementedError:
            pass
        try:
            if self.revisions:
                raise StoragePoolException(
                    "Cannot encrypt a volume that has revisions; "
                    "discard revisions first"
                )
        except NotImplementedError:
            pass

    def _discard_unused_cow(self):
        """Remove a clean leftover COW so the next start matches origin size.

        After growing the origin for a LUKS header, an old empty COW at
        the previous size would be reused as-is by the file driver.
        """
        cow = getattr(self, "path_cow", None)
        if not cow or not os.path.exists(cow):
            return
        try:
            if self.is_dirty():
                raise StoragePoolException(
                    "Refusing to discard a dirty COW file for {!s}".format(
                        self.vid
                    )
                )
        except NotImplementedError:
            pass
        os.unlink(cow)

    async def is_luks(self, device=None):
        """Return True if *device* (default: this volume's origin) is LUKS."""
        if device is None:
            try:
                device = self._luks_backend_path()
            except StoragePoolException:
                return False
        if not device or not os.path.exists(device):
            return False
        try:
            await qubes.utils.cryptsetup("--", "isLuks", device)
            return True
        except subprocess.CalledProcessError:
            return False

    async def setup_luks(self, device=None, *, existing=None):
        """Create a LUKS2 header on this volume.

        If the volume already has a LUKS header, this is a no-op.  If it
        already contains data, the volume is grown by
        :py:data:`LUKS2_HEADER_SIZE` and encrypted in place with
        ``cryptsetup reencrypt --encrypt`` so existing contents are kept.
        Otherwise ``luksFormat`` is used.

        Dirty volumes and volumes with revisions are refused.  Once the
        backing device has been mutated, :py:attr:`_luks_device_mutated`
        stays set so callers do not clear the encrypted flag.

        The passphrase must already be set via :py:meth:`set_passphrase`.
        It is passed to cryptsetup on stdin and is not written to disk.
        """
        if not self.has_passphrase():
            raise StoragePoolException(
                "Passphrase required to set up LUKS on volume {!s}".format(
                    self.vid
                )
            )
        if device is None:
            device = self._luks_backend_path()
        if not device or not os.path.exists(device):
            raise StoragePoolException(
                "Cannot set up LUKS: device {!r} does not exist".format(device)
            )
        if await self.is_luks(device):
            return
        self._assert_safe_to_encrypt()
        if existing is None:
            existing = self._volume_has_data()
        if existing:
            await self._encrypt_existing(device)
        else:
            await self._luks_format(device)

    async def _luks_format(self, device):
        self._luks_device_mutated = True
        self._encrypted = True
        await qubes.utils.cryptsetup(
            "--batch-mode",
            "--type=luks2",
            "--cipher=aes-xts-plain64",
            "--key-file=-",
            "--",
            "luksFormat",
            device,
            passphrase=self._passphrase,
        )

    async def _encrypt_existing(self, device):
        """Encrypt an existing volume in place, preserving its data.

        The backing store is grown first so that after
        ``--reduce-device-size`` the guest-visible size is unchanged.
        """
        # Mark *before* resize/reencrypt so a mid-flight failure cannot
        # be mistaken for "not encrypted" (which would attach ciphertext
        # as a normal disk).
        self._luks_device_mutated = True
        self._encrypted = True
        await qubes.utils.coro_maybe(self.resize(self.size + LUKS2_HEADER_SIZE))
        device = self.path or device
        await qubes.utils.cryptsetup(
            "--batch-mode",
            "--type=luks2",
            "--encrypt",
            "--reduce-device-size=32M",
            "--key-file=-",
            "--",
            "reencrypt",
            device,
            passphrase=self._passphrase,
        )
        self._discard_unused_cow()

    async def start_luks(self, name):
        """Unlock a persistent LUKS2 volume and start the backing volume.

        The mapper *name* is the path returned by
        :py:meth:`encrypted_volume_path`.  The in-memory passphrase is
        wiped after a successful open.  This method never formats the
        origin; a missing LUKS header is an error.
        """
        assert name.startswith("/dev/mapper/"), (
            "Invalid path %r passed to cryptsetup" % name
        )
        mapper_name = name[12:]
        assert "/" not in mapper_name, "Invalid name passed to cryptsetup"
        if not self.has_passphrase():
            raise StoragePoolException(
                "Passphrase required to unlock encrypted volume {!s}".format(
                    self.vid
                )
            )
        if os.path.exists(name):
            await qubes.utils.cryptsetup("--", "close", mapper_name)
        origin = self._luks_backend_path()
        if not await self.is_luks(origin):
            raise StoragePoolException(
                "Encrypted volume {!s} is not LUKS formatted".format(self.vid)
            )
        started = False
        try:
            await qubes.utils.coro_maybe(self.start())
            started = True
            backend = self.block_device().path
            try:
                await qubes.utils.cryptsetup(
                    "--type=luks2",
                    "--key-file=-",
                    "--",
                    "open",
                    backend,
                    mapper_name,
                    passphrase=self._passphrase,
                )
            except subprocess.CalledProcessError as exc:
                raise StoragePoolException(
                    "Failed to unlock encrypted volume {!s}".format(self.vid)
                ) from exc
            # Apply any offline backing-store grow to the LUKS payload.
            try:
                await qubes.utils.cryptsetup("--", "resize", mapper_name)
            except subprocess.CalledProcessError as exc:
                raise StoragePoolException(
                    "Failed to resize unlocked volume {!s}".format(self.vid)
                ) from exc
            self.clear_passphrase()
        except Exception:
            if started:
                if os.path.exists(name):
                    try:
                        await qubes.utils.cryptsetup("--", "close", mapper_name)
                    except Exception:  # pylint: disable=broad-except
                        pass
                try:
                    await qubes.utils.coro_maybe(self.stop())
                except Exception:  # pylint: disable=broad-except
                    pass
            raise

    async def stop_luks(self, name):
        """Close the LUKS mapping and stop the backing volume."""
        assert name.startswith("/dev/mapper/"), (
            "invalid encrypted volume path %r" % name
        )
        if os.path.exists(name):
            await qubes.utils.cryptsetup("--", "close", name[12:])
        await qubes.utils.coro_maybe(self.stop())

    async def change_passphrase(self, old, new):
        """Replace the LUKS passphrase.  Neither value is written to disk."""
        device = self._luks_backend_path()
        if not await self.is_luks(device):
            raise StoragePoolException(
                "Volume {!s} is not LUKS formatted".format(self.vid)
            )
        # Validate the new passphrase first (also rejects newline / empty)
        # without replacing the current one until cryptsetup succeeds.
        new_bytes = _coerce_passphrase(new)
        try:
            await qubes.utils.cryptsetup_change_key(device, old, new_bytes)
        except subprocess.CalledProcessError as exc:
            raise StoragePoolException(
                "Failed to change passphrase on volume {!s}".format(self.vid)
            ) from exc
        self.set_passphrase(new_bytes)

    async def start_encrypted(self, name):
        """
        Start a volume encrypted with an ephemeral key.
        This can be implemented as a coroutine.

        The default implementation of this method uses ``cryptsetup(8)`` with a
        key taken from ``/dev/urandom``.  This is highly secure and works with
        any storage pool implementation.  Volume implementations should override
        this method if they can provide a secure and more efficient
        implementation.
        """
        assert name.startswith("/dev/mapper/"), (
            "Invalid path %r passed to cryptsetup" % name
        )
        must_stop = os.path.exists(name)
        path = name
        name = name[12:]
        assert "/" not in name, "Invalid name passed to cryptsetup"
        if must_stop:
            await qubes.utils.cryptsetup("--", "close", name)
        await qubes.utils.coro_maybe(self.start())
        await qubes.utils.cryptsetup(
            "--key-file=/dev/urandom",
            "--cipher=aes-xts-plain64",
            "--type=plain",
            "--",
            "open",
            self.block_device().path,
            name,
        )
        if _am_root:
            with open(path, "wb+") as clearer:
                clearer.write(_big_buffer)
        else:
            await qubes.utils.run_program(
                "dd",
                "if=/dev/zero",
                "of=" + path,
                "count=1",
                "bs=" + str(BYTES_TO_ZERO),
                sudo=True,
            )

    async def stop_encrypted(self, name):
        """
        Stop an encrypted, ephemeral volume.
        This can be implemented as a coroutine.

        The default implementation of this method uses ``cryptsetup(8)``.
        Volume implementations that override :py:meth:`start_encrypted` MUST
        override this method as well.
        """
        assert name.startswith("/dev/mapper/"), (
            "invalid encrypted volume path %r" % name
        )
        if os.path.exists(name):
            await qubes.utils.cryptsetup("--", "close", name)
        await qubes.utils.coro_maybe(self.stop())

    @staticmethod
    def locked(method):
        """Decorator running given Volume's coroutine under a lock."""

        @functools.wraps(method)
        async def wrapper(self, *args, **kwargs):
            async with self._lock:  # pylint: disable=protected-access
                return await method(self, *args, **kwargs)

        return wrapper

    async def create(self):
        """Create the given volume on disk.

        This method is called only once in the volume lifetime. Before
        calling this method, no data on disk should be touched (in
        context of this volume).

        This can be implemented as a coroutine.
        """
        raise self._not_implemented("create")

    async def remove(self):
        """Remove volume.

        This can be implemented as a coroutine."""
        raise self._not_implemented("remove")

    async def export(self):
        """Returns a path to read the volume data from.

        Reading from this path when domain owning this volume is
        running (i.e. when :py:meth:`is_dirty` is True) should return the
        data from before domain startup.

        Reading from the path returned by this method should return the
        volume data. If extracting volume data require something more
        than just reading from file (for example connecting to some other
        domain, or decompressing the data), the returned path may be a pipe.

        This can be implemented as a coroutine.

        """
        raise self._not_implemented("export")

    async def export_end(self, path):
        """Cleanup after exporting data.

        This method is called after exporting the volume data (using
        :py:meth:`export`), when the *path* is not needed anymore.

        This can be implemented as a coroutine.

        :param path: path to cleanup, returned by :py:meth:`export`
        """
        # do nothing by default (optional method)

    async def import_data(self, size):
        """Returns a path to overwrite volume data.

        This method is called after volume was already :py:meth:`create`-ed.

        Writing to this path should overwrite volume data. If importing
        volume data require something more than just writing to a file (
        for example connecting to some other domain, or converting data
        on the fly), the returned path may be a pipe.

        This can be implemented as a coroutine.

        :param int size: size of new data in bytes
        """
        raise self._not_implemented("import_data")

    async def import_data_end(self, success):
        """End the data import operation. This may be used by pool
        implementation to commit changes, cleanup temporary files etc.

        This method is called regardless the operation was successful or not.

        This can be implemented as a coroutine.

        :param success: True if data import was successful, otherwise False
        """
        # by default do nothing

    async def import_volume(self, src_volume):
        """Imports data from a different volume (possibly in a different
        pool.

        The volume needs to be create()d first.

        This can be implemented as a coroutine."""
        # pylint: disable=unused-argument
        raise self._not_implemented("import_volume")

    def is_dirty(self):
        """Return `True` if volume was not properly shutdown and committed.

        This include the situation when domain owning the volume is still
        running.

        """
        raise self._not_implemented("is_dirty")

    def is_outdated(self):
        """Returns `True` if this snapshot of a source volume (for
        `snap_on_start` = True) is outdated.
        """
        raise self._not_implemented("is_outdated")

    async def resize(self, size):
        """Expands volume, throws
        :py:class:`qubes.storage.StoragePoolException` if
        given size is less than current_size

        This can be implemented as a coroutine.

        :param int size: new size in bytes
        """
        # pylint: disable=unused-argument
        raise self._not_implemented("resize")

    async def revert(self, revision=None):
        """Revert volume to previous revision

        This can be implemented as a coroutine.

        :param revision: revision to revert volume to, see :py:attr:`revisions`
        """
        # pylint: disable=unused-argument
        raise self._not_implemented("revert")

    async def start(self):
        """Do what ever is needed on start.

        This include making a snapshot of template's volume if
        :py:attr:`snap_on_start` is set.

        This can be implemented as a coroutine."""
        raise self._not_implemented("start")

    async def stop(self):
        """Do what ever is needed on stop.

        This include committing data if :py:attr:`save_on_stop` is set.

        This can be implemented as a coroutine."""
        raise self._not_implemented("stop")

    async def verify(self):
        """Verifies the volume.

        This function is supposed to either return :py:obj:`True`, or raise
        an exception.

        This can be implemented as a coroutine."""
        raise self._not_implemented("verify")

    def block_device(self):
        """Return :py:class:`BlockDevice` for serialization in
        the libvirt XML template as <disk>.
        """
        return BlockDevice(
            self.path, self.name, None, self.rw, self.domain, self.devtype
        )

    @property
    def revisions(self):
        """Returns a dict containing revision identifiers and time of their
        creation"""
        msg = "{!s} has revisions not implemented".format(self.__class__)
        raise NotImplementedError(msg)

    @property
    def size(self):
        """Volume size in bytes"""
        return self._size

    def encrypted_volume_path(self, qube_name, device_name):
        """Find the name of the encrypted volatile volume"""
        # We need to ensure we don’t collide with any name used by LVM or LUKS,
        # and that different qubes have different encrypted volume names.
        # LUKS volumes have a name starting with ‘luks-’ followed by a UUID.
        # LVM volumes always have at most one dash that is not doubled.
        # And there is a one-to-one relationship between escaped and original
        # names: replace ‘_d’ with ‘-’, then replace ‘_u’ with ‘_’.
        # So we are in the clear here.
        escaped_qube_name = qube_name.replace("_", "_u").replace("-", "_d")
        return (
            "/dev/mapper/vm-volatile-"
            + escaped_qube_name
            + "-crypt@"
            + device_name
        )

    def make_encrypted_device(self, device, qube_name):
        """Takes :py:class:`BlockDevice` and returns its encrypted version for
        serialization in the libvirt XML template as <disk>.  The qube name
        is available to help construct the device path.
        """
        assert device.domain is None, "Volatile volume must be in dom0"
        assert device.devtype == "disk"
        assert device.rw, "Encrypting read-only volumes makes no sense"
        path = self.encrypted_volume_path(qube_name, device.name)
        return qubes.storage.BlockDevice(
            path=path,
            name=device.name,
            rw=device.rw,
            domain=None,
            devtype="disk",
        )

    @property
    def config(self):
        """return config data for serialization to qubes.xml"""
        result = {
            "name": self.name,
            "pool": str(self.pool),
            "vid": self.vid,
            "revisions_to_keep": self.revisions_to_keep,
            "rw": self.rw,
            "save_on_stop": self.save_on_stop,
            "snap_on_start": self.snap_on_start,
        }

        if self._ephemeral is not None:
            result["ephemeral"] = self.ephemeral

        if self._encrypted:
            result["encrypted"] = True

        if self.size:
            result["size"] = self.size

        if self.source:
            result["source"] = str(self.source)

        return result

    def _not_implemented(self, method_name):
        """Helper for emitting helpful `NotImplementedError` exceptions"""
        msg = "Volume {!s} has {!s}() not implemented"
        msg = msg.format(str(self.__class__.__name__), method_name)
        return NotImplementedError(msg)

    @property
    def snapshots_disabled(self) -> bool:
        return (
            self.revisions_to_keep == -1
            and not self.snap_on_start
            and self.save_on_stop
        )

    @property
    def state_file(self) -> str:
        return os.path.join(
            VOLUME_STATE_DIR,
            VOLUME_STATE_PREFIX
            + f"{self.pool.name}:{self.vid}".replace("-", "--").replace(
                "/", "-"
            ),
        )

    def is_running(self) -> bool:
        return os.path.exists(self.state_file)


class Storage:
    """Class for handling VM virtual disks.

    This is base class for all other implementations, mostly with Xen on Linux
    in mind.
    """

    # all frontends, prefer xvdi
    # TODO: get this from libvirt driver?
    AVAILABLE_FRONTENDS = ["xvd" + c for c in string.ascii_lowercase[8:]]
    AVAILABLE_FRONTENDS += [
        "xvd" + c + d
        for c in string.ascii_lowercase
        for d in string.ascii_lowercase
    ]
    # xvda - xvdh are reserved by Qubes OS and sometimes hidden from tools,
    # so we put them to the end of the list
    AVAILABLE_FRONTENDS += ["xvd" + c for c in string.ascii_lowercase[:8]]

    def __init__(self, vm):
        #: Domain for which we manage storage
        self.vm = vm
        self.log = self.vm.log
        #: Additional drive (currently used only by HVM)
        self.drive = None

        if hasattr(vm, "volume_config"):
            for name, conf in self.vm.volume_config.items():
                self.init_volume(name, conf)

    def _update_volume_config_source(self, name, volume_config):
        """Retrieve 'source' volume from VM's template"""
        template = getattr(self.vm, "template", None)
        # recursively lookup source volume - templates may be
        # chained (TemplateVM -> AppVM -> DispVM, where the
        # actual source should be used from TemplateVM)
        while template:
            source = template.volumes[name]
            volume_config["source"] = source
            volume_config["pool"] = source.pool
            volume_config["size"] = source.size
            if source.source is not None:
                template = getattr(template, "template", None)
            else:
                break

    def init_volume(self, name, volume_config):
        """Initialize Volume instance attached to this domain"""

        if "name" not in volume_config:
            volume_config["name"] = name

        if "source" in volume_config:
            # we have no control over VM load order,
            # so initialize storage recursively if needed
            template = getattr(self.vm, "template", None)
            if template and template.storage is None:
                template.storage = Storage(template)

            if volume_config["source"] is None:
                self._update_volume_config_source(name, volume_config)
            else:
                # if source is already specified, pool needs to be too
                pool = self.vm.app.get_pool(volume_config["pool"])
                volume_config["source"] = pool.volumes[volume_config["source"]]

        # if pool still unknown, load default
        if "pool" not in volume_config:
            volume_config["pool"] = getattr(self.vm.app, "default_pool_" + name)
        pool = self.vm.app.get_pool(volume_config["pool"])
        if "internal" in volume_config:
            # migrate old config
            del volume_config["internal"]
        volume = pool.init_volume(self.vm, volume_config.copy())
        self.vm.volumes[name] = volume
        return volume

    def get_volume(self, volume_or_name):
        if isinstance(volume_or_name, Volume):
            return volume_or_name
        if isinstance(volume_or_name, str):
            return self.vm.volumes[volume_or_name]
        raise TypeError("You need to pass a Volume object or name")

    def attach(self, volume, rw=False):
        """Attach a volume to the domain"""
        assert self.vm.is_running()

        if self._is_already_attached(volume):
            self.vm.log.info("{!r} already attached".format(volume))
            return

        try:
            frontend = self.unused_frontend()
        except IndexError:
            raise StoragePoolException("No unused frontend found")
        disk = lxml.etree.Element("disk")
        disk.set("type", "block")
        disk.set("device", "disk")
        lxml.etree.SubElement(disk, "driver").set("name", "phy")
        lxml.etree.SubElement(disk, "source").set("dev", "/dev/%s" % volume.vid)
        lxml.etree.SubElement(disk, "target").set("dev", frontend)
        if not rw:
            lxml.etree.SubElement(disk, "readonly")

        if volume.domain is not None:
            lxml.etree.SubElement(disk, "backenddomain").set(
                "name", volume.domain.name
            )

        xml_string = lxml.etree.tostring(disk, encoding="utf-8")
        self.vm.libvirt_domain.attachDevice(xml_string)
        # trigger watches to update device status
        # FIXME: this should be removed once libvirt will report such
        # events itself
        # self.vm.untrusted_qdb.write('/qubes-block-devices', '')
        # ← do we need this?

    def _is_already_attached(self, volume):
        """Checks if the given volume is already attached"""
        parsed_xml = lxml.etree.fromstring(self.vm.libvirt_domain.XMLDesc())
        disk_sources = parsed_xml.xpath("//domain/devices/disk/source")
        for source in disk_sources:
            if source.get("dev") == "/dev/%s" % volume.vid:
                return True
        return False

    def detach(self, volume):
        """Detach a volume from domain"""
        parsed_xml = lxml.etree.fromstring(self.vm.libvirt_domain.XMLDesc())
        disks = parsed_xml.xpath("//domain/devices/disk")
        for disk in disks:
            source = disk.xpath("source")[0]
            if source.get("dev") == "/dev/%s" % volume.vid:
                disk_xml = lxml.etree.tostring(disk, encoding="utf-8")
                self.vm.libvirt_domain.detachDevice(disk_xml)
                return
        raise StoragePoolException("Volume {!r} is not attached".format(volume))

    @property
    def kernels_dir(self):
        """Directory where kernel resides.

        If :py:attr:`self.vm.kernel` is :py:obj:`None`, the this points inside
        :py:attr:`self.vm.dir_path`
        """
        if not self.vm.kernel:
            return None
        if "kernel" in self.vm.volumes:
            return self.vm.volumes["kernel"].kernels_dir
        return os.path.join(
            qubes.config.qubes_base_dir,
            qubes.config.system_path["qubes_kernels_base_dir"],
            self.vm.kernel,
        )

    def get_disk_utilization(self):
        """Returns summed up disk utilization for all domain volumes"""
        result = 0
        for volume in self.vm.volumes.values():
            result += volume.usage
        return result

    async def resize(self, volume, size):
        """Resizes volume a read-writable volume"""
        volume = self.get_volume(volume)
        await qubes.utils.coro_maybe(volume.resize(size))
        if volume.encrypted:
            mapper = volume.encrypted_volume_path(self.vm.name, volume.name)
            if os.path.exists(mapper):
                await qubes.utils.cryptsetup("--", "resize", mapper[12:])
        if self.vm.is_running():
            try:
                await self.vm.run_service_for_stdio(
                    "qubes.ResizeDisk", input=volume.name.encode(), user="root"
                )
            except subprocess.CalledProcessError as e:
                service_error = e.stderr.decode("ascii", errors="ignore")
                service_error = service_error.replace("%", "")
                raise StoragePoolException(
                    "Online resize of volume {} failed (you need to resize "
                    "filesystem manually): {}".format(volume, service_error)
                )

    async def create(self):
        """Creates volumes on disk"""
        encrypted = [vol for vol in self.vm.volumes.values() if vol.encrypted]
        missing = [vol.name for vol in encrypted if not vol.has_passphrase()]
        if missing:
            raise StoragePoolException(
                "Passphrase required to set up encrypted volume(s): "
                + ", ".join(missing)
            )
        await qubes.utils.void_coros_maybe(
            vol.create() for vol in self.vm.volumes.values()
        )
        await qubes.utils.void_coros_maybe(
            vol.setup_luks() for vol in encrypted
        )

    async def clone_volume(self, src_vm, name):
        """Clone single volume from the specified vm

        :param QubesVM src_vm: source VM
        :param str name: name of volume to clone ('root', 'private' etc)
        :return: cloned volume object
        """
        config = dict(self.vm.volume_config[name])
        src_volume = src_vm.volumes[name]
        # Clone copies the LUKS container raw; carry the encrypted flag
        # so the destination is unlocked the same way.  Same passphrase.
        if src_volume.encrypted:
            config["encrypted"] = True
        dst_pool = self.vm.app.get_pool(config["pool"])
        dst = dst_pool.init_volume(self.vm, config)
        msg = "Importing volume {!s} from vm {!s}"
        self.vm.log.info(msg.format(src_volume.name, src_vm.name))
        await qubes.utils.coro_maybe(dst.create())
        await qubes.utils.coro_maybe(dst.import_volume(src_volume))
        self.vm.volumes[name] = dst
        return self.vm.volumes[name]

    async def clone(self, src_vm):
        """Clone volumes from the specified vm"""

        self.vm.volumes = {}
        with VmCreationManager(self.vm):
            await qubes.utils.void_coros_maybe(
                self.clone_volume(src_vm, vol_name)
                for vol_name in self.vm.volume_config.keys()
            )

    @property
    def outdated_volumes(self):
        """Returns a list of outdated volumes"""
        if self.vm.is_halted():
            return []
        return [vol for vol in self.vm.volumes.values() if vol.is_outdated()]

    async def verify(self):
        """Verify that the storage is sane.

        On success, returns normally. On failure, raises exception.
        """
        if not os.path.exists(self.vm.dir_path):
            raise qubes.exc.QubesVMError(
                self.vm,
                "VM directory does not exist: {}".format(self.vm.dir_path),
            )
        await qubes.utils.void_coros_maybe(
            vol.verify() for vol in self.vm.volumes.values()
        )
        self.vm.fire_event("domain-verify-files")
        return True

    async def remove(self):
        """Remove all the volumes.

        Errors on removal are catched and logged.
        """
        results = []
        try:
            await self.stop()
        except (IOError, OSError, subprocess.SubprocessError):
            self.vm.log.exception(
                "Failed to stop some volume, continuing anyway"
            )
        for vol in self.vm.volumes.values():
            self.log.info("Removing volume %s: %s" % (vol.name, vol.vid))
            try:
                results.append(vol.remove())
            except (IOError, OSError):
                self.vm.log.exception("Failed to remove volume %s", vol.name)
        try:
            await qubes.utils.void_coros_maybe(results)
        except (IOError, OSError):
            self.vm.log.exception("Failed to remove some volume")

    def block_devices(self):
        """Return all :py:class:`qubes.storage.BlockDevice` for current domain
        for serialization in the libvirt XML template as <disk>.
        """
        for v in self.vm.volumes.values():
            block_dev = v.block_device()
            if block_dev is not None:
                if v.ephemeral or v.encrypted is True:
                    yield v.make_encrypted_device(block_dev, self.vm.name)
                else:
                    yield block_dev

    def set_revisions_to_keep(self, volume, value):
        if value < -1:
            raise qubes.exc.QubesValueError(
                "Invalid value for revisions_to_keep"
            )

        currentvalue = self.vm.volumes[volume].revisions_to_keep
        enabling_disabling_snapshots = value != currentvalue and (
            currentvalue == -1 or value == -1
        )
        if self.vm.is_running() and enabling_disabling_snapshots:
            raise qubes.exc.QubesVMNotHaltedError(self.vm)

        if self.vm.klass == "AppVM" and enabling_disabling_snapshots:
            for vm in self.vm.dispvms:
                if vm.is_running():
                    raise qubes.exc.QubesVMNotHaltedError(vm)

        self.vm.volumes[volume].revisions_to_keep = value

    def _volume_start_stop(self, name, vol, *, start):
        """Pick start/stop / start_luks/stop_luks / start_encrypted/..."""
        mapper = vol.encrypted_volume_path(self.vm.name, name)
        if vol.encrypted:
            return vol.start_luks(mapper) if start else vol.stop_luks(mapper)
        if start:
            return vol.start_encrypted(mapper) if vol.ephemeral else vol.start()
        # Always call stop_encrypted() - which can handle an unencrypted
        # volume as well - to correctly clean up even if the ephemeral
        # property became False while the volume was already started.
        return vol.stop_encrypted(mapper)

    async def _ensure_passphrases(self):
        """Ask for missing LUKS passphrases, then fail if still unset."""
        missing = [
            name
            for name, vol in self.vm.volumes.items()
            if vol.encrypted and not vol.has_passphrase()
        ]
        if not missing:
            return
        fire = getattr(self.vm, "fire_event_async", None)
        if fire is not None:
            await fire("domain-passphrase-required", volumes=missing)
        missing = [
            name
            for name, vol in self.vm.volumes.items()
            if vol.encrypted and not vol.has_passphrase()
        ]
        if missing:
            raise StoragePoolException(
                "Passphrase required for encrypted volume(s): "
                + ", ".join(missing)
            )

    async def start(self):
        """Execute the start method on each volume"""
        for vol in self.vm.volumes.values():
            if (
                vol.source
                and vol.source.snapshots_disabled
                and vol.source.is_running()
            ):
                raise qubes.exc.QubesVMError(
                    self.vm, f"Volume {vol.source.vid} is running"
                )
        await self._ensure_passphrases()
        await qubes.utils.void_coros_maybe(
            self._volume_start_stop(name, vol, start=True)
            for name, vol in self.vm.volumes.items()
        )

        for vol in self.vm.volumes.values():
            with open(vol.state_file, "w", encoding="ascii"):
                pass

    async def stop(self):
        """Stop each volume"""
        await qubes.utils.void_coros_maybe(
            self._volume_start_stop(name, vol, start=False)
            for name, vol in self.vm.volumes.items()
        )
        for vol in self.vm.volumes.values():
            qubes.utils.remove_file(vol.state_file)

    def unused_frontend(self):
        """Find an unused device name"""
        unused_frontends = self.AVAILABLE_FRONTENDS.difference(
            self.used_frontends
        )
        return sorted(unused_frontends)[0]

    @property
    def used_frontends(self):
        """Used device names"""
        xml = self.vm.libvirt_domain.XMLDesc()
        parsed_xml = lxml.etree.fromstring(xml)
        return {
            target.get("dev", None)
            for target in parsed_xml.xpath("//domain/devices/disk/target")
        }

    async def export(self, volume):
        """Helper function to export volume"""
        return await qubes.utils.coro_maybe(self.get_volume(volume).export())

    async def export_end(self, volume, export_path):
        """Cleanup after exporting data from the volume

        :param volume: volume that was exported
        :param export_path: path returned by the export() call
        """
        await qubes.utils.coro_maybe(
            self.get_volume(volume).export_end(export_path)
        )

    async def import_data(self, volume, size):
        """
        Helper function to import volume data.

        :size: new size in bytes, or None if using old size
        """

        volume = self.get_volume(volume)
        if size is None:
            size = volume.size
        return await qubes.utils.coro_maybe(volume.import_data(size))

    async def import_data_end(self, volume, success):
        """Helper function to finish/cleanup data import"""
        volume = self.get_volume(volume)
        result = await qubes.utils.coro_maybe(
            volume.import_data_end(success=success)
        )
        # Import/Clear overwrite the origin.  Re-apply LUKS if this is an
        # encrypted volume (no-op when the imported image is already LUKS).
        if success and volume.encrypted:
            if not volume.has_passphrase():
                raise StoragePoolException(
                    "Passphrase required to re-format encrypted volume "
                    "{!s} after import".format(volume.vid)
                )
            await volume.setup_luks()
        return result

    async def import_volume(self, dst_volume: Volume, src_volume: Volume):
        """Helper function to import data from another volume"""
        if src_volume.is_running() and src_volume.snapshots_disabled:
            raise StoragePoolException(
                f"Volume {src_volume.vid} must be stopped before importing its "
                f"data"
            )

        if src_volume.encrypted and not dst_volume.encrypted:
            # Must mark dest *before* copying so a LUKS container is
            # never attached as a plaintext disk.  The setter enforces
            # save_on_stop / rw / not snap_on_start.
            dst_volume.encrypted = True
        elif dst_volume.encrypted and not src_volume.encrypted:
            raise StoragePoolException(
                "Cannot import unencrypted volume {!s} into encrypted "
                "volume {!s}".format(src_volume.vid, dst_volume.vid)
            )

        import_rslt = await qubes.utils.coro_maybe(
            dst_volume.import_volume(src_volume)
        )
        await self.vm.fire_event_async(
            "domain-import-volume", name=dst_volume.name, source=src_volume
        )
        return import_rslt


class VolumesCollection:
    """Convenient collection wrapper for pool.get_volume and
    pool.list_volumes
    """

    def __init__(self, pool):
        self._pool = pool

    def __getitem__(self, item):
        """Get a single volume with given Volume ID.

        You can also a Volume instance to get the same Volume or KeyError if
        Volume no longer exists.

        :param item: a Volume ID (str) or a Volume instance
        """
        if isinstance(item, Volume):
            if item.pool == self._pool:
                return self[item.vid]
            raise KeyError(item)
        try:
            return self._pool.get_volume(item)
        except NotImplementedError:
            for vol in self:
                if vol.vid == item:
                    return vol
            # if list_volumes is not implemented too, it will raise
            # NotImplementedError again earlier
            raise KeyError(item)

    def __iter__(self):
        """Get iterator over pool's volumes"""
        return iter(self._pool.list_volumes())

    def __contains__(self, item):
        """Check if given volume (either Volume ID or Volume instance) is
        present in the pool
        """
        try:
            return self[item] is not None
        except KeyError:
            return False

    def keys(self):
        """Return list of volume IDs"""
        return [vol.vid for vol in self]

    def values(self):
        """Return list of Volumes"""
        return list(self)


class Pool:
    """A Pool is used to manage different kind of volumes (File
    based/LVM/Btrfs/...).

    3rd Parties providing own storage implementations will need to extend
    this class.
    """  # pylint: disable=unused-argument

    private_img_size = qubes.config.defaults["private_img_size"]
    root_img_size = qubes.config.defaults["root_img_size"]

    def __init__(self, *, name, revisions_to_keep=1, ephemeral_volatile=False):
        self._volumes_collection = VolumesCollection(self)
        self.name = name
        self.revisions_to_keep = revisions_to_keep
        self.ephemeral_volatile = qubes.utils.parse_bool(ephemeral_volatile)

    def __eq__(self, other):
        if isinstance(other, Pool):
            return self.name == other.name
        if isinstance(other, str):
            return self.name == other
        return NotImplemented

    def __neq__(self, other):
        return not self.__eq__(other)

    def __str__(self):
        return self.name

    def __hash__(self):
        return hash(self.name)

    def __xml__(self):
        config = _sanitize_config(self.config)
        return lxml.etree.Element("pool", **config)

    @property
    def config(self):
        """Returns the pool config to be written to qubes.xml"""
        raise self._not_implemented("config")

    async def destroy(self):
        """Called when removing the pool. Use this for implementation specific
        clean up.

        This can be implemented as a coroutine.
        """
        raise self._not_implemented("destroy")

    def init_volume(self, vm, volume_config):
        """
        Initialize a :py:class:`qubes.storage.Volume` from `volume_config`.
        """
        raise self._not_implemented("init_volume")

    async def setup(self):
        """Called when adding a pool to the system. Use this for implementation
        specific set up.

        This can be implemented as a coroutine.
        """
        raise self._not_implemented("setup")

    @property
    def volumes(self):
        """Return a collection of volumes managed by this pool"""
        return self._volumes_collection

    def list_volumes(self):
        """Return a list of volumes managed by this pool"""
        raise self._not_implemented("list_volumes")

    def get_volume(self, vid):
        """Return a volume with *vid* from this pool

        :raise KeyError: if no volume is found
        """
        raise self._not_implemented("get_volume")

    def included_in(self, app):
        """Check if this pool is physically included in another one

        This works on best-effort basis, because one pool driver may not know
        all the other drivers.

        :param app: Qubes() object to lookup other pools in
        :return: pool or None
        """

    @property
    def size(self):
        """Storage pool size in bytes, or None if unknown"""
        return

    @property
    def usage(self):
        """Space used in the pool in bytes, or None if unknown"""
        return

    @property
    def usage_details(self):
        """Detailed information about pool usage as a dictionary
        Contains data_usage for usage in bytes and data_size for pool
        size; other implementations may add more implementation-specific
        detail"""
        result = {}
        if self.usage is not None:
            result["data_usage"] = self.usage
        if self.size is not None:
            result["data_size"] = self.size

        return result

    def _not_implemented(self, method_name):
        """Helper for emitting helpful `NotImplementedError` exceptions"""
        msg = "Pool driver {!s} has {!s}() not implemented"
        msg = msg.format(str(self.__class__.__name__), method_name)
        return NotImplementedError(msg)


def _sanitize_config(config):
    """Helper function to convert types to appropriate strings"""
    # FIXME: find another solution for serializing basic types
    result = {}
    for key, value in config.items():
        if isinstance(value, bool):
            if value:
                result[key] = "True"
            else:
                result[key] = "False"
        else:
            result[key] = str(value)
    return result


def pool_drivers():
    """Return a list of EntryPoints names"""
    return [
        ep.name
        for ep in importlib.metadata.entry_points(group=STORAGE_ENTRY_POINT)
    ]


def driver_parameters(name):
    """Get __init__ parameters from a driver with out `self` & `name`."""
    init_function = qubes.utils.get_entry_point_one(
        qubes.storage.STORAGE_ENTRY_POINT, name
    ).__init__
    signature = inspect.signature(init_function)
    params = signature.parameters
    ignored_params = ["self", "name", "kwargs"]
    return {
        p.name: p.default is inspect.Parameter.empty
        for p in params.values()
        if p.name not in ignored_params
    }


def isodate(seconds):
    """Helper method which returns an iso date"""
    return (
        datetime.fromtimestamp(seconds, tz=timezone.utc)
        .isoformat()
        .replace("+00:00", "")
    )


def search_pool_containing_dir(pools, dir_path):
    """Helper function looking for a pool containing given directory.

    This is useful for implementing Pool.included_in method
    """

    real_dir_path = os.path.realpath(dir_path)

    # prefer filesystem pools
    for pool in pools:
        if hasattr(pool, "dir_path"):
            pool_real_dir_path = os.path.realpath(pool.dir_path)
            if (
                os.path.commonpath([pool_real_dir_path, real_dir_path])
                == pool_real_dir_path
            ):
                return pool

    # then look for lvm
    for pool in pools:
        if hasattr(pool, "thin_pool") and hasattr(pool, "volume_group"):
            if (
                pool.volume_group,
                pool.thin_pool,
            ) == DirectoryThinPool.thin_pool(real_dir_path):
                return pool

    return None


class VmCreationManager:
    """A `ContextManager` which cleans up if volume creation fails."""

    # pylint: disable=too-few-public-methods

    def __init__(self, vm):
        self.vm = vm

    def __enter__(self):
        pass

    def __exit__(self, type, value, tb):  # pylint: disable=redefined-builtin
        if type is not None and value is not None and tb is not None:
            for volume in self.vm.volumes.values():
                try:
                    volume.remove()
                except Exception:  # pylint: disable=broad-except
                    pass
            os.rmdir(self.vm.dir_path)


# pylint: disable=too-few-public-methods
class DirectoryThinPool:
    """The thin pool containing the device of given filesystem"""

    _thin_pool: Dict[str, Tuple[Union[str, None], Union[str, None]]] = {}

    @classmethod
    def _init(cls, dir_path):
        """Find out the thin pool containing given filesystem"""
        if dir_path not in cls._thin_pool:
            cls._thin_pool[dir_path] = None, None

            try:
                fs_stat = os.stat(dir_path)
                fs_major = (fs_stat.st_dev & 0xFF00) >> 8
                fs_minor = fs_stat.st_dev & 0xFF

                sudo = []
                if os.getuid():
                    sudo = ["sudo"]
                root_table = subprocess.check_output(
                    sudo
                    + [
                        "dmsetup",
                        "-j",
                        str(fs_major),
                        "-m",
                        str(fs_minor),
                        "table",
                    ],
                    stderr=subprocess.DEVNULL,
                )

                _start, _sectors, target_type, target_args = (
                    root_table.decode().split(" ", 3)
                )
                if target_type == "thin":
                    thin_pool_devnum, _thin_pool_id = target_args.split(" ")
                    with open(
                        "/sys/dev/block/{}/dm/name".format(thin_pool_devnum),
                        "r",
                        encoding="ascii",
                    ) as thin_pool_tpool_f:
                        thin_pool_tpool = thin_pool_tpool_f.read().rstrip("\n")
                    if thin_pool_tpool.endswith("-tpool"):
                        # LVM replaces '-' by '--' if name contains
                        # a hyphen
                        thin_pool_tpool = thin_pool_tpool.replace("--", "=")
                        volume_group, thin_pool, _tpool = (
                            thin_pool_tpool.rsplit("-", 2)
                        )
                        volume_group = volume_group.replace("=", "-")
                        thin_pool = thin_pool.replace("=", "-")
                        cls._thin_pool[dir_path] = volume_group, thin_pool
            except:  # pylint: disable=bare-except
                pass

    @classmethod
    def thin_pool(cls, dir_path):
        """Thin tuple (volume group, pool name) containing given filesystem"""
        cls._init(dir_path)
        return cls._thin_pool[dir_path]
