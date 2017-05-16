#!/usr/bin/python2
# -*- coding: utf-8 -*-
#
# The Qubes OS Project, http://www.qubes-os.org
#
# Copyright (C) 2010  Joanna Rutkowska <joanna@invisiblethingslab.com>
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

import atexit
import grp
import logging
import os
import os.path
import sys
import tempfile
import time
import warnings
import xml.parsers.expat

import lxml.etree

if os.name == 'posix':
    import fcntl
elif os.name == 'nt':
    import win32con
    import win32file
    import pywintypes
else:
    raise RuntimeError, "Qubes works only on POSIX or WinNT systems"

# Do not use XenAPI or create/read any VM files
# This is for testing only!
dry_run = False
#dry_run = True

if not dry_run:
    import libvirt
    try:
        import xen.lowlevel.xs
    except ImportError:
        pass


qubes_base_dir   = "/var/lib/qubes"
system_path = {
    'qubes_guid_path': '/usr/bin/qubes-guid',
    'qrexec_daemon_path': '/usr/lib/qubes/qrexec-daemon',
    'qrexec_client_path': '/usr/lib/qubes/qrexec-client',
    'qubesdb_daemon_path': '/usr/sbin/qubesdb-daemon',

    'qubes_base_dir': qubes_base_dir,

    # Relative to qubes_base_dir
    'qubes_appvms_dir': 'appvms',
    'qubes_templates_dir': 'vm-templates',
    'qubes_servicevms_dir': 'servicevms',
    'qubes_store_filename': 'qubes.xml',
    'qubes_kernels_base_dir': 'vm-kernels',

    # qubes_icon_dir is obsolete
    # use QIcon.fromTheme() where applicable
    'qubes_icon_dir': '/usr/share/icons/hicolor/128x128/devices',

    'qrexec_policy_dir': '/etc/qubes-rpc/policy',

    'config_template_pv': '/usr/share/qubes/vm-template.xml',

    'qubes_pciback_cmd': '/usr/lib/qubes/unbind-pci-device.sh',
    'prepare_volatile_img_cmd': '/usr/lib/qubes/prepare-volatile-img.sh',
}

vm_files = {
    'root_img': 'root.img',
    'rootcow_img': 'root-cow.img',
    'volatile_img': 'volatile.img',
    'private_img': 'private.img',
    'kernels_subdir': 'kernels',
    'firewall_conf': 'firewall.xml',
    'whitelisted_appmenus': 'whitelisted-appmenus.list',
    'updates_stat_file': 'updates.stat',
}

defaults = {
    'libvirt_uri': 'xen:///',
    'memory': 400,
    'kernelopts': "nopat",
    'kernelopts_pcidevs': "nopat iommu=soft swiotlb=8192",

    'dom0_update_check_interval': 6*3600,

    'private_img_size': 2*1024*1024*1024,
    'root_img_size': 10*1024*1024*1024,

    'storage_class': None,

    # how long (in sec) to wait for VMs to shutdown,
    # before killing them (when used qvm-run with --wait option),
    'shutdown_counter_max': 60,

    'vm_default_netmask': "255.255.255.0",

    # Set later
    'appvm_label': None,
    'template_label': None,
    'servicevm_label': None,
}

qubes_max_qid = 254
qubes_max_netid = 254

class QubesException (Exception):
    pass

class QubesVMMConnection(object):
    def __init__(self):
        self._libvirt_conn = None
        self._xs = None
        self._xc = None
        self._offline_mode = False

    @property
    def offline_mode(self):
        return self._offline_mode

    @offline_mode.setter
    def offline_mode(self, value):
        if not value and self._libvirt_conn is not None:
            raise QubesException("Cannot change offline mode while already connected")

        self._offline_mode = value

    def _libvirt_error_handler(self, ctx, error):
        pass

    def init_vmm_connection(self):
        if self._libvirt_conn is not None:
            # Already initialized
            return
        if self._offline_mode:
            # Do not initialize in offline mode
            return

        if 'xen.lowlevel.xs' in sys.modules:
            self._xs = xen.lowlevel.xs.xs()
        self._libvirt_conn = libvirt.open(defaults['libvirt_uri'])
        if self._libvirt_conn == None:
            raise QubesException("Failed connect to libvirt driver")
        libvirt.registerErrorHandler(self._libvirt_error_handler, None)
        atexit.register(self._libvirt_conn.close)

    def _common_getter(self, name):
        if self._offline_mode:
            # Do not initialize in offline mode
            raise QubesException("VMM operations disabled in offline mode")

        if self._libvirt_conn is None:
            self.init_vmm_connection()
        return getattr(self, name)

    @property
    def libvirt_conn(self):
        return self._common_getter('_libvirt_conn')

    @property
    def xs(self):
        if 'xen.lowlevel.xs' in sys.modules:
            return self._common_getter('_xs')
        else:
            return None


##### VMM global variable definition #####

if not dry_run:
    vmm = QubesVMMConnection()

##########################################

class QubesHost(object):
    def __init__(self):
        (model, memory, cpus, mhz, nodes, socket, cores, threads) = vmm.libvirt_conn.getInfo()
        self._total_mem = long(memory)*1024
        self._no_cpus = cpus

#        print "QubesHost: total_mem  = {0}B".format (self.xen_total_mem)
#        print "QubesHost: free_mem   = {0}".format (self.get_free_xen_memory())
#        print "QubesHost: total_cpus = {0}".format (self.xen_no_cpus)

    @property
    def memory_total(self):
        return self._total_mem

    @property
    def no_cpus(self):
        return self._no_cpus

    # TODO
    def measure_cpu_usage(self, qvmc, previous=None, previous_time = None,
            wait_time=1):
        """measure cpu usage for all domains at once"""
        if previous is None:
            previous_time = time.time()
            previous = {}
            for vm in qvmc.values():
                if not vm.is_running():
                    continue
                cputime = vm.get_cputime()
                previous[vm.xid] = {}
                previous[vm.xid]['cpu_time'] = (
                        cputime / max(vm.vcpus, 1))
                previous[vm.xid]['cpu_usage'] = 0
            time.sleep(wait_time)

        current_time = time.time()
        current = {}
        for vm in qvmc.values():
            if not vm.is_running():
                continue
            cputime = vm.get_cputime()
            current[vm.xid] = {}
            current[vm.xid]['cpu_time'] = (
                    cputime / max(vm.vcpus, 1))
            if vm.xid in previous.keys():
                current[vm.xid]['cpu_usage'] = (
                    float(current[vm.xid]['cpu_time'] -
                        previous[vm.xid]['cpu_time']) /
                    long(1000**3) / (current_time-previous_time) * 100)
                if current[vm.xid]['cpu_usage'] < 0:
                    # VM has been rebooted
                    current[vm.xid]['cpu_usage'] = 0
            else:
                current[vm.xid]['cpu_usage'] = 0

        return (current_time, current)

class QubesVmLabel(object):
    def __init__(self, index, color, name, dispvm=False):
        self.index = index
        self.color = color
        self.name = name
        self.dispvm = dispvm

        self.icon = '{}-{}'.format(('dispvm' if dispvm else 'appvm'), name)

    def __repr__(self):
        return '{}({!r}, {!r}, {!r}, dispvm={!r})'.format(
            self.__class__.__name__,
            self.index,
            self.color,
            self.name,
            self.dispvm)

    # self.icon_path is obsolete
    # use QIcon.fromTheme(label.icon) where applicable
    @property
    def icon_path(self):
        return os.path.join(system_path['qubes_icon_dir'], self.icon) + ".png"

def register_qubes_vm_class(vm_class):
    QubesVmClasses[vm_class.__name__] = vm_class
    # register class as local for this module - to make it easy to import from
    # other modules
    setattr(sys.modules[__name__], vm_class.__name__, vm_class)

