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

import datetime
import fcntl
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
from qubes import qmemman
from qubes import qmemman_algo
import libvirt
import warnings

from qubes.qdb import QubesDB
from qubes.qubes import dry_run,vmm
from qubes.qubes import register_qubes_vm_class
from qubes.qubes import QubesVmCollection,QubesException,QubesHost,QubesVmLabels
from qubes.qubes import defaults,system_path,vm_files,qubes_max_qid
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
    hooks_create_xenstore_entries = []
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
            "conf_file": {
                "func": lambda value: self.absolute_path(value, self.name +
                                                                 ".conf"),
                "order": 3 },
            ### order >= 10: have base attrs set
            "root_img": {
                "func": self._absolute_path_gen(vm_files["root_img"]),
                "order": 10 },
            "private_img": {
                "func": self._absolute_path_gen(vm_files["private_img"]),
                "order": 10 },
            "volatile_img": {
                "func": self._absolute_path_gen(vm_files["volatile_img"]),
                "order": 10 },
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
                "func": lambda value: [] if value in ["none", None]  else
                    eval(value) if value.find("[") >= 0 else
                    eval("[" + value + "]") },
            # Internal VM (not shown in qubes-manager, doesn't create appmenus entries
            "internal": { "default": False, 'attr': '_internal' },
            "vcpus": { "default": None },
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
                    else defaults["kernelopts"] },
            "mac": { "attr": "_mac", "default": None },
            "include_in_backups": { "default": True },
            "services": {
                "default": {},
                "func": lambda value: eval(str(value)) },
            "debug": { "default": False },
            "default_user": { "default": "user", "attr": "_default_user" },
            "qrexec_timeout": { "default": 60 },
            "autostart": { "default": False, "attr": "_autostart" },
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
            "_start_guid_first": { "func": lambda x: False },
            }

        ### Mark attrs for XML inclusion
        # Simple string attrs
        for prop in ['qid', 'uuid', 'name', 'dir_path', 'memory', 'maxmem',
            'pcidevs', 'vcpus', 'internal',\
            'uses_default_kernel', 'kernel', 'uses_default_kernelopts',\
            'kernelopts', 'services', 'installed_by_rpm',\
            'uses_default_netvm', 'include_in_backups', 'debug',\
            'qrexec_timeout', 'autostart',
            'backup_content', 'backup_size', 'backup_path' ]:
            attrs[prop]['save'] = lambda prop=prop: str(getattr(self, prop))
        # Simple paths
        for prop in ['conf_file', 'root_img', 'volatile_img', 'private_img']:
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

    def __basic_parse_xml_attr(self, value):
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
                   "or one of 'none', 'true', 'false')") % self.name
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

        # By default allow use all VCPUs
        if self.vcpus is None and not vmm.offline_mode:
            qubes_host = QubesHost()
            self.vcpus = qubes_host.no_cpus

        # Always set if meminfo-writer should be active or not
        if 'meminfo-writer' not in self.services:
            self.services['meminfo-writer'] = not (len(self.pcidevs) > 0)

        # Additionally force meminfo-writer disabled when VM have PCI devices
        if len(self.pcidevs) > 0:
            self.services['meminfo-writer'] = False

        # Some additional checks for template based VM
        if self.template is not None:
            if not self.template.is_template():
                print >> sys.stderr, "ERROR: template_qid={0} doesn't point to a valid TemplateVM".\
                    format(self.template.qid)
                return False
            self.template.appvms[self.qid] = self
        else:
            assert self.root_img is not None, "Missing root_img for standalone VM!"

        self.storage = defaults["storage_class"](self)
        if hasattr(self, 'kernels_dir'):
            self.storage.modules_img = os.path.join(self.kernels_dir,
                    "modules.img")
            self.storage.modules_img_rw = self.kernel is None

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
        else:
            return os.path.join(self.dir_path, (arg if arg is not None else default))

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
            os.symlink (new_label.icon_path, self.icon_path)
            subprocess.call(['sudo', 'xdg-icon-resource', 'forceupdate'])

        # fire hooks
        for hook in self.hooks_label_setter:
            hook(self, new_label)

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
        if self.is_running() and new_netvm is not None and not new_netvm.is_running():
            raise QubesException("Cannot dynamically attach to stopped NetVM")
        if self.netvm is not None:
            self.netvm.connected_vms.pop(self.qid)
            if self.is_running():
                self.detach_network()

                if hasattr(self.netvm, 'post_vm_net_detach'):
                    self.netvm.post_vm_net_detach(self)

        if new_netvm is None:
            if not self._do_not_reset_firewall:
                # Set also firewall to block all traffic as discussed in #370
                if os.path.exists(self.firewall_conf):
                    shutil.copy(self.firewall_conf, os.path.join(system_path["qubes_base_dir"],
                                "backup", "%s-firewall-%s.xml" % (self.name,
                                time.strftime('%Y-%m-%d-%H:%M:%S'))))
                self.write_firewall_conf({'allow': False, 'allowDns': False,
                        'allowIcmp': False, 'allowYumProxy': False, 'rules': []})
        else:
            new_netvm.connected_vms[self.qid]=self

        self._netvm = new_netvm

        if new_netvm is None:
            return

        if self.is_running():
            # refresh IP, DNS etc
            self.create_xenstore_entries(self.xid)
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
            for f in ('vmlinuz', 'modules.img'):
                if not os.path.exists(os.path.join(
                        system_path['qubes_kernels_base_dir'], new_value, f)):
                    raise QubesException(
                        "Kernel '%s' not properly installed: missing %s "
                        "file" % (new_value, f))
        self._kernel = new_value

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

    def verify_name(self, name):
        if not isinstance(self.__basic_parse_xml_attr(name), str):
            return False
        if len(name) > 31:
            return False
        return re.match(r"^[a-zA-Z][a-zA-Z0-9_-]*$", name) is not None

    def pre_rename(self, new_name):
        # fire hooks
        for hook in self.hooks_pre_rename:
            hook(self, new_name)

    def set_name(self, name):
        if self.is_running():
            raise QubesException("Cannot change name of running VM!")

        if not self.verify_name(name):
            raise QubesException("Invalid characters in VM name")

        if self.installed_by_rpm:
            raise QubesException("Cannot rename VM installed by RPM -- first clone VM and then use yum to remove package.")

        self.pre_rename(name)
        self.libvirt_domain.undefine()
        self._libvirt_domain = None
        self._qdb_connection.close()
        self._qdb_connection = None

        new_conf = os.path.join(self.dir_path, name + '.conf')
        if os.path.exists(self.conf_file):
            os.rename(self.conf_file, new_conf)
        old_dirpath = self.dir_path
        new_dirpath = os.path.join(os.path.dirname(self.dir_path), name)
        os.rename(old_dirpath, new_dirpath)
        self.dir_path = new_dirpath
        old_name = self.name
        self.name = name
        if self.private_img is not None:
            self.private_img = self.private_img.replace(old_dirpath, new_dirpath)
        if self.root_img is not None:
            self.root_img = self.root_img.replace(old_dirpath, new_dirpath)
        if self.volatile_img is not None:
            self.volatile_img = self.volatile_img.replace(old_dirpath, new_dirpath)
        if self.conf_file is not None:
            self.conf_file = new_conf.replace(old_dirpath, new_dirpath)
        if self.icon_path is not None:
            self.icon_path = self.icon_path.replace(old_dirpath, new_dirpath)
        if hasattr(self, 'kernels_dir') and self.kernels_dir is not None:
            self.kernels_dir = self.kernels_dir.replace(old_dirpath, new_dirpath)

        self._update_libvirt_domain()
        self.post_rename(old_name)

    def post_rename(self, old_name):
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
    def autostart(self):
        return self._autostart

    @autostart.setter
    def autostart(self, value):
        if value:
            retcode = subprocess.call(["sudo", "systemctl", "enable", "qubes-vm@%s.service" % self.name])
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
            if self.is_running():
                self._qdb_connection = QubesDB(self.name)
        return self._qdb_connection

    @property
    def xid(self):
        if self.libvirt_domain is None:
            return -1
        return self.libvirt_domain.ID()

    def get_xid(self):
        # obsoleted
        return self.xid

    def _update_libvirt_domain(self):
        domain_config = self.create_config_file()
        if self._libvirt_domain:
            self._libvirt_domain.undefine()
        self._libvirt_domain = vmm.libvirt_conn.defineXML(domain_config)
        self.uuid = uuid.UUID(bytes=self._libvirt_domain.UUID())

    @property
    def libvirt_domain(self):
        if self._libvirt_domain is not None:
            return self._libvirt_domain

        try:
            if self.uuid is not None:
                self._libvirt_domain = vmm.libvirt_conn.lookupByUUID(self.uuid.bytes)
            else:
                self._libvirt_domain = vmm.libvirt_conn.lookupByName(self.name)
                self.uuid = uuid.UUID(bytes=self._libvirt_domain.UUID())
        except libvirt.libvirtError:
            if libvirt.virGetLastError()[0] == libvirt.VIR_ERR_NO_DOMAIN:
                self._update_libvirt_domain()
            else:
                raise
        return self._libvirt_domain

    def get_uuid(self):
        # obsoleted
        return self.uuid

    def get_mem(self):
        if dry_run:
            return 666

        if not self.libvirt_domain.isActive():
            return 0
        return self.libvirt_domain.info()[1]

    def get_mem_static_max(self):
        if dry_run:
            return 666

        if self.libvirt_domain is None:
            return 0

        return self.libvirt_domain.maxMemory()

    def get_prefmem(self):
        # TODO: qmemman is still xen specific
        untrusted_meminfo_key = xs.read('', '/local/domain/%s/memory/meminfo'
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

        libvirt_domain = self.libvirt_domain
        if libvirt_domain and libvirt_domain.isActive():
            return libvirt_domain.getCPUStats(
                    libvirt.VIR_NODE_CPU_STATS_ALL_CPUS, 0)[0]['cpu_time']/10**9
        else:
            return 0

    def get_disk_utilization_root_img(self):
        return qubes.qubesutils.get_disk_usage(self.root_img)

    def get_root_img_sz(self):
        if not os.path.exists(self.root_img):
            return 0

        return os.path.getsize(self.root_img)

    def get_power_state(self):
        if dry_run:
            return "NA"

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

        return "NA"

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
        if self.libvirt_domain and self.libvirt_domain.isActive():
            return True
        else:
            return False

    def is_paused(self):
        if self.libvirt_domain and self.libvirt_domain.state() == libvirt.VIR_DOMAIN_PAUSED:
            return True
        else:
            return False

    def get_start_time(self):
        if not self.is_running():
            return None

        # TODO
        uuid = self.uuid

        start_time = vmm.xs.read('', "/vm/%s/start_time" % str(uuid))
        if start_time != '':
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
                                       '-inum', str(tz_info.st_ino)],
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
        for dev in vmm.xs.ls('', dev_basepath):
            # check if backend domain is alive
            backend_xid = int(vmm.xs.read('', '%s/%s/backend-id' % (dev_basepath, dev)))
            if backend_xid in vmm.libvirt_conn.listDomainsID():
                # check if device is still active
                if vmm.xs.read('', '%s/%s/state' % (dev_basepath, dev)) == '4':
                    continue
            # remove dead device
            vmm.xs.rm('', '%s/%s' % (dev_basepath, dev))

    def create_xenstore_entries(self, xid = None):
        if dry_run:
            return

        self.qdb.write("/name", self.name)
        self.qdb.write("/qubes-vm-type", self.type)
        self.qdb.write("/qubes-vm-updateable", str(self.updateable))

        if self.is_netvm():
            self.qdb.write("/qubes-netvm-gateway", self.gateway)
            self.qdb.write("/qubes-netvm-secondary-dns", self.secondary_dns)
            self.qdb.write("/qubes-netvm-netmask", self.netmask)
            self.qdb.write("/qubes-netvm-network", self.network)

        if self.netvm is not None:
            self.qdb.write("/qubes-ip", self.ip)
            self.qdb.write("/qubes-netmask", self.netvm.netmask)
            self.qdb.write("/qubes-gateway", self.netvm.gateway)
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

        # TODO: Currently whole qmemman is quite Xen-specific, so stay with
        # xenstore for it until decided otherwise
        if qmemman_present:
            vmm.xs.set_permissions('', '/local/domain/{0}/memory'.format(self.xid),
                    [{ 'dom': xid }])

        # fire hooks
        for hook in self.hooks_create_xenstore_entries:
            hook(self, xid=xid)

    def _format_net_dev(self, ip, mac, backend):
        template = "    <interface type='ethernet'>\n" \
                   "      <mac address='{mac}'/>\n" \
                   "      <ip address='{ip}'/>\n" \
                   "      <script path='vif-route-qubes'/>\n" \
                   "      <domain name='{backend}'/>\n" \
                   "    </interface>\n"
        return template.format(ip=ip, mac=mac, backend=backend)

    def _format_pci_dev(self, address):
        template = "    <hostdev type='pci' managed='yes'>\n" \
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
                fun=dev_match.group(3))

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
        if self.netvm is not None:
            args['ip'] = self.ip
            args['mac'] = self.mac
            args['gateway'] = self.netvm.gateway
            args['dns1'] = self.netvm.gateway
            args['dns2'] = self.secondary_dns
            args['netmask'] = self.netmask
            args['netdev'] = self._format_net_dev(self.ip, self.mac, self.netvm.name)
            args['disable_network1'] = '';
            args['disable_network2'] = '';
        else:
            args['ip'] = ''
            args['mac'] = ''
            args['gateway'] = ''
            args['dns1'] = ''
            args['dns2'] = ''
            args['netmask'] = ''
            args['netdev'] = ''
            args['disable_network1'] = '<!--';
            args['disable_network2'] = '-->';
        args.update(self.storage.get_config_params())
        if hasattr(self, 'kernelopts'):
            args['kernelopts'] = self.kernelopts
            if self.debug:
                print >> sys.stderr, "--> Debug mode: adding 'earlyprintk=xen' to kernel opts"
                args['kernelopts'] += ' earlyprintk=xen'

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
        os.symlink (self.label.icon_path, self.icon_path)

        # fire hooks
        for hook in self.hooks_create_on_disk:
            hook(self, verbose, source_template=source_template)

    def get_clone_attrs(self):
        attrs = ['kernel', 'uses_default_kernel', 'netvm', 'uses_default_netvm', \
            'memory', 'maxmem', 'kernelopts', 'uses_default_kernelopts', 'services', 'vcpus', \
            '_mac', 'pcidevs', 'include_in_backups', '_label', 'default_user']

        # fire hooks
        for hook in self.hooks_get_clone_attrs:
            attrs = hook(self, attrs)

        return attrs

    def clone_attrs(self, src_vm, fail_on_error=True):
        self._do_not_reset_firewall = True
        for prop in self.get_clone_attrs():
            try:
                setattr(self, prop, getattr(src_vm, prop))
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

        # fire hooks
        for hook in self.hooks_clone_disk_files:
            hook(self, src_vm, verbose)

    def verify_files(self):
        if dry_run:
            return

        self.storage.verify_files()

        if not os.path.exists (os.path.join(self.kernels_dir, 'vmlinuz')):
            raise QubesException (
                "VM kernel does not exists: {0}".\
                format(os.path.join(self.kernels_dir, 'vmlinuz')))

        if not os.path.exists (os.path.join(self.kernels_dir, 'initramfs')):
            raise QubesException (
                "VM initramfs does not exists: {0}".\
                format(os.path.join(self.kernels_dir, 'initramfs')))

        # fire hooks
        for hook in self.hooks_verify_files:
            hook(self)

        return True

    def remove_from_disk(self):
        if dry_run:
            return

        # fire hooks
        for hook in self.hooks_remove_from_disk:
            hook(self)

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
                fcntl.lockf(f, fcntl.LOCK_EX)
                tree.write(f, encoding="UTF-8", pretty_print=True)
                fcntl.lockf(f, fcntl.LOCK_UN)
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

        args = [system_path["qrexec_client_path"], "-d", str(self.xid), "%s:%s" % (user, command)]
        if localcmd is not None:
            args += [ "-l", localcmd]
        if filter_esc:
            args += ["-t"]
        if os.isatty(sys.stderr.fileno()):
            args += ["-T"]
        if passio:
            os.execv(system_path["qrexec_client_path"], args)
            exit(1)

        call_kwargs = {}
        if ignore_stderr:
            null = open("/dev/null", "w")
            call_kwargs['stderr'] = null

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
        if not wait:
            args += ["-e"]
        retcode = subprocess.call(args, **call_kwargs)
        if null:
            null.close()
        return retcode

    def run_service(self, service, source="dom0", user=None,
                    passio_popen =  False, input=None):
        if input and passio_popen:
            raise ValueError("'input' and 'passio_popen' cannot be used "
                             "together")
        if input:
            return self.run("QUBESRPC %s %s" % (service, source),
                        localcmd="echo %s" % input, user=user, wait=True)
        else:
            return self.run("QUBESRPC %s %s" % (service, source),
                        passio_popen=passio_popen, user=user, wait=True)

    def attach_network(self, verbose = False, wait = True, netvm = None):
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
        #self.run('echo $$ >> /tmp/qubes-session-waiter; [ ! -f /tmp/qubes-session-env ] && exec sleep 365d', ignore_stderr=True, gui=False, wait=True)

        # Note : User root is redefined to SYSTEM in the Windows agent code
        p = self.run('QUBESRPC qubes.WaitForSession none', user="root", passio_popen=True, gui=False, wait=True)
        p.communicate(input=self.default_user)

    def start_guid(self, verbose = True, notify_function = None,
            extra_guid_args=[], before_qrexec=False):
        if verbose:
            print >> sys.stderr, "--> Starting Qubes GUId..."

        guid_cmd = [system_path["qubes_guid_path"],
            "-d", str(xid), "-N", self.name,
            "-c", self.label.color,
            "-i", self.label.icon_path,
            "-l", str(self.label.index)]
        guid_cmd += extra_guid_args
        if self.debug:
            guid_cmd += ['-v', '-v']
        elif not verbose:
            guid_cmd += ['-q']
        retcode = subprocess.call (guid_cmd)
        if (retcode != 0) :
            raise QubesException("Cannot start qubes-guid!")

        if verbose:
            print >> sys.stderr, "--> Sending monitor layout..."

        try:
            subprocess.call([system_path["monitor_layout_notify_cmd"], self.name])
        except Exception as e:
            print >>sys.stderr, "ERROR: %s" % e

        if verbose:
            print >> sys.stderr, "--> Waiting for qubes-session..."

        self.wait_for_session(notify_function)

    def start_qrexec_daemon(self, verbose = False, notify_function = None):
        if verbose:
            print >> sys.stderr, "--> Starting the qrexec daemon..."
        qrexec_args = [str(self.xid), self.name, self.default_user]
        if not verbose:
            qrexec_args.insert(0, "-q")
        qrexec_env = os.environ
        qrexec_env['QREXEC_STARTUP_TIMEOUT'] = str(self.qrexec_timeout)
        retcode = subprocess.call ([system_path["qrexec_daemon_path"]] +
                                   qrexec_args, env=qrexec_env)
        if (retcode != 0) :
            raise OSError ("Cannot execute qrexec-daemon!")

    def start_qubesdb(self):
        retcode = subprocess.call ([
            system_path["qubesdb_daemon_path"],
            str(self.xid),
            self.name])
        if retcode != 0:
            self.force_shutdown()
            raise OSError("ERROR: Cannot execute qubesdb-daemon!")

    def start(self, verbose = False, preparing_dvm = False, start_guid = True,
            notify_function = None, mem_required = None):
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

        if mem_required is None:
            mem_required = int(self.memory) * 1024 * 1024
        if qmemman_present:
            qmemman_client = QMemmanClient()
            try:
                got_memory = qmemman_client.request_memory(mem_required)
            except IOError as e:
                raise IOError("ERROR: Failed to connect to qmemman: %s" % str(e))
            if not got_memory:
                qmemman_client.close()
                raise MemoryError ("ERROR: insufficient memory to start VM '%s'" % self.name)

        # Bind pci devices to pciback driver
        for pci in self.pcidevs:
            nd = vmm.libvirt_conn.nodeDeviceLookupByName('pci_0000_' + pci.replace(':','_').replace('.','_'))
            nd.dettach()

        self.libvirt_domain.createWithFlags(libvirt.VIR_DOMAIN_START_PAUSED)

        if verbose:
            print >> sys.stderr, "--> Starting Qubes DB..."
        self.start_qubesdb()

        xid = self.xid

        if preparing_dvm:
            self.services['qubes-dvm'] = True
        if verbose:
            print >> sys.stderr, "--> Setting Qubes DB info for the VM..."
        self.create_xenstore_entries(xid)

        qvm_collection = QubesVmCollection()
        qvm_collection.lock_db_for_reading()
        qvm_collection.load()
        qvm_collection.unlock_db()

        if verbose:
            print >> sys.stderr, "--> Updating firewall rules..."
        for vm in qvm_collection.values():
            if vm.is_proxyvm() and vm.is_running():
                vm.write_iptables_xenstore_entry()

        # fire hooks
        for hook in self.hooks_start:
            hook(self, verbose = verbose, preparing_dvm =  preparing_dvm,
                    start_guid = start_guid, notify_function = notify_function)

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

        if self._start_guid_first and start_guid and not preparing_dvm and os.path.exists('/var/run/shm.id'):
            self.start_guid(verbose=verbose, notify_function=notify_function, before_qrexec=True)

        if not preparing_dvm:
            self.start_qrexec_daemon(verbose=verbose,notify_function=notify_function)

        if start_guid and not preparing_dvm and os.path.exists('/var/run/shm.id'):
            self.start_guid(verbose=verbose, notify_function=notify_function)

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
        if dry_run:
            return

        if not self.is_running():
            raise QubesException ("VM already stopped!")

        self.libvirt_domain.shutdown()

    def force_shutdown(self, xid = None):
        if dry_run:
            return

        if not self.is_running() and not self.is_paused():
            raise QubesException ("VM already stopped!")

        self.libvirt_domain.destroy()

    def suspend(self):
        # TODO!!!
        if dry_run:
            return

        if not self.is_running() and not self.is_paused():
            raise QubesException ("VM already stopped!")

        if len (self.pcidevs) > 0:
            raise NotImplementedError
        else:
            self.pause()

    def resume(self):
        # TODO!!!
        if dry_run:
            return

        if self.get_power_state() == "Suspended":
            raise NotImplementedError
        else:
            self.unpause()

    def pause(self):
        if dry_run:
            return

        self.libvirt_domain.suspend()

    def unpause(self):
        if dry_run:
            return

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
