#
# The Qubes OS Project, http://www.qubes-os.org
#
# Copyright (C) 2016 Bahtiar `kalkin-` Gadimov <bahtiar@gadimov.de>
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

''' Driver for storing vm images in a LVM thin pool '''

import logging
import os
import subprocess

import qubes


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

    def clone(self, source, target):
        cmd = ['clone', str(source), str(target)]
        qubes_lvm(cmd, self.log)
        return target

    def _commit(self, volume):
        msg = "Trying to commit {!s}, but it has save_on_stop == False"
        msg = msg.format(volume)
        assert volume.save_on_stop, msg

        msg = "Trying to commit {!s}, but it has rw == False"
        msg = msg.format(volume)
        assert volume.rw, msg
        assert hasattr(volume, '_vid_snap')

        try:
            cmd = ['remove', volume.vid + "-back"]
            qubes_lvm(cmd, self.log)
        except qubes.storage.StoragePoolException:
            pass
        cmd = ['clone', volume.vid, volume.vid + "-back"]
        qubes_lvm(cmd, self.log)

        cmd = ['remove', volume.vid]
        qubes_lvm(cmd, self.log)
        cmd = ['clone', volume._vid_snap, volume.vid]
        qubes_lvm(cmd, self.log)

    @property
    def config(self):
        return {
            'name': self.name,
            'volume_group': self.volume_group,
            'thin_pool': self.thin_pool,
            'driver': ThinPool.driver
        }

    def create(self, volume):
        assert volume.vid
        assert volume.size
        if volume.save_on_stop:
            if volume.source:
                cmd = ['clone', str(volume.source), volume.vid]
            else:
                cmd = [
                    'create',
                    self._pool_id,
                    volume.vid.split('/', 1)[1],
                    str(volume.size)
                ]
            qubes_lvm(cmd, self.log)
            reset_cache()
        return volume

    def destroy(self):
        pass  # TODO Should we remove an existing pool?

    def export(self, volume):
        ''' Returns an object that can be `open()`. '''
        devpath = '/dev/' + volume.vid
        return devpath

    def import_data(self, volume):
        ''' Returns an object that can be `open()`. '''
        devpath = '/dev/' + volume.vid
        return devpath

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

            volume_config['vid'] = "{!s}/{!s}-{!s}".format(
                self.volume_group, vm_name, volume_config['name'])

        volume_config['volume_group'] = self.volume_group

        return ThinVolume(**volume_config)

    def import_volume(self, dst_pool, dst_volume, src_pool, src_volume):
        if not src_volume.save_on_stop:
            return dst_volume

        src_path = src_pool.export(src_volume)

        # HACK: neat trick to speed up testing if you have same physical thin
        # pool assigned to two qubes-pools i.e: qubes_dom0 and test-lvm
        # pylint: disable=line-too-long
        if isinstance(src_pool, ThinPool) and src_pool.thin_pool == dst_pool.thin_pool:  # NOQA
            return self.clone(src_volume, dst_volume)
        else:
            dst_volume = self.create(dst_volume)

        cmd = ['sudo', 'dd', 'if=' + src_path, 'of=/dev/' + dst_volume.vid,
            'conv=sparse']
        subprocess.check_call(cmd)
        reset_cache()
        return dst_volume

    def is_dirty(self, volume):
        if volume.save_on_stop:
            return os.path.exists(volume.path + '-snap')
        return False

    def remove(self, volume):
        assert volume.vid
        if self.is_dirty(volume):
            cmd = ['remove', volume._vid_snap]
            qubes_lvm(cmd, self.log)

        if not os.path.exists(volume.path):
            return
        cmd = ['remove', volume.vid]
        qubes_lvm(cmd, self.log)
        reset_cache()

    def rename(self, volume, old_name, new_name):
        ''' Called when the domain changes its name '''
        new_vid = "{!s}/{!s}-{!s}".format(self.volume_group, new_name,
                                          volume.name)
        if volume.save_on_stop:
            cmd = ['clone', volume.vid, new_vid]
            qubes_lvm(cmd, self.log)
            cmd = ['remove', volume.vid]
            qubes_lvm(cmd, self.log)

        volume.vid = new_vid

        if volume.snap_on_start:
            volume._vid_snap = volume.vid + '-snap'
        reset_cache()
        return volume

    def revert(self, volume, revision=None):
        old_path = volume.path + '-back'
        if not os.path.exists(old_path):
            msg = "Volume {!s} has no {!s}".format(volume, old_path)
            raise qubes.storage.StoragePoolException(msg)

        cmd = ['remove', volume.vid]
        qubes_lvm(cmd, self.log)
        cmd = ['clone', volume.vid + '-back', volume.vid]
        qubes_lvm(cmd, self.log)
        reset_cache()
        return volume

    def resize(self, volume, size):
        ''' Expands volume, throws
            :py:class:`qubst.storage.qubes.storage.StoragePoolException` if
            given size is less than current_size
        '''
        if not volume.rw:
            msg = 'Can not resize reađonly volume {!s}'.format(volume)
            raise qubes.storage.StoragePoolException(msg)

        if size <= volume.size:
            raise qubes.storage.StoragePoolException(
                'For your own safety, shrinking of %s is'
                ' disabled. If you really know what you'
                ' are doing, use `lvresize` on %s manually.' %
                (volume.name, volume.vid))

        cmd = ['extend', volume.vid, str(size)]
        qubes_lvm(cmd, self.log)
        reset_cache()

    def setup(self):
        pass  # TODO Should we create a non existing pool?

    def start(self, volume):
        if volume.snap_on_start:
            if not volume.save_on_stop or not self.is_dirty(volume):
                self._snapshot(volume)
        elif not volume.save_on_stop:
            self._reset_volume(volume)

        reset_cache()
        return volume

    def stop(self, volume):
        if volume.save_on_stop and volume.snap_on_start:
            self._commit(volume)
        if volume.snap_on_start:
            cmd = ['remove', volume._vid_snap]
            qubes_lvm(cmd, self.log)
        elif not volume.save_on_stop:
            cmd = ['remove', volume.vid]
            qubes_lvm(cmd, self.log)
        reset_cache()
        return volume

    def _snapshot(self, volume):
        try:
            cmd = ['remove', volume._vid_snap]
            qubes_lvm(cmd, self.log)
        except:  # pylint: disable=bare-except
            pass

        if volume.source is None:
            cmd = ['clone', volume.vid, volume._vid_snap]
        else:
            cmd = ['clone', str(volume.source), volume._vid_snap]
        qubes_lvm(cmd, self.log)

    def verify(self, volume):
        ''' Verifies the volume. '''
        try:
            vol_info = size_cache[volume.vid]
            return vol_info['attr'][4] == 'a'
        except KeyError:
            return False

    @property
    def volumes(self):
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
            config = {
                'pool': self.name,
                'vid': vid,
                'name': vid,
                'volume_group': self.volume_group,
                'rw': vol_info['attr'][1] == 'w',
            }
            volumes += [ThinVolume(**config)]
        return volumes

    def _reset_volume(self, volume):
        ''' Resets a volatile volume '''
        assert volume._is_volatile, \
            'Expected a volatile volume, but got {!r}'.format(volume)
        self.log.debug('Resetting volatile ' + volume.vid)
        try:
            cmd = ['remove', volume.vid]
            qubes_lvm(cmd, self.log)
        except qubes.storage.StoragePoolException:
            pass
        cmd = ['create', self._pool_id, volume.vid.split('/')[1],
               str(volume.size)]
        qubes_lvm(cmd, self.log)


def init_cache(log=logging.getLogger('qube.storage.lvm')):
    cmd = ['lvs', '--noheadings', '-o',
           'vg_name,pool_lv,name,lv_size,data_percent,lv_attr',
           '--units', 'b', '--separator', ',']
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
        pool_name, pool_lv, name, size, usage_percent, attr = line.split(',', 5)
        if '' in [pool_name, pool_lv, name, size, usage_percent]:
            continue
        name = pool_name + "/" + name
        size = int(size[:-1])
        usage = int(size / 100 * float(usage_percent))
        result[name] = {'size': size, 'usage': usage, 'pool_lv': pool_lv,
            'attr': attr}

    return result


size_cache = init_cache()

class ThinVolume(qubes.storage.Volume):
    ''' Default LVM thin volume implementation
    '''  # pylint: disable=too-few-public-methods


    def __init__(self, volume_group, size=0, **kwargs):
        self.volume_group = volume_group
        super(ThinVolume, self).__init__(size=size, **kwargs)

        if self.snap_on_start and self.source is None:
            msg = "snap_on_start specified on {!r} but no volume source set"
            msg = msg.format(self.name)
            raise qubes.storage.StoragePoolException(msg)
        elif not self.snap_on_start and self.source is not None:
            msg = "source specified on {!r} but no snap_on_start set"
            msg = msg.format(self.name)
            raise qubes.storage.StoragePoolException(msg)

        if self.snap_on_start:
            self._vid_snap = self.vid + '-snap'

        self._size = size

    @property
    def path(self):
        return '/dev/' + self.vid

    @property
    def revisions(self):
        path = self.path + '-back'
        if os.path.exists(path):
            seconds = os.path.getctime(path)
            iso_date = qubes.storage.isodate(seconds).split('.', 1)[0]
            return {iso_date: path}
        return {}

    @property
    def _is_origin(self):
        return not self.snap_on_start and self.save_on_stop

    @property
    def _is_origin_snapshot(self):
        return self.snap_on_start and self.save_on_stop

    @property
    def _is_snapshot(self):
        return self.snap_on_start and not self.save_on_stop

    @property
    def _is_volatile(self):
        return not self.snap_on_start and not self.save_on_stop

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

    def block_device(self):
        ''' Return :py:class:`qubes.storage.BlockDevice` for serialization in
            the libvirt XML template as <disk>.
        '''
        if self.snap_on_start:
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


def qubes_lvm(cmd, log=logging.getLogger('qube.storage.lvm')):
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
        size = int(cmd[2]) / (1000 * 1000)
        lvm_cmd = ["lvextend", "-L%s" % size, cmd[1]]
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
