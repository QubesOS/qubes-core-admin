#!/usr/bin/python
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

from qubes import QubesVm,QubesException,QubesVmCollection
from qubes import QubesVmClasses
from qubes import xs, xl_ctx
from qubes import system_path,vm_files
import sys
import os
import subprocess
import re
import time
import grp,pwd
from datetime import datetime
from qmemman_client import QMemmanClient

import xen.lowlevel.xc
import xen.lowlevel.xl
import xen.lowlevel.xs

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
        disk = False
        major = 7
    elif name.startswith("md"):
        disk = False
        major = 9
    else:
        # Unknown device
        return (0, 0)

    if not dXpY_style:
        name_match = re.match(r"^([a-z]+)([a-z])([0-9]*)$", name)
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
    device_re = re.compile(r"^[a-z0-9]{1,12}$")
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
        self.block_callback = None
        self.domain_callback = None
        self.xs.watch('@introduceDomain', QubesWatch.WatchType(self.domain_list_changed, None))
        self.xs.watch('@releaseDomain', QubesWatch.WatchType(self.domain_list_changed, None))

    def setup_block_watch(self, callback):
        old_block_callback = self.block_callback
        self.block_callback = callback
        if old_block_callback is not None and callback is None:
            # remove watches
            self.update_watches_vbd([])
            self.update_watches_block([])
        else:
            # possibly add watches
            self.domain_list_changed(None)

    def setup_domain_watch(self, callback):
        self.domain_callback = callback

    def get_block_key(self, xid):
        return '/local/domain/%s/qubes-block-devices' % xid

    def get_vbd_key(self, xid):
        return '/local/domain/%s/device/vbd' % xid

    def update_watches_block(self, xid_list):
        for i in only_in_first_list(xid_list, self.watch_tokens_block.keys()):
            #new domain has been created
            watch = QubesWatch.WatchType(self.block_callback, i)
            self.watch_tokens_block[i] = watch
            self.xs.watch(self.get_block_key(i), watch)
        for i in only_in_first_list(self.watch_tokens_block.keys(), xid_list):
            #domain destroyed
            self.xs.unwatch(self.get_block_key(i), self.watch_tokens_block[i])
            self.watch_tokens_block.pop(i)

    def update_watches_vbd(self, xid_list):
        for i in only_in_first_list(xid_list, self.watch_tokens_vbd.keys()):
            #new domain has been created
            watch = QubesWatch.WatchType(self.block_callback, i)
            self.watch_tokens_vbd[i] = watch
            self.xs.watch(self.get_vbd_key(i), watch)
        for i in only_in_first_list(self.watch_tokens_vbd.keys(), xid_list):
            #domain destroyed
            self.xs.unwatch(self.get_vbd_key(i), self.watch_tokens_vbd[i])
            self.watch_tokens_vbd.pop(i)

    def domain_list_changed(self, param):
        curr = self.xs.ls('', '/local/domain')
        if curr == None:
            return
        if self.domain_callback:
            self.domain_callback()
        if self.block_callback:
            self.update_watches_block(curr)
            self.update_watches_vbd(curr)

    def watch_single(self):
        result = self.xs.read_watch()
        token = result[1]
        token.fn(token.param)

    def watch_loop(self):
        while True:
            self.watch_single()

######## Backups #########

def get_disk_usage(file_or_dir):
    if not os.path.exists(file_or_dir):
        return 0

    p = subprocess.Popen (["du", "-s", "--block-size=1", file_or_dir],
            stdout=subprocess.PIPE)
    result = p.communicate()
    m = re.match(r"^(\d+)\s.*", result[0])
    sz = int(m.group(1)) if m is not None else 0
    return sz


def file_to_backup (file_path, sz = None):
    if sz is None:
        sz = os.path.getsize (system_path["qubes_store_filename"])

    abs_file_path = os.path.abspath (file_path)
    abs_base_dir = os.path.abspath (system_path["qubes_base_dir"]) + '/'
    abs_file_dir = os.path.dirname (abs_file_path) + '/'
    (nothing, dir, subdir) = abs_file_dir.partition (abs_base_dir)
    assert nothing == ""
    assert dir == abs_base_dir
    return [ { "path" : file_path, "size": sz, "subdir": subdir} ]

def backup_prepare(base_backup_dir, vms_list = None, exclude_list = [], print_callback = print_stdout):
    """If vms = None, include all (sensible) VMs; exclude_list is always applied"""
    files_to_backup = file_to_backup (system_path["qubes_store_filename"])

    if exclude_list is None:
        exclude_list = []

    qvm_collection = QubesVmCollection()
    qvm_collection.lock_db_for_writing()
    qvm_collection.load()

    if vms_list is None:
        all_vms = [vm for vm in qvm_collection.values()]
        selected_vms = [vm for vm in all_vms if vm.include_in_backups]
        appvms_to_backup = [vm for vm in selected_vms if vm.is_appvm() and not vm.internal]
        netvms_to_backup = [vm for vm in selected_vms if vm.is_netvm() and not vm.qid == 0]
        template_vms_worth_backingup = [vm for vm in selected_vms if (vm.is_template() and not vm.installed_by_rpm)]

        vms_list = appvms_to_backup + netvms_to_backup + template_vms_worth_backingup

    vms_for_backup = vms_list
    # Apply exclude list
    if exclude_list:
        vms_for_backup = [vm for vm in vms_list if vm.name not in exclude_list]

    no_vms = len (vms_for_backup)

    there_are_running_vms = False

    fields_to_display = [
        { "name": "VM", "width": 16},
        { "name": "type","width": 12 },
        { "name": "size", "width": 12}
    ]

    # Display the header
    s = ""
    for f in fields_to_display:
        fmt="{{0:-^{0}}}-+".format(f["width"] + 1)
        s += fmt.format('-')
    print_callback(s)
    s = ""
    for f in fields_to_display:
        fmt="{{0:>{0}}} |".format(f["width"] + 1)
        s += fmt.format(f["name"])
    print_callback(s)
    s = ""
    for f in fields_to_display:
        fmt="{{0:-^{0}}}-+".format(f["width"] + 1)
        s += fmt.format('-')
    print_callback(s)

    for vm in vms_for_backup:
        if vm.is_template():
            # handle templates later
            continue

        if vm.private_img is not None:
            vm_sz = vm.get_disk_usage (vm.private_img)
            files_to_backup += file_to_backup(vm.private_img, vm_sz )

        if vm.is_appvm():
            files_to_backup += file_to_backup(vm.icon_path)
        if vm.updateable:
            if os.path.exists(vm.dir_path + "/apps.templates"):
                # template
                files_to_backup += file_to_backup(vm.dir_path + "/apps.templates")
            else:
                # standaloneVM
                files_to_backup += file_to_backup(vm.dir_path + "/apps")

            if os.path.exists(vm.dir_path + "/kernels"):
                files_to_backup += file_to_backup(vm.dir_path + "/kernels")
        if os.path.exists (vm.firewall_conf):
            files_to_backup += file_to_backup(vm.firewall_conf)
        if 'appmenus_whitelist' in vm_files and \
                os.path.exists(vm.dir_path + vm_files['appmenus_whitelist']):
            files_to_backup += file_to_backup(vm.dir_path + vm_files['appmenus_whitelist'])

        if vm.updateable:
            sz = vm.get_disk_usage(vm.root_img)
            files_to_backup += file_to_backup(vm.root_img, sz)
            vm_sz += sz

        s = ""
        fmt="{{0:>{0}}} |".format(fields_to_display[0]["width"] + 1)
        s += fmt.format(vm.name)

        fmt="{{0:>{0}}} |".format(fields_to_display[1]["width"] + 1)
        if vm.is_netvm():
            s += fmt.format("NetVM" + (" + Sys" if vm.updateable else ""))
        else:
            s += fmt.format("AppVM" + (" + Sys" if vm.updateable else ""))

        fmt="{{0:>{0}}} |".format(fields_to_display[2]["width"] + 1)
        s += fmt.format(size_to_human(vm_sz))

        if vm.is_running():
            s +=  " <-- The VM is running, please shut it down before proceeding with the backup!"
            there_are_running_vms = True

        print_callback(s)

    for vm in vms_for_backup:
        if not vm.is_template():
            # already handled
            continue
        vm_sz = vm.get_disk_utilization()
        files_to_backup += file_to_backup (vm.dir_path,  vm_sz)

        s = ""
        fmt="{{0:>{0}}} |".format(fields_to_display[0]["width"] + 1)
        s += fmt.format(vm.name)

        fmt="{{0:>{0}}} |".format(fields_to_display[1]["width"] + 1)
        s += fmt.format("Template VM")

        fmt="{{0:>{0}}} |".format(fields_to_display[2]["width"] + 1)
        s += fmt.format(size_to_human(vm_sz))

        if vm.is_running():
            s +=  " <-- The VM is running, please shut it down before proceeding with the backup!"
            there_are_running_vms = True

        print_callback(s)

    # Initialize backup flag on all VMs
    vms_for_backup_qid = [vm.qid for vm in vms_for_backup]
    for vm in qvm_collection.values():
        vm.backup_content = False

        if vm.qid in vms_for_backup_qid:
            vm.backup_content = True
            vm.backup_size = vm.get_disk_utilization()
            vm.backup_path = vm.dir_path.split(os.path.normpath(system_path["qubes_base_dir"])+"/")[1]

    qvm_collection.save()
    # FIXME: should be after backup completed
    qvm_collection.unlock_db()

    # Dom0 user home
    if not 'dom0' in exclude_list:
        local_user = grp.getgrnam('qubes').gr_mem[0]
        home_dir = pwd.getpwnam(local_user).pw_dir
        # Home dir should have only user-owned files, so fix it now to prevent
        # permissions problems - some root-owned files can left after
        # 'sudo bash' and similar commands
        subprocess.check_call(['sudo', 'chown', '-R', local_user, home_dir])

        home_sz = get_disk_usage(home_dir)
        home_to_backup = [ { "path" : home_dir, "size": home_sz, "subdir": 'dom0-home'} ]
        files_to_backup += home_to_backup

        s = ""
        fmt="{{0:>{0}}} |".format(fields_to_display[0]["width"] + 1)
        s += fmt.format('Dom0')

        fmt="{{0:>{0}}} |".format(fields_to_display[1]["width"] + 1)
        s += fmt.format("User home")

        fmt="{{0:>{0}}} |".format(fields_to_display[2]["width"] + 1)
        s += fmt.format(size_to_human(home_sz))

        print_callback(s)

    total_backup_sz = 0
    for file in files_to_backup:
        total_backup_sz += file["size"]

    s = ""
    for f in fields_to_display:
        fmt="{{0:-^{0}}}-+".format(f["width"] + 1)
        s += fmt.format('-')
    print_callback(s)

    s = ""
    fmt="{{0:>{0}}} |".format(fields_to_display[0]["width"] + 1)
    s += fmt.format("Total size:")
    fmt="{{0:>{0}}} |".format(fields_to_display[1]["width"] + 1 + 2 + fields_to_display[2]["width"] + 1)
    s += fmt.format(size_to_human(total_backup_sz))
    print_callback(s)

    s = ""
    for f in fields_to_display:
        fmt="{{0:-^{0}}}-+".format(f["width"] + 1)
        s += fmt.format('-')
    print_callback(s)
    # TODO: check at least if backing up to local drive
    '''
    stat = os.statvfs(base_backup_dir)
    backup_fs_free_sz = stat.f_bsize * stat.f_bavail
    print_callback("")
    if (total_backup_sz > backup_fs_free_sz):
        raise QubesException("Not enough space available on the backup filesystem!")

    if (there_are_running_vms):
        raise QubesException("Please shutdown all VMs before proceeding.")

    print_callback("-> Available space: {0}".format(size_to_human(backup_fs_free_sz)))
    '''	
    return files_to_backup

def backup_do(base_backup_dir, files_to_backup, progress_callback = None):

    total_backup_sz = 0
    for file in files_to_backup:
        total_backup_sz += file["size"]

    backup_dir = base_backup_dir + "/qubes-{0}".format (time.strftime("%Y-%m-%d-%H%M%S"))
    if os.path.exists (backup_dir):
        raise QubesException("ERROR: the path {0} already exists?!".format(backup_dir))

    os.mkdir (backup_dir)

    if not os.path.exists (backup_dir):
        raise QubesException("Strange: couldn't create backup dir: {0}?!".format(backup_dir))

    bytes_backedup = 0
    for file in files_to_backup:
        # We prefer to use Linux's cp, because it nicely handles sparse files
        progress = bytes_backedup * 100 / total_backup_sz
        progress_callback(progress)
        dest_dir = backup_dir + '/' + file["subdir"]
        if file["subdir"] != "":
            retcode = subprocess.call (["mkdir", "-p", dest_dir])
            if retcode != 0:
                raise QubesException("Cannot create directory: {0}?!".format(dest_dir))

        retcode = subprocess.call (["cp", "-rp", file["path"], dest_dir])
        if retcode != 0:
            raise QubesException("Error while copying file {0} to {1}".format(file["path"], dest_dir))

        bytes_backedup += file["size"]
        progress = bytes_backedup * 100 / total_backup_sz
        progress_callback(progress)

