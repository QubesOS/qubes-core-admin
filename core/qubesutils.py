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
import errno
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

BLKSIZE = 512

# all frontends, prefer xvdi
# TODO: get this from libvirt driver?
AVAILABLE_FRONTENDS = ['xvd'+c for c in
                       string.lowercase[8:]+string.lowercase[:8]]

class USBProxyNotInstalled(QubesException):
    pass

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
                if backend_name == device['vm'] and (path == device['device']
                        or not path.startswith('/dev/') and path == device[
                        'desc']):
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
    if mode == "r":
        SubElement(disk, 'readonly')
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
usb_device_re = re.compile(r"^[0-9]+-[0-9]+(_[0-9]+)*$")
usb_port_re = re.compile(r"^$|^[0-9]+-[0-9]+(\.[0-9]+)?$")
usb_desc_re = re.compile(r"^[ -~]{1,255}$")
# should match valid VM name
usb_connected_to_re = re.compile(r"^[a-zA-Z][a-zA-Z0-9_.-]*$")

def usb_decode_device_from_qdb(qdb_encoded_device):
    """ recover actual device name (xenstore doesn't allow dot in key names, so it was translated to underscore) """
    return qdb_encoded_device.replace('_', '.')

def usb_encode_device_for_qdb(device):
    """ encode actual device name (xenstore doesn't allow dot in key names, so translated it into underscore) """
    return device.replace('.', '_')

def usb_list_vm(qvmc, vm):
    if not vm.is_running():
        return {}

    try:
        untrusted_devices = vm.qdb.multiread('/qubes-usb-devices/')
    except Error:
        vm.refresh()
        return {}

    def get_dev_item(dev, item):
        return untrusted_devices.get(
            '/qubes-usb-devices/%s/%s' % (dev, item),
            None)

    devices = {}

    untrusted_devices_names = list(set(map(lambda x: x.split("/")[2],
        untrusted_devices.keys())))
    for untrusted_dev_name in untrusted_devices_names:
        if usb_device_re.match(untrusted_dev_name):
            dev_name = untrusted_dev_name
            untrusted_device_desc = get_dev_item(dev_name, 'desc')
            if not usb_desc_re.match(untrusted_device_desc):
                print >> sys.stderr, "Invalid %s device desc in VM '%s'" % (
                    dev_name, vm.name)
                continue
            device_desc = untrusted_device_desc

            untrusted_connected_to = get_dev_item(dev_name, 'connected-to')
            if untrusted_connected_to:
                if not usb_connected_to_re.match(untrusted_connected_to):
                    print >>sys.stderr, \
                        "Invalid %s device 'connected-to' in VM '%s'" % (
                            dev_name, vm.name)
                    continue
                connected_to = qvmc.get_vm_by_name(untrusted_connected_to)
                if connected_to is None:
                    print >>sys.stderr, \
                        "Device {} appears to be connected to {}, " \
                        "but such VM doesn't exist".format(
                            dev_name, untrusted_connected_to)
            else:
                connected_to = None

            device = usb_decode_device_from_qdb(dev_name)

            full_name = vm.name + ':' + device

            devices[full_name] = {
                'vm': vm,
                'device': device,
                'qdb_path': '/qubes-usb-devices/' + dev_name,
                'name': full_name,
                'desc': device_desc,
                'connected-to': connected_to,
            }
    return devices


def usb_list(qvmc, vm=None):
    """
    Returns a dictionary of USB devices (for PVUSB backends running in all VM).
    The dictionary is keyed by 'name' (see below), each element is a dictionary itself:
     vm   = backend domain object
     device = device ID
     name = <backend-vm>:<device>
     desc = description
    """
    if vm is not None:
        if not vm.is_running():
            return {}
        else:
            vm_list = [vm]
    else:
        vm_list = qvmc.values()

    devices_list = {}
    for vm in vm_list:
        devices_list.update(usb_list_vm(qvmc, vm))
    return devices_list

def usb_check_attached(qvmc, device):
    """Reread device attachment status"""
    vm = device['vm']
    untrusted_connected_to = vm.qdb.read(
        '{}/connected-to'.format(device['qdb_path']))
    if untrusted_connected_to:
        if not usb_connected_to_re.match(untrusted_connected_to):
            raise QubesException(
                "Invalid %s device 'connected-to' in VM '%s'" % (
                    device['device'], vm.name))
        connected_to = qvmc.get_vm_by_name(untrusted_connected_to)
        if connected_to is None:
            print >>sys.stderr, \
                "Device {} appears to be connected to {}, " \
                "but such VM doesn't exist".format(
                    device['device'], untrusted_connected_to)
    else:
        connected_to = None
    return connected_to

def usb_attach(qvmc, vm, device, auto_detach=False, wait=True):
    if not vm.is_running():
        raise QubesException("VM {} not running".format(vm.name))

    if not device['vm'].is_running():
        raise QubesException("VM {} not running".format(device['vm'].name))

    connected_to = usb_check_attached(qvmc, device)
    if connected_to:
        if auto_detach:
            usb_detach(qvmc, device)
        else:
            raise QubesException("Device {} already connected, to {}".format(
                device['name'], connected_to
            ))

    # set qrexec policy to allow this device
    policy_line = '{} {} allow\n'.format(vm.name, device['vm'].name)
    policy_path = '/etc/qubes-rpc/policy/qubes.USB+{}'.format(device['device'])
    policy_exists = os.path.exists(policy_path)
    if not policy_exists:
        try:
            fd = os.open(policy_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, 'w') as f:
                f.write(policy_line)
        except OSError as e:
            if e.errno == errno.EEXIST:
                pass
            else:
                raise
    else:
        with open(policy_path, 'r+') as f:
            policy = f.readlines()
            policy.insert(0, policy_line)
            f.truncate(0)
            f.seek(0)
            f.write(''.join(policy))
    try:
        # and actual attach
        p = vm.run_service('qubes.USBAttach', passio_popen=True, user='root')
        (stdout, stderr) = p.communicate(
            '{} {}\n'.format(device['vm'].name, device['device']))
        if p.returncode == 127:
            raise USBProxyNotInstalled(
                "qubes-usb-proxy not installed in the VM")
        elif p.returncode != 0:
            # TODO: sanitize and include stdout
            sanitized_stderr = ''.join([c for c in stderr if ord(c) >= 0x20])
            raise QubesException('Device attach failed: {}'.format(
                sanitized_stderr))
    finally:
        # FIXME: there is a race condition here - some other process might
        # modify the file in the meantime. This may result in unexpected
        # denials, but will not allow too much
        if not policy_exists:
            os.unlink(policy_path)
        else:
            with open(policy_path, 'r+') as f:
                policy = f.readlines()
                policy.remove('{} {} allow\n'.format(vm.name, device['vm'].name))
                f.truncate(0)
                f.seek(0)
                f.write(''.join(policy))

def usb_detach(qvmc, vm, device):
    connected_to = usb_check_attached(qvmc, device)
    # detect race conditions; there is still race here, but much smaller
    if connected_to is None or connected_to.qid != vm.qid:
        raise QubesException(
            "Device {} not connected to VM {}".format(
                device['name'], vm.name))

    p = device['vm'].run_service('qubes.USBDetach', passio_popen=True,
        user='root')
    (stdout, stderr) = p.communicate(
        '{}\n'.format(device['device']))
    if p.returncode != 0:
        # TODO: sanitize and include stdout
        raise QubesException('Device detach failed')

def usb_detach_all(qvmc, vm):
    for dev in usb_list(qvmc).values():
        connected_to = dev['connected-to']
        if connected_to is not None and connected_to.qid == vm.qid:
            usb_detach(qvmc, connected_to, dev)

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
                else:
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
        if libvirt_domain and libvirt_domain.ID() == 0:
            # don't use libvirt object for dom0, to always have the same
            # hardcoded "dom0" name
            libvirt_domain = None
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
            if name in self._qdb:
                return
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
        if libvirt_domain and libvirt_domain.ID() == 0:
            name = "dom0"
        else:
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
