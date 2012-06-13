#!/usr/bin/python2.6
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

import sys
import stat
import os
import os.path
import subprocess
import xml.etree.ElementTree
import xml.parsers.expat
import fcntl
import re
import shutil
import uuid
import time
from datetime import datetime
from qmemman_client import QMemmanClient

# Do not use XenAPI or create/read any VM files
# This is for testing only!
dry_run = False
#dry_run = True


if not dry_run:
    import xen.lowlevel.xc
    import xen.lowlevel.xl
    import xen.lowlevel.xs


qubes_guid_path = "/usr/bin/qubes_guid"
qrexec_daemon_path = "/usr/lib/qubes/qrexec_daemon"
qrexec_client_path = "/usr/lib/qubes/qrexec_client"
qubes_clipd_path = "/usr/bin/qclipd"

qubes_base_dir   = "/var/lib/qubes"

qubes_appvms_dir = qubes_base_dir + "/appvms"
qubes_templates_dir = qubes_base_dir + "/vm-templates"
qubes_servicevms_dir = qubes_base_dir + "/servicevms"
qubes_store_filename = qubes_base_dir + "/qubes.xml"
qubes_kernels_base_dir = qubes_base_dir + "/vm-kernels"

qubes_max_qid = 254
qubes_max_netid = 254
vm_default_netmask = "255.255.255.0"

default_root_img = "root.img"
default_rootcow_img = "root-cow.img"
default_volatile_img = "volatile.img"
default_clean_volatile_img = "clean-volatile.img.tar"
default_private_img = "private.img"
default_appmenus_templates_subdir = "apps.templates"
default_appmenus_template_templates_subdir = "apps-template.templates"
default_kernels_subdir = "kernels"
default_firewall_conf_file = "firewall.xml"
default_memory = 400
default_kernelopts = ""
default_kernelopts_pcidevs = "iommu=soft swiotlb=2048"

default_hvm_disk_size = 20*1024*1024*1024
default_hvm_private_img_size = 2*1024*1024*1024
default_hvm_memory = 512

config_template_pv = '/usr/share/qubes/vm-template.conf'
config_template_hvm = '/usr/share/qubes/vm-template-hvm.conf'

start_appmenu_template = '/usr/share/qubes/qubes-start.desktop'

qubes_whitelisted_appmenus = 'whitelisted-appmenus.list'

dom0_update_check_interval = 6*3600
updates_stat_file = 'updates.stat'

# how long (in sec) to wait for VMs to shutdown
# before killing them (when used qvm-run with --wait option)
shutdown_counter_max = 60

# do not allow to start a new AppVM if Dom0 mem was to be less than this
dom0_min_memory = 700*1024*1024

# We need this global reference, as each instance of QubesVm
# must be able to ask Dom0 VM about how much memory it currently has...
dom0_vm = None

qubes_appmenu_create_cmd = "/usr/lib/qubes/create_apps_for_appvm.sh"
qubes_appmenu_remove_cmd = "/usr/lib/qubes/remove_appvm_appmenus.sh"
qubes_pciback_cmd = '/usr/lib/qubes/unbind_pci_device.sh'

yum_proxy_ip = '10.137.255.254'
yum_proxy_port = '8082'

class QubesException (Exception) : pass

if not dry_run:
    xc = xen.lowlevel.xc.xc()
    xs = xen.lowlevel.xs.xs()
    xl_ctx = xen.lowlevel.xl.ctx()

class QubesHost(object):
    def __init__(self):
        self.physinfo = xc.physinfo()

        self.xen_total_mem = long(self.physinfo['total_memory'])
        self.xen_no_cpus = self.physinfo['nr_cpus']

#        print "QubesHost: total_mem  = {0}B".format (self.xen_total_mem)
#        print "QubesHost: free_mem   = {0}".format (self.get_free_xen_memory())
#        print "QubesHost: total_cpus = {0}".format (self.xen_no_cpus)

    @property
    def memory_total(self):
        return self.xen_total_mem

    @property
    def no_cpus(self):
        return self.xen_no_cpus

    def get_free_xen_memory(self):
        ret = self.physinfo['free_memory']
        return long(ret)

    # measure cpu usage for all domains at once
    def measure_cpu_usage(self, previous=None, previous_time = None, wait_time=1):
        if previous is None:
            previous_time = time.time()
            previous = {}
            info = xc.domain_getinfo(0, qubes_max_qid)
            for vm in info:
                previous[vm['domid']] = {}
                previous[vm['domid']]['cpu_time'] = vm['cpu_time']/vm['online_vcpus']
                previous[vm['domid']]['cpu_usage'] = 0
            time.sleep(wait_time)

        current_time = time.time()
        current = {}
        info = xc.domain_getinfo(0, qubes_max_qid)
        for vm in info:
            current[vm['domid']] = {}
            current[vm['domid']]['cpu_time'] = vm['cpu_time']/max(vm['online_vcpus'],1)
            if vm['domid'] in previous.keys():
                current[vm['domid']]['cpu_usage'] = \
                    float(current[vm['domid']]['cpu_time'] - previous[vm['domid']]['cpu_time']) \
                    / long(1000**3) / (current_time-previous_time) * 100
                if current[vm['domid']]['cpu_usage'] < 0:
                    # VM has been rebooted
                    current[vm['domid']]['cpu_usage'] = 0
            else:
                current[vm['domid']]['cpu_usage'] = 0

        return (current_time, current)

class QubesVmLabel(object):
    def __init__(self, name, index, color = None, icon = None):
        self.name = name
        self.index = index
        self.color = color if color is not None else name
        self.icon = icon if icon is not None else name
        self.icon_path = "/usr/share/qubes/icons/" + self.icon + ".png"

# Globally defined lables
QubesVmLabels = {
    "red" : QubesVmLabel ("red", 1),
    "orange" : QubesVmLabel ("orange", 2),
    "yellow" : QubesVmLabel ("yellow", 3),
    "green" : QubesVmLabel ("green", 4, color="0x5fa05e"),
    "gray" : QubesVmLabel ("gray", 5),
    "blue" : QubesVmLabel ("blue", 6),
    "purple" : QubesVmLabel ("purple", 7, color="0xb83374"),
    "black" : QubesVmLabel ("black", 8),
}

QubesDispVmLabels = {
    "red" : QubesVmLabel ("red", 1, icon="dispvm-red"),
    "orange" : QubesVmLabel ("orange", 2, icon="dispvm-orange"),
    "yellow" : QubesVmLabel ("yellow", 3, icon="dispvm-yellow"),
    "green" : QubesVmLabel ("green", 4, color="0x5fa05e", icon="dispvm-green"),
    "gray" : QubesVmLabel ("gray", 5, icon="dispvm-gray"),
    "blue" : QubesVmLabel ("blue", 6, icon="dispvm-blue"),
    "purple" : QubesVmLabel ("purple", 7, color="0xb83374", icon="dispvm-purple"),
    "black" : QubesVmLabel ("black", 8, icon="dispvm-black"),
}

default_appvm_label = QubesVmLabels["red"]
default_template_label = QubesVmLabels["gray"]
default_servicevm_label = QubesVmLabels["red"]

class QubesVm(object):
    """
    A representation of one Qubes VM
    Only persistent information are stored here, while all the runtime
    information, e.g. Xen dom id, etc, are to be retrieved via Xen API
    Note that qid is not the same as Xen's domid!
    """

    def _get_attrs_config(self):
        """ Object attributes for serialization/deserialization
            inner dict keys:
             - order: initialization order (to keep dependency intact)
                      attrs without order will be evaluated at the end
             - default: default value used when attr not given to object constructor
             - attr: set value to this attribute instead of parameter name
             - eval: assign result of this expression instead of value directly;
                     local variable 'value' contains attribute value (or default if it was not given)
             - save: use evaluation result as value for XML serialization; only attrs with 'save' key will be saved in XML
             - save_skip: if present and evaluates to true, attr will be omitted in XML
             - save_attr: save to this XML attribute instead of parameter name
             """

        attrs = {
            # __qid cannot be accessed by setattr, so must be set manually in __init__
            "qid": { "attr": "_qid", "order": 0 },
            "name": { "order": 1 },
            "dir_path": { "default": None, "order": 2 },
            "conf_file": { "eval": 'self.absolute_path(value, self.name + ".conf")', 'order': 3 },
            # order >= 10: have base attrs set
            "root_img": { "eval": 'self.absolute_path(value, default_root_img)', 'order': 10 },
            "private_img": { "eval": 'self.absolute_path(value, default_private_img)', 'order': 10 },
            "volatile_img": { "eval": 'self.absolute_path(value, default_volatile_img)', 'order': 10 },
            "firewall_conf": { "eval": 'self.absolute_path(value, default_firewall_conf_file)', 'order': 10 },
            "installed_by_rpm": { "default": False, 'order': 10 },
            "template": { "default": None, 'order': 10 },
            # order >= 20: have template set
            "uses_default_netvm": { "default": True, 'order': 20 },
            "netvm": { "default": None, "attr": "_netvm", 'order': 20 },
            "label": { "attr": "_label", "default": QubesVmLabels["red"], 'order': 20 },
            "memory": { "default": default_memory, 'order': 20, "eval": "int(value)" },
            "maxmem": { "default": None, 'order': 25, "eval": "int(value) if value else None" },
            "pcidevs": { "default": '[]', 'order': 25, "eval": \
                '[] if value in ["none", None] else eval(value) if value.find("[") >= 0 else eval("[" + value + "]")'  },
            # Internal VM (not shown in qubes-manager, doesn't create appmenus entries
            "internal": { "default": False },
            "vcpus": { "default": None },
            "kernel": { "default": None, 'order': 30 },
            "uses_default_kernel": { "default": True, 'order': 30 },
            "uses_default_kernelopts": { "default": True, 'order': 30 },
            "kernelopts": { "default": "", 'order': 31, "eval": \
                'value if not self.uses_default_kernelopts else default_kernelopts_pcidevs if len(self.pcidevs) > 0 else default_kernelopts' },
            "mac": { "attr": "_mac", "default": None },
            "include_in_backups": { "default": True },
            "services": { "default": {}, "eval": "eval(str(value))" },
            "debug": { "default": False },
            ##### Internal attributes - will be overriden in __init__ regardless of args
            "appmenus_templates_dir": { "eval": \
                'self.dir_path + "/" + default_appmenus_templates_subdir if self.updateable else ' + \
                'self.template.appmenus_templates_dir if self.template is not None else None' },
            "config_file_template": { "eval": "config_template_pv" },
            "icon_path": { "eval": 'self.dir_path + "/icon.png" if self.dir_path is not None else None' },
            "kernels_dir": { 'eval': 'qubes_kernels_base_dir + "/" + self.kernel if self.kernel is not None else ' + \
                # for backward compatibility (or another rare case): kernel=None -> kernel in VM dir
                'self.dir_path + "/" + default_kernels_subdir' },
            }

        ### Mark attrs for XML inclusion
        # Simple string attrs
        for prop in ['qid', 'name', 'dir_path', 'memory', 'maxmem', 'pcidevs', 'vcpus', 'internal',\
            'uses_default_kernel', 'kernel', 'uses_default_kernelopts',\
            'kernelopts', 'services', 'installed_by_rpm',\
            'uses_default_netvm', 'include_in_backups', 'debug' ]:
            attrs[prop]['save'] = 'str(self.%s)' % prop
        # Simple paths
        for prop in ['conf_file', 'root_img', 'volatile_img', 'private_img']:
            attrs[prop]['save'] = 'self.relative_path(self.%s)' % prop
            attrs[prop]['save_skip'] = 'self.%s is None' % prop

        attrs['mac']['save'] = 'str(self._mac)'
        attrs['mac']['save_skip'] = 'self._mac is None'

        attrs['netvm']['save'] = 'str(self.netvm.qid) if self.netvm is not None else "none"'
        attrs['netvm']['save_attr'] = "netvm_qid"
        attrs['template']['save'] = 'str(self.template.qid) if self.template else "none"'
        attrs['template']['save_attr'] = "template_qid"
        attrs['label']['save'] = 'self.label.name'

        return attrs

    def __init__(self, **kwargs):

        attrs = self._get_attrs_config()
        for attr_name in sorted(attrs, key=lambda _x: attrs[_x]['order'] if 'order' in attrs[_x] else 1000):
            attr_config = attrs[attr_name]
            attr = attr_name
            if 'attr' in attr_config:
                attr = attr_config['attr']
            value = None
            if attr_name not in kwargs:
                if 'default' in attr_config:
                    value = attr_config['default']
            else:
                value = kwargs[attr_name]
            if 'eval' in attr_config:
                setattr(self, attr, eval(attr_config['eval']))
            else:
                #print "setting %s to %s" % (attr, value)
                setattr(self, attr, value)

        #Init private attrs
        self.__qid = self._qid

        assert self.__qid < qubes_max_qid, "VM id out of bounds!"
        assert self.name is not None

        if self.netvm is not None:
            self.netvm.connected_vms[self.qid] = self

        # Not in generic way to not create QubesHost() to frequently
        if self.maxmem is None:
            qubes_host = QubesHost()
            total_mem_mb = qubes_host.memory_total/1024
            self.maxmem = total_mem_mb/2

        # By default allow use all VCPUs
        if self.vcpus is None:
            qubes_host = QubesHost()
            self.vcpus = qubes_host.no_cpus

        # Always set if meminfo-writer should be active or not
        if 'meminfo-writer' not in self.services:
            self.services['meminfo-writer'] = not (len(self.pcidevs) > 0)

        # Some additional checks for template based VM
        if self.template is not None:
            if not self.template.is_template():
                print >> sys.stderr, "ERROR: template_qid={0} doesn't point to a valid TemplateVM".\
                    format(self.template.qid)
                return False
            self.template.appvms[self.qid] = self
        else:
            assert self.root_img is not None, "Missing root_img for standalone VM!"

        self.xid = -1
        self.xid = self.get_xid()

    def absolute_path(self, arg, default):
        if arg is not None and os.path.isabs(arg):
            return arg
        else:
            return self.dir_path + "/" + (arg if arg is not None else default)

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

    @property
    def netvm(self):
        return self._netvm

    # Don't know how properly call setter from base class, so workaround it...
    @netvm.setter
    def netvm(self, new_netvm):
        self._set_netvm(new_netvm)

    def _set_netvm(self, new_netvm):
        if self.is_running() and new_netvm is not None and not new_netvm.is_running():
            raise QubesException("Cannot dynamically attach to stopped NetVM")
        if self.netvm is not None:
            self.netvm.connected_vms.pop(self.qid)
            if self.is_running():
                subprocess.call(["xl", "network-detach", self.name, "0"], stderr=subprocess.PIPE)
                if hasattr(self.netvm, 'post_vm_net_detach'):
                    self.netvm.post_vm_net_detach(self)

        if new_netvm is None:
            # Set also firewall to block all traffic as discussed in #370
            if os.path.exists(self.firewall_conf):
                shutil.copy(self.firewall_conf, "%s/backup/%s-firewall-%s.xml"
                        % (qubes_base_dir, self.name, time.strftime('%Y-%m-%d-%H:%M:%S')))
            self.write_firewall_conf({'allow': False, 'allowDns': False,
                    'allowIcmp': False, 'allowYumProxy': False, 'rules': []})
        else:
            new_netvm.connected_vms[self.qid]=self

        self._netvm = new_netvm

        if new_netvm is None:
            return

        if self.is_running():
            # refresh IP, DNS etc
            self.create_xenstore_entries()
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
    def updateable(self):
        return self.template is None

    # Leaved for compatibility
    def is_updateable(self):
        return self.updateable

    def is_networked(self):
        if self.is_netvm():
            return True

        if self.netvm is not None:
            return True
        else:
            return False

    def pre_rename(self, new_name):
        pass

    def set_name(self, name):
        if self.is_running():
            raise QubesException("Cannot change name of running VM!")

        self.pre_rename(name)

        new_conf = "%s/%s.conf" % (self.dir_path, name)
        if os.path.exists(self.conf_file):
            os.rename(self.conf_file, "%s/%s.conf" % (self.dir_path, name))
        old_dirpath = self.dir_path
        new_dirpath = os.path.dirname(self.dir_path) + '/' + name
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
        if self.appmenus_templates_dir is not None:
            self.appmenus_templates_dir = self.appmenus_templates_dir.replace(old_dirpath, new_dirpath)
        if self.icon_path is not None:
            self.icon_path = self.icon_path.replace(old_dirpath, new_dirpath)
        if hasattr(self, 'kernels_dir') and self.kernels_dir is not None:
            self.kernels_dir = self.kernels_dir.replace(old_dirpath, new_dirpath)

        self.post_rename(old_name)

    def post_rename(self, old_name):
        pass

    def is_template(self):
        return isinstance(self, QubesTemplateVm)

    def is_appvm(self):
        return isinstance(self, QubesAppVm)

    def is_netvm(self):
        return isinstance(self, QubesNetVm)

    def is_proxyvm(self):
        return isinstance(self, QubesProxyVm)

    def is_disposablevm(self):
        return isinstance(self, QubesDisposableVm)

    def get_xl_dominfo(self):
        if dry_run:
            return

        domains = xl_ctx.list_domains()
        for dominfo in domains:
            domname = xl_ctx.domid_to_name(dominfo.domid)
            if domname == self.name:
                return dominfo
        return None

    def get_xc_dominfo(self):
        if dry_run:
            return

        start_xid = self.xid
        if start_xid < 0:
            start_xid = 0
        try:
            domains = xc.domain_getinfo(start_xid, qubes_max_qid)
        except xen.lowlevel.xc.Error:
            return None

        for dominfo in domains:
            domname = xl_ctx.domid_to_name(dominfo['domid'])
            if domname == self.name:
                return dominfo
        return None

    def get_xid(self):
        if dry_run:
            return 666

        dominfo = self.get_xc_dominfo()
        if dominfo:
            self.xid = dominfo['domid']
            return self.xid
        else:
            return -1

    def get_uuid(self):

        dominfo = self.get_xl_dominfo()
        if dominfo:
            vmuuid = uuid.UUID(''.join('%02x' % b for b in dominfo.uuid))
            return vmuuid
        else:
            return None

    def get_mem(self):
        if dry_run:
            return 666

        dominfo = self.get_xc_dominfo()
        if dominfo:
            return dominfo['mem_kb']
        else:
            return 0

    def get_mem_static_max(self):
        if dry_run:
            return 666

        dominfo = self.get_xc_dominfo()
        if dominfo:
            return dominfo['maxmem_kb']
        else:
            return 0

    def get_per_cpu_time(self):
        if dry_run:
            import random
            return random.random() * 100

        dominfo = self.get_xc_dominfo()
        if dominfo:
            return dominfo['cpu_time']/dominfo['online_vcpus']
        else:
            return 0

    def get_disk_utilization_root_img(self):
        if not os.path.exists(self.root_img):
            return 0

        return self.get_disk_usage(self.root_img)

    def get_root_img_sz(self):
        if not os.path.exists(self.root_img):
            return 0

        return os.path.getsize(self.root_img)

    def get_power_state(self):
        if dry_run:
            return "NA"

        dominfo = self.get_xc_dominfo()
        if dominfo:
            if dominfo['paused']:
                return "Paused"
            elif dominfo['crashed']:
                return "Crashed"
            elif dominfo['shutdown']:
                return "Halting"
            elif dominfo['dying']:
                return "Dying"
            else:
                if not self.is_fully_usable():
                    return "Transient"
                else:
                    return "Running"
        else:
            return 'Halted'

        return "NA"

    def is_guid_running(self):
        xid = self.get_xid()
        if xid < 0:
            return False
        if not os.path.exists('/var/run/qubes/guid_running.%d' % xid):
            return False
        return True

    def is_fully_usable(self):
        # Running gui-daemon implies also VM running
        if not self.is_guid_running():
            return False
        # currently qrexec daemon doesn't cleanup socket in /var/run/qubes, so
        # it can be left from some other VM
        return True

    def is_running(self):
        # in terms of Xen and internal logic - starting VM is running
        if self.get_power_state() in ["Running", "Transient"]:
            return True
        else:
            return False

    def is_paused(self):
        if self.get_power_state() == "Paused":
            return True
        else:
            return False

    def get_start_time(self):
        if not self.is_running():
            return None

        dominfo = self.get_xl_dominfo()

        uuid = self.get_uuid()

        start_time = xs.read('', "/vm/%s/start_time" % str(uuid))
        if start_time != '':
            return datetime.fromtimestamp(float(start_time))
        else:
            return None

    def is_outdated(self):
        # Makes sense only on VM based on template
        if self.template is None:
            return False

        if not self.is_running():
            return False

        rootimg_inode = os.stat(self.template.root_img)
        rootcow_inode = os.stat(self.template.rootcow_img)

        current_dmdev = "/dev/mapper/snapshot-{0:x}:{1}-{2:x}:{3}".format(
                rootimg_inode[2], rootimg_inode[1],
                rootcow_inode[2], rootcow_inode[1])

        # Don't know why, but 51712 is xvda
        #  backend node name not available through xenapi :(
        used_dmdev = xs.read('', "/local/domain/0/backend/vbd/{0}/51712/node".format(self.get_xid()))

        return used_dmdev != current_dmdev

    def get_disk_usage(self, file_or_dir):
        if not os.path.exists(file_or_dir):
            return 0
        p = subprocess.Popen (["du", "-s", "--block-size=1", file_or_dir],
                              stdout=subprocess.PIPE)
        result = p.communicate()
        m = re.match(r"^(\d+)\s.*", result[0])
        sz = int(m.group(1)) if m is not None else 0
        return sz

    def get_disk_utilization(self):
        return self.get_disk_usage(self.dir_path)

    def get_disk_utilization_private_img(self):
        return self.get_disk_usage(self.private_img)

    def get_private_img_sz(self):
        if not os.path.exists(self.private_img):
            return 0

        return os.path.getsize(self.private_img)

    def resize_private_img(self, size):
        assert size >= self.get_private_img_sz(), "Cannot shrink private.img"

        f_private = open (self.private_img, "a+b")
        f_private.truncate (size)
        f_private.close ()

        retcode = 0
        if self.is_running():
            # find loop device
            p = subprocess.Popen (["sudo", "losetup", "--associated", self.private_img],
                    stdout=subprocess.PIPE)
            result = p.communicate()
            m = re.match(r"^(/dev/loop\d+):\s", result[0])
            if m is None:
                raise QubesException("ERROR: Cannot find loop device!")

            loop_dev = m.group(1)

            # resize loop device
            subprocess.check_call(["sudo", "losetup", "--set-capacity", loop_dev])

            retcode = self.run("root:while [ \"`blockdev --getsize64 /dev/xvdb`\" -lt {0} ]; do ".format(size) +
                "head /dev/xvdb > /dev/null; sleep 0.2; done; resize2fs /dev/xvdb", wait=True)
        else:
            retcode = subprocess.check_call(["sudo", "resize2fs", "-f", self.private_img])
        if retcode != 0:
            raise QubesException("resize2fs failed")


    # FIXME: should be outside of QubesVM?
    def get_timezone(self):
        clock_config = open('/etc/sysconfig/clock', "r")
        clock_config_lines = clock_config.readlines()
        clock_config.close()
        zone_re = re.compile(r'^ZONE="(.*)"')
        for line in clock_config_lines:
            line_match = zone_re.match(line)
            if line_match:
                return line_match.group(1)

        return None

    def cleanup_vifs(self):
        """
        Xend does not remove vif when backend domain is down, so we must do it
        manually
        """

        if not self.is_running():
            return

        dev_basepath = '/local/domain/%d/device/vif' % self.xid
        for dev in xs.ls('', dev_basepath):
            # check if backend domain is alive
            backend_xid = int(xs.read('', '%s/%s/backend-id' % (dev_basepath, dev)))
            if xl_ctx.domid_to_name(backend_xid) is not None:
                # check if device is still active
                if xs.read('', '%s/%s/state' % (dev_basepath, dev)) == '4':
                    continue
            # remove dead device
            xs.rm('', '%s/%s' % (dev_basepath, dev))

    def create_xenstore_entries(self, xid = None):
        if dry_run:
            return

        if xid is None:
            xid = self.xid

        domain_path = xs.get_domain_path(xid)

        # Set Xen Store entires with VM networking info:

        xs.write('', "{0}/qubes_vm_type".format(domain_path),
                self.type)
        xs.write('', "{0}/qubes_vm_updateable".format(domain_path),
                str(self.updateable))

        if self.is_netvm():
            xs.write('',
                    "{0}/qubes_netvm_gateway".format(domain_path),
                    self.gateway)
            xs.write('',
                    "{0}/qubes_netvm_secondary_dns".format(domain_path),
                    self.secondary_dns)
            xs.write('',
                    "{0}/qubes_netvm_netmask".format(domain_path),
                    self.netmask)
            xs.write('',
                    "{0}/qubes_netvm_network".format(domain_path),
                    self.network)

        if self.netvm is not None:
            xs.write('', "{0}/qubes_ip".format(domain_path), self.ip)
            xs.write('', "{0}/qubes_netmask".format(domain_path),
                    self.netvm.netmask)
            xs.write('', "{0}/qubes_gateway".format(domain_path),
                    self.netvm.gateway)
            xs.write('',
                    "{0}/qubes_secondary_dns".format(domain_path),
                    self.netvm.secondary_dns)

        tzname = self.get_timezone()
        if tzname:
             xs.write('',
                     "{0}/qubes-timezone".format(domain_path),
                     tzname)

        for srv in self.services.keys():
            # convert True/False to "1"/"0"
            xs.write('', "{0}/qubes-service/{1}".format(domain_path, srv),
                    str(int(self.services[srv])))

        xs.write('',
                "{0}/qubes-block-devices".format(domain_path),
                '')

        xs.write('', "{0}/qubes-debug-mode".format(domain_path),
                str(int(self.debug)))

        # Fix permissions
        xs.set_permissions('', '{0}/device'.format(domain_path),
                [{ 'dom': xid }])
        xs.set_permissions('', '{0}/memory'.format(domain_path),
                [{ 'dom': xid }])
        xs.set_permissions('', '{0}/qubes-block-devices'.format(domain_path),
                [{ 'dom': xid }])

    def get_rootdev(self, source_template=None):
        if self.template:
            return "'script:snapshot:{dir}/root.img:{dir}/root-cow.img,xvda,r',".format(dir=self.template.dir_path)
        else:
            return "'script:file:{dir}/root.img,xvda,w',".format(dir=self.dir_path)

    def get_config_params(self, source_template=None):
        args = {}
        args['name'] = self.name
        if hasattr(self, 'kernels_dir'):
            args['kerneldir'] = self.kernels_dir
        args['vmdir'] = self.dir_path
        args['pcidev'] = str(self.pcidevs).strip('[]')
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
            args['netdev'] = "'mac={mac},script=/etc/xen/scripts/vif-route-qubes,ip={ip}".format(ip=self.ip, mac=self.mac)
            if self.netvm.qid != 0:
                args['netdev'] += ",backend={0}".format(self.netvm.name)
            args['netdev'] += "'"
        else:
            args['ip'] = ''
            args['mac'] = ''
            args['gateway'] = ''
            args['dns1'] = ''
            args['dns2'] = ''
            args['netmask'] = ''
            args['netdev'] = ''
        args['rootdev'] = self.get_rootdev(source_template=source_template)
        args['privatedev'] = "'script:file:{dir}/private.img,xvdb,w',".format(dir=self.dir_path)
        args['volatiledev'] = "'script:file:{dir}/volatile.img,xvdc,w',".format(dir=self.dir_path)
        if hasattr(self, 'kernel'):
            modulesmode='r'
            if self.updateable and self.kernel is None:
                modulesmode='w'
            args['otherdevs'] = "'script:file:{dir}/modules.img,xvdd,{mode}',".format(dir=self.kernels_dir, mode=modulesmode)
        if hasattr(self, 'kernelopts'):
            args['kernelopts'] = self.kernelopts
            if self.debug:
                print >> sys.stderr, "--> Debug mode: adding 'earlyprintk=xen' to kernel opts"
                args['kernelopts'] += ' earlyprintk=xen'

        return args

    @property
    def uses_custom_config(self):
        return self.conf_file != self.absolute_path(self.name + ".conf", None)

    def create_config_file(self, file_path = None, source_template = None, prepare_dvm = False):
        if file_path is None:
            file_path = self.conf_file
            if self.uses_custom_config:
                return
        if source_template is None:
            source_template = self.template

        f_conf_template = open(self.config_file_template, 'r')
        conf_template = f_conf_template.read()
        f_conf_template.close()

        template_params = self.get_config_params(source_template)
        if prepare_dvm:
            template_params['name'] = '%NAME%'
            template_params['privatedev'] = ''
            template_params['netdev'] = re.sub(r"ip=[0-9.]*", "ip=%IP%", template_params['netdev'])
        conf_appvm = open(file_path, "w")

        conf_appvm.write(conf_template.format(**template_params))
        conf_appvm.close()

    def create_on_disk(self, verbose, source_template = None):
        if source_template is None:
            source_template = self.template
        assert source_template is not None

        if dry_run:
            return

        if verbose:
            print >> sys.stderr, "--> Creating directory: {0}".format(self.dir_path)
        os.mkdir (self.dir_path)

        if verbose:
            print >> sys.stderr, "--> Creating the VM config file: {0}".format(self.conf_file)

        self.create_config_file(source_template = source_template)

        template_priv = source_template.private_img
        if verbose:
            print >> sys.stderr, "--> Copying the template's private image: {0}".\
                    format(template_priv)

        # We prefer to use Linux's cp, because it nicely handles sparse files
        retcode = subprocess.call (["cp", template_priv, self.private_img])
        if retcode != 0:
            raise IOError ("Error while copying {0} to {1}".\
                           format(template_priv, self.private_img))

        if os.path.exists(source_template.dir_path + '/vm-' + qubes_whitelisted_appmenus):
            if verbose:
                print >> sys.stderr, "--> Creating default whitelisted apps list: {0}".\
                    format(self.dir_path + '/' + qubes_whitelisted_appmenus)
            shutil.copy(source_template.dir_path + '/vm-' + qubes_whitelisted_appmenus,
                    self.dir_path + '/' + qubes_whitelisted_appmenus)

        if self.updateable:
            template_root = source_template.root_img
            if verbose:
                print >> sys.stderr, "--> Copying the template's root image: {0}".\
                        format(template_root)

            # We prefer to use Linux's cp, because it nicely handles sparse files
            retcode = subprocess.call (["cp", template_root, self.root_img])
            if retcode != 0:
                raise IOError ("Error while copying {0} to {1}".\
                               format(template_root, self.root_img))

            kernels_dir = source_template.kernels_dir
            if verbose:
                print >> sys.stderr, "--> Copying the kernel (set kernel \"none\" to use it): {0}".\
                        format(kernels_dir)

            os.mkdir (self.dir_path + '/kernels')
            for f in ("vmlinuz", "initramfs", "modules.img"):
                shutil.copy(kernels_dir + '/' + f, self.dir_path + '/kernels/' + f)

            if verbose:
                print >> sys.stderr, "--> Copying the template's appmenus templates dir:\n{0} ==>\n{1}".\
                        format(source_template.appmenus_templates_dir, self.appmenus_templates_dir)
            shutil.copytree (source_template.appmenus_templates_dir, self.appmenus_templates_dir)

        # Create volatile.img
        self.reset_volatile_storage(source_template = source_template, verbose=verbose)

        if verbose:
            print >> sys.stderr, "--> Creating icon symlink: {0} -> {1}".format(self.icon_path, self.label.icon_path)
        os.symlink (self.label.icon_path, self.icon_path)

    def create_appmenus(self, verbose, source_template = None):
        if source_template is None:
            source_template = self.template

        vmtype = None
        if self.is_netvm():
            vmtype = 'servicevms'
        else:
            vmtype = 'appvms'

        try:
            if source_template is not None:
                subprocess.check_call ([qubes_appmenu_create_cmd, source_template.appmenus_templates_dir, self.name, vmtype])
            elif self.appmenus_templates_dir is not None:
                subprocess.check_call ([qubes_appmenu_create_cmd, self.appmenus_templates_dir, self.name, vmtype])
            else:
                # Only add apps to menu
                subprocess.check_call ([qubes_appmenu_create_cmd, "none", self.name, vmtype])
        except subprocess.CalledProcessError:
            print >> sys.stderr, "Ooops, there was a problem creating appmenus for {0} VM!".format (self.name)

    def get_clone_attrs(self):
        return ['kernel', 'uses_default_kernel', 'netvm', 'uses_default_netvm', \
            'memory', 'maxmem', 'kernelopts', 'uses_default_kernelopts', 'services', 'vcpus', \
            '_mac', 'pcidevs', 'include_in_backups']

    def clone_attrs(self, src_vm):
        for prop in self.get_clone_attrs():
            setattr(self, prop, getattr(src_vm, prop))

    def clone_disk_files(self, src_vm, verbose):
        if dry_run:
            return

        if src_vm.is_running():
            raise QubesException("Attempt to clone a running VM!")

        if verbose:
            print >> sys.stderr, "--> Creating directory: {0}".format(self.dir_path)
        os.mkdir (self.dir_path)

        if src_vm.private_img is not None and self.private_img is not None:
            if verbose:
                print >> sys.stderr, "--> Copying the private image:\n{0} ==>\n{1}".\
                        format(src_vm.private_img, self.private_img)
            # We prefer to use Linux's cp, because it nicely handles sparse files
            retcode = subprocess.call (["cp", src_vm.private_img, self.private_img])
            if retcode != 0:
                raise IOError ("Error while copying {0} to {1}".\
                               format(src_vm.private_img, self.private_img))

        if src_vm.updateable and src_vm.root_img is not None and self.root_img is not None:
            if verbose:
                print >> sys.stderr, "--> Copying the root image:\n{0} ==>\n{1}".\
                        format(src_vm.root_img, self.root_img)
            # We prefer to use Linux's cp, because it nicely handles sparse files
            retcode = subprocess.call (["cp", src_vm.root_img, self.root_img])
            if retcode != 0:
                raise IOError ("Error while copying {0} to {1}".\
                           format(src_vm.root_img, self.root_img))

        if src_vm.updateable and src_vm.appmenus_templates_dir is not None and self.appmenus_templates_dir is not None:
            if verbose:
                print >> sys.stderr, "--> Copying the template's appmenus templates dir:\n{0} ==>\n{1}".\
                        format(src_vm.appmenus_templates_dir, self.appmenus_templates_dir)
            shutil.copytree (src_vm.appmenus_templates_dir, self.appmenus_templates_dir)

        if os.path.exists(src_vm.dir_path + '/' + qubes_whitelisted_appmenus):
            if verbose:
                print >> sys.stderr, "--> Copying whitelisted apps list: {0}".\
                    format(self.dir_path + '/' + qubes_whitelisted_appmenus)
            shutil.copy(src_vm.dir_path + '/' + qubes_whitelisted_appmenus,
                    self.dir_path + '/' + qubes_whitelisted_appmenus)

        if src_vm.icon_path is not None and self.icon_path is not None:
            if os.path.exists (src_vm.dir_path):
                if os.path.islink(src_vm.dir_path):
                    icon_path = os.readlink(src_vm.dir_path)
                    if verbose:
                        print >> sys.stderr, "--> Creating icon symlink: {0} -> {1}".format(self.icon_path, icon_path)
                    os.symlink (icon_path, self.icon_path)
                else:
                    if verbose:
                        print >> sys.stderr, "--> Copying icon: {0} -> {1}".format(src_vm.icon_path, self.icon_path)
                    shutil.copy(src_vm.icon_path, self.icon_path)

        # Create appmenus
        self.create_appmenus(verbose)

    def remove_appmenus(self):
        vmtype = None
        if self.is_netvm():
            vmtype = 'servicevms'
        else:
            vmtype = 'appvms'
        subprocess.check_call ([qubes_appmenu_remove_cmd, self.name, vmtype])

    def verify_files(self):
        if dry_run:
            return

        if not os.path.exists (self.dir_path):
            raise QubesException (
                "VM directory doesn't exist: {0}".\
                format(self.dir_path))

        if self.updateable and not os.path.exists (self.root_img):
            raise QubesException (
                "VM root image file doesn't exist: {0}".\
                format(self.root_img))

        if not os.path.exists (self.private_img):
            raise QubesException (
                "VM private image file doesn't exist: {0}".\
                format(self.private_img))

        if not os.path.exists (self.kernels_dir + '/vmlinuz'):
            raise QubesException (
                "VM kernel does not exists: {0}".\
                format(self.kernels_dir + '/vmlinuz'))

        if not os.path.exists (self.kernels_dir + '/initramfs'):
            raise QubesException (
                "VM initramfs does not exists: {0}".\
                format(self.kernels_dir + '/initramfs'))

        if not os.path.exists (self.kernels_dir + '/modules.img'):
            raise QubesException (
                "VM kernel modules image does not exists: {0}".\
                format(self.kernels_dir + '/modules.img'))
        return True

    def reset_volatile_storage(self, source_template = None, verbose = False):
        assert not self.is_running(), "Attempt to clean volatile image of running VM!"

        if source_template is None:
            source_template = self.template

        # Only makes sense on template based VM
        if source_template is None:
            return

        if verbose:
            print >> sys.stderr, "--> Cleaning volatile image: {0}...".format (self.volatile_img)
        if dry_run:
            return
        if os.path.exists (self.volatile_img):
           os.remove (self.volatile_img)

        retcode = subprocess.call (["tar", "xf", source_template.clean_volatile_img, "-C", self.dir_path])
        if retcode != 0:
            raise IOError ("Error while unpacking {0} to {1}".\
                           format(source_template.clean_volatile_img, self.volatile_img))

    def remove_from_disk(self):
        if dry_run:
            return

        shutil.rmtree (self.dir_path)

    def write_firewall_conf(self, conf):
        defaults = self.get_firewall_conf()
        for item in defaults.keys():
            if item not in conf:
                conf[item] = defaults[item]

        root = xml.etree.ElementTree.Element(
                "QubesFirwallRules",
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
            element = xml.etree.ElementTree.Element(
                    "rule",
                    address=rule["address"],
                    proto=str(rule["proto"]),
            )
            if rule["netmask"] is not None and rule["netmask"] != 32:
                element.set("netmask", str(rule["netmask"]))
            if rule["portBegin"] is not None and rule["portBegin"] > 0:
                element.set("port", str(rule["portBegin"]))
            if rule["portEnd"] is not None and rule["portEnd"] > 0:
                element.set("toport", str(rule["portEnd"]))

            root.append(element)

        tree = xml.etree.ElementTree.ElementTree(root)

        try:
            f = open(self.firewall_conf, 'a') # create the file if not exist
            f.close()

            with open(self.firewall_conf, 'w') as f:
                fcntl.lockf(f, fcntl.LOCK_EX)
                tree.write(f, "UTF-8")
                fcntl.lockf(f, fcntl.LOCK_UN)
            f.close()
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

        return True

    def has_firewall(self):
        return os.path.exists (self.firewall_conf)

    def get_firewall_defaults(self):
        return { "rules": list(), "allow": True, "allowDns": True, "allowIcmp": True, "allowYumProxy": False }

    def get_firewall_conf(self):
        conf = self.get_firewall_defaults()

        try:
            tree = xml.etree.ElementTree.parse(self.firewall_conf)
            root = tree.getroot()

            conf["allow"] = (root.get("policy") == "allow")
            conf["allowDns"] = (root.get("dns") == "allow")
            conf["allowIcmp"] = (root.get("icmp") == "allow")
            conf["allowYumProxy"] = (root.get("yumProxy") == "allow")

            for element in root:
                rule = {}
                attr_list = ("address", "netmask", "proto", "port", "toport")

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

    def run(self, command, verbose = True, autostart = False, notify_function = None, passio = False, passio_popen = False, localcmd = None, wait = False):
        """command should be in form 'user:cmdline'"""

        if not self.is_running():
            if not autostart:
                raise QubesException("VM not running")

            try:
                if notify_function is not None:
                    notify_function ("info", "Starting the '{0}' VM...".format(self.name))
                elif verbose:
                    print >> sys.stderr, "Starting the VM '{0}'...".format(self.name)
                xid = self.start(verbose=verbose)

            except (IOError, OSError, QubesException) as err:
                raise QubesException("Error while starting the '{0}' VM: {1}".format(self.name, err))
            except (MemoryError) as err:
                raise QubesException("Not enough memory to start '{0}' VM! Close one or more running VMs and try again.".format(self.name))

        xid = self.get_xid()
        if os.getenv("DISPLAY") is not None and not self.is_guid_running():
            self.start_guid(verbose = verbose, notify_function = notify_function)

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

        xs_path = '/local/domain/%d/device/vif/0/state' % (self.xid)
        if xs.read('', xs_path) is not None:
            # TODO: check its state and backend state (this can be stale vif after NetVM restart)
            if verbose:
                print >> sys.stderr, "NOTICE: Network already attached"
                return

        xm_cmdline = ["/usr/sbin/xl", "network-attach", str(self.xid), "script=/etc/xen/scripts/vif-route-qubes", "ip="+self.ip, "backend="+netvm.name ]
        retcode = subprocess.call (xm_cmdline)
        if retcode != 0:
            print >> sys.stderr, ("WARNING: Cannot attach to network to '{0}'!".format(self.name))
        if wait:
            tries = 0
            while xs.read('', xs_path) != '4':
                tries += 1
                if tries > 50:
                    raise QubesException ("Network attach timed out!")
                time.sleep(0.2)

    def start_guid(self, verbose = True, notify_function = None):
        if verbose:
            print >> sys.stderr, "--> Starting Qubes GUId..."
        xid = self.get_xid()

        guid_cmd = [qubes_guid_path, "-d", str(xid), "-c", self.label.color, "-i", self.label.icon, "-l", str(self.label.index)]
        if self.debug:
            guid_cmd += ['-v', '-v']
        retcode = subprocess.call (guid_cmd)
        if (retcode != 0) :
            raise QubesException("Cannot start qubes_guid!")

        if verbose:
            print >> sys.stderr, "--> Waiting for qubes-session..."

        subprocess.call([qrexec_client_path, "-d", str(xid), "user:echo $$ >> /tmp/qubes-session-waiter; [ ! -f /tmp/qubes-session-env ] && exec sleep 365d"])

        retcode = subprocess.call([qubes_clipd_path])
        if retcode != 0:
            print >> sys.stderr, "ERROR: Cannot start qclipd!"
            if notify_function is not None:
                notify_function("error", "ERROR: Cannot start the Qubes Clipboard Notifier!")

    def start_qrexec_daemon(self, verbose = False):
        if verbose:
            print >> sys.stderr, "--> Starting the qrexec daemon..."
        xid = self.get_xid()
        retcode = subprocess.call ([qrexec_daemon_path, str(xid)])
        if (retcode != 0) :
            self.force_shutdown()
            raise OSError ("ERROR: Cannot execute qrexec_daemon!")

    def start(self, debug_console = False, verbose = False, preparing_dvm = False, start_guid = True):
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
                    self.netvm.start()

        self.reset_volatile_storage(verbose=verbose)
        if verbose:
            print >> sys.stderr, "--> Loading the VM (type = {0})...".format(self.type)

        # refresh config file
        self.create_config_file()

        mem_required = int(self.memory) * 1024 * 1024
        qmemman_client = QMemmanClient()
        if not qmemman_client.request_memory(mem_required):
            qmemman_client.close()
            raise MemoryError ("ERROR: insufficient memory to start VM '%s'" % self.name)

        # Bind pci devices to pciback driver
        for pci in self.pcidevs:
            try:
                subprocess.check_call(['sudo', qubes_pciback_cmd, pci])
            except subprocess.CalledProcessError:
                raise QubesException("Failed to prepare PCI device %s" % pci)

        xl_cmdline = ['sudo', '/usr/sbin/xl', 'create', self.conf_file, '-q', '-p']

        try:
            subprocess.check_call(xl_cmdline)
        except:
            raise QubesException("Failed to load VM config")

        xid = self.get_xid()
        self.xid = xid

        if preparing_dvm:
            self.services['qubes-dvm'] = True
        if verbose:
            print >> sys.stderr, "--> Setting Xen Store info for the VM..."
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

        if verbose:
            print >> sys.stderr, "--> Starting the VM..."
        xc.domain_unpause(xid)

# close() is not really needed, because the descriptor is close-on-exec
# anyway, the reason to postpone close() is that possibly xl is not done
# constructing the domain after its main process exits
# so we close() when we know the domain is up
# the successful unpause is some indicator of it
        qmemman_client.close()

        if not preparing_dvm:
            self.start_qrexec_daemon(verbose=verbose)

        if start_guid and not preparing_dvm and os.path.exists('/var/run/shm.id'):
            self.start_guid(verbose=verbose)

        if preparing_dvm:
            if verbose:
                print >> sys.stderr, "--> Preparing config template for DispVM"
            self.create_config_file(file_path = self.dir_path + '/dvm.conf', prepare_dvm = True)

        # perhaps we should move it before unpause and fork?
        # FIXME: this uses obsolete xm api
        if debug_console:
            from xen.xm import console
            if verbose:
                print >> sys.stderr, "--> Starting debug console..."
            console.execConsole (xid)

        return xid

    def shutdown(self, force=False):
        if dry_run:
            return

        subprocess.call (['/usr/sbin/xl', 'shutdown', self.name])
        #xc.domain_destroy(self.get_xid())

    def force_shutdown(self):
        if dry_run:
            return

        subprocess.call (['/usr/sbin/xl', 'destroy', self.name])
        #xc.domain_destroy(self.get_xid())

    def pause(self):
        if dry_run:
            return

        xc.domain_pause(self.get_xid())

    def unpause(self):
        if dry_run:
            return

        xc.domain_unpause(self.get_xid())

    def remove_from_disk(self):
        if dry_run:
            return


        shutil.rmtree (self.dir_path)

    def get_xml_attrs(self):
        attrs = {}
        attrs_config = self._get_attrs_config()
        for attr in attrs_config:
            attr_config = attrs_config[attr]
            if 'save' in attr_config:
                if 'save_skip' in attr_config and eval(attr_config['save_skip']):
                    continue
                if 'save_attr' in attr_config:
                    attrs[attr_config['save_attr']] = eval(attr_config['save'])
                else:
                    attrs[attr] = eval(attr_config['save'])
        return attrs

    def create_xml_element(self):
        # Compatibility hack (Qubes*VM in type vs Qubes*Vm in XML)...
        rx_type = re.compile (r"VM")

        attrs = self.get_xml_attrs()
        element = xml.etree.ElementTree.Element(
            "Qubes" + rx_type.sub("Vm", self.type),
            **attrs)
        return element


class QubesTemplateVm(QubesVm):
    """
    A class that represents an TemplateVM. A child of QubesVm.
    """

    def _get_attrs_config(self):
        attrs_config = super(QubesTemplateVm, self)._get_attrs_config()
        attrs_config['dir_path']['eval'] = 'value if value is not None else qubes_templates_dir + "/" + self.name'
        attrs_config['label']['default'] = default_template_label

        # New attributes

        # Image for template changes
        attrs_config['rootcow_img'] = { 'eval': 'self.dir_path + "/" + default_rootcow_img' }
        # Clean image for root-cow and swap (AppVM side)
        attrs_config['clean_volatile_img'] = { 'eval': 'self.dir_path + "/" + default_clean_volatile_img' }

        attrs_config['appmenus_templates_dir'] = { 'eval': 'self.dir_path + "/" + default_appmenus_templates_subdir' }
        return attrs_config

    def __init__(self, **kwargs):

        super(QubesTemplateVm, self).__init__(**kwargs)

        self.appvms = QubesVmCollection()

    @property
    def type(self):
        return "TemplateVM"

    @property
    def updateable(self):
        return True

    def get_firewall_defaults(self):
        return { "rules": list(), "allow": False, "allowDns": False, "allowIcmp": False, "allowYumProxy": True }

    def get_rootdev(self, source_template=None):
        return "'script:origin:{dir}/root.img:{dir}/root-cow.img,xvda,w',".format(dir=self.dir_path)

    def clone_disk_files(self, src_vm, verbose):
        if dry_run:
            return

        super(QubesTemplateVM, self).clone_disk_files(src_vm=src_vm, verbose=verbose)

        if os.path.exists(src_vm.dir_path + '/vm-' + qubes_whitelisted_appmenus):
            if verbose:
                print >> sys.stderr, "--> Copying default whitelisted apps list: {0}".\
                    format(self.dir_path + '/vm-' + qubes_whitelisted_appmenus)
            shutil.copy(src_vm.dir_path + '/vm-' + qubes_whitelisted_appmenus,
                    self.dir_path + '/vm-' + qubes_whitelisted_appmenus)

        if verbose:
            print >> sys.stderr, "--> Copying the template's clean volatile image:\n{0} ==>\n{1}".\
                    format(src_vm.clean_volatile_img, self.clean_volatile_img)
        # We prefer to use Linux's cp, because it nicely handles sparse files
        retcode = subprocess.call (["cp", src_vm.clean_volatile_img, self.clean_volatile_img])
        if retcode != 0:
            raise IOError ("Error while copying {0} to {1}".\
                           format(src_vm.clean_volatile_img, self.clean_volatile_img))
        if verbose:
            print >> sys.stderr, "--> Copying the template's volatile image:\n{0} ==>\n{1}".\
                    format(self.clean_volatile_img, self.volatile_img)
        # We prefer to use Linux's cp, because it nicely handles sparse files
        retcode = subprocess.call (["cp", self.clean_volatile_img, self.volatile_img])
        if retcode != 0:
            raise IOError ("Error while copying {0} to {1}".\
                           format(self.clean_img, self.volatile_img))

        if verbose:
            print >> sys.stderr, "--> Copying the template's DispVM prerun script..."
        retcode = subprocess.call (["cp", src_vm.dir_path + '/dispvm-prerun.sh', self.dir_path + '/dispvm-prerun.sh'])
        if retcode != 0:
            raise IOError ("Error while copying DispVM prerun script")

        # Create root-cow.img
        self.commit_changes(verbose=verbose)

    def create_appmenus(self, verbose, source_template = None):
        if source_template is None:
            source_template = self.template

        try:
            subprocess.check_call ([qubes_appmenu_create_cmd, self.appmenus_templates_dir, self.name, "vm-templates"])
        except subprocess.CalledProcessError:
            print >> sys.stderr, "Ooops, there was a problem creating appmenus for {0} VM!".format (self.name)

    def remove_appmenus(self):
        subprocess.check_call ([qubes_appmenu_remove_cmd, self.name, "vm-templates"])

    def pre_rename(self, new_name):
        self.remove_appmenus()

    def post_rename(self, old_name):
        self.create_appmenus(False)

        old_dirpath = os.path.dirname(self.dir_path) + '/' + old_name
        self.clean_volatile_img = self.clean_volatile_img.replace(old_dirpath, self.dir_path)
        self.rootcow_img = self.rootcow_img.replace(old_dirpath, self.dir_path)

    def remove_from_disk(self):
        if dry_run:
            return

        self.remove_appmenus()
        super(QubesTemplateVm, self).remove_from_disk()

    def verify_files(self):
        if dry_run:
            return


        if not os.path.exists (self.dir_path):
            raise QubesException (
                "VM directory doesn't exist: {0}".\
                format(self.dir_path))

        if not os.path.exists (self.root_img):
            raise QubesException (
                "VM root image file doesn't exist: {0}".\
                format(self.root_img))

        if not os.path.exists (self.private_img):
            raise QubesException (
                "VM private image file doesn't exist: {0}".\
                format(self.private_img))

        if not os.path.exists (self.volatile_img):
            raise QubesException (
                "VM volatile image file doesn't exist: {0}".\
                format(self.volatile_img))

        if not os.path.exists (self.clean_volatile_img):
            raise QubesException (
                "Clean VM volatile image file doesn't exist: {0}".\
                format(self.clean_volatile_img))

        if not os.path.exists (self.kernels_dir):
            raise QubesException (
                "VM's kernels directory does not exist: {0}".\
                format(self.kernels_dir))

        return True

    def reset_volatile_storage(self, verbose = False):
        assert not self.is_running(), "Attempt to clean volatile image of running Template VM!"

        if verbose:
            print >> sys.stderr, "--> Cleaning volatile image: {0}...".format (self.volatile_img)
        if dry_run:
            return
        if os.path.exists (self.volatile_img):
           os.remove (self.volatile_img)

        retcode = subprocess.call (["tar", "xf", self.clean_volatile_img, "-C", self.dir_path])
        if retcode != 0:
            raise IOError ("Error while unpacking {0} to {1}".\
                           format(self.template.clean_volatile_img, self.volatile_img))

    def commit_changes (self, verbose = False):

        assert not self.is_running(), "Attempt to commit changes on running Template VM!"

        if verbose:
            print >> sys.stderr, "--> Commiting template updates... COW: {0}...".format (self.rootcow_img)

        if dry_run:
            return
        if os.path.exists (self.rootcow_img):
           os.rename (self.rootcow_img, self.rootcow_img + '.old')

        f_cow = open (self.rootcow_img, "w")
        f_root = open (self.root_img, "r")
        f_root.seek(0, os.SEEK_END)
        f_cow.truncate (f_root.tell()) # make empty sparse file of the same size as root.img
        f_cow.close ()
        f_root.close()

class QubesNetVm(QubesVm):
    """
    A class that represents a NetVM. A child of QubesCowVM.
    """
    def _get_attrs_config(self):
        attrs_config = super(QubesNetVm, self)._get_attrs_config()
        attrs_config['dir_path']['eval'] = 'value if value is not None else qubes_servicevms_dir + "/" + self.name'
        attrs_config['label']['default'] = default_servicevm_label
        attrs_config['memory']['default'] = 200

        # New attributes
        attrs_config['netid'] = { 'save': 'str(self.netid)', 'order': 30 }
        attrs_config['netprefix'] = { 'eval': '"10.137.{0}.".format(self.netid)' }
        attrs_config['dispnetprefix'] = { 'eval': '"10.138.{0}.".format(self.netid)' }

        # Dont save netvm prop
        attrs_config['netvm'].pop('save')
        attrs_config['uses_default_netvm'].pop('save')

        return attrs_config

    def __init__(self, **kwargs):
        super(QubesNetVm, self).__init__(**kwargs)
        self.connected_vms = QubesVmCollection()

        self.__network = "10.137.{0}.0".format(self.netid)
        self.__netmask = vm_default_netmask
        self.__gateway = self.netprefix + "1"
        self.__secondary_dns = self.netprefix + "254"

        self.__external_ip_allowed_xids = set()

    @property
    def type(self):
        return "NetVM"

    @property
    def gateway(self):
        return self.__gateway

    @property
    def secondary_dns(self):
        return self.__secondary_dns

    @property
    def netmask(self):
        return self.__netmask

    @property
    def network(self):
        return self.__network

    def get_ip_for_vm(self, qid):
        lo = qid % 253 + 2
        assert lo >= 2 and lo <= 254, "Wrong IP address for VM"
        return self.netprefix  + "{0}".format(lo)

    def get_ip_for_dispvm(self, dispid):
        lo = dispid % 254 + 1
        assert lo >= 1 and lo <= 254, "Wrong IP address for VM"
        return self.dispnetprefix  + "{0}".format(lo)

    def create_xenstore_entries(self, xid = None):
        if dry_run:
            return

        if xid is None:
            xid = self.xid


        super(QubesNetVm, self).create_xenstore_entries(xid)
        xs.write('', "/local/domain/{0}/qubes_netvm_external_ip".format(xid), '')
        self.update_external_ip_permissions(xid)

    def update_external_ip_permissions(self, xid = -1):
        if xid < 0:
            xid = self.get_xid()
        if xid < 0:
            return

        command = [
                "/usr/bin/xenstore-chmod",
                "/local/domain/{0}/qubes_netvm_external_ip".format(xid)
            ]

        command.append("n{0}".format(xid))

        for id in self.__external_ip_allowed_xids:
            command.append("r{0}".format(id))

        return subprocess.check_call(command)

    def start(self, **kwargs):
        if dry_run:
            return

        xid=super(QubesNetVm, self).start(**kwargs)

        # Connect vif's of already running VMs
        for vm in self.connected_vms.values():
            if not vm.is_running():
                continue

            if 'verbose' in kwargs and kwargs['verbose']:
                print >> sys.stderr, "--> Attaching network to '{0}'...".format(vm.name)

            # Cleanup stale VIFs
            vm.cleanup_vifs()

            # wait for frontend to forget about this device (UGLY HACK)
            time.sleep(0.2)

            try:
                vm.attach_network(wait=False)
            except QubesException as ex:
                print >> sys.stderr, ("WARNING: Cannot attach to network to '{0}': {1}".format(vm.name, ex))

        return xid

    def shutdown(self, force=False):
        if dry_run:
            return

        connected_vms =  [vm for vm in self.connected_vms.values() if vm.is_running()]
        if connected_vms and not force:
            raise QubesException("There are other VMs connected to this VM: " + str([vm.name for vm in connected_vms]))

        super(QubesNetVm, self).shutdown(force=force)

    def add_external_ip_permission(self, xid):
        if int(xid) < 0:
            return
        self.__external_ip_allowed_xids.add(int(xid))
        self.update_external_ip_permissions()

    def remove_external_ip_permission(self, xid):
        self.__external_ip_allowed_xids.discard(int(xid))
        self.update_external_ip_permissions()

    def create_on_disk(self, verbose, source_template = None):
        if dry_run:
            return

        super(QubesNetVm, self).create_on_disk(verbose, source_template=source_template)

        if os.path.exists(source_template.dir_path + '/netvm-' + qubes_whitelisted_appmenus):
            if verbose:
                print >> sys.stderr, "--> Creating default whitelisted apps list: {0}".\
                    format(self.dir_path + '/' + qubes_whitelisted_appmenus)
            shutil.copy(source_template.dir_path + '/netvm-' + qubes_whitelisted_appmenus,
                    self.dir_path + '/' + qubes_whitelisted_appmenus)

        if not self.internal:
            self.create_appmenus (verbose, source_template=source_template)

class QubesProxyVm(QubesNetVm):
    """
    A class that represents a ProxyVM, ex FirewallVM. A child of QubesNetVM.
    """

    def _get_attrs_config(self):
        attrs_config = super(QubesProxyVm, self)._get_attrs_config()
        attrs_config['uses_default_netvm']['eval'] = 'False'
        # Save netvm prop again
        attrs_config['netvm']['save'] = 'str(self.netvm.qid) if self.netvm is not None else "none"'

        return attrs_config

    def __init__(self, **kwargs):
        super(QubesProxyVm, self).__init__(**kwargs)
        self.rules_applied = None

    @property
    def type(self):
        return "ProxyVM"

    def _set_netvm(self, new_netvm):
        old_netvm = self.netvm
        super(QubesProxyVm, self)._set_netvm(new_netvm)
        if self.netvm is not None:
            self.netvm.add_external_ip_permission(self.get_xid())
        self.write_netvm_domid_entry()
        if old_netvm is not None:
            old_netvm.remove_external_ip_permission(self.get_xid())

    def post_vm_net_attach(self, vm):
        """ Called after some VM net-attached to this ProxyVm """

        self.write_iptables_xenstore_entry()

    def post_vm_net_detach(self, vm):
        """ Called after some VM net-detached from this ProxyVm """

        self.write_iptables_xenstore_entry()

    def start(self, **kwargs):
        if dry_run:
            return
        retcode = super(QubesProxyVm, self).start(**kwargs)
        self.netvm.add_external_ip_permission(self.get_xid())
        self.write_netvm_domid_entry()
        return retcode

    def force_shutdown(self):
        if dry_run:
            return
        self.netvm.remove_external_ip_permission(self.get_xid())
        super(QubesProxyVm, self).force_shutdown()

    def create_xenstore_entries(self, xid = None):
        if dry_run:
            return

        if xid is None:
            xid = self.xid


        super(QubesProxyVm, self).create_xenstore_entries(xid)
        xs.write('', "/local/domain/{0}/qubes_iptables_error".format(xid), '')
        xs.set_permissions('', "/local/domain/{0}/qubes_iptables_error".format(xid),
                [{ 'dom': xid, 'write': True }])
        self.write_iptables_xenstore_entry()

    def write_netvm_domid_entry(self, xid = -1):
        if not self.is_running():
            return

        if xid < 0:
            xid = self.get_xid()

        if self.netvm is None:
            xs.write('', "/local/domain/{0}/qubes_netvm_domid".format(xid), '')
        else:
            xs.write('', "/local/domain/{0}/qubes_netvm_domid".format(xid),
                    "{0}".format(self.netvm.get_xid()))

    def write_iptables_xenstore_entry(self):
        xs.rm('', "/local/domain/{0}/qubes_iptables_domainrules".format(self.get_xid()))
        iptables =  "# Generated by Qubes Core on {0}\n".format(datetime.now().ctime())
        iptables += "*filter\n"
        iptables += ":INPUT DROP [0:0]\n"
        iptables += ":FORWARD DROP [0:0]\n"
        iptables += ":OUTPUT ACCEPT [0:0]\n"

        # Strict INPUT rules
        iptables += "-A INPUT -i vif+ -p udp -m udp --dport 68 -j DROP\n"
        iptables += "-A INPUT -m state --state RELATED,ESTABLISHED -j ACCEPT\n"
        iptables += "-A INPUT -p icmp -j ACCEPT\n"
        iptables += "-A INPUT -i lo -j ACCEPT\n"
        iptables += "-A INPUT -j REJECT --reject-with icmp-host-prohibited\n"

        iptables += "-A FORWARD -m state --state RELATED,ESTABLISHED -j ACCEPT\n"
        # Allow dom0 networking
        iptables += "-A FORWARD -i vif0.0 -j ACCEPT\n"
        # Deny inter-VMs networking
        iptables += "-A FORWARD -i vif+ -o vif+ -j DROP\n"
        iptables += "COMMIT\n"
        xs.write('', "/local/domain/{0}/qubes_iptables_header".format(self.get_xid()), iptables)

        vms = [vm for vm in self.connected_vms.values()]
        for vm in vms:
            iptables="*filter\n"
            if vm.has_firewall():
                conf = vm.get_firewall_conf()
            else:
                conf = { "rules": list(), "allow": True, "allowDns": True, "allowIcmp": True, "allowYumProxy": False }

            xid = vm.get_xid()
            if xid < 0: # VM not active ATM
                continue

            ip = vm.ip
            if ip is None:
                continue

            iptables += "# '{0}' VM:\n".format(vm.name)
            # Anti-spoof rules are added by vif-script (vif-route-qubes), here we trust IP address

            accept_action = "ACCEPT"
            reject_action = "REJECT --reject-with icmp-host-prohibited"

            if conf["allow"]:
                default_action = accept_action
                rules_action = reject_action
            else:
                default_action = reject_action
                rules_action = accept_action

            for rule in conf["rules"]:
                iptables += "-A FORWARD -s {0} -d {1}".format(ip, rule["address"])
                if rule["netmask"] != 32:
                    iptables += "/{0}".format(rule["netmask"])

                if rule["proto"] is not None and rule["proto"] != "any":
                    iptables += " -p {0}".format(rule["proto"])
                    if rule["portBegin"] is not None and rule["portBegin"] > 0:
                        iptables += " --dport {0}".format(rule["portBegin"])
                        if rule["portEnd"] is not None and rule["portEnd"] > rule["portBegin"]:
                            iptables += ":{0}".format(rule["portEnd"])

                iptables += " -j {0}\n".format(rules_action)

            if conf["allowDns"]:
                # PREROUTING does DNAT to NetVM DNSes, so we need self.netvm. properties
                iptables += "-A FORWARD -s {0} -p udp -d {1} --dport 53 -j ACCEPT\n".format(ip,self.netvm.gateway)
                iptables += "-A FORWARD -s {0} -p udp -d {1} --dport 53 -j ACCEPT\n".format(ip,self.netvm.secondary_dns)
            if conf["allowIcmp"]:
                iptables += "-A FORWARD -s {0} -p icmp -j ACCEPT\n".format(ip)
            if conf["allowYumProxy"]:
                iptables += "-A FORWARD -s {0} -p tcp -d {1} --dport {2} -j ACCEPT\n".format(ip, yum_proxy_ip, yum_proxy_port)
            else:
                iptables += "-A FORWARD -s {0} -p tcp -d {1} --dport {2} -j DROP\n".format(ip, yum_proxy_ip, yum_proxy_port)

            iptables += "-A FORWARD -s {0} -j {1}\n".format(ip, default_action)
            iptables += "COMMIT\n"
            xs.write('', "/local/domain/"+str(self.get_xid())+"/qubes_iptables_domainrules/"+str(xid), iptables)
        # no need for ending -A FORWARD -j DROP, cause default action is DROP

        self.write_netvm_domid_entry()

        self.rules_applied = None
        xs.write('', "/local/domain/{0}/qubes_iptables".format(self.get_xid()), 'reload')

class QubesDom0NetVm(QubesNetVm):
    def __init__(self):
        super(QubesDom0NetVm, self).__init__(qid=0, name="dom0", netid=0,
                                             dir_path=None,
                                             private_img = None,
                                             template = None,
                                             label = default_template_label)
        self.xid = 0

    def is_running(self):
        return True

    def get_xid(self):
        return 0

    def get_power_state(self):
        return "Running"

    def get_disk_usage(self, file_or_dir):
        return 0

    def get_disk_utilization(self):
        return 0

    def get_disk_utilization_private_img(self):
        return 0

    def get_private_img_sz(self):
        return 0

    @property
    def ip(self):
        return "10.137.0.1"

    def start(self, **kwargs):
        raise QubesException ("Cannot start Dom0 fake domain!")

    def get_xl_dominfo(self):
        if dry_run:
            return

        domains = xl_ctx.list_domains()
        for dominfo in domains:
            if dominfo.domid == 0:
                return dominfo
        return None

    def get_xc_dominfo(self):
        if dry_run:
            return

        domains = xc.domain_getinfo(0, 1)
        return domains[0]

    def create_xml_element(self):
        return None

    def verify_files(self):
        return True

class QubesDisposableVm(QubesVm):
    """
    A class that represents an DisposableVM. A child of QubesVm.
    """

    def _get_attrs_config(self):
        attrs_config = super(QubesDisposableVm, self)._get_attrs_config()

        # New attributes
        attrs_config['dispid'] = { 'save': 'str(self.dispid)' }

        return attrs_config

    def __init__(self, **kwargs):

        super(QubesDisposableVm, self).__init__(dir_path="/nonexistent", **kwargs)

        assert self.template is not None, "Missing template for DisposableVM!"

        # Use DispVM icon with the same color
        if self._label:
            self._label = QubesDispVmLabels[self._label.name]
            self.icon_path = self._label.icon_path

    @property
    def type(self):
        return "DisposableVM"

    @property
    def ip(self):
        if self.netvm is not None:
            return self.netvm.get_ip_for_dispvm(self.dispid)
        else:
            return None


    def get_xml_attrs(self):
        # Minimal set - do not inherit rest of attributes
        attrs = {}
        attrs["qid"] = str(self.qid)
        attrs["name"] = self.name
        attrs["dispid"] = str(self.dispid)
        attrs["template_qid"] = str(self.template.qid)
        attrs["label"] = self.label.name
        attrs["firewall_conf"] = self.relative_path(self.firewall_conf)
        return attrs

    def verify_files(self):
        return True


class QubesAppVm(QubesVm):
    """
    A class that represents an AppVM. A child of QubesVm.
    """
    def _get_attrs_config(self):
        attrs_config = super(QubesAppVm, self)._get_attrs_config()
        attrs_config['dir_path']['eval'] = 'value if value is not None else qubes_appvms_dir + "/" + self.name'

        return attrs_config

    @property
    def type(self):
        return "AppVM"

    def create_on_disk(self, verbose, source_template = None):
        if dry_run:
            return

        super(QubesAppVm, self).create_on_disk(verbose, source_template=source_template)

        if not self.internal:
            self.create_appmenus (verbose, source_template=source_template)

    def remove_from_disk(self):
        if dry_run:
            return

        self.remove_appmenus()
        super(QubesAppVm, self).remove_from_disk()

    def pre_rename(self, new_name):
        self.remove_appmenus()

    def post_rename(self, old_name):
        self.create_appmenus(False)

class QubesHVm(QubesVm):
    """
    A class that represents an HVM. A child of QubesVm.
    """

    # FIXME: logically should inherit after QubesAppVm, but none of its methods
    # are useful for HVM

    def _get_attrs_config(self):
        attrs = super(QubesHVm, self)._get_attrs_config()
        attrs.pop('kernel')
        attrs.pop('kernels_dir')
        attrs.pop('kernelopts')
        attrs.pop('uses_default_kernel')
        attrs.pop('uses_default_kernelopts')
        attrs['volatile_img']['eval'] = 'None'
        attrs['config_file_template']['eval'] = 'config_template_hvm'
        attrs['drive'] = { 'save': 'str(self.drive)' }
        attrs['maxmem'].pop('save')
        attrs['timezone'] = { 'default': 'localtime', 'save': 'str(self.timezone)' }

        return attrs

    def __init__(self, **kwargs):

        if "dir_path" not in kwargs or kwargs["dir_path"] is None:
            kwargs["dir_path"] = qubes_appvms_dir + "/" + kwargs["name"]

        # only updateable HVM supported
        kwargs["updateable"] = True
        kwargs["template_vm"] = None
        if "memory" not in kwargs or kwargs["memory"] is None:
            kwargs["memory"] = default_hvm_memory

        super(QubesHVm, self).__init__(**kwargs)
        # HVM doesn't support dynamic memory management
        self.maxmem = self.memory

    @property
    def type(self):
        return "HVM"

    def is_appvm(self):
        return True

    def get_clone_attrs(self):
        attrs = super(QubesHVm, self).get_clone_attrs()
        attrs.remove('kernel')
        attrs.remove('uses_default_kernel')
        attrs.remove('kernelopts')
        attrs.remove('uses_default_kernelopts')
        attrs += [ 'timezone' ]
        return attrs

    def create_on_disk(self, verbose, source_template = None):
        if dry_run:
            return

        if verbose:
            print >> sys.stderr, "--> Creating directory: {0}".format(self.dir_path)
        os.mkdir (self.dir_path)

        if verbose:
            print >> sys.stderr, "--> Creating icon symlink: {0} -> {1}".format(self.icon_path, self.label.icon_path)
        os.symlink (self.label.icon_path, self.icon_path)

        if verbose:
            print >> sys.stderr, "--> Creating appmenus directory: {0}".format(self.appmenus_templates_dir)
        os.mkdir (self.appmenus_templates_dir)
        shutil.copy (start_appmenu_template, self.appmenus_templates_dir)

        if not self.internal:
            self.create_appmenus (verbose, source_template=source_template)

        self.create_config_file()

        # create empty disk
        f_root = open(self.root_img, "w")
        f_root.truncate(default_hvm_disk_size)
        f_root.close()

        # create empty private.img
        f_private = open(self.private_img, "w")
        f_private.truncate(default_hvm_private_img_size)
        f_root.close()

    def remove_from_disk(self):
        if dry_run:
            return

        self.remove_appmenus()
        super(QubesHVm, self).remove_from_disk()

    def pre_rename(self, new_name):
        self.remove_appmenus()

    def post_rename(self, old_name):
        self.create_appmenus(False)

    def get_disk_utilization_private_img(self):
        return 0

    def get_private_img_sz(self):
        return 0

    def resize_private_img(self, size):
        raise NotImplementedError("HVM has no private.img")

    def get_config_params(self, source_template=None):

        params = super(QubesHVm, self).get_config_params(source_template=source_template)

        params['volatiledev'] = ''
        if self.drive:
            type_mode = ":cdrom,r"
            drive_path = self.drive
            # leave empty to use standard syntax in case of dom0
            backend_domain = ""
            if drive_path.startswith("hd:"):
                type_mode = ",w"
                drive_path = drive_path[3:]
            elif drive_path.startswith("cdrom:"):
                type_mode = ":cdrom,r"
                drive_path = drive_path[6:]
            backend_split = re.match(r"^([a-zA-Z0-9-]*):(.*)", drive_path)
            if backend_split:
                backend_domain = "," + backend_split.group(1)
                drive_path = backend_split.group(2)

            # FIXME: os.stat will work only when backend in dom0...
            stat_res = None
            if backend_domain == "":
                stat_res = os.stat(drive_path)
            if stat_res and stat.S_ISBLK(stat_res.st_mode):
                params['otherdevs'] = "'phy:%s,xvdc%s%s'," % (drive_path, type_mode, backend_domain)
            else:
                params['otherdevs'] = "'script:file:%s,xvdc%s%s'," % (drive_path, type_mode, backend_domain)
        else:
             params['otherdevs'] = ''

        # Disable currently unused private.img - to be enabled when TemplateHVm done
        params['privatedev'] = ''

        if self.timezone.lower() == 'localtime':
             params['localtime'] = '1'
             params['timeoffset'] = '0'
        elif self.timezone.isdigit():
            params['localtime'] = '0'
            params['timeoffset'] = self.timezone
        else:
            print >>sys.stderr, "WARNING: invalid 'timezone' value: %s" % self.timezone
            params['localtime'] = '0'
            params['timeoffset'] = '0'
        return params

    def verify_files(self):
        if dry_run:
            return

        if not os.path.exists (self.dir_path):
            raise QubesException (
                    "VM directory doesn't exist: {0}".\
                    format(self.dir_path))

        if self.is_updateable() and not os.path.exists (self.root_img):
            raise QubesException (
                    "VM root image file doesn't exist: {0}".\
                    format(self.root_img))

        if not os.path.exists (self.private_img):
            print >>sys.stderr, "WARNING: Creating empty VM private image file: {0}".\
                format(self.private_img)
            f_private = open(self.private_img, "w")
            f_private.truncate(default_hvm_private_img_size)
            f_private.close()

        return True

    def reset_volatile_storage(self, **kwargs):
        pass

    @property
    def vif(self):
        if self.xid < 0:
            return None
        if self.netvm is None:
            return None
        return "vif{0}.+".format(self.stubdom_xid)

    def run(self, command, **kwargs):
        raise NotImplementedError("Needs qrexec agent - TODO")

    @property
    def stubdom_xid(self):
        if self.xid < 0:
            return -1

        return int(xs.read('', '/local/domain/%d/image/device-model-domid' % self.xid))

    def start_guid(self, verbose = True, notify_function = None):
        if verbose:
            print >> sys.stderr, "--> Starting Qubes GUId..."

        retcode = subprocess.call ([qubes_guid_path, "-d", str(self.stubdom_xid), "-c", self.label.color, "-i", self.label.icon, "-l", str(self.label.index)])
        if (retcode != 0) :
            raise QubesException("Cannot start qubes_guid!")

    def start_qrexec_daemon(self, **kwargs):
        pass

    def pause(self):
        if dry_run:
            return

        xc.domain_pause(self.stubdom_xid)
        super(QubesHVm, self).pause()

    def unpause(self):
        if dry_run:
            return

        xc.domain_unpause(self.stubdom_xid)
        super(QubesHVm, self).unpause()

    def is_guid_running(self):
        xid = self.stubdom_xid
        if xid < 0:
            return False
        if not os.path.exists('/var/run/qubes/guid_running.%d' % xid):
            return False
        return True

class QubesVmCollection(dict):
    """
    A collection of Qubes VMs indexed by Qubes id (qid)
    """

    def __init__(self, store_filename=qubes_store_filename):
        super(QubesVmCollection, self).__init__()
        self.default_netvm_qid = None
        self.default_fw_netvm_qid = None
        self.default_template_qid = None
        self.default_kernel = None
        self.updatevm_qid = None
        self.qubes_store_filename = store_filename
        self.clockvm_qid = None

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
        if key not in self:
            return super(QubesVmCollection, self).__setitem__(key, value)
        else:
            assert False, "Attempt to add VM with qid that already exists in the collection!"


    def add_new_appvm(self, name, template,
                      dir_path = None, conf_file = None,
                      private_img = None,
                      label = None):

        qid = self.get_new_unused_qid()
        vm = QubesAppVm (qid=qid, name=name, template=template,
                         dir_path=dir_path, conf_file=conf_file,
                         private_img=private_img,
                         netvm = self.get_default_netvm(),
                         kernel = self.get_default_kernel(),
                         uses_default_kernel = True,
                         label=label)

        if not self.verify_new_vm (vm):
            assert False, "Wrong VM description!"
        self[vm.qid]=vm
        return vm

    def add_new_hvm(self, name, label = None):

        qid = self.get_new_unused_qid()
        vm = QubesHVm (qid=qid, name=name,
                         netvm = self.get_default_netvm(),
                         label=label)

        if not self.verify_new_vm (vm):
            assert False, "Wrong VM description!"
        self[vm.qid]=vm
        return vm

    def add_new_disposablevm(self, name, template, dispid,
                      label = None):

        qid = self.get_new_unused_qid()
        vm = QubesDisposableVm (qid=qid, name=name, template=template,
                         netvm = self.get_default_netvm(),
                         label=label, dispid=dispid)

        if not self.verify_new_vm (vm):
            assert False, "Wrong VM description!"
        self[vm.qid]=vm
        return vm

    def add_new_templatevm(self, name,
                           dir_path = None, conf_file = None,
                           root_img = None, private_img = None,
                           installed_by_rpm = True):

        qid = self.get_new_unused_qid()
        vm = QubesTemplateVm (qid=qid, name=name,
                              dir_path=dir_path, conf_file=conf_file,
                              root_img=root_img, private_img=private_img,
                              installed_by_rpm=installed_by_rpm,
                              netvm = self.get_default_netvm(),
                              kernel = self.get_default_kernel(),
                              uses_default_kernel = True)

        if not self.verify_new_vm (vm):
            assert False, "Wrong VM description!"
        self[vm.qid]=vm

        if self.default_template_qid is None:
            self.set_default_template(vm)

        return vm

    def clone_templatevm(self, src_template, name, dir_path = None, verbose = False):

        assert not src_template.is_running(), "Attempt to clone a running Template VM!"

        vm = self.add_new_templatevm (name=name, dir_path=dir_path, installed_by_rpm = False)

        return vm


    def add_new_netvm(self, name, template,
                      dir_path = None, conf_file = None,
                      private_img = None, installed_by_rpm = False,
                      label = None):

        qid = self.get_new_unused_qid()
        netid = self.get_new_unused_netid()
        vm = QubesNetVm (qid=qid, name=name, template=template,
                         netid=netid, label=label,
                         private_img=private_img, installed_by_rpm=installed_by_rpm,
                         kernel = self.get_default_kernel(),
                         uses_default_kernel = True,
                         dir_path=dir_path, conf_file=conf_file)

        if not self.verify_new_vm (vm):
            assert False, "Wrong VM description!"
        self[vm.qid]=vm

        if self.default_fw_netvm_qid is None:
            self.set_default_fw_netvm(vm)

        # by default ClockVM is the first NetVM
        if self.clockvm_qid is None:
            self.set_clockvm_vm(vm)

        return vm

    def add_new_proxyvm(self, name, template,
                     dir_path = None, conf_file = None,
                     private_img = None, installed_by_rpm = False,
                     label = None):

        qid = self.get_new_unused_qid()
        netid = self.get_new_unused_netid()
        vm = QubesProxyVm (qid=qid, name=name, template=template,
                              netid=netid, label=label,
                              private_img=private_img, installed_by_rpm=installed_by_rpm,
                              dir_path=dir_path, conf_file=conf_file,
                              kernel = self.get_default_kernel(),
                              uses_default_kernel = True,
                              netvm = self.get_default_fw_netvm())

        if not self.verify_new_vm (vm):
            assert False, "Wrong VM description!"
        self[vm.qid]=vm

        if self.default_netvm_qid is None:
            self.set_default_netvm(vm)

        if self.updatevm_qid is None:
            self.set_updatevm_vm(vm)

        return vm

    def set_default_template(self, vm):
        assert vm.is_template(), "VM {0} is not a TemplateVM!".format(vm.name)
        self.default_template_qid = vm.qid

    def get_default_template(self):
        if self.default_template_qid is None:
            return None
        else:
            return self[self.default_template_qid]

    def set_default_netvm(self, vm):
        assert vm.is_netvm(), "VM {0} does not provide network!".format(vm.name)
        self.default_netvm_qid = vm.qid

    def get_default_netvm(self):
        if self.default_netvm_qid is None:
            return None
        else:
            return self[self.default_netvm_qid]

    def set_default_kernel(self, kernel):
        assert os.path.exists(qubes_kernels_base_dir + '/' + kernel), "Kerel {0} not installed!".format(kernel)
        self.default_kernel = kernel

    def get_default_kernel(self):
        return self.default_kernel

    def set_default_fw_netvm(self, vm):
        assert vm.is_netvm(), "VM {0} does not provide network!".format(vm.name)
        self.default_fw_netvm_qid = vm.qid

    def get_default_fw_netvm(self):
        if self.default_fw_netvm_qid is None:
            return None
        else:
            return self[self.default_fw_netvm_qid]

    def set_updatevm_vm(self, vm):
        self.updatevm_qid = vm.qid

    def get_updatevm_vm(self):
        if self.updatevm_qid is None:
            return None
        else:
            return self[self.updatevm_qid]

    def set_clockvm_vm(self, vm):
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
                print >> sys.stderr, "ERROR: The name={0} is already used by other VM with qid='{1}'!".\
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
        self.qubes_store_file = open (self.qubes_store_filename, 'w')
        self.clear()
        self.save()

    def lock_db_for_reading(self):
        self.qubes_store_file = open (self.qubes_store_filename, 'r')
        fcntl.lockf (self.qubes_store_file, fcntl.LOCK_SH)

    def lock_db_for_writing(self):
        self.qubes_store_file = open (self.qubes_store_filename, 'r+')
        fcntl.lockf (self.qubes_store_file, fcntl.LOCK_EX)

    def unlock_db(self):
        fcntl.lockf (self.qubes_store_file, fcntl.LOCK_UN)
        self.qubes_store_file.close()

    def save(self):
        root = xml.etree.ElementTree.Element(
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
        tree = xml.etree.ElementTree.ElementTree(root)

        try:

            # We need to manually truncate the file, as we open the
            # file as "r+" in the lock_db_for_writing() function
            self.qubes_store_file.seek (0, os.SEEK_SET)
            self.qubes_store_file.truncate()
            tree.write(self.qubes_store_file, "UTF-8")
        except EnvironmentError as err:
            print("{0}: export error: {1}".format(
                os.path.basename(sys.argv[0]), err))
            return False
        return True

    def parse_xml_element(self, element):
        kwargs = {}
        common_attr_list = ("qid", "name", "dir_path", "conf_file",
                "private_img", "root_img", "template_qid",
                "installed_by_rpm", "internal",
                "uses_default_netvm", "label", "memory", "vcpus", "pcidevs",
                "maxmem", "kernel", "uses_default_kernel", "kernelopts", "uses_default_kernelopts",
                "mac", "services", "include_in_backups", "debug", "drive" )

        for attribute in common_attr_list:
            kwargs[attribute] = element.get(attribute)
            if kwargs[attribute] is None:
                kwargs.pop(attribute)

        kwargs["qid"] = int(kwargs["qid"])

        if "include_in_backups" in kwargs:
            kwargs["include_in_backups"] = True if kwargs["include_in_backups"] == "True" else False

        if "installed_by_rpm" in kwargs:
            kwargs["installed_by_rpm"] = True if kwargs["installed_by_rpm"] == "True" else False

        if "internal" in kwargs:
            kwargs["internal"] = True if kwargs["internal"] == "True" else False

        if "template_qid" in kwargs:
            if kwargs["template_qid"] == "none" or kwargs["template_qid"] is None:
                kwargs.pop("template_qid")
            else:
                kwargs["template_qid"] = int(kwargs["template_qid"])
                template = self[kwargs.pop("template_qid")]
                if template is None:
                    print >> sys.stderr, "ERROR: VM '{0}' uses unkown template qid='{1}'!".\
                            format(kwargs["name"], kwargs["template_qid"])
                else:
                    kwargs["template"] = template

        if "label" in kwargs:
            if kwargs["label"] not in QubesVmLabels:
                print >> sys.stderr, "ERROR: incorrect label for VM '{0}'".format(kwargs["name"])
                kwargs.pop ("label")
            else:
                kwargs["label"] = QubesVmLabels[kwargs["label"]]

        if "kernel" in kwargs and kwargs["kernel"] == "None":
            kwargs["kernel"] = None
        if "uses_default_kernel" in kwargs:
            kwargs["uses_default_kernel"] = True if kwargs["uses_default_kernel"] == "True" else False
        else:
            # For backward compatibility
            kwargs["uses_default_kernel"] = False
        if kwargs["uses_default_kernel"]:
            kwargs["kernel"] = self.get_default_kernel()
        else:
            if "kernel" in kwargs and kwargs["kernel"]=="None":
                kwargs["kernel"]=None
            # for other cases - generic assigment is ok

        if "uses_default_kernelopts" in kwargs:
            kwargs["uses_default_kernelopts"] = False if kwargs["uses_default_kernelopts"] == "False" else True

        if "kernelopts" in kwargs and kwargs["kernelopts"] == "None":
            kwargs.pop("kernelopts")
        if "kernelopts" not in kwargs:
            kwargs["uses_default_kernelopts"] = True

        if "debug" in kwargs:
            kwargs["debug"] = True if kwargs["debug"] == "True" else False

        if "drive" in kwargs and kwargs["drive"] == "None":
            kwargs["drive"] = None

        return kwargs

    def set_netvm_dependency(self, element):
        kwargs = {}
        attr_list = ("qid", "uses_default_netvm", "netvm_qid")

        for attribute in attr_list:
            kwargs[attribute] = element.get(attribute)

        vm = self[int(kwargs["qid"])]

        if "uses_default_netvm" not in kwargs:
            vm.uses_default_netvm = True
        else:
            vm.uses_default_netvm = True if kwargs["uses_default_netvm"] == "True" else False
        if vm.uses_default_netvm is True:
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

    def load(self):
        self.clear()

        dom0vm = QubesDom0NetVm ()
        self[dom0vm.qid] = dom0vm
        self.default_netvm_qid = 0

        global dom0_vm
        dom0_vm = dom0vm

        try:
            tree = xml.etree.ElementTree.parse(self.qubes_store_file)
        except (EnvironmentError,
                xml.parsers.expat.ExpatError) as err:
            print("{0}: import error: {1}".format(
                os.path.basename(sys.argv[0]), err))
            return False

        element = tree.getroot()
        default_template = element.get("default_template")
        self.default_template_qid = int(default_template) \
                if default_template != "None" else None

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

        # Then, read in the TemplateVMs, because a reference to template VM
        # is needed to create each AppVM
        for element in tree.findall("QubesTemplateVm"):
            try:

                kwargs = self.parse_xml_element(element)

                vm = QubesTemplateVm(**kwargs)

                self[vm.qid] = vm
            except (ValueError, LookupError) as err:
                print("{0}: import error (QubesTemplateVm): {1}".format(
                    os.path.basename(sys.argv[0]), err))
                return False

        # Read in the NetVMs first, because a reference to NetVM
        # is needed to create all other VMs
        for element in tree.findall("QubesNetVm"):
            try:
                kwargs = self.parse_xml_element(element)
                # Add NetVM specific fields
                attr_list = ("netid",)

                for attribute in attr_list:
                    kwargs[attribute] = element.get(attribute)

                kwargs["netid"] = int(kwargs["netid"])

                vm = QubesNetVm(**kwargs)
                self[vm.qid] = vm

            except (ValueError, LookupError) as err:
                print("{0}: import error (QubesNetVM) {1}".format(
                    os.path.basename(sys.argv[0]), err))
                return False

        # Next read in the ProxyVMs, because they may be referenced
        # by other VMs
        for element in tree.findall("QubesProxyVm"):
            try:
                kwargs = self.parse_xml_element(element)
                # Add ProxyVM specific fields
                attr_list = ("netid",)

                for attribute in attr_list:
                    kwargs[attribute] = element.get(attribute)

                kwargs["netid"] = int(kwargs["netid"])

                vm = QubesProxyVm(**kwargs)
                self[vm.qid] = vm

            except (ValueError, LookupError) as err:
                print("{0}: import error (QubesProxyVM) {1}".format(
                    os.path.basename(sys.argv[0]), err))
                return False

        # After importing all NetVMs and ProxyVMs, set netvm references
        # 1. For TemplateVMs
        for element in tree.findall("QubesTemplateVm"):
            try:
                self.set_netvm_dependency(element)
            except (ValueError, LookupError) as err:
                print("{0}: import error (QubesTemplateVm): {1}".format(
                    os.path.basename(sys.argv[0]), err))
                return False

        # 2. For PoxyVMs
        for element in tree.findall("QubesProxyVm"):
            try:
                self.set_netvm_dependency(element)
            except (ValueError, LookupError) as err:
                print("{0}: import error (QubesProxyVM) {1}".format(
                    os.path.basename(sys.argv[0]), err))
                return False

        # Finally, read in the AppVMs
        for element in tree.findall("QubesAppVm"):
            try:
                kwargs = self.parse_xml_element(element)
                vm = QubesAppVm(**kwargs)

                self[vm.qid] = vm

                self.set_netvm_dependency(element)
            except (ValueError, LookupError) as err:
                print("{0}: import error (QubesAppVm): {1}".format(
                    os.path.basename(sys.argv[0]), err))
                return False

        # And HVMs
        for element in tree.findall("QubesHVm"):
            try:
                kwargs = self.parse_xml_element(element)
                vm = QubesHVm(**kwargs)

                self[vm.qid] = vm

                self.set_netvm_dependency(element)
            except (ValueError, LookupError) as err:
                print("{0}: import error (QubesHVm): {1}".format(
                    os.path.basename(sys.argv[0]), err))
                return False

        # Really finally, read in the DisposableVMs
        for element in tree.findall("QubesDisposableVm"):
            try:
                kwargs = {}
                attr_list = ("qid", "name",
                             "template_qid",
                             "label", "dispid", "firewall_conf" )

                for attribute in attr_list:
                    kwargs[attribute] = element.get(attribute)

                kwargs["qid"] = int(kwargs["qid"])
                kwargs["dispid"] = int(kwargs["dispid"])
                kwargs["template_qid"] = int(kwargs["template_qid"])

                template = self[kwargs.pop("template_qid")]
                if template is None:
                    print >> sys.stderr, "ERROR: DisposableVM '{0}' uses unkown template qid='{1}'!".\
                            format(kwargs["name"], kwargs["template_qid"])
                else:
                    kwargs["template"] = template

                kwargs["netvm"] = self.get_default_netvm()

                if kwargs["label"] is not None:
                    if kwargs["label"] not in QubesVmLabels:
                        print >> sys.stderr, "ERROR: incorrect label for VM '{0}'".format(kwargs["name"])
                        kwargs.pop ("label")
                    else:
                        kwargs["label"] = QubesVmLabels[kwargs["label"]]

                vm = QubesDisposableVm(**kwargs)

                self[vm.qid] = vm
            except (ValueError, LookupError) as err:
                print("{0}: import error (DisposableAppVm): {1}".format(
                    os.path.basename(sys.argv[0]), err))
                return False

        # if there was no clockvm entry in qubes.xml, try to determine default:
        # root of default NetVM chain
        if clockvm is None:
            if self.default_netvm_qid is not None:
                clockvm = self[self.default_netvm_qid]
                # Find root of netvm chain
                while clockvm.netvm is not None:
                    clockvm = clockvm.netvm

                self.clockvm_qid = clockvm.qid

        # Disable ntpd in ClockVM - to not conflict with ntpdate (both are using 123/udp port)
        if self.clockvm_qid is not None:
            self[self.clockvm_qid].services['ntpd'] = False
        return True

    def pop(self, qid):
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
            print >> sys.stderr, "Path {0} doesn't exist, assuming stale pidfile.".format(proc_path)
            return True

        f = open (proc_path)
        cmdline = f.read ()
        f.close()

#       The following doesn't work with python -- one would have to get argv[1] and compare it with self.name...
#        if not cmdline.strip().endswith(self.name):
#            print >> sys.stderr, "{0} = {1} doesn't seem to point to our process ({2}), assuming stale pidile.".format(proc_path, cmdline, self.name)
#            return True

        return False # It's a good pidfile

    def remove_pidfile(self):
        os.remove (self.path)

    def __enter__ (self):
        # assumes the pidfile doesn't exist -- you should ensure it before opening the context
        self.create_pidfile()
    def __exit__ (self):
        self.remove_pidfile()


# vim:sw=4:et:
