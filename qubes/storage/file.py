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

from __future__ import absolute_import

import os
import os.path
import re
import subprocess

import qubes.storage

BLKSIZE = 512


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

    def __init__(self, revisions_to_keep=1, dir_path=None, **kwargs):
        self._revisions_to_keep = 0
        super(FilePool, self).__init__(revisions_to_keep=revisions_to_keep,
                                       **kwargs)
        assert dir_path, "No pool dir_path specified"
        self.dir_path = os.path.normpath(dir_path)
        self._volumes = []

    @property
    def config(self):
        return {
            'name': self.name,
            'dir_path': self.dir_path,
            'driver': FilePool.driver,
            'revisions_to_keep': self.revisions_to_keep
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

    def destroy(self):
        pass

    def setup(self):
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

class FileVolume(qubes.storage.Volume):
    ''' Parent class for the xen volumes implementation which expects a
        `target_dir` param on initialization.  '''

    def __init__(self, dir_path, **kwargs):
        self.dir_path = dir_path
        assert self.dir_path, "dir_path not specified"
        self._revisions_to_keep = 0
        super(FileVolume, self).__init__(**kwargs)

        if self.snap_on_start:
            img_name = self.source.vid + '-cow.img'
            self.path_source_cow = os.path.join(self.dir_path, img_name)

    @property
    def revisions_to_keep(self):
        return self._revisions_to_keep

    @revisions_to_keep.setter
    def revisions_to_keep(self, value):
        if int(value) > 1:
            raise NotImplementedError(
                'FileVolume supports maximum 1 volume revision to keep')
        self._revisions_to_keep = int(value)

    def create(self):
        assert isinstance(self.size, int) and self.size > 0, \
            'Volume size must be > 0'
        if not self.snap_on_start:
            create_sparse_file(self.path, self.size)

    def remove(self):
        if not self.snap_on_start:
            _remove_if_exists(self.path)
        if self.snap_on_start or self.save_on_stop:
            _remove_if_exists(self.path_cow)

    def is_dirty(self):
        if not self.save_on_stop:
            return False
        if os.path.exists(self.path_cow):
            stat = os.stat(self.path_cow)
            return stat.st_blocks > 0
        return False

    def resize(self, size):
        ''' Expands volume, throws
            :py:class:`qubst.storage.qubes.storage.StoragePoolException` if
            given size is less than current_size
        '''  # pylint: disable=no-self-use
        if not self.rw:
            msg = 'Can not resize reađonly volume {!s}'.format(self)
            raise qubes.storage.StoragePoolException(msg)

        if size < self.size:
            raise qubes.storage.StoragePoolException(
                'For your own safety, shrinking of %s is'
                ' disabled. If you really know what you'
                ' are doing, use `truncate` on %s manually.' %
                (self.name, self.vid))

        with open(self.path, 'a+b') as fd:
            fd.truncate(size)

        p = subprocess.Popen(['losetup', '--associated', self.path],
                             stdout=subprocess.PIPE)
        result = p.communicate()

        m = re.match(r'^(/dev/loop\d+):\s', result[0].decode())
        if m is not None:
            loop_dev = m.group(1)

            # resize loop device
            subprocess.check_call(['losetup', '--set-capacity',
                                   loop_dev])
        self.size = size

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

    def export(self):
        # FIXME: this should rather return snapshot(self.path, self.path_cow)
        #  if domain is running
        return self.path

    def import_volume(self, src_volume):
        msg = "Can not import snapshot volume {!s} in to pool {!s} "
        msg = msg.format(src_volume, self)
        assert not src_volume.snap_on_start, msg
        if self.save_on_stop:
            _remove_if_exists(self.path)
            copy_file(src_volume.export(), self.path)
        return self


    def import_data(self):
        return self.path

    def reset(self):
        ''' Remove and recreate a volatile volume '''
        assert not self.snap_on_start and not self.save_on_stop, \
            "Not a volatile volume"
        assert isinstance(self.size, int) and self.size > 0, \
            'Volatile volume size must be > 0'

        _remove_if_exists(self.path)
        create_sparse_file(self.path, self.size)
        return self

    def start(self):
        if not self.save_on_stop and not self.snap_on_start:
            self.reset()
        else:
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
        return self

    def stop(self):
        if self.save_on_stop:
            self.commit()
        elif self.snap_on_start:
            _remove_if_exists(self.path_cow)
        else:
            _remove_if_exists(self.path)
        return self

    @property
    def path(self):
        if self.snap_on_start:
            return os.path.join(self.dir_path, self.source.vid + '.img')
        return os.path.join(self.dir_path, self.vid + '.img')

    @property
    def path_cow(self):
        img_name = self.vid + '-cow.img'
        return os.path.join(self.dir_path, img_name)

    def verify(self):
        ''' Verifies the volume. '''
        if not os.path.exists(self.path) and \
                (self.snap_on_start or self.save_on_stop):
            msg = 'Missing image file: {!s}.'.format(self.path)
            raise qubes.storage.StoragePoolException(msg)
        return True

    @property
    def script(self):
        if not self.snap_on_start and not self.save_on_stop:
            return None
        elif not self.snap_on_start and self.save_on_stop:
            return 'block-origin'
        elif self.snap_on_start:
            return 'block-snapshot'
        return None

    def block_device(self):
        ''' Return :py:class:`qubes.storage.BlockDevice` for serialization in
            the libvirt XML template as <disk>.
        '''
        path = self.path
        if self.snap_on_start:
            path += ":" + self.path_source_cow
        if self.snap_on_start or self.save_on_stop:
            path += ":" + self.path_cow
        return qubes.storage.BlockDevice(path, self.name, self.script, self.rw,
                                         self.domain, self.devtype)

    @property
    def revisions(self):
        if not hasattr(self, 'path_cow'):
            return {}

        old_revision = self.path_cow + '.old'  # pylint: disable=no-member

        if not os.path.exists(old_revision):
            return {}

        seconds = os.path.getctime(old_revision)
        iso_date = qubes.storage.isodate(seconds).split('.', 1)[0]
        return {'old': iso_date}

    @property
    def usage(self):
        ''' Returns the actualy used space '''
        usage = 0
        if self.save_on_stop or self.snap_on_start:
            usage = get_disk_usage(self.path_cow)
        if self.save_on_stop or not self.snap_on_start:
            usage += get_disk_usage(self.path)
        return usage



def create_sparse_file(path, size):
    ''' Create an empty sparse file '''
    if os.path.exists(path):
        raise IOError("Volume %s already exists" % path)
    parent_dir = os.path.dirname(path)
    if not os.path.exists(parent_dir):
        os.makedirs(parent_dir)
    with open(path, 'a+b') as fh:
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
    if os.path.exists(path):
        os.remove(path)


def _check_path(path):
    ''' Raise an StoragePoolException if ``path`` does not exist'''
    if not os.path.exists(path):
        msg = 'Missing image file: %s' % path
        raise qubes.storage.StoragePoolException(msg)
