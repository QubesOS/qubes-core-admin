#!/usr/bin/python2
#
# The Qubes OS Project, http://www.qubes-os.org
#
# Copyright (C) 2011  Marek Marczykowski <marmarek@invisiblethingslab.com>
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.
#
#

from qubes import QubesVm,QubesException
from qubes import xs, xl_ctx
import sys
#import os
#import os.path
import subprocess
#import fcntl
import re
#import shutil
#import uuid
#import time
from datetime import datetime
from qmemman_client import QMemmanClient

import xen.lowlevel.xc
import xen.lowlevel.xl
import xen.lowlevel.xs

def mbytes_to_kmg(size):
    if size > 1024:
        return "%d GB" % (size/1024)
    else:
        return "%d MB" % size

def kbytes_to_kmg(size):
    if size > 1024:
        return mbytes_to_kmg(size/1024)
    else:
        return "%d KB" % size

def bytes_to_kmg(size):
    if size > 1024:
        return kbytes_to_kmg(size/1024)
    else:
        return "%d B" % size


def block_devid_to_name(devid):
    major = devid / 256
    minor = devid % 256

    dev_class = ""
    if major == 202:
        dev_class = "xvd"
    elif major == 8:
        dev_class = "sd"
    else:
        raise QubesException("Unknown device class %d" % major)

    if minor % 16 == 0:
        return "%s%c" % (dev_class, ord('a')+minor/16)
    else:
        return "%s%c%d" % (dev_class, ord('a')+minor/16, minor%16)

def block_name_to_majorminor(name):
    # check if it is already devid
    if isinstance(name, int):
        return (name / 256, name % 256)
    if name.isdigit():
        return (int(name) / 256, int(name) % 256)

    major = 0
    minor = 0

    name_match = re.match(r"([a-z]+)([a-z])([0-9]*)", name)
    if not name_match:
        raise QubesException("Invalid device name: %s" % name)

    disk = True
    if name_match.group(1) == "xvd":
        major = 202
    elif name_match.group(1) == "sd":
        major = 8
    elif name.startswith("scd"):
        disk = False
        major = 11
    elif name.startswith("sr"):
        disk = False
        major = 11
    else:
        raise QubesException("Unknown device type %s" % name_match.group(1))

    if disk:
        minor = (ord(name_match.group(2))-ord('a')) * 16
    else:
        minor = 0
    if name_match.group(3):
        minor += int(name_match.group(3))

    return (major, minor)


def block_name_to_devid(name):
    # check if it is already devid
    if isinstance(name, int):
        return name
    if name.isdigit():
        return int(name)

    (major, minor) = block_name_to_majorminor(name)
    return major << 8 | minor

def block_list(vm = None):
    device_re = re.compile(r"^[a-z0-9]{1,8}$")
    # FIXME: any better idea of desc_re?
    desc_re = re.compile(r"^.{1,255}$")
    mode_re = re.compile(r"^[rw]$")

    vm_list = []
    if vm is not None:
        if not vm.is_running():
            return []
        else:
            vm_list = [ str(vm.xid) ]
    else:
         vm_list = xs.ls('', '/local/domain')

    devices_list = {}
    for xid in vm_list:
        vm_name = xs.read('', '/local/domain/%s/name' % xid)
        vm_devices = xs.ls('', '/local/domain/%s/qubes-block-devices' % xid)
        if vm_devices is None:
            continue
        for device in vm_devices:
            # Sanitize device name
            if not device_re.match(device):
                print >> sys.stderr, "Invalid device name in VM '%s'" % vm_name
                continue

            device_size = xs.read('', '/local/domain/%s/qubes-block-devices/%s/size' % (xid, device))
            device_desc = xs.read('', '/local/domain/%s/qubes-block-devices/%s/desc' % (xid, device))
            device_mode = xs.read('', '/local/domain/%s/qubes-block-devices/%s/mode' % (xid, device))

            if not device_size.isdigit():
                print >> sys.stderr, "Invalid %s device size in VM '%s'" % (device, vm_name)
                continue
            if not desc_re.match(device_desc):
                print >> sys.stderr, "Invalid %s device desc in VM '%s'" % (device, vm_name)
                continue
            if not mode_re.match(device_mode):
                print >> sys.stderr, "Invalid %s device mode in VM '%s'" % (device, vm_name)
                continue
            visible_name = "%s:%s" % (vm_name, device)
            devices_list[visible_name] = {"name": visible_name, "xid":int(xid),
                "vm": vm_name, "device":device, "size":int(device_size),
                "desc":device_desc, "mode":device_mode}

    return devices_list

def block_check_attached(backend_vm, device, backend_xid = None):
    if backend_xid is None:
        backend_xid = backend_vm.xid
    vm_list = xs.ls('', '/local/domain/%d/backend/vbd' % backend_xid)
    if vm_list is None:
        return None
    device_majorminor = block_name_to_majorminor(device)
    for vm_xid in vm_list:
        for devid in xs.ls('', '/local/domain/%d/backend/vbd/%s' % (backend_xid, vm_xid)):
            phys_device = xs.read('', '/local/domain/%d/backend/vbd/%s/%s/physical-device' % (backend_xid, vm_xid, devid))
            if phys_device is None or not phys_device.find(':'):
                # Skip not-phy devices
                continue
            (tmp_major, tmp_minor) = phys_device.split(":")
            tmp_major = int(tmp_major, 16)
            tmp_minor = int(tmp_minor, 16)
            if (tmp_major, tmp_minor) == device_majorminor:
                vm_name = xl_ctx.domid_to_name(int(vm_xid))
                frontend = block_devid_to_name(int(devid))
                return {"xid":int(vm_xid), "frontend": frontend, "devid": int(devid), "vm": vm_name}
    return None

def block_attach(vm, backend_vm, device, frontend="xvdi", mode="w", auto_detach=False):
    if not vm.is_running():
        raise QubesException("VM %s not running" % vm.name)

    if not backend_vm.is_running():
        raise QubesException("VM %s not running" % backend_vm.name)

    # Check if any device attached at this frontend
    if xs.read('', '/local/domain/%d/device/vbd/%d/state' % (vm.xid, block_name_to_devid(frontend))) == '4':
        raise QubesException("Frontend %s busy in VM %s, detach it first" % (frontend, vm.name))

    # Check if this device is attached to some domain
    attached_vm = block_check_attached(backend_vm, device)
    if attached_vm:
        if auto_detach:
            block_detach(None, attached_vm['devid'], vm_xid=attached_vm['vm_xid'])
        else:
            raise QubesException("Device %s from %s already connected to VM %s as %s" % (device, backend_vm.name, attached_vm['vm'], attached_vm['frontend']))

    xl_cmd = [ '/usr/sbin/xl', 'block-attach', vm.name, 'phy:/dev/' + device, frontend, mode, str(backend_vm.xid) ]
    subprocess.check_call(xl_cmd)

def block_detach(vm, frontend = "xvdi", vm_xid = None):
    # Get XID if not provided already
    if vm_xid is None:
        if not vm.is_running():
            raise QubesException("VM %s not running" % vm.name)
        # FIXME: potential race
        vm_xid = vm.xid

    # Check if this device is really connected
    if not xs.read('', '/local/domain/%d/device/vbd/%d/state' % (vm_xid, block_name_to_devid(frontend))) == '4':
        # Do nothing - device already detached
        return

    xl_cmd = [ '/usr/sbin/xl', 'block-detach', str(vm_xid), str(frontend)]
    subprocess.check_call(xl_cmd)

# vim:sw=4:et:
