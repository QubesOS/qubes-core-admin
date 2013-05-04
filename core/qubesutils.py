#!/usr/bin/python
# -*- coding: utf-8 -*-
#
# The Qubes OS Project, http://www.qubes-os.org
#
# Copyright (C) 2011  Marek Marczykowski <marmarek@invisiblethingslab.com>
# Copyright (C) 2014  Wojciech Porczyk <wojciech@porczyk.eu>
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

from qubes import QubesVm,QubesException,QubesVmCollection
from qubes import QubesVmClasses
from qubes import xs
from qubes import system_path,vm_files
import sys
import os
import subprocess
import re
import time
import stat

import xen.lowlevel.xc
import xen.lowlevel.xs

BLKSIZE = 512

def mbytes_to_kmg(size):
    if size > 1024:
        return "%d GiB" % (size/1024)
    else:
        return "%d MiB" % size

def kbytes_to_kmg(size):
    if size > 1024:
        return mbytes_to_kmg(size/1024)
    else:
        return "%d KiB" % size

def bytes_to_kmg(size):
    if size > 1024:
        return kbytes_to_kmg(size/1024)
    else:
        return "%d B" % size

def size_to_human (size):
    """Humane readable size, with 1/10 precission"""
    if size < 1024:
        return str (size);
    elif size < 1024*1024:
        return str(round(size/1024.0,1)) + ' KiB'
    elif size < 1024*1024*1024:
        return str(round(size/(1024.0*1024),1)) + ' MiB'
    else:
        return str(round(size/(1024.0*1024*1024),1)) + ' GiB'

def parse_size(size):
    units = [ ('K', 1024), ('KB', 1024),
        ('M', 1024*1024), ('MB', 1024*1024),
        ('G', 1024*1024*1024), ('GB', 1024*1024*1024),
    ]

    size = size.strip().upper()
    if size.isdigit():
        return int(size)

    for unit, multiplier in units:
        if size.endswith(unit):
            size = size[:-len(unit)].strip()
            return int(size)*multiplier

    raise QubesException("Invalid size: {0}.".format(size))

def get_disk_usage_one(st):
    try:
        return st.st_blocks * BLKSIZE
    except AttributeError:
        return st.st_size

def get_disk_usage(path):
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

def print_stdout(text):
    print (text)

def print_stderr(text):
    print >> sys.stderr, (text)

###### Block devices ########

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

    if os.path.exists('/dev/%s' % name):
        blk_info = os.stat(os.path.realpath('/dev/%s' % name))
        if stat.S_ISBLK(blk_info.st_mode):
            return (blk_info.st_rdev / 256, blk_info.st_rdev % 256)

    major = 0
    minor = 0
    dXpY_style = False
    disk = True

    if name.startswith("xvd"):
        major = 202
    elif name.startswith("sd"):
        major = 8
    elif name.startswith("mmcblk"):
        dXpY_style = True
        major = 179
    elif name.startswith("scd"):
        disk = False
        major = 11
    elif name.startswith("sr"):
        disk = False
        major = 11
    elif name.startswith("loop"):
        dXpY_style = True
        disk = False
        major = 7
    elif name.startswith("md"):
        dXpY_style = True
        major = 9
    elif name.startswith("dm-"):
        disk = False
        major = 253
    else:
        # Unknown device
        return (0, 0)

    if not dXpY_style:
        name_match = re.match(r"^([a-z]+)([a-z-])([0-9]*)$", name)
    else:
        name_match = re.match(r"^([a-z]+)([0-9]*)(?:p([0-9]+))?$", name)
    if not name_match:
        raise QubesException("Invalid device name: %s" % name)

    if disk:
        if dXpY_style:
            minor = int(name_match.group(2))*8
        else:
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

def block_find_unused_frontend(vm = None):
    assert vm is not None
    assert vm.is_running()

    vbd_list = xs.ls('', '/local/domain/%d/device/vbd' % vm.xid)
    # xvd* devices
    major = 202
    # prefer xvdi
    for minor in range(8*16,254,16)+range(0,8*16,16):
        if vbd_list is None or str(major << 8 | minor) not in vbd_list:
            return block_devid_to_name(major << 8 | minor)
    return None

def block_list(vm = None, system_disks = False):
    device_re = re.compile(r"^[a-z0-9-]{1,12}$")
    # FIXME: any better idea of desc_re?
    desc_re = re.compile(r"^.{1,255}$")
    mode_re = re.compile(r"^[rw]$")

    xs_trans = xs.transaction_start()

    vm_list = []
    if vm is not None:
        if not vm.is_running():
            xs.transaction_end(xs_trans)
            return []
        else:
            vm_list = [ str(vm.xid) ]
    else:
         vm_list = xs.ls(xs_trans, '/local/domain')

    devices_list = {}
    for xid in vm_list:
        vm_name = xs.read(xs_trans, '/local/domain/%s/name' % xid)
        vm_devices = xs.ls(xs_trans, '/local/domain/%s/qubes-block-devices' % xid)
        if vm_devices is None:
            continue
        for device in vm_devices:
            # Sanitize device name
            if not device_re.match(device):
                print >> sys.stderr, "Invalid device name in VM '%s'" % vm_name
                continue

            device_size = xs.read(xs_trans, '/local/domain/%s/qubes-block-devices/%s/size' % (xid, device))
            device_desc = xs.read(xs_trans, '/local/domain/%s/qubes-block-devices/%s/desc' % (xid, device))
            device_mode = xs.read(xs_trans, '/local/domain/%s/qubes-block-devices/%s/mode' % (xid, device))

            if device_size is None or device_desc is None or device_mode is None:
                print >> sys.stderr, "Missing field in %s device parameters" % device
                continue
            if not device_size.isdigit():
                print >> sys.stderr, "Invalid %s device size in VM '%s'" % (device, vm_name)
                continue
            if not desc_re.match(device_desc):
                print >> sys.stderr, "Invalid %s device desc in VM '%s'" % (device, vm_name)
                continue
            if not mode_re.match(device_mode):
                print >> sys.stderr, "Invalid %s device mode in VM '%s'" % (device, vm_name)
                continue
            # Check if we know major number for this device; attach will work without this, but detach and check_attached don't
            if block_name_to_majorminor(device) == (0, 0):
                print >> sys.stderr, "Unsupported device %s:%s" % (vm_name, device)
                continue

            if not system_disks:
                if xid == '0' and device_desc.startswith(system_path["qubes_base_dir"]):
                    continue

            visible_name = "%s:%s" % (vm_name, device)
            devices_list[visible_name] = {"name": visible_name, "xid":int(xid),
                "vm": vm_name, "device":device, "size":int(device_size),
                "desc":device_desc, "mode":device_mode}

    xs.transaction_end(xs_trans)
    return devices_list

def block_check_attached(backend_vm, device, backend_xid = None):
    if backend_xid is None:
        backend_xid = backend_vm.xid
    xs_trans = xs.transaction_start()
    vm_list = xs.ls(xs_trans, '/local/domain/%d/backend/vbd' % backend_xid)
    if vm_list is None:
        xs.transaction_end(xs_trans)
        return None
    device_majorminor = None
    try:
        device_majorminor = block_name_to_majorminor(device)
    except:
        # Unknown devices will be compared directly - perhaps it is a filename?
        pass
    for vm_xid in vm_list:
        for devid in xs.ls(xs_trans, '/local/domain/%d/backend/vbd/%s' % (backend_xid, vm_xid)):
            (tmp_major, tmp_minor) = (0, 0)
            phys_device = xs.read(xs_trans, '/local/domain/%d/backend/vbd/%s/%s/physical-device' % (backend_xid, vm_xid, devid))
            dev_params = xs.read(xs_trans, '/local/domain/%d/backend/vbd/%s/%s/params' % (backend_xid, vm_xid, devid))
            if phys_device and phys_device.find(':'):
                (tmp_major, tmp_minor) = phys_device.split(":")
                tmp_major = int(tmp_major, 16)
                tmp_minor = int(tmp_minor, 16)
            else:
                # perhaps not ready yet - check params
                if not dev_params:
                    # Skip not-phy devices
                    continue
                elif not dev_params.startswith('/dev/'):
                    # will compare params directly
                    pass
                else:
                    (tmp_major, tmp_minor) = block_name_to_majorminor(dev_params.lstrip('/dev/'))

            if (device_majorminor and (tmp_major, tmp_minor) == device_majorminor) or \
               (device_majorminor is None and dev_params == device):
                   #TODO
                vm_name = xl_ctx.domid_to_name(int(vm_xid))
                frontend = block_devid_to_name(int(devid))
                xs.transaction_end(xs_trans)
                return {"xid":int(vm_xid), "frontend": frontend, "devid": int(devid), "vm": vm_name}
    xs.transaction_end(xs_trans)
    return None

def block_attach(vm, backend_vm, device, frontend=None, mode="w", auto_detach=False, wait=True):
    device_attach_check(vm, backend_vm, device, frontend)
    do_block_attach(vm, backend_vm, device, frontend, mode, auto_detach, wait)

def device_attach_check(vm, backend_vm, device, frontend):
    """ Checks all the parameters, dies on errors """
    if not vm.is_running():
        raise QubesException("VM %s not running" % vm.name)

    if not backend_vm.is_running():
        raise QubesException("VM %s not running" % backend_vm.name)

def do_block_attach(vm, backend_vm, device, frontend, mode, auto_detach, wait):
    if frontend is None:
        frontend = block_find_unused_frontend(vm)
        if frontend is None:
            raise QubesException("No unused frontend found")
    else:
        # Check if any device attached at this frontend
        if xs.read('', '/local/domain/%d/device/vbd/%d/state' % (vm.xid, block_name_to_devid(frontend))) == '4':
            raise QubesException("Frontend %s busy in VM %s, detach it first" % (frontend, vm.name))

    # Check if this device is attached to some domain
    attached_vm = block_check_attached(backend_vm, device)
    if attached_vm:
        if auto_detach:
            block_detach(None, attached_vm['devid'], vm_xid=attached_vm['xid'])
        else:
            raise QubesException("Device %s from %s already connected to VM %s as %s" % (device, backend_vm.name, attached_vm['vm'], attached_vm['frontend']))

    if device.startswith('/'):
        backend_dev = 'script:file:' + device
    else:
        backend_dev = 'phy:/dev/' + device

    xl_cmd = [ '/usr/sbin/xl', 'block-attach', vm.name, backend_dev, frontend, mode, str(backend_vm.xid) ]
    subprocess.check_call(xl_cmd)
    if wait:
        be_path = '/local/domain/%d/backend/vbd/%d/%d' % (backend_vm.xid, vm.xid, block_name_to_devid(frontend))
        # There is no way to use xenstore watch with a timeout, so must check in a loop
        interval = 0.100
        # 5sec timeout
        timeout = 5/interval
        while timeout > 0:
            be_state = xs.read('', be_path + '/state')
            hotplug_state = xs.read('', be_path + '/hotplug-status')
            if be_state is None:
                raise QubesException("Backend device disappeared, something weird happened")
            elif int(be_state) == 4:
                # Ok
                return
            elif int(be_state) > 4:
                # Error
                error = xs.read('', '/local/domain/%d/error/backend/vbd/%d/%d/error' % (backend_vm.xid, vm.xid, block_name_to_devid(frontend)))
                if error is not None:
                    raise QubesException("Error while connecting block device: " + error)
                else:
                    raise QubesException("Unknown error while connecting block device")
            elif hotplug_state == 'error':
                hotplug_error = xs.read('', be_path + '/hotplug-error')
                if hotplug_error:
                    raise QubesException("Error while connecting block device: " + hotplug_error)
                else:
                    raise QubesException("Unknown hotplug error while connecting block device")
            time.sleep(interval)
            timeout -= interval
        raise QubesException("Timeout while waiting for block defice connection")

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

def block_detach_all(vm, vm_xid = None):
    """ Detach all non-system devices"""
    # Get XID if not provided already
    if vm_xid is None:
        if not vm.is_running():
            raise QubesException("VM %s not running" % vm.name)
        # FIXME: potential race
        vm_xid = vm.xid

    xs_trans = xs.transaction_start()
    devices = xs.ls(xs_trans, '/local/domain/%d/device/vbd' % vm_xid)
    if devices is None:
        return
    devices_to_detach = []
    for devid in devices:
        # check if this is system disk
        be_path = xs.read(xs_trans, '/local/domain/%d/device/vbd/%s/backend' % (vm_xid, devid))
        assert be_path is not None
        be_params = xs.read(xs_trans, be_path + '/params')
        if be_path.startswith('/local/domain/0/') and be_params is not None and be_params.startswith(system_path["qubes_base_dir"]):
            # system disk
            continue
        devices_to_detach.append(devid)
    xs.transaction_end(xs_trans)
    for devid in devices_to_detach:
        xl_cmd = [ '/usr/sbin/xl', 'block-detach', str(vm_xid), devid]
        subprocess.check_call(xl_cmd)

