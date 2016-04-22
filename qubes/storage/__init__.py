#!/usr/bin/python2 -O
# vim: fileencoding=utf-8

#
# The Qubes OS Project, https://www.qubes-os.org/
#
# Copyright (C) 2013-2015  Joanna Rutkowska <joanna@invisiblethingslab.com>
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
""" Qubes storage system"""

from __future__ import absolute_import

import os
import os.path
import shutil

import pkg_resources
import qubes
import qubes.exc
import qubes.utils
from qubes.devices import BlockDevice

import lxml.etree

STORAGE_ENTRY_POINT = 'qubes.storage'


class StoragePoolException(qubes.exc.QubesException):
    pass


class Volume(object):
    ''' Encapsulates all data about a volume for serialization to qubes.xml and
        libvirt config.
    '''

    devtype = 'disk'
    domain = None
    path = None
    rw = True
    script = None
    usage = 0

    def __init__(self,
                 name=None,
                 pool=None,
                 volume_type=None,
                 vid=None,
                 size=0):
        assert name and pool and volume_type
        self.name = str(name)
        self.pool = str(pool)
        self.vid = vid
        self.size = size
        self.volume_type = volume_type

    def __xml__(self):
        return lxml.etree.Element('volume', **self.config)

    @property
    def config(self):
        ''' return config data for serialization to qubes.xml '''
        return {'name': self.name,
                'pool': self.pool,
                'volume_type': self.volume_type}

    def __str__(self):
        return str({'name': self.name, 'pool': self.pool, 'vid': self.vid})

    def block_device(self):
        ''' Return :py:class:`qubes.devices.BlockDevice` for serialization in
            the libvirt XML template as <disk>.
        '''
        return BlockDevice(self.path, self.name, self.script, self.rw,
                           self.domain, self.devtype)


class Storage(object):
    ''' Class for handling VM virtual disks.

    This is base class for all other implementations, mostly with Xen on Linux
    in mind.
    '''

    def __init__(self, vm):
        #: Domain for which we manage storage
        self.vm = vm
        self.log = self.vm.log
        #: Additional drive (currently used only by HVM)
        self.drive = None
        self.pools = {}
        if hasattr(vm, 'volume_config'):
            for name, conf in self.vm.volume_config.items():
                assert 'pool' in conf, "Pool missing in volume_config" % str(
                    conf)
                pool = self.vm.app.get_pool(conf['pool'])
                self.vm.volumes[name] = pool.init_volume(self.vm, conf)
                self.pools[name] = pool

    @property
    def kernels_dir(self):
        '''Directory where kernel resides.

        If :py:attr:`self.vm.kernel` is :py:obj:`None`, the this points inside
        :py:attr:`self.vm.dir_path`
        '''
        assert 'kernel' in self.vm.volumes, "VM has no kernel pool"
        return self.vm.volumes['kernel'].kernels_dir

    def get_disk_utilization(self):
        ''' Returns summed up disk utilization for all domain volumes '''
        result = 0
        for volume in self.vm.volumes.values():
            result += volume.usage
        return result

    # TODO Remove this wrapper
    def get_disk_utilization_private_img(self):
        # pylint: disable=invalid-name,missing-docstring
        return self.vm.volume['private'].usage

    # TODO Remove this wrapper
    def get_private_img_sz(self):
        # :pylint: disable=missing-docstring
        return self.vm.volume['private'].size

    def resize(self, volume, size):
        ''' Resize volume '''
        self.get_pool(volume).resize(volume, size)

    # TODO rename it to create()
    def create_on_disk(self, source_template=None):
        # :pylint: disable=missing-docstring
        if source_template is None and hasattr(self.vm, 'template'):
            source_template = self.vm.template

        old_umask = os.umask(002)

        self.log.info('Creating directory: {0}'.format(self.vm.dir_path))
        os.makedirs(self.vm.dir_path)
        for name, volume in self.vm.volumes.items():
            source_volume = None
            if source_template and hasattr(source_template, 'volumes'):
                source_volume = source_template.volumes[name]
            self.get_pool(volume).create(volume, source_volume=source_volume)

        os.umask(old_umask)

    def clone(self, src_vm):
        self.vm.log.info('Creating directory: {0}'.format(self.vm.dir_path))
        if not os.path.exists(self.vm.dir_path):
            self.log.info('Creating directory: {0}'.format(self.vm.dir_path))
            os.makedirs(self.vm.dir_path)
        for name, target in self.vm.volumes.items():
            pool = self.get_pool(target)
            source = src_vm.volumes[name]
            volume = pool.clone(source, target)
            assert volume, "%s.clone() returned '%s'" % (pool.__class__,
                                                         volume)
            self.vm.volumes[name] = volume

    def rename(self, old_name, new_name):
        ''' Notify the pools that the domain was renamed '''
        volumes = self.vm.volumes
        for name, volume in volumes.items():
            pool = self.get_pool(volume)
            volumes[name] = pool.rename(volume, old_name, new_name)

    def verify_files(self):
        '''Verify that the storage is sane.

        On success, returns normally. On failure, raises exception.
        '''
        if not os.path.exists(self.vm.dir_path):
            raise qubes.exc.QubesVMError(
                self.vm,
                'VM directory does not exist: {}'.format(self.vm.dir_path))

    def remove(self):
        for name, volume in self.vm.volumes.items():
            self.log.info('Removing volume %s: %s' % (name, volume.vid))
            self.get_pool(volume).remove(volume)
        shutil.rmtree(self.vm.dir_path)

    def start(self):
        ''' Execute the start method on each pool '''
        for volume in self.vm.volumes.values():
            self.get_pool(volume).start(volume)

    def stop(self):
        ''' Execute the start method on each pool '''
        for volume in self.vm.volumes.values():
            self.get_pool(volume).stop(volume)

    def get_pool(self, volume):
        ''' Helper function '''
        assert isinstance(volume, Volume), "You need to pass a Volume"
        return self.pools[volume.name]

    def commit_template_changes(self):
        for volume in self.vm.volumes.values():
            if volume.volume_type == 'origin':
                self.get_pool(volume).commit_template_changes(volume)


