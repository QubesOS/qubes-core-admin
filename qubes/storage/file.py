#!/usr/bin/python2 -O
# vim: fileencoding=utf-8
#
# The Qubes OS Project, https://www.qubes-os.org/
#
# Copyright (C) 2015  Joanna Rutkowska <joanna@invisiblethingslab.com>
# Copyright (C) 2013-2015  Marek Marczykowski-Górecki
#                              <marmarek@invisiblethingslab.com>
# Copyright (C) 2015  Wojtek Porczyk <woju@invisiblethingslab.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
#
''' This module contains pool implementations backed by file images'''

from __future__ import absolute_import

import os
import os.path
import re
import subprocess

import qubes.devices
import qubes.storage

BLKSIZE = 512


class FilePool(qubes.storage.Pool):
    ''' File based 'original' disk implementation
    '''  # pylint: disable=protected-access
    driver = 'file'

    def __init__(self, revisions_to_keep=1, dir_path=None, **kwargs):
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

    def clone(self, source, target):
        new_dir = os.path.dirname(target.path)
        if target._is_origin or target._is_volume:
            if not os.path.exists:
                os.makedirs(new_dir)
            copy_file(source.path, target.path)
        return target

    def create(self, volume):
        assert isinstance(volume.size, (int, long)) and volume.size > 0, \
            'Volatile volume size must be > 0'
        if volume._is_origin:
            create_sparse_file(volume.path, volume.size)
            create_sparse_file(volume.path_cow, volume.size)
        elif not volume._is_snapshot:
            if volume.source is not None:
                source_path = os.path.join(self.dir_path,
                                           volume.source + '.img')
                copy_file(source_path, volume.path)
            elif volume._is_volatile:
                pass
            else:
                create_sparse_file(volume.path, volume.size)

    def init_volume(self, vm, volume_config):
        volume_config['dir_path'] = self.dir_path
        if os.path.join(self.dir_path, self._vid_prefix(vm)) == vm.dir_path:
            volume_config['backward_comp'] = True

        if 'vid' not in volume_config:
            volume_config['vid'] = os.path.join(
                self._vid_prefix(vm), volume_config['name'])

        try:
            if volume_config['reset_on_start']:
                volume_config['revisions_to_keep'] = 0
        except KeyError:
            pass
        finally:
            if 'revisions_to_keep' not in volume_config:
                volume_config['revisions_to_keep'] = self.revisions_to_keep

        volume = FileVolume(**volume_config)
        self._volumes += [volume]
        return volume

    def is_dirty(self, volume):
        return False  # TODO: How to implement this?

    def resize(self, volume, size):
        ''' Expands volume, throws
            :py:class:`qubst.storage.qubes.storage.StoragePoolException` if
            given size is less than current_size
        '''  # pylint: disable=no-self-use
        if not volume.rw:
            msg = 'Can not resize reađonly volume {!s}'.format(volume)
            raise qubes.storage.StoragePoolException(msg)

        if size <= volume.size:
            raise qubes.storage.StoragePoolException(
                'For your own safety, shrinking of %s is'
                ' disabled. If you really know what you'
                ' are doing, use `truncate` on %s manually.' %
                (volume.name, volume.vid))

        with open(volume.path, 'a+b') as fd:
            fd.truncate(size)

        p = subprocess.Popen(['sudo', 'losetup', '--associated', volume.path],
                             stdout=subprocess.PIPE)
        result = p.communicate()

        m = re.match(r'^(/dev/loop\d+):\s', result[0])
        if m is not None:
            loop_dev = m.group(1)

            # resize loop device
            subprocess.check_call(['sudo', 'losetup', '--set-capacity',
                                   loop_dev])

    def remove(self, volume):
        if not volume.internal:
            return  # do not remove random attached file volumes
        elif volume._is_snapshot:
            return  # no need to remove, because it's just a snapshot
        else:
            _remove_if_exists(volume.path)
            if volume._is_origin:
                _remove_if_exists(volume.path_cow)

    def rename(self, volume, old_name, new_name):
        assert issubclass(volume.__class__, FileVolume)
        subdir, _, volume_path = volume.vid.split('/', 2)

        if volume._is_origin:
            # TODO: Renaming the old revisions
            new_path = os.path.join(self.dir_path, subdir, new_name)
            if not os.path.exists(new_path):
                os.mkdir(new_path, 0755)
            new_volume_path = os.path.join(new_path, self.name + '.img')
            if not volume.backward_comp:
                os.rename(volume.path, new_volume_path)
            new_volume_path_cow = os.path.join(new_path, self.name + '-cow.img')
            if os.path.exists(new_volume_path_cow) and not volume.backward_comp:
                os.rename(volume.path_cow, new_volume_path_cow)

        volume.vid = os.path.join(subdir, new_name, volume_path)

        return volume

    def import_volume(self, dst_pool, dst_volume, src_pool, src_volume):
        msg = "Can not import snapshot volume {!s} in to pool {!s} "
        msg = msg.format(src_volume, self)
        assert not src_volume.snap_on_start, msg
        if dst_volume.save_on_stop:
            copy_file(src_pool.export(src_volume), dst_volume.path)
        return dst_volume

    def commit(self, volume):
        msg = 'Tried to commit a non commitable volume {!r}'.format(volume)
        assert (volume._is_origin or volume._is_volume) and volume.rw, msg

        if volume._is_volume:
            return volume

        if os.path.exists(volume.path_cow):
            old_path = volume.path_cow + '.old'
            os.rename(volume.path_cow, old_path)

        old_umask = os.umask(0o002)
        with open(volume.path_cow, 'w') as f_cow:
            f_cow.truncate(volume.size)
        os.umask(old_umask)
        return volume

    def destroy(self):
        pass

    def export(self, volume):
        return volume.path

    def reset(self, volume):
        ''' Remove and recreate a volatile volume '''
        assert volume._is_volatile, "Not a volatile volume"
        assert isinstance(volume.size, (int, long)) and volume.size > 0, \
            'Volatile volume size must be > 0'

        _remove_if_exists(volume.path)

        with open(volume.path, "w") as f_volatile:
            f_volatile.truncate(volume.size)
        return volume

    def revert(self, volume, revision=None):
        if revision is not None:
            try:
                return volume.revisions[revision]
            except KeyError:
                msg = "Volume {!r} does not have revision {!s}"
                msg = msg.format(volume, revision)
                raise qubes.storage.StoragePoolException(msg)
        else:
            try:
                old_path = volume.revisions.values().pop()
                os.rename(old_path, volume.path_cow)
            except IndexError:
                msg = "Volume {!r} does not have old revisions".format(volume)
                raise qubes.storage.StoragePoolException(msg)

    def setup(self):
        create_dir_if_not_exists(self.dir_path)
        appvms_path = os.path.join(self.dir_path, 'appvms')
        create_dir_if_not_exists(appvms_path)
        vm_templates_path = os.path.join(self.dir_path, 'vm-templates')
        create_dir_if_not_exists(vm_templates_path)

    def start(self, volume):
        if volume._is_snapshot or volume._is_origin:
            _check_path(volume.path)
            try:
                _check_path(volume.path_cow)
            except qubes.storage.StoragePoolException:
                create_sparse_file(volume.path_cow, volume.size)
                _check_path(volume.path_cow)
        elif volume._is_volatile:
            self.reset(volume)
        return volume

    def stop(self, volume):
        if volume.save_on_stop:
            self.commit(volume)
        elif volume._is_volatile:
            _remove_if_exists(volume.path)
        return volume

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

    def verify(self, volume):
        return volume.verify()

    @property
    def volumes(self):
        return self._volumes


