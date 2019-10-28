#
# The Qubes OS Project, http://www.qubes-os.org
#
# Copyright (C) 2016 Bahtiar `kalkin-` Gadimov <bahtiar@gadimov.de>
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

# related documentation worth skimming if you are modifying this file:
#
# Documentation for the Qubes storage model:
# https://dev.qubes-os.org/projects/core-admin/en/latest/qubes-storage.html

# This is what we're trying to achieve:
# https://dev.qubes-os.org/projects/core-admin/en/latest/qubes-storage.html#storage-pool-driver-api
#
# Documentation for the pyzfs/liblzfs_core bindings to the ZFS api:
# https://pyzfs.readthedocs.io/en/latest/
#
# Source code for the lvm_thin driver upon which this module is based
# https://github.com/QubesOS/qubes-core-admin/blob/master/qubes/storage/lvm.py
#
# https://github.com/zfsonlinux/zfs/wiki/Custom-Packages#get-the-source-code
# https://www.qubes-os.org/doc/zfs/

# TODO f'' is not implemented in python3.5

# TODO libzfs_core.[lzc_list_snaps,lzc_list_children,lzc_get_props,
# lzc_inherit_prop]
# are dummy implementations that just throw exceptions
# (gee, thanks for exposing that)
# lzc_get_prop, lzc_set_prop not available in my version TODO
# can check this with:
# libzfs_core.is_supported(libzfs_core.lzc_inherit_prop) -> False
# TODO this is tracked here: https://github.com/zfsonlinux/zfs/issues/9008

## TODO checkpoints? lzc_pool_checkpoint
## TODO something should call lzc_sync(pool)

# TODO whenever we refer to /dev/zvol/ we should readlink()
# to make sure it refers to a /dev/zd-device to prevent just
#writing to the devtmpfs (why is that even writeable?)

""" Driver for storing VM images in a ZFS dataset for each VM
    containing a number of zvol.
"""

import functools
import logging
import os
import subprocess

import asyncio

import qubes
import qubes.storage
import qubes.utils

# exposed by zfsonlinux:
import libzfs_core

DEFAULT_ZVOL_PROPS = {
        # volmode governs whether stuff is available via /dev/zvol
    b"volmode": b"dev",
    b"volblocksize": 8192, # TODO set to max(4096, actual_block_dev_size)
    b'snapdev': 1,
    # TODO the lzc_create api has a problem with a lot of bytestrings
    # for some reason
    #
    # b"refreservation": b"auto"
}

DEFAULT_DATASET_PROPS = {
    b"mountpoint": b"none",
    b"compression": 1, # 1=on, 14=lze, 15=lz4
    b'snapdir': 1, # visible
    #   TODO let user use 14=lze (which just does sparse hole detection),
    b"atime": 0,
    b"exec": 0,
    b"setuid": 0,
    b"canmount": 0,
    # unconfirmed:
    # TODO b'reservation': reserve space for temp volumes
}

DEFAULT_SNAPSHOT_PROPS = {
    b'exec': 0,
    b'setuid': 0,
}

DEFAULT_ZPOOL_CMDLINE_OPTIONS = [
    # TODO allow options like this to be passed through from qvm-pool
    # TODO to see space actually allocated: zpool get -o free,allocated myzpool
    # mountpoint in dom0 fs:
    "-m", "none",
    "-o", "autotrim=on",
    # enable LZ4 compression:
    "-o", "feature@lz4_compress=enabled",
    # TODO I guess the user can set this manually at a later point
    #      if they want:
    # just in case the user wants to use encryption:
    # TODO move this to zfs_encrypted
    "-o", "feature@encryption=enabled",
    # TODO is this a good idea, allowing read-only on failure?
    "-o", "failmode=continue",
    # fast checksum algorithm alternative to sha256
    # note that this probably does not work with GRUB/zfsonroot:
    "-o", "feature@edonr=enabled",
    # TODO maybe -o listsnapshots=off
    # "-o", "feature@async_destroy=enabled"
    "-o", "feature@bookmarks=enabled",
    "-o", "feature@embedded_data=enabled",
    "-o", "feature@empty_bpobj=enabled",
    "-o", "feature@enabled_txg=enabled",
    # TODO snapdir=? for datasets,snapdev=?
    # maybe b'volblockmode' is also relevant
]

# TODO libzfs_core.lzc_snaprange_space
# Make sure we have a recent enough version of pyzfs etc to
# support what we need:
required_functionality = [
    libzfs_core.lzc_clone,
    libzfs_core.lzc_exists,
    # ^-- TODO documentation for this doesn't mention zpools, but it seems to
    # work for them.
    libzfs_core.lzc_create,
    libzfs_core.lzc_destroy,
    libzfs_core.lzc_hold,
    libzfs_core.lzc_unload_key,
]

for func in required_functionality:
    assert libzfs_core.is_supported(func)


def run_command(cmd, log=logging.getLogger("qubes.storage.zfs")):
    environ = os.environ.copy()
    environ["LC_ALL"] = "C.utf8"
    p = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        close_fds=True,
        env=environ,
    )
    out, err = p.communicate()
    return_code = p.returncode
    if return_code == 0 and err:
        log.warning(err)
    elif return_code != 0:
        raise qubes.storage.StoragePoolException(err)
    return out


class ZFSQpool(qubes.storage.Pool):
    """ ZFS zpool-based Pool implementation

    Volumes are stored as ZFS zvol volumes, in datasets specified by
    *zpool*/*dataset* arguments. ZFS zvol naming scheme:

        /{zpool}/vm/{vm_name}/{volume_name}/[suffix]

    Where suffix can be one of:
        "@snap" - snapshot for currently running VM, at VM shutdown will be
        either discarded (if save_on_stop=False), or committed
        (if save_on_stop=True)
        @revision "-{revision_id}" - volume revision - new revision is
                  automatically
        created at each VM shutdown, *revisions_to_keep* control how many
        old revisions (in addition to the current one) should be stored
        # TODO "/current":
        "" (no suffix) - the most recent committed volume state; also volatile
        volume (snap_on_start=False, save_on_stop=False)

    On VM startup, new volume is created, depending on volume type,
    according to the table below:

    snap_on_start, save_on_stop
    False,         False,        - no suffix, fresh empty volume
    False,         True,         - "-snap", snapshot of last committed revision
    True ,         False,        - "-snap", snapshot of last committed revision
                                   of source volume (from VM's template)
    True,          True,         - unsupported configuration

    Volume's revision_id format is "{timestamp}-back", where timestamp is in
    '%s' format (seconds since unix epoch)
    """  # pylint: disable=protected-access

    driver = "zfs_zvol"

    def _exists(self):
        if not libzfs_core.lzc_exists(self.zfs_ns.encode()):
            return False
        # TODO need to check that it is a zpool
        return True

    def __init__(self, name, block_devices=None, **kwargs):
        """Initializes a new zpool-backed ZFS pool.
           The 'block_devices' argument is mandatory, and accepts a list of
           colon-separated devices that will be ERASED AND RE-FORMATTED
           as ZFS vdevs when setup() is called.
        """
        self.name = name
        super().__init__(name)

        # avoid things that will come back to bite us:
        try:
            assert not name.startswith(
                "-"
            )  # zpool name cannot start with '-'
            assert name not in [
                "mirror",
                "raidz",
                "spare",
                "log",
            ]  #'zpool name clashes with reserved value'
            assert not sum([
                name.startswith(notok) for notok in ["mirror", "raidz", "spare"]
            ])
            # for zpools, the namespace is simply the name of the zpool:
            self.zfs_ns = name
            assert len(self.zfs_ns) < libzfs_core.MAXNAMELEN
            assert '/' not in self.zfs_ns
            # , "zpool name too long")
            if len(self.zfs_ns) == 2:
                # can't be regex: c[0-9]
                assert not (
                    self.zfs_ns.startswith("c")
                    and 0x30 <= ord(self.zfs_ns[1]) <= 0x39
                )
        except AssertionError:
            raise qubes.storage.StoragePoolException(
                "zfs - invalid zpool name"
            )

        self.block_devices = (block_devices or "").split(",")
        # TODO should tell the user that they should specify these as
        # LVM paths or by-uuid/ etc paths to prevent clashes.

        self.log = logging.getLogger(
            "qubes.storage.{}.{}".format(self.driver, self.zfs_ns)
        )

    def __repr__(self):
        return "<{} at {:#x} name={!r} zpool={!r} block_devices={!r}>".format(
            type(self).__name__,
            id(self),
            self.name,
            self.zfs_ns,
            self.block_devices,
        )

    def init_volume(self, vm, volume_config, zfs_ns=''):
        """ Initialize a :py:class:`qubes.storage.Volume` from `volume_config`.
        """
        self.log.warning("zfs init_volume() vm={} volume_config={}".format(
            vm, volume_config
        ))
        self.log.warning("zfs init_volume dir(vm): {}".format(dir(vm)))
        if vm and hasattr(vm, "name"):
            # TODO
            vm_name = vm.name
        if "vid" not in volume_config.keys():
            # if vid already exists then...
            if vm and hasattr(vm, "name"):
                vm_name = vm.name
            else:
                # for the future if we have volumes not belonging to a vm
                # TODO well then we should namespace that differently:
                vm_name = qubes.utils.random_string()
                raise qubes.storage.StoragePoolException(
                    "got a volume request from something that is not a VM"
                )

            assert vm_name

            volume_config["vm_name"] = vm_name

        if zfs_ns == '':
            zfs_ns = self.zfs_ns
        volume_config["zfs_ns"] = zfs_ns
        volume_config["pool_obj"] = self
        volume_config["pool"] = self
        volume_config["vm_name"] = vm_name
        volume = ZFSQzvol(log=self.log, **volume_config)
        return volume

    def destroy(self):
        self.log.warning(
            "zfs destroying zpool {}: maybe lzc_destroy() doesnt work \
            for pools".format(
                self.name
            )
        )
        try:
            libzfs_core.lzc_destroy(self.zfs_ns.encode())
            self.log.warning("zfs zpool - destroyed!")
        except libzfs_core.exceptions.ZFSGenericError as e:
            self.log.warning("zfs zpool tried (failed) to destroy: {!r}".format(
                e))
            raise qubes.storage.StoragePoolException(e)
        except libzfs_core.exceptions.FilesystemNotFound:
            pass
        except libzfs_core.exceptions.DatasetBusy:
            # TODO this exception is not documented in the api.
            self.log.warning("zfs zpool busy, can't destroy")
        if libzfs_core.lzc_exists(self.zfs_ns.encode()):
            self.log.warning(
                "zfs destroying zpool {}: lzc_destroy() did nothing".format(
                    self.name
                )
            )

    @asyncio.coroutine
    def setup(self):
        """Create a new zpool on the specified devices.
           By default it will also create a vm/ dataset as a namespace for
           virtual machine storage (in which the underlying zvols will be
           created).
        """

        if self._exists():
            raise qubes.storage.StoragePoolException(
                "setup() on already existing zpool"
            )
        if not isinstance(self.block_devices, list) \
           or self.block_devices == [] \
           or self.block_devices == ['']:
            raise qubes.storage.StoragePoolException(
                "ZFS pool: need at least one device to create zpool {}".format(
                    self.zfs_ns
                )
            )
        self.log.warning('zfs blockdevs {!r}'.format(self.block_devices))
        # and maybe letting user pass in options with zpool_atime=no etc?

        # TODO if any of this stuff fails we should likely revert the
        # whole thing to the previous state.

        # TODO at least use the qubes_cmd_coro() here
        # TODO get rid of sudo here if we can
        environ = os.environ.copy()
        environ["LC_ALL"] = "C.utf8"
        p = yield from asyncio.create_subprocess_exec(
            *[
                "sudo",
                "zpool",
                "create",
                *DEFAULT_ZPOOL_CMDLINE_OPTIONS,
                self.zfs_ns,
                *self.block_devices,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,  # todo capture stderr
            close_fds=True,
            env=environ,
        )
        _, err = yield from p.communicate()
        if p.returncode != 0:
            raise qubes.storage.StoragePoolException(
                "unable to create ZFS zpool:[{}] {}".format(p.returncode, err)
            )

        # Set up permissions for new zpool to avoid having to run other
        # commands as root. This allows some basic protection from programming
        # mistakes, since we can whitelist the operations that can be performed
        # without root privileges:

        # TODO should we attempt cleanup if any of this fails?

        p = yield from asyncio.create_subprocess_exec(
            *[
                "sudo",
                "zfs",
                "allow",
                "-ld",  # this zpool + its descendants
                "-g", # -g TODO
                "qubes",  # qubes gid / group TODO
                ("encryption,load-key,refreservation,create,destroy,mount,clone,snapshot,hold,"
                 "bookmark,send,diff,sync,volmode,rollback,receive,"
                 "volsize,volblocksize,volmode"
                ),
                self.zfs_ns,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            close_fds=True,
            env=environ,
        )
        _, err = yield from p.communicate()
        if p.returncode != 0:
            raise qubes.storage.StoragePoolException(
                "unable to set permissions for ZFS zpool: {}".format(err)
            )

        p = yield from asyncio.create_subprocess_exec(
            *[
                "sudo",
                "zfs",
                "allow",
                "-d",  # ONLY descendants (NOT this zpool itself)
                "-g",
                "qubes",  # qubes gid / group
                ("refreservation,volmode,destroy,rollback,receive,volsize,"
                 "devices,volblocksize,volmode,encryption"),
                self.zfs_ns,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            close_fds=True,
            env=environ,
        )
        _, err = yield from p.communicate()
        if p.returncode != 0:
            raise qubes.storage.StoragePoolException(
                "unable to set child permissions for ZFS zpool: {}".format(
                    err
                )
            )

        for namespace in [b"import", b"vm"]:
            try:
                #qubes_cmd_coro(["create", ])
                # TODO here we would like to set 'refreservation=auto'
                ds_name = b"/".join([self.zfs_ns.encode(), namespace])
                libzfs_core.lzc_create(
                    ds_name,
                    ds_type="zfs",
                    props=DEFAULT_DATASET_PROPS,
                )
            except libzfs_core.exceptions.FilesystemExists:
                raise qubes.storage.StoragePoolException(
                    "ZFS dataset for {}/{} already exists".format(
                        self.name, namespace
                    )
                )
            except libzfs_core.exceptions.ZFSError as e:
                raise qubes.storage.StoragePoolException(
                    "ZFS dataset {}/{} could not be created: {!r}".format(
                        self.name, namespace.encode(), e)
                )
        # zpool created successfully

    @property
    def config(self):
        return {
            "name": self.name,
            "zfs_ns": self.zfs_ns,
            "driver": ZFSQpool.driver,
            # block_devices intentionally left out. this info can be pulled
            # via zfs if necessary, and we do NOT want to risk accidentally
            # reformatting them upon reinstantiation, ever.
        }

    @property
    def size(self):
        # Storage pool size in bytes
        # TODO should we return FREE + ALLOC instead, does Qubes try to
        # infer that?
        i = run_command(
            [
                "zpool",
                "list",
                "-Hp",
                "-o",
                "size",
                self.zfs_ns,
            ])
        return int(i)

    @property
    def usage(self):
        # Space used in the pool in bytes
        i = run_command(
            [
                "zpool",
                "list",
                "-Hp",
                "-o",
                "allocated",
                self.zfs_ns
            ]
        )
        return int(i)


def locked(method):
    """Decorator running given Volume's coroutine under a lock.
    Needs to be added after wrapping with @asyncio.coroutine, for example:

    >>>@locked
    >>>@asyncio.coroutine
    >>>def start(self):
    >>>    pass
    """

    @asyncio.coroutine
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        with (yield from self._lock):  # pylint: disable=protected-access
            return (yield from method(self, *args, **kwargs))

    return wrapper


class ZFSQzvol(qubes.storage.Volume):
    """ ZFS zvol-based Volume implementation.

        - self.vid - comes from Pool.init_volume() and is a full path
        to a ZFS zvol, meaning that /dev/zvol/{self.vid} is a valid path.
          It has this structure: {zpool}/vm/{vm_name}/{name}
          - {zpool} is the zpool backing the ZFSQpool
          - 'vm' is a dataset, using a fixed string to provide namespacing
          - {vm_name} is a dataset specific to the VM
          - {name} is either 'snap', 'current', 'import',
            or a previous snapshot (revision). is always unique.

        :ivar self.zfs_ns: {zpool} name
        self.vm_name: name of vm whose storage this volume belongs to
        self.name: str(name) of volume it belongs to, like 'root' or 'private'
    """  # pylint: disable=too-few-public-methods

    # TODO revisions: zfs get snapshot_count

    def __init__(self, zfs_ns, vm_name, pool, name, size=0,
                 rw=False, **kwargs):
        """must have no permanent effect, called each time management stack
           is brought online.
           :param zfs_ns: For unencrypted volumes, this is the name
                           of the zpool.
                          For encrypted volumes, this will be
                            (zpool)/encryption/(encpool)
                          This may be extended by classes inheriting from
                           this one, but MUST NOT be shrunk.
           :type zfs_ns: str
           :param vm_name: The name of the VM this volume belongs to.
           :param name: The name of the volume, for example
                        'private' or 'volatile'
           :param size: The size (in bytes) the qubesd believes this
                         volume should have.
                        Before create() has been called, this directs us to
                        create a zvol of that size.
                        If instead we are initializing an existing zvol,
                        this may be incorrect and should probably be checked.
                        TODO.
        """

        self.vm_name = vm_name
        self.name = name
        assert self.name
        self.pool = pool # <- ref to parent ZFSQpool
        self.log = logging.getLogger(
            "qubes.storage.zfs.ZFSQzvol.{}".format(zfs_ns))
        self.log.warning('ZFSQzvol kwargs {}'.format(kwargs))
        self.zfs_ns = zfs_ns # prefix to use before anything
        assert self.zfs_ns
        if self.zfs_ns.startswith("-"):
            raise qubes.storage.StoragePoolException(
                "Invalid zfs_ns; prefixed with '-'")

        # TODO verify/update this by retrieving ?
        # if lzc_exists(whatever):
        #   self._size = lzc_get_props(whatever, "volsize")
        self._size = size

        self.vid = "/".join([self.zfs_ns,
                             "vm",
                             self.vm_name,
                             self.name])
        self.import_path = b"/".join([self.zfs_ns.encode(), b"import",
                                      self.vm_name.encode()])
        self._vid_import = b"/".join([self.import_path, self.name.encode()])

        self.save_on_stop = False
        self.snap_on_start = False
        self.rw = rw
        super().__init__(name=self.name,
                         pool=self.pool,
                         vid=self.vid,
                         rw=self.rw,
                         size=self._size)

        self.log.warning("dataset_path assert {!r} {!r} {!r}".format(self.zfs_ns, b"vm", self.vm_name))
        self.dataset_path = b"/".join(
            [
                self.zfs_ns.encode(),
                b"vm",
                self.vm_name.encode(),
            ]
        )
        # sanity check:
        assert self.dataset_path + b"/" + self.name.encode() == self.vid.encode()
        self._vid_snap = self.vid.encode() + b"@latest"


        if self.save_on_stop:
            raise qubes.storage.StoragePoolException(
                "TODO save_on_stop not supported"
            )

        self._size = size
        self._lock = asyncio.Lock()

    @locked
    @asyncio.coroutine
    def create(self):
        assert self.vid
        assert self.size

        self.log.warning("zfs_zvol:create() vid {}".format(self.vid))

        # if vm-specific datasets doesn't exist, create them:
        for namespace in [self.import_path, self.dataset_path]:
            try:
                make_dataset = not libzfs_core.lzc_exists(namespace)
            except libzfs_core.exceptions.ParentNotFound:
                make_dataset = True
            finally:
                if make_dataset:
                    self.log.warning(
                        "zfs - creating namespace dataset {}".format(
                            namespace
                        )
                    )
                    libzfs_core.lzc_create(
                        namespace,
                        ds_type="zfs",
                        props=DEFAULT_DATASET_PROPS,
                    )

        if libzfs_core.lzc_exists(self.vid.encode()):
            raise qubes.storage.StoragePoolException(
                "zfs - trying to create already existing zvol {}".format(
                    self.vid
                )
            )

        if self.source:
            # we're supposed to clone from this, maybe.
            self.log.warning("zfs volume.create(): there is a .source!")
        # TODO probably want lzc_clone in some cases.

        #i_totally_know_python = DEFAULT_ZVOL_PROPS.copy()
        i_totally_know_python = {}
        i_totally_know_python[b"volsize"] = self.size
        self.log.warning('ZFS: {!r}({}) zvol opts: {}'.format(
            self.vid, self.vid.encode().hex(), i_totally_know_python))
        libzfs_core.lzc_create(
            self.vid.encode(),
            ds_type="zvol",
            props=i_totally_know_python
        )

        return self

    @property
    def revisions(self):
        # TODO here we should likely list either @snap or @revision
        # or something like that
        return []

    @property
    def size(self):
        return self._size

    @size.setter
    def size(self, _):
        raise qubes.storage.StoragePoolException(
            "You shouldn't use zfs size setter"
        )

    @locked
    @asyncio.coroutine
    def remove(self):
        # all this will likely not work since there will be snapshots
        # blocking deletion since we are not destroyin recursively.
        # zfs destroy -r is the way to. TODO
        self.log.warning(
            "zfs - remove() of {} is not fully implemented yet, \
            you will still have a bunch of snapshots and stuff \
            lying around.".format(self.vid))
        # TODO should signal ZFSQpool to that the vm/{self.vm_name} dataset can
        # be cleaned up.
        assert self.vid
        if libzfs_core.lzc_exists(self._vid_snap):
            self.log.warning("zfs volume destroying self._vid_snap")
            libzfs_core.lzc_destroy(self._vid_snap)
        if libzfs_core.lzc_exists(self._vid_import):
            libzfs_core.lzc_destroy(self._vid_import)
        if libzfs_core.lzc_exists(self.vid.encode()):
            libzfs_core.lzc_destroy(self.vid.encode())

    def export(self):
        """ Returns a path to the volume that can be `open()`.
            The API explicitly details that is is for READ operations,
            but we cannot guarantee that without giving path to a snapshot.
            Unfortunately the API does not prescribe a method for the caller
            to tell us that they are done using this.
            (which in the LVM case would allow lvm to `deactivate`, and in our
            case: kill said snapshot.
        """
        # TODO Reading from this path when domain owning this volume is running
        # (i.e. when is_dirty() is True) should return the data from
        # before domain startup.
        # Reading from the path returned by this method should return the
        # volume data. If extracting volume data require something more than
        # just reading from file (for example connecting to some other domain,
        # or decompressing the data), the returned path may be a pipe.
        assert self.snap_on_start
        devpath = "/dev/zvol/" + self.vid

        # Return open fd instead of getting into race conditions with
        # udevd and whathaveyou. The docs say we should return a pipe,
        # but we return a regular fd instead, hoping that is good enough.
        # TODO is it important that this be a pipe?
        try:
            if "/zd" in os.readlink(devpath):
                return devpath
        except:
            # if readlink failed
            pass
        finally:
            raise qubes.storage.StoragePoolException(
                "ZFSQzvol: export(): devpath {!r} does not \
                point to a zfs device".format(devpath)
            )

    @locked
    @asyncio.coroutine
    def import_volume(self, src_volume):
        raise qubes.storage.StoragePoolException(
            "TODO zfs import_volume() nfc what semantics of this is"
        )
        if not src_volume.save_on_stop:
            return self

        # there's some intricate dance of
        # zfs clone
        # zfs promote
        # zfs remove
        # we can do here to do this efficiently.
        # alternatively we can fallback to some sort of dd thing.

        # if self.is_dirty():
        #    raise qubes.storage.StoragePoolException(
        #        "Cannot import to dirty volume {} -"
        #        " start and stop a qube to cleanup".format(self.vid)
        #    )
        # self.abort_if_import_in_progress()
        # return self

    @locked
    @asyncio.coroutine
    def import_data(self):
        """ Returns an object that can be `open()`. """
        self.log.warning("zfs import_data not oding anything")
        if self.is_dirty():
            raise qubes.storage.StoragePoolException(
                "Cannot import data to dirty volume {}, \
                stop the qube first".format(self.vid)
            )
        self.abort_if_import_in_progress()
        raise NotImplementedError("zfs import_data() not implemented")
        # TODO this whole section is a TODO.
        # The other targets use dd conv=sparse to prevent writing zeroes
        #  instead of sparse holes.
        # ZFS will detect nulls when using compression=zle or compression=lz4
        #  (which we use), so we skip `dd` here.
        # Deliberately not using buffered I/O here because we
        # are going to use sendfile to avoid copying forth and back
        # between kernel and userspace like we would have done if
        # we were to use `dd` - unfortunately that means we have to take
        # care of fd cleanup and failure modes on our own:
        # TODO these are relevant for making things go faster, eventually:
        # https://www.quora.com/What-is-the-main-difference-between-copy_file_range-and-sendfile-system-calls-in-Linux?share=1
        # https://github.com/zfsonlinux/zfs/issues/4237
        import os
        try:
            indev = os.open(
                self.source.path,
                os.O_RDONLY | os.O_CLOEXEC | os.O_LARGEFILE | os.O_NOATIME)
        except os.OSError as e:
            raise qubes.storage.StoragePoolException(
                "zfs import_data(): open path {} for copy to {}: {}".format(
                    self.source.path, self._vid_import, e.strerror
                ))
        try:
            outdev = os.open("/dev/zvol/" + self._vid_import,
                             os.O_WRONLY | os.O_CLOEXEC | os.O_LARGEFILE)
            os.fstat(outdev)
            # TODO ensure we are writing to a block device.
            # should be fine since we didn't pass O_CREAT ?
        except os.OSError as e:
            os.close(indev)
            raise qubes.storage.StoragePoolException(
                "zfs import_data(): open {} for writing: {}".format(
                    self._vid_import, e.strerror
                ))

        # TODO amountofbytes = os.fstat(indev).something
        remaining = 10
        try:
            while remaining != 0:
                written = os.sendfile(outdev, indev, offset=0,
                                      count=remaining)
                assert written != -1 # python should raise
                if written == 0:
                    break
                remaining -= written
                # TODO yield?
        except os.OSError as e:
            os.close(outdev)
            os.close(indev)
            raise qubes.storage.StoragePoolException(
                "zfs failed to import from path {} to zvol {}: {}".format(
                    self.source.path, self._vid_import, e.strerror
                )
            )
        os.fsync(outdev)
        os.close(outdev)
        os.close(indev)
        self.log.warning('zfs wrote {}/{} bytes to {} from {}'.format(
            "TODO", 0, self.source.path, self._vid_import
        ))
        # cmd = [
        #    "create",
        #    self.pool._pool_id,
        #    self._vid_import.split("/")[1],
        #    str(self.size),
        # ]
        # yield from qubes_cmd_coro(cmd, self.log)
        # devpath = "/dev/" + self._vid_import
        # return devpath

    @locked
    @asyncio.coroutine
    def import_data_end(self, success):
        """Either commit imported data, or discard temporary volume"""
        if not libzfs_core.lzc_exists(self._vid_import):
            raise qubes.storage.StoragePoolException(
                "No import operation in progress on {}".format(self.vid)
            )
        if success:
            # yield from self._commit(self._vid_import)
            self.log.warning("import_data_end success, what to do")
            pass
        else:
            cmd = ["remove", self._vid_import]
            yield from qubes_cmd_coro(cmd, self.log)

    @locked
    @asyncio.coroutine
    def abort_if_import_in_progress(self):
        devpath = "/dev/zvol/" + self._vid_import
        # TODO race condition ... need a lock here.
        if libzfs_core.lzc_exists(self._vid_import.encode()):
            raise qubes.storage.StoragePoolException(
                "Import operation in progress on {}".format(self.vid)
            )

    def is_dirty(self):
        if self.save_on_stop:
            raise qubes.storage.StoragePoolException(
                "zfs save_on_stop semantics not supported TODO")
            return libzfs_core.lzc_exists(self._vid_snap)
        self.log.warning("ZFSQzvol: is_dirty(): is it? i have no idea TODO")
        return libzfs_core.lzc_exists(self._vid_import)

    def is_outdated(self):
        self.log.warning(
            "ZFSQzvol:is_outdated(): it is never outdated atm TODO")
        if not self.snap_on_start:
            return False
        return False  # TODO
        # return (size_cache[self._vid_snap]['origin'] !=
        #    self.source.path.split('/')[-1])

    @locked
    @asyncio.coroutine
    def revert(self, revision=None):
        # basically we would want 'zfs rollback' here
        if self.is_dirty():
            raise qubes.storage.StoragePoolException(
                "Cannot revert dirty volume {}, stop the qube first".format(
                    self.vid
                )
            )
        self.abort_if_import_in_progress()
        if revision is None:
            # TODO find latest snapshot
            # revision = max(self.revisions.items(), key=_revision_sort_key)[0]
            pass
        raise NotImplementedError(
            "ZFSQzvol.revert(revision={}) on {} TODO".format(revision, self.vid)
        )
        # return self

    @locked
    @asyncio.coroutine
    def resize(self, size):
        """ Expands volume, throws
            :py:class:`qubst.storage.qubes.storage.StoragePoolException` if
            given size is less than current_size
        """
        if not self.rw:
            msg = "Can not resize reađonly volume {!s}".format(self)
            raise qubes.storage.StoragePoolException(msg)

        if size < self.size:
            raise qubes.storage.StoragePoolException(
                "For your own safety, shrinking of %s is"
                " disabled (%d < %d). If you really know what you"
                " are doing, use `zfs -o volsize` on %s manually."
                % (self.name, size, self.size, self.vid)
            )

        if size == self.size:
            return

        # TODO for zfs zvol resizing to be valid, it must be a multiple
        # of the current blocksize. we currently don't enforce that,
        # but the qubes manager specifies increments of 1MB, so that works
        # out for us. if in the future some other API frontend wil lbe used,
        # we should probably verify that it is.

        self.log.warning(
            "ZFSQzvol:resize() oh you must be pretty brave. well ok, \
            yolo. TODO resizing from {} to {} (diff {})".format(
                self.size, size, size-self.size
            )
        )
        # TODO what does dirty mean
        if self.is_dirty():
            cmd = ["resize", self.vid, size]
            yield from qubes_cmd_coro(cmd, self.log)
            # Update our understanding of the size,
            # so that we can warn about decreasing it in the future.
            # TODO we should probably detect the new real size instead
            # of just relying on our estimate being accurate.
            self._size = size # TODO
        #elif hasattr(self, "_vid_import") and libzfs_core.lzc_exists(
        #    self._vid_import
        #):
        #    cmd = ["resize", self._vid_import.decode(), size]
        #    yield from qubes_cmd_coro(cmd, self.log)
        #

    @asyncio.coroutine
    def _snapshot(self):
        if self.source:
            self.log.warning(
                "zfs.volume._snapshot() with .source, should probably \
                snapshot source.path={!r} instead of {!r}".format(
                    self.source.path, self.vid))

        from time import strftime
        now = strftime('%Y-%m-%d.%H:%M:%S.%Z').encode()
        try:
            # take two snapshots, one with timestamp and one
            # called 'latest'.
            # TODO consider using monotonic time?
            try:
                libzfs_core.lzc_destroy(self._vid_snap)
            except libzfs_core.extentions.ZFSError:
                # if that failed then 'latest' won't be latest anymore.
                self.log.warning(
                    'zfs snapshotting, TODO, unable to \
                    remove self._vid_snap before creating new, \
                    how to handle this?')
            libzfs_core.lzc_snapshot(
                [
                    self.vid.encode() + b'@' + now,
                    self._vid_snap,
                ],
                props=DEFAULT_SNAPSHOT_PROPS,
            )
        except libzfs_core.extensions.SnapshotFailure as e:
            self.log.warning(
                'zfs volume {!r}: unable to create snapshots: {}'.format(
                self.vid, e.errors
            ))

    @locked
    @asyncio.coroutine
    def start(self):
        self.log.warning("zfs ZFSQzvol start {}".format(self.name))
        self.abort_if_import_in_progress()
        if self.snap_on_start:
            yield from self._snapshot()
            #or self.save_on_stop:
            #if not self.save_on_stop or not self.is_dirty():
                #yield from self._snapshot()
            #    pass
        else:
            # yield from self._reset()
            # TODO rollback I guess?
            pass
        return self

    @locked
    @asyncio.coroutine
    def stop(self):
        try:
            if self.save_on_stop:
                pass
            if self.snap_on_start and not self.save_on_stop:
                # cmd = ['remove', self._vid_snap]
                # yield from qubes_cmd_coro(cmd, self.log)
                pass
            elif not self.snap_on_start and not self.save_on_stop:
                # cmd = ['remove', self.vid]
                # yield from qubes_cmd_coro(cmd, self.log)
                pass
        finally:
            pass
        return self

    def verify(self):
        """ Verifies the volume. """
        if not self.save_on_stop and not self.snap_on_start:
            # volatile volumes don't need any files
            return True
        if self.source is not None:
            vid = self.source.path
        else:
            vid = self.vid
        try:
            # TODO check zfs health
            pass
        except KeyError:
            raise qubes.storage.StoragePoolException(
                "volume {} missing".format(vid)
            )
        return True

    def block_device(self):
        """ Return :py:class:`qubes.storage.BlockDevice` for serialization in
            the libvirt XML template as <disk>.
        """
        if self.snap_on_start or self.save_on_stop:
            # TODO what are we trying to do here, remnants of LVM?
            return qubes.storage.BlockDevice(
                "/dev/zvol/" + self._vid_snap,
                self.name,
                self.script,
                False, # vid snap is always read-only
                self.domain,
                self.devtype,
            )

        self.path = ''.join(['/dev/zvol/', self.vid])
        # verify that it is a ZFS device:
        assert 'zd' in os.readlink(self.path)
        self.devtype = 'disk'
        return super().block_device()

    @property
    def usage(self):
        # "zfs", "get", "used", "self.vid"
        return 0  # TODO


def _get_zfs_cmdline(cmd):
    """ Build command line for :program:`zfs` call.
    The purpose of this function is to keep all the detailed zfs options in
    one place.

    :param cmd: array of str, where cmd[0] is action and the rest are arguments
    :return array of str appropriate for subprocess.Popen
    """
    action = cmd[0]
    if action == "remove":
        # ZFS TODO
        # do we get the poolname here or what?
        # TODO there's defer_destroy / -d
        libzfs_core.lzc_destroy(cmd[1])
        return None
    elif action == "create":
        # libzfs_core.lzc_create seems broken, ideally we would
        # be able to pass in properties at creation time, but
        # that doesn't seem to be the case.
        # Instead we use call out to `zfs create`:
        name = cmd[1]

        # options are passed to us in the format:
        #   ["compression=lze", "autotrim=on"]
        options = []
        for kvopt in cmd[2]:
            options.extend(["-o", kvopt])

        return ["zfs", "create",
                *options,
                name]
    elif action == "clone":
        origin = cmd[1]  # source zvol
        name = cmd[2]  # name of new zvol
        libzfs_core.lzc_clone(name, origin, ds_type="zvol")
        return None
    elif action == "resize":
        log = logging.getLogger("qubes.storage.zfs.resize")
        log.warning("zfs volume resize: rw={} {}".format(
            None, cmd)) # TODO self.rw here
        name = cmd[1].encode()
        if not isinstance(cmd[2], int):
            raise qubes.storage.StoragePoolException(
                'resize size is for some reason not an integer. \
                bailing out. TODO')
        size = cmd[2]
        # zfs parent dataset: libzfs_core.lzc_set_prop(name, b'quota', size)
        try:
            libzfs_core.lzc_set_props(name, b"volsize", size)
            libzfs_core.lzc_set_props(name, b"refreservation", b"auto")
        except libzfs_core.exceptions.ZFSError as e:
            log.warning("library call failed: {}".format(e))
        except NotImplementedError:
            # since this function is not implemented (yet), we fall back
            # to using the CLI utility:
            # TODO set refreservation= too?
            return ["zfs", "set",
                    "refreservation=auto",
                    "volsize={}".format(size),
                    name]
        return None
    elif action == "activate":
        # lvm_cmd = ['lvchange', '-ay', cmd[1]]
        return None
    elif action == "rename":  # ZFS DONE
        old_name = cmd[1]
        new_name = cmd[2]
        libzfs_core.lzc_rename(source=new_name, target=old_name)
        return None
    else:
        raise NotImplementedError("unsupported action: " + action)


def _process_zfs_output(returncode, stdout, stderr, log):
    """Process output of ZFS, determine if the call was successful and
    possibly log warnings."""
    # Filter out warning about intended over-provisioning.
    # Upstream discussion about missing option to silence it:
    # https://bugzilla.redhat.com/1347008
    err = "\n".join(
        line
        for line in stderr.decode().splitlines()
        if "exceeds the size of thin pool" not in line
    )
    if stdout:
        log.debug(stdout)
    if returncode == 0 and err:
        log.warning(err)
    elif returncode != 0:
        assert (
            err
        ), "Command exited unsuccessful, but printed nothing to stderr"
        err = err.replace("%", "%%")
        raise qubes.storage.StoragePoolException(err)
    return True


@asyncio.coroutine
def qubes_cmd_coro(cmd, log=logging.getLogger("qubes.storage.zfs_zvol")):
    """ Call :program:`zfs` to execute a ZFS operation

    Coroutine version."""
    environ = os.environ.copy()
    environ["LC_ALL"] = "C.utf8"
    if cmd[0] == "remove":
        # https://github.com/zfsonlinux/zfs/commit/fa56567630cfad95b77dee507595d77f24e99cb9
        # could also consider followig up with a 'zfs trim' maybe...
        pre_cmd = ["blkdiscard", "/dev/zvol/" + cmd[1]]
        p = yield from asyncio.create_subprocess_exec(
            *pre_cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            env=environ
        )
        _, _ = yield from p.communicate()

    def library_call_failed(exc=None):
        msg = "ZFS library call failed without error handling: {}".format(exc)
        log.warning(msg)
        raise qubes.storage.StoragePoolException(msg)

    try:
        cmd = _get_zfs_cmdline(cmd)
    except libzfs_core.exceptions.ZFSError as e:
        # TODO list specific exceptions
        library_call_failed(e)
    if isinstance(cmd, bool):
        # we don't need to run a command.
        if not cmd:
            library_call_failed()
        return True
    if not isinstance(cmd, list):
        # if it's not a boolean either, something went wrong
        # and _get_zfs_cmdline accidentally returned incorrectly:
        library_call_failed()
    p = yield from asyncio.create_subprocess_exec(
        *cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        close_fds=True,
        env=environ
    )
    out, err = yield from p.communicate()
    return _process_zfs_output(p.returncode, out, err, log)
