"""
Driver for storing qube images in ZFS pool volumes.
"""

import asyncio
import contextlib
import dataclasses
import logging
import os
import random
import shlex
import shutil
import string
import subprocess
import time

import qubes
import qubes.storage
import qubes.storage.file
import qubes.utils


from typing import (
    cast,
    Optional,
    TypedDict,
    Dict,
    List,
    Union,
    Any,
    AsyncIterator,
    Tuple,
    Coroutine,
    Literal,
    TypeVar,
    Callable,
    Type,
    Set,
)

ZVOL_DIR = "/dev/zvol"
EXPORTED = ".exported"
IMPORTING = ".importing"
TMP = ".tmp"
REVISION_PREFIX = "qubes"
QUBES_POOL_FLAG = "org.qubes-os:part-of-qvm-pool"
CLEAN_SNAPSHOT = "qubes-clean"
# Controls whether `qvm-pool remove` destroys a pool if
# the pool is the root of a ZFS pool.  By default it
# is false because the user may have created a Qubes
# storage pool in the root of a ZFS pool by mistake,
# and therefore removal of the storage pool could lead to
# unrelated datasets being catastrophically destroyed.
DESTROY_ROOT_POOLS = False
# If True, a volume revision is deleted once the volume
# has been rolled back to it.
DELETE_REVISION_UPON_REVERT = True
# Knob to quickly enable debug logging as warning.
DEBUG_IS_WARNING = False

# Sentinel value for auto-snapshot policy:
# Do not let zfs-auto-snapshot create useless snapshots
# for a volume that will be wiped anyway, and whose
# source is likely either not snapshot-worthy, or
# already auto-snapshotted by explicit sysadmin policy.
NO_AUTO_SNAPSHOT = {"com.sun:auto-snapshot": "false"}
DEF_AUTO_SNAPSHOT: Dict[str, str] = {}

_sudo, _dd, _zfs, _zpool, _ionice = "sudo", "dd", "zfs", "zpool", "ionice"


async def fail_unless_exists_async(path: str) -> None:
    if os.path.exists(path):
        return
    err = f"Device path {path} never appeared"
    raise qubes.storage.StoragePoolException(err)


def get_random_string(
    length: int,
    character_set: str = string.ascii_lowercase,
) -> str:
    return "".join(random.choice(character_set) for _ in range(length))


T = TypeVar("T")


async def retry_async(
    kallable: Callable[[], Coroutine[None, None, T]],
    exception_class: Type[BaseException],
    times: int,
    sleep_between_tries: float,
) -> T:
    counter = times
    while True:
        try:
            v = await kallable()
            return v
        except exception_class:
            counter = counter - 1
            if counter < 1:
                raise
            await asyncio.sleep(sleep_between_tries)


async def wait_for_device_async(devpath: str) -> str:
    await retry_async(
        lambda: fail_unless_exists_async(devpath),
        qubes.storage.StoragePoolException,
        1000,
        0.01,
    )
    return devpath


def dataset_in_root(dataset: str, root: str) -> bool:
    """
    Checks that a dataset is within a root.

    >>> dataset_in_root("a/b", "a")
    True
    >>> dataset_in_root("a", "a")
    True
    >>> dataset_in_root("a/b", "a/c")
    False
    """
    return dataset == root or (dataset + "/").startswith(root + "/")


def timestamp_to_revision(timestamp: Union[int, str, float], cause: str) -> str:
    """
    Converts a timestamp to a revision.

    >>> timestamp_to_revision(123, "a")
    qubes:a:123.000000
    >>> timestamp_to_revision(123.1, "b")
    qubes:b:123.100000
    >>> timestamp_to_revision("123", "C")
    qubes:C:123.000000
    """
    return "%s:%s:%.6f" % (REVISION_PREFIX, cause, float(timestamp))


def is_revision_dataset(fsname: "VolumeSnapshot") -> bool:
    """
    Verifies that a snapshot name is a revision snapshot.

    >>> is_revision_dataset("testvol/vm/private@qubes:123")
    True
    >>> is_revision_dataset("testvol/vm/private@qubes:after-x:123")
    True
    >>> is_revision_dataset("testvol/vm/private@qubes-after-x:123")
    False
    """
    return fsname.snapshot.startswith(REVISION_PREFIX + ":")


def timestamp_from_revision(fsname: str) -> float:
    """
    From a revision snapshot name, infer the timeestamp.

    >>> timestamp_from_revision("testvol/vm/private@qubes:123")
    123.0
    >>> timestamp_from_revision("testvol/vm/private@qubes:after-x:123")
    123.0
    """
    return float(fsname.split("@")[-1].split(":")[-1])


async def duplicate_disk(
    inpath: str,
    outpath: str,
    log: logging.Logger,
) -> None:
    """
    Byte-copies (sparsely) from inpath to outpath.

    Will print periodic progress info to stderr.

    Raises `qubes.storage.StoragePoolException` if the copy fails.
    """
    thecmd = [
        _ionice,
        "-c3",
        "--",
        _dd,
        "if=" + inpath,
        "of=" + outpath,
        "conv=sparse,nocreat",
        "status=progress",
        "bs=64M",
        "iflag=nocache",
        "oflag=nocache,dsync",
    ]

    if not os.access(outpath, os.W_OK) or not os.access(inpath, os.R_OK):
        thecmd = [_sudo] + thecmd
    log.debug(
        "Duplicating %s to %s",
        inpath,
        outpath,
    )
    log.debug("Invoked with arguments %r", thecmd)
    p = await asyncio.create_subprocess_exec(*thecmd)
    ret = await p.wait()
    if ret != 0:
        raise qubes.storage.StoragePoolException(
            "%s failed with error %s" % (thecmd, ret)
        )


def check_zfs_available() -> None:
    if not shutil.which(_zfs) or not shutil.which(_zpool):
        raise qubes.storage.StoragePoolException(
            "ZFS is not available on this system",
        )


class DatasetBusy(qubes.storage.StoragePoolException):
    """
    Dataset is busy.  Causes:

      * associated device file open
      * fs mounted with open files (not the case for this driver)
    """


class DatasetHasDependentClones(qubes.storage.StoragePoolException):
    """
    Dataset has dependent clones.

    Caused by attempting to remove a snapshot (or a file system / volume
    containing a snapshot) that is currently cloned to another dataset
    (file system or volume).

    To remove such datasets, one of its clones must be promoted so that
    it takes over ownership (and disk space accounting) of the snapshot
    in question.
    """


class DatasetDoesNotExist(qubes.storage.StoragePoolException):
    """
    Dataset does not exist.

    Raised when an operation with a dataset fails because it cannot
    be found in the pool (e.g. it was deleted).
    """


@contextlib.contextmanager
def _enoent_is_spe():
    try:
        yield
    except FileNotFoundError as exc:
        # Oops.  No ZFS.  Raise the appropriate exception.
        raise qubes.storage.StoragePoolException(
            "ZFS is not available on this system",
        ) from exc


def zfs(
    *cmd: str,
    log: logging.Logger,
) -> str:
    """
    Call :program:`zfs` to execute a ZFS operation.

    If the first parameter in cmd is "zpool", then
    :program:`zpool` is called instead.

    Returns the standard output of the program run.

    Raises a `qubes.storage.StoragePoolException` if the command fails.

    This version is synchronous.
    """
    thecmd, environ = _generate_zfs_command(cmd)
    with _enoent_is_spe():
        p = subprocess.run(
            thecmd,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=False,
            close_fds=True,
            env=environ,
        )
    return _process_zfs_output(
        thecmd,
        p.returncode,
        p.stdout,
        p.stderr,
        log=log,
    )


async def zfs_async(
    *cmd: str,
    log: logging.Logger,
) -> str:
    """
    Asynchronous version of `zfs()`.
    """
    thecmd, environ = _generate_zfs_command(cmd)
    with _enoent_is_spe():
        p = await asyncio.create_subprocess_exec(
            *thecmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environ,
            close_fds=True,
        )
    stdout, stderr = await p.communicate()
    returncode = await p.wait()
    return _process_zfs_output(
        thecmd,
        returncode,
        stdout,
        stderr,
        log=log,
    )


def _generate_zfs_command(
    cmd: Tuple[str, ...],
) -> Tuple[List[str], Dict[str, str]]:
    if cmd and cmd[0] == "zpool":
        thecmd = [_zpool] + list(cmd)[1:]
    else:
        thecmd = [_zfs] + list(cmd)
    if os.getuid() != 0:
        thecmd = [_sudo] + thecmd
    environ = {"LC_ALL": "C.UTF-8", **os.environ}
    return thecmd, environ


def _process_zfs_output(
    cmd: List[str],
    returncode: int,
    stdout: bytes,
    stderr: bytes,
    log: logging.Logger,
):
    thecmd_shell = " ".join(shlex.quote(x) for x in cmd)
    err = stderr.decode()
    if stdout:
        numlines = len(stdout.splitlines())
        if numlines > 2:
            log.debug("%s -> (%s lines)", thecmd_shell, numlines)
        else:
            log.debug("%s -> %s", thecmd_shell, stdout.decode().rstrip())
    else:
        log.debug("%s -> (no output)", thecmd_shell)
    if returncode == 0 and err:
        log.warning("%s succeeded but produced stderr: %s", thecmd_shell, err)
    elif returncode != 0:
        log.debug(
            "%s failed with %s and produced stderr: %s",
            thecmd_shell,
            returncode,
            err,
        )
        if err.rstrip().endswith("dataset is busy"):
            raise DatasetBusy(err)
        if "has dependent clones\n" in err or err.rstrip().endswith(
            "has dependent clones"
        ):
            raise DatasetHasDependentClones(err)
        if err.rstrip().endswith("dataset does not exist"):
            raise DatasetDoesNotExist(err)
        raise qubes.storage.StoragePoolException(err)
    return stdout.decode()


class Vid(str):
    @classmethod
    def make(cls, container: str, vm_name: str, volume_name: str) -> "Vid":
        return Vid("{!s}/{!s}/{!s}".format(container, vm_name, volume_name))


class Volume(str):
    @classmethod
    def make(cls, name: str) -> "Volume":
        assert "@" not in name
        return Volume(name)

    @property
    def volume(self) -> "Volume":
        return self

    def snapshot(self, snapshot_name: str) -> "VolumeSnapshot":
        return VolumeSnapshot.make(self, snapshot_name)

    def clean_snapshot(self) -> "VolumeSnapshot":
        return VolumeSnapshot.make(
            self,
            CLEAN_SNAPSHOT + "-" + get_random_string(8),
        )


