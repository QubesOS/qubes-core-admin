#
# The Qubes OS Project, http://www.qubes-os.org
#
# Copyright (C) 2010-2015  Joanna Rutkowska <joanna@invisiblethingslab.com>
# Copyright (C) 2015       Wojtek Porczyk <woju@invisiblethingslab.com>
# Copyright (C) 2016       Bahtiar `kalkin-` Gadimov <bahtiar@gadimov.de>
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

''' This module contains pool implementations for different OS kernels. '''

import os

from qubes.storage import Pool, StoragePoolException, Volume


class LinuxModules(Volume):
    ''' A volume representing a ro linux kernel '''
    rw = False

    def __init__(self, target_dir, kernel_version, **kwargs):
        kwargs['vid'] = ''
        kwargs['source'] = self
        super(LinuxModules, self).__init__(**kwargs)
        self._kernel_version = kernel_version
        self.target_dir = target_dir

    @property
    def vid(self):
        if callable(self._kernel_version):
            return self._kernel_version()
        return self._kernel_version

    @vid.setter
    def vid(self, value):
        # ignore
        pass

    @property
    def kernels_dir(self):
        kernel_version = self.vid
        if kernel_version is None:
            return None
        return os.path.join(self.target_dir, kernel_version)

    @property
    def path(self):
        kernels_dir = self.kernels_dir
        if kernels_dir is None:
            return None
        return os.path.join(kernels_dir, 'modules.img')

    @property
    def vmlinuz(self):
        kernels_dir = self.kernels_dir
        if kernels_dir is None:
            return None
        return os.path.join(kernels_dir, 'vmlinuz')

    @property
    def initramfs(self):
        kernels_dir = self.kernels_dir
        if kernels_dir is None:
            return None
        return os.path.join(kernels_dir, 'initramfs')

    @property
    def revisions(self):
        return {}

    def block_device(self):
        if self.vid is not None:
            return super().block_device()


class LinuxKernel(Pool):
    ''' Provides linux kernels '''
    driver = 'linux-kernel'

    def __init__(self, name=None, dir_path=None):
        assert dir_path, 'Missing dir_path'
        super(LinuxKernel, self).__init__(name=name)
        self.dir_path = dir_path

    def init_volume(self, vm, volume_config):
        assert not volume_config['rw']

        volume = LinuxModules(self.dir_path, lambda: vm.kernel, **volume_config)

        return volume

    def is_dirty(self, volume):
        return False

    def clone(self, source, target):
        return target

    def create(self, volume):
        return volume

    def commit(self, volume):
        return volume

    @property
    def config(self):
        return {
            'name': self.name,
            'dir_path': self.dir_path,
            'driver': LinuxKernel.driver,
        }

    def destroy(self):
        pass

    def export(self, volume):
        return volume.path

    def import_volume(self, dst_pool, dst_volume, src_pool, src_volume):
        pass

    def is_outdated(self, volume):
        return False

    def remove(self, volume):
        pass

    def rename(self, volume, old_name, new_name):
        return volume

    def setup(self):
        pass

    def start(self, volume):
        path = volume.path
        if path and not os.path.exists(path):
            raise StoragePoolException('Missing kernel modules: %s' % path)

        return volume

    def stop(self, volume):
        pass

    def verify(self, volume):
        if volume.vid is not None:
            _check_path(volume.path)
            _check_path(volume.vmlinuz)
            _check_path(volume.initramfs)

    @property
    def volumes(self):
        ''' Return all known kernel volumes '''
        return [LinuxModules(self.dir_path,
                             kernel_version,
                             pool=self.name,
                             name=kernel_version,
                             internal=True,
                             rw=False
                             )
                for kernel_version in os.listdir(self.dir_path)]


def _check_path(path):
    ''' Raise an :py:class:`qubes.storage.StoragePoolException` if ``path`` does
        not exist.
    '''
    if not os.path.exists(path):
        raise StoragePoolException('Missing file: %s' % path)