####### USB devices ######

usb_ver_re = re.compile(r"^(1|2)$")
usb_device_re = re.compile(r"^[0-9]+-[0-9]+(_[0-9]+)?$")
usb_port_re = re.compile(r"^$|^[0-9]+-[0-9]+(\.[0-9]+)?$")

def usb_setup(backend_vm_xid, vm_xid, devid, usb_ver):
    """
    Attach frontend to the backend.
     backend_vm_xid - id of the backend domain
     vm_xid - id of the frontend domain
     devid  - id of the pvusb controller
    """
    num_ports = 8
    trans = xs.transaction_start()

    be_path = "/local/domain/%d/backend/vusb/%d/%d" % (backend_vm_xid, vm_xid, devid)
    fe_path = "/local/domain/%d/device/vusb/%d" % (vm_xid, devid)

    be_perm = [{'dom': backend_vm_xid}, {'dom': vm_xid, 'read': True} ]
    fe_perm = [{'dom': vm_xid}, {'dom': backend_vm_xid, 'read': True} ]

    # Create directories and set permissions
    xs.write(trans, be_path, "")
    xs.set_permissions(trans, be_path, be_perm)

    xs.write(trans, fe_path, "")
    xs.set_permissions(trans, fe_path, fe_perm)

    # Write backend information into the location that frontend looks for
    xs.write(trans, "%s/backend-id" % fe_path, str(backend_vm_xid))
    xs.write(trans, "%s/backend" % fe_path, be_path)

    # Write frontend information into the location that backend looks for
    xs.write(trans, "%s/frontend-id" % be_path, str(vm_xid))
    xs.write(trans, "%s/frontend" % be_path, fe_path)

    # Write USB Spec version field.
    xs.write(trans, "%s/usb-ver" % be_path, usb_ver)

    # Write virtual root hub field.
    xs.write(trans, "%s/num-ports" % be_path, str(num_ports))
    for port in range(1, num_ports+1):
            # Set all port to disconnected state
            xs.write(trans, "%s/port/%d" % (be_path, port), "")

    # Set state to XenbusStateInitialising
    xs.write(trans, "%s/state" % fe_path, "1")
    xs.write(trans, "%s/state" % be_path, "1")
    xs.write(trans, "%s/online" % be_path, "1")

    xs.transaction_end(trans)

def usb_decode_device_from_xs(xs_encoded_device):
    """ recover actual device name (xenstore doesn't allow dot in key names, so it was translated to underscore) """
    return xs_encoded_device.replace('_', '.')

def usb_encode_device_for_xs(device):
    """ encode actual device name (xenstore doesn't allow dot in key names, so translated it into underscore) """
    return device.replace('.', '_')

def usb_list():
    """
    Returns a dictionary of USB devices (for PVUSB backends running in all VM).
    The dictionary is keyed by 'name' (see below), each element is a dictionary itself:
     vm   = name of the backend domain
     xid  = xid of the backend domain
     device = <frontend device number>-<frontend port number>
     name = <name of backend domain>:<frontend device number>-<frontend port number>
     desc = description
    """
    # FIXME: any better idea of desc_re?
    desc_re = re.compile(r"^.{1,255}$")

    devices_list = {}

    xs_trans = xs.transaction_start()
    vm_list = xs.ls(xs_trans, '/local/domain')

    for xid in vm_list:
        vm_name = xs.read(xs_trans, '/local/domain/%s/name' % xid)
        vm_devices = xs.ls(xs_trans, '/local/domain/%s/qubes-usb-devices' % xid)
        if vm_devices is None:
            continue
        # when listing devices in xenstore we get encoded names
        for xs_encoded_device in vm_devices:
            # Sanitize device id
            if not usb_device_re.match(xs_encoded_device):
                print >> sys.stderr, "Invalid device id in backend VM '%s'" % vm_name
                continue
            device = usb_decode_device_from_xs(xs_encoded_device)
            device_desc = xs.read(xs_trans, '/local/domain/%s/qubes-usb-devices/%s/desc' % (xid, xs_encoded_device))
            if not desc_re.match(device_desc):
                print >> sys.stderr, "Invalid %s device desc in VM '%s'" % (device, vm_name)
                continue
            visible_name = "%s:%s" % (vm_name, device)
            # grab version
            usb_ver = xs.read(xs_trans, '/local/domain/%s/qubes-usb-devices/%s/usb-ver' % (xid, xs_encoded_device))
            if usb_ver is None or not usb_ver_re.match(usb_ver):
                print >> sys.stderr, "Invalid %s device USB version in VM '%s'" % (device, vm_name)
                continue
            devices_list[visible_name] = {"name": visible_name, "xid":int(xid),
                "vm": vm_name, "device":device,
                "desc":device_desc,
                "usb_ver":usb_ver}

    xs.transaction_end(xs_trans)
    return devices_list

def usb_check_attached(xs_trans, backend_vm, device):
    """
    Checks if the given device in the given backend attached to any frontend.
    Parameters:
     backend_vm - xid of the backend domain
     device - device name in the backend domain
    Returns None or a dictionary:
     vm - the name of the frontend domain
     xid - xid of the frontend domain
     frontend - frontend device number FIXME
     devid - frontend port number FIXME
    """
    # sample xs content: /local/domain/0/backend/vusb/4/0/port/1 = "7-5"
    attached_dev = None
    vms = xs.ls(xs_trans, '/local/domain/%d/backend/vusb' % backend_vm)
    if vms is None:
        return None
    for vm in vms:
        if not vm.isdigit():
            print >> sys.stderr, "Invalid VM id"
            continue
        frontend_devs = xs.ls(xs_trans, '/local/domain/%d/backend/vusb/%s' % (backend_vm, vm))
        if frontend_devs is None:
            continue
        for frontend_dev in frontend_devs:
            if not frontend_dev.isdigit():
                print >> sys.stderr, "Invalid frontend in VM %s" % vm
                continue
            ports = xs.ls(xs_trans, '/local/domain/%d/backend/vusb/%s/%s/port' % (backend_vm, vm, frontend_dev))
            if ports is None:
                continue
            for port in ports:
                # FIXME: refactor, see similar loop in usb_find_unused_frontend(), use usb_list() instead?
                if not port.isdigit():
                    print >> sys.stderr, "Invalid port in VM %s frontend %s" % (vm, frontend)
                    continue
                dev = xs.read(xs_trans, '/local/domain/%d/backend/vusb/%s/%s/port/%s' % (backend_vm, vm, frontend_dev, port))
                if dev == "":
                    continue
                # Sanitize device id
                if not usb_port_re.match(dev):
                    print >> sys.stderr, "Invalid device id in backend VM %d @ %s/%s/port/%s" % \
                        (backend_vm, vm, frontend_dev, port)
                    continue
                if dev == device:
                    frontend = "%s-%s" % (frontend_dev, port)
                    #TODO
                    vm_name = xl_ctx.domid_to_name(int(vm))
                    if vm_name is None:
                        # FIXME: should we wipe references to frontends running on nonexistent VMs?
                        continue
                    attached_dev = {"xid":int(vm), "frontend": frontend, "devid": device, "vm": vm_name}
                    break
    return attached_dev

#def usb_check_frontend_busy(vm, front_dev, port):
#    devport = frontend.split("-")
#    if len(devport) != 2:
#        raise QubesException("Malformed frontend syntax, must be in device-port format")
#    # FIXME:
#    # return xs.read('', '/local/domain/%d/device/vusb/%d/state' % (vm.xid, frontend)) == '4'
#    return False