class VolumeSnapshot(str):
    @classmethod
    def make(cls, dataset: str, snapshot: str) -> "VolumeSnapshot":
        assert "@" not in dataset, "invalid dataset %s" % dataset
        assert "@" not in snapshot, "invalid snapshot name %s" % snapshot
        return VolumeSnapshot("%s@%s" % (dataset, snapshot))

    @property
    def snapshot(self) -> str:
        return self.split("@")[1]

    @property
    def volume(self) -> "Volume":
        return Volume(self.split("@", maxsplit=1)[0])

    def is_clean_snapshot(self) -> bool:
        return self.snapshot.startswith(CLEAN_SNAPSHOT)


@dataclasses.dataclass
class VolumeSnapshotInfo:
    name: VolumeSnapshot
    creation: int
    defer_destroy: bool


class ZFSPoolConfig(TypedDict):
    name: str
    container: str
    driver: str
    revisions_to_keep: int
    ephemeral_volatile: bool
    snap_on_start_forensics: bool


class ZFSPool(qubes.storage.Pool):
    """ZFS thin storage for Qubes OS.

    Volumes are stored as ZFS volumes, under a container dataset
    specified by the *container* argument.  Here is the general
    naming scheme for the volumes:

        {vm_name}/{volume_name}

    On VM startup,  volume contents are modified, depending on type,
    according to the table below:

    snap_on_start  save_on_stop    typical use

    False          False           volatile
        upon domain start:
            the volume is recursively destroyed and recreated
            to its specifications
        upon domain stop:
            the volume is removed completely

    False          True            private / full persistence
        upon create:
            the volume is created according to specifications;
            it may later be used as an import target or a clone
            source
        upon domain start:
            the volume is used as-is; but flagged dirty
        upon domain stop:
            the volume is kept untouched; a revision snapshot
            is created after stopping the qube, and all aged
            snapshots are deleted; then it is flagged clean

    True           False           root / volatile
        upon domain start:
            the volume is recursively destroyed and recreated,
            cloning it from the last committed state of the
            corresponding source volume, and then applying
            the volume's storage specifications (size)
        upon domain stop:
            if snap on start forensics is enabled:
                the volume is kept; the next start it
                will be blown-away and recreated
            if snap on start forensics is disabled:
                the volume will be blown-away

    True           True            unsupported

    The term snap_on_start is deceptive in the ZFS world.  What it
    means in the context of this driver is simply "clone on start",
    when expressed in ZFS terminology.

    The format of the revision name is `qubes:{cause}:{timestamp}`,
    corresponding to a volume snapshot name of `@qubes:{cause}:{timestamp}`,
    where `timestamp` is in '%s.s' format (seconds / milliseconds
    since unix epoch),

    Options exclusive to the ZFS driver:

    * `container` (mandatory string): dataset path to use for the
      ZFS Qubes pool objects.  This driver will both create the
      dataset and, upon `destroy()`, destroy the dataset and all
      descendants too.
    * `snap_on_start_forensics` (default `False`): when `True`,
      `snap_on_start` volumes (generally the root volume of every
      AppVM) in this pool are kept after the machines using them
      are powered off.  Useful to detect compromises in VMs after
      the fact, as well as to perform general analysis of what's
      being written to AppVM's root volumes.  Increases disk space
      usage of the pool as the root volumes do not get cleaned up
      until next VM start.
    """

    driver = "zfs"

    def __init__(
        self,
        *,
        name: str,
        revisions_to_keep: int = 1,
        container: str,
        ephemeral_volatile: bool = False,
        snap_on_start_forensics: bool = False,
    ):
        super().__init__(  # type: ignore
            name=name,
            revisions_to_keep=revisions_to_keep,
            ephemeral_volatile=ephemeral_volatile,
        )
        self.container = container
        # Intify.
        self.revisions_to_keep = int(self.revisions_to_keep)
        # Boolify.
        self.ephemeral_volatile = qubes.property.bool(
            None,
            None,
            self.ephemeral_volatile,
        )
        self.snap_on_start_forensics = qubes.property.bool(
            None,
            None,
            snap_on_start_forensics,
        )
        self._volume_objects_cache: Dict[Vid, ZFSVolume] = {}
        self._cached_usage_time = 0.0
        self._cached_size_time = 0.0
        self._cached_usage = 0
        self._cached_size = 0
        self.log = logging.getLogger("%s" % (self.name,))
        if DEBUG_IS_WARNING:
            self.log.debug = self.log.warning  # type:ignore
        self.accessor: ZFSAccessor = ZFSAccessor(self.container)

    def __repr__(self) -> str:
        return "<{} at {:#x} name={!r} container={!r}>".format(
            type(self).__name__, id(self), self.name, self.container
        )

    @property
    def config(self) -> ZFSPoolConfig:
        return ZFSPoolConfig(
            {
                "name": self.name,
                "container": self.container,
                "driver": self.driver,
                "revisions_to_keep": self.revisions_to_keep,
                "ephemeral_volatile": self.ephemeral_volatile,
                "snap_on_start_forensics": self.snap_on_start_forensics,
            }
        )

    def init_volume(
        self,
        vm: qubes.vm.qubesvm.QubesVM,
        volume_config: Dict[str, Any],
    ) -> "ZFSVolume":
        """
        Initialize a :py:class:`qubes.storage.Volume` from `volume_config`.
        """
        cfg = volume_config

        if "vid" not in cfg:
            if vm and hasattr(vm, "name"):
                vm_name = str(vm.name)
            else:
                # for the future if we have volumes not belonging to a vm
                vm_name = qubes.utils.random_string()  # type:ignore

            vid = Vid.make(self.container, vm_name, volume_config["name"])
        else:
            vid = Vid(cfg["vid"])

        revisions_to_keep = (
            self.revisions_to_keep
            if "revisions_to_keep" not in cfg
            else cfg["revisions_to_keep"]
        )

        volume = ZFSVolume(
            name=cfg["name"],
            pool=self,
            vid=vid,
            revisions_to_keep=revisions_to_keep,
            rw=cfg.get("rw", False),
            save_on_stop=cfg.get("save_on_stop", False),
            size=cfg["size"],
            snap_on_start=cfg.get("snap_on_start", False),
            source=cfg.get("source", None),
            ephemeral=cfg.get("ephemeral"),
            snap_on_start_forensics=cfg.get("snap_on_start_forensics", False),
        )
        self._volume_objects_cache[vid] = volume
        return volume

    async def __init_container(self) -> None:
        try:
            ret = await zfs_async(
                "list",
                "-H",
                "-o",
                f"name,{QUBES_POOL_FLAG}",
                self.container,
                log=self.log,
            )
            val = ret.splitlines()[0].split("\t")[1]
            if val != "true":
                # Probably a root pool!  It already exists, but doesn't
                # have the flag.  So we flag it here.  Mere existence
                # is not enough to determine if the pool has already been
                # flagged as a ZFS pool (needed because of udev rules).
                await zfs_async(
                    "set",
                    f"{QUBES_POOL_FLAG}=true",
                    "volmode=dev",
                    self.container,
                    log=self.log,
                )
        except qubes.storage.StoragePoolException:
            self.log.info("Creating container dataset %s", self.container)
            await zfs_async(
                "create",
                # Nothing below here shall be mounted by default.
                "-o",
                "mountpoint=none",
                # No volumes shall have their partitions exposed in dom0.
                "-o",
                "volmode=dev",
                # Ensure Qubes OS knows this is a Qubes pool, as well
                # as all descendant datasets, for udev purposes.
                "-o",
                f"{QUBES_POOL_FLAG}=true",
                "-p",
                self.container,
                log=self.log,
            )

    async def setup(self) -> None:
        # Trip here to prevent pool being added without ZFS.
        check_zfs_available()
        await self.__init_container()

    async def destroy(self) -> None:
        """
        Destroy this pool.  The container will be gone after calling this.
        """
        try:
            await zfs_async(
                "list",
                self.container,
                log=self.log,
            )
        except qubes.storage.StoragePoolException:
            # Pool container does not exist anymore.
            return

        # Pool exists.  Is it the root of a pool or not?
        if "/" in self.container:
            # This is a child dataset of the root of a pool.
            # Safe to destroy recursively.
            self.log.info("Deleting container dataset %s", self.container)
            await zfs_async(
                "destroy",
                "-r",
                self.container,
                log=self.log,
            )
        else:
            # This is the root of a pool.  We only destroy children here.
            # Thus, only select the immediate children for recursive delete,
            # because zfs destroy does not work on the root dataset of a pool.
            # To prevent data loss in datasets unrelated to the Qubes pool,
            # we only destroy if a boolean is set, which by default is unset.
            if DESTROY_ROOT_POOLS:
                self.log.info("Destroying datasets within %s", self.container)
                datasets_to_delete = [
                    dset
                    for dset in (
                        await zfs_async(
                            "list",
                            "-r",
                            "-o",
                            "name",
                            self.container,
                            log=self.log,
                        )
                    ).splitlines()
                    if len(dset.split("/")) == 2
                ]
                for dset in reversed(datasets_to_delete):
                    await zfs_async(
                        "destroy",
                        "-r",
                        dset,
                        log=self.log,
                    )
            self.log.info(
                "Reverting formerly Qubes-managed properties of %s defaults",
                self.container,
            )
            # Restore volmode to default.
            await zfs_async(
                "inherit",
                "volmode",
                self.container,
                log=self.log,
            )
            # Remove Qubes pool flag.
            await zfs_async(
                "inherit",
                QUBES_POOL_FLAG,
                self.container,
                log=self.log,
            )

    def get_volume(self, vid: Vid) -> "ZFSVolume":
        """Return a volume with given vid"""
        if vid in self._volume_objects_cache:
            return self._volume_objects_cache[vid]

        # don't cache this object, as it doesn't carry full configuration
        return ZFSVolume("unconfigured", self, vid)

    def notify_volume_deleted(self, volume: "ZFSVolume") -> None:
        self._volume_objects_cache.pop(volume.vid, None)

    def list_volumes(self) -> List["ZFSVolume"]:
        """Return a list of volumes managed by this pool"""
        return list(self._volume_objects_cache.values())

    @property
    def size(self) -> int:
        """
        Return size in bytes of the pool

        Value is never queried to the backend more than once in 30 seconds.
        """
        now = time.time()
        if self._cached_size_time + 30 < now:
            self._cached_size = self.accessor.get_pool_size(
                log=self.log,
            )
            self._cached_size_time = now
        return self._cached_size

    @property
    def usage(self) -> int:
        """
        Return usage of pool in bytes.

        Value is never queried to the backend more than once in 30 seconds.
        """
        now = time.time()
        if self._cached_usage_time + 30 < now:
            self._cached_usage = self.accessor.get_pool_size(
                log=self.log,
            ) - self.accessor.get_pool_available(
                log=self.log,
            )
            self._cached_usage_time = now
        return self._cached_usage


