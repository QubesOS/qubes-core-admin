#!/usr/bin/python2
# -*- coding: utf-8 -*-
#
# The Qubes OS Project, http://www.qubes-os.org
#
# Copyright (C) 2010  Joanna Rutkowska <joanna@invisiblethingslab.com>
# Copyright (C) 2013  Marek Marczykowski <marmarek@invisiblethingslab.com>
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

import ast
import datetime
import base64
import hashlib
import logging
import grp
import lxml.etree
import os
import os.path
import re
import shutil
import subprocess
import sys
import time
import uuid
import xml.parsers.expat
import signal
import pwd
from qubes import qmemman
from qubes import qmemman_algo
import libvirt

from qubes.qubes import dry_run,vmm
from qubes.qubes import register_qubes_vm_class
from qubes.qubes import QubesVmCollection,QubesException,QubesHost,QubesVmLabels
from qubes.qubes import defaults,system_path,vm_files,qubes_max_qid
from qubes.storage import get_pool

qmemman_present = False
try:
    from qubes.qmemman_client import QMemmanClient
    qmemman_present = True
except ImportError:
    pass

import qubes.qubesutils

xid_to_name_cache = {}

class QubesVm(object):
    """
    A representation of one Qubes VM
    Only persistent information are stored here, while all the runtime
    information, e.g. Xen dom id, etc, are to be retrieved via Xen API
    Note that qid is not the same as Xen's domid!
    """

    # In which order load this VM type from qubes.xml
    load_order = 100

    # hooks for plugins (modules) which want to influence existing classes,
    # without introducing new ones
    hooks_clone_disk_files = []
    hooks_create_on_disk = []
    hooks_create_qubesdb_entries = []
    hooks_get_attrs_config = []
    hooks_get_clone_attrs = []
    hooks_get_config_params = []
    hooks_init = []
    hooks_label_setter = []
    hooks_netvm_setter = []
    hooks_post_rename = []
    hooks_pre_rename = []
    hooks_remove_from_disk = []
    hooks_start = []
    hooks_verify_files = []
    hooks_set_attr = []

    def get_attrs_config(self):
        """ Object attributes for serialization/deserialization
            inner dict keys:
             - order: initialization order (to keep dependency intact)
                      attrs without order will be evaluated at the end
             - default: default value used when attr not given to object constructor
             - attr: set value to this attribute instead of parameter name
             - eval: (DEPRECATED) assign result of this expression instead of
                      value directly; local variable 'value' contains
                      attribute value (or default if it was not given)
             - func: callable used to parse the value retrieved from XML
             - save: use evaluation result as value for XML serialization; only attrs with 'save' key will be saved in XML
             - save_skip: if present and evaluates to true, attr will be omitted in XML
             - save_attr: save to this XML attribute instead of parameter name
             """

        attrs = {
            # __qid cannot be accessed by setattr, so must be set manually in __init__
            "qid": { "attr": "_qid", "order": 0 },
            "name": { "order": 1 },
            "uuid": { "order": 0, "eval": 'uuid.UUID(value) if value else None' },
            "dir_path": { "default": None, "order": 2 },
            "pool_name": { "default":"default" },
            "conf_file": {
                "func": lambda value: self.absolute_path(value, self.name +
                                                                 ".conf"),
                "order": 3 },
            ### order >= 10: have base attrs set
            "firewall_conf": {
                "func": self._absolute_path_gen(vm_files["firewall_conf"]),
                "order": 10 },
            "installed_by_rpm": { "default": False, 'order': 10 },
            "template": { "default": None, "attr": '_template', 'order': 10 },
            ### order >= 20: have template set
            "uses_default_netvm": { "default": True, 'order': 20 },
            "netvm": { "default": None, "attr": "_netvm", 'order': 20 },
            "label": { "attr": "_label", "default": defaults["appvm_label"], 'order': 20,
                'xml_deserialize': lambda _x: QubesVmLabels[_x] },
            "memory": { "default": defaults["memory"], 'order': 20 },
            "maxmem": { "default": None, 'order': 25 },
            "pcidevs": {
                "default": '[]',
                "order": 25,
                "func": lambda value: list([] if value in ["none", None] else
                    ast.literal_eval(value) if value.find("[") >= 0 else
                    ast.literal_eval("[" + value + "]")) },
            "pci_strictreset": {"default": True},
            "pci_e820_host": {"default": True},
            "virt_mode": {
                "default": "default",
                "order": 26, # __virt_mode needs self.pcidevs
                "attr": '_virt_mode',
                "func": self.__virt_mode},
            # Internal VM (not shown in qubes-manager, doesn't create appmenus entries
            "internal": { "default": False, 'attr': '_internal' },
            "vcpus": { "default": 2, "func": int },
            "uses_default_kernel": { "default": True, 'order': 30 },
            "uses_default_kernelopts": { "default": True, 'order': 30 },
            "kernel": {
                "attr": "_kernel",
                "default": None,
                "order": 31,
                "func": lambda value: self._collection.get_default_kernel() if
                  self.uses_default_kernel else value },
            "kernelopts": {
                "default": "",
                "order": 31,
                "func": lambda value: value if not self.uses_default_kernelopts\
                    else defaults["kernelopts_pcidevs"] if len(self.pcidevs)>0 \
                    else self.template.kernelopts if self.template
                    else defaults["kernelopts"] },
            "mac": { "attr": "_mac", "default": None },
            "include_in_backups": {
                "func": lambda x: x if x is not None
                else not self.installed_by_rpm },
            "services": {
                "default": {},
                "func": lambda value: dict(ast.literal_eval(str(value))) },
            "debug": { "default": False },
            "default_user": { "default": "user", "attr": "_default_user" },
            "qrexec_timeout": { "default": 60 },
            "autostart": { "default": False, "attr": "_autostart" },
            "uses_default_dispvm_netvm": {"default": True, "order": 30},
            "dispvm_netvm": {"attr": "_dispvm_netvm", "default": None},
            "backup_content" : { 'default': False },
            "backup_size" : {
                "default": 0,
                "func": int },
            "backup_path" : { 'default': "" },
            "backup_timestamp": {
                "func": lambda value:
                    datetime.datetime.fromtimestamp(int(value)) if value
                    else None },
            ##### Internal attributes - will be overriden in __init__ regardless of args
            "config_file_template": {
                "func": lambda x: system_path["config_template_pv"] },
            "icon_path": {
                "func": lambda x: os.path.join(self.dir_path, "icon.png") if
                               self.dir_path is not None else None },
            # used to suppress side effects of clone_attrs
            "_do_not_reset_firewall": { "func": lambda x: False },
            "kernels_dir": {
                # for backward compatibility (or another rare case): kernel=None -> kernel in VM dir
                "func": lambda x: \
                    os.path.join(system_path["qubes_kernels_base_dir"],
                                 self.kernel) if self.kernel is not None \
                        else os.path.join(self.dir_path,
                                          vm_files["kernels_subdir"]) },
            }

        ### Mark attrs for XML inclusion
        # Simple string attrs
        for prop in ['qid', 'uuid', 'name', 'dir_path', 'memory', 'maxmem',
            'pcidevs', 'pci_strictreset', 'vcpus', 'internal',\
            'uses_default_kernel', 'kernel', 'uses_default_kernelopts',\
            'kernelopts', 'services', 'installed_by_rpm',\
            'uses_default_netvm', 'include_in_backups', 'debug',\
            'qrexec_timeout', 'autostart', 'uses_default_dispvm_netvm',
            'backup_content', 'backup_size', 'backup_path', 'pool_name',\
            'pci_e820_host', 'virt_mode']:
            attrs[prop]['save'] = lambda prop=prop: str(getattr(self, prop))
        # Simple paths
        for prop in ['conf_file', 'firewall_conf']:
            attrs[prop]['save'] = \
                lambda prop=prop: self.relative_path(getattr(self, prop))
            attrs[prop]['save_skip'] = \
                lambda prop=prop: getattr(self, prop) is None

        # Can happen only if VM created in offline mode
        attrs['maxmem']['save_skip'] = lambda: self.maxmem is None
        attrs['vcpus']['save_skip'] = lambda: self.vcpus is None

        attrs['uuid']['save_skip'] = lambda: self.uuid is None
        attrs['mac']['save'] = lambda: str(self._mac)
        attrs['mac']['save_skip'] = lambda: self._mac is None

        attrs['default_user']['save'] = lambda: str(self._default_user)

        attrs['backup_timestamp']['save'] = \
            lambda: self.backup_timestamp.strftime("%s")
        attrs['backup_timestamp']['save_skip'] = \
            lambda: self.backup_timestamp is None

        attrs['netvm']['save'] = \
            lambda: str(self.netvm.qid) if self.netvm is not None else "none"
        attrs['netvm']['save_attr'] = "netvm_qid"
        attrs['dispvm_netvm']['save'] = \
            lambda: str(self.dispvm_netvm.qid) \
                if self.dispvm_netvm is not None \
                else "none"
        attrs['template']['save'] = \
            lambda: str(self.template.qid) if self.template else "none"
        attrs['template']['save_attr'] = "template_qid"
        attrs['label']['save'] = lambda: self.label.name

        # fire hooks
        for hook in self.hooks_get_attrs_config:
            attrs = hook(self, attrs)
        return attrs

    def post_set_attr(self, attr, newvalue, oldvalue):
        for hook in self.hooks_set_attr:
            hook(self, attr, newvalue, oldvalue)

    @staticmethod
    def __basic_parse_xml_attr(value):
        if value is None:
            return None
        if value.lower() == "none":
            return None
        if value.lower() == "true":
            return True
        if value.lower() == "false":
            return False
        if value.isdigit():
            return int(value)
        return value

    def __init__(self, **kwargs):
        self._collection = None
        if 'collection' in kwargs:
            self._collection = kwargs['collection']
        else:
            raise ValueError("No collection given to QubesVM constructor")

        # Special case for template b/c it is given in "template_qid" property
        if "xml_element" in kwargs and kwargs["xml_element"].get("template_qid"):
            template_qid = kwargs["xml_element"].get("template_qid")
            if template_qid.lower() != "none":
                if int(template_qid) in self._collection:
                    kwargs["template"] = self._collection[int(template_qid)]
                else:
                    raise ValueError("Unknown template with QID %s" % template_qid)
        attrs = self.get_attrs_config()
        for attr_name in sorted(attrs, key=lambda _x: attrs[_x]['order'] if 'order' in attrs[_x] else 1000):
            attr_config = attrs[attr_name]
            attr = attr_name
            if 'attr' in attr_config:
                attr = attr_config['attr']
            value = None
            if attr_name in kwargs:
                value = kwargs[attr_name]
            elif 'xml_element' in kwargs and kwargs['xml_element'].get(attr_name) is not None:
                if 'xml_deserialize' in attr_config and callable(attr_config['xml_deserialize']):
                    value = attr_config['xml_deserialize'](kwargs['xml_element'].get(attr_name))
                else:
                    value = self.__basic_parse_xml_attr(kwargs['xml_element'].get(attr_name))
            else:
                if 'default' in attr_config:
                    value = attr_config['default']
            if 'func' in attr_config:
                setattr(self, attr, attr_config['func'](value))
            elif 'eval' in attr_config:
                setattr(self, attr, eval(attr_config['eval']))
            else:
                #print "setting %s to %s" % (attr, value)
                setattr(self, attr, value)

        #Init private attrs
        self.__qid = self._qid

        self._libvirt_domain = None
        self._qdb_connection = None

        assert self.__qid < qubes_max_qid, "VM id out of bounds!"
        assert self.name is not None

        if not self.verify_name(self.name):
            msg = ("'%s' is invalid VM name (invalid characters, over 31 chars long, "
                   "ends with '-dm', or one of 'none', 'true', 'false')") % self.name
            if 'xml_element' in kwargs:
                print >>sys.stderr, "WARNING: %s" % msg
            else:
                raise QubesException(msg)

        if self.netvm is not None:
            self.netvm.connected_vms[self.qid] = self

        # Not in generic way to not create QubesHost() to frequently
        if self.maxmem is None and not vmm.offline_mode:
            qubes_host = QubesHost()
            total_mem_mb = qubes_host.memory_total/1024
            self.maxmem = total_mem_mb/2
        
        # Linux specific cap: max memory can't scale beyond 10.79*init_mem
        if self.maxmem > self.memory * 10:
            self.maxmem = self.memory * 10

        # Always set if meminfo-writer should be active or not
        if 'meminfo-writer' not in self.services:
            self.services['meminfo-writer'] = not (len(self.pcidevs) > 0)

        # Additionally force meminfo-writer disabled when VM have PCI devices
        if len(self.pcidevs) > 0:
            self.services['meminfo-writer'] = False

        if 'xml_element' not in kwargs:
            # New VM, disable updates check if requested for new VMs
            if os.path.exists(qubes.qubesutils.UPDATES_DEFAULT_VM_DISABLE_FLAG):
                self.services['qubes-update-check'] = False

        # Initialize VM image storage class
        self.storage = get_pool(self.pool_name, self).getStorage()
        self.dir_path = self.storage.vmdir
        self.icon_path = os.path.join(self.storage.vmdir, 'icon.png')
        self.conf_file = os.path.join(self.storage.vmdir, self.name + '.conf')

        if hasattr(self, 'kernels_dir'):
            modules_path = os.path.join(self.kernels_dir,
                    "modules.img")
            if os.path.exists(modules_path):
                self.storage.modules_img = modules_path
                self.storage.modules_img_rw = self.kernel is None

        # Some additional checks for template based VM
        if self.template is not None:
            if not self.template.is_template():
                print >> sys.stderr, "ERROR: template_qid={0} doesn't point to a valid TemplateVM".\
                    format(self.template.qid)
                return
            self.template.appvms[self.qid] = self
        else:
            assert self.root_img is not None, "Missing root_img for standalone VM!"

        self.log = logging.getLogger('qubes.vm.{}'.format(self.qid))
        self.log.debug('instantiated name={!r} class={}'.format(
            self.name, self.__class__.__name__))

        # fire hooks
        for hook in self.hooks_init:
            hook(self)

    def __repr__(self):
        return '<{} at {:#0x} qid={!r} name={!r}>'.format(
            self.__class__.__name__,
            id(self),
            self.qid,
            self.name)

    def absolute_path(self, arg, default):
        if arg is not None and os.path.isabs(arg):
            return arg
        elif self.dir_path is not None:
            return os.path.join(self.dir_path, (arg if arg is not None else default))
        else:
            # cannot provide any meaningful value without dir_path; this is
            # only to import some older format of `qubes.xml` (for example
            # during migration from older release)
            return None

    def _absolute_path_gen(self, default):
        return lambda value: self.absolute_path(value, default)

    def relative_path(self, arg):
        return arg.replace(self.dir_path + '/', '')

    @property
    def qid(self):
        return self.__qid

    @property
    def label(self):
        return self._label

    @label.setter
    def label(self, new_label):
        self._label = new_label
        if self.icon_path:
            try:
                os.remove(self.icon_path)
            except:
                pass
            if hasattr(os, "symlink"):
                os.symlink (new_label.icon_path, self.icon_path)
                # FIXME: some os-independent wrapper?
                subprocess.call(['sudo', 'xdg-icon-resource', 'forceupdate'])
            else:
                shutil.copy(new_label.icon_path, self.icon_path)

        # fire hooks
        for hook in self.hooks_label_setter:
            hook(self, new_label)

    def __virt_mode(self, value):
        if value not in ["default", "pv", "pvh", "hvm"]:
            raise QubesException("Invalid virt_mode.")

        if value == 'default':
            # We can't decide this in offline mode. So store 'default' which
            # will be switched to the proper value on next load with vmm
            # available.
            if vmm.offline_mode:
                return 'default'

            if vmm.pvh_supported and vmm.hap_supported and not self.pcidevs:
                value = 'pvh'
            else:
                value = 'pv'

        return value

    @property
    def virt_mode(self):
        return self._virt_mode

    @virt_mode.setter
    def virt_mode(self, new_value):
        self._virt_mode = self.__virt_mode(new_value)

    @property
    def netvm(self):
        return self._netvm

    # Don't know how properly call setter from base class, so workaround it...
    @netvm.setter
    def netvm(self, new_netvm):
        self._set_netvm(new_netvm)
        # fire hooks
        for hook in self.hooks_netvm_setter:
            hook(self, new_netvm)

    def _set_netvm(self, new_netvm):
        self.log.debug('netvm = {!r}'.format(new_netvm))
        if new_netvm and not new_netvm.is_netvm():
            raise ValueError("Vm {!r} does not provide network".format(
                new_netvm))
        if self.is_running() and new_netvm is not None and not new_netvm.is_running():
            raise QubesException("Cannot dynamically attach to stopped NetVM")
        if self.netvm is not None:
            self.netvm.connected_vms.pop(self.qid)
            if self.is_running():
                self.detach_network()

                if hasattr(self.netvm, 'post_vm_net_detach'):
                    self.netvm.post_vm_net_detach(self)

        if new_netvm is not None:
            new_netvm.connected_vms[self.qid]=self

        self._netvm = new_netvm

        if new_netvm is None:
            return

        if self.is_running():
            # refresh IP, DNS etc
            self.create_qubesdb_entries()
            self.attach_network()
            if hasattr(self.netvm, 'post_vm_net_attach'):
                self.netvm.post_vm_net_attach(self)

    @property
    def ip(self):
        if self.netvm is not None:
            return self.netvm.get_ip_for_vm(self.qid)
        else:
            return None

    @property
    def netmask(self):
        if self.netvm is not None:
            return self.netvm.netmask
        else:
            return None

    @property
    def gateway(self):
        # This is gateway IP for _other_ VMs, so make sense only in NetVMs
        return None

    @property
    def secondary_dns(self):
        if self.netvm is not None:
            return self.netvm.secondary_dns
        else:
            return None

    @property
    def vif(self):
        if self.xid < 0:
            return None
        if self.netvm is None:
            return None
        return "vif{0}.+".format(self.xid)

    @property
    def mac(self):
        if self._mac is not None:
            return self._mac
        else:
            return "00:16:3E:5E:6C:{qid:02X}".format(qid=self.qid)

    @mac.setter
    def mac(self, new_mac):
        self._mac = new_mac

    @property
    def kernel(self):
        return self._kernel

    @kernel.setter
    def kernel(self, new_value):
        if new_value is not None:
            if not os.path.exists(os.path.join(system_path[
                'qubes_kernels_base_dir'], new_value)):
                raise QubesException("Kernel '%s' not installed" % new_value)
            for f in ('vmlinuz', 'initramfs'):
                if not os.path.exists(os.path.join(
                        system_path['qubes_kernels_base_dir'], new_value, f)):
                    raise QubesException(
                        "Kernel '%s' not properly installed: missing %s "
                        "file" % (new_value, f))
        self._kernel = new_value
        self.uses_default_kernel = False

    @property
    def updateable(self):
        return self.template is None

    # Leaved for compatibility
    def is_updateable(self):
        return self.updateable

    @property
    def default_user(self):
        if self.template is not None:
            return self.template.default_user
        else:
            return self._default_user

    @default_user.setter
    def default_user(self, value):
        self._default_user = value

    def is_networked(self):
        if self.is_netvm():
            return True

        if self.netvm is not None:
            return True
        else:
            return False

    @classmethod
    def verify_name(cls, name):
        if not isinstance(cls.__basic_parse_xml_attr(name), str):
            return False
        if len(name) > 31:
            return False
        if name == 'lost+found':
            # avoid conflict when /var/lib/qubes/appvms is mounted on
            # separate partition
            return False
        if name.endswith('-dm'):
            # avoid conflict with device model stubdomain names for HVMs
            return False
        if name == 'default':
            # disallow keywords as VM names
            return False
        return re.match(r"^[a-zA-Z][a-zA-Z0-9_.-]*$", name) is not None

    def pre_rename(self, new_name):
        if self.autostart:
            subprocess.check_call(['sudo', 'systemctl', '-q', 'disable',
                                   'qubes-vm@{}.service'.format(self.name)])
        # fire hooks
        for hook in self.hooks_pre_rename:
            hook(self, new_name)

    def set_name(self, name):
        self.log.debug('name = {!r}'.format(name))
        if self.is_running():
            raise QubesException("Cannot change name of running VM!")

        if not self.verify_name(name):
            raise QubesException("Invalid VM name")

        if self.installed_by_rpm:
            raise QubesException("Cannot rename VM installed by RPM -- first clone VM and then use yum to remove package.")

        assert self._collection is not None
        if self._collection.get_vm_by_name(name):
            raise QubesException("VM with this name already exists")

        self.pre_rename(name)
        try:
            self.libvirt_domain.undefine()
        except libvirt.libvirtError as e:
            if e.get_error_code() == libvirt.VIR_ERR_NO_DOMAIN:
                pass
            else:
                raise
        if self._qdb_connection:
            self._qdb_connection.close()
            self._qdb_connection = None

        new_conf = os.path.join(self.dir_path, name + '.conf')
        if os.path.exists(self.conf_file):
            os.rename(self.conf_file, new_conf)
        old_dirpath = self.dir_path
        self.storage.rename(self.name, name)
        new_dirpath = self.storage.vmdir
        self.dir_path = new_dirpath
        old_name = self.name
        self.name = name
        if self.conf_file is not None:
            self.conf_file = new_conf.replace(old_dirpath, new_dirpath)
        if self.icon_path is not None:
            self.icon_path = self.icon_path.replace(old_dirpath, new_dirpath)
        if hasattr(self, 'kernels_dir') and self.kernels_dir is not None:
            self.kernels_dir = self.kernels_dir.replace(old_dirpath, new_dirpath)
        if self.firewall_conf is not None:
            self.firewall_conf = self.firewall_conf.replace(old_dirpath,
                                                            new_dirpath)

        self._update_libvirt_domain()
        self.post_rename(old_name)

    def post_rename(self, old_name):
        if self.autostart:
            # force setter to be called again
            self.autostart = self.autostart
        # fire hooks
        for hook in self.hooks_post_rename:
            hook(self, old_name)

    @property
    def internal(self):
        return self._internal

    @internal.setter
    def internal(self, value):
        oldvalue = self._internal
        self._internal = value
        self.post_set_attr('internal', value, oldvalue)

    @property
    def dispvm_netvm(self):
        if self.uses_default_dispvm_netvm:
            return self.netvm
        else:
            if isinstance(self._dispvm_netvm, int):
                if  self._dispvm_netvm in self._collection:
                    return self._collection[self._dispvm_netvm]
                else:
                    return None
            else:
                return self._dispvm_netvm

    @dispvm_netvm.setter
    def dispvm_netvm(self, value):
        if value and not value.is_netvm():
            raise ValueError("Vm {!r} does not provide network".format(
                value))
        self._dispvm_netvm = value

    @property
    def autostart(self):
        return self._autostart

    @autostart.setter
    def autostart(self, value):
        if value:
            retcode = subprocess.call(["sudo", "ln", "-sf",
                                       "/usr/lib/systemd/system/qubes-vm@.service",
                                       "/etc/systemd/system/multi-user.target.wants/qubes-vm@%s.service" % self.name])
        else:
            retcode = subprocess.call(["sudo", "systemctl", "disable", "qubes-vm@%s.service" % self.name])
        if retcode != 0:
            raise QubesException("Failed to set autostart for VM via systemctl")
        self._autostart = bool(value)

    @classmethod
    def is_template_compatible(cls, template):
        """Check if given VM can be a template for this VM"""
        # FIXME: check if the value is instance of QubesTemplateVM, not the VM
        # type. The problem is while this file is loaded, QubesTemplateVM is
        # not defined yet.
        if template and (not template.is_template() or template.type != "TemplateVM"):
            return False
        return True

    @property
    def template(self):
        return self._template

    @template.setter
    def template(self, value):
        if self._template is None and value is not None:
            raise QubesException("Cannot set template for standalone VM")
        if value and not self.is_template_compatible(value):
            raise QubesException("Incompatible template type %s with VM of type %s" % (value.type, self.type))
        self._template = value

    def is_template(self):
        return False

    def is_appvm(self):
        return False

    def is_netvm(self):
        return False

    def is_proxyvm(self):
        return False

    def is_disposablevm(self):
        return False

    @property
    def qdb(self):
        if self._qdb_connection is None:
            from qubes.qdb import QubesDB
            self._qdb_connection = QubesDB(self.name)
        return self._qdb_connection

    @property
    def xid(self):
        try:
            return self.libvirt_domain.ID()
        except libvirt.libvirtError as e:
            if e.get_error_code() == libvirt.VIR_ERR_NO_DOMAIN:
                return -1
            else:
                print >>sys.stderr, "libvirt error code: {!r}".format(
                    e.get_error_code())
                raise


    def get_xid(self):
        # obsoleted
        return self.xid

    def _update_libvirt_domain(self):
        domain_config = self.create_config_file()
        try:
            self._libvirt_domain = vmm.libvirt_conn.defineXML(domain_config)
        except libvirt.libvirtError as e:
            # shouldn't this be in QubesHVm implementation?
            if e.get_error_code() == libvirt.VIR_ERR_OS_TYPE and \
                    e.get_str2() == 'hvm':
                raise QubesException("HVM domains not supported on this "
                                     "machine. Check BIOS settings for "
                                     "VT-x/AMD-V extensions.")
            else:
                raise e
        self.uuid = uuid.UUID(bytes=self._libvirt_domain.UUID())

    @property
    def libvirt_domain(self):
        if self._libvirt_domain is None:
            if self.uuid is not None:
                self._libvirt_domain = vmm.libvirt_conn.lookupByUUID(self.uuid.bytes)
            else:
                self._libvirt_domain = vmm.libvirt_conn.lookupByName(self.name)
                self.uuid = uuid.UUID(bytes=self._libvirt_domain.UUID())
        return self._libvirt_domain

    def get_uuid(self):
        # obsoleted
        return self.uuid

    def refresh(self):
        self._libvirt_domain = None
        self._qdb_connection = None

    def get_mem(self):
        if dry_run:
            return 666

        try:
            if not self.libvirt_domain.isActive():
                return 0
            return self.libvirt_domain.info()[1]
        except libvirt.libvirtError as e:
            if e.get_error_code() == libvirt.VIR_ERR_NO_DOMAIN:
                return 0
                # libxl_domain_info failed - domain no longer exists
            elif e.get_error_code() == libvirt.VIR_ERR_INTERNAL_ERROR:
                return 0
            elif e.get_error_code() is None:  # unknown...
                return 0
            else:
                print >>sys.stderr, "libvirt error code: {!r}".format(
                    e.get_error_code())
                raise

    def get_cputime(self):
        if dry_run:
            return 666

        try:
            if not self.libvirt_domain.isActive():
                return 0
            return self.libvirt_domain.info()[4]
        except libvirt.libvirtError as e:
            if e.get_error_code() == libvirt.VIR_ERR_NO_DOMAIN:
                return 0
                # libxl_domain_info failed - domain no longer exists
            elif e.get_error_code() == libvirt.VIR_ERR_INTERNAL_ERROR:
                return 0
            elif e.get_error_code() is None:  # unknown...
                return 0
            else:
                print >>sys.stderr, "libvirt error code: {!r}".format(
                    e.get_error_code())
                raise

    def get_mem_static_max(self):
        if dry_run:
            return 666

        try:
            return self.libvirt_domain.maxMemory()
        except libvirt.libvirtError as e:
            if e.get_error_code() == libvirt.VIR_ERR_NO_DOMAIN:
                return 0
            else:
                raise

    def get_prefmem(self):
        # TODO: qmemman is still xen specific
        untrusted_meminfo_key = vmm.xs.read('',
                                            '/local/domain/%s/memory/meminfo'
                                            % self.xid)
        if untrusted_meminfo_key is None or untrusted_meminfo_key == '':
            return 0
        domain = qmemman.DomainState(self.xid)
        qmemman_algo.refresh_meminfo_for_domain(domain, untrusted_meminfo_key)
        domain.memory_maximum = self.get_mem_static_max()*1024
        return qmemman_algo.prefmem(domain)/1024

    def get_per_cpu_time(self):
        if dry_run:
            import random
            return random.random() * 100

        try:
            if self.libvirt_domain.isActive():
                return self.libvirt_domain.getCPUStats(
                        libvirt.VIR_NODE_CPU_STATS_ALL_CPUS, 0)[0]['cpu_time']/10**9
            else:
                return 0
        except libvirt.libvirtError as e:
            if e.get_error_code() == libvirt.VIR_ERR_NO_DOMAIN:
                return 0
            else:
                print >>sys.stderr, "libvirt error code: {!r}".format(
                    e.get_error_code())
                raise

    def get_disk_utilization_root_img(self):
        return qubes.qubesutils.get_disk_usage(self.root_img)

    def get_root_img_sz(self):
        if not os.path.exists(self.root_img):
            return 0

        return os.path.getsize(self.root_img)

    def get_power_state(self):
        if dry_run:
            return "NA"

        try:
            libvirt_domain = self.libvirt_domain
            if libvirt_domain.isActive():
                if libvirt_domain.state()[0] == libvirt.VIR_DOMAIN_PAUSED:
                    return "Paused"
                elif libvirt_domain.state()[0] == libvirt.VIR_DOMAIN_CRASHED:
                    return "Crashed"
                elif libvirt_domain.state()[0] == libvirt.VIR_DOMAIN_SHUTDOWN:
                    return "Halting"
                elif libvirt_domain.state()[0] == libvirt.VIR_DOMAIN_SHUTOFF:
                    return "Dying"
                elif libvirt_domain.state()[0] == libvirt.VIR_DOMAIN_PMSUSPENDED:
                    return "Suspended"
                else:
                    if not self.is_fully_usable():
                        return "Transient"
                    else:
                        return "Running"
            else:
                return 'Halted'
        except libvirt.libvirtError as e:
            if e.get_error_code() == libvirt.VIR_ERR_NO_DOMAIN:
                return "Halted"
            else:
                raise


    def is_guid_running(self):
        xid = self.xid
        if xid < 0:
            return False
        if not os.path.exists('/var/run/qubes/guid-running.%d' % xid):
            return False
        return True

    def is_qrexec_running(self):
        if self.xid < 0:
            return False
        return os.path.exists('/var/run/qubes/qrexec.%s' % self.name)

    def is_fully_usable(self):
        # Running gui-daemon implies also VM running
        if not self.is_guid_running():
            return False
        if not self.is_qrexec_running():
            return False
        return True

    def is_running(self):
        if vmm.offline_mode:
            return False
        try:
            if self.libvirt_domain.isActive():
                return True
            else:
                return False
        except libvirt.libvirtError as e:
            if e.get_error_code() == libvirt.VIR_ERR_NO_DOMAIN:
                return False
                # libxl_domain_info failed - domain no longer exists
            elif e.get_error_code() == libvirt.VIR_ERR_INTERNAL_ERROR:
                return False
            elif e.get_error_code() is None:  # unknown...
                return False
            else:
                print >>sys.stderr, "libvirt error code: {!r}".format(
                    e.get_error_code())
                raise

    def is_paused(self):
        try:
            if self.libvirt_domain.state()[0] == libvirt.VIR_DOMAIN_PAUSED:
                return True
            else:
                return False
        except libvirt.libvirtError as e:
            if e.get_error_code() == libvirt.VIR_ERR_NO_DOMAIN:
                return False
                # libxl_domain_info failed - domain no longer exists
            elif e.get_error_code() == libvirt.VIR_ERR_INTERNAL_ERROR:
                return False
            elif e.get_error_code() is None:  # unknown...
                return False
            else:
                print >>sys.stderr, "libvirt error code: {!r}".format(
                    e.get_error_code())
                raise

    def get_start_time(self):
        if not self.is_running():
            return None

        # TODO
        uuid = self.uuid

        start_time = vmm.xs.read('', "/vm/%s/start_time" % str(uuid))
        if start_time:
            return datetime.datetime.fromtimestamp(float(start_time))
        else:
            return None

    def is_outdated(self):
        # Makes sense only on VM based on template
        if self.template is None:
            return False

        if not self.is_running():
            return False

        if not hasattr(self.template, 'rootcow_img'):
            return False

        rootimg_inode = os.stat(self.template.root_img)
        try:
            rootcow_inode = os.stat(self.template.rootcow_img)
        except OSError:
            # The only case when rootcow_img doesn't exists is in the middle of
            # commit_changes, so VM is outdated right now
            return True

        current_dmdev = "/dev/mapper/snapshot-{0:x}:{1}-{2:x}:{3}".format(
                rootimg_inode[2], rootimg_inode[1],
                rootcow_inode[2], rootcow_inode[1])

        # FIXME
        # 51712 (0xCA00) is xvda
        #  backend node name not available through xenapi :(
        used_dmdev = vmm.xs.read('', "/local/domain/0/backend/vbd/{0}/51712/node".format(self.xid))

        return used_dmdev != current_dmdev

    @property
    def private_img(self):
        return self.storage.private_img

    @property
    def root_img(self):
        return self.storage.root_img

    @property
    def volatile_img(self):
        return self.storage.volatile_img

    def get_disk_utilization(self):
        return qubes.qubesutils.get_disk_usage(self.dir_path)

    def get_disk_utilization_private_img(self):
        return qubes.qubesutils.get_disk_usage(self.private_img)

    def get_private_img_sz(self):
        return self.storage.get_private_img_sz()

    def resize_private_img(self, size):
        assert size >= self.get_private_img_sz(), "Cannot shrink private.img"

        # resize the image
        self.storage.resize_private_img(size)

        # and then the filesystem
        retcode = 0
        if self.is_running():
            retcode = self.run("while [ \"`blockdev --getsize64 /dev/xvdb`\" -lt {0} ]; do ".format(size) +
                "head /dev/xvdb > /dev/null; sleep 0.2; done; resize2fs /dev/xvdb", user="root", wait=True)
        if retcode != 0:
            raise QubesException("resize2fs failed")



    # FIXME: should be outside of QubesVM?
    def get_timezone(self):
        # fc18
        if os.path.islink('/etc/localtime'):
            return '/'.join(os.readlink('/etc/localtime').split('/')[-2:])
        # <=fc17
        elif os.path.exists('/etc/sysconfig/clock'):
            clock_config = open('/etc/sysconfig/clock', "r")
            clock_config_lines = clock_config.readlines()
            clock_config.close()
            zone_re = re.compile(r'^ZONE="(.*)"')
            for line in clock_config_lines:
                line_match = zone_re.match(line)
                if line_match:
                    return line_match.group(1)
        else:
            # last resort way, some applications makes /etc/localtime
            # hardlink instead of symlink...
            tz_info = os.stat('/etc/localtime')
            if not tz_info:
                return None
            if tz_info.st_nlink > 1:
                p = subprocess.Popen(['find', '/usr/share/zoneinfo',
                                      '-inum', str(tz_info.st_ino),
                                      '-print', '-quit'],
                                     stdout=subprocess.PIPE)
                tz_path = p.communicate()[0].strip()
                return tz_path.replace('/usr/share/zoneinfo/', '')
        return None

    def cleanup_vifs(self):
        """
        Xend does not remove vif when backend domain is down, so we must do it
        manually
        """

        # FIXME: remove this?
        if not self.is_running():
            return

        dev_basepath = '/local/domain/%d/device/vif' % self.xid
        for dev in (vmm.xs.ls('', dev_basepath) or []):
            # check if backend domain is alive
            backend_xid = int(vmm.xs.read('', '%s/%s/backend-id' % (dev_basepath, dev)))
            if backend_xid in vmm.libvirt_conn.listDomainsID():
                # check if device is still active
                if vmm.xs.read('', '%s/%s/state' % (dev_basepath, dev)) == '4':
                    continue
            # remove dead device
            self.detach_network()

    def create_qubesdb_entries(self):
        if dry_run:
            return

        self.qdb.write("/name", self.name)
        self.qdb.write("/qubes-vm-type", self.type)
        self.qdb.write("/qubes-vm-updateable", str(self.updateable))
        self.qdb.write("/qubes-vm-persistence",
                       "full" if self.updateable else "rw-only")
        self.qdb.write("/qubes-base-template",
                       self.template.name if self.template else '')

        if self.is_netvm():
            self.qdb.write("/qubes-netvm-gateway", self.gateway)
            self.qdb.write("/qubes-netvm-primary-dns", self.gateway)
            self.qdb.write("/qubes-netvm-secondary-dns", self.secondary_dns)
            self.qdb.write("/qubes-netvm-netmask", self.netmask)
            self.qdb.write("/qubes-netvm-network", self.network)

        if self.netvm is not None:
            self.qdb.write("/qubes-ip", self.ip)
            self.qdb.write("/qubes-netmask", self.netvm.netmask)
            self.qdb.write("/qubes-gateway", self.netvm.gateway)
            self.qdb.write("/qubes-primary-dns", self.netvm.gateway)
            self.qdb.write("/qubes-secondary-dns", self.netvm.secondary_dns)

        tzname = self.get_timezone()
        if tzname:
             self.qdb.write("/qubes-timezone", tzname)

        for srv in self.services.keys():
            # convert True/False to "1"/"0"
            self.qdb.write("/qubes-service/{0}".format(srv),
                    str(int(self.services[srv])))

        self.qdb.write("/qubes-block-devices", '')

        self.qdb.write("/qubes-usb-devices", '')

        self.qdb.write("/qubes-debug-mode", str(int(self.debug)))

        self.provide_random_seed_to_vm()

        # TODO: Currently the whole qmemman is quite Xen-specific, so stay with
        # xenstore for it until decided otherwise
        if qmemman_present:
            vmm.xs.set_permissions('', '/local/domain/{0}/memory'.format(self.xid),
                    [{ 'dom': self.xid }])

        # fire hooks
        for hook in self.hooks_create_qubesdb_entries:
            hook(self)

    def provide_random_seed_to_vm(self):
        f = open('/dev/urandom', 'r')
        s = f.read(64)
        if len(s) != 64:
            raise IOError("failed to read seed from /dev/urandom")
        f.close()
        self.qdb.write("/qubes-random-seed", base64.b64encode(hashlib.sha512(s).digest()))

    def _format_net_dev(self, ip, mac, backend):
        template = "    <interface type='ethernet'>\n" \
                   "      <mac address='{mac}'/>\n" \
                   "      <ip address='{ip}'/>\n" \
                   "      <script path='vif-route-qubes'/>\n" \
                   "      <backenddomain name='{backend}'/>\n" \
                   "    </interface>\n"
        return template.format(ip=ip, mac=mac, backend=backend)

    def _format_pci_dev(self, address):
        template = "    <hostdev type='pci' managed='yes'{strictreset}>\n" \
                   "      <source>\n" \
                   "        <address bus='0x{bus}' slot='0x{slot}' function='0x{fun}'/>\n" \
                   "      </source>\n" \
                   "    </hostdev>\n"
        dev_match = re.match('([0-9a-f]+):([0-9a-f]+)\.([0-9a-f]+)', address)
        if not dev_match:
            raise QubesException("Invalid PCI device address: %s" % address)
        return template.format(
                bus=dev_match.group(1),
                slot=dev_match.group(2),
                fun=dev_match.group(3),
                strictreset=("" if self.pci_strictreset else
                             " nostrictreset='yes'"),
        )

    def get_config_params(self):
        args = {}
        args['name'] = self.name
        if hasattr(self, 'kernels_dir'):
            args['kerneldir'] = self.kernels_dir
        args['uuidnode'] = "<uuid>%s</uuid>" % str(self.uuid) if self.uuid else ""
        args['vmdir'] = self.dir_path
        args['pcidevs'] = ''.join(map(self._format_pci_dev, self.pcidevs))
        args['mem'] = str(self.memory)
        if self.maxmem < self.memory:
            args['mem'] = str(self.maxmem)
        args['maxmem'] = str(self.maxmem)
        if 'meminfo-writer' in self.services and not self.services['meminfo-writer']:
            # If dynamic memory management disabled, set maxmem=mem
            args['maxmem'] = args['mem']
        args['vcpus'] = str(self.vcpus)
        args['features'] = ''
        if self.netvm is not None:
            args['ip'] = self.ip
            args['mac'] = self.mac
            args['gateway'] = self.netvm.gateway
            args['dns1'] = self.netvm.gateway
            args['dns2'] = self.secondary_dns
            args['netmask'] = self.netmask
            args['netdev'] = self._format_net_dev(self.ip, self.mac, self.netvm.name)
            args['network_begin'] = ''
            args['network_end'] = ''
            args['no_network_begin'] = '<!--'
            args['no_network_end'] = '-->'
        else:
            args['ip'] = ''
            args['mac'] = ''
            args['gateway'] = ''
            args['dns1'] = ''
            args['dns2'] = ''
            args['netmask'] = ''
            args['netdev'] = ''
            args['network_begin'] = '<!--'
            args['network_end'] = '-->'
            args['no_network_begin'] = ''
            args['no_network_end'] = ''
        if len(self.pcidevs) and self.pci_e820_host:
            args['features'] = '<xen><e820_host state=\'on\'/></xen>'
        args.update(self.storage.get_config_params())
        if hasattr(self, 'kernelopts'):
            args['kernelopts'] = self.kernelopts
            if self.debug:
                print >> sys.stderr, "--> Debug mode: adding 'earlyprintk=xen' to kernel opts"
                args['kernelopts'] += ' earlyprintk=xen'

        if self.virt_mode == 'pv':
            args['machine'] = 'xenpv'
            args['type'] = 'linux'
            args['cpu_begin'] = '<!--'
            args['cpu_end'] = '-->'
            args['emulator_begin'] = '<!--'
            args['emulator_end'] = '-->'
        else:
            args['machine'] = 'xenfv'
            args['type'] = 'hvm'
            args['cpu_begin'] = ''
            args['cpu_end'] = ''
            args['features'] += '<pae/><acpi/><apic/><viridian/>'
            args['emulator_begin'] = ''
            args['emulator_end'] = ''

        if self.virt_mode == 'hvm':
            args['boot_begin'] = ''
            args['boot_end'] = ''
            args['kernel_begin'] = '<!--'
            args['kernel_end'] = '-->'
            args['emulator_type'] = 'stubdom-linux'
        else:
            args['emulator_type'] = 'none' # ignored in pv mode
            args['boot_begin'] = '<!--'
            args['boot_end'] = '-->'
            args['kernel_begin'] = ''
            args['kernel_end'] = ''


        # fire hooks
        for hook in self.hooks_get_config_params:
            args = hook(self, args)

        return args

    @property
    def uses_custom_config(self):
        return self.conf_file != self.absolute_path(self.name + ".conf", None)

    def create_config_file(self, file_path = None, prepare_dvm = False):
        if file_path is None:
            file_path = self.conf_file
        if self.uses_custom_config:
            conf_appvm = open(file_path, "r")
            domain_config = conf_appvm.read()
            conf_appvm.close()
            return domain_config

        f_conf_template = open(self.config_file_template, 'r')
        conf_template = f_conf_template.read()
        f_conf_template.close()

        template_params = self.get_config_params()
        if prepare_dvm:
            template_params['name'] = '%NAME%'
            template_params['privatedev'] = ''
            template_params['netdev'] = re.sub(r"address='[0-9.]*'", "address='%IP%'", template_params['netdev'])
        domain_config = conf_template.format(**template_params)

        # FIXME: This is only for debugging purposes
        old_umask = os.umask(002)
        try:
            if os.path.exists(file_path):
                os.unlink(file_path)
            conf_appvm = open(file_path, "w")
            conf_appvm.write(domain_config)
            conf_appvm.close()
        except:
            # Ignore errors
            pass
        finally:
            os.umask(old_umask)

        return domain_config

    def create_on_disk(self, verbose=False, source_template = None):
        self.log.debug('create_on_disk(source_template={!r})'.format(
            source_template))
        if source_template is None:
            source_template = self.template
        assert source_template is not None

        if dry_run:
            return

        self.storage.create_on_disk(verbose, source_template)

        if self.updateable:
            kernels_dir = source_template.kernels_dir
            if verbose:
                print >> sys.stderr, "--> Copying the kernel (set kernel \"none\" to use it): {0}".\
                        format(kernels_dir)

            os.mkdir (self.dir_path + '/kernels')
            for f in ("vmlinuz", "initramfs", "modules.img"):
                shutil.copy(os.path.join(kernels_dir, f),
                        os.path.join(self.dir_path, vm_files["kernels_subdir"], f))

        if verbose:
            print >> sys.stderr, "--> Creating icon symlink: {0} -> {1}".format(self.icon_path, self.label.icon_path)
        if hasattr(os, "symlink"):
            os.symlink (self.label.icon_path, self.icon_path)
        else:
            shutil.copy(self.label.icon_path, self.icon_path)

        # Make sure that we have UUID allocated
        if not vmm.offline_mode:
            self._update_libvirt_domain()
        else:
            self.uuid = uuid.uuid4()

        # fire hooks
        for hook in self.hooks_create_on_disk:
            hook(self, verbose, source_template=source_template)

    def get_clone_attrs(self):
        attrs = ['kernel', 'uses_default_kernel', 'netvm', 'uses_default_netvm',
                 'memory', 'maxmem', 'kernelopts', 'uses_default_kernelopts',
                 'services', 'vcpus', '_mac', 'pcidevs', 'include_in_backups',
                 '_label', 'default_user', 'qrexec_timeout',
                 'dispvm_netvm', 'uses_default_dispvm_netvm']

        # fire hooks
        for hook in self.hooks_get_clone_attrs:
            attrs = hook(self, attrs)

        return attrs

    def clone_attrs(self, src_vm, fail_on_error=True):
        self._do_not_reset_firewall = True
        for prop in self.get_clone_attrs():
            try:
                val = getattr(src_vm, prop)
                if isinstance(val, dict):
                    val = val.copy()
                setattr(self, prop, val)
            except Exception as e:
                if fail_on_error:
                    self._do_not_reset_firewall = False
                    raise
                else:
                    print >>sys.stderr, "WARNING: %s" % str(e)
        self._do_not_reset_firewall = False

    def clone_disk_files(self, src_vm, verbose):
        if dry_run:
            return

        if src_vm.is_running():
            raise QubesException("Attempt to clone a running VM!")

        self.storage.clone_disk_files(src_vm, verbose)

        if src_vm.icon_path is not None and self.icon_path is not None:
            if os.path.exists (src_vm.dir_path):
                if os.path.islink(src_vm.icon_path):
                    icon_path = os.readlink(src_vm.icon_path)
                    if verbose:
                        print >> sys.stderr, "--> Creating icon symlink: {0} -> {1}".format(self.icon_path, icon_path)
                    os.symlink (icon_path, self.icon_path)
                else:
                    if verbose:
                        print >> sys.stderr, "--> Copying icon: {0} -> {1}".format(src_vm.icon_path, self.icon_path)
                    shutil.copy(src_vm.icon_path, self.icon_path)

        if src_vm.has_firewall():
            self.write_firewall_conf(src_vm.get_firewall_conf())

        # Make sure that we have UUID allocated
        self._update_libvirt_domain()

        # fire hooks
        for hook in self.hooks_clone_disk_files:
            hook(self, src_vm, verbose)

    def verify_files(self):
        if dry_run:
            return

        self.storage.verify_files()

        if not os.path.exists (os.path.join(self.kernels_dir, 'vmlinuz')):
            raise QubesException (
                "VM kernel does not exist: {0}".\
                format(os.path.join(self.kernels_dir, 'vmlinuz')))

        if not os.path.exists (os.path.join(self.kernels_dir, 'initramfs')):
            raise QubesException (
                "VM initramfs does not exist: {0}".\
                format(os.path.join(self.kernels_dir, 'initramfs')))

        # fire hooks
        for hook in self.hooks_verify_files:
            hook(self)

        return True

    def remove_from_disk(self):
        self.log.debug('remove_from_disk()')
        if dry_run:
            return

        # fire hooks
        for hook in self.hooks_remove_from_disk:
            hook(self)

        try:
            self.libvirt_domain.undefine()
        except libvirt.libvirtError as e:
            if e.get_error_code() == libvirt.VIR_ERR_NO_DOMAIN:
                # already undefined
                pass
            else:
                print >>sys.stderr, "libvirt error code: {!r}".format(
                    e.get_error_code())
                raise

        if os.path.exists("/etc/systemd/system/multi-user.target.wants/qubes-vm@" + self.name + ".service"):
            retcode = subprocess.call(["sudo", "systemctl", "-q", "disable",
                "qubes-vm@" + self.name + ".service"])
            if retcode != 0:
                raise QubesException("Failed to delete autostart entry for VM")

        self.storage.remove_from_disk()

    def write_firewall_conf(self, conf):
        defaults = self.get_firewall_conf()
        expiring_rules_present = False
        for item in defaults.keys():
            if item not in conf:
                conf[item] = defaults[item]

        root = lxml.etree.Element(
                "QubesFirewallRules",
                policy = "allow" if conf["allow"] else "deny",
                dns = "allow" if conf["allowDns"] else "deny",
                icmp = "allow" if conf["allowIcmp"] else "deny",
                yumProxy = "allow" if conf["allowYumProxy"] else "deny"
        )

        for rule in conf["rules"]:
            # For backward compatibility
            if "proto" not in rule:
                if rule["portBegin"] is not None and rule["portBegin"] > 0:
                    rule["proto"] = "tcp"
                else:
                    rule["proto"] = "any"
            element = lxml.etree.Element(
                    "rule",
                    address=rule["address"],
                    proto=str(rule["proto"]),
            )
            if rule["netmask"] is not None and rule["netmask"] != 32:
                element.set("netmask", str(rule["netmask"]))
            if rule.get("portBegin", None) is not None and \
                            rule["portBegin"] > 0:
                element.set("port", str(rule["portBegin"]))
            if rule.get("portEnd", None) is not None and rule["portEnd"] > 0:
                element.set("toport", str(rule["portEnd"]))
            if "expire" in rule:
                element.set("expire", str(rule["expire"]))
                expiring_rules_present = True

            root.append(element)

        tree = lxml.etree.ElementTree(root)

        try:
            old_umask = os.umask(002)
            with open(self.firewall_conf, 'w') as f:
                tree.write(f, encoding="UTF-8", pretty_print=True)
            f.close()
            os.umask(old_umask)
        except EnvironmentError as err:
            print >> sys.stderr, "{0}: save error: {1}".format(
                    os.path.basename(sys.argv[0]), err)
            return False

        # Automatically enable/disable 'yum-proxy-setup' service based on allowYumProxy
        if conf['allowYumProxy']:
            self.services['yum-proxy-setup'] = True
        else:
            if self.services.has_key('yum-proxy-setup'):
                self.services.pop('yum-proxy-setup')

        if expiring_rules_present:
            subprocess.call(["sudo", "systemctl", "start",
                             "qubes-reload-firewall@%s.timer" % self.name])

        return True

    def has_firewall(self):
        return os.path.exists (self.firewall_conf)

    def get_firewall_defaults(self):
        return { "rules": list(), "allow": True, "allowDns": True, "allowIcmp": True, "allowYumProxy": False }

    def get_firewall_conf(self):
        conf = self.get_firewall_defaults()

        try:
            tree = lxml.etree.parse(self.firewall_conf)
            root = tree.getroot()

            conf["allow"] = (root.get("policy") == "allow")
            conf["allowDns"] = (root.get("dns") == "allow")
            conf["allowIcmp"] = (root.get("icmp") == "allow")
            conf["allowYumProxy"] = (root.get("yumProxy") == "allow")

            for element in root:
                rule = {}
                attr_list = ("address", "netmask", "proto", "port", "toport",
                             "expire")

                for attribute in attr_list:
                    rule[attribute] = element.get(attribute)

                if rule["netmask"] is not None:
                    rule["netmask"] = int(rule["netmask"])
                else:
                    rule["netmask"] = 32

                if rule["port"] is not None:
                    rule["portBegin"] = int(rule["port"])
                else:
                    # backward compatibility
                    rule["portBegin"] = 0

                # For backward compatibility
                if rule["proto"] is None:
                    if rule["portBegin"] > 0:
                        rule["proto"] = "tcp"
                    else:
                        rule["proto"] = "any"

                if rule["toport"] is not None:
                    rule["portEnd"] = int(rule["toport"])
                else:
                    rule["portEnd"] = None

                if rule["expire"] is not None:
                    rule["expire"] = int(rule["expire"])
                    if rule["expire"] <= int(datetime.datetime.now().strftime(
                            "%s")):
                        continue
                else:
                    del(rule["expire"])

                del(rule["port"])
                del(rule["toport"])

                conf["rules"].append(rule)

        except EnvironmentError as err:
            return conf
        except (xml.parsers.expat.ExpatError,
                ValueError, LookupError) as err:
            print("{0}: load error: {1}".format(
                os.path.basename(sys.argv[0]), err))
            return None

        return conf

    def pci_add(self, pci):
        self.log.debug('pci_add(pci={!r})'.format(pci))
        if not os.path.exists('/sys/bus/pci/devices/0000:%s' % pci):
            raise QubesException("Invalid PCI device: %s" % pci)
        if self.pcidevs.count(pci):
            # already added
            return
        self.pcidevs.append(pci)
        if self.is_running():
            try:
                subprocess.check_call(['sudo', system_path["qubes_pciback_cmd"], pci])
                subprocess.check_call(['sudo', 'xl', 'pci-attach', str(self.xid), pci])
            except Exception as e:
                print >>sys.stderr, "Failed to attach PCI device on the fly " \
                    "(%s), changes will be seen after VM restart" % str(e)

    def pci_remove(self, pci):
        self.log.debug('pci_remove(pci={!r})'.format(pci))
        if not self.pcidevs.count(pci):
            # not attached
            return
        self.pcidevs.remove(pci)
        if self.is_running():
            p = subprocess.Popen(['xl', 'pci-list', str(self.xid)],
                    stdout=subprocess.PIPE)
            result = p.communicate()
            m = re.search(r"^(\d+.\d+)\s+0000:%s$" % pci, result[0], flags=re.MULTILINE)
            if not m:
                print >>sys.stderr, "Device %s already detached" % pci
                return
            vmdev = m.group(1)
            try:
                self.run_service("qubes.DetachPciDevice",
                                 user="root", input="00:%s" % vmdev)
                subprocess.check_call(['sudo', 'xl', 'pci-detach', str(self.xid), pci])
            except Exception as e:
                print >>sys.stderr, "Failed to detach PCI device on the fly " \
                    "(%s), changes will be seen after VM restart" % str(e)

    def run(self, command, user = None, verbose = True, autostart = False,
            notify_function = None,
            passio = False, passio_popen = False, passio_stderr=False,
            ignore_stderr=False, localcmd = None, wait = False, gui = True,
            filter_esc = False):
        """command should be in form 'cmdline'
            When passio_popen=True, popen object with stdout connected to pipe.
            When additionally passio_stderr=True, stderr also is connected to pipe.
            When ignore_stderr=True, stderr is connected to /dev/null.
            """

        self.log.debug(
            'run(command={!r}, user={!r}, passio={!r}, wait={!r})'.format(
                command, user, passio, wait))

        if user is None:
            user = self.default_user
        null = None
        if not self.is_running() and not self.is_paused():
            if not autostart:
                raise QubesException("VM not running")

            try:
                if notify_function is not None:
                    notify_function ("info", "Starting the '{0}' VM...".format(self.name))
                elif verbose:
                    print >> sys.stderr, "Starting the VM '{0}'...".format(self.name)
                self.start(verbose=verbose, start_guid = gui, notify_function=notify_function)

            except (IOError, OSError, QubesException) as err:
                raise QubesException("Error while starting the '{0}' VM: {1}".format(self.name, err))
            except (MemoryError) as err:
                raise QubesException("Not enough memory to start '{0}' VM! "
                                     "Close one or more running VMs and try "
                                     "again.".format(self.name))

        if self.is_paused():
            raise QubesException("VM is paused")
        if not self.is_qrexec_running():
            raise QubesException(
                "Domain '{}': qrexec not connected.".format(self.name))

        if gui and os.getenv("DISPLAY") is not None and not self.is_guid_running():
            self.start_guid(verbose = verbose, notify_function = notify_function)

        args = [system_path["qrexec_client_path"], "-d", str(self.name), "%s:%s" % (user, command)]
        if localcmd is not None:
            args += [ "-l", localcmd]
        if filter_esc:
            args += ["-t"]
        if os.isatty(sys.stderr.fileno()):
            args += ["-T"]

        call_kwargs = {}
        if ignore_stderr or not passio:
            null = open("/dev/null", "w+")
            call_kwargs['stderr'] = null
        if not passio:
            call_kwargs['stdin'] = null
            call_kwargs['stdout'] = null

        if passio_popen:
            popen_kwargs={'stdout': subprocess.PIPE}
            popen_kwargs['stdin'] = subprocess.PIPE
            if passio_stderr:
                popen_kwargs['stderr'] = subprocess.PIPE
            else:
                popen_kwargs['stderr'] = call_kwargs.get('stderr', None)
            p = subprocess.Popen (args, **popen_kwargs)
            if null:
                null.close()
            return p
        if not wait and not passio:
            args += ["-e"]
        retcode = subprocess.call(args, **call_kwargs)
        if null:
            null.close()
        return retcode

    def run_service(self, service, source="dom0", user=None,
                    passio_popen=False, input=None, localcmd=None, gui=False,
                    wait=True):
        if bool(input) + bool(passio_popen) + bool(localcmd) > 1:
            raise ValueError("'input', 'passio_popen', 'localcmd' cannot be "
                             "used together")
        if not wait and (localcmd or input):
            raise ValueError("Cannot use wait=False with input or "
                             "localcmd specified")
        if localcmd:
            return self.run("QUBESRPC %s %s" % (service, source),
                            localcmd=localcmd, user=user, wait=wait, gui=gui)
        elif input:
            p = self.run("QUBESRPC %s %s" % (service, source),
                user=user, wait=wait, gui=gui, passio_popen=True,
                passio_stderr=True)
            p.communicate(input)
            return p.returncode
        else:
            return self.run("QUBESRPC %s %s" % (service, source),
                            passio_popen=passio_popen, user=user, wait=wait,
                            gui=gui, passio_stderr=passio_popen)

    def attach_network(self, verbose = False, wait = True, netvm = None):
        self.log.debug('attach_network(netvm={!r})'.format(netvm))
        if dry_run:
            return

        if not self.is_running():
            raise QubesException ("VM not running!")

        if netvm is None:
            netvm = self.netvm

        if netvm is None:
            raise QubesException ("NetVM not set!")

        if netvm.qid != 0:
            if not netvm.is_running():
                if verbose:
                    print >> sys.stderr, "--> Starting NetVM {0}...".format(netvm.name)
                netvm.start()

        self.libvirt_domain.attachDevice(
                self._format_net_dev(self.ip, self.mac, self.netvm.name))

    def detach_network(self, verbose = False, netvm = None):
        self.log.debug('detach_network(netvm={!r})'.format(netvm))
        if dry_run:
            return

        if not self.is_running():
            raise QubesException ("VM not running!")

        if netvm is None:
            netvm = self.netvm

        if netvm is None:
            raise QubesException ("NetVM not set!")

        self.libvirt_domain.detachDevice( self._format_net_dev(self.ip,
            self.mac, self.netvm.name))

    def wait_for_session(self, notify_function = None):
        self.log.debug('wait_for_session()')
        #self.run('echo $$ >> /tmp/qubes-session-waiter; [ ! -f /tmp/qubes-session-env ] && exec sleep 365d', ignore_stderr=True, gui=False, wait=True)

        # Note : User root is redefined to SYSTEM in the Windows agent code
        p = self.run('QUBESRPC qubes.WaitForSession none', user="root", passio_popen=True, gui=False, wait=True)
        p.communicate(input=self.default_user)

    def start_guid(self, verbose = True, notify_function = None,
            extra_guid_args=None, before_qrexec=False):
        self.log.debug(
            'start_guid(extra_guid_args={!r}, before_qrexec={!r})'.format(
                extra_guid_args, before_qrexec))
        if before_qrexec:
            # On PV start GUId only after qrexec-daemon
            return

        if verbose:
            print >> sys.stderr, "--> Starting Qubes GUId..."

        guid_cmd = []
        if os.getuid() == 0:
            # try to always have guid running as normal user, otherwise
            # clipboard file may be created as root and other permission
            # problems
            qubes_group = grp.getgrnam('qubes')
            guid_cmd = ['runuser', '-u', qubes_group.gr_mem[0], '--']

        guid_cmd += [system_path["qubes_guid_path"],
            "-d", str(self.xid), "-N", self.name,
            "-c", self.label.color,
            "-i", self.label.icon_path,
            "-l", str(self.label.index)]
        if extra_guid_args is not None:
            guid_cmd += extra_guid_args
        if self.debug:
            guid_cmd += ['-v', '-v']
        elif not verbose:
            guid_cmd += ['-q']
        # Avoid using environment variables for checking the current session,
        #  because this script may be called with cleared env (like with sudo).
        if subprocess.check_output(
                ['xprop', '-root', '-notype', 'KWIN_RUNNING']) == \
                'KWIN_RUNNING = 0x1\n':
            # native decoration plugins is used, so adjust window properties
            # accordingly
            guid_cmd += ['-T']  # prefix window titles with VM name
            # get owner of X11 session
            session_owner = None
            for line in subprocess.check_output(['xhost']).splitlines():
                if line == 'SI:localuser:root':
                    pass
                elif line.startswith('SI:localuser:'):
                    session_owner = line.split(":")[2]
            if session_owner is not None:
                data_dir = os.path.expanduser(
                    '~{}/.local/share'.format(session_owner))
            else:
                # fallback to current user
                data_dir = os.path.expanduser('~/.local/share')

            guid_cmd += ['-p',
                '_KDE_NET_WM_COLOR_SCHEME=s:{}'.format(
                    os.path.join(data_dir,
                        'qubes-kde', self.label.name + '.colors'))]

        retcode = subprocess.call (guid_cmd)
        if (retcode != 0) :
            raise QubesException("Cannot start qubes-guid!")

        if not self.is_qrexec_running():
            return

        try:
            import qubes.monitorlayoutnotify
            if verbose:
                print >> sys.stderr, "--> Sending monitor layout..."
            monitor_layout = qubes.monitorlayoutnotify.get_monitor_layout()
            # Notify VM only if we've got a monitor_layout which is not empty
            # or else we break proper VM resolution set by gui-agent
            if len(monitor_layout) > 0:
                qubes.monitorlayoutnotify.notify_vm(self, monitor_layout)
        except ImportError as e:
            print >>sys.stderr, "ERROR: %s" % e

        if verbose:
            print >> sys.stderr, "--> Waiting for qubes-session..."

        self.wait_for_session(notify_function)

    def start_qrexec_daemon(self, verbose = False, notify_function = None):
        self.log.debug('start_qrexec_daemon()')
        if verbose:
            print >> sys.stderr, "--> Starting the qrexec daemon..."
        qrexec = []
        if os.getuid() == 0:
            # try to always have qrexec running as normal user, otherwise
            # many qrexec services would need to deal with root/user
            # permission problems
            qubes_group = grp.getgrnam('qubes')
            qrexec = ['runuser', '-u', qubes_group.gr_mem[0], '--']

        qrexec += ['env', 'QREXEC_STARTUP_TIMEOUT=' + str(self.qrexec_timeout),
            system_path["qrexec_daemon_path"]]

        qrexec_args = [str(self.xid), self.name, self.default_user]
        if not verbose:
            qrexec_args.insert(0, "-q")
        retcode = subprocess.call(qrexec + qrexec_args)
        if (retcode != 0) :
            raise OSError ("Cannot execute qrexec-daemon!")

    def start_qubesdb(self):
        self.log.debug('start_qubesdb()')
        pidfile = '/var/run/qubes/qubesdb.{}.pid'.format(self.name)
        try:
            if os.path.exists(pidfile):
                old_qubesdb_pid = open(pidfile, 'r').read()
                try:
                    os.kill(int(old_qubesdb_pid), signal.SIGTERM)
                except OSError:
                    raise QubesException(
                        "Failed to kill old QubesDB instance (PID {}). "
                        "Terminate it manually and retry. "
                        "If that isn't QubesDB process, "
                        "remove the pidfile: {}".format(old_qubesdb_pid,
                                                        pidfile))
                timeout = 25
                while os.path.exists(pidfile) and timeout:
                    time.sleep(0.2)
                    timeout -= 1
        except IOError:  # ENOENT (pidfile)
            pass

        # force connection to a new daemon
        self._qdb_connection = None

        qubesdb_cmd = []
        if os.getuid() == 0:
            # try to always have qubesdb running as normal user, otherwise
            # killing it at VM restart (see above) will always fail
            qubes_group = grp.getgrnam('qubes')
            qubesdb_cmd = ['runuser', '-u', qubes_group.gr_mem[0], '--']

        qubesdb_cmd += [
            system_path["qubesdb_daemon_path"],
            str(self.xid),
            self.name]

        retcode = subprocess.call (qubesdb_cmd)
        if retcode != 0:
            raise OSError("ERROR: Cannot execute qubesdb-daemon!")

    def request_memory(self, mem_required = None):
        # Overhead of per-VM/per-vcpu Xen structures, taken from OpenStack nova/virt/xenapi/driver.py
        # see https://wiki.openstack.org/wiki/XenServer/Overhead
        # add an extra MB because Nova rounds up to MBs
        MEM_OVERHEAD_BASE = (3 + 1) * 1024 * 1024
        MEM_OVERHEAD_PER_VCPU = 3 * 1024 * 1024 / 2
        if mem_required is None:
            mem_required = int(self.memory) * 1024 * 1024
            if self.virt_mode == 'hvm':
                mem_required += (128 + 8) * 1024 * 1024 # memory for stubdom
        if qmemman_present:
            qmemman_client = QMemmanClient()
            try:
                mem_required_with_overhead = mem_required + MEM_OVERHEAD_BASE + self.vcpus * MEM_OVERHEAD_PER_VCPU
                got_memory = qmemman_client.request_memory(mem_required_with_overhead)
            except IOError as e:
                raise IOError("ERROR: Failed to connect to qmemman: %s" % str(e))
            if not got_memory:
                qmemman_client.close()
                raise MemoryError ("ERROR: insufficient memory to start VM '%s'" % self.name)
            return qmemman_client

    def start(self, verbose = False, preparing_dvm = False, start_guid = True,
            notify_function = None, mem_required = None):
        self.log.debug('start('
            'preparing_dvm={!r}, start_guid={!r}, mem_required={!r})'.format(
                preparing_dvm, start_guid, mem_required))

        if len(self.pcidevs) != 0 and self.virt_mode == 'pvh':
            raise QubesException(
                "pvh mode can't be set if pci devices are attached")

        if dry_run:
            return

        # Intentionally not used is_running(): eliminate also "Paused", "Crashed", "Halting"
        if self.get_power_state() != "Halted":
            raise QubesException ("VM is already running!")

        self.verify_files()

        if self.netvm is not None:
            if self.netvm.qid != 0:
                if not self.netvm.is_running():
                    if verbose:
                        print >> sys.stderr, "--> Starting NetVM {0}...".format(self.netvm.name)
                    self.netvm.start(verbose = verbose, start_guid = start_guid, notify_function = notify_function)

        self.storage.prepare_for_vm_startup(verbose=verbose)
        if verbose:
            print >> sys.stderr, "--> Loading the VM (type = {0})...".format(self.type)

        self._update_libvirt_domain()

        qmemman_client = self.request_memory(mem_required)

        # Bind pci devices to pciback driver
        for pci in self.pcidevs:
            try:
                nd = vmm.libvirt_conn.nodeDeviceLookupByName('pci_0000_' + pci.replace(':','_').replace('.','_'))
            except libvirt.libvirtError as e:
                if e.get_error_code() == libvirt.VIR_ERR_NO_NODE_DEVICE:
                    raise QubesException(
                        "PCI device {} does not exist (domain {})".
                        format(pci, self.name))
                else:
                    raise
            try:
                nd.dettach()
            except libvirt.libvirtError as e:
                if e.get_error_code() == libvirt.VIR_ERR_INTERNAL_ERROR:
                    # already detached
                    pass
                else:
                    raise

        self.libvirt_domain.createWithFlags(libvirt.VIR_DOMAIN_START_PAUSED)

        try:
            if verbose:
                print >> sys.stderr, "--> Starting Qubes DB..."
            self.start_qubesdb()

            xid = self.xid
            self.log.debug('xid={}'.format(xid))

            if preparing_dvm:
                self.services['qubes-dvm'] = True
            if verbose:
                print >> sys.stderr, "--> Setting Qubes DB info for the VM..."
            self.create_qubesdb_entries()

            if verbose:
                print >> sys.stderr, "--> Updating firewall rules..."
            netvm = self.netvm
            while netvm is not None:
                if netvm.is_proxyvm() and netvm.is_running():
                    netvm.write_iptables_qubesdb_entry()
                netvm = netvm.netvm

            # fire hooks
            for hook in self.hooks_start:
                hook(self, verbose = verbose, preparing_dvm =  preparing_dvm,
                     start_guid = start_guid, notify_function = notify_function)
        except:
            self.force_shutdown()
            raise

        if verbose:
            print >> sys.stderr, "--> Starting the VM..."
        self.libvirt_domain.resume()

# close() is not really needed, because the descriptor is close-on-exec
# anyway, the reason to postpone close() is that possibly xl is not done
# constructing the domain after its main process exits
# so we close() when we know the domain is up
# the successful unpause is some indicator of it
        if qmemman_present:
            qmemman_client.close()

        extra_guid_args = []
        if preparing_dvm:
            # Run GUI daemon in "invisible" mode, so applications started by
            # prerun script will not disturb the user
            extra_guid_args = ['-I']
        elif not os.path.exists('/var/run/shm.id'):
            # Start GUI daemon only when shmoverride is loaded; unless
            # preparing DispVM, where it isn't needed because of "invisible"
            # mode
            start_guid = False
        if start_guid and 'DISPLAY' not in os.environ:
            if verbose:
                print >> sys.stderr, \
                    "WARNING: not starting GUI, because DISPLAY not set"
            start_guid = False

        if start_guid:
            self.start_guid(verbose=verbose, notify_function=notify_function,
                            before_qrexec=True, extra_guid_args=extra_guid_args)

        if not preparing_dvm:
            self.start_qrexec_daemon(verbose=verbose,notify_function=notify_function)

        if start_guid:
            self.start_guid(verbose=verbose, notify_function=notify_function,
                            extra_guid_args=extra_guid_args)

        return xid

    def _cleanup_zombie_domains(self):
        """
        This function is workaround broken libxl (which leaves not fully
        created domain on failure) and vchan on domain crash behaviour
        @return: None
        """
        xc = self.get_xc_dominfo()
        if xc and xc['dying'] == 1:
            # GUID still running?
            guid_pidfile = '/var/run/qubes/guid-running.%d' % xc['domid']
            if os.path.exists(guid_pidfile):
                guid_pid = open(guid_pidfile).read().strip()
                os.kill(int(guid_pid), 15)
            # qrexec still running?
            if self.is_qrexec_running():
                #TODO: kill qrexec daemon
                pass

    def shutdown(self, force=False, xid = None):
        self.log.debug('shutdown()')
        if dry_run:
            return

        if not self.is_running():
            raise QubesException ("VM already stopped!")

        self.libvirt_domain.shutdown()

    def force_shutdown(self, xid = None):
        self.log.debug('force_shutdown()')
        if dry_run:
            return

        if not self.is_running() and not self.is_paused():
            raise QubesException ("VM already stopped!")

        self.libvirt_domain.destroy()
        self.refresh()

    def suspend(self):
        self.log.debug('suspend()')
        if dry_run:
            return

        if not self.is_running() and not self.is_paused() or \
                self.get_power_state() == "Suspended":
            raise QubesException ("VM not running!")

        if len (self.pcidevs) > 0:
            self.libvirt_domain.pMSuspendForDuration(
                libvirt.VIR_NODE_SUSPEND_TARGET_MEM, 0, 0)
        else:
            self.pause()

    def resume(self):
        self.log.debug('resume()')
        if dry_run:
            return

        if self.get_power_state() == "Suspended":
            self.libvirt_domain.pMWakeup()
        else:
            self.unpause()

    def pause(self):
        self.log.debug('pause()')
        if dry_run:
            return

        if not self.is_running():
            raise QubesException ("VM not running!")

        self.libvirt_domain.suspend()

    def unpause(self):
        self.log.debug('unpause()')
        if dry_run:
            return

        if not self.is_paused():
            raise QubesException ("VM not paused!")

        self.libvirt_domain.resume()

    def get_xml_attrs(self):
        attrs = {}
        attrs_config = self.get_attrs_config()
        for attr in attrs_config:
            attr_config = attrs_config[attr]
            if 'save' in attr_config:
                if 'save_skip' in attr_config:
                    if callable(attr_config['save_skip']):
                        if attr_config['save_skip']():
                            continue
                    elif eval(attr_config['save_skip']):
                        continue
                if callable(attr_config['save']):
                    value = attr_config['save']()
                else:
                    value = eval(attr_config['save'])
                if 'save_attr' in attr_config:
                    attrs[attr_config['save_attr']] = value
                else:
                    attrs[attr] = value
        return attrs

    def create_xml_element(self):

        attrs = self.get_xml_attrs()
        element = lxml.etree.Element(
            # Compatibility hack (Qubes*VM in type vs Qubes*Vm in XML)...
            "Qubes" + self.type.replace("VM", "Vm"),
            **attrs)
        return element

register_qubes_vm_class(QubesVm)