def usb_find_unused_frontend(xs_trans, backend_vm_xid, vm_xid, usb_ver):
    """
    Find an unused frontend/port to link the given backend with the given frontend.
    Creates new frontend if needed.
    Returns frontend specification in <device>-<port> format.
    """

    # This variable holds an index of last frontend scanned by the loop below.
    # If nothing found, this value will be used to derive the index of a new frontend.
    last_frontend_dev = -1

    frontend_devs = xs.ls(xs_trans, "/local/domain/%d/device/vusb" % vm_xid)
    if frontend_devs is not None:
        for frontend_dev in frontend_devs:
            if not frontend_dev.isdigit():
                print >> sys.stderr, "Invalid frontend_dev in VM %d" % vm_xid
                continue
            frontend_dev = int(frontend_dev)
            fe_path = "/local/domain/%d/device/vusb/%d" % (vm_xid, frontend_dev)
            if xs.read(xs_trans, "%s/backend-id" % fe_path) == str(backend_vm_xid):
                if xs.read(xs_trans, '/local/domain/%d/backend/vusb/%d/%d/usb-ver' % (backend_vm_xid, vm_xid, frontend_dev)) != usb_ver:
                    last_frontend_dev = frontend_dev
                    continue
                # here: found an existing frontend already connected to right backend using an appropriate USB version
                ports = xs.ls(xs_trans, '/local/domain/%d/backend/vusb/%d/%d/port' % (backend_vm_xid, vm_xid, frontend_dev))
                if ports is None:
                    print >> sys.stderr, "No ports in VM %d frontend_dev %d?" % (vm_xid, frontend_dev)
                    last_frontend_dev = frontend_dev
                    continue
                for port in ports:
                    # FIXME: refactor, see similar loop in usb_check_attached(), use usb_list() instead?
                    if not port.isdigit():
                        print >> sys.stderr, "Invalid port in VM %d frontend_dev %d" % (vm_xid, frontend_dev)
                        continue
                    port = int(port)
                    dev = xs.read(xs_trans, '/local/domain/%d/backend/vusb/%d/%s/port/%s' % (backend_vm_xid, vm_xid, frontend_dev, port))
                    # Sanitize device id
                    if not usb_port_re.match(dev):
                        print >> sys.stderr, "Invalid device id in backend VM %d @ %d/%d/port/%d" % \
                            (backend_vm_xid, vm_xid, frontend_dev, port)
                        continue
                    if dev == "":
                        return '%d-%d' % (frontend_dev, port)
            last_frontend_dev = frontend_dev

    # create a new frontend_dev and link it to the backend
    frontend_dev = last_frontend_dev + 1
    usb_setup(backend_vm_xid, vm_xid, frontend_dev, usb_ver)
    return '%d-%d' % (frontend_dev, 1)

def usb_attach(vm, backend_vm, device, frontend=None, auto_detach=False, wait=True):
    device_attach_check(vm, backend_vm, device, frontend)

    xs_trans = xs.transaction_start()

    xs_encoded_device = usb_encode_device_for_xs(device)
    usb_ver = xs.read(xs_trans, '/local/domain/%s/qubes-usb-devices/%s/usb-ver' % (backend_vm.xid, xs_encoded_device))
    if usb_ver is None or not usb_ver_re.match(usb_ver):
        xs.transaction_end(xs_trans)
        raise QubesException("Invalid %s device USB version in VM '%s'" % (device, backend_vm.name))

    if frontend is None:
        frontend = usb_find_unused_frontend(xs_trans, backend_vm.xid, vm.xid, usb_ver)
    else:
        # Check if any device attached at this frontend
        #if usb_check_frontend_busy(vm, frontend):
        #    raise QubesException("Frontend %s busy in VM %s, detach it first" % (frontend, vm.name))
        xs.transaction_end(xs_trans)
        raise NotImplementedError("Explicit USB frontend specification is not implemented yet")

    # Check if this device is attached to some domain
    attached_vm = usb_check_attached(xs_trans, backend_vm.xid, device)
    xs.transaction_end(xs_trans)

    if attached_vm:
        if auto_detach:
            usb_detach(backend_vm, attached_vm)
        else:
            raise QubesException("Device %s from %s already connected to VM %s as %s" % (device, backend_vm.name, attached_vm['vm'], attached_vm['frontend']))

    # Run helper script
    xl_cmd = [ '/usr/lib/qubes/xl-qvm-usb-attach.py', str(vm.xid), device, frontend, str(backend_vm.xid) ]
    subprocess.check_call(xl_cmd)

def usb_detach(backend_vm, attachment):
    xl_cmd = [ '/usr/lib/qubes/xl-qvm-usb-detach.py', str(attachment['xid']), attachment['devid'], attachment['frontend'], str(backend_vm.xid) ]
    subprocess.check_call(xl_cmd)

def usb_detach_all(vm):
    raise NotImplementedError("Detaching all devices from a given VM is not implemented yet")

####### QubesWatch ######

