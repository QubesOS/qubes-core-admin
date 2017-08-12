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

import inspect
import os
import os.path
import string  # pylint: disable=deprecated-module
import time
from datetime import datetime

import asyncio
import lxml.etree
import pkg_resources
import qubes
import qubes.exc
import qubes.utils

STORAGE_ENTRY_POINT = 'qubes.storage'


class StoragePoolException(qubes.exc.QubesException):
    ''' A general storage exception '''
    pass


class BlockDevice(object):
    ''' Represents a storage block device. '''
    # pylint: disable=too-few-public-methods
    def __init__(self, path, name, script=None, rw=True, domain=None,
                 devtype='disk'):
        assert name, 'Missing device name'
        assert path, 'Missing device path'
        self.path = path
        self.name = name
        self.rw = rw
        self.script = script
        self.domain = domain
        self.devtype = devtype


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
    #: disk space used by this volume, can be smaller than :py:attr:`size`
    #: for sparse volumes
    usage = 0

    def __init__(self, name, pool, vid,
            revisions_to_keep=0, rw=False, save_on_stop=False, size=0,
            snap_on_start=False, source=None, **kwargs):
        ''' Initialize a volume.

            :param str name: The name of the volume inside owning domain
            :param Pool pool: The pool object
            :param str vid:  Volume identifier needs to be unique in pool
            :param int revisions_to_keep: Amount of revisions to keep around
            :param bool rw: If true volume will be mounted read-write
            :param bool snap_on_start: Create a snapshot from source on
                start, instead of using volume own data
            :param bool save_on_stop: Write changes to the volume in
                vm.stop(), otherwise - discard
            :param Volume source: other volume in same pool to make snapshot
                from, required if *snap_on_start*=`True`
            :param str/int size: Size of the volume

        '''

        super(Volume, self).__init__(**kwargs)
        assert isinstance(pool, Pool)
        assert source is None or (isinstance(source, Volume)
                                  and source.pool == pool)

        if snap_on_start and source is None:
            msg = "snap_on_start specified on {!r} but no volume source set"
            msg = msg.format(name)
            raise StoragePoolException(msg)
        elif not snap_on_start and source is not None:
            msg = "source specified on {!r} but no snap_on_start set"
            msg = msg.format(name)
            raise StoragePoolException(msg)

        #: Name of the volume in a domain it's attached to (like `root` or
        #: `private`).
        self.name = str(name)
        #: :py:class:`Pool` instance owning this volume
        self.pool = pool
        #: How many revisions of the volume to keep. Each revision is created
        #  at :py:meth:`stop`, if :py:attr:`save_on_stop` is True
        self.revisions_to_keep = int(revisions_to_keep)
        #: Should this volume be writable by domain.
        self.rw = rw
        #: Should volume state be saved or discarded at :py:meth:`stop`
        self.save_on_stop = save_on_stop
        self._size = int(size)
        #: Should the volume state be initialized with a snapshot of
        #: same-named volume of domain's template.
        self.snap_on_start = snap_on_start
        #: source volume for :py:attr:`snap_on_start` volumes
        self.source = source
        #: Volume unique (inside given pool) identifier
        self.vid = vid

    def __eq__(self, other):
        if isinstance(other, Volume):
            return other.pool == self.pool and other.vid == self.vid
        return NotImplemented

    def __hash__(self):
        return hash('%s:%s' % (self.pool, self.vid))

    def __neq__(self, other):
        return not self.__eq__(other)

    def __repr__(self):
        return '{!r}'.format(str(self.pool) + ':' + self.vid)

    def __str__(self):
        return str(self.vid)

    def __xml__(self):
        config = _sanitize_config(self.config)
        return lxml.etree.Element('volume', **config)

    def create(self):
        ''' Create the given volume on disk.

            This method is called only once in the volume lifetime. Before
            calling this method, no data on disk should be touched (in
            context of this volume).

            This can be implemented as a coroutine.
        '''
        raise self._not_implemented("create")

    def remove(self):
        ''' Remove volume.

        This can be implemented as a coroutine.'''
        raise self._not_implemented("remove")

    def export(self):
        ''' Returns a path to read the volume data from.

            Reading from this path when domain owning this volume is
            running (i.e. when :py:meth:`is_dirty` is True) should return the
            data from before domain startup.

            Reading from the path returned by this method should return the
            volume data. If extracting volume data require something more
            than just reading from file (for example connecting to some other
            domain, or decompressing the data), the returned path may be a pipe.
        '''
        raise self._not_implemented("export")

    def import_data(self):
        ''' Returns a path to overwrite volume data.

            This method is called after volume was already :py:meth:`create`-ed.

            Writing to this path should overwrite volume data. If importing
            volume data require something more than just writing to a file (
            for example connecting to some other domain, or converting data
            on the fly), the returned path may be a pipe.
        '''
        raise self._not_implemented("import")

    def import_data_end(self, success):
        ''' End the data import operation. This may be used by pool
        implementation to commit changes, cleanup temporary files etc.

        This method is called regardless the operation was successful or not.

        :param success: True if data import was successful, otherwise False
        '''
        # by default do nothing
        pass

    def import_volume(self, src_volume):
        ''' Imports data from a different volume (possibly in a different
        pool.

        The volume needs to be create()d first.

        This can be implemented as a coroutine. '''
        # pylint: disable=unused-argument
        raise self._not_implemented("import_volume")

    def is_dirty(self):
        ''' Return `True` if volume was not properly shutdown and committed.

            This include the situation when domain owning the volume is still
            running.

        '''
        raise self._not_implemented("is_dirty")

    def is_outdated(self):
        ''' Returns `True` if this snapshot of a source volume (for
        `snap_on_start`=True) is outdated.
        '''
        raise self._not_implemented("is_outdated")

    def resize(self, size):
        ''' Expands volume, throws
            :py:class:`qubes.storage.StoragePoolException` if
            given size is less than current_size

            This can be implemented as a coroutine.

            :param int size: new size in bytes
        '''
        # pylint: disable=unused-argument
        raise self._not_implemented("resize")

    def revert(self, revision=None):
        ''' Revert volume to previous revision

        :param revision: revision to revert volume to, see :py:attr:`revisions`
        '''
        # pylint: disable=unused-argument
        raise self._not_implemented("revert")

    def start(self):
        ''' Do what ever is needed on start.

        This include making a snapshot of template's volume if
        :py:attr:`snap_on_start` is set.

        This can be implemented as a coroutine.'''
        raise self._not_implemented("start")

    def stop(self):
        ''' Do what ever is needed on stop.

        This include committing data if :py:attr:`save_on_stop` is set.

        This can be implemented as a coroutine.'''

    def verify(self):
        ''' Verifies the volume.

        This can be implemented as a coroutine.'''
        raise self._not_implemented("verify")

    def block_device(self):
        ''' Return :py:class:`BlockDevice` for serialization in
            the libvirt XML template as <disk>.
        '''
        return BlockDevice(self.path, self.name, self.script,
                                         self.rw, self.domain, self.devtype)

    @property
    def revisions(self):
        ''' Returns a dict containing revision identifiers and time of their
        creation '''
        msg = "{!s} has revisions not implemented".format(self.__class__)
        raise NotImplementedError(msg)

    @property
    def size(self):
        ''' Volume size in bytes '''
        return self._size

    @size.setter
    def size(self, size):
        # pylint: disable=attribute-defined-outside-init
        self._size = int(size)


    @property
    def config(self):
        ''' return config data for serialization to qubes.xml '''
        result = {
            'name': self.name,
            'pool': str(self.pool),
            'vid': self.vid,
            'revisions_to_keep': self.revisions_to_keep,
            'rw': self.rw,
            'save_on_stop': self.save_on_stop,
            'snap_on_start': self.snap_on_start,
        }

        if self.size:
            result['size'] = self.size

        if self.source:
            result['source'] = str(self.source)

        return result

    def _not_implemented(self, method_name):
        ''' Helper for emitting helpful `NotImplementedError` exceptions '''
        msg = "Volume {!s} has {!s}() not implemented"
        msg = msg.format(str(self.__class__.__name__), method_name)
        return NotImplementedError(msg)

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

        if hasattr(vm, 'volume_config'):
            for name, conf in self.vm.volume_config.items():
                self.init_volume(name, conf)

    def _update_volume_config_source(self, name, volume_config):
        '''Retrieve 'source' volume from VM's template'''
        template = getattr(self.vm, 'template', None)
        # recursively lookup source volume - templates may be
        # chained (TemplateVM -> AppVM -> DispVM, where the
        # actual source should be used from TemplateVM)
        while template:
            source = template.volumes[name]
            volume_config['source'] = source
            volume_config['pool'] = source.pool
            volume_config['size'] = source.size
            if source.source is not None:
                template = getattr(template, 'template', None)
            else:
                break

    def init_volume(self, name, volume_config):
        ''' Initialize Volume instance attached to this domain '''

        if 'name' not in volume_config:
            volume_config['name'] = name

        if 'source' in volume_config:
            # we have no control over VM load order,
            # so initialize storage recursively if needed
            template = getattr(self.vm, 'template', None)
            if template and template.storage is None:
                template.storage = Storage(template)

            if volume_config['source'] is None:
                self._update_volume_config_source(name, volume_config)
            else:
                # if source is already specified, pool needs to be too
                pool = self.vm.app.get_pool(volume_config['pool'])
                volume_config['source'] = pool.volumes[volume_config['source']]

        # if pool still unknown, load default
        if 'pool' not in volume_config:
            volume_config['pool'] = \
                getattr(self.vm.app, 'default_pool_' + name)
        pool = self.vm.app.get_pool(volume_config['pool'])
        if 'internal' in volume_config:
            # migrate old config
            del volume_config['internal']
        volume = pool.init_volume(self.vm, volume_config)
        self.vm.volumes[name] = volume
        return volume

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
        # self.vm.untrusted_qdb.write('/qubes-block-devices', '')
        # ← do we need this?

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

    @asyncio.coroutine
    def resize(self, volume, size):
        ''' Resizes volume a read-writable volume '''
        if isinstance(volume, str):
            volume = self.vm.volumes[volume]
        ret = volume.resize(size)
        if asyncio.iscoroutine(ret):
            yield from ret
        if self.vm.is_running():
            yield from self.vm.run_service_for_stdio('qubes.ResizeDisk',
                input=volume.name.encode(),
                user='root')

    @asyncio.coroutine
    def create(self):
        ''' Creates volumes on disk '''
        old_umask = os.umask(0o002)

        coros = []
        for volume in self.vm.volumes.values():
            # launch the operation, if it's asynchronous, then append to wait
            #  for them at the end
            ret = volume.create()
            if asyncio.iscoroutine(ret):
                coros.append(ret)
        if coros:
            yield from asyncio.wait(coros)

        os.umask(old_umask)

    @asyncio.coroutine
    def clone_volume(self, src_vm, name):
        ''' Clone single volume from the specified vm

        :param QubesVM src_vm: source VM
        :param str name: name of volume to clone ('root', 'private' etc)
        :return cloned volume object
        '''
        config = self.vm.volume_config[name]
        dst_pool = self.vm.app.get_pool(config['pool'])
        dst = dst_pool.init_volume(self.vm, config)
        src_volume = src_vm.volumes[name]
        msg = "Importing volume {!s} from vm {!s}"
        self.vm.log.info(msg.format(src_volume.name, src_vm.name))

        # First create the destination volume
        create_op_ret = dst.create()
        # clone/import functions may be either synchronous or asynchronous
        # in the later case, we need to wait for them to finish
        if asyncio.iscoroutine(create_op_ret):
            yield from create_op_ret

        # Then import data from source volume
        clone_op_ret = dst.import_volume(src_volume)

        # clone/import functions may be either synchronous or asynchronous
        # in the later case, we need to wait for them to finish
        if asyncio.iscoroutine(clone_op_ret):
            yield from clone_op_ret
        self.vm.volumes[name] = dst
        return self.vm.volumes[name]

    @asyncio.coroutine
    def clone(self, src_vm):
        ''' Clone volumes from the specified vm '''

        self.vm.volumes = {}
        with VmCreationManager(self.vm):
            yield from asyncio.wait([self.clone_volume(src_vm, vol_name)
                for vol_name in self.vm.volume_config.keys()])

    @property
    def outdated_volumes(self):
        ''' Returns a list of outdated volumes '''
        result = []
        if self.vm.is_halted():
            return result

        volumes = self.vm.volumes
        for volume in volumes.values():
            if volume.is_outdated():
                result += [volume]

        return result

    @asyncio.coroutine
    def verify(self):
        '''Verify that the storage is sane.

        On success, returns normally. On failure, raises exception.
        '''
        if not os.path.exists(self.vm.dir_path):
            raise qubes.exc.QubesVMError(
                self.vm,
                'VM directory does not exist: {}'.format(self.vm.dir_path))
        futures = []
        for volume in self.vm.volumes.values():
            ret = volume.verify()
            if asyncio.iscoroutine(ret):
                futures.append(ret)
        if futures:
            yield from asyncio.wait(futures)
        self.vm.fire_event('domain-verify-files')
        return True

    @asyncio.coroutine
    def remove(self):
        ''' Remove all the volumes.

            Errors on removal are catched and logged.
        '''
        futures = []
        for name, volume in self.vm.volumes.items():
            self.log.info('Removing volume %s: %s' % (name, volume.vid))
            try:
                ret = volume.remove()
                if asyncio.iscoroutine(ret):
                    futures.append(ret)
            except (IOError, OSError) as e:
                self.vm.log.exception("Failed to remove volume %s", name, e)

        if futures:
            try:
                yield from asyncio.wait(futures)
            except (IOError, OSError) as e:
                self.vm.log.exception("Failed to remove some volume", e)

    @asyncio.coroutine
    def start(self):
        ''' Execute the start method on each pool '''
        futures = []
        for volume in self.vm.volumes.values():
            ret = volume.start()
            if asyncio.iscoroutine(ret):
                futures.append(ret)

        if futures:
            yield from asyncio.wait(futures)

    @asyncio.coroutine
    def stop(self):
        ''' Execute the start method on each pool '''
        futures = []
        for volume in self.vm.volumes.values():
            ret = volume.stop()
            if asyncio.iscoroutine(ret):
                futures.append(ret)

        if futures:
            yield from asyncio.wait(futures)

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

    def export(self, volume):
        ''' Helper function to export volume (pool.export(volume))'''
        assert isinstance(volume, (Volume, str)), \
            "You need to pass a Volume or pool name as str"
        if isinstance(volume, Volume):
            return volume.export()

        return self.vm.volumes[volume].export()

    def import_data(self, volume):
        ''' Helper function to import volume data (pool.import_data(volume))'''
        assert isinstance(volume, (Volume, str)), \
            "You need to pass a Volume or pool name as str"
        if isinstance(volume, Volume):
            return volume.import_data()

        return self.vm.volumes[volume].import_data()

    def import_data_end(self, volume, success):
        ''' Helper function to finish/cleanup data import
        (pool.import_data_end( volume))'''
        assert isinstance(volume, (Volume, str)), \
            "You need to pass a Volume or pool name as str"
        if isinstance(volume, Volume):
            return volume.import_data_end(success=success)

        return self.vm.volumes[volume].import_data_end(success=success)


class VolumesCollection(object):
    '''Convenient collection wrapper for pool.get_volume and
    pool.list_volumes
    '''
    def __init__(self, pool):
        self._pool = pool

    def __getitem__(self, item):
        ''' Get a single volume with given Volume ID.

        You can also a Volume instance to get the same Volume or KeyError if
        Volume no longer exists.

        :param item: a Volume ID (str) or a Volume instance
        '''
        if isinstance(item, Volume):
            if item.pool == self._pool:
                return self[item.vid]
            else:
                raise KeyError(item)
        try:
            return self._pool.get_volume(item)
        except NotImplementedError:
            for vol in self:
                if vol.vid == item:
                    return vol
            # if list_volumes is not implemented too, it will raise
            # NotImplementedError again earlier
            raise KeyError(item)

    def __iter__(self):
        ''' Get iterator over pool's volumes '''
        return iter(self._pool.list_volumes())

    def __contains__(self, item):
        ''' Check if given volume (either Volume ID or Volume instance) is
        present in the pool
        '''
        try:
            return self[item] is not None
        except KeyError:
            return False

    def keys(self):
        ''' Return list of volume IDs '''
        return [vol.vid for vol in self]

    def values(self):
        ''' Return list of Volumes'''
        return [vol for vol in self]


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
        self._volumes_collection = VolumesCollection(self)
        self.name = name
        self.revisions_to_keep = revisions_to_keep
        kwargs['name'] = self.name

    def __eq__(self, other):
        if isinstance(other, Pool):
            return self.name == other.name
        elif isinstance(other, str):
            return self.name == other
        return NotImplemented

    def __neq__(self, other):
        return not self.__eq__(other)

    def __str__(self):
        return self.name

    def __hash__(self):
        return hash(self.name)

    def __xml__(self):
        config = _sanitize_config(self.config)
        return lxml.etree.Element('pool', **config)

    @property
    def config(self):
        ''' Returns the pool config to be written to qubes.xml '''
        raise self._not_implemented("config")

    def destroy(self):
        ''' Called when removing the pool. Use this for implementation specific
            clean up.
        '''
        raise self._not_implemented("destroy")

    def init_volume(self, vm, volume_config):
        ''' Initialize a :py:class:`qubes.storage.Volume` from `volume_config`.
        '''
        raise self._not_implemented("init_volume")

    def setup(self):
        ''' Called when adding a pool to the system. Use this for implementation
            specific set up.
        '''
        raise self._not_implemented("setup")

    @property
    def volumes(self):
        ''' Return a collection of volumes managed by this pool '''
        return self._volumes_collection

    def list_volumes(self):
        ''' Return a list of volumes managed by this pool '''
        raise self._not_implemented("list_volumes")

    def get_volume(self, vid):
        ''' Return a volume with *vid* from this pool

        :raise KeyError: if no volume is found
        '''
        raise self._not_implemented("get_volume")

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


def driver_parameters(name):
    ''' Get __init__ parameters from a driver with out `self` & `name`. '''
    init_function = qubes.utils.get_entry_point_one(
        qubes.storage.STORAGE_ENTRY_POINT, name).__init__
    params = init_function.func_code.co_varnames
    ignored_params = ['self', 'name']
    return [p for p in params if p not in ignored_params]


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
                    volume.remove()
                except Exception:  # pylint: disable=broad-except
                    pass
            os.rmdir(self.vm.dir_path)
