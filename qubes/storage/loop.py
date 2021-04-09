#
# The Qubes OS Project, https://www.qubes-os.org/
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

"""
This module contains loop device handling code.
"""

import os
from _qubes_loop import ffi, lib

class LoopDevice(object):
    """
    A loop device
    """
    __slots__ = ('device', 'inode', 'backing_file', 'fd', 'refcount', 'path')
    def __init__(self, device, inode, backing_file, path):
        self.device, self.inode, self.backing_file, self.refcount, self.path = device, inode, backing_file, 1, path

def process_loop_dev(res, fd, mapping, i, prefix):
    path = '/dev/loop%d' % res
    sysfs_fd = os.open(i + '/loop/backing_file', os.O_RDONLY|os.O_NOCTTY|os.O_CLOEXEC, dir_fd=fd)
    with open(sysfs_fd, 'rb') as back, \
         open(path, 'rb') as loop_dev, \
         ffi.new('struct loop_info64 *') as loop_info:
        backing_file = back.read()
        if not backing_file.startswith(prefix + b'/'):
            return
        if not backing_file.endswith(b'\n'):
            raise ValueError('bad response from kernel')
        if lib.qubes_get_loop_dev_info(loop_dev.fileno(), loop_info):
            raise OSError('ioctl')
        stat_info = os.stat(backing_file[:-1])
        if stat_info.st_dev != loop_info.lo_device or \
           stat_info.st_ino != loop_info.lo_inode:
            raise OSError('inode mismatch')
        dev = LoopDevice(loop_info.lo_device, loop_info.lo_inode, backing_file[:-1], path)
        mapping[(loop_info.lo_device, loop_info.lo_inode)] = dev
        mapping[backing_file[:-1]] = dev

class LoopDevicePool(object):
    """
    A pool of loop devices.
    """
    __slots__ = ('_devices',)
    def __init__(self, prefix):
        prefix = prefix.encode('UTF-8', 'surrogateescape')
        self._devices = {}
        fd = os.open('/sys/devices/virtual/block', os.O_DIRECTORY|os.O_RDONLY|os.O_CLOEXEC)
        try:
            for i in os.listdir(fd):
                if not i.startswith('loop'):
                    continue
                try:
                    res = int(i[4:])
                except ValueError:
                    continue
                process_loop_dev(res, fd, self._devices, i, prefix)
        finally:
            os.close(fd)
