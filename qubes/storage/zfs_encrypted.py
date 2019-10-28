"""
Pool backed by encrypted ZFS zvols on top of an existing zfs_zvol pool.

For a breakdown of how the encryption scheme works, see:
  https://blog.heckel.io/2017/01/08/zfs-encryption-openzfs-zfs-on-linux/
"""

import asyncio
import libzfs_core
import logging
import os
import subprocess
import time
import qubes
import qubes.storage
import qubes.storage.zfs as qzfs

# TODO something that checks the unload_timeout

import functools
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
        # not that we use '_zfs_enc_lock' here and not '_lock' to prevent
        # clashing with inherited locks from the parent.
        if not hasattr(self, '_zfs_enc_lock'):
            self._zfs_enc_lock = asyncio.Lock()
        with (yield from self._zfs_enc_lock):  # pylint: disable=protected-access
            return (yield from method(self, *args, **kwargs))

    return wrapper


class ZFSQEncryptedPool(qubes.storage.Pool):
    """ZFS pool for encrypted datasets inside an existing
       ZFSQpool(a.k.a. zfs_zvol)
    """

    driver = "zfs_encrypted"

    app_reference = None

    def __repr__(self):
        return "<{} at {:#x} name={!r} underlying={!r}>".format(
            type(self).__name__,
            id(self),
            self.name,
            self.zpool_name
        )

    async def _ask_password(self, receiving_cmd):
        """
        Call out to QRexec qubes.AskPassword and passes the resulting stdout
        to :receiving_cmd: when successful.
        """
        if not self.app_reference:
            # TODO this sucks, is there an easier way to get a reference to the
            # global 'app' qubes.Qubes() instance?
            self.app_reference = qubes.Qubes()
        pw_vm = self.app_reference.domains[self.ask_password_domain]
        if not pw_vm:
            raise qubes.storage.StoragePoolException(
                "unable to find handle for ask_password_domain={}".format(
                    self.ask_password_domain
                )
            )
        pw_pipe_in, pw_pipe_out = os.pipe()
        try:
            # TODO how do we pass $1 to this stuff? we can pass **kwargs to
            # asyncio.create_subprocess_exec, but we can't influence command
            await pw_vm.run_service_for_stdio(
                'qubes.AskPassword',
                autostart=True, gui=True,
                user='user',
                input=self.name.encode()+b'\n', # context for the prompt
                stdout=pw_pipe_out)
        except subprocess.CalledProcessError as e:
            # TODO os.close(pw_pipe_in pw_pipe_out)
            os.close(pw_pipe_in)
            os.close(pw_pipe_out)
            self.log.warning(
                "zfs ask_password: exception while trying to get pw: {}".format(
                    e
                )
            )
            raise e
        environ = os.environ.copy()
        environ["LC_ALL"] = "C.utf8"
        p = await asyncio.create_subprocess_exec(
            *receiving_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=pw_pipe_in,
            close_fds=True,
            env=environ
        )
        zfsout, zfserr = await p.communicate()
        self.log.warning("ZFS key consumer: ".format(
            p.returncode, zfsout, zfserr))
        os.close(pw_pipe_in)
        os.close(pw_pipe_out)
        # TODO make sure zfs get keystat foo == 'available'
        #      and zfs get encryptionroot foo == foo
        return (p, zfsout, zfserr)

    async def ask_password(self, receiving_cmd, retries=5):
        """
        Wrapper around self._ask_password which retries a number of times
        """
        attempts = retries + 1
        for attempt in range(1, 1 + attempts):
            try:
                self.log.warning('attempting to ask for pw: {}'.format(
                    receiving_cmd))
                (p, stdout, stderr) = await self._ask_password(receiving_cmd)
                if p.returncode != 0:
                    raise Exception(stderr)
                return (p, stdout, stderr)
            except Exception as e:
                self.log.warning(
                    "zfs ask_password failed, attempt {}/{}: {}".format(
                        attempt, attempts, e))
                if attempt == attempts:
                    # out of retries:
                    raise e

    def __init__(self, name, zpool_name, ask_password_domain='dom0',
                 unload_timeout=1200, **kwargs):
        """
        Initializes a new encrypted pool. The pool will timeout after
        :param zfs_parent: Name of existing zfs_zvol or zfs_encrypted pool
        :type zfs_parent: str

        :param ask_password_domain: Domain to direct QRexec qubes.AskPassword
                                    calls to for retrieving the encryption
                                    passphrase.
        :type ask_password_domain: str

        :param unload_timeout: The number of seconds after which the key
                               protecting this pool will be unloaded when there
                               are no more volumes in use.
        :type unload_timeout: str

        :param `**kwargs`: Passed to the underlying :class:`qzfs.ZFSQpool`

        :raises :class:`qubes.storage.StoragePoolException`:
        ask_password_domain is invalid

        :raises :class:`qubes.storage.StoragePoolException`:
        Supposed parent pool doesn't exist

        TODO is initialization order guaranteed by included_in(), e.g. can we
        be sure the underlying zpool will always be initialized by the time
        we get called ?
        """
        self.name = name
        self.pool = self
        self.log = logging.getLogger("qubes.storage.{}.{}".format(
            self.driver, self.name))

        self.unload_timeout = int(unload_timeout)
        assert self.unload_timeout >= 0

        self.ask_password_domain = ask_password_domain
        if self.ask_password_domain == '':
            raise qubes.storage.StoragePoolException(
                "ask_password_domain is empty"
            )

        self.zpool_name = zpool_name

        # TODO look up pool in qubes.app
        #self.underlying = qubes.app.get(zfs_parent, None)
        #if not self.underlying:
        #    raise qubes.storage.StoragePoolException(
        #        "zfs_encrypted: unable to look up parent qvm-pool {}".format(
        #            zfs_parent
        #        )
        #    )
        # TODO validate name
        if not libzfs_core.lzc_exists(self.zpool_name.encode()):
            raise qubes.storage.StoragePoolException(
                "zfs_encrypted: underlying namespace {!r} does \
                not exist".format(self.zpool_name))


        # Here we configure the prefixes for the datasets we will be making.
        # We get a parent namespace from the underlying, and add to it like:
        # {underlying ns}/encryption/{this pool name}/
        self.name = name
        self.encryption_ns = b"/".join([self.zpool_name.encode(),
                                        b"encryption"])
        # zfs_ns must be a string:
        self.zfs_ns = "/".join([self.encryption_ns.decode(), self.name])
        # Keep this around to make sure something doesn't overwrite it:
        self.zfs_ns_safety_valve = self.zfs_ns.encode()

        # Track which volumes are in use, and when the set of
        # used volumes was last modified.
        # (The idea being that we can unload-key the encryption key
        #  when the encrypted pool has been unused for some time):
        self.used_volumes = set()
        self.used_volumes_last_empty = time.clock_gettime(
            time.CLOCK_MONOTONIC_RAW)
        self._await_timeout_instance = asyncio.get_event_loop().create_task(
            self.await_timeout()
        )

    async def await_timeout(self):
        """
        This runs as an (eternal) background task that will periodically
        wake up and check if we should attempt to unload the encryption keys
        for this encrypted pool.
        """
        # at initialization time, we can always wait at least one period:
        self.log.warning(
            "await_timeout is locked and loaded. unload_timeout={}".format(
                self.unload_timeout
            )
        )
        countdown = self.unload_timeout
        while True:
            self.log.warning(
                "going to await_timeout, sleep {} sec".format(countdown))
            await asyncio.sleep(countdown)
            now = time.clock_gettime(time.CLOCK_MONOTONIC_RAW)
            elapsed = now - self.used_volumes_last_empty
            if self.unload_timeout > 0:
                countdown = self.unload_timeout - elapsed
            else:
                # When no timeout is configured, we keep this task alive in case
                # the user decides to change their timeout settings.
                # we look for new settings every so often:
                countdown = 60
                # action kicks in when timeout is reached:
            if countdown < 1:
                # reset countdown:
                countdown = self.unload_timeout
                if not self.used_volumes:
                    self.log.warning(
                        'should zfs unload-key {} unless we are already \
                        unloaded'.format(self.zfs_ns))
                    try:
                        libzfs_core.lzc_unload_key(self.zfs_ns.encode())
                        self.log.warning("UNLOADED key for {}.".format(
                            self.zfs_ns))
                    except libzfs_core.exceptions.EncryptionKeyNotLoaded:
                        pass
                    except libzfs_core.exceptions.ZFSError as e:
                        self.log.warning(
                            "key unloading failed for {}: {}".format(
                                self.zfs_ns, e
                            )
                        )
                        # try again:
                        countdown = 10

    async def ensure_key_is_loaded(self):
        keystatus = qzfs.run_command(
            ["zfs", "list", "-H",
             "-o", 'keystatus', self.zfs_ns]
        )
        self.log.warning("track volume start keystatus {}".format(keystatus))
        if keystatus.strip() == b'unavailable':
            await self.ask_password(["zfs", "load-key", self.zfs_ns])
            # TODO ideally I guess here we would wait for udevd to kick in...
            await asyncio.sleep(1)
        if keystatus.strip() == b'-':
            self.log.warning("zfs track volume start err why is keystatus '-' ?")

    @locked
    async def track_volume_start(self, vm):
        """
        Register a volume (not a VM!) as used, for the purpose
         of unloading the encryption key after a timeout
         when no volumes are in use.
        It will also prompt the user for their passphrase when trying
         to start a volume in a group whose key is currently not loaded.
        """
        self.used_volumes.add(vm)
        self.log.warning('track_volume_start add {} => {}'.format(
                         vm, self.used_volumes))
        await self.ensure_key_is_loaded()

    @locked
    async def track_volume_stop(self, vm):
        """Register a volume (not a VM!) as NOT used anymore,
           for the purpose of unloading the encryption key after a timeout
           when no volumes are in use.
        """
        self.used_volumes.discard(vm)
        self.used_volumes_last_empty = time.clock_gettime(
            time.CLOCK_MONOTONIC_RAW)

    def init_volume(self, appvm, volume_config):
        vm_name = appvm.name
        if not hasattr(volume_config, 'zfs_ns'):
            volume_config["zfs_ns"] = self.zfs_ns
        volume_config["pool"] = self
        return ZFSQEncryptedVolume(
            vm_name=vm_name,
            encrypted_pool=self,
            **volume_config
        )

    def included_in(self, app):
        """
        Returns the parent pool if found, otherwise raises an AssertionError.
        This function also moonlights as our method to retrieve a handle for
        'app' which we record and re-use when asking for passwords.
        """
        self.app_reference = app
        found = app.pools[self.zpool_name]
        return found

    def destroy(self):
        """
        Currently does nothing. TODO
        """
        # zfs umount foo/bar/baz
        # zfs key -u foo/bar
        self.log.warning(
            "zfs_encrypted:destroy(): TODO implement, please do this \
            yourself with zfs destroy {}/encrypted/{}".format(
                self.zpool_name, self.name
            )
        )

    @property
    def config(self):
        return {
            "name": self.name,
            "zpool_name": self.zpool_name,
            "zfs_ns": self.zfs_ns,
            "driver": self.driver,
            "unload_timeout": str(self.unload_timeout),
        }

    async def setup(self):
        """
        Install a new encrypted Pool.
        """

        # TODO at the moment this is set on pool initialization
        # by the underlying zpool for ALL zpools, we should be nice
        # and only enable this for pools that actually need it, by recursively
        # walking zfs_parent until the first element (the pool),
        # basically we can split by '/' and take the first element:
        # "sudo", "zpool", "set", "feature@encryption=enable",
        #   self.zfs_ns.split('/',1)[0]

        # General namespace for encrypted VMs:
        if not libzfs_core.lzc_exists(self.encryption_ns):
            await qzfs.qubes_cmd_coro(
                ["create",
                 self.encryption_ns,
                 [] # empty set of options TODO
                ])

        # Namespace for this pool.
        # It will be encrypted, and the datasets and zvols inside
        # will inheir the encryption key.)
        assert self.zfs_ns.encode() == self.zfs_ns_safety_valve
        if libzfs_core.lzc_exists(self.zfs_ns.encode()):
            raise qubes.storage.StoragePoolException(
                "our ns already exists. TODO does this leave a \
                broken qvm-pool floating around?"
            )
        (p, stdout, stderr) = await self.ask_password(
            [ # <- cmd list
                "zfs",
                "create",
                "-o", "encryption=aes-256-gcm",
                "-o", "keylocation=prompt",
                "-o", "keyformat=passphrase",
                    # TODO "pbkdf2iters=1000000",
                    # ^-- minimum is 100k, default 350k
                # TODO DEFAULT_DATASET_PROPS
                self.zfs_ns
            ]
        )
        self.log.warning("ask_password create {}/{}/{}".format(
            p, stdout, stderr))
        if p.returncode != 0:
            self.log.warning("failed to recv password / create encrypted ns")
            raise qubes.storage.StoragePoolException(
                "failed to create dataset with enc password: {}".format(
                    stderr
                ))
        self.log.warning("encrypted ns {} made!".format(self.zfs_ns))
        # zfs mount -l our_ns

        # ok so now we need to basically do the same as
        # super().setup() does after it has created the zpool.
        # TODO for now we copy-paste, but this should really move \
        # to something inheritable.
        for namespace in [b"import", b"vm"]:
            try:
                #qubes_cmd_coro(["create", ])
                # TODO here we would like to set 'refreservation=auto'
                ds_name = b"/".join([self.zfs_ns.encode(), namespace])
                libzfs_core.lzc_create(
                    ds_name,
                    ds_type="zfs",
                    props=qzfs.DEFAULT_DATASET_PROPS,
                )
            except libzfs_core.exceptions.FilesystemExists:
                raise qubes.storage.StoragePoolException(
                    "ZFS dataset for {}/{} already exists".format(
                        self.zfs_ns, namespace
                    )
                )
            except libzfs_core.exceptions.ZFSError as e:
                raise qubes.storage.StoragePoolException(
                    "ZFS dataset {}/{} could not be created: {!r}".format(
                        self.zfs_ns, namespace.encode(), e)
                    )


class ZFSQEncryptedVolume(qzfs.ZFSQzvol):
    """
    Storage volume contained inside an encrypted ZFS dataset pool.
    """
    def __init__(self, vm_name, name, encrypted_pool, **kwargs):
        self.name = name
        self.encrypted_pool = encrypted_pool
        self.pool = self.encrypted_pool
        if not hasattr(kwargs, 'zfs_ns'):
            zfs_ns = encrypted_pool.zfs_ns
            kwargs["zfs_ns"] = zfs_ns
        self.zfs_ns = zfs_ns
        super(ZFSQEncryptedVolume, self).__init__(
            vm_name=vm_name,
            name=name,
            # like it's passed to qubes.storage.Volume.__init__(),
            # lord knows what that does to it
            **kwargs)

    @locked
    async def create(self):
        """
        Installs a new volume by initializing a zvol inside an
        encrypted dataset.
        create() in a volume and setup() in a pool do the same.
        """
        self.log.warning("zfs_encrypted:create() {}".format(self.vid))
        # Prevent encryption key from timing out while we initialize:
        await self.encrypted_pool.track_volume_start(self.vid)

        # TODO should verify that encryption=on and that key is loaded.
        try:
            self.log.warning("zfs_encrypted: about to call super({})".format(
                self.vid))
            await super(ZFSQEncryptedVolume, self).create()
            self.log.warning("zfs_encrypted:create(): worked: {}".format(
                libzfs_core.lzc_exists(self.vid.encode())))
        except Exception as e:
            await self.encrypted_pool.track_volume_stop(self.vid)
            raise e
        # If all went well, stop tracking this. This coroutine is @locked,
        # so a subsequent start() will add it again.
        # If we don't relinquish the lock here, creation of a new VM would
        # permanently disable the unload_timeout:
        await self.encrypted_pool.track_volume_stop(self.vid)

    @locked
    async def start(self):
        self.log.warning('zfs encrypted vol start {}'.format(
            self.vid))
        # Called before the parent to allow their start to act on the dataset:
        await self.encrypted_pool.track_volume_start(self.vid)
        try:
            await super(ZFSQEncryptedVolume, self).start()
        except Exception as e:
            # If that failed due to for instance abort_if_import_in_progress(),
            # the import volume should still be active,
            # which means we can safely:
            await self.encrypted_pool.track_volume_stop(self.vid)
            raise e

    @locked
    async def stop(self):
        self.log.warning("ZFS STOP {}".format(self.vid))
        try:
            await super(ZFSQEncryptedVolume, self).stop()
        except Exception as e:
            # Called after the parent to allow their shutdown
            # before unloading key:
            await self.encrypted_pool.track_volume_stop(self.vid)
            raise e
        finally:
            await self.encrypted_pool.track_volume_stop(self.vid)
