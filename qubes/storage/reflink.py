#
# The Qubes OS Project, https://www.qubes-os.org/
#
# Copyright (C) 2018 Rusty Bird <rustybird@net-c.com>
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

''' Driver for handling VM images as files, without any device-mapper
    involvement. A reflink-capable filesystem is strongly recommended,
    but not required.
'''

import asyncio
import collections
import errno
import fcntl
import functools
import glob
import logging
import os
import platform
import subprocess
import tempfile
from contextlib import contextmanager, suppress

import qubes.storage
import qubes.utils


LOGGER = logging.getLogger('qubes.storage.reflink')

# defined in <linux/loop.h>
LOOP_SET_CAPACITY = 0x4C07

# defined in <linux/fs.h>
FICLONE = {
    'x86_64':  0x40049409,
    'ppc64le': 0x80049409,
}[platform.machine()]


def _coroutinized(function):
    ''' Wrap a synchronous function in a coroutine that runs the
        function via the event loop's ThreadPool-based default
        executor.
    '''
    @functools.wraps(function)
    async def wrapper(*args, **kwargs):
        return await asyncio.get_event_loop().run_in_executor(
            None, functools.partial(function, *args, **kwargs))
    return wrapper


class ReflinkPool(qubes.storage.Pool):
    driver = 'file-reflink'
    _known_dir_path_prefixes = ['appvms', 'vm-templates']

    def __init__(self, *, name, revisions_to_keep=1,
                 dir_path, setup_check=True, ephemeral_volatile=False):
        super().__init__(name=name, revisions_to_keep=revisions_to_keep,
                         ephemeral_volatile=ephemeral_volatile)
        self._setup_check = qubes.property.bool(None, None, setup_check)
        self._volumes = {}
        self.dir_path = os.path.abspath(dir_path)

    @_coroutinized
    def setup(self):  # pylint: disable=invalid-overridden-method
        created = _create_dir(self.dir_path)
        if self._setup_check and not is_supported(self.dir_path):
            if created:
                _remove_empty_dir(self.dir_path)
            raise qubes.storage.StoragePoolException(
                'The filesystem for {!r} does not support reflinks. If you'
                ' can live with VM startup delays and wasted disk space, pass'
                ' the "setup_check=False" option.'.format(self.dir_path))
        for dir_path_prefix in self._known_dir_path_prefixes:
            _create_dir(os.path.join(self.dir_path, dir_path_prefix))
        return self

    def init_volume(self, vm, volume_config):
        # Fail closed on any strange VM dir_path_prefix, just in case
        # /usr/lib/udev/rules.d/00-qubes-ignore-devices.rules needs update
        assert vm.dir_path_prefix in self._known_dir_path_prefixes, \
               'Unknown dir_path_prefix {!r}'.format(vm.dir_path_prefix)

        if 'revisions_to_keep' not in volume_config:
            volume_config['revisions_to_keep'] = self.revisions_to_keep
        if 'vid' not in volume_config:
            volume_config['vid'] = os.path.join(
                vm.dir_path_prefix, vm.name, volume_config['name'])
        volume_config['pool'] = self
        volume = ReflinkVolume(**volume_config)
        self._volumes[volume.vid] = volume
        return volume

    def list_volumes(self):
        return list(self._volumes.values())

    def get_volume(self, vid):
        return self._volumes[vid]

    async def destroy(self):
        pass

    @property
    def config(self):
        return {
            'name': self.name,
            'dir_path': self.dir_path,
            'driver': ReflinkPool.driver,
            'revisions_to_keep': self.revisions_to_keep,
            'ephemeral_volatile': self.ephemeral_volatile,
        }

    @property
    def usage_details(self):
        with suppress(FileNotFoundError):
            stat = os.statvfs(self.dir_path)
            return {
                'data_size': stat.f_frsize * stat.f_blocks,
                'data_usage': stat.f_frsize * (stat.f_blocks - stat.f_bfree),
            }
        return {}

    @property
    def size(self):
        return self.usage_details.get('data_size')

    @property
    def usage(self):
        return self.usage_details.get('data_usage')

    def included_in(self, app):
        ''' Check if there is pool containing this one - either as a
        filesystem or its LVM volume'''
        return qubes.storage.search_pool_containing_dir(
            [pool for pool in app.pools.values() if pool is not self],
            self.dir_path)


class ReflinkVolume(qubes.storage.Volume):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._path_vid = os.path.join(self.pool.dir_path, self.vid)
        self._path_clean = self._path_vid + '.img'
        self._path_precache = self._path_vid + '-precache.img'
        self._path_dirty = self._path_vid + '-dirty.img'
        self._path_import = self._path_vid + '-import.img'
        self.path = self._path_dirty

    @contextmanager
    def _update_precache(self):
        _remove_file(self._path_precache)
        yield
        _copy_file(self._path_clean, self._path_precache, copy_mtime=True)

    def _remove_stale_precache(self):
        ''' Defuse the following situation: We created a precache.
            After that, the pool was used on an older Qubes version
            without precache support - causing staleness. Now the
            pool is here again on new Qubes.
        '''
        stat_clean = os.stat(self._path_clean)
        with suppress(FileNotFoundError):
            if not _eq_files(stat_clean, os.stat(self._path_precache),
                             by_attrs=['st_mtime_ns', 'st_size']):
                # pylint: disable=redundant-keyword-arg
                _remove_file(self._path_precache, log_level=logging.DEBUG)
                LOGGER.warning('Removed stale file: %r', self._path_precache)

    @qubes.storage.Volume.locked
    @_coroutinized
    def create(self):  # pylint: disable=invalid-overridden-method
        self._remove_all_images()
        if self.save_on_stop and not self.snap_on_start:
            with self._update_precache():
                _create_sparse_file(self._path_clean, self._size)
        return self

    @_coroutinized
    def verify(self):  # pylint: disable=invalid-overridden-method
        if self.snap_on_start:
            img = self.source._path_clean  # pylint: disable=protected-access
        elif self.save_on_stop:
            img = self._path_clean
        else:
            img = None

        if img is None or os.path.exists(img):
            return True
        raise qubes.storage.StoragePoolException(
            'Missing image file {!r} for volume {}'.format(img, self.vid))

    @qubes.storage.Volume.locked
    @_coroutinized
    def remove(self):  # pylint: disable=invalid-overridden-method
        self.pool._volumes.pop(self.vid, None)  # pylint: disable=protected-access
        self._remove_all_images()
        _remove_empty_dir(os.path.dirname(self._path_vid))
        return self

    def _remove_all_images(self):
        self._remove_incomplete_images()
        self._prune_revisions(keep=0)
        _remove_file(self._path_clean)
        _remove_file(self._path_precache)
        _remove_file(self._path_dirty)

    def _remove_incomplete_images(self):
        for tmp in glob.iglob(glob.escape(self._path_vid) + '*.img*~*'):
            _remove_file(tmp)
        _remove_file(self._path_import)

    def is_outdated(self):
        if self.snap_on_start:
            with suppress(FileNotFoundError):
                return not _eq_files(
                    # pylint: disable=protected-access
                    os.stat(self.source._path_clean),
                    os.stat(self._path_clean))
        return False

    def is_dirty(self):
        return self.save_on_stop and os.path.exists(self._path_dirty)

    @qubes.storage.Volume.locked
    @_coroutinized
    def start(self):  # pylint: disable=invalid-overridden-method
        self._remove_incomplete_images()
        if not self.is_dirty():
            if self.snap_on_start:
                _remove_file(self._path_clean)
                # pylint: disable=protected-access
                _hardlink_file(self.source._path_clean, self._path_clean)
                _copy_file(self._path_clean, self._path_dirty)
            elif self.save_on_stop:
                self._remove_stale_precache()
                try:
                    _rename_file(self._path_precache, self._path_dirty)
                except FileNotFoundError:
                    _copy_file(self._path_clean, self._path_dirty)
            else:
                _create_sparse_file(self._path_dirty, self._size)
        return self

    @qubes.storage.Volume.locked
    @_coroutinized
    def stop(self):  # pylint: disable=invalid-overridden-method
        if self.is_dirty():
            self._commit(self._path_dirty)
        elif not self.save_on_stop:
            if not self.snap_on_start:
                self._size = self.size  # preserve manual resize of image
            _remove_file(self._path_dirty)
            _remove_file(self._path_clean)
        return self

    def _commit(self, path_from):
        self._add_revision()
        self._prune_revisions()
        qubes.utils.fsync_path(path_from)
        with self._update_precache():
            _rename_file(path_from, self._path_clean)

    def _add_revision(self):
        if self.revisions_to_keep == 0:
            return
        timestamp = qubes.storage.isodate(
            int(os.path.getmtime(self._path_clean)))
        _copy_file(
            self._path_clean,
            self._path_revision(self._next_revision, timestamp))

    def _prune_revisions(self, keep=None):
        if keep is None:
            keep = self.revisions_to_keep
        # pylint: disable=invalid-unary-operand-type
        for revision, timestamp in list(self.revisions.items())[:-keep or None]:
            _remove_file(self._path_revision(revision, timestamp))

    @qubes.storage.Volume.locked
    @_coroutinized
    def revert(self, revision=None):  # pylint: disable=invalid-overridden-method
        if self.is_dirty():
            raise qubes.storage.StoragePoolException(
                'Cannot revert: {} is not cleanly stopped'.format(self.vid))
        path_revision = self._path_revision(revision)
        self._add_revision()
        with self._update_precache():
            _rename_file(path_revision, self._path_clean)
        return self

    @qubes.storage.Volume.locked
    @_coroutinized
    def resize(self, size):  # pylint: disable=invalid-overridden-method
        ''' Resize a read-write volume; notify any corresponding loop
            devices of the size change.
        '''
        if not self.rw:
            raise qubes.storage.StoragePoolException(
                'Cannot resize: {} is read-only'.format(self.vid))
        try:
            _resize_file(self._path_dirty, size)
        except FileNotFoundError:
            if self.save_on_stop and not self.snap_on_start:
                with self._update_precache():
                    _copy_file(
                        self._path_clean, self._path_clean, dst_size=size)
        else:
            _update_loopdev_sizes(self._path_dirty)
        self._size = size
        return self

    async def export(self):
        if not self.save_on_stop:
            raise NotImplementedError(
                'Cannot export: {} is not save_on_stop'.format(self.vid))
        return self._path_clean

    @qubes.storage.Volume.locked
    @_coroutinized
    def import_data(self, size):  # pylint: disable=invalid-overridden-method
        if not self.save_on_stop:
            raise NotImplementedError(
                'Cannot import_data: {} is not save_on_stop'.format(self.vid))
        _create_sparse_file(self._path_import, size)
        return self._path_import

    @_coroutinized
    def _import_data_end_unlocked(self, success):
        (self._commit if success else _remove_file)(self._path_import)
        return self

    import_data_end = qubes.storage.Volume.locked(_import_data_end_unlocked)

    @qubes.storage.Volume.locked
    async def import_volume(self, src_volume):
        if self.save_on_stop:
            success = False
            try:
                src_path = await qubes.utils.coro_maybe(src_volume.export())
                try:
                    await _coroutinized(_copy_file)(src_path, self._path_import)
                finally:
                    await qubes.utils.coro_maybe(
                        src_volume.export_end(src_path))
                success = True
            finally:
                await self._import_data_end_unlocked(success)
        return self

    def _path_revision(self, revision=None, timestamp=None):
        if timestamp is None:
            if revision is None:
                revision, timestamp = list(self.revisions.items())[-1]
            else:
                timestamp = self.revisions[revision]
        return self._path_clean + '.' + revision + '@' + timestamp + 'Z'

    @property
    def _next_revision(self):
        revisions = self.revisions.keys()
        return str(int(list(revisions)[-1]) + 1) if revisions else '1'

    @property
    def revisions(self):
        prefix = self._path_clean + '.'
        paths = glob.iglob(glob.escape(prefix) + '*?@????-??-??T??:??:??Z')
        items = (path[len(prefix):-1].split('@') for path in paths)
        return collections.OrderedDict(
            sorted(items, key=lambda item: int(item[0])))

    @property
    def size(self):
        for path in (self._path_dirty, self._path_clean):
            with suppress(FileNotFoundError):
                return os.path.getsize(path)
        return self._size

    @property
    def usage(self):
        for path in (self._path_dirty, self._path_clean):
            with suppress(FileNotFoundError):
                return os.stat(path).st_blocks * 512
        return 0


def _replace_file(dst):
    _create_dir(os.path.dirname(dst))
    return qubes.utils.replace_file(
        dst, permissions=0o600, log_level=logging.INFO)

_rename_file = functools.partial(
    qubes.utils.rename_file, log_level=logging.INFO)

_remove_file = functools.partial(
    qubes.utils.remove_file, log_level=logging.INFO)

def _hardlink_file(src, dst):
    dst_dir = os.path.dirname(dst)
    _create_dir(dst_dir)
    os.link(src, dst)
    qubes.utils.fsync_path(dst_dir)
    LOGGER.info('Hardlinked file: %r -> %r', src, dst)

def _create_dir(path):
    try:
        created = False
        os.mkdir(path)
        created = True
    except FileExistsError:
        if not os.path.isdir(path):
            raise
    if created:
        qubes.utils.fsync_path(os.path.dirname(path))
        LOGGER.info('Created directory: %r', path)
    return created

def _remove_empty_dir(path):
    try:
        removed = False
        os.rmdir(path)
        removed = True
    except OSError as ex:
        if ex.errno not in (errno.ENOENT, errno.ENOTEMPTY):
            raise
    if removed:
        qubes.utils.fsync_path(os.path.dirname(path))
        LOGGER.info('Removed empty directory: %r', path)
    return removed

def _resize_file(path, size):
    ''' Resize an existing file. '''
    with open(path, 'rb+') as file_io:
        file_io.truncate(size)
        os.fsync(file_io.fileno())

def _create_sparse_file(path, size):
    ''' Create an empty sparse file. '''
    with _replace_file(path) as tmp_io:
        tmp_io.truncate(size)
        LOGGER.info('Created sparse file: %r', tmp_io.name)

def _eq_files(stat1, stat2, *, by_attrs=('st_ino', 'st_dev')):
    for attr in by_attrs:
        if getattr(stat1, attr) != getattr(stat2, attr):
            return False
    return True

def _update_loopdev_sizes(img):
    ''' Resolve img; update the size of loop devices backed by it. '''
    needle = os.fsencode(os.path.realpath(img)) + b'\n'
    for sys_path in glob.iglob('/sys/block/loop[0-9]*/loop/backing_file'):
        matched = False
        with suppress(FileNotFoundError), open(sys_path, 'rb') as sys_io:
            matched = sys_io.read() == needle
        if matched:
            with open('/dev/' + sys_path.split('/')[3], 'rb') as dev_io:
                fcntl.ioctl(dev_io.fileno(), LOOP_SET_CAPACITY)

def _attempt_ficlone(src_io, dst_io):
    try:
        ficloned = False
        fcntl.ioctl(dst_io.fileno(), FICLONE, src_io.fileno())
        ficloned = True
    except OSError as ex:
        if ex.errno not in (errno.EBADF, errno.EINVAL,
                            errno.EOPNOTSUPP, errno.EXDEV):
            raise
    return ficloned

def _copy_file(src, dst, *, dst_size=None, copy_mtime=False):
    ''' Transfer the data at src (and optionally its modification
        time) to a new inode at dst, using a reflink if possible or a
        sparsifying copy if not. Optionally, the new dst will have
        been resized to dst_size bytes.
    '''
    with open(src, 'rb') as src_io, _replace_file(dst) as tmp_io:
        if dst_size == 0:
            reflinked = None
        else:
            reflinked = _attempt_ficlone(src_io, tmp_io)
            if reflinked:
                LOGGER.info('Reflinked file: %r -> %r', src, tmp_io.name)
            else:
                LOGGER.info('Copying file: %r -> %r', src, tmp_io.name)
                result = subprocess.run(
                    ['cp', '--sparse=always', '--', src, tmp_io.name],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
                if result.returncode != 0:
                    raise qubes.storage.StoragePoolException(str(result))
            if dst_size is not None:
                tmp_io.truncate(dst_size)
        if copy_mtime:
            mtime_ns = os.stat(src_io.fileno()).st_mtime_ns
            atime_ns = mtime_ns  # Python doesn't support UTIME_OMIT
            os.utime(tmp_io.fileno(), ns=(atime_ns, mtime_ns))
    return reflinked

def is_supported(dst_dir, *, src_dir=None):
    ''' Return whether destination directory supports reflink copies
        from source directory. (A temporary file is created in each
        directory, using O_TMPFILE if possible.)
    '''
    if src_dir is None:
        src_dir = dst_dir
    with tempfile.TemporaryFile(dir=src_dir) as src_io, \
         tempfile.TemporaryFile(dir=dst_dir) as dst_io:
        src_io.write(b'foo')  # don't let any fs get clever with empty files
        return _attempt_ficlone(src_io, dst_io)