ZFSPropertyBag = TypedDict(
    "ZFSPropertyBag",
    {
        "exists": bool,
        "volsize": int,
        "snapshots": List[VolumeSnapshot],
        "readonly": bool,
        "creation": int,
        "used": int,
        "org.qubes:dirty": bool,
    },
    total=False,
)
ZFSPropertyKeys = Literal[
    "volsize",
    "exists",
    "snapshots",
    "readonly",
    "creation",
    "used",
    "org.qubes:dirty",
]


class ZFSPropertyCache:
    """
    A cache to speed up property query operations and other
    expensive requests.

    Caller must grab the lock available in this class
    instance during a sequence of gets / sets / invalidates.
    The correct way to grab the lock varies depending on
    whether the calling code is async or not:

    * If the caller is async:
        async with propertycache.locked():
            <your async-safe code goes here>
    * If the caller is sync:
        no lock necessary, qubesd is not multithreaded
            <your blocking code goes here>

    The lock is not recursive!  Never call a function that
    holds the lock from another function that grabs the lock.
    """

    def __init__(self) -> None:
        self.cache: Dict[Union[Volume, VolumeSnapshot], ZFSPropertyBag] = {}
        self.__lock = asyncio.Lock()

    @contextlib.asynccontextmanager
    async def locked(self):
        """Lock context manager to aid in respecting Demeter's law."""
        async with self.__lock:
            yield

    def set(
        self,
        obj: Union[Volume, VolumeSnapshot],
        propname: ZFSPropertyKeys,
        value: Any,
    ) -> None:
        """Set a cached value."""
        # Grab lock before performing operation!
        if obj not in self.cache:
            self.cache[obj] = {}
        propcache = self.cache[obj]
        propcache[propname] = value

    def get(
        self,
        obj: Union[Volume, VolumeSnapshot],
        propname: ZFSPropertyKeys,
    ) -> Any:
        """Get a cached value.  Returns None if not in cache."""
        # Grab lock before performing operation!
        if obj not in self.cache:
            return None
        if propname not in self.cache[obj]:
            return None
        return self.cache[obj][propname]

    def invalidate(
        self,
        obj: Union[Volume, VolumeSnapshot],
        propname: Optional[ZFSPropertyKeys] = None,
    ) -> None:
        """Invalidate a cache value or all values for an object."""
        # Grab lock before performing operation!
        if obj not in self.cache:
            return
        if propname is None:
            del self.cache[obj]
        else:
            if propname not in self.cache[obj]:
                return
            del self.cache[obj][propname]

    def invalidate_recursively(
        self,
        obj: Volume,
        propname: Optional[ZFSPropertyKeys] = None,
    ) -> None:
        """Invalidate a value / all values for an object and descendants."""
        # Grab lock before performing operation!
        for dataset in list(self.cache):
            if not dataset_in_root(dataset, obj):
                continue
            if propname is None:
                del self.cache[dataset]
            elif propname in self.cache[dataset]:
                del self.cache[dataset][propname]


