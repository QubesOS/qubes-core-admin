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

import collections
import errno
import fcntl
import glob
import logging
import os
import re
import subprocess
import tempfile
from contextlib import contextmanager, suppress

import qubes.storage

BLKSIZE = 512
FICLONE = 1074041865  # see ioctl_ficlone manpage
LOGGER = logging.getLogger('qubes.storage.reflink')


class ReflinkPool(qubes.storage.Pool):
    driver = 'file-reflink'
    _known_dir_path_prefixes = ['appvms', 'vm-templates']

    def __init__(self, dir_path, setup_check='yes', revisions_to_keep=1,
                 **kwargs):
        super().__init__(revisions_to_keep=revisions_to_keep, **kwargs)
        self._volumes = {}
        self.dir_path = os.path.abspath(dir_path)
        self.setup_check = qubes.property.bool(None, None, setup_check)

    def setup(self):
        created = _make_dir(self.dir_path)
        if self.setup_check and not is_reflink_supported(self.dir_path):
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

class ReflinkVolume(qubes.storage.Volume):
    def create(self):
        if self.save_on_stop and not self.snap_on_start:
            _create_sparse_file(self._path_clean, self.size)
        return self

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

    def remove(self):
        ''' Drop volume object from pool; remove volume images from
            oldest to newest; remove empty VM directory.
        '''
        self.pool._volumes.pop(self, None)  # pylint: disable=protected-access
        self._prune_revisions(keep=0)
        _remove_file(self._path_clean)
        _remove_file(self._path_dirty)
        _remove_empty_dir(os.path.dirname(self._path_dirty))
        return self

    def is_outdated(self):
        if self.snap_on_start:
            with suppress(FileNotFoundError):
                # pylint: disable=protected-access
                return (os.path.getmtime(self.source._path_clean) >
                        os.path.getmtime(self._path_clean))
        return False

    def is_dirty(self):
        return self.save_on_stop and os.path.exists(self._path_dirty)

    def start(self):
        if self.is_dirty():  # implies self.save_on_stop
            return self
        if self.snap_on_start:
            # pylint: disable=protected-access
            _copy_file(self.source._path_clean, self._path_clean)
        if self.snap_on_start or self.save_on_stop:
            _copy_file(self._path_clean, self._path_dirty)
        else:
            _create_sparse_file(self._path_dirty, self.size)
        return self

    def stop(self):
        if self.save_on_stop:
            self._commit()
        else:
            _remove_file(self._path_dirty)
            _remove_file(self._path_clean)
        return self

    def _commit(self):
        self._add_revision()
        self._prune_revisions()
        _rename_file(self._path_dirty, self._path_clean)

    def _add_revision(self):
        if self.revisions_to_keep == 0:
            return
        if _get_file_disk_usage(self._path_clean) == 0:
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

    def revert(self, revision=None):
        if revision is None:
            number, timestamp = list(self.revisions.items())[-1]
        else:
            number, timestamp = revision, None
        path_revision = self._path_revision(number, timestamp)
        self._add_revision()
        _rename_file(path_revision, self._path_clean)
        return self

    def resize(self, size):
        ''' Expand a read-write volume image; notify any corresponding
            loop devices of the size change.
        '''
        if not self.rw:
            raise qubes.storage.StoragePoolException(
                'Cannot resize: {} is read-only'.format(self.vid))

        if size < self.size:
            raise qubes.storage.StoragePoolException(
                'For your own safety, shrinking of {} is disabled'
                ' ({} < {}). If you really know what you are doing,'
                ' use "truncate" manually.'.format(self.vid, size, self.size))

        try:  # assume volume is not (cleanly) stopped ...
            _resize_file(self._path_dirty, size)
        except FileNotFoundError:  # ... but it actually is.
            _resize_file(self._path_clean, size)

        self.size = size

        # resize any corresponding loop devices
        out = _cmd('losetup', '--associated', self._path_dirty)
        for match in re.finditer(br'^(/dev/loop[0-9]+): ', out, re.MULTILINE):
            loop_dev = match.group(1).decode('ascii')
            _cmd('losetup', '--set-capacity', loop_dev)

        return self

    def _require_save_on_stop(self, method_name):
        if not self.save_on_stop:
            raise NotImplementedError(
                'Cannot {}: {} is not save_on_stop'.format(
                    method_name, self.vid))

    def export(self):
        self._require_save_on_stop('export')
        return self._path_clean

    def import_data(self):
        self._require_save_on_stop('import_data')
        _create_sparse_file(self._path_dirty, self.size)
        return self._path_dirty

    def import_data_end(self, success):
        if success:
            self._commit()
        else:
            _remove_file(self._path_dirty)
        return self

    def import_volume(self, src_volume):
        self._require_save_on_stop('import_volume')
        try:
            _copy_file(src_volume.export(), self._path_dirty)
        except:
            self.import_data_end(False)
            raise
        self.import_data_end(True)
        return self

    def _path_revision(self, number, timestamp=None):
        if timestamp is None:
            timestamp = self.revisions[number]
        return self._path_clean + '.' + number + '@' + timestamp + 'Z'

    @property
    def _path_clean(self):
        return os.path.join(self.pool.dir_path, self.vid + '.img')

    @property
    def _path_dirty(self):
        return os.path.join(self.pool.dir_path, self.vid + '-dirty.img')

    @property
    def path(self):
        return self._path_dirty

    @property
    def _next_revision_number(self):
        numbers = self.revisions.keys()
        if numbers:
            return str(int(list(numbers)[-1]) + 1)
        return '1'

    @property
    def revisions(self):
        prefix = self._path_clean + '.'
        paths = glob.glob(glob.escape(prefix) + '*@*Z')
        items = sorted((path[len(prefix):-1].split('@') for path in paths),
                       key=lambda item: int(item[0]))
        return collections.OrderedDict(items)

    @property
    def usage(self):
        ''' Return volume disk usage from the VM's perspective. It is
            usually much lower from the host's perspective due to CoW.
        '''
        with suppress(FileNotFoundError):
            return _get_file_disk_usage(self._path_dirty)
        with suppress(FileNotFoundError):
            return _get_file_disk_usage(self._path_clean)
        return 0


