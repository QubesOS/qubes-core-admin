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
import string  # pylint: disable=deprecated-module
import time
from datetime import datetime

import lxml.etree
import pkg_resources
import qubes
import qubes.devices
import qubes.exc
import qubes.utils

STORAGE_ENTRY_POINT = 'qubes.storage'


class StoragePoolException(qubes.exc.QubesException):
    ''' A general storage exception '''
    pass


class Volume(object):
    ''' Encapsulates all data about a volume for serialization to qubes.xml and
        libvirt config.


        Keep in mind!
        volatile        = not snap_on_start and not save_on_stop
        snapshot        =     snap_on_start and not save_on_stop
        origin          = not snap_on_start and     save_on_stop
        origin_snapshot =     snap_on_start and     save_on_stop
    '''

    devtype = 'disk'
    domain = None
    path = None
    script = None
    usage = 0

    def __init__(self, name, pool, vid, internal=False, removable=False,
            revisions_to_keep=0, rw=False, save_on_stop=False, size=0,
            snap_on_start=False, source=None, **kwargs):
        ''' Initialize a volume.

            :param str name: The domain name
            :param str pool: The pool name
            :param str vid:  Volume identifier needs to be unique in pool
            :param bool internal: If `True` volume is hidden when qvm-block ls
                is used
            :param bool removable: If `True` volume can be detached from vm at
                run time
            :param int revisions_to_keep: Amount of revisions to keep around
            :param bool rw: If true volume will be mounted read-write
            :param bool snap_on_start: Create a snapshot from source on start
            :param bool save_on_stop: Write changes to disk in vm.stop()
            :param str source: Vid of other volume in same pool
            :param str/int size: Size of the volume

        '''

        super(Volume, self).__init__(**kwargs)

        self.name = str(name)
        self.pool = str(pool)
        self.internal = internal
        self.removable = removable
        self.revisions_to_keep = revisions_to_keep
        self.rw = rw
        self.save_on_stop = save_on_stop
        self.size = int(size)
        self.snap_on_start = snap_on_start
        self.source = source
        self.vid = vid

    def __eq__(self, other):
        return other.pool == self.pool and other.vid == self.vid

    def __hash__(self):
        return hash('%s:%s' % (self.pool, self.vid))

    def __neq__(self, other):
        return not self.__eq__(other)

    def __repr__(self):
        return '{!r}'.format(self.pool + ':' + self.vid)

    def __str__(self):
        return str(self.vid)

    def __xml__(self):
        config = _sanitize_config(self.config)
        return lxml.etree.Element('volume', **config)

    def block_device(self):
        ''' Return :py:class:`qubes.devices.BlockDevice` for serialization in
            the libvirt XML template as <disk>.
        '''
        return qubes.devices.BlockDevice(self.path, self.name, self.script,
                                         self.rw, self.domain, self.devtype)

    @property
    def revisions(self):
        ''' Returns a `dict` containing revision identifiers and paths '''
        msg = "{!s} has revisions not implemented".format(self.__class__)
        raise NotImplementedError(msg)

    @property
    def config(self):
        ''' return config data for serialization to qubes.xml '''
        result = {'name': self.name, 'pool': self.pool, 'vid': self.vid, }

        if self.internal:
            result['internal'] = self.internal

        if self.removable:
            result['removable'] = self.removable

        if self.revisions_to_keep:
            result['revisions_to_keep'] = self.revisions_to_keep

        if self.rw:
            result['rw'] = self.rw

        if self.save_on_stop:
            result['save_on_stop'] = self.save_on_stop

        if self.size:
            result['size'] = self.size

        if self.snap_on_start:
            result['snap_on_start'] = self.snap_on_start

        if self.source:
            result['source'] = self.source

        return result


class Storage(object):
    ''' Class for handling VM virtual disks.

    This is base class for all other implementations, mostly with Xen on Linux
    in mind.
    '''

    AVAILABLE_FRONTENDS = set(['xvd' + c for c in string.ascii_lowercase])

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
                if 'volume_type' in conf:
                    conf = self._migrate_config(conf)

                pool = self.vm.app.get_pool(conf['pool'])
                self.vm.volumes[name] = pool.init_volume(self.vm, conf)
                self.pools[name] = pool

    def _migrate_config(self, conf):
        ''' Migrates from the old config style to new
        '''  # FIXME: Remove this compatibility hack
        assert 'volume_type' in conf
        _type = conf['volume_type']
        old_volume_types = [
            'read-write', 'read-only', 'origin', 'snapshot', 'volatile'
        ]
        msg = "Volume {!s} has unknown type {!s}".format(conf['name'], _type)
        assert conf['volume_type'] in old_volume_types, msg
        if _type == 'origin':
            conf['rw'] = True
            conf['source'] = None
            conf['save_on_stop'] = True
            conf['revisions_to_keep'] = 1
        elif _type == 'snapshot':
            conf['rw'] = False
            if conf['pool'] == 'default':
                template_vid = os.path.join('vm-templates',
                    self.vm.template.name, conf['name'])
            elif conf['pool'] == 'qubes_dom0':
                template_vid = os.path.join(
                    'qubes_dom0', self.vm.template.name + '-' + conf['name'])
            conf['source'] = template_vid
            conf['snap_on_start'] = True
        elif _type == 'read-write':
            conf['rw'] = True
            conf['save_on_stop'] = True
            conf['revisions_to_keep'] = 0
        elif _type == 'read-only':
            conf['rw'] = False
            conf['snap_on_start'] = True
            conf['save_on_stop'] = False
            conf['revisions_to_keep'] = 0
        elif _type == 'volatile':
            conf['snap_on_start'] = False
            conf['save_on_stop'] = False
            conf['revisions_to_keep'] = 0
        del conf['volume_type']
        return conf

    def attach(self, volume, rw=False):
        ''' Attach a volume to the domain '''
        assert self.vm.is_running()

        if self._is_already_attached(volume):
            self.vm.log.info("{!r} already attached".format(volume))
            return

        try:
            frontend = self.unused_frontend()
        except IndexError:
            raise StoragePoolException("No unused frontend found")
        disk = lxml.etree.Element("disk")
        disk.set('type', 'block')
        disk.set('device', 'disk')
        lxml.etree.SubElement(disk, 'driver').set('name', 'phy')
        lxml.etree.SubElement(disk, 'source').set('dev', '/dev/%s' % volume.vid)
        lxml.etree.SubElement(disk, 'target').set('dev', frontend)
        if not rw:
            lxml.etree.SubElement(disk, 'readonly')

        if volume.domain is not None:
            lxml.etree.SubElement(disk, 'backenddomain').set(
                'name', volume.domain.name)

        xml_string = lxml.etree.tostring(disk, encoding='utf-8')
        self.vm.libvirt_domain.attachDevice(xml_string)
        # trigger watches to update device status
        # FIXME: this should be removed once libvirt will report such
        # events itself
        # self.vm.qdb.write('/qubes-block-devices', '') ← do we need this?

    def _is_already_attached(self, volume):
        ''' Checks if the given volume is already attached '''
        parsed_xml = lxml.etree.fromstring(self.vm.libvirt_domain.XMLDesc())
        disk_sources = parsed_xml.xpath("//domain/devices/disk/source")
        for source in disk_sources:
            if source.get('dev') == '/dev/%s' % volume.vid:
                return True
        return False

    def detach(self, volume):
        ''' Detach a volume from domain '''
        parsed_xml = lxml.etree.fromstring(self.vm.libvirt_domain.XMLDesc())
        disks = parsed_xml.xpath("//domain/devices/disk")
        for disk in disks:
            source = disk.xpath('source')[0]
            if source.get('dev') == '/dev/%s' % volume.vid:
                disk_xml = lxml.etree.tostring(disk, encoding='utf-8')
                self.vm.libvirt_domain.detachDevice(disk_xml)
                return
        raise StoragePoolException('Volume {!r} is not attached'.format(volume))

    @property
    def kernels_dir(self):
        '''Directory where kernel resides.

        If :py:attr:`self.vm.kernel` is :py:obj:`None`, the this points inside
        :py:attr:`self.vm.dir_path`
        '''
        assert 'kernel' in self.vm.volumes, "VM has no kernel volume"
        return self.vm.volumes['kernel'].kernels_dir

    def get_disk_utilization(self):
        ''' Returns summed up disk utilization for all domain volumes '''
        result = 0
        for volume in self.vm.volumes.values():
            result += volume.usage
        return result

    def resize(self, volume, size):
        ''' Resizes volume a read-writable volume '''
        if isinstance(volume, basestring):
            volume = self.vm.volumes[volume]
        self.get_pool(volume).resize(volume, size)
        if self.vm.is_running():
            self.vm.run_service('qubes.ResizeDisk', input=volume.name,
                user='root', wait=True)

    def create(self):
        ''' Creates volumes on disk '''
        old_umask = os.umask(0o002)

        for volume in self.vm.volumes.values():
            self.get_pool(volume).create(volume)

        os.umask(old_umask)

    def clone(self, src_vm):
        ''' Clone volumes from the specified vm '''

        src_path = src_vm.dir_path
        msg = "Source path {!s} does not exist".format(src_path)
        assert os.path.exists(src_path), msg

        dst_path = self.vm.dir_path
        msg = "Destination {!s} already exists".format(dst_path)
        assert not os.path.exists(dst_path), msg
        os.mkdir(dst_path)

        self.vm.volumes = {}
        with VmCreationManager(self.vm):
            for name, config in self.vm.volume_config.items():
                dst_pool = self.get_pool(config['pool'])
                dst = dst_pool.init_volume(self.vm, config)
                src_volume = src_vm.volumes[name]
                src_pool = self.vm.app.get_pool(src_volume.pool)
                if dst_pool == src_pool:
                    msg = "Cloning volume {!s} from vm {!s}"
                    self.vm.log.info(msg.format(src_volume.name, src_vm.name))
                    volume = dst_pool.clone(src_volume, dst)
                else:
                    msg = "Importing volume {!s} from vm {!s}"
                    self.vm.log.info(msg.format(src_volume.name, src_vm.name))
                    volume = dst_pool.import_volume(dst_pool, dst, src_pool,
                                                    src_volume)

                assert volume, "%s.clone() returned '%s'" % (
                    dst_pool.__class__.__name__, volume)

                self.vm.volumes[name] = volume

        msg = "Cloning directory: {!s} to {!s}"
        msg = msg.format(src_path, dst_path)
        self.log.info(msg)

    @property
    def outdated_volumes(self):
        ''' Returns a list of outdated volumes '''
        result = []
        if self.vm.is_halted():
            return result

        volumes = self.vm.volumes
        for volume in volumes.values():
            pool = self.get_pool(volume)
            if pool.is_outdated(volume):
                result += [volume]

        return result

    def rename(self, old_name, new_name):
        ''' Notify the pools that the domain was renamed '''
        volumes = self.vm.volumes
        vm = self.vm
        old_dir_path = os.path.join(os.path.dirname(vm.dir_path), old_name)
        new_dir_path = os.path.join(os.path.dirname(vm.dir_path), new_name)
        os.rename(old_dir_path, new_dir_path)
        for name, volume in volumes.items():
            pool = self.get_pool(volume)
            volumes[name] = pool.rename(volume, old_name, new_name)

    def verify(self):
        '''Verify that the storage is sane.

        On success, returns normally. On failure, raises exception.
        '''
        if not os.path.exists(self.vm.dir_path):
            raise qubes.exc.QubesVMError(
                self.vm,
                'VM directory does not exist: {}'.format(self.vm.dir_path))
        for volume in self.vm.volumes.values():
            self.get_pool(volume).verify(volume)
        self.vm.fire_event('domain-verify-files')
        return True

    def remove(self):
        ''' Remove all the volumes.

            Errors on removal are catched and logged.
        '''
        for name, volume in self.vm.volumes.items():
            self.log.info('Removing volume %s: %s' % (name, volume.vid))
            try:
                self.get_pool(volume).remove(volume)
            except (IOError, OSError) as e:
                self.vm.log.exception("Failed to remove volume %s", name, e)

    def start(self):
        ''' Execute the start method on each pool '''
        for volume in self.vm.volumes.values():
            pool = self.get_pool(volume)
            volume = pool.start(volume)

    def stop(self):
        ''' Execute the start method on each pool '''
        for volume in self.vm.volumes.values():
            self.get_pool(volume).stop(volume)

    def get_pool(self, volume):
        ''' Helper function '''
        assert isinstance(volume, (Volume, basestring)), \
            "You need to pass a Volume or pool name as str"
        if isinstance(volume, Volume):
            return self.pools[volume.name]
        else:
            return self.vm.app.pools[volume]

    def commit(self):
        ''' Makes changes to an 'origin' volume persistent '''
        for volume in self.vm.volumes.values():
            if volume.save_on_stop:
                self.get_pool(volume).commit(volume)

    def unused_frontend(self):
        ''' Find an unused device name '''
        unused_frontends = self.AVAILABLE_FRONTENDS.difference(
            self.used_frontends)
        return sorted(unused_frontends)[0]

    @property
    def used_frontends(self):
        ''' Used device names '''
        xml = self.vm.libvirt_domain.XMLDesc()
        parsed_xml = lxml.etree.fromstring(xml)
        return set([target.get('dev', None)
                    for target in parsed_xml.xpath(
                        "//domain/devices/disk/target")])


class Pool(object):
    ''' A Pool is used to manage different kind of volumes (File
        based/LVM/Btrfs/...).

        3rd Parties providing own storage implementations will need to extend
        this class.
    '''  # pylint: disable=unused-argument
    private_img_size = qubes.config.defaults['private_img_size']
    root_img_size = qubes.config.defaults['root_img_size']

    def __init__(self, name, revisions_to_keep=1, **kwargs):
        super(Pool, self).__init__(**kwargs)
        self.name = name
        self.revisions_to_keep = revisions_to_keep
        kwargs['name'] = self.name

    def __eq__(self, other):
        return self.name == other.name

    def __neq__(self, other):
        return not self.__eq__(other)

    def __str__(self):
        return self.name

    def __xml__(self):
        config = _sanitize_config(self.config)
        return lxml.etree.Element('pool', **config)

    def create(self, volume):
        ''' Create the given volume on disk or copy from provided
            `source_volume`.
        '''
        raise self._not_implemented("create")

    def commit(self, volume):  # pylint: disable=no-self-use
        ''' Write the snapshot to disk '''
        msg = "Got volume_type {!s} when expected 'snap'"
        msg = msg.format(volume.volume_type)
        assert volume.volume_type == 'snap', msg

    @property
    def config(self):
        ''' Returns the pool config to be written to qubes.xml '''
        raise self._not_implemented("config")

    def clone(self, source, target):
        ''' Clone volume '''
        raise self._not_implemented("clone")

    def destroy(self):
        ''' Called when removing the pool. Use this for implementation specific
            clean up.
        '''
        raise self._not_implemented("destroy")

    def export(self, volume):
        ''' Returns an object that can be `open()`. '''
        raise self._not_implemented("export")

    def import_volume(self, dst_pool, dst_volume, src_pool, src_volume):
        ''' Imports data to a volume in this pool '''
        raise self._not_implemented("import_volume")

    def init_volume(self, vm, volume_config):
        ''' Initialize a :py:class:`qubes.storage.Volume` from `volume_config`.
        '''
        raise self._not_implemented("init_volume")

    def is_dirty(self, volume):
        ''' Return `True` if volume was not properly shutdown and commited '''
        raise self._not_implemented("is_dirty")

    def is_outdated(self, volume):
        ''' Returns `True` if the currently used `volume.source` of a snapshot
            volume is outdated.
        '''
        raise self._not_implemented("is_outdated")

    def recover(self, volume):
        ''' Try to recover a :py:class:`Volume` or :py:class:`SnapVolume` '''
        raise self._not_implemented("recover")

    def remove(self, volume):
        ''' Remove volume'''
        raise self._not_implemented("remove")

    def rename(self, volume, old_name, new_name):
        ''' Called when the domain changes its name '''
        raise self._not_implemented("rename")

    def reset(self, volume):
        ''' Drop and recreate volume without copying it's content from source.
        '''
        raise self._not_implemented("reset")

    def resize(self, volume, size):
        ''' Expands volume, throws
            :py:class:`qubes.storage.StoragePoolException` if
            given size is less than current_size
        '''
        raise self._not_implemented("resize")

    def revert(self, volume, revision=None):
        ''' Revert volume to previous revision  '''
        raise self._not_implemented("revert")

    def setup(self):
        ''' Called when adding a pool to the system. Use this for implementation
            specific set up.
        '''
        raise self._not_implemented("setup")

    def start(self, volume):  # pylint: disable=no-self-use
        ''' Do what ever is needed on start '''
        raise self._not_implemented("start")

    def stop(self, volume):  # pylint: disable=no-self-use
        ''' Do what ever is needed on stop'''

    def verify(self, volume):
        ''' Verifies the volume. '''
        raise self._not_implemented("verify")

    @property
    def volumes(self):
        ''' Return a list of volumes managed by this pool '''
        raise self._not_implemented("volumes")

    def _not_implemented(self, method_name):
        ''' Helper for emitting helpful `NotImplementedError` exceptions '''
        msg = "Pool driver {!s} has {!s}() not implemented"
        msg = msg.format(str(self.__class__.__name__), method_name)
        return NotImplementedError(msg)


def _sanitize_config(config):
    ''' Helper function to convert types to appropriate strings
    '''  # FIXME: find another solution for serializing basic types
    result = {}
    for key, value in config.items():
        if isinstance(value, bool):
            if value:
                result[key] = 'True'
        else:
            result[key] = str(value)
    return result


def pool_drivers():
    """ Return a list of EntryPoints names """
    return [ep.name
            for ep in pkg_resources.iter_entry_points(STORAGE_ENTRY_POINT)]


def isodate(seconds=time.time()):
    ''' Helper method which returns an iso date '''
    return datetime.utcfromtimestamp(seconds).isoformat("T")


class VmCreationManager(object):
    ''' A `ContextManager` which cleans up if volume creation fails.
    '''  # pylint: disable=too-few-public-methods
    def __init__(self, vm):
        self.vm = vm

    def __enter__(self):
        pass

    def __exit__(self, type, value, tb):  # pylint: disable=redefined-builtin
        if type is not None and value is not None and tb is not None:
            for volume in self.vm.volumes.values():
                try:
                    pool = self.vm.storage.get_pool(volume)
                    pool.remove(volume)
                except Exception:  # pylint: disable=broad-except
                    pass
            os.rmdir(self.vm.dir_path)
