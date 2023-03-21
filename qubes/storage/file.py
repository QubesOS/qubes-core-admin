#
# The Qubes OS Project, https://www.qubes-os.org/
#
# Copyright (C) 2015  Joanna Rutkowska <joanna@invisiblethingslab.com>
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

''' This module contains pool implementations backed by file images'''
import asyncio
import errno
import os
import os.path
import re
import stat
import subprocess
from contextlib import suppress

import qubes.storage
import qubes.utils

BLKSIZE = 512
CREATE_SCRIPT = '/usr/lib/qubes/create-snapshot'
DESTROY_SCRIPT = '/usr/lib/qubes/destroy-snapshot'

# 256 KiB chunk, same as in create-snapshot script. Header created by
# struct.pack('<4I', 0x70416e53, 1, 1, 256) mimicking write_header()
# in linux/drivers/md/dm-snap-persistent.c
EMPTY_SNAPSHOT = b'SnAp\x01\x00\x00\x00\x01\x00\x00\x00\x00\x01\x00\x00' \
                 + bytes(262128)

def _dev_path(file):
    res = os.stat(file)
    assert stat.S_ISREG(res.st_mode), 'not a regular file?'
    return '%x:%d' % (res.st_dev, res.st_ino)

_lock = asyncio.Lock()


def bytes_used(fobject):
    """Return bytes used by a file, taking sparseness into account.

    Non-zero byte size is not synonymous with presence of data.
    """
    return os.fstat(fobject.fileno()).st_blocks * BLKSIZE


def has_any_data(fobject):
    """Return True if the file has any non-hole data, False otherwise."""
    pos = fobject.tell()
    try:
        # Move file pointer to the beginning of the next data byte.
        fobject.seek(0, os.SEEK_DATA)
        # There was a data byte -> the file is non-empty.
        return True
    except OSError as e:
        if e.errno == errno.ENXIO:
            # The file was completely empty (zero bytes or 100% sparse).
            return False
        # Oh noes!
        raise
    finally:
        # Restore the position of the file to preserve the invariant.
        fobject.seek(pos, 0)


class FilePool(qubes.storage.Pool):
    ''' File based 'original' disk implementation

    Volumes are stored in sparse files. Additionally device-mapper is used for
    applying copy-on-write layer.

    Quick reference on device-mapper layers:

    snap_on_start save_on_stop layout
    yes           yes          not supported
    no            yes          snapshot-origin(volume.img, volume-cow.img)
    yes           no           snapshot(
                                   snapshot(source.img, source-cow.img),
                                   volume-cow.img)
    no            no           volume.img directly

    '''  # pylint: disable=protected-access
    driver = 'file'

    def __init__(self, *, name, revisions_to_keep=1, dir_path,
                 ephemeral_volatile=False):
        super().__init__(name=name, revisions_to_keep=revisions_to_keep,
                         ephemeral_volatile=ephemeral_volatile)
        self.dir_path = os.path.normpath(dir_path)
        self._volumes = []

    @property
    def config(self):
        return {
            'name': self.name,
            'dir_path': self.dir_path,
            'driver': FilePool.driver,
            'revisions_to_keep': self.revisions_to_keep,
            'ephemeral_volatile': self.ephemeral_volatile,
        }

    def init_volume(self, vm, volume_config):
        if volume_config.get('snap_on_start', False) and \
                volume_config.get('save_on_stop', False):
            raise NotImplementedError(
                'snap_on_start + save_on_stop not supported by file driver')
        volume_config['dir_path'] = self.dir_path

        if 'vid' not in volume_config:
            volume_config['vid'] = os.path.join(
                self._vid_prefix(vm), volume_config['name'])

        try:
            if not volume_config.get('save_on_stop', False):
                volume_config['revisions_to_keep'] = 0
        except KeyError:
            pass

        if 'revisions_to_keep' not in volume_config:
            volume_config['revisions_to_keep'] = self.revisions_to_keep

        volume_config['pool'] = self
        volume = FileVolume(**volume_config)
        self._volumes += [volume]
        return volume

    @staticmethod
    def check_block_dev_exists(path):
        """
        Check if a block device exists
        """
        try:
            stat_result = os.stat(path)
        except FileNotFoundError:
            return False
        assert stat.S_ISBLK(stat_result.st_mode), "not a block device?"
        return True

    @property
    def revisions_to_keep(self):
        return self._revisions_to_keep

    @revisions_to_keep.setter
    def revisions_to_keep(self, value):
        value = int(value)
        if value > 1:
            raise NotImplementedError(
                'FilePool supports maximum 1 volume revision to keep')
        self._revisions_to_keep = value

    async def destroy(self):
        pass

    def setup(self):  # pylint: disable=invalid-overridden-method
        create_dir_if_not_exists(self.dir_path)
        appvms_path = os.path.join(self.dir_path, 'appvms')
        create_dir_if_not_exists(appvms_path)
        vm_templates_path = os.path.join(self.dir_path, 'vm-templates')
        create_dir_if_not_exists(vm_templates_path)

    @staticmethod
    def _vid_prefix(vm):
        ''' Helper to create a prefix for the vid for volume
        '''  # FIX Remove this if we drop the file backend
        import qubes.vm.templatevm  # pylint: disable=redefined-outer-name
        import qubes.vm.dispvm  # pylint: disable=redefined-outer-name
        if isinstance(vm, qubes.vm.templatevm.TemplateVM):
            subdir = 'vm-templates'
        else:
            subdir = 'appvms'

        return os.path.join(subdir, vm.name)

    def target_dir(self, vm):
        """ Returns the path to vmdir depending on the type of the VM.

            The default QubesOS file storage saves the vm images in three
            different directories depending on the ``QubesVM`` type:

            * ``appvms`` for ``QubesAppVm`` or ``QubesHvm``
            * ``vm-templates`` for ``QubesTemplateVm`` or ``QubesTemplateHvm``

            Args:
                vm: a QubesVM
                pool_dir: the root directory of the pool

            Returns:
                string (str) absolute path to the directory where the vm files
                             are stored
        """

        return os.path.join(self.dir_path, self._vid_prefix(vm))

    def list_volumes(self):
        return self._volumes

    @property
    def size(self):
        try:
            statvfs = os.statvfs(self.dir_path)
            return statvfs.f_frsize * statvfs.f_blocks
        except FileNotFoundError:
            return 0

    @property
    def usage(self):
        try:
            statvfs = os.statvfs(self.dir_path)
            return statvfs.f_frsize * (statvfs.f_blocks - statvfs.f_bfree)
        except FileNotFoundError:
            return 0

    def included_in(self, app):
        ''' Check if there is pool containing this one - either as a
        filesystem or its LVM volume'''
        return qubes.storage.search_pool_containing_dir(
            [pool for pool in app.pools.values() if pool is not self],
            self.dir_path)

class FileVolume(qubes.storage.Volume):
    ''' Parent class for the xen volumes implementation which expects a
        `target_dir` param on initialization.  '''
    _marker_running = object()
    _marker_exported = object()

    def __init__(self, dir_path, **kwargs):
        self.dir_path = dir_path
        assert self.dir_path, "dir_path not specified"
        self._revisions_to_keep = 0
        self._export_lock = None
        super().__init__(**kwargs)

        if self.snap_on_start:
            img_name = self.source.vid + '-cow.img'
            self.path_source_cow = os.path.join(self.dir_path, img_name)

    @property
    def revisions_to_keep(self):
        return self._revisions_to_keep

    @revisions_to_keep.setter
    def revisions_to_keep(self, value):
        if not isinstance(value, int) or value > 1 or value < 0:
            raise NotImplementedError(
                'FileVolume supports maximum 1 volume revision to keep')
        self._revisions_to_keep = value

    def create(self):  # pylint: disable=invalid-overridden-method
        assert isinstance(self.size, int) and self.size > 0, \
            'Volume size must be > 0'
        if not self.snap_on_start:
            create_sparse_file(self.path, self.size, permissions=0o664)

    async def _destroy_blockdev(self):
        async with _lock:
            path = self._block_device_path()
            if os.path.exists(path):
                await qubes.utils.run_program(DESTROY_SCRIPT,
                        path, sudo=True)

    async def remove(self):
        with suppress(ValueError):
            self.pool._volumes.remove(self)  # pylint: disable=protected-access
        await self.stop()
        if not self.snap_on_start:
            _remove_if_exists(self.path)
        if self.snap_on_start or self.save_on_stop:
            _remove_if_exists(self.path_cow)
            _remove_if_exists(self.path_cow + '.old')

    def is_outdated(self):
        return False  # avoid spamming the log with NotImplementedError

    def is_dirty(self):
        if self.save_on_stop:
            with suppress(FileNotFoundError), open(self.path_cow, 'rb') as cow:
                # The bytes used on disk does not determine whether a
                # file actually has any data.  In ZFS, for example,
                # a completely empty file (textbook 100% sparse, or even
                # zero-byte-length) will still occupy at least one block.
                # Thus, below, the function has_any_data() is used to
                # determine if the copy-on-write file has any data.
                cow_used = bytes_used(cow)
                return (has_any_data(cow) and
                        (cow_used > len(EMPTY_SNAPSHOT) or
                         cow.read(len(EMPTY_SNAPSHOT)) != EMPTY_SNAPSHOT or
                         cow_used > cow.seek(0, os.SEEK_HOLE)))
        return False

    def _resize_snapshot_dev(self, size):
        path = self._block_device_path()
        # read old table:
        dm_table = subprocess.check_output(['dmsetup', 'table', path])
        assert dm_table.count(b'\n') == 1
        dm_table_parts = dm_table.decode().split(' ')
        assert dm_table_parts[0] == '0'
        # Kernel docs say:
        # > When loading or unloading the snapshot target, the corresponding
        # > snapshot-origin or snapshot-merge target must be suspended.
        # > A failure to suspend the origin target could result in data
        # > corruption.
        # This doesn't apply to loading snapshot-origin target itself.
        # Beware if ever adding resize of 'snapshot' target.
        assert dm_table_parts[2] == 'snapshot-origin'
        # replace the size
        dm_table_parts[1] = str(size // 512)
        dm_table = ' '.join(dm_table_parts)
        # load new table
        subprocess.check_call(['dmsetup', 'load', '--table=' + dm_table, path])
        # and make it active
        subprocess.check_call(['dmsetup', 'resume', path])

    def resize(self, size):  # pylint: disable=invalid-overridden-method
        ''' Expands volume, throws
            :py:class:`qubst.storage.qubes.storage.StoragePoolException` if
            given size is less than current_size
        '''
        if not self.rw:
            msg = 'Can not resize readonly volume {!s}'.format(self)
            raise qubes.storage.StoragePoolException(msg)

        if self.snap_on_start:
            # this theoretically could be supported, but it's unusual
            # enough to not worth the effort
            msg = 'Cannot resize volume based on a template - resize' \
                  'the template instead'
            raise qubes.storage.StoragePoolException(msg)

        if size < self.size:
            raise qubes.storage.StoragePoolException(
                'For your own safety, shrinking of %s is'
                ' disabled. If you really know what you'
                ' are doing, use `truncate` on %s manually.' %
                (self.name, self.vid))

        with open(self.path, 'a+b') as fd:
            fd.truncate(size)

        with subprocess.Popen(['losetup', '--associated', self.path],
                              stdout=subprocess.PIPE) as p:
            result = p.communicate()

        m = re.match(r'\A(/dev/loop\d+):\s', result[0].decode())
        if m is not None:
            loop_dev = m.group(1)

            # resize loop device
            subprocess.check_call(['losetup', '--set-capacity',
                                   loop_dev])
            if self.save_on_stop:
                self._resize_snapshot_dev(size)

        self._size = size

    def commit(self):
        msg = 'Tried to commit a non commitable volume {!r}'.format(self)
        assert self.save_on_stop and self.rw, msg

        if os.path.exists(self.path_cow):
            if self.revisions_to_keep:
                old_path = self.path_cow + '.old'
                os.rename(self.path_cow, old_path)
            else:
                os.unlink(self.path_cow)

        create_sparse_file(self.path_cow, self.size)
        return self

    def export(self):  # pylint: disable=invalid-overridden-method
        if self._export_lock is not None:
            assert self._export_lock is FileVolume._marker_running, \
                'nested calls to export()'
            raise qubes.storage.StoragePoolException(
                'file pool cannot export running volumes')
        if self.is_dirty():
            raise qubes.storage.StoragePoolException(
                'file pool cannot export dirty volumes')
        self._export_lock = FileVolume._marker_exported
        return self.path

    async def export_end(self, path):
        assert self._export_lock is not FileVolume._marker_running, \
            'ending an export on a running volume?'
        self._export_lock = None

    async def import_volume(self, src_volume):
        if src_volume.snap_on_start:
            raise qubes.storage.StoragePoolException(
                "Can not import snapshot volume {!s} in to pool {!s} ".format(
                    src_volume, self))
        if self.save_on_stop:
            _remove_if_exists(self.path)
            path = await qubes.utils.coro_maybe(src_volume.export())
            try:
                copy_file(path, self.path)
            finally:
                await qubes.utils.coro_maybe(src_volume.export_end(path))
        return self

    def import_data(self, size):  # pylint: disable=invalid-overridden-method
        if not self.save_on_stop:
            raise qubes.storage.StoragePoolException(
                "Can not import into save_on_stop=False volume {!s}".format(
                    self))
        create_sparse_file(self.path_import, size)
        return self.path_import

    def import_data_end(self, success):  # pylint: disable=invalid-overridden-method
        if success:
            os.rename(self.path_import, self.path)
        else:
            os.unlink(self.path_import)
        return self

    def reset(self):
        ''' Remove and recreate a volatile volume '''
        assert not self.snap_on_start and not self.save_on_stop, \
            "Not a volatile volume"
        assert isinstance(self.size, int) and self.size > 0, \
            'Volatile volume size must be > 0'

        _remove_if_exists(self.path)
        create_sparse_file(self.path, self.size)
        return self

    async def start(self):
        if self._export_lock is not None:
            assert self._export_lock is FileVolume._marker_exported, \
                'nested calls to start()'
            raise qubes.storage.StoragePoolException(
                'file pool cannot start a VM with an exported volume')
        self._export_lock = FileVolume._marker_running
        if not self.save_on_stop and not self.snap_on_start:
            self.reset()
            # so that we do not trip an assertion below
            return self
        if not self.save_on_stop:
            # make sure previous snapshot is removed - even if VM
            # shutdown routine wasn't called (power interrupt or so)
            _remove_if_exists(self.path_cow)
        if not os.path.exists(self.path_cow):
            create_sparse_file(self.path_cow, self.size)
        if not self.snap_on_start:
            _check_path(self.path)
        if hasattr(self, 'path_source_cow'):
            if not os.path.exists(self.path_source_cow):
                create_sparse_file(self.path_source_cow, self.size)

        path = self._block_device_path()
        assert path.startswith('/dev/mapper/'), 'bad path %r' % path
        path = path[12:]
        async with _lock:
            if self.save_on_stop:
                assert not self.snap_on_start, 'unsupported configuration'
                await qubes.utils.run_program(CREATE_SCRIPT, path, self.path,
                        self.path_cow, sudo=True)
            elif self.snap_on_start:
                assert self.path.endswith('.img')
                assert self.path_source_cow == self.path[:-4] + '-cow.img'
                await qubes.utils.run_program(CREATE_SCRIPT, path, self.path,
                        self.path_source_cow, self.path_cow, sudo=True)
        return self

    async def stop(self):
        assert self._export_lock is not FileVolume._marker_exported, \
            'trying to stop exported file volume?'
        if self.save_on_stop or self.snap_on_start:
            await self._destroy_blockdev()
        if self.save_on_stop:
            if self.rw:
                self.commit()
            else:
                _remove_if_exists(self.path_cow)
        elif self.snap_on_start:
            _remove_if_exists(self.path_cow)
        else:
            _remove_if_exists(self.path)
        self._export_lock = None
        return self

    @property
    def path(self):
        if self.snap_on_start:
            assert not self.save_on_stop
            return os.path.join(self.dir_path, self.source.vid + '.img')
        return os.path.join(self.dir_path, self.vid + '.img')

    @property
    def path_cow(self):
        img_name = self.vid + '-cow.img'
        return os.path.join(self.dir_path, img_name)

    @property
    def path_import(self):
        img_name = self.vid + '-import.img'
        return os.path.join(self.dir_path, img_name)

    def verify(self):  # pylint: disable=invalid-overridden-method
        ''' Verifies the volume. '''
        if not os.path.exists(self.path) and \
                (self.snap_on_start or self.save_on_stop):
            msg = 'Missing image file: {!s}.'.format(self.path)
            raise qubes.storage.StoragePoolException(msg)
        return True

    @property
    def script(self):
        pass

    def _block_device_path(self):
        if not self.snap_on_start:
            if not self.save_on_stop:
                return self.path
            return '-'.join([
                '/dev/mapper/origin',
                _dev_path(self.path),
            ])
        assert not self.save_on_stop, 'unsuppported configuration'
        return '-'.join([
            '/dev/mapper/snapshot',
            _dev_path(self.path),
            _dev_path(self.path_source_cow),
            _dev_path(self.path_cow),
        ])

    def block_device(self):
        ''' Return :py:class:`qubes.storage.BlockDevice` for serialization in
            the libvirt XML template as <disk>.
        '''
        path = self._block_device_path()
        return qubes.storage.BlockDevice(path, self.name, self.script, self.rw,
                                         self.domain, self.devtype)

    @property
    def revisions(self):
        if not hasattr(self, 'path_cow'):
            return {}

        old_revision = self.path_cow + '.old'  # pylint: disable=no-member

        if not os.path.exists(old_revision):
            return {}

        seconds = int(os.path.getctime(old_revision))
        iso_date = qubes.storage.isodate(seconds)
        return {'old': iso_date}

    @property
    def size(self):
        with suppress(FileNotFoundError):
            self._size = os.path.getsize(self.path)
        return self._size

    @property
    def usage(self):
        ''' Returns the actualy used space '''
        usage = 0
        if self.save_on_stop or self.snap_on_start:
            usage = get_disk_usage(self.path_cow)
        if self.save_on_stop or not self.snap_on_start:
            usage += get_disk_usage(self.path)
        return usage


def create_sparse_file(path, size, permissions=None):
    ''' Create an empty sparse file '''
    if os.path.exists(path):
        raise IOError("Volume %s already exists" % path)
    parent_dir = os.path.dirname(path)
    if not os.path.exists(parent_dir):
        os.makedirs(parent_dir)
    with open(path, 'a+b') as fh:
        if permissions is not None:
            os.fchmod(fh.fileno(), permissions)
        fh.truncate(size)


def get_disk_usage_one(st):
    '''Extract disk usage of one inode from its stat_result struct.

    If known, get real disk usage, as written to device by filesystem, not
    logical file size. Those values may be different for sparse files.

    :param os.stat_result st: stat result
    :returns: disk usage
    '''
    try:
        return st.st_blocks * BLKSIZE
    except AttributeError:
        return st.st_size


def get_disk_usage(path):
    '''Get real disk usage of given path (file or directory).

    When *path* points to directory, then it is evaluated recursively.

    This function tries estimate real disk usage. See documentation of
    :py:func:`get_disk_usage_one`.

    :param str path: path to evaluate
    :returns: disk usage
    '''
    try:
        st = os.lstat(path)
    except OSError:
        return 0

    ret = get_disk_usage_one(st)

    # if path is not a directory, this is skipped
    for dirpath, dirnames, filenames in os.walk(path):
        for name in dirnames + filenames:
            ret += get_disk_usage_one(os.lstat(os.path.join(dirpath, name)))

    return ret


def create_dir_if_not_exists(path):
    """ Check if a directory exists in if not create it.

        This method does not create any parent directories.
    """
    if not os.path.exists(path):
        os.mkdir(path)


def copy_file(source, destination):
    '''Effective file copy, preserving sparse files etc.'''
    # We prefer to use Linux's cp, because it nicely handles sparse files
    assert os.path.exists(source), \
        "Missing the source %s to copy from" % source
    assert not os.path.exists(destination), \
        "Destination %s already exists" % destination

    parent_dir = os.path.dirname(destination)
    if not os.path.exists(parent_dir):
        os.makedirs(parent_dir)

    try:
        cmd = ['cp', '--sparse=always',
               '--reflink=auto', source, destination]
        subprocess.check_call(cmd)
    except subprocess.CalledProcessError:
        raise IOError('Error while copying {!r} to {!r}'.format(source,
                                                                destination))


def _remove_if_exists(path):
    ''' Removes a file if it exist, silently succeeds if file does not exist '''
    try:
        os.remove(path)
    except FileNotFoundError:
        pass

def _check_path(path):
    ''' Raise an StoragePoolException if ``path`` does not exist'''
    if not os.path.exists(path):
        msg = 'Missing image file: %s' % path
        raise qubes.storage.StoragePoolException(msg)