@contextmanager
def _replace_file(dst):
    ''' Yield a tempfile whose name starts with dst, creating the last
        directory component if necessary. If the block does not raise
        an exception, flush+fsync the tempfile and rename it to dst.
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

def _get_file_disk_usage(path):
    ''' Return real disk usage (not logical file size) of a file. '''
    return os.stat(path).st_blocks * BLKSIZE

def _fsync_dir(path):
    dir_fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)

def _make_dir(path):
    ''' mkdir path, ignoring FileExistsError; return whether we
        created it.
    '''
    with suppress(FileExistsError):
        os.mkdir(path)
        _fsync_dir(os.path.dirname(path))
        LOGGER.info('Created directory: %s', path)
        return True
    return False

def _remove_file(path):
    with suppress(FileNotFoundError):
        os.remove(path)
        _fsync_dir(os.path.dirname(path))
        LOGGER.info('Removed file: %s', path)

def _remove_empty_dir(path):
    try:
        os.rmdir(path)
        _fsync_dir(os.path.dirname(path))
        LOGGER.info('Removed empty directory: %s', path)
    except OSError as ex:
        if ex.errno not in (errno.ENOENT, errno.ENOTEMPTY):
            raise

def _rename_file(src, dst):
    os.rename(src, dst)
    dst_dir = os.path.dirname(dst)
    src_dir = os.path.dirname(src)
    _fsync_dir(dst_dir)
    if src_dir != dst_dir:
        _fsync_dir(src_dir)
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

def _copy_file(src, dst):
    ''' Copy src to dst as a reflink if possible, sparse if not. '''
    if not os.path.exists(src):
        raise FileNotFoundError(src)
    with _replace_file(dst) as tmp:
        LOGGER.info('Copying file: %s -> %s', src, tmp.name)
        _cmd('cp', '--sparse=always', '--reflink=auto', src, tmp.name)

def _cmd(*args):
    ''' Run command until finished; return stdout (as bytes) if it
        exited 0. Otherwise, raise a detailed StoragePoolException.
    '''
    try:
        return subprocess.run(args, check=True,
                              stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE).stdout
    except subprocess.CalledProcessError as ex:
        msg = '{} err={!r} out={!r}'.format(ex, ex.stderr, ex.stdout)
        raise qubes.storage.StoragePoolException(msg) from ex

def is_reflink_supported(dst_dir, src_dir=None):
    ''' Return whether destination directory supports reflink copies
        from source directory. (A temporary file is created in each
        directory, using O_TMPFILE if possible.)
    '''
    if src_dir is None:
        src_dir = dst_dir
    dst = tempfile.TemporaryFile(dir=dst_dir)
    src = tempfile.TemporaryFile(dir=src_dir)
    src.write(b'foo')  # don't let any filesystem get clever with empty files

    try:
        fcntl.ioctl(dst.fileno(), FICLONE, src.fileno())
        return True
    except OSError:
        return False
