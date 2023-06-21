#
# The Qubes OS Project, http://www.qubes-os.org
#
# Copyright (C) 2016 Bahtiar `kalkin-` Gadimov <bahtiar@gadimov.de>
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

''' Driver for storing vm images in a LVM thin pool '''
import logging
import os
import subprocess

import time

import asyncio

import qubes
import qubes.storage
import qubes.utils
import json

_sudo, _dd, _lvm = 'sudo', 'dd', 'lvm'

class ThinPool(qubes.storage.Pool):
    ''' LVM Thin based pool implementation

    Volumes are stored as LVM thin volumes, in thin pool specified by
    *volume_group*/*thin_pool* arguments. LVM volume naming scheme:

        vm-{vm_name}-{volume_name}[-suffix]

    Where suffix can be one of:
        "-snap" - snapshot for currently running VM, at VM shutdown will be
        either discarded (if save_on_stop=False), or committed
        (if save_on_stop=True)
        "-{revision_id}" - volume revision - new revision is automatically
        created at each VM shutdown, *revisions_to_keep* control how many
        old revisions (in addition to the current one) should be stored
        "" (no suffix) - the most recent committed volume state; also volatile
        volume (snap_on_start=False, save_on_stop=False)

    On VM startup, new volume is created, depending on volume type,
    according to the table below:

    snap_on_start, save_on_stop
    False,         False,        - no suffix, fresh empty volume
    False,         True,         - "-snap", snapshot of last committed revision
    True ,         False,        - "-snap", snapshot of last committed revision
                                   of source volume (from VM's template)
    True,          True,         - unsupported configuration

    Volume's revision_id format is "{timestamp}-back", where timestamp is in
    '%s' format (seconds since unix epoch)
    '''  # pylint: disable=protected-access

    size_cache = None

    driver = 'lvm_thin'

    def __init__(self, *, name, revisions_to_keep=1, volume_group, thin_pool,
                 ephemeral_volatile=False):
        super().__init__(name=name, revisions_to_keep=revisions_to_keep,
                         ephemeral_volatile=ephemeral_volatile)
        self.volume_group = volume_group
        self.thin_pool = thin_pool
        self._pool_id = "{!s}/{!s}".format(volume_group, thin_pool)
        self.log = logging.getLogger('qubes.storage.lvm.%s' % self._pool_id)

        self._volume_objects_cache = {}

    def __repr__(self):
        return '<{} at {:#x} name={!r} volume_group={!r} thin_pool={!r}>'.\
            format(
                type(self).__name__, id(self),
                self.name, self.volume_group, self.thin_pool)

    @property
    def config(self):
        return {
            'name': self.name,
            'volume_group': self.volume_group,
            'thin_pool': self.thin_pool,
            'driver': ThinPool.driver,
            'revisions_to_keep': self.revisions_to_keep,
            'ephemeral_volatile': self.ephemeral_volatile,
        }

    async def destroy(self):
        pass  # TODO Should we remove an existing pool?

    def init_volume(self, vm, volume_config):
        ''' Initialize a :py:class:`qubes.storage.Volume` from `volume_config`.
        '''

        if 'revisions_to_keep' not in volume_config.keys():
            volume_config['revisions_to_keep'] = self.revisions_to_keep
        if 'vid' not in volume_config.keys():
            if vm and hasattr(vm, 'name'):
                vm_name = vm.name
            else:
                # for the future if we have volumes not belonging to a vm
                vm_name = qubes.utils.random_string()

            assert self.name

            volume_config['vid'] = "{!s}/vm-{!s}-{!s}".format(
                self.volume_group, vm_name, volume_config['name'])

        volume_config['volume_group'] = self.volume_group
        volume_config['pool'] = self
        volume = ThinVolume(**volume_config)
        self._volume_objects_cache[volume_config['vid']] = volume
        return volume

    async def setup(self):
        await reset_cache_coro()
        cache_key = self.volume_group + '/' + self.thin_pool
        if cache_key not in size_cache:
            raise qubes.storage.StoragePoolException(
                'Thin pool {} does not exist'.format(cache_key))
        if size_cache[cache_key]['attr'][0] != 't':
            raise qubes.storage.StoragePoolException(
                'Volume {} is not a thin pool'.format(cache_key))
        # TODO Should we create a non existing pool?

    def get_volume(self, vid):
        ''' Return a volume with given vid'''
        if vid in self._volume_objects_cache:
            return self._volume_objects_cache[vid]

        config = {
                'pool': self,
                'vid': vid,
                'name': vid,
                'volume_group': self.volume_group,
            }
        # don't cache this object, as it doesn't carry full configuration
        return ThinVolume(**config)

    def list_volumes(self):
        ''' Return a list of volumes managed by this pool '''
        volumes = []
        for vid, vol_info in size_cache.items():
            if not vid.startswith(self.volume_group + '/'):
                continue
            if vol_info['pool_lv'] != self.thin_pool:
                continue
            if vid.endswith('-snap') or vid.endswith('-import'):
                # implementation detail volume
                continue
            if vid.endswith('-back'):
                # old revisions
                continue
            volume = self.get_volume(vid)
            if volume in volumes:
                continue
            volumes.append(volume)
        return volumes

    @property
    def size(self):
        try:
            return qubes.storage.lvm.size_cache[
                self.volume_group + '/' + self.thin_pool]['size']
        except KeyError:
            return 0

    @property
    def usage(self):
        refresh_cache()
        try:
            return qubes.storage.lvm.size_cache[
                self.volume_group + '/' + self.thin_pool]['usage']
        except KeyError:
            return 0

    @property
    def usage_details(self):
        result = {}
        result['data_size'] = self.size
        result['data_usage'] = self.usage

        try:
            metadata_size = qubes.storage.lvm.size_cache[
                self.volume_group + '/' + self.thin_pool]['metadata_size']
            metadata_usage = qubes.storage.lvm.size_cache[
                self.volume_group + '/' + self.thin_pool]['metadata_usage']
        except KeyError:
            metadata_size = 0
            metadata_usage = 0
        result['metadata_size'] = metadata_size
        result['metadata_usage'] = metadata_usage

        return result

_init_cache_cmd = [_lvm, 'lvs', '--noheadings', '-o',
   'vg_name,pool_lv,name,lv_size,data_percent,lv_attr,origin,lv_metadata_size,'
   'metadata_percent', '--units', 'b', '--reportformat=json']
if os.getuid() != 0:
    _init_cache_cmd.insert(0, _sudo)

def _parse_lvm_cache(lvm_output):
    # Assume that LVM produces correct JSON.
    out_list = json.loads(lvm_output)["report"][0]["lv"]
    result = {}
    for row in out_list:
        try:
            pool_name, name = row['vg_name'], row['lv_name']
            size, usage_percent = row['lv_size'], row['data_percent']
        except KeyError:
            continue
        if '' in [pool_name, name, size, usage_percent]:
            continue
        pool_lv, attr, origin = row['pool_lv'], row['lv_attr'], row['origin']
        metadata_size = row['lv_metadata_size']
        metadata_percent = row['metadata_percent']
        name = pool_name + "/" + name
        size = int(size[:-1])  # Remove 'B' suffix
        usage = int(size / 100 * float(usage_percent))
        if metadata_size:
            metadata_size = int(metadata_size[:-1])
            metadata_usage = int(metadata_size / 100 * float(metadata_percent))
        else:
            metadata_usage = None
        result[name] = {'size': size, 'usage': usage, 'pool_lv': pool_lv,
            'attr': attr, 'origin': origin, 'metadata_size': metadata_size,
                        'metadata_usage': metadata_usage}

    return result

def init_cache(log=logging.getLogger('qubes.storage.lvm')):
    cmd = _init_cache_cmd
    environ={'LC_ALL': 'C.UTF-8', **os.environ}
    with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            close_fds=True, env=environ) as p:
        out, err = p.communicate()
    return_code = p.returncode
    if return_code == 0 and err:
        log.warning(err)
    elif return_code != 0:
        raise qubes.storage.StoragePoolException(err)

    return _parse_lvm_cache(out)

async def init_cache_coro(log=logging.getLogger('qubes.storage.lvm')):
    cmd = _init_cache_cmd
    environ={'LC_ALL': 'C.UTF-8', **os.environ}
    p = await asyncio.create_subprocess_exec(*cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        close_fds=True, env=environ)
    out, err = await p.communicate()
    return_code = p.returncode
    if return_code == 0 and err:
        log.warning(err)
    elif return_code != 0:
        raise qubes.storage.StoragePoolException(err)

    return _parse_lvm_cache(out)

size_cache_time = 0
size_cache = init_cache()


def _revision_sort_key(revision):
    '''Sort key for revisions. Sort them by time

    :returns timestamp
    '''
    if isinstance(revision, tuple):
        revision = revision[0]
    if '-' in revision:
        revision = revision.split('-')[0]
    return int(revision)

class ThinVolume(qubes.storage.Volume):
    ''' Default LVM thin volume implementation
    '''  # pylint: disable=too-few-public-methods


    def __init__(self, volume_group, **kwargs):
        self.volume_group = volume_group
        super().__init__(**kwargs)
        self.log = logging.getLogger('qubes.storage.lvm.%s' % str(self.pool))

        if self.snap_on_start or self.save_on_stop:
            self._vid_snap = self.vid + '-snap'
        if self.save_on_stop:
            self._vid_import = self.vid + '-import'

    @property
    def path(self):
        return '/dev/' + self._vid_current

    @property
    def _vid_current(self):
        if self.vid in size_cache:
            return self.vid
        vol_revisions = self.revisions
        if vol_revisions:
            last_revision = \
                max(vol_revisions.items(), key=_revision_sort_key)[0]
            return self.vid + '-' + last_revision
        # detached pool? return expected path
        return self.vid

    @property
    def revisions(self):
        name_prefix = self.vid + '-'
        revisions = {}
        for revision_vid in size_cache:
            if not revision_vid.startswith(name_prefix):
                continue
            if not revision_vid.endswith('-back'):
                continue
            revision_vid = revision_vid[len(name_prefix):]
            if revision_vid.count('-') > 1:
                # VM+volume name is a prefix of another VM, see #4680
                continue
            # get revision without suffix
            seconds = int(revision_vid.split('-')[0])
            iso_date = qubes.storage.isodate(seconds)
            revisions[revision_vid] = iso_date
        return revisions

    @property
    def size(self):
        try:
            if (self.snap_on_start or self.save_on_stop) \
               and os.path.exists('/dev/' + self._vid_snap):
                return qubes.storage.lvm.size_cache[self._vid_snap]['size']
            return qubes.storage.lvm.size_cache[self._vid_current]['size']
        except KeyError:
            return self._size

    async def _reset(self):
        ''' Resets a volatile volume '''
        assert not self.snap_on_start and not self.save_on_stop, \
            "Not a volatile volume"
        self.log.debug('Resetting volatile %s', self.vid)
        try:
            assert self.path.startswith('/dev/'), \
                'bad value for self.path: %r' % self.path
            cmd = ['remove', self.path[5:]]
            await qubes_lvm_coro(cmd, self.log)
        except qubes.storage.StoragePoolException:
            pass
        # pylint: disable=protected-access
        cmd = ['create', self.pool._pool_id, self.vid.split('/')[1],
               str(self.size)]
        await qubes_lvm_coro(cmd, self.log)

    async def _remove_revisions(self, revisions=None):
        '''Remove old volume revisions.

        If no revisions list is given, it removes old revisions according to
        :py:attr:`revisions_to_keep`

        :param revisions: list of revisions to remove
        '''
        if revisions is None:
            revisions = sorted(self.revisions.items(),
                key=_revision_sort_key)
            # pylint: disable=invalid-unary-operand-type
            revisions = revisions[:(-self.revisions_to_keep) or None]
            revisions = [rev_id for rev_id, _ in revisions]

        for rev_id in revisions:
            # safety check
            assert rev_id != self._vid_current
            try:
                cmd = ['remove', self.vid + '-' + rev_id]
                await qubes_lvm_coro(cmd, self.log)
            except qubes.storage.StoragePoolException:
                pass

    async def _commit(self, vid_to_commit=None, keep=False):
        '''
        Commit temporary volume into current one. By default
        :py:attr:`_vid_snap` is used (which is created by :py:meth:`start()`),
        but can be overriden by *vid_to_commit* argument.

        :param vid_to_commit: LVM volume ID to commit into this one
        :param keep: whether to keep or not *vid_to_commit*.
          IOW use 'clone' or 'rename' methods.
        :return: True if any change was made
        '''
        msg = "Trying to commit {!s}, but it has save_on_stop == False"
        msg = msg.format(self)
        assert self.save_on_stop, msg

        msg = "Trying to commit {!s}, but it has rw == False"
        msg = msg.format(self)
        assert self.rw, msg
        if vid_to_commit is None:
            assert hasattr(self, '_vid_snap')
            vid_to_commit = self._vid_snap

        assert self._lock.locked()
        if not os.path.exists('/dev/' + vid_to_commit):
            # nothing to commit
            return False

        if self._vid_current == self.vid:
            cmd = ['rename', self.vid,
                   '{}-{}-back'.format(self.vid, int(time.time()))]
            await qubes_lvm_coro(cmd, self.log)
            await reset_cache_coro()

        cmd = ['clone' if keep else 'rename',
               vid_to_commit,
               self.vid]
        await qubes_lvm_coro(cmd, self.log)
        await reset_cache_coro()
        # make sure the one we've committed right now is properly
        # detected as the current one - before removing anything
        assert self._vid_current == self.vid

        # and remove old snapshots, if needed
        await self._remove_revisions()
        return True

    @qubes.storage.Volume.locked
    async def create(self):
        assert self.vid
        assert self.size
        if self.save_on_stop:
            if self.source:
                cmd = ['clone', self.source.path, self.vid]
            else:
                cmd = [
                    'create',
                    self.pool._pool_id,  # pylint: disable=protected-access
                    self.vid.split('/', 1)[1],
                    str(self.size)
                ]
            await qubes_lvm_coro(cmd, self.log)
            await reset_cache_coro()
        return self

    @qubes.storage.Volume.locked
    async def remove(self):
        assert self.vid
        try:
            if os.path.exists('/dev/' + self._vid_snap):
                cmd = ['remove', self._vid_snap]
                await qubes_lvm_coro(cmd, self.log)
        except AttributeError:
            pass

        try:
            if os.path.exists('/dev/' + self._vid_import):
                cmd = ['remove', self._vid_import]
                await qubes_lvm_coro(cmd, self.log)
        except AttributeError:
            pass

        await self._remove_revisions(self.revisions.keys())
        if not os.path.exists(self.path):
            return
        assert self.path.startswith('/dev/'), \
            'bad value for self.path: %r' % self.path
        cmd = ['remove', self.path[5:]]
        await qubes_lvm_coro(cmd, self.log)
        await reset_cache_coro()
        # pylint: disable=protected-access
        self.pool._volume_objects_cache.pop(self.vid, None)

    async def export(self):
        ''' Returns an object that can be `open()`. '''
        # make sure the device node is available
        cmd = ['activate', self.path]
        await qubes_lvm_coro(cmd, self.log)
        devpath = self.path
        return devpath

    @qubes.storage.Volume.locked
    async def import_volume(self, src_volume):
        if not src_volume.save_on_stop:
            return self

        if self.is_dirty():
            raise qubes.storage.StoragePoolException(
                'Cannot import to dirty volume {} -'
                ' start and stop a qube to cleanup'.format(self.vid))
        self.abort_if_import_in_progress()
        # HACK: neat trick to speed up testing if you have same physical thin
        # pool assigned to two qubes-pools i.e: qubes_dom0 and test-lvm
        # pylint: disable=line-too-long
        if hasattr(src_volume.pool, 'thin_pool') and \
                src_volume.pool.thin_pool == self.pool.thin_pool:  # NOQA
            await self._commit(src_volume.path[len('/dev/'):], keep=True)
        else:
            cmd = ['create',
                   self.pool._pool_id,  # pylint: disable=protected-access
                   self._vid_import.split('/')[1],
                   str(src_volume.size)]
            await qubes_lvm_coro(cmd, self.log)
            src_path = await qubes.utils.coro_maybe(src_volume.export())
            try:
                cmd = [_dd, 'if=' + src_path, 'of=/dev/' + self._vid_import,
                       'conv=sparse,nocreat,fsync', 'status=none', 'bs=128K']
                if not os.access('/dev/' + self._vid_import, os.W_OK) or \
                        not os.access(src_path, os.R_OK):
                    cmd.insert(0, _sudo)

                p = await asyncio.create_subprocess_exec(*cmd)
                await p.wait()
            finally:
                await qubes.utils.coro_maybe(
                    src_volume.export_end(src_path))
            if p.returncode != 0:
                cmd = ['remove', self._vid_import]
                await qubes_lvm_coro(cmd, self.log)
                raise qubes.storage.StoragePoolException(
                    'Failed to import volume {!r}, dd exit code: {}'.format(
                        src_volume, p.returncode))
            await self._commit(self._vid_import)

        return self

    @qubes.storage.Volume.locked
    async def import_data(self, size):
        ''' Returns an object that can be `open()`. '''
        if self.is_dirty():
            raise qubes.storage.StoragePoolException(
                'Cannot import data to dirty volume {}, stop the qube first'.
                format(self.vid))
        self.abort_if_import_in_progress()
        # pylint: disable=protected-access
        cmd = ['create', self.pool._pool_id, self._vid_import.split('/')[1],
               str(size)]
        await qubes_lvm_coro(cmd, self.log)
        await reset_cache_coro()
        devpath = '/dev/' + self._vid_import
        return devpath

    @qubes.storage.Volume.locked
    async def import_data_end(self, success):
        '''Either commit imported data, or discard temporary volume'''
        if not os.path.exists('/dev/' + self._vid_import):
            raise qubes.storage.StoragePoolException(
                'No import operation in progress on {}'.format(self.vid))
        if success:
            await self._commit(self._vid_import)
        else:
            cmd = ['remove', self._vid_import]
            await qubes_lvm_coro(cmd, self.log)

    def abort_if_import_in_progress(self):
        try:
            devpath = '/dev/' + self._vid_import
            if os.path.exists(devpath):
                raise qubes.storage.StoragePoolException(
                    'Import operation in progress on {}'.format(self.vid))
        except AttributeError:  # self._vid_import
            # no vid_import - import definitely not in progress
            pass

    def is_dirty(self):
        if self.save_on_stop:
            return os.path.exists('/dev/' + self._vid_snap)
        return False

    def is_outdated(self):
        if not self.snap_on_start:
            return False
        if self._vid_snap not in size_cache:
            return False
        # pylint: disable=protected-access
        return (size_cache[self._vid_snap]['origin'] !=
               self.source.path.split('/')[-1])

    @qubes.storage.Volume.locked
    async def revert(self, revision=None):
        if self.is_dirty():
            raise qubes.storage.StoragePoolException(
                'Cannot revert dirty volume {}, stop the qube first'.format(
                    self.vid))
        self.abort_if_import_in_progress()
        if revision is None:
            revision = \
                max(self.revisions.items(), key=_revision_sort_key)[0]
        old_path = '/dev/' + self.vid + '-' + revision
        if not os.path.exists(old_path):
            msg = "Volume {!s} has no {!s}".format(self, old_path)
            raise qubes.storage.StoragePoolException(msg)

        if self.vid in size_cache:
            cmd = ['remove', self.vid]
            await qubes_lvm_coro(cmd, self.log)
        cmd = ['clone', self.vid + '-' + revision, self.vid]
        await qubes_lvm_coro(cmd, self.log)
        await reset_cache_coro()
        return self

    @qubes.storage.Volume.locked
    async def resize(self, size):
        ''' Expands volume, throws
            :py:class:`qubst.storage.qubes.storage.StoragePoolException` if
            given size is less than current_size
        '''
        if not self.rw:
            msg = 'Can not resize readonly volume {!s}'.format(self)
            raise qubes.storage.StoragePoolException(msg)

        if size < self.size:
            raise qubes.storage.StoragePoolException(
                'For your own safety, shrinking of %s is'
                ' disabled (%d < %d). If you really know what you'
                ' are doing, use `lvresize` on %s manually.' %
                (self.name, size, self.size, self.vid))

        if size == self.size:
            return

        if self.is_dirty() or self.snap_on_start:
            cmd = ['extend', self._vid_snap, str(size)]
            await qubes_lvm_coro(cmd, self.log)
        elif hasattr(self, '_vid_import') and \
                os.path.exists('/dev/' + self._vid_import):
            cmd = ['extend', self._vid_import, str(size)]
            await qubes_lvm_coro(cmd, self.log)
        elif self.save_on_stop and not self.snap_on_start:
            cmd = ['extend', self._vid_current, str(size)]
            await qubes_lvm_coro(cmd, self.log)

        self._size = size
        await reset_cache_coro()

    async def _snapshot(self):
        try:
            cmd = ['remove', self._vid_snap]
            await qubes_lvm_coro(cmd, self.log)
        except AssertionError:
            raise
        except:  # pylint: disable=bare-except
            pass

        if self.source is None:
            cmd = ['clone', self._vid_current, self._vid_snap]
        else:
            cmd = ['clone', self.source.path, self._vid_snap]
        await qubes_lvm_coro(cmd, self.log)

    async def _remove_if_exists(self, vid):
        """Remove LVM volume if it exists.

        :return bool True if anything was removed, False otherwise
        """
        if not os.path.exists('/dev/' + vid):
            return False
        cmd = ['remove', vid]
        await qubes_lvm_coro(cmd, self.log)
        return True

    @qubes.storage.Volume.locked
    async def start(self):
        self.abort_if_import_in_progress()
        try:
            if self.snap_on_start or self.save_on_stop:
                if not self.save_on_stop or not self.is_dirty():
                    await self._snapshot()
            else:
                await self._reset()
        finally:
            await reset_cache_coro()
        return self

    @qubes.storage.Volume.locked
    async def stop(self):
        # assume something was changed in case of exception too
        changed = True
        try:
            if self.save_on_stop:
                changed = await self._commit()
            elif self.snap_on_start:
                changed = await self._remove_if_exists(self._vid_snap)
            else:
                changed = await self._remove_if_exists(self.vid)
        finally:
            if changed:
                await reset_cache_coro()
        return self

    async def verify(self):
        ''' Verifies the volume. '''
        if not self.save_on_stop and not self.snap_on_start:
            # volatile volumes don't need any files
            return True
        if self.source is not None:
            vid = self.source.path[len('/dev/'):]
        else:
            vid = self._vid_current
        try:
            vol_info = size_cache[vid]
            if vol_info['attr'][4] != 'a':
                raise qubes.storage.StoragePoolException(
                    'volume {} not active'.format(vid))
        except KeyError:
            raise qubes.storage.StoragePoolException(
                'volume {} missing'.format(vid))
        return True


    def block_device(self):
        ''' Return :py:class:`qubes.storage.BlockDevice` for serialization in
            the libvirt XML template as <disk>.
        '''
        if self.snap_on_start or self.save_on_stop:
            return qubes.storage.BlockDevice(
                '/dev/' + self._vid_snap, self.name, None,
                self.rw, self.domain, self.devtype)

        return super().block_device()

    def encrypted_volume_path(self, qube_name, device_name):
        """Find the name of the encrypted volatile volume"""
        # pylint: disable=line-too-long
        vid = '-'.join(i.replace('-', '--') for i in self._vid_current.split('/'))
        return '/dev/mapper/' + vid + '@crypt'

    @property
    def usage(self):  # lvm thin usage always returns at least the same usage as
                      # the parent
        refresh_cache()
        try:
            return qubes.storage.lvm.size_cache[self._vid_current]['usage']
        except KeyError:
            return 0


def pool_exists(pool_id):
    ''' Return true if pool exists '''
    try:
        vol_info = size_cache[pool_id]
        return vol_info['attr'][0] == 't'
    except KeyError:
        return False

def _get_lvm_cmdline(cmd):
    ''' Build command line for :program:`lvm` call.
    The purpose of this function is to keep all the detailed lvm options in
    one place.

    :param cmd: array of str, where cmd[0] is action and the rest are arguments
    :return array of str appropriate for subprocess.Popen
    '''
    action = cmd[0]
    if action == 'remove':
        assert len(cmd) == 2, 'wrong number of arguments for remove'
        assert not cmd[1].startswith('/'), 'absolute path to \'remove\'???'
        assert '/' in cmd[1], 'refusing to delete entire volume group'
        lvm_cmd = ['lvremove', '--force', '--', cmd[1]]
    elif action == 'clone':
        assert len(cmd) == 3, 'wrong number of arguments for clone'
        lvm_cmd = ['lvcreate', '--setactivationskip=n', '--activate=y',
                   '--snapshot', '--type=thin', '--name=' + cmd[2],
                   '--', cmd[1]]
    elif action == 'create':
        assert len(cmd) == 4, 'wrong number of arguments for create'
        lvm_cmd = ['lvcreate', '--thin', '--setactivationskip=n',
                   '--activate=y', '--name=' + cmd[2],
                   '--virtualsize=' + cmd[3] + 'B', '--', cmd[1]]
    elif action == 'extend':
        assert len(cmd) == 3, 'wrong number of arguments for extend'
        lvm_cmd = ["lvextend", "--size=" + cmd[2] + 'B', '--', cmd[1]]
    elif action == 'activate':
        assert len(cmd) == 2, 'wrong number of arguments for activate'
        lvm_cmd = ['lvchange', '--activate=y', '--', cmd[1]]
    elif action == 'rename':
        assert len(cmd) == 3, 'wrong number of arguments for rename'
        lvm_cmd = ['lvrename', '--', cmd[1], cmd[2]]
    else:
        raise NotImplementedError('unsupported action: ' + action)
    if os.getuid() != 0:
        cmd = [_sudo, _lvm] + lvm_cmd
    else:
        cmd = [_lvm] + lvm_cmd

    return cmd

def _process_lvm_output(returncode, stdout, stderr, log):
    '''Process output of LVM, determine if the call was successful and
    possibly log warnings.'''
    # Filter out warning about intended over-provisioning.
    # Upstream discussion about missing option to silence it:
    # https://bugzilla.redhat.com/1347008
    err = '\n'.join(line for line in stderr.decode().splitlines()
        if 'exceeds the size of thin pool' not in line)
    if stdout:
        log.debug(stdout)
    if returncode == 0 and err:
        log.warning(err)
    elif returncode != 0:
        assert err, "Command exited unsuccessful, but printed nothing to stderr"
        err = err.replace('%', '%%')
        raise qubes.storage.StoragePoolException(err)
    return True

async def qubes_lvm_coro(cmd, log=logging.getLogger('qubes.storage.lvm')):
    ''' Call :program:`lvm` to execute an LVM operation '''
    environ={'LC_ALL': 'C.UTF-8', **os.environ}
    if cmd[0] == "remove":
        if not os.path.exists('/dev/' + cmd[1]):
            # ignore errors if the file does not exist
            return
        pre_cmd = ['blkdiscard', '-p', '1G', '/dev/'+cmd[1]]
        p = await asyncio.create_subprocess_exec(*pre_cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True, env=environ)
        _, _ = await p.communicate()
    cmd = _get_lvm_cmdline(cmd)
    log.debug('Invoked with arguments %r', cmd)
    p = await asyncio.create_subprocess_exec(*cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        close_fds=True, env=environ)
    out, err = await p.communicate()
    return _process_lvm_output(p.returncode, out, err, log)


def reset_cache():
    qubes.storage.lvm.size_cache = init_cache()
    qubes.storage.lvm.size_cache_time = time.monotonic()

async def reset_cache_coro():
    qubes.storage.lvm.size_cache = await init_cache_coro()
    qubes.storage.lvm.size_cache_time = time.monotonic()

def refresh_cache():
    '''Reset size cache, if it's older than 30sec '''
    if size_cache_time+30 < time.monotonic():
        reset_cache()