class QubesVmCollection(dict):
    """
    A collection of Qubes VMs indexed by Qubes id (qid)
    """

    def __init__(self, store_filename=None):
        super(QubesVmCollection, self).__init__()
        self.default_netvm_qid = None
        self.default_fw_netvm_qid = None
        self.default_template_qid = None
        self.default_kernel = None
        self.updatevm_qid = None
        self.qubes_store_filename = store_filename
        if not store_filename:
            self.qubes_store_filename = system_path["qubes_store_filename"]
        self.clockvm_qid = None
        self.qubes_store_file = None

        self.log = logging.getLogger('qubes.qvmc.{:x}'.format(id(self)))
        self.log.debug('instantiated store_filename={!r}'.format(
            self.qubes_store_filename))

    def __repr__(self):
        return '<{} {!r}>'.format(self.__class__.__name__, list(sorted(self.keys())))

    def clear(self):
        self.log.debug('clear()')
        # Hack for releasing FDs, which otherwise would be leaked because of
        # circular dependencies on QubesVMs objects (so garbage collector
        # doesn't handle them). See #1380 for details
        for vm in self.values():
            try:
                if vm._qdb_connection:
                    vm._qdb_connection.close()
                    vm._qdb_connection = None
            except AttributeError:
                pass
        super(QubesVmCollection, self).clear()

    def values(self):
        for qid in self.keys():
            yield self[qid]

    def items(self):
        for qid in self.keys():
            yield (qid, self[qid])

    def __iter__(self):
        for qid in sorted(super(QubesVmCollection, self).keys()):
            yield qid

    keys = __iter__

    def __setitem__(self, key, value):
        self.log.debug('[{!r}] = {!r}'.format(key, value))
        if key not in self:
            return super(QubesVmCollection, self).__setitem__(key, value)
        else:
            assert False, "Attempt to add VM with qid that already exists in the collection!"

    def add_new_vm(self, vm_type, **kwargs):
        self.log.debug('add_new_vm(vm_type={}, **kwargs={!r})'.format(
            vm_type, kwargs))
        if vm_type not in QubesVmClasses.keys():
            raise ValueError("Unknown VM type: %s" % vm_type)

        qid = self.get_new_unused_qid()
        vm_cls = QubesVmClasses[vm_type]
        if 'template' in kwargs:
            if not vm_cls.is_template_compatible(kwargs['template']):
                raise QubesException("Template not compatible with selected "
                                     "VM type")

        vm = vm_cls(qid=qid, collection=self, **kwargs)
        if not self.verify_new_vm(vm):
            raise QubesException("Wrong VM description!")
        self[vm.qid] = vm

        # make first created NetVM the default one
        if self.default_fw_netvm_qid is None and vm.is_netvm():
            self.set_default_fw_netvm(vm)

        if self.default_netvm_qid is None and vm.is_proxyvm():
            self.set_default_netvm(vm)

        # make first created TemplateVM the default one
        if self.default_template_qid is None and vm.is_template():
            self.set_default_template(vm)

        # make first created ProxyVM the UpdateVM
        if self.updatevm_qid is None and vm.is_proxyvm():
            self.set_updatevm_vm(vm)

        # by default ClockVM is the first NetVM
        if self.clockvm_qid is None and vm.is_netvm():
            self.set_clockvm_vm(vm)

        return vm

    def add_new_appvm(self, name, template,
                      dir_path = None, conf_file = None,
                      private_img = None,
                      label = None):

        warnings.warn("Call to deprecated function, use add_new_vm instead",
                DeprecationWarning, stacklevel=2)
        return self.add_new_vm("QubesAppVm", name=name, template=template,
                         dir_path=dir_path, conf_file=conf_file,
                         private_img=private_img,
                         netvm = self.get_default_netvm(),
                         kernel = self.get_default_kernel(),
                         uses_default_kernel = True,
                         label=label)

    def add_new_hvm(self, name, label = None):

        warnings.warn("Call to deprecated function, use add_new_vm instead",
                DeprecationWarning, stacklevel=2)
        return self.add_new_vm("QubesHVm", name=name, label=label)

    def add_new_disposablevm(self, name, template, dispid,
                      label = None, netvm = None):

        warnings.warn("Call to deprecated function, use add_new_vm instead",
                DeprecationWarning, stacklevel=2)
        return self.add_new_vm("QubesDisposableVm", name=name, template=template,
                         netvm = netvm,
                         label=label, dispid=dispid)

    def add_new_templatevm(self, name,
                           dir_path = None, conf_file = None,
                           root_img = None, private_img = None,
                           installed_by_rpm = True):

        warnings.warn("Call to deprecated function, use add_new_vm instead",
                DeprecationWarning, stacklevel=2)
        return self.add_new_vm("QubesTemplateVm", name=name,
                              dir_path=dir_path, conf_file=conf_file,
                              root_img=root_img, private_img=private_img,
                              installed_by_rpm=installed_by_rpm,
                              netvm = self.get_default_netvm(),
                              kernel = self.get_default_kernel(),
                              uses_default_kernel = True)

    def add_new_netvm(self, name, template,
                      dir_path = None, conf_file = None,
                      private_img = None, installed_by_rpm = False,
                      label = None):

        warnings.warn("Call to deprecated function, use add_new_vm instead",
                DeprecationWarning, stacklevel=2)
        return self.add_new_vm("QubesNetVm", name=name, template=template,
                         label=label,
                         private_img=private_img, installed_by_rpm=installed_by_rpm,
                         uses_default_kernel = True,
                         dir_path=dir_path, conf_file=conf_file)

    def add_new_proxyvm(self, name, template,
                     dir_path = None, conf_file = None,
                     private_img = None, installed_by_rpm = False,
                     label = None):

        warnings.warn("Call to deprecated function, use add_new_vm instead",
                DeprecationWarning, stacklevel=2)
        return self.add_new_vm("QubesProxyVm", name=name, template=template,
                              label=label,
                              private_img=private_img, installed_by_rpm=installed_by_rpm,
                              dir_path=dir_path, conf_file=conf_file,
                              uses_default_kernel = True,
                              netvm = self.get_default_fw_netvm())

    def set_default_template(self, vm):
        self.log.debug('set_default_template({!r})'.format(vm))
        if vm is None:
            self.default_template_qid = None
        else:
            assert vm.is_template(), "VM {0} is not a TemplateVM!".format(vm.name)
            self.default_template_qid = vm.qid

    def get_default_template(self):
        if self.default_template_qid is None:
            return None
        else:
            return self[self.default_template_qid]

    def set_default_netvm(self, vm):
        self.log.debug('set_default_netvm({!r})'.format(vm))
        if vm is None:
            self.default_netvm_qid = None
        else:
            assert vm.is_netvm(), "VM {0} does not provide network!".format(vm.name)
            self.default_netvm_qid = vm.qid

    def get_default_netvm(self):
        if self.default_netvm_qid is None:
            return None
        else:
            return self[self.default_netvm_qid]

    def set_default_kernel(self, kernel):
        self.log.debug('set_default_kernel({!r})'.format(kernel))
        assert os.path.exists(
                os.path.join(system_path["qubes_kernels_base_dir"], kernel)), \
            "Kerel {0} not installed!".format(kernel)
        self.default_kernel = kernel

    def get_default_kernel(self):
        return self.default_kernel

    def set_default_fw_netvm(self, vm):
        self.log.debug('set_default_fw_netvm({!r})'.format(vm))
        if vm is None:
            self.default_fw_netvm_qid = None
        else:
            assert vm.is_netvm(), "VM {0} does not provide network!".format(vm.name)
            self.default_fw_netvm_qid = vm.qid

    def get_default_fw_netvm(self):
        if self.default_fw_netvm_qid is None:
            return None
        else:
            return self[self.default_fw_netvm_qid]

    def set_updatevm_vm(self, vm):
        self.log.debug('set_updatevm_vm({!r})'.format(vm))
        if vm is None:
            self.updatevm_qid = None
        else:
            self.updatevm_qid = vm.qid

    def get_updatevm_vm(self):
        if self.updatevm_qid is None:
            return None
        else:
            return self[self.updatevm_qid]

    def set_clockvm_vm(self, vm):
        self.log.debug('set_clockvm({!r})'.format(vm))
        if vm is None:
            self.clockvm_qid = None
        else:
            self.clockvm_qid = vm.qid

    def get_clockvm_vm(self):
        if self.clockvm_qid is None:
            return None
        else:
            return self[self.clockvm_qid]

    def get_vm_by_name(self, name):
        for vm in self.values():
            if (vm.name == name):
                return vm
        return None

    def get_qid_by_name(self, name):
        vm = self.get_vm_by_name(name)
        return vm.qid if vm is not None else None

    def get_vms_based_on(self, template_qid):
        vms = set([vm for vm in self.values()
                   if (vm.template and vm.template.qid == template_qid)])
        return vms

    def get_vms_connected_to(self, netvm_qid):
        new_vms = [ netvm_qid ]
        dependend_vms_qid = []

        # Dependency resolving only makes sense on NetVM (or derivative)
        if not self[netvm_qid].is_netvm():
            return set([])

        while len(new_vms) > 0:
            cur_vm = new_vms.pop()
            for vm in self[cur_vm].connected_vms.values():
                if vm.qid not in dependend_vms_qid:
                    dependend_vms_qid.append(vm.qid)
                    if vm.is_netvm():
                        new_vms.append(vm.qid)

        vms = [vm for vm in self.values() if vm.qid in dependend_vms_qid]
        return vms

    def verify_new_vm(self, new_vm):

        # Verify that qid is unique
        for vm in self.values():
            if vm.qid == new_vm.qid:
                print >> sys.stderr, "ERROR: The qid={0} is already used by VM '{1}'!".\
                        format(vm.qid, vm.name)
                return False

        # Verify that name is unique
        for vm in self.values():
            if vm.name == new_vm.name:
                print >> sys.stderr, \
                    "ERROR: The name={0} is already used by other VM with qid='{1}'!".\
                        format(vm.name, vm.qid)
                return False

        return True

    def get_new_unused_qid(self):
        used_ids = set([vm.qid for vm in self.values()])
        for id in range (1, qubes_max_qid):
            if id not in used_ids:
                return id
        raise LookupError ("Cannot find unused qid!")

    def get_new_unused_netid(self):
        used_ids = set([vm.netid for vm in self.values() if vm.is_netvm()])
        for id in range (1, qubes_max_netid):
            if id not in used_ids:
                return id
        raise LookupError ("Cannot find unused netid!")


    def check_if_storage_exists(self):
        try:
            f = open (self.qubes_store_filename, 'r')
        except IOError:
            return False
        f.close()
        return True

    def create_empty_storage(self):
        self.log.debug('create_empty_storage()')
        self.qubes_store_file = open (self.qubes_store_filename, 'w')
        self.clear()
        self.save()

    def lock_db_for_reading(self):
        if self.qubes_store_file is not None:
            raise QubesException("lock already taken")
        # save() would rename the file over qubes.xml, _then_ release lock,
        # so we need to ensure that the file for which we've got the lock is
        # still the right file
        self.log.debug('lock_db_for_reading()')
        while True:
            self.qubes_store_file = open (self.qubes_store_filename, 'r')
            if os.name == 'posix':
                fcntl.lockf (self.qubes_store_file, fcntl.LOCK_SH)
            elif os.name == 'nt':
                overlapped = pywintypes.OVERLAPPED()
                win32file.LockFileEx(win32file._get_osfhandle(self.qubes_store_file.fileno()),
                        0, 0, -0x10000, overlapped)
            if os.fstat(self.qubes_store_file.fileno()) == os.stat(
                    self.qubes_store_filename):
                break
            self.qubes_store_file.close()

    def lock_db_for_writing(self):
        if self.qubes_store_file is not None:
            raise QubesException("lock already taken")
        # save() would rename the file over qubes.xml, _then_ release lock,
        # so we need to ensure that the file for which we've got the lock is
        # still the right file
        self.log.debug('lock_db_for_writing()')
        while True:
            self.qubes_store_file = open (self.qubes_store_filename, 'r+')
            if os.name == 'posix':
                fcntl.lockf (self.qubes_store_file, fcntl.LOCK_EX)
            elif os.name == 'nt':
                overlapped = pywintypes.OVERLAPPED()
                win32file.LockFileEx(win32file._get_osfhandle(self.qubes_store_file.fileno()),
                        win32con.LOCKFILE_EXCLUSIVE_LOCK, 0, -0x10000, overlapped)
            if os.fstat(self.qubes_store_file.fileno()) == os.stat(
                    self.qubes_store_filename):
                break
            self.qubes_store_file.close()

    def unlock_db(self):
        if self.qubes_store_file is None:
            return
        # intentionally do not call explicit unlock to not unlock the file
        # before all buffers are flushed
        self.log.debug('unlock_db()')
        self.qubes_store_file.close()
        self.qubes_store_file = None

    def save(self):
        self.log.debug('save()')
        root = lxml.etree.Element(
            "QubesVmCollection",

            default_template=str(self.default_template_qid) \
            if self.default_template_qid is not None else "None",

            default_netvm=str(self.default_netvm_qid) \
            if self.default_netvm_qid is not None else "None",

            default_fw_netvm=str(self.default_fw_netvm_qid) \
            if self.default_fw_netvm_qid is not None else "None",

            updatevm=str(self.updatevm_qid) \
            if self.updatevm_qid is not None else "None",

            clockvm=str(self.clockvm_qid) \
            if self.clockvm_qid is not None else "None",

            default_kernel=str(self.default_kernel) \
            if self.default_kernel is not None else "None",
        )

        for vm in self.values():
            element = vm.create_xml_element()
            if element is not None:
                root.append(element)
        tree = lxml.etree.ElementTree(root)

        try:

            new_store_file = tempfile.NamedTemporaryFile(prefix=self.qubes_store_filename, delete=False)
            if os.name == 'posix':
                fcntl.lockf (new_store_file, fcntl.LOCK_EX)
            elif os.name == 'nt':
                overlapped = pywintypes.OVERLAPPED()
                win32file.LockFileEx(win32file._get_osfhandle(new_store_file.fileno()),
                        win32con.LOCKFILE_EXCLUSIVE_LOCK, 0, -0x10000, overlapped)
            tree.write(new_store_file, encoding="UTF-8", pretty_print=True)
            new_store_file.flush()
            os.chmod(new_store_file.name, 0660)
            os.chown(new_store_file.name, -1, grp.getgrnam('qubes').gr_gid)
            os.rename(new_store_file.name, self.qubes_store_filename)
            self.qubes_store_file.close()
            self.qubes_store_file = new_store_file
        except EnvironmentError as err:
            print("{0}: export error: {1}".format(
                os.path.basename(sys.argv[0]), err))
            return False
        return True

    def set_netvm_dependency(self, element):
        kwargs = {}
        attr_list = ("qid", "netvm_qid")

        for attribute in attr_list:
            kwargs[attribute] = element.get(attribute)

        vm = self[int(kwargs["qid"])]

        if vm.uses_default_netvm is True:
            if vm.is_proxyvm():
                netvm = self.get_default_fw_netvm()
            else:
                netvm = self.get_default_netvm()
            kwargs.pop("netvm_qid")
        else:
            if kwargs["netvm_qid"] == "none" or kwargs["netvm_qid"] is None:
                netvm = None
                kwargs.pop("netvm_qid")
            else:
                netvm_qid = int(kwargs.pop("netvm_qid"))
                if netvm_qid not in self:
                    netvm = None
                else:
                    netvm = self[netvm_qid]

        # directly set internal attr to not call setters...
        vm._netvm = netvm
        if netvm:
            netvm.connected_vms[vm.qid] = vm


    def load_globals(self, element):
        default_template = element.get("default_template")
        self.default_template_qid = int(default_template) \
                if default_template.lower() != "none" else None

        default_netvm = element.get("default_netvm")
        if default_netvm is not None:
            self.default_netvm_qid = int(default_netvm) \
                    if default_netvm != "None" else None
            #assert self.default_netvm_qid is not None

        default_fw_netvm = element.get("default_fw_netvm")
        if default_fw_netvm is not None:
            self.default_fw_netvm_qid = int(default_fw_netvm) \
                    if default_fw_netvm != "None" else None
            #assert self.default_netvm_qid is not None

        updatevm = element.get("updatevm")
        if updatevm is not None:
            self.updatevm_qid = int(updatevm) \
                    if updatevm != "None" else None
            #assert self.default_netvm_qid is not None

        clockvm = element.get("clockvm")
        if clockvm is not None:
            self.clockvm_qid = int(clockvm) \
                    if clockvm != "None" else None

        self.default_kernel = element.get("default_kernel")


    def _check_global(self, attr, default):
        qid = getattr(self, attr)
        if qid is None:
            return
        try:
            self[qid]
        except KeyError:
            setattr(self, attr, default)


    def check_globals(self):
        '''Ensure that all referenced qids are present in the collection'''
        self._check_global('default_template_qid', None)
        self._check_global('default_fw_netvm_qid', None)
        self._check_global('default_netvm_qid', self.default_fw_netvm_qid)
        self._check_global('updatevm_qid', self.default_netvm_qid)
        self._check_global('clockvm_qid', self.default_netvm_qid)


    def load(self):
        self.log.debug('load()')
        self.clear()

        try:
            self.qubes_store_file.seek(0)
            tree = lxml.etree.parse(self.qubes_store_file)
        except (EnvironmentError,
                xml.parsers.expat.ExpatError) as err:
            raise QubesException("error loading qubes.xml: {}".format(err))

        self.load_globals(tree.getroot())

        for (vm_class_name, vm_class) in sorted(QubesVmClasses.items(),
                key=lambda _x: _x[1].load_order):
            vms_of_class = tree.findall(vm_class_name)
            # first non-template based, then template based
            sorted_vms_of_class = sorted(vms_of_class, key= \
                    lambda x: str(x.get('template_qid')).lower() != "none")
            for element in sorted_vms_of_class:
                try:
                    vm = vm_class(xml_element=element, collection=self)
                    self[vm.qid] = vm
                except (ValueError, LookupError) as err:
                    raise QubesException(
                        "error loading VM from qubes.xml({}): {}".format(
                            vm_class_name, err))

        # After importing all VMs, set netvm references, in the same order
        for (vm_class_name, vm_class) in sorted(QubesVmClasses.items(),
                key=lambda _x: _x[1].load_order):
            for element in tree.findall(vm_class_name):
                try:
                    self.set_netvm_dependency(element)
                except (ValueError, LookupError) as err:
                    print("{0}: import error2 ({}): {}".format(
                        os.path.basename(sys.argv[0]), vm_class_name, err))
                    return False

        self.check_globals()

        # if there was no clockvm entry in qubes.xml, try to determine default:
        # root of default NetVM chain
        if tree.getroot().get("clockvm") is None:
            if self.default_netvm_qid is not None:
                clockvm = self[self.default_netvm_qid]
                # Find root of netvm chain
                while clockvm.netvm is not None:
                    clockvm = clockvm.netvm

                self.clockvm_qid = clockvm.qid

        # Disable ntpd in ClockVM - to not conflict with ntpdate (both are
        # using 123/udp port)
        if self.clockvm_qid is not None:
            self[self.clockvm_qid].services['ntpd'] = False

        # Add dom0 if wasn't present in qubes.xml
        if not 0 in self.keys():
            dom0vm = QubesAdminVm (collection=self)
            self[dom0vm.qid] = dom0vm

        return True

    def pop(self, qid):
        self.log.debug('pop({})'.format(qid))

        if self.default_netvm_qid == qid:
            self.default_netvm_qid = None
        if self.default_fw_netvm_qid == qid:
            self.default_fw_netvm_qid = None
        if self.clockvm_qid == qid:
            self.clockvm_qid = None
        if self.updatevm_qid == qid:
            self.updatevm_qid = None
        if self.default_template_qid == qid:
            self.default_template_qid = None

        return super(QubesVmCollection, self).pop(qid)

class QubesDaemonPidfile(object):
    def __init__(self, name):
        self.name = name
        self.path = "/var/run/qubes/" + name + ".pid"

    def create_pidfile(self):
        f = open (self.path, 'w')
        f.write(str(os.getpid()))
        f.close()

    def pidfile_exists(self):
        return os.path.exists(self.path)

    def read_pid(self):
        f = open (self.path)
        pid = f.read ().strip()
        f.close()
        return int(pid)

    def pidfile_is_stale(self):
        if not self.pidfile_exists():
            return False

        # check if the pid file is valid...
        proc_path = "/proc/" + str(self.read_pid()) + "/cmdline"
        if not os.path.exists (proc_path):
            print >> sys.stderr, \
                "Path {0} doesn't exist, assuming stale pidfile.".\
                    format(proc_path)
            return True

        return False # It's a good pidfile

    def remove_pidfile(self):
        os.remove (self.path)

    def __enter__ (self):
        # assumes the pidfile doesn't exist -- you should ensure it before opening the context
        self.create_pidfile()

    def __exit__ (self, exc_type, exc_val, exc_tb):
        self.remove_pidfile()
        return False

### Initialization code

# Globally defined lables
QubesVmLabels = {
    "red":      QubesVmLabel(1, "0xcc0000", "red"     ),
    "orange":   QubesVmLabel(2, "0xf57900", "orange"  ),
    "yellow":   QubesVmLabel(3, "0xedd400", "yellow"  ),
    "green":    QubesVmLabel(4, "0x73d216", "green"   ),
    "gray":     QubesVmLabel(5, "0x555753", "gray"    ),
    "blue":     QubesVmLabel(6, "0x3465a4", "blue"    ),
    "purple":   QubesVmLabel(7, "0x75507b", "purple"  ),
    "black":    QubesVmLabel(8, "0x000000", "black"   ),
}

QubesDispVmLabels = {
    k: QubesVmLabel(index=v.index, color=v.color, name=v.name, dispvm=True)
        for k, v in QubesVmLabels.iteritems()
}

defaults["appvm_label"] = QubesVmLabels["red"]
defaults["template_label"] = QubesVmLabels["black"]
defaults["servicevm_label"] = QubesVmLabels["red"]


QubesVmClasses = {}
modules_dir = os.path.join(os.path.dirname(__file__), 'modules')
for module_file in sorted(os.listdir(modules_dir)):
    if not module_file.endswith(".py") or module_file == "__init__.py":
        continue
    __import__('qubes.modules.%s' % module_file[:-3])

try:
    import qubes.settings
    qubes.settings.apply(system_path, vm_files, defaults)
except ImportError:
    pass

for path_key in system_path.keys():
    if not os.path.isabs(system_path[path_key]):
        system_path[path_key] = os.path.join(
            system_path['qubes_base_dir'], system_path[path_key])

# vim:sw=4:et:
