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

from __future__ import absolute_import

import string
from lxml import etree
from lxml.etree import ElementTree, SubElement, Element

from qubes.qubes import QubesException
from qubes.qubes import vmm,defaults
from qubes.qubes import system_path,vm_files
import sys
import os
import subprocess
import re
import time
import stat
import libvirt
from qubes.qdb import QubesDB,Error,DisconnectedError

import xen.lowlevel.xc
import xen.lowlevel.xs

# all frontends, prefer xvdi
# TODO: get this from libvirt driver?
AVAILABLE_FRONTENDS = ['xvd'+c for c in
                       string.lowercase[8:]+string.lowercase[:8]]

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

    xml = vm.libvirt_domain.XMLDesc()
    parsed_xml = etree.fromstring(xml)
    used = [target.get('dev', None)  for target in
            parsed_xml.xpath("//domain/devices/disk/target")]
    for dev in AVAILABLE_FRONTENDS:
        if dev not in used:
            return dev
    return None

def block_list_vm(vm, system_disks = False):
    name_re = re.compile(r"^[a-z0-9-]{1,12}$")
    device_re = re.compile(r"^[a-z0-9/-]{1,64}$")
    # FIXME: any better idea of desc_re?
    desc_re = re.compile(r"^.{1,255}$")
    mode_re = re.compile(r"^[rw]$")

    assert vm is not None

    if not vm.is_running():
        return []

    devices_list = {}

    try:
        untrusted_devices = vm.qdb.multiread('/qubes-block-devices/')
    except Error:
        vm.refresh()
        return {}

    def get_dev_item(dev, item):
        return untrusted_devices.get(
            '/qubes-block-devices/%s/%s' % (dev, item),
            None)

    untrusted_devices_names = list(set(map(lambda x: x.split("/")[2],
        untrusted_devices.keys())))
    for untrusted_dev_name in untrusted_devices_names:
        if name_re.match(untrusted_dev_name):
            dev_name = untrusted_dev_name
            untrusted_device_size = get_dev_item(dev_name, 'size')
            untrusted_device_desc = get_dev_item(dev_name, 'desc')
            untrusted_device_mode = get_dev_item(dev_name, 'mode')
            untrusted_device_device = get_dev_item(dev_name, 'device')
            if untrusted_device_desc is None or untrusted_device_mode is None\
                    or untrusted_device_size is None:
                print >>sys.stderr, "Missing field in %s device parameters" %\
                                    dev_name
                continue
            if untrusted_device_device is None:
                untrusted_device_device = '/dev/' + dev_name
            if not device_re.match(untrusted_device_device):
                print >> sys.stderr, "Invalid %s device path in VM '%s'" % (
                    dev_name, vm.name)
                continue
            device_device = untrusted_device_device
            if not untrusted_device_size.isdigit():
                print >> sys.stderr, "Invalid %s device size in VM '%s'" % (
                    dev_name, vm.name)
                continue
            device_size = int(untrusted_device_size)
            if not desc_re.match(untrusted_device_desc):
                print >> sys.stderr, "Invalid %s device desc in VM '%s'" % (
                    dev_name, vm.name)
                continue
            device_desc = untrusted_device_desc
            if not mode_re.match(untrusted_device_mode):
                print >> sys.stderr, "Invalid %s device mode in VM '%s'" % (
                    dev_name, vm.name)
                continue
            device_mode = untrusted_device_mode

            if not system_disks:
                if vm.qid == 0 and device_desc.startswith(system_path[
                    "qubes_base_dir"]):
                    continue

            visible_name = "%s:%s" % (vm.name, dev_name)
            devices_list[visible_name] = {
                "name":   visible_name,
                "vm":     vm.name,
                "device": device_device,
                "size":   device_size,
                "desc":   device_desc,
                "mode":   device_mode
            }

    return devices_list

def block_list(qvmc = None, vm = None, system_disks = False):
    if vm is not None:
        if not vm.is_running():
            return []
        else:
            vm_list = [ vm ]
    else:
        if qvmc is None:
            raise QubesException("You must pass either qvm or vm argument")
        vm_list = qvmc.values()

    devices_list = {}
    for vm in vm_list:
        devices_list.update(block_list_vm(vm, system_disks))
    return devices_list

def block_check_attached(qvmc, device):
    """

    @type qvmc: QubesVmCollection
    """
    if qvmc is None:
        # TODO: ValueError
        raise QubesException("You need to pass qvmc argument")

    for vm in qvmc.values():
        if vm.qid == 0:
            # Connecting devices to dom0 not supported
            continue
        if not vm.is_running():
            continue
        try:
            libvirt_domain = vm.libvirt_domain
            if libvirt_domain:
                xml = libvirt_domain.XMLDesc()
            else:
                xml = None
        except libvirt.libvirtError:
            if vmm.libvirt_conn.virConnGetLastError()[0] == libvirt.VIR_ERR_NO_DOMAIN:
                xml = None
            else:
                raise
        if xml:
            parsed_xml = etree.fromstring(xml)
            disks = parsed_xml.xpath("//domain/devices/disk")
            for disk in disks:
                backend_name = 'dom0'
                if disk.find('backenddomain') is not None:
                    backend_name = disk.find('backenddomain').get('name')
                source = disk.find('source')
                if disk.get('type') == 'file':
                    path = source.get('file')
                elif disk.get('type') == 'block':
                    path = source.get('dev')
                else:
                    # TODO: logger
                    print >>sys.stderr, "Unknown disk type '%s' attached to " \
                                        "VM '%s'" % (source.get('type'),
                                                     vm.name)
                    continue
                if backend_name == device['vm'] and path == device['device']:
                    return {
                        "frontend": disk.find('target').get('dev'),
                        "vm": vm}
    return None

def device_attach_check(vm, backend_vm, device, frontend, mode):
    """ Checks all the parameters, dies on errors """
    if not vm.is_running():
        raise QubesException("VM %s not running" % vm.name)

    if not backend_vm.is_running():
        raise QubesException("VM %s not running" % backend_vm.name)

    if device['mode'] == 'r' and mode == 'w':
        raise QubesException("Cannot attach read-only device in read-write "
                             "mode")

def block_attach(qvmc, vm, device, frontend=None, mode="w", auto_detach=False, wait=True):
    backend_vm = qvmc.get_vm_by_name(device['vm'])
    device_attach_check(vm, backend_vm, device, frontend, mode)
    if frontend is None:
        frontend = block_find_unused_frontend(vm)
        if frontend is None:
            raise QubesException("No unused frontend found")
    else:
        # Check if any device attached at this frontend
        xml = vm.libvirt_domain.XMLDesc()
        parsed_xml = etree.fromstring(xml)
        disks = parsed_xml.xpath("//domain/devices/disk/target[@dev='%s']" %
                                 frontend)
        if len(disks):
            raise QubesException("Frontend %s busy in VM %s, detach it first" % (frontend, vm.name))

    # Check if this device is attached to some domain
    attached_vm = block_check_attached(qvmc, device)
    if attached_vm:
        if auto_detach:
            block_detach(attached_vm['vm'], attached_vm['frontend'])
        else:
            raise QubesException("Device %s from %s already connected to VM "
                                 "%s as %s" % (device['device'],
                                               backend_vm.name, attached_vm['vm'], attached_vm['frontend']))

    disk = Element("disk")
    disk.set('type', 'block')
    disk.set('device', 'disk')
    SubElement(disk, 'driver').set('name', 'phy')
    SubElement(disk, 'source').set('dev', device['device'])
    SubElement(disk, 'target').set('dev', frontend)
    if backend_vm.qid != 0:
        SubElement(disk, 'backenddomain').set('name', device['vm'])
    vm.libvirt_domain.attachDevice(etree.tostring(disk,  encoding='utf-8'))
    try:
        # trigger watches to update device status
        # FIXME: this should be removed once libvirt will report such
        # events itself
        vm.qdb.write('/qubes-block-devices', '')
    except Error:
        pass

def block_detach(vm, frontend = "xvdi"):

    xml = vm.libvirt_domain.XMLDesc()
    parsed_xml = etree.fromstring(xml)
    attached = parsed_xml.xpath("//domain/devices/disk")
    for disk in attached:
        if frontend is not None and disk.find('target').get('dev') != frontend:
            # Not the device we are looking for
            continue
        if frontend is None:
            # ignore system disks
            if disk.find('domain') == None and \
                    disk.find('source').get('dev').startswith(system_path[
                        "qubes_base_dir"]):
                continue
        vm.libvirt_domain.detachDevice(etree.tostring(disk, encoding='utf-8'))
        try:
            # trigger watches to update device status
            # FIXME: this should be removed once libvirt will report such
            # events itself
            vm.qdb.write('/qubes-block-devices', '')
        except Error:
            pass

def block_detach_all(vm):
    """ Detach all non-system devices"""

    block_detach(vm, None)

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
    trans = vmm.xs.transaction_start()

    be_path = "/local/domain/%d/backend/vusb/%d/%d" % (backend_vm_xid, vm_xid, devid)
    fe_path = "/local/domain/%d/device/vusb/%d" % (vm_xid, devid)

    be_perm = [{'dom': backend_vm_xid}, {'dom': vm_xid, 'read': True} ]
    fe_perm = [{'dom': vm_xid}, {'dom': backend_vm_xid, 'read': True} ]

    # Create directories and set permissions
    vmm.xs.write(trans, be_path, "")
    vmm.xs.set_permissions(trans, be_path, be_perm)

    vmm.xs.write(trans, fe_path, "")
    vmm.xs.set_permissions(trans, fe_path, fe_perm)

    # Write backend information into the location that frontend looks for
    vmm.xs.write(trans, "%s/backend-id" % fe_path, str(backend_vm_xid))
    vmm.xs.write(trans, "%s/backend" % fe_path, be_path)

    # Write frontend information into the location that backend looks for
    vmm.xs.write(trans, "%s/frontend-id" % be_path, str(vm_xid))
    vmm.xs.write(trans, "%s/frontend" % be_path, fe_path)

    # Write USB Spec version field.
    vmm.xs.write(trans, "%s/usb-ver" % be_path, usb_ver)

    # Write virtual root hub field.
    vmm.xs.write(trans, "%s/num-ports" % be_path, str(num_ports))
    for port in range(1, num_ports+1):
            # Set all port to disconnected state
            vmm.xs.write(trans, "%s/port/%d" % (be_path, port), "")

    # Set state to XenbusStateInitialising
    vmm.xs.write(trans, "%s/state" % fe_path, "1")
    vmm.xs.write(trans, "%s/state" % be_path, "1")
    vmm.xs.write(trans, "%s/online" % be_path, "1")

    vmm.xs.transaction_end(trans)

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

    xs_trans = vmm.xs.transaction_start()
    vm_list = vmm.xs.ls(xs_trans, '/local/domain')

    for xid in vm_list:
        vm_name = vmm.xs.read(xs_trans, '/local/domain/%s/name' % xid)
        vm_devices = vmm.xs.ls(xs_trans, '/local/domain/%s/qubes-usb-devices' % xid)
        if vm_devices is None:
            continue
        # when listing devices in xenstore we get encoded names
        for xs_encoded_device in vm_devices:
            # Sanitize device id
            if not usb_device_re.match(xs_encoded_device):
                print >> sys.stderr, "Invalid device id in backend VM '%s'" % vm_name
                continue
            device = usb_decode_device_from_xs(xs_encoded_device)
            device_desc = vmm.xs.read(xs_trans, '/local/domain/%s/qubes-usb-devices/%s/desc' % (xid, xs_encoded_device))
            if not desc_re.match(device_desc):
                print >> sys.stderr, "Invalid %s device desc in VM '%s'" % (device, vm_name)
                continue
            visible_name = "%s:%s" % (vm_name, device)
            # grab version
            usb_ver = vmm.xs.read(xs_trans, '/local/domain/%s/qubes-usb-devices/%s/usb-ver' % (xid, xs_encoded_device))
            if usb_ver is None or not usb_ver_re.match(usb_ver):
                print >> sys.stderr, "Invalid %s device USB version in VM '%s'" % (device, vm_name)
                continue
            devices_list[visible_name] = {"name": visible_name, "xid":int(xid),
                "vm": vm_name, "device":device,
                "desc":device_desc,
                "usb_ver":usb_ver}

    vmm.xs.transaction_end(xs_trans)
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
    vms = vmm.xs.ls(xs_trans, '/local/domain/%d/backend/vusb' % backend_vm)
    if vms is None:
        return None
    for vm in vms:
        if not vm.isdigit():
            print >> sys.stderr, "Invalid VM id"
            continue
        frontend_devs = vmm.xs.ls(xs_trans, '/local/domain/%d/backend/vusb/%s' % (backend_vm, vm))
        if frontend_devs is None:
            continue
        for frontend_dev in frontend_devs:
            if not frontend_dev.isdigit():
                print >> sys.stderr, "Invalid frontend in VM %s" % vm
                continue
            ports = vmm.xs.ls(xs_trans, '/local/domain/%d/backend/vusb/%s/%s/port' % (backend_vm, vm, frontend_dev))
            if ports is None:
                continue
            for port in ports:
                # FIXME: refactor, see similar loop in usb_find_unused_frontend(), use usb_list() instead?
                if not port.isdigit():
                    print >> sys.stderr, "Invalid port in VM %s frontend %s" % (vm, frontend)
                    continue
                dev = vmm.xs.read(xs_trans, '/local/domain/%d/backend/vusb/%s/%s/port/%s' % (backend_vm, vm, frontend_dev, port))
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
#    # return vmm.xs.read('', '/local/domain/%d/device/vusb/%d/state' % (vm.xid, frontend)) == '4'
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

    frontend_devs = vmm.xs.ls(xs_trans, "/local/domain/%d/device/vusb" % vm_xid)
    if frontend_devs is not None:
        for frontend_dev in frontend_devs:
            if not frontend_dev.isdigit():
                print >> sys.stderr, "Invalid frontend_dev in VM %d" % vm_xid
                continue
            frontend_dev = int(frontend_dev)
            fe_path = "/local/domain/%d/device/vusb/%d" % (vm_xid, frontend_dev)
            if vmm.xs.read(xs_trans, "%s/backend-id" % fe_path) == str(backend_vm_xid):
                if vmm.xs.read(xs_trans, '/local/domain/%d/backend/vusb/%d/%d/usb-ver' % (backend_vm_xid, vm_xid, frontend_dev)) != usb_ver:
                    last_frontend_dev = frontend_dev
                    continue
                # here: found an existing frontend already connected to right backend using an appropriate USB version
                ports = vmm.xs.ls(xs_trans, '/local/domain/%d/backend/vusb/%d/%d/port' % (backend_vm_xid, vm_xid, frontend_dev))
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
                    dev = vmm.xs.read(xs_trans, '/local/domain/%d/backend/vusb/%d/%s/port/%s' % (backend_vm_xid, vm_xid, frontend_dev, port))
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

    xs_trans = vmm.xs.transaction_start()

    xs_encoded_device = usb_encode_device_for_xs(device)
    usb_ver = vmm.xs.read(xs_trans, '/local/domain/%s/qubes-usb-devices/%s/usb-ver' % (backend_vm.xid, xs_encoded_device))
    if usb_ver is None or not usb_ver_re.match(usb_ver):
        vmm.xs.transaction_end(xs_trans)
        raise QubesException("Invalid %s device USB version in VM '%s'" % (device, backend_vm.name))

    if frontend is None:
        frontend = usb_find_unused_frontend(xs_trans, backend_vm.xid, vm.xid, usb_ver)
    else:
        # Check if any device attached at this frontend
        #if usb_check_frontend_busy(vm, frontend):
        #    raise QubesException("Frontend %s busy in VM %s, detach it first" % (frontend, vm.name))
        vmm.xs.transaction_end(xs_trans)
        raise NotImplementedError("Explicit USB frontend specification is not implemented yet")

    # Check if this device is attached to some domain
    attached_vm = usb_check_attached(xs_trans, backend_vm.xid, device)
    vmm.xs.transaction_end(xs_trans)

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
    def __init__(self):
        self._qdb = {}
        self._qdb_events = {}
        self.block_callback = None
        self.meminfo_callback = None
        self.domain_callback = None
        libvirt.virEventRegisterDefaultImpl()
        # open new libvirt connection because above
        # virEventRegisterDefaultImpl is in practice effective only for new
        # connections
        self.libvirt_conn = libvirt.open(defaults['libvirt_uri'])
        self.libvirt_conn.domainEventRegisterAny(
            None,
            libvirt.VIR_DOMAIN_EVENT_ID_LIFECYCLE,
            self._domain_list_changed, None)
        self.libvirt_conn.domainEventRegisterAny(
            None,
            libvirt.VIR_DOMAIN_EVENT_ID_DEVICE_REMOVED,
            self._device_removed, None)
        # TODO: device attach libvirt event
        for vm in vmm.libvirt_conn.listAllDomains():
            try:
                if vm.isActive():
                    self._register_watches(vm)
            except libvirt.libvirtError as e:
                # this will happen if we loose a race with another tool,
                # which can just remove the domain
                if e.get_error_code() == libvirt.VIR_ERR_NO_DOMAIN:
                    pass
                raise
        # and for dom0
        self._register_watches(None)

    def _qdb_handler(self, watch, fd, events, domain_name):
        try:
            path = self._qdb[domain_name].read_watch()
        except DisconnectedError:
            libvirt.virEventRemoveHandle(watch)
            del(self._qdb_events[domain_name])
            self._qdb[domain_name].close()
            del(self._qdb[domain_name])
            return
        if path.startswith('/qubes-block-devices'):
            if self.block_callback is not None:
                self.block_callback(domain_name)


    def setup_block_watch(self, callback):
        self.block_callback = callback

    def setup_meminfo_watch(self, callback):
        raise NotImplementedError

    def setup_domain_watch(self, callback):
        self.domain_callback = callback

    def get_meminfo_key(self, xid):
        return '/local/domain/%s/memory/meminfo' % xid

    def _register_watches(self, libvirt_domain):
        if libvirt_domain:
            name = libvirt_domain.name()
            if name in self._qdb:
                return
            if not libvirt_domain.isActive():
                return
            # open separate connection to Qubes DB:
            # 1. to not confuse pull() with responses to real commands sent from
            # other threads (like read, write etc) with watch events
            # 2. to not think whether QubesDB is thread-safe (it isn't)
            try:
                self._qdb[name] = QubesDB(name)
            except Error as e:
                if e.args[0] != 2:
                    raise
                libvirt.virEventAddTimeout(500, self._retry_register_watches,
                                           libvirt_domain)
                return
        else:
            name = "dom0"
            self._qdb[name] = QubesDB(name)
        try:
            self._qdb[name].watch('/qubes-block-devices')
        except Error as e:
            if e.args[0] == 102: # Connection reset by peer
                # QubesDB daemon not running - most likely we've connected to
                #  stale daemon which just exited; retry later
                libvirt.virEventAddTimeout(500, self._retry_register_watches,
                                           libvirt_domain)
                return
        self._qdb_events[name] = libvirt.virEventAddHandle(
            self._qdb[name].watch_fd(),
            libvirt.VIR_EVENT_HANDLE_READABLE,
            self._qdb_handler, name)

    def _retry_register_watches(self, timer, libvirt_domain):
        libvirt.virEventRemoveTimeout(timer)
        self._register_watches(libvirt_domain)

    def _unregister_watches(self, libvirt_domain):
        name = libvirt_domain.name()
        if name in self._qdb_events:
            libvirt.virEventRemoveHandle(self._qdb_events[name])
            del(self._qdb_events[name])
        if name in self._qdb:
            self._qdb[name].close()
            del(self._qdb[name])

    def _domain_list_changed(self, conn, domain, event, reason, param):
        # use VIR_DOMAIN_EVENT_RESUMED instead of VIR_DOMAIN_EVENT_STARTED to
        #  make sure that qubesdb daemon is already running
        if event == libvirt.VIR_DOMAIN_EVENT_RESUMED:
            self._register_watches(domain)
        elif event == libvirt.VIR_DOMAIN_EVENT_STOPPED:
            self._unregister_watches(domain)
        else:
            # ignore other events for now
            return None
        if self.domain_callback:
            self.domain_callback(name=domain.name(), uuid=domain.UUID())

    def _device_removed(self, conn, domain, device, param):
        if self.block_callback is not None:
            self.block_callback(domain.name())

    def watch_loop(self):
        while True:
            libvirt.virEventRunDefaultImpl()

##### updates check #####

#
# XXX this whole section is a new global property
# TODO make event handlers
#

UPDATES_DOM0_DISABLE_FLAG='/var/lib/qubes/updates/disable-updates'
UPDATES_DEFAULT_VM_DISABLE_FLAG=\
    '/var/lib/qubes/updates/vm-default-disable-updates'

def updates_vms_toggle(qvm_collection, value):
    # Flag for new VMs
    if value:
        if os.path.exists(UPDATES_DEFAULT_VM_DISABLE_FLAG):
            os.unlink(UPDATES_DEFAULT_VM_DISABLE_FLAG)
    else:
        open(UPDATES_DEFAULT_VM_DISABLE_FLAG, "w").close()

    # Change for existing VMs
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

def updates_vms_status(qvm_collection):
    # default value:
    status = not os.path.exists(UPDATES_DEFAULT_VM_DISABLE_FLAG)
    # check if all the VMs uses the default value
    for vm in qvm_collection.values():
        if vm.qid == 0:
            continue
        if vm.services.get('qubes-update-check', True) != status:
            # "mixed"
            return None
    return status

# vim:sw=4:et:
