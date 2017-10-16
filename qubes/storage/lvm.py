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
import operator
import os
import subprocess

import time

import asyncio

import qubes
import qubes.storage
import qubes.utils


def check_lvm_version():
    #Check if lvm is very very old, like in Travis-CI
    try:
        lvm_help = subprocess.check_output(['lvm', 'lvcreate', '--help'],
            stderr=subprocess.DEVNULL).decode()
        return '--setactivationskip' not in lvm_help
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass

lvm_is_very_old = check_lvm_version()

class ThinPool(qubes.storage.Pool):
    ''' LVM Thin based pool implementation
    '''  # pylint: disable=protected-access

    size_cache = None

    driver = 'lvm_thin'

    def __init__(self, volume_group, thin_pool, revisions_to_keep=1, **kwargs):
        super(ThinPool, self).__init__(revisions_to_keep=revisions_to_keep,
                                       **kwargs)
        self.volume_group = volume_group
        self.thin_pool = thin_pool
        self._pool_id = "{!s}/{!s}".format(volume_group, thin_pool)
        self.log = logging.getLogger('qube.storage.lvm.%s' % self._pool_id)

        self._volume_objects_cache = {}

    @property
    def config(self):
        return {
            'name': self.name,
            'volume_group': self.volume_group,
            'thin_pool': self.thin_pool,
            'driver': ThinPool.driver
        }

    def destroy(self):
        pass  # TODO Should we remove an existing pool?

    def init_volume(self, vm, volume_config):
        ''' Initialize a :py:class:`qubes.storage.Volume` from `volume_config`.
        '''

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

    def setup(self):
        pass  # TODO Should we create a non existing pool?

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
            if vid.endswith('-snap'):
                # implementation detail volume
                continue
            if vid.endswith('-back'):
                # old revisions
                continue
            config = {
                'pool': self,
                'vid': vid,
                'name': vid,
                'volume_group': self.volume_group,
                'rw': vol_info['attr'][1] == 'w',
            }
            volumes += [ThinVolume(**config)]
        return volumes


def init_cache(log=logging.getLogger('qubes.storage.lvm')):
    cmd = ['lvs', '--noheadings', '-o',
           'vg_name,pool_lv,name,lv_size,data_percent,lv_attr,origin',
           '--units', 'b', '--separator', ';']
    if os.getuid() != 0:
        cmd.insert(0, 'sudo')
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        close_fds=True)
    out, err = p.communicate()
    return_code = p.returncode
    if return_code == 0 and err:
        log.warning(err)
    elif return_code != 0:
        raise qubes.storage.StoragePoolException(err)

    result = {}

    for line in out.splitlines():
        line = line.decode().strip()
        pool_name, pool_lv, name, size, usage_percent, attr, \
            origin = line.split(';', 6)
        if '' in [pool_name, pool_lv, name, size, usage_percent]:
            continue
        name = pool_name + "/" + name
        size = int(size[:-1])  # Remove 'B' suffix
        usage = int(size / 100 * float(usage_percent))
        result[name] = {'size': size, 'usage': usage, 'pool_lv': pool_lv,
            'attr': attr, 'origin': origin}

    return result


size_cache = init_cache()

class ThinVolume(qubes.storage.Volume):
    ''' Default LVM thin volume implementation
    '''  # pylint: disable=too-few-public-methods


    def __init__(self, volume_group, size=0, **kwargs):
        self.volume_group = volume_group
        super(ThinVolume, self).__init__(size=size, **kwargs)
        self.log = logging.getLogger('qube.storage.lvm.%s' % str(self.pool))

        if self.snap_on_start or self.save_on_stop:
            self._vid_snap = self.vid + '-snap'

        self._size = size

    @property
    def path(self):
        return '/dev/' + self.vid

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
            seconds = int(revision_vid[:-len('-back')])
            iso_date = qubes.storage.isodate(seconds).split('.', 1)[0]
            revisions[revision_vid] = iso_date
        return revisions

    @property
    def size(self):
        try:
            return qubes.storage.lvm.size_cache[self.vid]['size']
        except KeyError:
            return self._size

    @size.setter
    def size(self, _):
        raise qubes.storage.StoragePoolException(
            "You shouldn't use lvm size setter")

    def _reset(self):
        ''' Resets a volatile volume '''
        assert not self.snap_on_start and not self.save_on_stop, \
            "Not a volatile volume"
        self.log.debug('Resetting volatile ' + self.vid)
        try:
            cmd = ['remove', self.vid]
            qubes_lvm(cmd, self.log)
        except qubes.storage.StoragePoolException:
            pass
        # pylint: disable=protected-access
        cmd = ['create', self.pool._pool_id, self.vid.split('/')[1],
               str(self.size)]
        qubes_lvm(cmd, self.log)

    def _remove_revisions(self, revisions=None):
        '''Remove old volume revisions.

        If no revisions list is given, it removes old revisions according to
        :py:attr:`revisions_to_keep`

        :param revisions: list of revisions to remove
        '''
        if revisions is None:
            revisions = sorted(self.revisions.items(),
                key=operator.itemgetter(1))
            revisions = revisions[:-self.revisions_to_keep]
            revisions = [rev_id for rev_id, _ in revisions]

        for rev_id in revisions:
            try:
                cmd = ['remove', self.vid + rev_id]
                qubes_lvm(cmd, self.log)
            except qubes.storage.StoragePoolException:
                pass

    def _commit(self):
        msg = "Trying to commit {!s}, but it has save_on_stop == False"
        msg = msg.format(self)
        assert self.save_on_stop, msg

        msg = "Trying to commit {!s}, but it has rw == False"
        msg = msg.format(self)
        assert self.rw, msg
        assert hasattr(self, '_vid_snap')

        if self.revisions_to_keep > 0:
            cmd = ['clone', self.vid,
                '{}-{}-back'.format(self.vid, int(time.time()))]
            qubes_lvm(cmd, self.log)
            self._remove_revisions()

        # TODO: when converting this function to coroutine, this _must_ be
        # under a lock
        # remove old volume only after _successful_ clone of the new one
        cmd = ['rename', self.vid, self.vid + '-tmp']
        qubes_lvm(cmd, self.log)
        try:
            cmd = ['clone', self._vid_snap, self.vid]
            qubes_lvm(cmd, self.log)
        except:
            # restore original volume
            cmd = ['rename', self.vid + '-tmp', self.vid]
            qubes_lvm(cmd, self.log)
            raise
        else:
            cmd = ['remove', self.vid + '-tmp']
            qubes_lvm(cmd, self.log)


    def create(self):
        assert self.vid
        assert self.size
        if self.save_on_stop:
            if self.source:
                cmd = ['clone', str(self.source), self.vid]
            else:
                cmd = [
                    'create',
                    self.pool._pool_id,  # pylint: disable=protected-access
                    self.vid.split('/', 1)[1],
                    str(self.size)
                ]
            qubes_lvm(cmd, self.log)
            reset_cache()
        return self

    def remove(self):
        assert self.vid
        if self.is_dirty():
            cmd = ['remove', self._vid_snap]
            qubes_lvm(cmd, self.log)

        self._remove_revisions(self.revisions.keys())
        if not os.path.exists(self.path):
            return
        cmd = ['remove', self.vid]
        qubes_lvm(cmd, self.log)
        reset_cache()
        # pylint: disable=protected-access
        self.pool._volume_objects_cache.pop(self.vid, None)

    def export(self):
        ''' Returns an object that can be `open()`. '''
        # make sure the device node is available
        qubes_lvm(['activate', self.vid], self.log)
        devpath = '/dev/' + self.vid
        return devpath

    @asyncio.coroutine
    def import_volume(self, src_volume):
        if not src_volume.save_on_stop:
            return self

        # HACK: neat trick to speed up testing if you have same physical thin
        # pool assigned to two qubes-pools i.e: qubes_dom0 and test-lvm
        # pylint: disable=line-too-long
        if isinstance(src_volume.pool, ThinPool) and \
                src_volume.pool.thin_pool == self.pool.thin_pool:  # NOQA
            cmd = ['remove', self.vid]
            qubes_lvm(cmd, self.log)
            cmd = ['clone', str(src_volume), str(self)]
            qubes_lvm(cmd, self.log)
        else:
            src_path = src_volume.export()
            cmd = ['dd', 'if=' + src_path, 'of=/dev/' + self.vid,
                'conv=sparse']
            p = yield from asyncio.create_subprocess_exec(*cmd)
            yield from p.wait()
            if p.returncode != 0:
                raise qubes.storage.StoragePoolException(
                    'Failed to import volume {!r}, dd exit code: {}'.format(
                        src_volume, p.returncode))
            reset_cache()

        return self

    def import_data(self):
        ''' Returns an object that can be `open()`. '''
        devpath = '/dev/' + self.vid
        return devpath

    def is_dirty(self):
        if self.save_on_stop:
            return os.path.exists('/dev/' + self._vid_snap)
        return False

    def is_outdated(self):
        if not self.snap_on_start:
            return False
        if self._vid_snap not in size_cache:
            return False
        return (size_cache[self._vid_snap]['origin'] !=
               self.source.vid.split('/')[1])


    def revert(self, revision=None):
        if revision is None:
            revision = \
                max(self.revisions.items(), key=operator.itemgetter(1))[0]
        old_path = self.path + '-' + revision
        if not os.path.exists(old_path):
            msg = "Volume {!s} has no {!s}".format(self, old_path)
            raise qubes.storage.StoragePoolException(msg)

        cmd = ['remove', self.vid]
        qubes_lvm(cmd, self.log)
        cmd = ['clone', self.vid + '-' + revision, self.vid]
        qubes_lvm(cmd, self.log)
        reset_cache()
        return self

    def resize(self, size):
        ''' Expands volume, throws
            :py:class:`qubst.storage.qubes.storage.StoragePoolException` if
            given size is less than current_size
        '''
        if not self.rw:
            msg = 'Can not resize reađonly volume {!s}'.format(self)
            raise qubes.storage.StoragePoolException(msg)

        if size < self.size:
            raise qubes.storage.StoragePoolException(
                'For your own safety, shrinking of %s is'
                ' disabled. If you really know what you'
                ' are doing, use `lvresize` on %s manually.' %
                (self.name, self.vid))

        if size == self.size:
            return

        cmd = ['extend', self.vid, str(size)]
        qubes_lvm(cmd, self.log)
        if self.is_dirty():
            cmd = ['extend', self._vid_snap, str(size)]
            qubes_lvm(cmd, self.log)
        reset_cache()

    def _snapshot(self):
        try:
            cmd = ['remove', self._vid_snap]
            qubes_lvm(cmd, self.log)
        except:  # pylint: disable=bare-except
            pass

        if self.source is None:
            cmd = ['clone', self.vid, self._vid_snap]
        else:
            cmd = ['clone', str(self.source), self._vid_snap]
        qubes_lvm(cmd, self.log)


    def start(self):
        try:
            if self.snap_on_start or self.save_on_stop:
                if not self.save_on_stop or not self.is_dirty():
                    self._snapshot()
            else:
                self._reset()
        finally:
            reset_cache()
        return self

    def stop(self):
        try:
            if self.save_on_stop:
                self._commit()
            if self.snap_on_start or self.save_on_stop:
                cmd = ['remove', self._vid_snap]
                qubes_lvm(cmd, self.log)
            else:
                cmd = ['remove', self.vid]
                qubes_lvm(cmd, self.log)
        finally:
            reset_cache()
        return self

    def verify(self):
        ''' Verifies the volume. '''
        if not self.save_on_stop and not self.snap_on_start:
            # volatile volumes don't need any files
            return True
        if self.source is not None:
            vid = str(self.source)
        else:
            vid = self.vid
        try:
            vol_info = size_cache[vid]
            if vol_info['attr'][4] != 'a':
                raise qubes.storage.StoragePoolException(
                    'volume {} not active'.format(vid))
        except KeyError:
            raise qubes.storage.StoragePoolException(
                'volume {} missing'.format(vid))


    def block_device(self):
        ''' Return :py:class:`qubes.storage.BlockDevice` for serialization in
            the libvirt XML template as <disk>.
        '''
        if self.snap_on_start or self.save_on_stop:
            return qubes.storage.BlockDevice(
                '/dev/' + self._vid_snap, self.name, self.script,
                self.rw, self.domain, self.devtype)

        return super(ThinVolume, self).block_device()

    @property
    def usage(self):  # lvm thin usage always returns at least the same usage as
                      # the parent
        try:
            return qubes.storage.lvm.size_cache[self.vid]['usage']
        except KeyError:
            return 0


def pool_exists(pool_id):
    ''' Return true if pool exists '''
    try:
        vol_info = size_cache[pool_id]
        return vol_info['attr'][0] == 't'
    except KeyError:
        return False


def qubes_lvm(cmd, log=logging.getLogger('qubes.storage.lvm')):
    ''' Call :program:`lvm` to execute an LVM operation '''
    action = cmd[0]
    if action == 'remove':
        lvm_cmd = ['lvremove', '-f', cmd[1]]
    elif action == 'clone':
        lvm_cmd = ['lvcreate', '-kn', '-ay', '-s', cmd[1], '-n', cmd[2]]
    elif action == 'create':
        lvm_cmd = ['lvcreate', '-T', cmd[1], '-kn', '-ay', '-n', cmd[2], '-V',
           str(cmd[3]) + 'B']
    elif action == 'extend':
        size = int(cmd[2]) / (1024 * 1024)
        lvm_cmd = ["lvextend", "-L%s" % size, cmd[1]]
    elif action == 'activate':
        lvm_cmd = ['lvchange', '-ay', cmd[1]]
    elif action == 'rename':
        lvm_cmd = ['lvrename', cmd[1], cmd[2]]
    else:
        raise NotImplementedError('unsupported action: ' + action)
    if lvm_is_very_old:
        # old lvm in trusty image used there does not support -k option
        lvm_cmd = [x for x in lvm_cmd if x != '-kn']
    if os.getuid() != 0:
        cmd = ['sudo', 'lvm'] + lvm_cmd
    else:
        cmd = ['lvm'] + lvm_cmd
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        close_fds=True)
    out, err = p.communicate()
    return_code = p.returncode
    if out:
        log.debug(out)
    if return_code == 0 and err:
        log.warning(err)
    elif return_code != 0:
        assert err, "Command exited unsuccessful, but printed nothing to stderr"
        raise qubes.storage.StoragePoolException(err)
    return True


def reset_cache():
    qubes.storage.lvm.size_cache = init_cache()