class ZFSAccessor:
    """
    Utility class to get / set / cache properties of datasets, as well
    as modify pool members (primarily oriented to volumes and snapshots).
    """

    def __init__(self, root: str) -> None:
        """
        Initialize.

        `root` is the root dataset against which all operations will be
        validated.  If an operation is attempted outside the root,
        an error is raised.
        """
        self.root = root
        self._cache = ZFSPropertyCache()
        self._usage_data = 0.0
        self._initialized = False

    async def _get_prop_table_async(
        self,
        volume: Union[Volume, VolumeSnapshot],
        columns: List[str],
        log: logging.Logger,
        recursive: bool = False,
    ) -> List[Dict[str, str]]:
        args = ["list", "-Hp"] + (["-r"] if recursive else [])
        args.extend(["-o", ",".join(columns)])
        text = await zfs_async(
            *args,
            volume,
            log=log,
        )
        result: List[Dict[str, str]] = []
        for line in text.splitlines():
            if not line.rstrip():
                continue
            fields = line.split("\t")
            row: Dict[str, str] = {}
            for k, v in zip(columns, fields):
                row[k] = v
            result.append(row)
        return result

    async def _get_prop_row_async(
        self,
        volume: Union[Volume, VolumeSnapshot],
        columns: List[str],
        log: logging.Logger,
    ) -> Dict[str, str]:
        res = await self._get_prop_table_async(volume, columns, log=log)
        return res[0]

    async def _get_prop_async(
        self,
        volume: Union[Volume, VolumeSnapshot],
        propname: str,
        log: logging.Logger,
    ) -> str:
        res = await self._get_prop_row_async(volume, [propname], log=log)
        return res[propname]

    def _get_prop_table(
        self,
        volume: Union[Volume, VolumeSnapshot],
        columns: List[str],
        log: logging.Logger,
        recursive: bool = False,
    ) -> List[Dict[str, str]]:
        args = ["list", "-Hp"] + (["-r"] if recursive else [])
        args.extend(["-o", ",".join(columns)])
        out = zfs(
            *args,
            volume,
            log=log,
        )
        result: List[Dict[str, str]] = []
        for line in out.splitlines():
            if not line.rstrip():
                continue
            fields = line.split("\t")
            row: Dict[str, str] = {}
            for k, v in zip(columns, fields):
                row[k] = v
            result.append(row)
        return result

    def _get_prop_row(
        self,
        volume: Union[Volume, VolumeSnapshot],
        columns: List[str],
        log: logging.Logger,
    ) -> Dict[str, str]:
        res = self._get_prop_table(volume, columns, log)
        return res[0]

    def _get_prop(
        self,
        volume: Union[Volume, VolumeSnapshot],
        propname: str,
        log: logging.Logger,
    ) -> str:
        res = self._get_prop_row(volume, [propname], log)
        return res[propname]

    async def _set_prop_async(
        self,
        volume: Volume,
        propname: str,
        propval: str,
        log: logging.Logger,
    ) -> None:
        await zfs_async("set", "%s=%s" % (propname, propval), volume, log=log)

    def _ack_exists_nl(self, volume: Volume):
        # This is just for the cache to efficiently
        # set existence of a dataset and its parents.
        # Must call with cache lock grabbed.
        splits = volume.split("/")
        for components, _ in enumerate(splits):
            components += +1
            dset = "/".join(splits[:components])
            if dataset_in_root(dset, self.root):
                self._cache.set(Volume.make(dset), "exists", True)

    async def volume_exists_async(
        self,
        volume: Volume,
        log: logging.Logger,
    ) -> bool:
        """
        Does volume exist?
        """
        assert dataset_in_root(volume, self.root)
        async with self._cache.locked():
            if not self._initialized:
                # Optimization.  Retrieve all exists properties
                # for all the volumes right away.  This is the
                # most frequently-asked piece of information, so
                # it makes sense to gather it right away.
                props = [
                    "name",
                    "creation",
                    "readonly",
                    "org.qubes:dirty",
                    "volsize",
                ]
                try:
                    res = await self._get_prop_table_async(
                        Volume.make(self.root), props, log=log, recursive=True
                    )
                    for row in res:
                        vol = Volume.make(row["name"])
                        self._cache.set(vol, "exists", True)
                        if row["creation"] != "-":
                            crtn = int(row["creation"])
                            self._cache.set(vol, "creation", crtn)
                        rdnly = row["readonly"] == "on"
                        self._cache.set(vol, "readonly", rdnly)
                        drty = row["org.qubes:dirty"] == "on"
                        self._cache.set(vol, "org.qubes:dirty", drty)
                except qubes.storage.StoragePoolException:
                    pass
                self._initialized = True

            cached = self._cache.get(volume, "exists")
            if cached is not None:
                return cast(bool, cached)
            try:
                await self._get_prop_async(volume, "name", log=log)
                self._ack_exists_nl(volume)
                return True
            except qubes.storage.StoragePoolException:
                self._cache.invalidate_recursively(volume)
                self._cache.set(volume, "exists", False)
                return False

    def volume_exists(
        self,
        volume: Volume,
        log: logging.Logger,
    ) -> bool:
        """
        Synchronous version of volume_exists_async.

        No need for locking since qubesd is not multithreaded and async
        code cannot run concurrently with sync code.
        """
        assert dataset_in_root(volume, self.root)
        with contextlib.nullcontext():  # to preserve visual similitude
            if not self._initialized:
                # Optimization.  Retrieve all exists properties
                # for all the volumes right away.  This is the
                # most frequently-asked piece of information, so
                # it makes sense to gather it right away.
                props = [
                    "name",
                    "creation",
                    "readonly",
                    "org.qubes:dirty",
                    "volsize",
                ]
                try:
                    res = self._get_prop_table(
                        Volume.make(self.root), props, log=log, recursive=True
                    )
                    for row in res:
                        vol = Volume.make(row["name"])
                        self._cache.set(vol, "exists", True)
                        if row["creation"] != "-":
                            crtn = int(row["creation"])
                            self._cache.set(vol, "creation", crtn)
                        rdnly = row["readonly"] == "on"
                        self._cache.set(vol, "readonly", rdnly)
                        drty = row["org.qubes:dirty"] == "on"
                        self._cache.set(vol, "org.qubes:dirty", drty)
                except qubes.storage.StoragePoolException:
                    pass
                self._initialized = True

            cached = self._cache.get(volume, "exists")
            if cached is not None:
                return cast(bool, cached)
            try:
                self._get_prop(volume, "name", log=log)
                self._ack_exists_nl(volume)
                return True
            except qubes.storage.StoragePoolException:
                self._cache.invalidate_recursively(volume)
                self._cache.set(volume, "exists", False)
                return False

    async def remove_volume_async(
        self,
        volume_or_snapshot: Union[Volume, VolumeSnapshot],
        log: logging.Logger,
    ) -> None:
        """
        Remove volume unconditionally, as well as all its children.

        If a snapshot is passed instead, only the snapshot is removed.
        """
        async with self._cache.locked():
            await self._remove_volume_async_nl(
                volume_or_snapshot,
                log,
            )

    async def _remove_volume_async_nl(
        self,
        volume_or_snapshot: Union[Volume, VolumeSnapshot],
        log: logging.Logger,
    ) -> None:
        """
        Warning: never call this directly unless you hold self.cache.lock.
        """
        volume = volume_or_snapshot.volume
        assert dataset_in_root(volume, self.root)
        cmd = ["destroy", "-r", volume_or_snapshot]
        if isinstance(volume_or_snapshot, VolumeSnapshot):
            # Deferred destroy as some snapshots may still be busy.
            cmd.insert(1, "-d")
        await zfs_async(*cmd, log=log)
        if isinstance(volume_or_snapshot, VolumeSnapshot):
            self._cache.invalidate(volume, "snapshots")
        else:
            self._cache.invalidate_recursively(volume)
            self._cache.set(volume, "exists", False)

    async def get_snapshot_clones_async(
        self,
        snapshot: VolumeSnapshot,
        log: logging.Logger,
    ) -> List[Volume]:
        """
        Get all volumes that are clones of this snapshot.

        The snapshot must exist.

        The return value is a list of `Volume`.

        This property is not cached — figuring out cache invalidation for
        this property has been postponed to a later cycle.  It is okay not
        to cache this because this is used very rarely.
        """
        assert dataset_in_root(snapshot, self.root)
        result = await self._get_prop_async(
            snapshot,
            "clones",
            log=log,
        )
        if result == "-":
            return []
        return [Volume.make(s) for s in (result).split(",")]

    async def remove_volume_retried_async(
        self,
        volume_or_snapshot: Union[Volume, VolumeSnapshot],
        log: logging.Logger,
    ) -> None:
        async def _remove_with_promote_async() -> None:
            try:
                await self._remove_volume_async_nl(
                    volume_or_snapshot,
                    log=log,
                )
            except DatasetHasDependentClones:
                # The following code looks complicated.
                # It really is not.
                # Narration follows.
                log.debug(
                    "%s has dependents, checking them out",
                    volume_or_snapshot,
                )

                already_promoted: Set[Volume] = set()
                # Queue up a list of snapshots we must check to see
                # if they have clones, so we can promote the clones.
                if isinstance(volume_or_snapshot, VolumeSnapshot):
                    # We already have our snapshot which we cannot delete.
                    snapshots = [volume_or_snapshot]
                else:
                    # We must never promote the file system we are about
                    # to blast from outer space.
                    already_promoted.add(volume_or_snapshot)
                    # List all the snapshots in the volume.
                    snapshots = [
                        sninfo.name
                        for sninfo in await self._get_volume_snapshots_async_nl(
                            volume_or_snapshot,
                            log=log,
                        )
                    ]

                for snapshot in snapshots:
                    # For each snapshot, we're going to get all the clones
                    # made out of it.  The intention is to assign the snapshot
                    # to the first clone, so that then the prior owner can
                    # be deleted (if that's what is being requested).
                    clones = await self.get_snapshot_clones_async(
                        snapshot,
                        log=log,
                    )
                    for clone in clones:
                        if clone in already_promoted:
                            # Never promote something twice.  It is an error.
                            continue

                        # We will now promote this clone.  This will make the
                        # snapshot "owned" by the clone, renaming the snapshot
                        # accordingly.
                        log.debug(
                            "Promoting %s so we can free up %s for removal",
                            clone,
                            snapshot,
                        )
                        await zfs_async("promote", clone, log=log)
                        self._cache.invalidate(clone, "snapshots")
                        self._cache.invalidate(snapshot.volume, "snapshots")
                        # Remember that we promoted this clone now, so we
                        # do not attempt to promote it again.
                        already_promoted.add(clone)
                        # Only promote the first.  We do not need to promote
                        # other clones because it is sufficient to promote one
                        # clone in order for it to "own" the snapshot.
                        break

                if isinstance(volume_or_snapshot, Volume):
                    # Retry the removal now.
                    await self._remove_volume_async_nl(
                        volume_or_snapshot,
                        log=log,
                    )
                    # There is no else clause for VolumeSnapshot because
                    # once a snapshot's clone has been promoted, then
                    # the snapshot is renamed to be "nested under" the
                    # clone, effectively "removing" the snapshot as far
                    # as the caller is concerned.

        async with self._cache.locked():
            # Retry up to 20 times if the dataset is busy.
            # Sometimes users of the volume return before the
            # kernel has actually closed the device file.  We must
            # wait until all users of the device file have closed it.
            await retry_async(
                _remove_with_promote_async,
                DatasetBusy,
                20,
                0.25,
            )

    async def clone_snapshot_to_volume_async(
        self,
        source: VolumeSnapshot,
        dest: Volume,
        dataset_options: Dict[str, str],
        log: logging.Logger,
    ) -> None:
        """
        Atomically clones a snapshot to a new volume.

        The destination must not exist.

        `dataset_options` will be applied to the clone.

        When this function returns, the block device associated
        with the new volume is confirmed to exist.
        """
        assert dataset_in_root(dest, self.root)
        async with self._cache.locked():
            cmd = ["clone", "-p"]
            for optname, optval in dataset_options.items():
                cmd += ["-o", f"{optname}={optval}"]
            cmd += [source, dest]
            await zfs_async(*cmd, log=log)
            self._cache.invalidate_recursively(dest)
            devpath = os.path.join(ZVOL_DIR, dest)
            await wait_for_device_async(devpath)

    async def rename_volume_async(
        self,
        source: Volume,
        dest: Volume,
        log: logging.Logger,
    ) -> None:
        """
        Atomically renames a volume to a new name.

        The new name must not exist.  The parent will be automatically created.

        When this function returns, the block device associated
        with the new name is confirmed to exist.
        """
        assert dataset_in_root(dest, self.root)
        async with self._cache.locked():
            await zfs_async("rename", "-p", source, dest, log=log)
            if dataset_in_root(source, self.root):
                self._cache.invalidate_recursively(source)
                self._cache.set(source, "exists", False)
            self._cache.invalidate_recursively(dest)
            self._ack_exists_nl(dest)
            devpath = os.path.join(ZVOL_DIR, dest)
            await wait_for_device_async(devpath)

    async def rename_snapshot_async(
        self,
        source: VolumeSnapshot,
        dest: VolumeSnapshot,
        log: logging.Logger,
    ) -> None:
        """
        Atomically renames a snapshot to a new name.

        The new name must not exist.
        """
        assert dataset_in_root(dest, self.root)
        assert source.volume == dest.volume
        async with self._cache.locked():
            await zfs_async("rename", source, dest, log=log)
            self._cache.invalidate_recursively(source.volume)

    async def create_volume_async(
        self,
        volume: Volume,
        size: int,
        dataset_options: Dict[str, str],
        log: logging.Logger,
    ) -> None:
        """
        Creates a volume.

        The volume is created thin-provisioned.

        The volume must not already exist.

        `dataset_options` establishes the -o opt=val parameters
        passed to the zfs create command.

        When this function returns, the block device associated
        with the newly-created volume is confirmed to exist.
        """
        assert dataset_in_root(volume, self.root)
        async with self._cache.locked():
            sizestr = str(size)
            cmd = ["create", "-p", "-s", "-V", sizestr]
            for optname, optval in dataset_options.items():
                cmd += ["-o", f"{optname}={optval}"]
            cmd += [volume]
            await zfs_async(
                *cmd,
                log=log,
            )
            self._cache.invalidate_recursively(volume)
            self._ack_exists_nl(volume)
            self._cache.set(volume, "volsize", size)
            devpath = os.path.join(ZVOL_DIR, volume)
            await wait_for_device_async(devpath)

    async def set_volume_readonly_async(
        self,
        volume: Volume,
        readonly: bool,
        log: logging.Logger,
    ) -> None:
        """
        Set a volume to read-only.  Prevents writes.
        """
        assert dataset_in_root(volume, self.root)
        async with self._cache.locked():
            self._cache.invalidate(volume, "readonly")
            val = "on" if readonly else "off"
            await self._set_prop_async(volume, "readonly", val, log)
            self._cache.set(volume, "readonly", readonly)

    async def resize_volume_async(
        self,
        volume: Volume,
        size: int,
        log: logging.Logger,
    ) -> None:
        """
        Enlarge a volume to the specified size.

        The volume must exist.

        An error will be raised if size is < current size.
        """
        assert dataset_in_root(volume, self.root)
        async with self._cache.locked():
            self._cache.invalidate(volume, "volsize")
            await self._set_prop_async(volume, "volsize", str(size), log)
            self._cache.set(volume, "volsize", size)

    def get_volume_size(
        self,
        volume: Volume,
        log: logging.Logger,
    ) -> int:
        """
        Get the current size of the volume, synchronously.

        No need for locking since qubesd is not multithreaded and async
        code cannot run concurrently with sync code.
        """
        assert dataset_in_root(volume, self.root)
        with contextlib.nullcontext():  # to preserve visual similitude
            cached = self._cache.get(volume, "volsize")
            if cached is not None:
                return cast(int, cached)
            ret = int(self._get_prop(volume, "volsize", log))
            self._cache.set(volume, "volsize", ret)
            return ret

    async def get_volume_size_async(
        self,
        volume: Volume,
        log: logging.Logger,
    ) -> int:
        """Get the current size of the volume."""
        assert dataset_in_root(volume, self.root)
        async with self._cache.locked():
            cached = self._cache.get(volume, "volsize")
            if cached is not None:
                return cast(int, cached)
            ret = int(await self._get_prop_async(volume, "volsize", log))
            self._cache.set(volume, "volsize", ret)
            return ret

    async def set_volume_dirty_async(
        self,
        volume: Volume,
        dirty: bool,
        log: logging.Logger,
    ) -> None:
        """
        Mark the volume as dirty.

        Usually used when a VM backed by this volume is started.
        """
        assert dataset_in_root(volume, self.root)
        async with self._cache.locked():
            self._cache.invalidate_recursively(volume, "org.qubes:dirty")
            val = "on" if dirty else "off"
            await self._set_prop_async(volume, "org.qubes:dirty", val, log)
            self._cache.set(volume, "org.qubes:dirty", dirty)

    def is_volume_dirty(
        self,
        volume: Volume,
        log: logging.Logger,
    ) -> bool:
        """
        Sync version of `is_volume_dirty_async()`.

        No need for locking since qubesd is not multithreaded and async
        code cannot run concurrently with sync code.
        """
        assert dataset_in_root(volume, self.root)
        with contextlib.nullcontext():  # to preserve visual similitude
            dirty = self._cache.get(volume, "org.qubes:dirty")
            if dirty is not None:
                return cast(bool, dirty)
            v = self._get_prop(volume, "org.qubes:dirty", log)
            ret = v == "on"
            self._cache.set(volume, "org.qubes:dirty", ret)
            return ret

    async def is_volume_dirty_async(
        self,
        volume: Volume,
        log: logging.Logger,
    ) -> bool:
        """
        Returns true if the volume is dirty.

        The volume must exist.
        """
        assert dataset_in_root(volume, self.root)
        async with self._cache.locked():
            dirty = self._cache.get(volume, "org.qubes:dirty")
            if dirty is not None:
                return cast(bool, dirty)
            v = await self._get_prop_async(volume, "org.qubes:dirty", log)
            ret = v == "on"
            self._cache.set(volume, "org.qubes:dirty", ret)
            return ret

    def get_volume_snapshots(
        self,
        volume: Volume,
        log: logging.Logger,
    ) -> List[VolumeSnapshotInfo]:
        """
        Get all snapshots of the volume, as a list of VolumeSnapshotInfo.
        The list is sorted from oldest to newest.

        The volume must exist.

        No need for locking since qubesd is not multithreaded and async
        code cannot run concurrently with sync code.
        """
        with contextlib.nullcontext():  # to preserve visual similitude
            snapshots = self._cache.get(volume, "snapshots")
            if snapshots is not None:
                return cast(List[VolumeSnapshotInfo], snapshots)
            lines = [
                s.split("\t")
                for s in zfs(
                    "list",
                    "-Hp",
                    "-o",
                    "name,creation,defer_destroy",
                    "-t",
                    "snapshot",
                    volume,
                    log=log,
                ).splitlines()
                if s
            ]
            ret = list(
                sorted(
                    [
                        VolumeSnapshotInfo(
                            VolumeSnapshot.make(
                                s.split("@")[0],
                                s.split("@")[1],
                            ),
                            int(t),
                            d == "on",
                        )
                        for s, t, d in lines
                    ],
                    key=lambda m: m.creation,
                )
            )
            self._cache.set(volume, "snapshots", ret)
            return ret

    async def get_volume_snapshots_async(
        self,
        volume: Volume,
        log: logging.Logger,
    ) -> List[VolumeSnapshotInfo]:
        """
        Get all snapshots of the volume, as a dictionary of VolumeSnapshot
        to creation date (int).

        The volume must exist.

        `lock` can be false if the calling function will grab
        self.cache.lock.
        """
        async with self._cache.locked():
            return await self._get_volume_snapshots_async_nl(volume, log)

    async def _get_volume_snapshots_async_nl(
        self,
        volume: Volume,
        log: logging.Logger,
    ) -> List[VolumeSnapshotInfo]:
        """
        Warning: never call this directly unless you hold self.cache.lock.
        """
        assert dataset_in_root(volume, self.root)
        snapshots = self._cache.get(volume, "snapshots")
        if snapshots is not None:
            return cast(List[VolumeSnapshotInfo], snapshots)
        lines = [
            s.split("\t")
            for s in (
                await zfs_async(
                    "list",
                    "-Hp",
                    "-o",
                    "name,creation,defer_destroy",
                    "-t",
                    "snapshot",
                    volume,
                    log=log,
                )
            ).splitlines()
            if s
        ]
        ret = list(
            sorted(
                [
                    VolumeSnapshotInfo(
                        VolumeSnapshot.make(
                            s.split("@")[0],
                            s.split("@")[1],
                        ),
                        int(t),
                        d == "on",
                    )
                    for s, t, d in lines
                ],
                key=lambda m: m.creation,
            )
        )
        self._cache.set(volume, "snapshots", ret)
        return ret

    async def snapshot_volume_async(
        self,
        vsnapshot: VolumeSnapshot,
        log: logging.Logger,
    ) -> None:
        """
        Snapshot a volume.

        The volume must exist.
        """
        assert dataset_in_root(vsnapshot.volume, self.root)
        async with self._cache.locked():
            self._cache.invalidate(vsnapshot.volume, "snapshots")
            await zfs_async(
                "snapshot",
                vsnapshot,
                log=log,
            )

    async def rollback_to_snapshot_async(
        self,
        vsnapshot: VolumeSnapshot,
        log: logging.Logger,
    ) -> None:
        """
        Rollback a volume to a specific snapshot.

        The volume must exist and contain the specified snapshot.

        All more recent snapshots will be nuked.
        """
        assert dataset_in_root(vsnapshot.volume, self.root)
        async with self._cache.locked():
            self._cache.invalidate(vsnapshot.volume)
            await zfs_async(
                "rollback",
                "-r",
                vsnapshot,
                log=log,
            )

    def get_volume_usage(
        self,
        volume: Volume,
        log: logging.Logger,
    ) -> int:
        """
        Get the usage in bytes of the volume.

        The returned value is the sum total of all volume-related
        objects, including its snapshots.  If the volume and
        all descendants (including clones) were destroyed, this
        is the space that would be returned to the pool.

        The values are updated every 30 seconds.

        No need for locking since qubesd is not multithreaded and async
        code cannot run concurrently with sync code.
        """
        assert dataset_in_root(volume, self.root)
        with contextlib.nullcontext():  # to preserve visual similitude
            now = time.time()
            if self._usage_data + 30 < now:
                self._cache.invalidate_recursively(
                    Volume.make(self.root),
                    "used",
                )
            used = self._cache.get(volume, "used")
            if used is not None:
                return cast(int, used)
            usage_by_dataset = self._get_prop_table(
                Volume.make(self.root),
                ["name", "logicalreferenced"],
                log,
                True,
            )
            for dinfo in usage_by_dataset:
                try:
                    used = int(dinfo["logicalreferenced"])
                except (TypeError, ValueError):
                    # Not an usage — maybe a dash.
                    continue
                vol = Volume.make(dinfo["name"])
                self._cache.set(vol, "used", used)
            self._usage_data = now
            return cast(int, self._cache.get(volume, "used"))

    def get_volume_creation(
        self,
        volume: Volume,
        log: logging.Logger,
    ) -> int:
        """
        Sync version of get_volume_creation_async().

        No need for locking since qubesd is not multithreaded and async
        code cannot run concurrently with sync code.
        """
        assert dataset_in_root(volume, self.root)
        with contextlib.nullcontext():  # to preserve visual similitude
            creation = self._cache.get(volume, "creation")
            if creation is not None:
                return cast(int, creation)
            ret = int(self._get_prop(volume, "creation", log=log))
            self._cache.set(volume, "creation", ret)
            return ret

    async def get_volume_creation_async(
        self,
        volume: Volume,
        log: logging.Logger,
    ) -> int:
        """
        Get volume creation time (as an UNIX timestamp).
        """
        assert dataset_in_root(volume, self.root)
        async with self._cache.locked():
            creation = self._cache.get(volume, "creation")
            if creation is not None:
                return cast(int, creation)
            ret = int(await self._get_prop_async(volume, "creation", log=log))
            self._cache.set(volume, "creation", ret)
            return ret

    def get_pool_available(
        self,
        log: logging.Logger,
    ) -> int:
        """Get available space in the pool, in bytes."""
        return int(
            zfs(
                "zpool",
                "list",
                "-Hp",
                "-o",
                "free",
                self.root.split("/")[0],
                log=log,
            ).strip()
        )

    def get_pool_size(
        self,
        log: logging.Logger,
    ) -> int:
        """Get total size of the pool, in bytes."""
        return int(
            zfs(
                "zpool",
                "list",
                "-Hp",
                "-o",
                "size",
                self.root.split("/")[0],
                log=log,
            ).strip()
        )


class ZFSVolume(qubes.storage.Volume):
    """
    ZFS thin volume implementation.
    """

    pool: ZFSPool

    def __init__(
        self,
        name: str,
        pool: ZFSPool,
        vid: Vid,
        revisions_to_keep: int = 1,
        rw: bool = False,
        save_on_stop: bool = False,
        size: int = 0,
        snap_on_start: bool = False,
        source: Optional[qubes.storage.Volume] = None,
        ephemeral: Optional[bool] = None,
        snap_on_start_forensics: bool = False,
        **kwargs: Dict[str, Any],
    ) -> None:
        """
        Representation of a ZFS-backed volume.

        Arguments:
          name: used internally by Qubes
          pool: ZFSPool object backing this volume
          vid: volume identifier used internally by Qubes
          revisions_to_keep: how many snapshots created by Qubes to keep
          rw: whether the volume should be read/write or read-only
          save_on_stop / snap_on_start: a variety of Qubes volume behaviors
          source: if this volume has a source to clone from, then this variable
                  will contain the `qubes.storage.Volume` source
          ephemeral: internally used by Qubes to implement anti-forensic
                     ephemerally encrypted block devices
          snap_on_start_forensics: for snap_on_start volumes, if True, keep
                                   the volumes around when the VM shuts off,
                                   else clean them up
        """
        if snap_on_start and save_on_stop:
            err = "ZFSVolume %s cannot be snap_on_start && save_on_stop" % vid
            raise qubes.storage.StoragePoolException(err)
        # Intify.
        revisions_to_keep = int(revisions_to_keep)
        if snap_on_start or save_on_stop:
            # Non-volatile.  This type of dataset requires
            # >= 1 revisions to keep if revert is to work
            # meaningfully at all.  The semantics are now
            # the same as the other drivers'.
            if revisions_to_keep < 1:
                err = "ZFSVolume %s needs >= 1 revisions to keep" % vid
                raise qubes.storage.StoragePoolException(err)
        super().__init__(  # type: ignore
            name=name,
            pool=pool,
            vid=vid,
            revisions_to_keep=revisions_to_keep,
            rw=rw,
            save_on_stop=save_on_stop,
            size=size,
            snap_on_start=snap_on_start,
            source=source,
            ephemeral=ephemeral,
            **kwargs,
        )
        self.snap_on_start_forensics = snap_on_start_forensics
        self.vid = vid
        self.log = logging.getLogger("%s" % (self.vid,))
        if DEBUG_IS_WARNING:
            self.log.debug = self.log.warning  # type:ignore
        if kwargs:
            raise qubes.storage.StoragePoolException(
                "Unsupported arguments received: %s" % ", ".join(kwargs),
            )
        self._auto_snapshot_policy = (
            DEF_AUTO_SNAPSHOT if self.save_on_stop else NO_AUTO_SNAPSHOT
        )

    async def _purge_old_revisions(self) -> None:
        """
        Deletes all revisions except the `revisions_to_keep` latest ones.

        May not actually delete all the revisions scheduled for deletion!
        Any revision being used as the basis for a snap-on-start volume
        currently in use simply may not be deleted, because the revision is
        backing the volume in question.  Unlike reflink (where a deleted file
        is absent from the VFS but continues to exist on-disk until all file
        descriptors are closed), ZFS does not permit the removal of datasets
        in active use, or snapshots backing datasets that exist.  However,
        we do mark these snapshots for deferred destruction (defer_destroy),
        so when the backing file system is finally gone, the snapshot will
        be destroyed too.
        """
        self.log.debug("_purge_old_revisions %s", self.volume)
        revisions = self.revisions
        if not revisions:
            return
        revs = list(
            reversed(
                sorted(
                    revisions.items(),
                    key=lambda m: m[1],
                )
            )
        )
        num = self.revisions_to_keep
        for snapshot, _ in revs[num:]:
            vsn = VolumeSnapshot.make(self.vid, snapshot)
            self.log.debug("Pruning %s", vsn)
            await self.pool.accessor.remove_volume_async(vsn, log=self.log)
        return

    async def _mark_clean(self):
        existing_cleans = [
            s.name
            for s in await self.pool.accessor.get_volume_snapshots_async(
                self.volume,
                log=self.log,
            )
            if s.name.is_clean_snapshot()
        ]
        new = self.volume.clean_snapshot()
        await self.pool.accessor.snapshot_volume_async(new, log=self.log)
        for old in existing_cleans:
            await self.pool.accessor.remove_volume_async(
                old,
                log=self.log,
            )

    async def _create_revision(self, cause: str) -> None:
        """Convenience function to create a snapshot timestamped now()."""
        await self.pool.accessor.snapshot_volume_async(
            VolumeSnapshot.make(
                self.volume,
                timestamp_to_revision(
                    time.time(),
                    cause,
                ),
            ),
            log=self.log,
        )
        await self._purge_old_revisions()

    async def _remove_volume_export_if_exists(
        self,
        only_this: Optional[str] = None,
    ) -> None:
        vol = self.exported_volume_name(only_this)
        if await self.pool.accessor.volume_exists_async(
            vol,
            log=self.log,
        ):
            await self.pool.accessor.remove_volume_retried_async(
                vol,
                log=self.log,
            )
            self.log.debug("Removed export %s", vol)

    async def _remove_volume_import_if_exists(self) -> None:
        vol = self.importing_volume_name
        if await self.pool.accessor.volume_exists_async(
            vol,
            log=self.log,
        ):
            await self.pool.accessor.remove_volume_retried_async(
                vol,
                log=self.log,
            )
            self.log.debug("Removed import %s", vol)

    async def _remove_tmp_volume_if_exists(self) -> None:
        vol = self.tmp_volume_name
        if await self.pool.accessor.volume_exists_async(
            vol,
            log=self.log,
        ):
            await self.pool.accessor.remove_volume_retried_async(
                vol,
                log=self.log,
            )
            self.log.debug("Removed import %s", vol)

    async def _remove_volume_if_exists(self) -> None:
        if await self.pool.accessor.volume_exists_async(
            self.volume,
            log=self.log,
        ):
            await self.pool.accessor.remove_volume_retried_async(
                self.volume, log=self.log
            )
            self.log.debug("Removed %s", self.volume)

    async def _remove_volume_and_derived(self) -> "ZFSVolume":
        await self._remove_volume_import_if_exists()
        await self._remove_volume_export_if_exists()
        await self._remove_tmp_volume_if_exists()
        await self._remove_volume_if_exists()
        return self

    async def _wipe_and_clone_from(self, source: qubes.storage.Volume) -> None:
        """
        Clones this volume from the source, atomically.

        If a volume existed before calling this, its data will be lost after
        this function returns successfully.  In case of error while copying
        the data from the source, the existing volume will remain untouched.

        Upon successful return, a bit-by-bit identical copy of the source
        exists in this volume.  Snapshots in this volume (the destination of
        the clone) will be erased too.  If the source volume is a `ZFSVolume`,
        then the copy was performed efficiently using copy-on-write.
        """
        if isinstance(source, ZFSVolume) and source.pool == self.pool:
            # The source device can be efficiently cloned;
            # simply find out what its latest qubes snapshot is,
            # then clone it from there.
            samepoolsource = cast(ZFSVolume, source)
            self.log.debug("Source shares pool with me")
            try:
                src = samepoolsource.latest_clean_snapshot[0]
            except DatasetDoesNotExist:
                src = VolumeSnapshot.make(
                    samepoolsource.volume,
                    samepoolsource.latest_revision[0],
                )
            async with self._clone_volume_2phase(src):
                # Do nothing.  The context manager takes care of everything.
                pass
        else:
            # Source is not a ZFS one;
            # create the dataset with the size of the
            # source (or larger if requested by user)
            # and dd the contents sparsely.
            if isinstance(source, qubes.storage.file.FileVolume):
                self.log.debug("Source is a File volume")
                # File volume export() does not actually return a coroutine.
                # This isn't just a typing error.  The await() fails.
                loop = asyncio.get_event_loop()
                in_ = await loop.run_in_executor(
                    None,
                    source.export,
                )  # type:ignore
            else:
                self.log.debug("Source is not a ZFS volume")
                in_ = await source.export()  # type:ignore
            try:
                async with self._copy_into_volume_2phase(source.size) as out:
                    await duplicate_disk(in_, out, self.log)
            finally:
                await source.export_end(in_)  # type:ignore

    async def _wipe_and_create_empty(
        self,
        size: Optional[int] = None,
    ) -> None:
        """
        Wipe a dataset and create it anew, empty.
        """
        # FIXME: optimization -- if both volumes are the same
        # size, or the requested size is larger than the
        # current size, then instead of deleting the volume,
        # BLKDISCARD the volume and then grow the size of the
        # volume, so it returns zeroes all over the place before
        # we return to the caller.  Confirm via experimentation
        # and unit testing that the newly-added tail of the volume
        # returns zeroes — perhaps it is not necessary.
        await self._remove_volume_if_exists()
        size = size if size is not None else self._size
        self.log.debug(
            "Creating empty volume %s with size %s",
            self.volume,
            size,
        )
        await self.pool.accessor.create_volume_async(
            self.volume,
            size,
            self._auto_snapshot_policy,
            log=self.log,
        )

    def _make_tmp_commit_rollback(
        self,
    ) -> Tuple[
        Callable[[], Coroutine[Any, Any, None]],
        Callable[[], Coroutine[Any, Any, None]],
    ]:
        # This code constructs generic rollback and commit hooks
        # for _start_clone and _start_copy, which conceptually
        # are the same, but just differ in implementation.
        async def rollback() -> None:
            self.log.error("Rolling back clone/copy of %s", self.volume)
            await self._remove_tmp_volume_if_exists()

        async def finish() -> None:
            self.log.debug("Finishing clone/copy of %s", self.volume)
            try:
                await self._remove_volume_if_exists()
            except Exception:
                await rollback()
                raise
            await self.pool.accessor.rename_volume_async(
                self.tmp_volume_name,
                self.volume,
                log=self.log,
            )
            self.log.debug("Finished clone/copy of %s", self.volume)

        return finish, rollback

    @contextlib.asynccontextmanager
    async def _clone_volume_2phase(
        self,
        src: VolumeSnapshot,
    ) -> AsyncIterator[None]:
        """
        Wipe the matching temporary dataset and clone it from src.
        Yield nothing, but work as a context.

        Requires src VolumeSnapshot to exist.

        If there is an error, the temporary dataset is rolled back.
        If the context finishes without error, the temporary dataset
        is committed to the volume.
        """
        await self._remove_tmp_volume_if_exists()
        self.log.debug(
            "Starting clone from %s into %s via zfs clone",
            src,
            self.tmp_volume_name,
        )
        await self.pool.accessor.clone_snapshot_to_volume_async(
            src,
            self.tmp_volume_name,
            self._auto_snapshot_policy,
            log=self.log,
        )
        finish, rollback = self._make_tmp_commit_rollback()
        try:
            yield
            await finish()
        except Exception:
            await rollback()
            raise

    @contextlib.asynccontextmanager
    async def _copy_into_volume_2phase(
        self,
        size: Optional[int] = None,
    ) -> AsyncIterator[str]:
        """
        Wipe the matching temporary dataset and create it anew, empty,
        in preparation for a copy.  Yield a writable path to the caller,
        while working as a context.

        If there is an error, the temporary dataset is rolled back.
        If the context finishes without error, the temporary dataset
        is committed to the volume.
        """
        # FIXME: optimization -- if both volumes are the same
        # size, or the requested size is larger than the
        # current size, then instead of deleting the volume,
        # BLKDISCARD the volume and then grow the size of the
        # volume, so it returns zeroes all over the place before
        # we return to the caller.  Confirm via experimentation
        # and unit testing that the newly-added tail of the volume
        # returns zeroes — perhaps it is not necessary.
        await self._remove_tmp_volume_if_exists()
        size = size if size is not None else self._size
        self.log.debug(
            "Starting copy into %s with size %s with an empty volume",
            self.tmp_volume_name,
            size,
        )
        await self.pool.accessor.create_volume_async(
            self.tmp_volume_name,
            size,
            self._auto_snapshot_policy,
            log=self.log,
        )
        finish, rollback = self._make_tmp_commit_rollback()
        try:
            yield os.path.join(ZVOL_DIR, self.tmp_volume_name)
            await finish()
        except Exception:
            await rollback()
            raise

    @property
    def volume(self) -> Volume:
        """Return the Volume object for this ZFSVolume."""
        return Volume(self.vid)

    def exported_volume_name(self, suffix: Optional[str] = None) -> Volume:
        p = os.path.join(
            self.pool.container,
            EXPORTED,
            self.vid.replace("/", "_"),
        )
        if suffix:
            p = os.path.join(p, suffix)
        return Volume.make(p)

    @property
    def importing_volume_name(self) -> Volume:
        return Volume.make(
            os.path.join(
                self.pool.container,
                IMPORTING,
                self.vid.replace("/", "_"),
            )
        )

    @property
    def tmp_volume_name(self) -> Volume:
        return Volume.make(
            os.path.join(
                self.pool.container,
                TMP,
                self.vid.replace("/", "_"),
            )
        )

    @property
    def revisions(self) -> Dict[str, str]:
        """
        Return a dictionary of revisions.

        While the type says `[str, str]`, the specific format of the returned
        revisions is as follows:
        * key is in the revision name format `qubes:{cause}:{timestamp}` and
          is the name of the snapshot that ZFS stores for this revision
        * value is an ISO date string referring to when the revision was
          created

        Revisions marked for deferred destruction are also listed.
        The user may revert a volume to such revisions until the moment
        that the dependent cloned dataset is destroyed, at which point in
        time the revision will disappear and will no longer be usable as a
        revert point.  This behavior was tested manually.
        """
        if not self.pool.accessor.volume_exists(self.volume, self.log):
            # No snapshots, volume does not exist yet.
            return {}
        snapshots = self.pool.accessor.get_volume_snapshots(
            self.volume,
            log=self.log,
        )
        revisions: Dict[str, str] = {}
        for sninfo in snapshots:
            if is_revision_dataset(sninfo.name) and not sninfo.defer_destroy:
                # It is important to hide the already-deleted revisions,
                # even if their deletion is deferred.
                timestamp = timestamp_from_revision(sninfo.name)
                revisions[sninfo.name.snapshot] = qubes.storage.isodate(
                    timestamp,
                )  # type: ignore
        return revisions

    @property  # type: ignore
    def size(self) -> int:
        """
        Get the allocated size of this volume.

        If the volume does not exist, it returns the presumptive size
        allocation the volume would get upon creation, which is a
        configuration value set at creation / resize time.
        """
        if not self.pool.accessor.volume_exists(self.volume, self.log):
            return self._size
        return self.pool.accessor.get_volume_size(
            self.volume,
            log=self.log,
        )

    @property
    def usage(self) -> int:  # type: ignore
        """
        Return used size of dataset in bytes.

        This usage data corresponds to the amount of logical bytes used in
        the dataset.  The dataset can actually take more space in disk than
        this number, because it can have snapshots, which are counted towards
        the total disk space usage of the dataset.

        However, this number matches the semantics expected by qui-disk-space.

        See zfsprops(7) for more info.
        """
        if not self.pool.accessor.volume_exists(self.volume, self.log):
            return 0
        return self.pool.accessor.get_volume_usage(
            self.volume,
            log=self.log,
        )

    @qubes.storage.Volume.locked  # type: ignore
    async def remove(self) -> "ZFSVolume":
        # FIXME: if the last volume of the VM is removed, then
        # the parent dataset should be removed too.
        ret = await self._remove_volume_and_derived()
        self.pool.notify_volume_deleted(self)
        return ret

    @qubes.storage.Volume.locked  # type: ignore
    async def create(self) -> "ZFSVolume":
        self.log.debug(
            "Creating %s save_on_stop %s snap_on_start %s",
            self.volume,
            self.save_on_stop,
            self.snap_on_start,
        )
        snap_on_start, save_on_stop = (self.snap_on_start, self.save_on_stop)

        if snap_on_start and save_on_stop:
            assert 0, "snap_on_start && save_on_stop on %s" % self.volume

        elif save_on_stop:
            # Private / persistent.
            # Save on stop cannot be True when snap on start
            # is True.  This means that this branch can never
            # be taken when snap on start is True.  Furthermore,
            # init_volume() blows up if a source is set, but
            # snap on start is False.  Ergo, self.source is
            # always unset here, and we do not need to cover
            # that case.
            #
            # This is silly tho!  Why can't I clone a save on stop
            # volume this way too?  It would be equivalent to the
            # import path, which the ZFS code is perfectly capable
            # of doing in an optimized way.
            if self.source:
                assert 0, "self.source != None && save_on_stop == True"
            self.log.debug(
                "Creating %s empty",
                self.volume,
            )
            await self._wipe_and_create_empty()
            # Make initial clean snapshot so this volume can be cloned later.
            await self._create_revision("after-create")
            await self._mark_clean()

        else:
            self.log.debug(
                "Deferring creation of %s (source %s)",
                self.volume,
                self.source,
            )

        return self

    @qubes.storage.Volume.locked  # type: ignore
    async def start(self) -> "ZFSVolume":
        """Start the volume, ensuring it is available to use in VMs."""
        # I have investigated what the other drivers do in this case for
        # snap on start and save on stop.  In both cases, the volume is
        # only acted upon if it is not dirty.  If it is dirty, the logic
        # is completely stopped.
        #
        # We do not track dirty / not dirty for fully volatile volumes,
        # we only track their existence.  If it exists, it's dirty and
        # therefore already started, so don't touch it.
        self.abort_if_import_in_progress()

        self.log.debug("Starting volume %s", self.volume)
        snap_on_start, save_on_stop = (self.snap_on_start, self.save_on_stop)

        if snap_on_start and save_on_stop:
            assert 0, "snap_on_start && save_on_stop on %s" % self.volume

        elif not snap_on_start and not save_on_stop:
            # Volatile.  Dataset only created on start.
            # God help me if the user specify a source volume here.
            # That should never have happened.
            assert not self.source, "volatiles should not have sources"
            if not await self.pool.accessor.volume_exists_async(
                self.volume,
                log=self.log,
            ):
                self.log.debug(
                    "Creating volatile %s empty",
                    self.volume,
                )
                await self._wipe_and_create_empty()

        elif save_on_stop:
            # Private / persistent.  Dataset already created.
            # We snapshot prior to end of start() to allow for the ability
            # to export / clone the volume cleanly while the VM is running.
            # Therefore we can support the assumption that the latest snapshot
            # is always the most up-to-date clean data source, and therefore
            # is cleanly exportable.
            if not await self.pool.accessor.is_volume_dirty_async(
                self.volume,
                log=self.log,
            ):
                self.log.debug("Dirtying up save on stop %s", self.volume)
                await self._create_revision("before-start")
                await self.pool.accessor.set_volume_dirty_async(
                    self.volume,
                    True,
                    log=self.log,
                )

        elif snap_on_start:
            if not await self.pool.accessor.volume_exists_async(
                self.volume,
                log=self.log,
            ) or not await self.pool.accessor.is_volume_dirty_async(
                self.volume,
                log=self.log,
            ):
                # Root / reset-on-start.  Clone or create from source.
                if self.source:
                    self.log.debug(
                        "Cloning snap on start %s from %s",
                        self.volume,
                        self.source,
                    )
                    await self._wipe_and_clone_from(self.source)
                else:
                    self.log.debug(
                        "Creating snap on start %s empty",
                        self.volume,
                    )
                    await self._wipe_and_create_empty()
                self.log.debug("Dirtying up snap on start %s", self.volume)
                await self.pool.accessor.set_volume_dirty_async(
                    self.volume,
                    True,
                    log=self.log,
                )

        # At the very end we set the read-only flag to what the
        # user requested via configuration.  This is wonderful
        # because it means the volume cannot be modified by anything
        # at all, even if something downstream insists the drive
        # be made read-write.
        await self.pool.accessor.set_volume_readonly_async(
            self.volume,
            not self.rw,
            log=self.log,
        )
        return self

    @qubes.storage.Volume.locked  # type: ignore
    async def stop(self) -> "ZFSVolume":
        """
        Stop the volume, making it clean for clones and such.

        In reality, only save on stop volumes are snapshotted for cloning.
        Snap on start volumes may be / may not be deleted, depending on
        Qubes ZFS pool configuration.
        """
        self.log.debug("Stopping volume %s", self.volume)
        snap_on_start, save_on_stop = (self.snap_on_start, self.save_on_stop)

        if snap_on_start and save_on_stop:
            assert 0, "snap_on_start && save_on_stop on %s" % self.volume

        elif not snap_on_start and not save_on_stop:
            # Volatile.  Delete if exists.  No sense in keeping this.
            await self._remove_volume_and_derived()

        elif save_on_stop:
            # Private / persistent.  User data that must be persisted.
            if await self.pool.accessor.volume_exists_async(
                self.volume,
                log=self.log,
            ) and await self.pool.accessor.is_volume_dirty_async(
                self.volume,
                log=self.log,
            ):
                self.log.debug("Marking as clean save on stop %s", self.volume)
                await self.pool.accessor.set_volume_dirty_async(
                    self.volume,
                    False,
                    log=self.log,
                )
                # Make clean snapshot so this volume can be cloned later.
                await self._mark_clean()

        elif snap_on_start:
            # Root / reset-on-start.
            # Will be recreated on start() anyway.
            if self.snap_on_start_forensics:
                self.log.debug(
                    "Marking as clean snap_on_start %s, keeping volume around",
                    self.volume,
                )
                await self.pool.accessor.set_volume_dirty_async(
                    self.volume,
                    False,
                    log=self.log,
                )
            else:
                await self._remove_volume_and_derived()

        return self

    async def export(self) -> str:
        """
        Returns an object that can be `open()`.

        Writes to the object will not be persisted in this volume.  It is
        expected that the caller will eventually call `export_end()` at
        which time the exported volume will be destroyed.
        """
        self.log.debug("Start of export of %s", self.volume)
        if not self.save_on_stop:
            raise NotImplementedError(
                f"Cannot export {self.vid} — volumes where save_on_stop=False"
                " do not feature snapshots to export from"
            )
        exported = self.exported_volume_name(get_random_string(8))
        dest_dset = Volume.make(exported)
        try:
            src = self.latest_clean_snapshot[0]
        except DatasetDoesNotExist:
            src = VolumeSnapshot.make(self.volume, self.latest_revision[0])
        self.log.debug(
            "Exporting %s via cloning from %s",
            dest_dset,
            src,
        )
        await self.pool.accessor.clone_snapshot_to_volume_async(
            src,
            dest_dset,
            NO_AUTO_SNAPSHOT,
            log=self.log,
        )
        return os.path.join(ZVOL_DIR, exported)

    async def export_end(self, path: str) -> None:
        """
        Removes the previous export.
        """
        self.log.debug(
            "End of export of %s to path %s",
            self.volume,
            path,
        )
        suffix = os.path.basename(path)
        # FIXME: if the last export of the volume is removed, then
        # the parent dataset ".exported" should be removed too.
        # This is not too urgent, as empty datasets are 40kb ea.
        # but their removal could help have a neater `zfs list`.
        await self._remove_volume_export_if_exists(suffix)

    def block_device(self) -> qubes.storage.BlockDevice:
        """Return :py:class:`qubes.storage.BlockDevice` for serialization in
        the libvirt XML template as <disk>.
        """
        return qubes.storage.BlockDevice(  # type: ignore
            os.path.join(
                ZVOL_DIR,
                self.volume,
            ),
            self.name,
            None,
            self.rw,
            self.domain,
            self.devtype,
        )

    @qubes.storage.Volume.locked  # type: ignore
    async def import_volume(
        self,
        src_volume: qubes.storage.Volume,
    ) -> "ZFSVolume":
        """
        Import a volume from another one.

        Calls `_wipe_and_clone_from()`.
        """
        if not self.save_on_stop:
            # Nothing to import.  This volume will be blown up
            # next time its owning VM starts up.
            return self
        self.log.debug(
            "Importing volume %s from source %s",
            self.volume,
            src_volume,
        )
        if not src_volume.save_on_stop:
            raise NotImplementedError(
                f"Cannot import from {self.vid} — volumes where"
                " save_on_stop=False cannot be exported for import"
            )

        if self.is_dirty():
            raise qubes.storage.StoragePoolException(
                f"Cannot import to dirty volume {self.volume} —"
                " start and stop its owning qube to clean it up"
            )
        self.abort_if_import_in_progress()
        await self._wipe_and_clone_from(src_volume)
        # Make clean snapshot so this volume can be cloned later.
        await self._create_revision("after-import-volume")
        await self._mark_clean()
        return self

    def abort_if_import_in_progress(self) -> None:
        """Abort if an import is in progress."""
        if self.pool.accessor.volume_exists(
            self.importing_volume_name,
            log=self.log,
        ):
            raise qubes.storage.StoragePoolException(
                "Import operation in progress on {}".format(self.volume)
            )

    @qubes.storage.Volume.locked  # type: ignore
    async def import_data(self, size: int) -> str:
        """
        Return a path name that can be `open()`ed.

        Callers generally write data to the object.
        """
        self.log.debug("Importing data of size %s into %s", size, self.volume)
        if self.is_dirty():
            raise qubes.storage.StoragePoolException(
                "Cannot import data to dirty volume {} -"
                " stop the qube using it first".format(self.volume)
            )
        self.abort_if_import_in_progress()
        imp = self.importing_volume_name
        self.log.debug("Creating volume for import %s with size %s", imp, size)
        await self.pool.accessor.create_volume_async(
            imp,
            size,
            self._auto_snapshot_policy,
            log=self.log,
        )
        return os.path.join(ZVOL_DIR, imp)

    @qubes.storage.Volume.locked  # type: ignore
    async def import_data_end(self, success: bool) -> None:
        """Either commit imported data, or discard temporary volume"""
        self.log.debug("End of importing data into %s", self.volume)
        if success:
            newvol = self.importing_volume_name
            self.log.debug("Adopting %s from %s", self.volume, newvol)
            await self._remove_volume_if_exists()
            await self.pool.accessor.rename_volume_async(
                newvol,
                self.volume,
                log=self.log,
            )
            # Make initial clean snapshot so this volume can be cloned later.
            await self._create_revision("after-import-data")
            await self._mark_clean()
        else:
            await self._remove_volume_import_if_exists()

    def is_dirty(self) -> bool:
        """
        Returns True if the volume is dirty (in use).

        If the machine crashes, it is plausible that some volumes
        may be dirty for an unspecified time until the VMs using
        those volumes successfully start then stop.
        """
        if self.save_on_stop:
            return self.pool.accessor.is_volume_dirty(
                self.volume,
                log=self.log,
            )
        return False

    @qubes.storage.Volume.locked  # type: ignore
    async def resize(self, size: int) -> None:
        """
        Expands volume.

        Throws
        :py:class:`qubst.storage.qubes.storage.StoragePoolException` if
        given size is less than current_size.
        """
        # FIXME: there does not seem to be a pathway to, but there
        # should be a pathway to, reducing the storage size of a
        # volume, whether it be by having to stop the VM first and
        # then making a non-atomic clone / partial copy / rename
        # of a zvol.  It is annoying that ZFS prevents volumes from
        # being reduced in size.  It is further annoying that
        # reduction of a volume requires the file system in it to
        # be reduced first, which can only be done while the qube
        # is running, but a Towers-of-Hanoi operation with datasets
        # can only be performed with the qube off.  Perhaps in the
        # future we can have a qvm feature exposed that allows dom0
        # to coordinate shrinking the file system and defers the
        # Towers-of-Hanoi operation to after the qube has powered off.
        self.log.debug("Resizing %s to %s", self.volume, size)
        mysize = self.size
        if size == mysize:
            return
        if size < mysize:
            raise qubes.storage.StoragePoolException(
                "Shrinking of ZFS volume %s is not possible" % (self.volume,)
            )
        if await self.pool.accessor.volume_exists_async(
            self.volume,
            log=self.log,
        ):
            # If the volume does not exist, we don't need to resize it.
            await self.pool.accessor.resize_volume_async(
                self.volume,
                size,
                log=self.log,
            )
        # Save the size of the volume so it is persisted in the
        # config, and the volume can be recreated at the configured
        # size if it is ever wiped/recreated.
        self._size = size

    def is_outdated(self) -> bool:
        """
        Returns whether the volume is outdated.

        Notes:

        * Volumes without snap_on_start can never be outdated.
        * Volumes without a source can never be outdated.
        * Nonexistent volumes cannot be outdated.
        * Otherwise, a volume is outdated if the snapshot it was cloned from,
          is older than the source's latest snapshot.

        In practical terms, a running VM's root file system is considered
        outdated when its source (the template's root file system), has been
        snapshotted anew, which in practice only happens when the template
        VM has been shut down.
        """
        if not self.snap_on_start:
            return False
        if not self.source:
            return False
        if not self.pool.accessor.volume_exists(self.volume, self.log):
            # Volumes that don't exist can't be outdated,
            # since they will be created on demand.
            return False
        if not isinstance(self.source, ZFSVolume):
            raise qubes.storage.StoragePoolException(
                "%s cannot be cloned by ZFSVolume" % self.source
            )

        try:
            _, last_source_rev_isodate = self.source.latest_clean_snapshot
        except DatasetDoesNotExist:
            _, last_source_rev_isodate = self.source.latest_revision

        this_volume_timestamp = self.pool.accessor.get_volume_creation(
            self.volume,
            log=self.log,
        )
        this_isodate = qubes.storage.isodate(
            this_volume_timestamp,
        )  # type: ignore
        return bool(last_source_rev_isodate > this_isodate)

    @property
    def latest_clean_snapshot(self) -> Tuple[VolumeSnapshot, str]:
        """
        Returns a tuple with the name of the latest clean snapshot,
        and its creation timestamp as an ISO date.

        Raises DatasetDoesNotExist if there is no clean snapshot.
        This should rarely be the case.
        """
        allclean = [
            (sninfo.name, sninfo.creation)
            for sninfo in self.pool.accessor.get_volume_snapshots(
                self.volume,
                log=self.log,
            )
            if sninfo.name.is_clean_snapshot()
        ]
        if not allclean:
            raise DatasetDoesNotExist(
                VolumeSnapshot.make(
                    self.volume,
                    CLEAN_SNAPSHOT,
                )
            )
        # The info comes pre-sorted oldest to newest.
        snap, tstamp = allclean[-1]
        return snap, qubes.storage.isodate(tstamp)

    @property
    def latest_revision(self) -> Tuple[str, str]:
        """
        Get the latest revision snapshot name and ISO date.

        If no revisions exist, raise `qubes.storage.StoragePoolException`.

        Invariant: all revisions are always clean.  All the code to create
        new volumes from other volmes and export existing volumes relies on
        this invariant.  The user can screw this up by using low-level zfs
        snapshot command that create snapshots named just right at the exact
        wrong times (e.g. a VM is running), but we do not expect them to do so,
        and if they do, it's their gun aimed at their feet — not ours.
        """
        revs = self.revisions
        if not revs:
            raise qubes.storage.StoragePoolException(
                "No revisions in %s" % self.volume,
            )
        return list(
            sorted(
                revs.items(),
                key=lambda m: m[1],
            )
        )[-1]

    @qubes.storage.Volume.locked  # type: ignore
    async def revert(self, revision: Optional[str] = None) -> "ZFSVolume":
        """
        Revert to a particular revision, or the most recent one
        if `revision` is None.
        """
        self.log.debug("revert %s to %s", self.volume, revision)
        if self.is_dirty():
            raise qubes.storage.StoragePoolException(
                "Cannot revert dirty volume {} -"
                " stop the qube first".format(
                    self.volume,
                )
            )
        self.abort_if_import_in_progress()
        snaps = self.revisions
        norevs = "Cannot revert volume %s with no revisions" % self.volume
        if not snaps:
            raise qubes.storage.StoragePoolException(norevs)
        if revision is None:
            snap, _ = self.latest_revision
        else:
            snap = revision
        snapobj = VolumeSnapshot.make(self.volume, snap)
        await self.pool.accessor.rollback_to_snapshot_async(
            snapobj,
            log=self.log,
        )
        if DELETE_REVISION_UPON_REVERT:
            await self.pool.accessor.remove_volume_async(
                snapobj,
                log=self.log,
            )
        await self._mark_clean()
        return self

    async def verify(self) -> bool:
        """Verifies the volume."""
        self.log.debug("verify %s", self.volume)
        if not self.snap_on_start and not self.save_on_stop:
            # Volatile.   start() creates it.
            return True
        if self.snap_on_start and not self.save_on_stop:
            # Root / reset-on-start.  start() creates it.
            return True
        if await self.pool.accessor.volume_exists_async(
            self.volume,
            log=self.log,
        ):
            return True
        raise qubes.storage.StoragePoolException(
            "volume {} missing".format(
                self.volume,
            )
        )