class Pool(object):
    ''' A Pool is used to manage different kind of volumes (File
        based/LVM/Btrfs/...).

        3rd Parties providing own storage implementations will need to extend
        this class.
    '''
    private_img_size = qubes.config.defaults['private_img_size']
    root_img_size = qubes.config.defaults['root_img_size']

    def __init__(self, name=None, **kwargs):
        # :pylint: disable=unused-argument
        assert name, "Pool name is missing"
        self.name = name
        kwargs['name'] = self.name

    def __xml__(self):
        return lxml.etree.Element('pool', **self.config)

    def create(self, volume, source_volume):
        ''' Create the given volume on disk or copy from provided
            `source_volume`.
        '''
        raise NotImplementedError("Pool %s has create() not implemented" %
                                  self.name)

    def commit_template_changes(self, volume):
        ''' Update origin device '''
        raise NotImplementedError(
            "Pool %s has commit_template_changes() not implemented" %
            self.name)

    @property
    def config(self):
        ''' Returns the pool config to be written to qubes.xml '''
        raise NotImplementedError("Pool %s has config() not implemented" %
                                  self.name)

    def clone(self, source, target):
        ''' Clone volume '''
        raise NotImplementedError("Pool %s has clone() not implemented" %
                                  self.name)

    def destroy(self):
        raise NotImplementedError("Pool %s has destroy() not implemented" %
                                  self.name)

    def remove(self, volume):
        ''' Remove volume'''
        raise NotImplementedError("Pool %s has remove() not implemented" %
                                  self.name)

    def rename(self, volume, old_name, new_name):
        ''' Called when the domain changes its name '''
        raise NotImplementedError("Pool %s has rename() not implemented" %
                                  self.name)

    def start(self, volume):
        ''' Do what ever is needed on start '''
        raise NotImplementedError("Pool %s has start() not implemented" %
                                  self.name)

    def setup(self):
        raise NotImplementedError("Pool %s has setup() not implemented" %
                                  self.name)

    def stop(self, volume):
        ''' Do what ever is needed on stop'''
        raise NotImplementedError("Pool %s has stop() not implemented" %
                                  self.name)

    def init_volume(self, volume_config):
        ''' Initialize a :py:class:`qubes.storage.Volume` from `volume_config`.
        '''
        raise NotImplementedError("Pool %s has init_volume() not implemented" %
                                  self.name)


def pool_drivers():
    """ Return a list of EntryPoints names """
    return [ep.name
            for ep in pkg_resources.iter_entry_points(STORAGE_ENTRY_POINT)]