def backup_do_copy(base_backup_dir, files_to_backup, passphrase, progress_callback = None, encrypt=False, appvm=None):
    total_backup_sz = 0
    for file in files_to_backup:
        total_backup_sz += file["size"]

    vmproc = None
    if appvm != None:
        # Prepare the backup target (Qubes service call)
        backup_target = "QUBESRPC qubes.Backup none"

        # does the vm exist?
        qvm_collection = QubesVmCollection()
        qvm_collection.lock_db_for_reading()
        qvm_collection.load()

        vm = qvm_collection.get_vm_by_name(appvm)
        if vm is None or vm.qid not in qvm_collection:
            raise QubesException("VM {0} does not exist".format(appvm))

        qvm_collection.unlock_db()

        # If APPVM, STDOUT is a PIPE
        vmproc = vm.run(command = backup_target, passio_popen = True)
        vmproc.stdin.write(base_backup_dir.replace("\r","").replace("\n","")+"\n")
        backup_stdout = vmproc.stdin

    else:
        # Prepare the backup target (local file)
        backup_target = base_backup_dir + "/qubes-{0}".format (time.strftime("%Y-%m-%d-%H%M%S"))

        # Create the target directory
        if not os.path.exists (base_backup_dir):
            raise QubesException("ERROR: the backup directory {0} does not exists".format(base_backup_dir))

        # If not APPVM, STDOUT is a local file
        backup_stdout = open(backup_target,'wb')

    global blocks_backedup
    blocks_backedup = 0
    progress = blocks_backedup * 11 / total_backup_sz
    progress_callback(progress)

    import tempfile
    feedback_file = tempfile.NamedTemporaryFile()
    backup_tmpdir = tempfile.mkdtemp(prefix="/var/tmp/backup_")

    # Tar with tapelength does not deals well with stdout (close stdout between two tapes)
    # For this reason, we will use named pipes instead
    print "Working in",backup_tmpdir

    backup_pipe = os.path.join(backup_tmpdir,"backup_pipe")
    print "Creating pipe in:",backup_pipe
    print os.mkfifo(backup_pipe)

    print "Will backup:",files_to_backup

    # Setup worker to send encrypted data chunks to the backup_target
    from multiprocessing import Queue,Process
    class Send_Worker(Process):
        def __init__(self,queue,base_dir,backup_stdout):
            super(Send_Worker, self).__init__()
            self.queue = queue
            self.base_dir = base_dir
            self.backup_stdout = backup_stdout

        def run(self):
            print "Started sending thread"

            print "Moving to temporary dir",self.base_dir
            os.chdir(self.base_dir)

            for filename in iter(self.queue.get,None):
                if filename == "FINISHED":
                    break

                print "Sending file",filename
                # This tar used for sending data out need to be as simple, as simple, as featureless as possible. It will not be verified before untaring.
                tar_final_cmd = ["tar", "-cO", "--posix", "-C", self.base_dir, filename]
                final_proc  = subprocess.Popen (tar_final_cmd, stdin=subprocess.PIPE, stdout=self.backup_stdout)
                final_proc.wait()

                # Delete the file as we don't need it anymore
                print "Removing file",filename
                os.remove(filename)

            print "Finished sending thread"

    def compute_progress(new_size, total_backup_sz):
        global blocks_backedup
        blocks_backedup += new_size
        progress = blocks_backedup / float(total_backup_sz)
        progress_callback(int(round(progress*100,2)))

    to_send    = Queue()
    send_proc = Send_Worker(to_send, backup_tmpdir, backup_stdout)
    send_proc.start()

    for filename in files_to_backup:
        print "Backing up",filename

        backup_tempfile = os.path.join(backup_tmpdir,filename["path"].split(os.path.normpath(system_path["qubes_base_dir"])+"/")[1])
        print "Using temporary location:",backup_tempfile

        # Ensure the temporary directory exists

        if not os.path.isdir(os.path.dirname(backup_tempfile)):
            os.makedirs(os.path.dirname(backup_tempfile))

        # The first tar cmd can use any complex feature as we want. Files will be verified before untaring this.
        tar_cmdline = ["tar", "-Pc", "-f", backup_pipe,'--sparse','--tape-length',str(1000000),'-C',system_path["qubes_base_dir"],
            filename["path"].split(os.path.normpath(system_path["qubes_base_dir"])+"/")[1]
            ]

        print " ".join(tar_cmdline)

        # Tips: Popen(bufsize=0)
        # Pipe: tar-sparse | encryptor [| hmac] | tar | backup_target
        # Pipe: tar-sparse [| hmac] | tar | backup_target
        tar_sparse = subprocess.Popen (tar_cmdline,stdin=subprocess.PIPE)

        # Wait for compressor (tar) process to finish or for any error of other subprocesses
        i=0
        run_error = "paused"
        running = []
        while run_error == "paused":

            pipe = open(backup_pipe,'rb')

            # Start HMAC
            hmac       = subprocess.Popen (["openssl", "dgst", "-hmac", passphrase], stdin=subprocess.PIPE, stdout=subprocess.PIPE)

            # Prepare a first chunk
            chunkfile = backup_tempfile + "." + "%03d" % i
            i += 1
            chunkfile_p = open(chunkfile,'wb')

            if encrypt:
                # Start encrypt
                # If no cipher is provided, the data is forwarded unencrypted !!!
                # Also note that the 
                encryptor  = subprocess.Popen (["openssl", "enc", "-e", "-aes-256-cbc", "-pass", "pass:"+passphrase], stdin=pipe, stdout=subprocess.PIPE)
                run_error = wait_backup_feedback(compute_progress, encryptor.stdout, encryptor, chunkfile_p, total_backup_sz, hmac=hmac, vmproc=vmproc, addproc=tar_sparse)
            else:
                run_error = wait_backup_feedback(compute_progress, pipe, None, chunkfile_p, total_backup_sz, hmac=hmac, vmproc=vmproc, addproc=tar_sparse)

            chunkfile_p.close()

            print "Wait_backup_feedback returned:",run_error

            if len(run_error) > 0:
                send_proc.terminate()
                raise QubesException("Failed to perform backup: error with "+run_error)

            # Send the chunk to the backup target
            to_send.put(chunkfile.split(os.path.normpath(backup_tmpdir)+"/")[1])

            # Close HMAC
            hmac.stdin.close()
            hmac.wait()
            print "HMAC proc return code:",hmac.poll()

            # Write HMAC data next to the chunk file
            hmac_data = hmac.stdout.read()
            print "Writing hmac to",chunkfile+".hmac"
            hmac_file = open(chunkfile+".hmac",'w')
            hmac_file.write(hmac_data)
            hmac_file.flush()
            hmac_file.close()

            # Send the HMAC to the backup target
            to_send.put(chunkfile.split(os.path.normpath(backup_tmpdir)+"/")[1]+".hmac")

            if tar_sparse.poll() == None:
                # Release the next chunk
                print "Release next chunk for process:",tar_sparse.poll()
                #tar_sparse.stdout = subprocess.PIPE
                tar_sparse.stdin.write("\n")
                run_error="paused"
            else:
                print "Finished tar sparse with error",tar_sparse.poll()

            pipe.close()

    to_send.put("FINISHED")
    send_proc.join()

    if send_proc.exitcode != 0:
        raise QubesException("Failed to send backup: error in the sending process")

    if vmproc:
        print "VMProc1 proc return code:",vmproc.poll()
        print "Sparse1 proc return code:",tar_sparse.poll()
        vmproc.stdin.close()

'''
' Wait for backup chunk to finish
' - Monitor all the processes (streamproc, hmac, vmproc, addproc) for errors
' - Copy stdout of streamproc to backup_target and hmac stdin if available
' - Compute progress based on total_backup_sz and send progress to progress_callback function
' - Returns if
' -     one of the monitored processes error out (streamproc, hmac, vmproc, addproc), along with the processe that failed
' -     all of the monitored processes except vmproc finished successfully (vmproc termination is controlled by the python script)
' -     streamproc does not delivers any data anymore (return with the error "")
'''
def wait_backup_feedback(progress_callback, in_stream, streamproc, backup_target, total_backup_sz, hmac=None, vmproc=None, addproc=None, remove_trailing_bytes=0):

    buffer_size = 4096

    run_error = None
    run_count = 1
    blocks_backedup = 0
    while run_count > 0 and run_error == None:

        buffer = in_stream.read(buffer_size)
        progress_callback(len(buffer),total_backup_sz)

        run_count = 0
        if hmac:
            retcode=hmac.poll()
            if retcode != None:
                if retcode != 0:
                    run_error = "hmac"
            else:
                run_count += 1

        if addproc:
            retcode=addproc.poll()
            #print "Tar proc status:",retcode
            if retcode != None:
                if retcode != 0:
                    run_error = "addproc"
            else:
                run_count += 1

        if vmproc:
            retcode = vmproc.poll()
            if retcode != None:
                if retcode != 0:
                    run_error = "VM"
                    print vmproc.stdout.read()
            else:
                # VM should run until the end
                pass

        if streamproc:
            retcode=streamproc.poll()
            if retcode != None:
                if retcode != 0:
                    run_error = "streamproc"
                elif retcode == 0 and len(buffer) <= 0:
                    return ""
                else:
                    #print "INFO: last packet"
                    #if remove_trailing_bytes > 0:
                    #    print buffer.encode("hex")
                    #    buffer = buffer[:-remove_trailing_bytes]
                    #    print buffer.encode("hex")

                    backup_target.write(buffer)

                    if hmac:
                        hmac.stdin.write(buffer)

                    run_count += 1
            else:
                #print "Process running:",len(buffer)
                # Process still running
                backup_target.write(buffer)

                if hmac:
                    hmac.stdin.write(buffer)

                run_count += 1

        else:
            if len(buffer) <= 0:
                return ""
            else:
                backup_target.write(buffer)

                if hmac:
                    hmac.stdin.write(buffer)


    return run_error

def restore_vm_dirs (backup_dir, backup_tmpdir, passphrase, vms_dirs, vms, vms_size, print_callback=None, error_callback=None, progress_callback=None, encrypted=False, appvm=None):

    # Setup worker to extract encrypted data chunks to the restore dirs
    from multiprocessing import Queue,Process
    class Extract_Worker(Process):
        def __init__(self,queue,base_dir,passphrase,encrypted,total_size,print_callback,error_callback,progress_callback,vmproc=None):
            super(Extract_Worker, self).__init__()
            self.queue = queue
            self.base_dir = base_dir
            self.passphrase = passphrase
            self.encrypted = encrypted
            self.total_size = total_size
            self.blocks_backedup = 0
            self.tar2_command = None

            self.print_callback = print_callback
            self.error_callback = error_callback
            self.progress_callback = progress_callback

            self.vmproc = vmproc

            self.restore_pipe = os.path.join(self.base_dir,"restore_pipe")
            print "Creating pipe in:",self.restore_pipe
            print os.mkfifo(self.restore_pipe)

        def compute_progress(self, new_size, total_size):
            self.blocks_backedup += new_size
            progress = self.blocks_backedup / float(self.total_size)
            progress = int(round(progress*100,2))
            self.progress_callback(progress)

        def run(self):
            self.print_callback("Started sending thread")

            self.print_callback("Moving to dir "+self.base_dir)
            os.chdir(self.base_dir)

            for filename in iter(self.queue.get,None):
                if filename == "FINISHED":
                    break

                self.print_callback("Extracting file "+filename+" to "+system_path["qubes_base_dir"])

                pipe = open(self.restore_pipe,'r+b')
                if self.tar2_command == None:
                    # FIXME: Make the extraction safer by avoiding to erase other vms:
                    # - extracting directly to the target directory (based on the vm name and by using the --strip=2).
                    # - ensuring that the leading slashs are ignored when extracting (can also be obtained by running with --strip ?)
                    # marmarek: use other (local) variable for command line
                    self.tar2_command = ['tar', '--tape-length','1000000', '-C', system_path["qubes_base_dir"], '-xvf', self.restore_pipe]
                    self.print_callback("Running command "+str(self.tar2_command))
                    self.tar2_command = subprocess.Popen(self.tar2_command, stdin=subprocess.PIPE, stderr=subprocess.PIPE)

                if self.encrypted:
                    # Start decrypt
                    encryptor  = subprocess.Popen (["openssl", "enc", "-d", "-aes-256-cbc", "-pass", "pass:"+passphrase], stdin=open(filename,'rb'), stdout=subprocess.PIPE)

                    # progress_callback, in_stream, streamproc, backup_target, total_backup_sz, hmac=None, vmproc=None, addproc=None, remove_trailing_bytes=0):
                    run_error = wait_backup_feedback(self.compute_progress, encryptor.stdout, encryptor, pipe, self.total_size, hmac=None, vmproc=self.vmproc, addproc=self.tar2_command)
                    #print "End wait_backup_feedback",run_error,self.tar2_command.poll(),encryptor.poll()
                else:
                    run_error = wait_backup_feedback(self.compute_progress, open(filename,"rb"), None, pipe, self.total_size, hmac=None, vmproc=self.vmproc, addproc=self.tar2_command)

                pipe.close()

                # tar2 input closed, wait for either it finishes, or prompt for the next
                # file part; in both cases we can use read() on stderr - in the former case
                # it will return "" (EOF)
                tar2_stderr=self.tar2_command.stderr.readline()
                if tar2_stderr == "":
                    # EOF, so collect process exit status
                    if self.tar2_command.wait() != 0:
                        raise QubesException("ERROR: unable to extract files for {0}.".format(filename))
                    else:
                        # Finished extracting the tar file
                        self.tar2_command = None

                else:
                    self.print_callback("Releasing next chunck")
                    self.tar2_command.stdin.write("\n")

                # Delete the file as we don't need it anymore
                self.print_callback("Removing file "+filename)
                os.remove(filename)

            self.print_callback("Finished extracting thread")

    if progress_callback == None:
        def progress_callback(data):
            pass

    to_extract    = Queue()
    extract_proc = Extract_Worker(to_extract, backup_tmpdir, passphrase, encrypted, vms_size, print_callback, error_callback, progress_callback)
    extract_proc.start()

    print_callback("Working in temporary dir:"+backup_tmpdir)
    print_callback(str(vms_size)+" bytes to restore")

    vmproc = None
    if appvm != None:
        # Prepare the backup target (Qubes service call)
        backup_target = "QUBESRPC qubes.Restore dom0"

        # does the vm exist?
        qvm_collection = QubesVmCollection()
        qvm_collection.lock_db_for_reading()
        qvm_collection.load()

        vm = qvm_collection.get_vm_by_name(appvm)
        if vm is None or vm.qid not in qvm_collection:
            raise QubesException("VM {0} does not exist".format(appvm))

        qvm_collection.unlock_db()

        # If APPVM, STDOUT is a PIPE
        vmproc = vm.run(command = backup_target, passio_popen = True)
        vmproc.stdin.write(backup_dir.replace("\r","").replace("\n","")+"\n")
        backup_stdin = vmproc.stdout
        tar1_command = ['/usr/libexec/qubes/qfile-dom0-unpacker', str(os.getuid()), backup_tmpdir, '-v']
    else:
        backup_stdin = open(backup_dir,'rb')

        tar1_command = ['tar', '-i', '-xvf', backup_dir, '-C', backup_tmpdir]

    # Remove already processed qubes.xml.000, because qfile-dom0-unpacker will
    # refuse to override files
    os.unlink(os.path.join(backup_tmpdir,'qubes.xml.000'))
    os.unlink(os.path.join(backup_tmpdir,'qubes.xml.000.hmac'))
    tar1_env = os.environ.copy()
    # TODO: add some safety margin?
    tar1_env['UPDATES_MAX_BYTES'] = str(vms_size)
    tar1_env['UPDATES_MAX_FILES'] = '0'
    print_callback("Run command"+str(tar1_command))
    command = subprocess.Popen(tar1_command,
            stdin=backup_stdin,
            stdout=vmproc.stdin if vmproc else subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=tar1_env)

    # qfile-dom0-unpacker output filelist on stderr (and have stdout connected
    # to the VM), while tar output filelist on stdout
    if appvm:
        filelist_pipe = command.stderr
    else:
        filelist_pipe = command.stdout

    while True:

        filename = filelist_pipe.readline().strip(" \t\r\n")

        print_callback("Getting new file:"+filename)

        if not filename or filename=="EOF":
            break

        hmacfile = filelist_pipe.readline().strip(" \t\r\n")
        print_callback("Getting hmac:"+hmacfile)

        if hmacfile != filename + ".hmac":
            raise QubesException("ERROR: expected hmac for {}, but got {}".format(filename, hmacfile))

        # skip qubes.xml after receiving its hmac to skip both of them
        if filename == 'qubes.xml.000':
            print_callback("Ignoring already processed qubes.xml")
            continue

        # FIXME: skip VMs not selected for restore

        print_callback("Verifying file "+filename)

        print os.path.join(backup_tmpdir,filename)
        hmac_proc = subprocess.Popen (["openssl", "dgst", "-hmac", passphrase], stdin=open(os.path.join(backup_tmpdir,filename),'rb'), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout,stderr = hmac_proc.communicate()

        if len(stderr) > 0:
            raise QubesException("ERROR: verify file {0}: {1}".format((filename,stderr)))
        else:
            print_callback("Loading hmac for file"+filename)
            hmac = load_hmac(open(os.path.join(backup_tmpdir,filename+".hmac"),'r').read())

            if len(hmac) > 0 and load_hmac(stdout) == hmac:
                print_callback("File verification OK -> Sending file "+filename+" for extraction")
                # Send the chunk to the backup target
                to_extract.put(os.path.join(backup_tmpdir,filename))

            else:
                raise QubesException("ERROR: invalid hmac for file {0}: {1}. Is the passphrase correct?".format(filename,load_hmac(stdout)))

    if command.wait() != 0:
        raise QubesException("ERROR: unable to read the qubes backup file {0} ({1}). Is it really a backup?".format(backup_dir, command.wait()))
    if vmproc:
        if vmproc.wait() != 0:
            raise QubesException("ERROR: unable to read the qubes backup {0} because of a VM error: {1}".format(backup_dir,vmproc.stderr.read()))
    print "Extraction process status:",extract_proc.exitcode

    to_extract.put("FINISHED")
    print_callback("Waiting for the extraction process to finish...")
    extract_proc.join()
    print_callback("Extraction process finished with code:"+str(extract_proc.exitcode))
    if extract_proc.exitcode != 0:
        raise QubesException("ERROR: unable to extract the qubes backup. Check extracting process errors.")

def backup_restore_set_defaults(options):
    if 'use-default-netvm' not in options:
        options['use-default-netvm'] = False
    if 'use-none-netvm' not in options:
        options['use-none-netvm'] = False
    if 'use-default-template' not in options:
        options['use-default-template'] = False
    if 'dom0-home' not in options:
        options['dom0-home'] = True
    if 'replace-template' not in options:
        options['replace-template'] = []

    return options

def load_hmac(hmac):
    hmac = hmac.strip(" \t\r\n").split("=")
    if len(hmac) > 1:
        hmac = hmac[1].strip()
    else:
        raise QubesException("ERROR: invalid hmac file content")

    return hmac

def backup_restore_header(restore_target, passphrase, encrypt=False, appvm=None):
    # Simulate dd if=backup_file count=10 | file -
    # Simulate dd if=backup_file count=10 | gpg2 -d | tar xzv -O
    # analysis  = subprocess.Popen()
    vmproc = None

    import tempfile
    feedback_file = tempfile.NamedTemporaryFile()
    backup_tmpdir = tempfile.mkdtemp(prefix="/var/tmp/restore_")

    os.chdir(backup_tmpdir)

    # Tar with tapelength does not deals well with stdout (close stdout between two tapes)
    # For this reason, we will use named pipes instead
    print "Working in",backup_tmpdir


    tar1_env = os.environ.copy()
    if appvm != None:
        # Prepare the backup target (Qubes service call)
        restore_command = "QUBESRPC qubes.Restore dom0"

        # does the vm exist?
        qvm_collection = QubesVmCollection()
        qvm_collection.lock_db_for_reading()
        qvm_collection.load()

        vm = qvm_collection.get_vm_by_name(appvm)
        if vm is None or vm.qid not in qvm_collection:
            raise QubesException("VM {0} does not exist".format(appvm))

        qvm_collection.unlock_db()

        # If APPVM, STDOUT is a PIPE
        vmproc = vm.run(command = restore_command, passio_popen = True, passio_stderr = True)
        vmproc.stdin.write(restore_target.replace("\r","").replace("\n","")+"\n")
        tar1_command = ['/usr/libexec/qubes/qfile-dom0-unpacker', str(os.getuid()), backup_tmpdir, '-v']
        # extract only qubes.xml.000 and qubes.xml.000.hmac
        tar1_env['UPDATES_MAX_FILES'] = '2'
    else:
        # Check source file
        if not os.path.exists (restore_target):
            raise QubesException("ERROR: the backup directory {0} does not exists".format(restore_target))

        # TODO: perhaps pass only first 40kB here? Tar uses seek to skip files,
        # so not a big problem, but still it might save some time
        tar1_command = ['tar', '-i', '-xvf', restore_target, '-C', backup_tmpdir, 'qubes.xml.000', 'qubes.xml.000.hmac']

    command = subprocess.Popen(tar1_command,
            stdin=vmproc.stdout if vmproc else None,
            stdout=vmproc.stdin if vmproc else subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=tar1_env)

    if vmproc and vmproc.poll() != None:
        error = vmproc.stderr.read()
        print error
        print vmproc.poll(),command.poll()
        raise QubesException("ERROR: Immediate VM error while retrieving backup headers:{0}".format(error))

    filename = "qubes.xml.000"

    command.wait()

    if not os.path.exists(os.path.join(backup_tmpdir,filename+".hmac")):
        raise QubesException("ERROR: header not extracted correctly: {0}".format(os.path.join(backup_tmpdir,filename+".hmac")))

    if vmproc and vmproc.poll() != None and vmproc.poll() != 0:
        error = vmproc.stderr.read()
        print error
        print vmproc.poll(),command.poll()
        raise QubesException("ERROR: VM error retrieving backup headers")
    elif command.returncode not in [0,-15,122]:
        error = command.stderr.read()
        print error
        print vmproc.poll(),command.poll()
        raise QubesException("ERROR: retrieving backup headers:{0}".format(error))

    if vmproc and vmproc.poll() == None:
        vmproc.terminate()
        vmproc.wait()

    print "Loading hmac for file",filename
    hmac = load_hmac(open(os.path.join(backup_tmpdir,filename+".hmac"),'r').read())

    print "Successfully retrieved headers"

    print "Verifying file",filename
    hmac_proc = subprocess.Popen (["openssl", "dgst", "-hmac", passphrase], stdin=open(os.path.join(backup_tmpdir,filename),'rb'), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout,stderr = hmac_proc.communicate()
    if len(stderr) > 0:
        raise QubesException("ERROR: verify file {0}: {1}".format((filename,stderr)))
    else:
        if len(hmac) > 0 and load_hmac(stdout) == hmac:
            print "File verification OK -> Extracting archive",filename
            if encrypt:
                print "Starting decryption process"
                encryptor  = subprocess.Popen (["openssl", "enc", "-d", "-aes-256-cbc", "-pass", "pass:"+passphrase], stdin=open(os.path.join(backup_tmpdir,filename),'rb'), stdout=subprocess.PIPE)
                tarhead_command = subprocess.Popen(['tar', '--tape-length','1000000', '-xv'],stdin=encryptor.stdout)
            else:
                print "No decryption process required"
                encryptor = None
                tarhead_command = subprocess.Popen(['tar', '--tape-length','1000000', '-xvf', os.path.join(backup_tmpdir,filename)])

            tarhead_command.wait()
            if encryptor:
                if encryptor.wait() != 0:
                    raise QubesException("ERROR: unable to decrypt file {0}".format(filename))
            if tarhead_command.wait() != 0:
                    raise QubesException("ERROR: unable to extract the qubes.xml file. Is archive encrypted?")

            return (backup_tmpdir,"qubes.xml")
        else:
            raise QubesException("ERROR: unable to verify the qubes.xml file. Is the passphrase correct?")

    return None

def backup_restore_prepare(backup_dir, qubes_xml, passphrase, options = {}, host_collection = None, encrypt=False, appvm=None):
    # Defaults
    backup_restore_set_defaults(options)

    #### Private functions begin
    def is_vm_included_in_backup (backup_dir, vm):
        if vm.qid == 0:
            # Dom0 is not included, obviously
            return False

        if vm.backup_content:
            return True
        else:
            return False

    def find_template_name(template, replaces):
        rx_replace = re.compile("(.*):(.*)")
        for r in replaces:
            m = rx_replace.match(r)
            if m.group(1) == template:
                return m.group(2)

        return template
    #### Private functions end
    print "Loading file",qubes_xml
    backup_collection = QubesVmCollection(store_filename = qubes_xml)
    backup_collection.lock_db_for_reading()
    backup_collection.load()

    if host_collection is None:
        host_collection = QubesVmCollection()
        host_collection.lock_db_for_reading()
        host_collection.load()
        host_collection.unlock_db()

    backup_vms_list = [vm for vm in backup_collection.values()]
    host_vms_list = [vm for vm in host_collection.values()]
    vms_to_restore = {}

    there_are_conflicting_vms = False
    there_are_missing_templates = False
    there_are_missing_netvms = False
    dom0_username_mismatch = False
    restore_home = False
    # ... and the actual data
    for vm in backup_vms_list:
        if is_vm_included_in_backup (backup_dir, vm):
            print vm.name,"is included in backup"

            vms_to_restore[vm.name] = {}
            vms_to_restore[vm.name]['vm'] = vm;
            if 'exclude' in options.keys():
                vms_to_restore[vm.name]['excluded'] = vm.name in options['exclude']
                vms_to_restore[vm.name]['good-to-go'] = False

            if host_collection.get_vm_by_name (vm.name) is not None:
                vms_to_restore[vm.name]['already-exists'] = True
                vms_to_restore[vm.name]['good-to-go'] = False

            if vm.template is None:
                vms_to_restore[vm.name]['template'] = None
            else:
                templatevm_name = find_template_name(vm.template.name, options['replace-template'])
                vms_to_restore[vm.name]['template'] = templatevm_name
                template_vm_on_host = host_collection.get_vm_by_name (templatevm_name)

                # No template on the host?
                if not ((template_vm_on_host is not None) and template_vm_on_host.is_template()):
                    # Maybe the (custom) template is in the backup?
                    template_vm_on_backup = backup_collection.get_vm_by_name (templatevm_name)
                    if template_vm_on_backup is None or not \
                        (is_vm_included_in_backup(backup_dir, template_vm_on_backup) and \
                         template_vm_on_backup.is_template()):
                        if options['use-default-template']:
                            vms_to_restore[vm.name]['orig-template'] = templatevm_name
                            vms_to_restore[vm.name]['template'] = host_collection.get_default_template().name
                        else:
                            vms_to_restore[vm.name]['missing-template'] = True
                            vms_to_restore[vm.name]['good-to-go'] = False

            if vm.netvm is None:
                vms_to_restore[vm.name]['netvm'] = None
            else:
                netvm_name = vm.netvm.name
                vms_to_restore[vm.name]['netvm'] = netvm_name
                # Set to None to not confuse QubesVm object from backup
                # collection with host collection (further in clone_attrs). Set
                # directly _netvm to suppress setter action, especially
                # modifying firewall
                vm._netvm = None

                netvm_on_host = host_collection.get_vm_by_name (netvm_name)

                # No netvm on the host?
                if not ((netvm_on_host is not None) and netvm_on_host.is_netvm()):

                    # Maybe the (custom) netvm is in the backup?
                    netvm_on_backup = backup_collection.get_vm_by_name (netvm_name)
                    if not ((netvm_on_backup is not None) and netvm_on_backup.is_netvm() and is_vm_included_in_backup(backup_dir, netvm_on_backup)):
                        if options['use-default-netvm']:
                            vms_to_restore[vm.name]['netvm'] = host_collection.get_default_netvm().name
                            vm.uses_default_netvm = True
                        elif options['use-none-netvm']:
                            vms_to_restore[vm.name]['netvm'] = None
                        else:
                            vms_to_restore[vm.name]['missing-netvm'] = True
                            vms_to_restore[vm.name]['good-to-go'] = False

            if 'good-to-go' not in vms_to_restore[vm.name].keys():
                vms_to_restore[vm.name]['good-to-go'] = True

    # ...and dom0 home
    # FIXME, replace this part of code to handle the new backup format using tar
    if options['dom0-home'] and os.path.exists(backup_dir + '/dom0-home'):
        vms_to_restore['dom0'] = {}
        local_user = grp.getgrnam('qubes').gr_mem[0]

        dom0_homes = os.listdir(backup_dir + '/dom0-home')
        if len(dom0_homes) > 1:
            raise QubesException("More than one dom0 homedir in backup")

        vms_to_restore['dom0']['username'] = dom0_homes[0]
        if dom0_homes[0] != local_user:
            vms_to_restore['dom0']['username-mismatch'] = True
            if not options['ignore-dom0-username-mismatch']:
                vms_to_restore['dom0']['good-to-go'] = False

        if 'good-to-go' not in vms_to_restore['dom0']:
            vms_to_restore['dom0']['good-to-go'] = True

    return vms_to_restore

def backup_restore_print_summary(restore_info, print_callback = print_stdout):
    fields = {
        "qid": {"func": "vm.qid"},

        "name": {"func": "('[' if vm.is_template() else '')\
                 + ('{' if vm.is_netvm() else '')\
                 + vm.name \
                 + (']' if vm.is_template() else '')\
                 + ('}' if vm.is_netvm() else '')"},

        "type": {"func": "'Tpl' if vm.is_template() else \
                 'HVM' if vm.type == 'HVM' else \
                 vm.type.replace('VM','')"},

        "updbl" : {"func": "'Yes' if vm.updateable else ''"},

        "template": {"func": "'n/a' if vm.is_template() or vm.template is None else\
                     vm_info['template']"},

        "netvm": {"func": "'n/a' if vm.is_netvm() and not vm.is_proxyvm() else\
                  ('*' if vm.uses_default_netvm else '') +\
                    vm_info['netvm'] if vm_info['netvm'] is not None else '-'"},

        "label" : {"func" : "vm.label.name"},
    }

    fields_to_display = ["name", "type", "template", "updbl", "netvm", "label" ]

    # First calculate the maximum width of each field we want to display
    total_width = 0;
    for f in fields_to_display:
        fields[f]["max_width"] = len(f)
        for vm_info in restore_info.values():
            if 'vm' in vm_info.keys():
                vm = vm_info['vm']
                l = len(str(eval(fields[f]["func"])))
                if l > fields[f]["max_width"]:
                    fields[f]["max_width"] = l
        total_width += fields[f]["max_width"]

    print_callback("")
    print_callback("The following VMs are included in the backup:")
    print_callback("")

    # Display the header
    s = ""
    for f in fields_to_display:
        fmt="{{0:-^{0}}}-+".format(fields[f]["max_width"] + 1)
        s += fmt.format('-')
    print_callback(s)
    s = ""
    for f in fields_to_display:
        fmt="{{0:>{0}}} |".format(fields[f]["max_width"] + 1)
        s += fmt.format(f)
    print_callback(s)
    s = ""
    for f in fields_to_display:
        fmt="{{0:-^{0}}}-+".format(fields[f]["max_width"] + 1)
        s += fmt.format('-')
    print_callback(s)

    for vm_info in restore_info.values():
        # Skip non-VM here
        if not 'vm' in vm_info:
            continue
        vm = vm_info['vm']
        s = ""
        for f in fields_to_display:
            fmt="{{0:>{0}}} |".format(fields[f]["max_width"] + 1)
            s += fmt.format(eval(fields[f]["func"]))

        if 'excluded' in vm_info and vm_info['excluded']:
            s += " <-- Excluded from restore"
        elif 'already-exists' in vm_info:
            s +=  " <-- A VM with the same name already exists on the host!"
        elif 'missing-template' in vm_info:
            s += " <-- No matching template on the host or in the backup found!"
        elif 'missing-netvm' in vm_info:
            s += " <-- No matching netvm on the host or in the backup found!"
        elif 'orig-template' in vm_info:
            s += " <-- Original template was '%s'" % (vm_info['orig-template'])

        print_callback(s)

    if 'dom0' in restore_info.keys():
        s = ""
        for f in fields_to_display:
            fmt="{{0:>{0}}} |".format(fields[f]["max_width"] + 1)
            if f == "name":
                s += fmt.format("Dom0")
            elif f == "type":
                s += fmt.format("Home")
            else:
                s += fmt.format("")
        if 'username-mismatch' in restore_info['dom0']:
            s += " <-- username in backup and dom0 mismatch"

        print_callback(s)

def backup_restore_do(backup_dir, restore_tmpdir, passphrase, restore_info, host_collection = None, print_callback = print_stdout, error_callback = print_stderr, progress_callback = None, encrypted=False, appvm=None):

    lock_obtained = False
    if host_collection is None:
        host_collection = QubesVmCollection()
        host_collection.lock_db_for_writing()
        host_collection.load()
        lock_obtained = True

    # Perform VM restoration in backup order
    vms_dirs = []
    vms_size = 0
    vms = {}
    for vm_info in restore_info.values():
        if not vm_info['good-to-go']:
            continue
        if 'vm' not in vm_info:
            continue
        vm = vm_info['vm']
        vms_size += vm.backup_size
        vms_dirs.append(vm.backup_path+"*")
        vms[vm.name] = vm

    restore_vm_dirs (backup_dir, restore_tmpdir, passphrase, vms_dirs, vms, vms_size, print_callback, error_callback, progress_callback, encrypted, appvm)


    # Add VM in right order
    for (vm_class_name, vm_class) in sorted(QubesVmClasses.items(),
            key=lambda _x: _x[1].load_order):
        for vm_info in restore_info.values():
            if not vm_info['good-to-go']:
                continue
            if 'vm' not in vm_info:
                continue
            vm = vm_info['vm']
            if not vm.__class__ == vm_class:
                continue
            print_callback("-> Restoring {type} {0}...".format(vm.name, type=vm_class_name))
            retcode = subprocess.call (["mkdir", "-p", vm.dir_path])
            if retcode != 0:
                error_callback("*** Cannot create directory: {0}?!".format(dest_dir))
                error_callback("Skipping...")
                continue


            template = None
            if vm.template is not None:
                template_name = vm_info['template']
                template = host_collection.get_vm_by_name(template_name)

            new_vm = None

            try:
                new_vm = host_collection.add_new_vm(vm_class_name, name=vm.name,
                                                   conf_file=vm.conf_file,
                                                   dir_path=vm.dir_path,
                                                   template=template,
                                                   installed_by_rpm=False)

                new_vm.verify_files()
            except Exception as err:
                error_callback("ERROR: {0}".format(err))
                error_callback("*** Skipping VM: {0}".format(vm.name))
                if new_vm:
                    host_collection.pop(new_vm.qid)
                continue

            try:
                new_vm.clone_attrs(vm)
            except Exception as err:
                error_callback("ERROR: {0}".format(err))
                error_callback("*** Some VM property will not be restored")

            try:
                new_vm.appmenus_create(verbose=True)
            except Exception as err:
                error_callback("ERROR during appmenu restore: {0}".format(err))
                error_callback("*** VM '{0}' will not have appmenus".format(vm.name))

    # Set network dependencies - only non-default netvm setting
    for vm_info in restore_info.values():
        if not vm_info['good-to-go']:
            continue
        if 'vm' not in vm_info:
            continue
        vm = vm_info['vm']
        host_vm = host_collection.get_vm_by_name(vm.name)
        if host_vm is None:
            # Failed/skipped VM
            continue

        if not vm.uses_default_netvm:
            host_vm.netvm = host_collection.get_vm_by_name (vm_info['netvm']) if vm_info['netvm'] is not None else None

    host_collection.save()
    if lock_obtained:
        host_collection.unlock_db()

    # ... and dom0 home as last step
    if 'dom0' in restore_info.keys() and restore_info['dom0']['good-to-go']:
        backup_info = restore_info['dom0']
        local_user = grp.getgrnam('qubes').gr_mem[0]
        home_dir = pwd.getpwnam(local_user).pw_dir
        backup_dom0_home_dir = backup_dir + '/dom0-home/' + backup_info['username']
        restore_home_backupdir = "home-pre-restore-{0}".format (time.strftime("%Y-%m-%d-%H%M%S"))

        print_callback("-> Restoring home of user '{0}'...".format(local_user))
        print_callback("--> Existing files/dirs backed up in '{0}' dir".format(restore_home_backupdir))
        os.mkdir(home_dir + '/' + restore_home_backupdir)
        for f in os.listdir(backup_dom0_home_dir):
            home_file = home_dir + '/' + f
            if os.path.exists(home_file):
                os.rename(home_file, home_dir + '/' + restore_home_backupdir + '/' + f)
            retcode = subprocess.call (["cp", "-nrp", backup_dom0_home_dir + '/' + f, home_file])
            if retcode != 0:
                error_callback("*** Error while copying file {0} to {1}".format(backup_dom0_home_dir + '/' + f, home_file))
        retcode = subprocess.call(['sudo', 'chown', '-R', local_user, home_dir])
        if retcode != 0:
            error_callback("*** Error while setting home directory owner")

# vim:sw=4:et:
