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
import subprocess
import tempfile
import threading
from contextlib import contextmanager, suppress

import qubes.storage

FICLONE = 1074041865        # defined in <linux/fs.h>, assuming sizeof(int)==4
LOOP_SET_CAPACITY = 0x4C07  # defined in <linux/loop.h>
LOGGER = logging.getLogger('qubes.storage.reflink')


def _coroutinized(function):
    ''' Decorator transforming a synchronous function into a coroutine
        that runs the function in the event loop's thread-based
        default executor.
    '''
    @asyncio.coroutine
    @functools.wraps(function)
    def wrapper(*args, **kwargs):
        return (yield from asyncio.get_event_loop().run_in_executor(
            None, functools.partial(function, *args, **kwargs)))
    return wrapper

class ReflinkPool(qubes.storage.Pool):
    driver = 'file-reflink'
    _known_dir_path_prefixes = ['appvms', 'vm-templates']

    def __init__(self, dir_path, setup_check='yes', revisions_to_keep=1,
                 **kwargs):
        super().__init__(revisions_to_keep=revisions_to_keep, **kwargs)
        self._volumes = {}
        self.dir_path = os.path.abspath(dir_path)
        self.setup_check = qubes.property.bool(None, None, setup_check)

    @_coroutinized
    def setup(self):
        created = _make_dir(self.dir_path)
        if self.setup_check and not is_supported(self.dir_path):
            if created:
                _remove_empty_dir(self.dir_path)
            raise qubes.storage.StoragePoolException(
                'The filesystem for {!r} does not support reflinks. If you'
                ' can live with VM startup delays and wasted disk space, pass'
                ' the "setup_check=no" option.'.format(self.dir_path))
        for dir_path_prefix in self._known_dir_path_prefixes:
            _make_dir(os.path.join(self.dir_path, dir_path_prefix))
        return self

    def init_volume(self, vm, volume_config):
        # Fail closed on any strange VM dir_path_prefix, just in case
        # /etc/udev/rules/00-qubes-ignore-devices.rules needs updating
        assert vm.dir_path_prefix in self._known_dir_path_prefixes, \
               'Unknown dir_path_prefix {!r}'.format(vm.dir_path_prefix)

        volume_config['pool'] = self
        if 'revisions_to_keep' not in volume_config:
            volume_config['revisions_to_keep'] = self.revisions_to_keep
        if 'vid' not in volume_config:
            volume_config['vid'] = os.path.join(vm.dir_path_prefix, vm.name,
                                                volume_config['name'])
        volume = ReflinkVolume(**volume_config)
        self._volumes[volume_config['vid']] = volume
        return volume

    def list_volumes(self):
        return list(self._volumes.values())

    def get_volume(self, vid):
        return self._volumes[vid]

    def destroy(self):
        pass

    @property
    def config(self):
        return {
            'name': self.name,
            'dir_path': self.dir_path,
            'driver': ReflinkPool.driver,
            'revisions_to_keep': self.revisions_to_keep
        }

    @property
    def size(self):
        statvfs = os.statvfs(self.dir_path)
        return statvfs.f_frsize * statvfs.f_blocks

    @property
    def usage(self):
        statvfs = os.statvfs(self.dir_path)
        return statvfs.f_frsize * (statvfs.f_blocks - statvfs.f_bfree)

    def included_in(self, app):
        ''' Check if there is pool containing this one - either as a
        filesystem or its LVM volume'''
        return qubes.storage.search_pool_containing_dir(
            [pool for pool in app.pools.values() if pool is not self],
            self.dir_path)


def _locked(method):
    ''' Decorator transforming a synchronous volume method to run
        under the volume lock.
    '''
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._lock:  # pylint: disable=protected-access
            return method(self, *args, **kwargs)
    return wrapper

class ReflinkVolume(qubes.storage.Volume):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._lock = threading.Lock()
        self._path_vid = os.path.join(self.pool.dir_path, self.vid)
        self._path_clean = self._path_vid + '.img'
        self._path_dirty = self._path_vid + '-dirty.img'
        self._path_import = self._path_vid + '-import.img'
        self.path = self._path_dirty

    @_coroutinized
    @_locked
    def create(self):
        if self.save_on_stop and not self.snap_on_start:
            _create_sparse_file(self._path_clean, self._get_size())
        return self

    @_coroutinized
    def verify(self):
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

    @_coroutinized
    @_locked
    def remove(self):
        ''' Drop volume object from pool; remove volume images from
            oldest to newest; remove empty VM directory.
        '''
        self.pool._volumes.pop(self, None)  # pylint: disable=protected-access
        self._remove_incomplete_files()
        self._prune_revisions(keep=0)
        _remove_file(self._path_clean)
        _remove_file(self._path_dirty)
        _remove_empty_dir(os.path.dirname(self._path_dirty))
        return self

    def _remove_incomplete_files(self):
        for tmp in glob.iglob(glob.escape(self._path_vid) + '*.img*~*'):
            _remove_file(tmp)
        _remove_file(self._path_import)

    def is_outdated(self):
        if self.snap_on_start:
            with suppress(FileNotFoundError):
                # pylint: disable=protected-access
                return (os.path.getmtime(self.source._path_clean) >
                        os.path.getmtime(self._path_clean))
        return False

    def is_dirty(self):
        return self.save_on_stop and os.path.exists(self._path_dirty)

    @_coroutinized
    @_locked
    def start(self):
        self._remove_incomplete_files()
        if self.is_dirty():  # implies self.save_on_stop
            return self
        if self.snap_on_start:
            # pylint: disable=protected-access
            _copy_file(self.source._path_clean, self._path_clean)
        if self.snap_on_start or self.save_on_stop:
            _copy_file(self._path_clean, self._path_dirty)
        else:
            _create_sparse_file(self._path_dirty, self._get_size())
        return self

    @_coroutinized
    @_locked
    def stop(self):
        if self.save_on_stop:
            self._commit(self._path_dirty)
        else:
            _remove_file(self._path_dirty)
            _remove_file(self._path_clean)
        return self

    def _commit(self, path_from):
        self._add_revision()
        self._prune_revisions()
        _fsync_path(path_from)
        _rename_file(path_from, self._path_clean)

    def _add_revision(self):
        if self.revisions_to_keep == 0:
            return
        ctime = os.path.getctime(self._path_clean)
        timestamp = qubes.storage.isodate(int(ctime))
        _copy_file(self._path_clean,
                   self._path_revision(self._next_revision_number, timestamp))

    def _prune_revisions(self, keep=None):
        if keep is None:
            keep = self.revisions_to_keep
        # pylint: disable=invalid-unary-operand-type
        for number, timestamp in list(self.revisions.items())[:-keep or None]:
            _remove_file(self._path_revision(number, timestamp))

    @_coroutinized
    @_locked
    def revert(self, revision=None):
        if self.is_dirty():
            raise qubes.storage.StoragePoolException(
                'Cannot revert: {} is not cleanly stopped'.format(self.vid))
        if revision is None:
            number, timestamp = list(self.revisions.items())[-1]
        else:
            number, timestamp = revision, None
        path_revision = self._path_revision(number, timestamp)
        self._add_revision()
        _rename_file(path_revision, self._path_clean)
        return self

    @_coroutinized
    @_locked
    def resize(self, size):
        ''' Resize a read-write volume; notify any corresponding loop
            devices of the size change.
        '''
        if not self.rw:
            raise qubes.storage.StoragePoolException(
                'Cannot resize: {} is read-only'.format(self.vid))
        for path in (self._path_dirty, self._path_clean):
            with suppress(FileNotFoundError):
                _resize_file(path, size)
                break
        self._size = size
        if path == self._path_dirty:
            _update_loopdev_sizes(self._path_dirty)
        return self

    def export(self):
        if not self.save_on_stop:
            raise NotImplementedError(
                'Cannot export: {} is not save_on_stop'.format(self.vid))
        return self._path_clean

    @_coroutinized
    @_locked
    def import_data(self):
        if not self.save_on_stop:
            raise NotImplementedError(
                'Cannot import_data: {} is not save_on_stop'.format(self.vid))
        _create_sparse_file(self._path_import, self._get_size())
        return self._path_import

    def _import_data_end(self, success):
        (self._commit if success else _remove_file)(self._path_import)
        return self

    import_data_end = _coroutinized(_locked(_import_data_end))

    @_coroutinized
    @_locked
    def import_volume(self, src_volume):
        if not self.save_on_stop:
            return self
        try:
            success = False
            _copy_file(src_volume.export(), self._path_import)
            success = True
        finally:
            self._import_data_end(success)
        return self

    def _path_revision(self, number, timestamp=None):
        if timestamp is None:
            timestamp = self.revisions[number]
        return self._path_clean + '.' + number + '@' + timestamp + 'Z'

    @property
    def _next_revision_number(self):
        numbers = self.revisions.keys()
        if numbers:
            return str(int(list(numbers)[-1]) + 1)
        return '1'

    @property
    def revisions(self):
        prefix = self._path_clean + '.'
        paths = glob.iglob(glob.escape(prefix) + '*@*Z')
        items = (path[len(prefix):-1].split('@') for path in paths)
        return collections.OrderedDict(sorted(items,
                                              key=lambda item: int(item[0])))

    def _get_size(self):
        for path in (self._path_dirty, self._path_clean):
            with suppress(FileNotFoundError):
                self._size = os.path.getsize(path)
                break
        return self._size

    size = property(_locked(_get_size))

    @property
    def usage(self):
        ''' Return volume disk usage from the VM's perspective. It is
            usually much lower from the host's perspective due to CoW.
        '''
        for path in (self._path_dirty, self._path_clean):
            with suppress(FileNotFoundError):
                return os.stat(path).st_blocks * 512
        return 0


@contextmanager
def _replace_file(dst):
    ''' Yield a tempfile whose name starts with dst, creating the last
        directory component if necessary. If the block does not raise
        an exception, safely rename the tempfile to dst.
    '''
    tmp_dir, prefix = os.path.split(dst + '~')
    _make_dir(tmp_dir)
    tmp = tempfile.NamedTemporaryFile(dir=tmp_dir, prefix=prefix, delete=False)
    try:
        yield tmp
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp.close()
        _rename_file(tmp.name, dst)
    except:
        tmp.close()
        _remove_file(tmp.name)
        raise

def _fsync_path(path):
    fd = os.open(path, os.O_RDONLY)  # works for a file or a directory
    try:
        os.fsync(fd)
    finally:
        os.close(fd)

def _make_dir(path):
    ''' mkdir path, ignoring FileExistsError; return whether we
        created it.
    '''
    with suppress(FileExistsError):
        os.mkdir(path)
        _fsync_path(os.path.dirname(path))
        LOGGER.info('Created directory: %s', path)
        return True
    return False

def _remove_file(path):
    with suppress(FileNotFoundError):
        os.remove(path)
        _fsync_path(os.path.dirname(path))
        LOGGER.info('Removed file: %s', path)

def _remove_empty_dir(path):
    try:
        os.rmdir(path)
        _fsync_path(os.path.dirname(path))
        LOGGER.info('Removed empty directory: %s', path)
    except OSError as ex:
        if ex.errno not in (errno.ENOENT, errno.ENOTEMPTY):
            raise

def _rename_file(src, dst):
    os.rename(src, dst)
    dst_dir = os.path.dirname(dst)
    src_dir = os.path.dirname(src)
    _fsync_path(dst_dir)
    if src_dir != dst_dir:
        _fsync_path(src_dir)
    LOGGER.info('Renamed file: %s -> %s', src, dst)

def _resize_file(path, size):
    ''' Resize an existing file. '''
    with open(path, 'rb+') as file:
        file.truncate(size)
        os.fsync(file.fileno())

def _create_sparse_file(path, size):
    ''' Create an empty sparse file. '''
    with _replace_file(path) as tmp:
        tmp.truncate(size)
        LOGGER.info('Created sparse file: %s', tmp.name)

def _update_loopdev_sizes(img):
    ''' Resolve img; update the size of loop devices backed by it. '''
    needle = os.fsencode(os.path.realpath(img)) + b'\n'
    for sys_path in glob.iglob('/sys/block/loop[0-9]*/loop/backing_file'):
        try:
            with open(sys_path, 'rb') as sys_io:
                if sys_io.read() != needle:
                    continue
        except FileNotFoundError:
            continue
        with open('/dev/' + sys_path.split('/')[3], 'rb') as dev_io:
            fcntl.ioctl(dev_io.fileno(), LOOP_SET_CAPACITY)

def _attempt_ficlone(src, dst):
    try:
        fcntl.ioctl(dst.fileno(), FICLONE, src.fileno())
        return True
    except OSError:
        return False

def _copy_file(src, dst):
    ''' Copy src to dst as a reflink if possible, sparse if not. '''
    with _replace_file(dst) as tmp_io:
        with open(src, 'rb') as src_io:
            if _attempt_ficlone(src_io, tmp_io):
                LOGGER.info('Reflinked file: %s -> %s', src, tmp_io.name)
                return True
        LOGGER.info('Copying file: %s -> %s', src, tmp_io.name)
        cmd = 'cp', '--sparse=always', src, tmp_io.name
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           check=False)
        if p.returncode != 0:
            raise qubes.storage.StoragePoolException(str(p))
        return False

def is_supported(dst_dir, src_dir=None):
    ''' Return whether destination directory supports reflink copies
        from source directory. (A temporary file is created in each
        directory, using O_TMPFILE if possible.)
    '''
    if src_dir is None:
        src_dir = dst_dir
    with tempfile.TemporaryFile(dir=src_dir) as src, \
         tempfile.TemporaryFile(dir=dst_dir) as dst:
        src.write(b'foo')  # don't let any fs get clever with empty files
        return _attempt_ficlone(src, dst)