class FileVolume(qubes.storage.Volume):
    ''' Parent class for the xen volumes implementation which expects a
        `target_dir` param on initialization.  '''

    def __init__(self, dir_path, backward_comp=False, **kwargs):
        self.dir_path = dir_path
        self.backward_comp = backward_comp
        assert self.dir_path, "dir_path not specified"
        super(FileVolume, self).__init__(**kwargs)

        if self.snap_on_start and self.source is None:
            msg = "snap_on_start specified on {!r} but no volume source set"
            msg = msg.format(self.name)
            raise qubes.storage.StoragePoolException(msg)
        elif not self.snap_on_start and self.source is not None:
            msg = "source specified on {!r} but no snap_on_start set"
            msg = msg.format(self.name)
            raise qubes.storage.StoragePoolException(msg)

        if self._is_snapshot:
            self.path = os.path.join(self.dir_path, self.source + '.img')
            img_name = self.source + '-cow.img'
            self.path_cow = os.path.join(self.dir_path, img_name)
        elif self._is_volume or self._is_volatile:
            self.path = os.path.join(self.dir_path, self.vid + '.img')
        elif self._is_origin:
            self.path = os.path.join(self.dir_path, self.vid + '.img')
            img_name = self.vid + '-cow.img'
            self.path_cow = os.path.join(self.dir_path, img_name)
        else:
            assert False, 'This should not happen'

    def verify(self):
        ''' Verifies the volume. '''
        if not os.path.exists(self.path) and not self._is_volatile:
            msg = 'Missing image file: {!s}.'.format(self.path)
            raise qubes.storage.StoragePoolException(msg)
        return True

    @property
    def script(self):
        if self._is_volume or self._is_volatile:
            return None
        elif self._is_origin:
            return 'block-origin'
        elif self._is_origin_snapshot or self._is_snapshot:
            return 'block-snapshot'

    def block_device(self):
        ''' Return :py:class:`qubes.devices.BlockDevice` for serialization in
            the libvirt XML template as <disk>.
        '''
        path = self.path
        if self._is_origin or self._is_snapshot:
            path += ":" + self.path_cow
        return qubes.devices.BlockDevice(path, self.name, self.script, self.rw,
                                         self.domain, self.devtype)

    @property
    def revisions(self):
        if not hasattr(self, 'path_cow'):
            return {}

        old_revision = self.path_cow + '.old'  # pylint: disable=no-member

        if not os.path.exists(old_revision):
            return {}
        else:
            seconds = os.path.getctime(old_revision)
            iso_date = qubes.storage.isodate(seconds).split('.', 1)[0]
            return {iso_date: old_revision}

    @property
    def usage(self):
        ''' Returns the actualy used space '''
        return get_disk_usage(self.vid)

    @property
    def _is_volatile(self):
        ''' Internal helper. Useful for differentiating volume handling '''
        return not self.snap_on_start and not self.save_on_stop

    @property
    def _is_origin(self):
        ''' Internal helper. Useful for differentiating volume handling '''
        # pylint: disable=line-too-long
        return not self.snap_on_start and self.save_on_stop and self.revisions_to_keep > 0  # NOQA

    @property
    def _is_snapshot(self):
        ''' Internal helper. Useful for differentiating volume handling '''
        return self.snap_on_start and not self.save_on_stop

    @property
    def _is_origin_snapshot(self):
        ''' Internal helper. Useful for differentiating volume handling '''
        return self.snap_on_start and self.save_on_stop

    @property
    def _is_volume(self):
        ''' Internal helper. Usefull for differentiating volume handling '''
        # pylint: disable=line-too-long
        return not self.snap_on_start and self.save_on_stop and self.revisions_to_keep == 0  # NOQA

def create_sparse_file(path, size):
    ''' Create an empty sparse file '''
    if os.path.exists(path):
        raise IOError("Volume %s already exists", path)
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

    This function tries estiate real disk usage. See documentation of
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
        cmd = ['sudo', 'cp', '--sparse=auto',
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