def only_in_first_list(l1, l2):
    ret=[]
    for i in l1:
        if not i in l2:
            ret.append(i)
    return ret

class QubesWatch(object):
    class WatchType(object):
        def __init__(self, fn, param):
            self.fn = fn
            self.param = param

    def __init__(self):
        self.xs = xen.lowlevel.xs.xs()
        self.watch_tokens_block = {}
        self.watch_tokens_vbd = {}
        self.watch_tokens_meminfo = {}
        self.block_callback = None
        self.meminfo_callback = None
        self.domain_callback = None
        self.xs.watch('@introduceDomain', QubesWatch.WatchType(self.domain_list_changed, None))
        self.xs.watch('@releaseDomain', QubesWatch.WatchType(self.domain_list_changed, None))

    def setup_block_watch(self, callback):
        old_block_callback = self.block_callback
        self.block_callback = callback
        if old_block_callback is not None and callback is None:
            # remove watches
            self.update_watches_block([])
        else:
            # possibly add watches
            self.domain_list_changed(None)

    def setup_meminfo_watch(self, callback):
        old_meminfo_callback = self.meminfo_callback
        self.meminfo_callback = callback
        if old_meminfo_callback is not None and callback is None:
            # remove watches
            self.update_watches_meminfo([])
        else:
            # possibly add watches
            self.domain_list_changed(None)

    def setup_domain_watch(self, callback):
        self.domain_callback = callback

    def get_block_key(self, xid):
        return '/local/domain/%s/qubes-block-devices' % xid

    def get_vbd_key(self, xid):
        return '/local/domain/%s/device/vbd' % xid

    def get_meminfo_key(self, xid):
        return '/local/domain/%s/memory/meminfo' % xid

    def update_watches(self, xid_list, watch_tokens, xs_key_func, callback):
        for i in only_in_first_list(xid_list, watch_tokens.keys()):
            #new domain has been created
            watch = QubesWatch.WatchType(callback, i)
            watch_tokens[i] = watch
            self.xs.watch(xs_key_func(i), watch)
        for i in only_in_first_list(watch_tokens.keys(), xid_list):
            #domain destroyed
            self.xs.unwatch(xs_key_func(i), watch_tokens[i])
            watch_tokens.pop(i)

    def update_watches_block(self, xid_list):
        self.update_watches(xid_list, self.watch_tokens_block,
                            self.get_block_key, self.block_callback)
        self.update_watches(xid_list, self.watch_tokens_vbd,
                            self.get_vbd_key, self.block_callback)

    def update_watches_meminfo(self, xid_list):
        self.update_watches(xid_list, self.watch_tokens_meminfo,
                            self.get_meminfo_key, self.meminfo_callback)

    def domain_list_changed(self, param):
        curr = self.xs.ls('', '/local/domain')
        if curr == None:
            return
        if self.domain_callback:
            self.domain_callback()
        if self.block_callback:
            self.update_watches_block(curr)
        if self.meminfo_callback:
            self.update_watches_meminfo(curr)

    def watch_single(self):
        result = self.xs.read_watch()
        token = result[1]
        token.fn(token.param)

    def watch_loop(self):
        while True:
            self.watch_single()

##### updates check #####

UPDATES_DOM0_DISABLE_FLAG='/var/lib/qubes/updates/disable-updates'

def updates_vms_toggle(qvm_collection, value):
    for vm in qvm_collection.values():
        if vm.qid == 0:
            continue
        if value:
            vm.services.pop('qubes-update-check', None)
            if vm.is_running():
                try:
                    vm.run("systemctl start qubes-update-check.timer",
                           user="root")
                except:
                    pass
        else:
            vm.services['qubes-update-check'] = False
            if vm.is_running():
                try:
                    vm.run("systemctl stop qubes-update-check.timer",
                           user="root")
                except:
                    pass
def updates_dom0_toggle(qvm_collection, value):
    if value:
        if os.path.exists(UPDATES_DOM0_DISABLE_FLAG):
            os.unlink(UPDATES_DOM0_DISABLE_FLAG)
    else:
        open(UPDATES_DOM0_DISABLE_FLAG, "w").close()

def updates_dom0_status(qvm_collection):
    return not os.path.exists(UPDATES_DOM0_DISABLE_FLAG)


# vim:sw=4:et:
