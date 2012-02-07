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

from qubes import QubesVm,QubesException,QubesVmCollection
from qubes import xs, xl_ctx, qubes_guid_path, qubes_clipd_path, qrexec_client_path
from qubes import qubes_store_filename, qubes_base_dir
import sys
import os
#import os.path
import subprocess
#import fcntl
import re
#import shutil
#import uuid
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

def run_in_vm(vm, command, verbose = True, autostart = False, notify_function = None, passio = False, passio_popen = False, localcmd = None, wait = False):
    assert vm is not None

    if not vm.is_running():
        if not autostart:
            raise QubesException("VM not running")

        try:
            if verbose:
                print >> sys.stderr, "Starting the VM '{0}'...".format(vm.name)
            if notify_function is not None:
                notify_function ("info", "Starting the '{0}' VM...".format(vm.name))
            xid = vm.start(verbose=verbose)

        except (IOError, OSError, QubesException) as err:
            raise QubesException("Error while starting the '{0}' VM: {1}".format(vm.name, err))
        except (MemoryError) as err:
            raise QubesException("Not enough memory to start '{0}' VM! Close one or more running VMs and try again.".format(vm.name))

    xid = vm.get_xid()
    if os.getenv("DISPLAY") is not None and not os.path.isfile("/var/run/qubes/guid_running.{0}".format(xid)):
        vm.start_guid(verbose = verbose, notify_function = notify_function)

    args = [qrexec_client_path, "-d", str(xid), command]
    if localcmd is not None:
        args += [ "-l", localcmd]
    if passio:
        os.execv(qrexec_client_path, args)
        exit(1)
    if passio_popen:
        p = subprocess.Popen (args, stdout=subprocess.PIPE)
        return p
    if not wait:
        args += ["-e"]
    return subprocess.call(args)

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
        sz = os.path.getsize (qubes_store_filename)

    abs_file_path = os.path.abspath (file_path)
    abs_base_dir = os.path.abspath (qubes_base_dir) + '/'
    abs_file_dir = os.path.dirname (abs_file_path) + '/'
    (nothing, dir, subdir) = abs_file_dir.partition (abs_base_dir)
    assert nothing == ""
    assert dir == abs_base_dir
    return [ { "path" : file_path, "size": sz, "subdir": subdir} ]

def print_stdout(text):
    print (text)

def backup_prepare(base_backup_dir, vms_list = None, exclude_list = [], print_callback = print_stdout):
    """If vms = None, include all (sensible) VMs; exclude_list is always applied"""

    if not os.path.exists (base_backup_dir):
        raise QubesException("The target directory doesn't exist!")

    files_to_backup = file_to_backup (qubes_store_filename)

    if vms_list is None:
        qvm_collection = QubesVmCollection()
        qvm_collection.lock_db_for_reading()
        qvm_collection.load()
        # FIXME: should be after backup completed
        qvm_collection.unlock_db()

        all_vms = [vm for vm in qvm_collection.values()]
        appvms_to_backup = [vm for vm in all_vms if vm.is_appvm() and not vm.internal]
        netvms_to_backup = [vm for vm in all_vms if vm.is_netvm() and not vm.qid == 0]
        template_vms_worth_backingup = [vm for vm in all_vms if (vm.is_template() and not vm.installed_by_rpm)]

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

        vm_sz = vm.get_disk_usage (vm.private_img)
        files_to_backup += file_to_backup(vm.private_img, vm_sz )

        if vm.is_appvm():
            files_to_backup += file_to_backup(vm.icon_path)
        if vm.is_updateable():
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
        if os.path.exists(vm.dir_path + '/whitelisted-appmenus.list'):
            files_to_backup += file_to_backup(vm.dir_path + '/whitelisted-appmenus.list')

        if vm.is_updateable():
            sz = vm.get_disk_usage(vm.root_img)
            files_to_backup += file_to_backup(vm.root_img, sz)
            vm_sz += sz
            sz = vm.get_disk_usage(vm.volatile_img)
            files_to_backup += file_to_backup(vm.volatile_img, sz)
            vm_sz += sz

        s = ""
        fmt="{{0:>{0}}} |".format(fields_to_display[0]["width"] + 1)
        s += fmt.format(vm.name)

        fmt="{{0:>{0}}} |".format(fields_to_display[1]["width"] + 1)
        if vm.is_netvm():
            s += fmt.format("NetVM" + (" + Sys" if vm.is_updateable() else ""))
        else:
            s += fmt.format("AppVM" + (" + Sys" if vm.is_updateable() else ""))

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

    # Dom0 user home
    local_user = grp.getgrnam('qubes').gr_mem[0]
    home_dir = pwd.getpwnam(local_user).pw_dir
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

    stat = os.statvfs(base_backup_dir)
    backup_fs_free_sz = stat.f_bsize * stat.f_bavail
    print_callback("")
    if (total_backup_sz > backup_fs_free_sz):
        raise QubesException("Not enough space avilable on the backup filesystem!")

    if (there_are_running_vms):
        raise QubesException("Please shutdown all VMs before proceeding.")

    print_callback("-> Avilable space: {0}".format(size_to_human(backup_fs_free_sz)))

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


# vim:sw=4:et:
