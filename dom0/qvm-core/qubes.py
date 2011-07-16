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

qubes_base_dir   = "/var/lib/qubes"

qubes_appvms_dir = qubes_base_dir + "/appvms"
qubes_templates_dir = qubes_base_dir + "/vm-templates"
qubes_servicevms_dir = qubes_base_dir + "/servicevms"
qubes_store_filename = qubes_base_dir + "/qubes.xml"
qubes_kernels_base_dir = qubes_base_dir + "/vm-kernels"

qubes_max_xid = 1024
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
default_servicevm_vcpus = 1

qubes_whitelisted_appmenus = 'whitelisted-appmenus.list'

dom0_update_check_interval = 6*3600

# do not allow to start a new AppVM if Dom0 mem was to be less than this
dom0_min_memory = 700*1024*1024

# We need this global reference, as each instance of QubesVm
# must be able to ask Dom0 VM about how much memory it currently has...
dom0_vm = None

qubes_appmenu_create_cmd = "/usr/lib/qubes/create_apps_for_appvm.sh"
qubes_appmenu_remove_cmd = "/usr/lib/qubes/remove_appvm_appmenus.sh"
qubes_pciback_cmd = '/usr/lib/qubes/unbind_pci_device.sh'

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
            info = xc.domain_getinfo(0, qubes_max_xid)
            for vm in info:
                previous[vm['domid']] = {}
                previous[vm['domid']]['cpu_time'] = vm['cpu_time']/vm['online_vcpus']
                previous[vm['domid']]['cpu_usage'] = 0
            time.sleep(wait_time)

        current_time = time.time()
        current = {}
        info = xc.domain_getinfo(0, qubes_max_xid)
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

    def __init__(self, qid, name,
                 dir_path, conf_file = None,
                 uses_default_netvm = True,
                 netvm_vm = None,
                 installed_by_rpm = False,
                 updateable = False,
                 label = None,
                 root_img = None,
                 private_img = None,
                 memory = default_memory,
                 maxmem = None,
                 template_vm = None,
                 firewall_conf = None,
                 volatile_img = None,
                 pcidevs = None,
                 internal = False,
                 vcpus = None,
                 kernel = None,
                 uses_default_kernel = True):


        assert qid < qubes_max_qid, "VM id out of bounds!"
        self.__qid = qid
        self.name = name

        dir_path = dir_path
        self.dir_path = dir_path
        conf_file = conf_file
        if self.dir_path is not None:
            if (conf_file is None):
                self.conf_file = dir_path + "/" + name + ".conf"
            else:
                if os.path.isabs(conf_file):
                    self.conf_file = conf_file
                else:
                    self.conf_file = dir_path + "/" + conf_file

        self.uses_default_netvm = uses_default_netvm
        self.netvm_vm = netvm_vm
        if netvm_vm is not None:
            netvm_vm.connected_vms[qid] = self

        # We use it in remove from disk to avoid removing rpm files (for templates)
        self.installed_by_rpm = installed_by_rpm

        # Setup standard VM storage; some VM types may not use them all
        if root_img is not None and os.path.isabs(root_img):
            self.root_img = root_img
        else:
            self.root_img = dir_path + "/" + (
                root_img if root_img is not None else default_root_img)

        self.volatile_img = dir_path + "/" + default_volatile_img

        if private_img is not None and os.path.isabs(private_img):
            self.private_img = private_img
        else:
            self.private_img = dir_path + "/" + (
                private_img if private_img is not None else default_private_img)

        if firewall_conf is None:
            self.firewall_conf = dir_path + "/" + default_firewall_conf_file
        else:
            self.firewall_conf = firewall_conf

        self.updateable = updateable
        self.label = label if label is not None else QubesVmLabels["red"]
        if self.dir_path is not None:
            self.icon_path = self.dir_path + "/icon.png"
        else:
            self.icon_path = None

        # PCI devices - used only by NetVM
        if pcidevs is None or pcidevs == "none":
            self.pcidevs = []
        elif pcidevs.find('[') < 0:
            # Backward compatibility
            self.pcidevs = eval('[' + pcidevs + ']')
        else:
            self.pcidevs  = eval(pcidevs)

        self.memory = memory

        if maxmem is None:
            host = QubesHost()
            total_mem_mb = host.memory_total/1024
            self.maxmem = total_mem_mb/2
        else:
            self.maxmem = maxmem

        self.template_vm = template_vm
        if template_vm is not None:
            if updateable:
                print "ERROR: Template based VM cannot be updateable!"
                return False
            if not template_vm.is_template():
                print "ERROR: template_qid={0} doesn't point to a valid TemplateVM".\
                    format(template_vm.qid)
                return False

            template_vm.appvms[qid] = self
        else:
            assert self.root_img is not None, "Missing root_img for standalone VM!"

        self.kernel = kernel

        if template_vm is not None:
            self.kernels_dir = template_vm.kernels_dir
        elif self.kernel is not None:
            self.kernels_dir = qubes_kernels_base_dir + "/" + self.kernel
        else:
            # for backward compatibility (or another rare case): kernel=None -> kernel in VM dir
            self.kernels_dir = self.dir_path + "/" + default_kernels_subdir

        self.uses_default_kernel = uses_default_kernel

        self.appmenus_templates_dir = None
        if updateable:
            self.appmenus_templates_dir = self.dir_path + "/" + default_appmenus_templates_subdir
        elif template_vm is not None:
            self.appmenus_templates_dir = template_vm.appmenus_templates_dir

        # By default allow use all VCPUs
        if vcpus is None:
            qubes_host = QubesHost()
            self.vcpus = qubes_host.no_cpus
        else:
            self.vcpus = vcpus

        # Internal VM (not shown in qubes-manager, doesn't create appmenus entries
        self.internal = internal

        self.xid = -1
        self.xid = self.get_xid()

    @property
    def qid(self):
        return self.__qid

    @property
    def ip(self):
        if self.netvm_vm is not None:
            return self.netvm_vm.get_ip_for_vm(self.qid)
        else:
            return None

    @property
    def netmask(self):
        if self.netvm_vm is not None:
            return self.netvm_vm.netmask
        else:
            return None

    @property
    def gateway(self):
        if self.netvm_vm is not None:
            return self.netvm_vm.gateway
        else:
            return None

    @property
    def secondary_dns(self):
        if self.netvm_vm is not None:
            return self.netvm_vm.secondary_dns
        else:
            return None

    def is_updateable(self):
        return self.updateable

    def is_networked(self):
        if self.is_netvm():
            return True

        if self.netvm_vm is not None:
            return True
        else:
            return False

    def set_updateable(self):
        if self.is_updateable():
            return

        raise QubesException ("Change 'updateable' flag is not supported. Please use qvm-create.")

    def set_nonupdateable(self):
        if not self.is_updateable():
            return

        raise QubesException ("Change 'updateable' flag is not supported. Please use qvm-create.")

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
            domains = xc.domain_getinfo(start_xid, qubes_max_xid-start_xid)
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
            uuid = uuid.UUID(''.join('%02x' % b for b in dominfo.uuid))
            return uuid
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
            elif dominfo['shutdown']:
                return "Halted"
            elif dominfo['crashed']:
                return "Crashed"
            elif dominfo['dying']:
                return "Dying"
            else:
                return "Running"
        else:
            return 'Halted'

        return "NA"

    def is_running(self):
        if self.get_power_state() == "Running":
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
            return 0

        dominfo = self.get_xl_dominfo()

        uuid = self.get_uuid()

        start_time = xs.read('', "/vm/%s/start_time" % str(uuid))

        return start_time

    def is_outdated(self):
        # Makes sense only on VM based on template
        if self.template_vm is None:
            return False

        if not self.is_running():
            return False

        rootimg_inode = os.stat(self.template_vm.root_img)
        rootcow_inode = os.stat(self.template_vm.rootcow_img)

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
        f_private = open (self.private_img, "a+b")
        f_private.truncate (size)
        f_private.close ()

    def cleanup_vifs(self):
        """
        Xend does not remove vif when backend domain is down, so we must do it
        manually
        """

        if not self.is_running():
            return

        p = subprocess.Popen (["/usr/sbin/xl", "network-list", self.name],
                 stdout=subprocess.PIPE)
        result = p.communicate()
        for line in result[0].split('\n'):
            m = re.match(r"^(\d+)\s*(\d+)", line)
            if m:
                retcode = subprocess.call(["/usr/sbin/xl", "list", m.group(2)],
                        stderr=subprocess.PIPE)
                if retcode != 0:
                    # Don't check retcode - it always will fail when backend domain is down
                    subprocess.call(["/usr/sbin/xl",
                            "network-detach", self.name, m.group(1)], stderr=subprocess.PIPE)

    def create_xenstore_entries(self, xid):
        if dry_run:
            return

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

        if self.netvm_vm is not None:
            xs.write('', "{0}/qubes_ip".format(domain_path), self.ip)
            xs.write('', "{0}/qubes_netmask".format(domain_path),
                    self.netvm_vm.netmask)
            xs.write('', "{0}/qubes_gateway".format(domain_path),
                    self.netvm_vm.gateway)
            xs.write('',
                    "{0}/qubes_secondary_dns".format(domain_path),
                    self.netvm_vm.secondary_dns)

        # Fix permissions
        xs.set_permissions('', '{0}/device'.format(domain_path),
                [{ 'dom': xid }])
        xs.set_permissions('', '{0}/memory'.format(domain_path),
                [{ 'dom': xid }])

    def get_rootdev(self, source_template=None):
        if self.template_vm:
            return "'script:snapshot:{dir}/root.img:{dir}/root-cow.img,xvda,r',".format(dir=self.template_vm.dir_path)
        else:
            return "'script:file:{dir}/root.img,xvda,w',".format(dir=self.dir_path)

    def get_config_params(self, source_template=None):
        args = {}
        args['name'] = self.name
        args['kerneldir'] = self.kernels_dir
        args['vmdir'] = self.dir_path
        args['pcidev'] = str(self.pcidevs).strip('[]')
        args['mem'] = str(self.memory)
        args['maxmem'] = str(self.maxmem)
        args['vcpus'] = str(self.vcpus)
        if self.netvm_vm is not None:
            args['netdev'] = "'script=/etc/xen/scripts/vif-route-qubes,ip={ip}".format(ip=self.ip)
            if self.netvm_vm.qid != 0:
                args['netdev'] += ",backend={0}".format(self.netvm_vm.name)
            args['netdev'] += "'"
        else:
            args['netdev'] = ''
        args['rootdev'] = self.get_rootdev(source_template=source_template)
        args['privatedev'] = "'script:file:{dir}/private.img,xvdb,w',".format(dir=self.dir_path)
        args['volatiledev'] = "'script:file:{dir}/volatile.img,xvdc,w',".format(dir=self.dir_path)
        args['otherdevs'] = "'script:file:{dir}/modules.img,xvdd,r',".format(dir=self.kernels_dir)
        args['kernelopts'] = ''

        return args

    def create_config_file(self, file_path = None, source_template = None, prepare_dvm = False):
        if file_path is None:
            file_path = self.conf_file
        if source_template is None:
            source_template = self.template_vm

        f_conf_template = open('/usr/share/qubes/vm-template.conf', 'r')
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
            source_template = self.template_vm
        assert source_template is not None

        if dry_run:
            return

        if verbose:
            print "--> Creating directory: {0}".format(self.dir_path)
        os.mkdir (self.dir_path)

        if verbose:
            print "--> Creating the VM config file: {0}".format(self.conf_file)

        self.create_config_file(source_template = source_template)

        template_priv = source_template.private_img
        if verbose:
            print "--> Copying the template's private image: {0}".\
                    format(template_priv)

        # We prefer to use Linux's cp, because it nicely handles sparse files
        retcode = subprocess.call (["cp", template_priv, self.private_img])
        if retcode != 0:
            raise IOError ("Error while copying {0} to {1}".\
                           format(template_priv, self.private_img))

        if os.path.exists(source_template.dir_path + '/vm-' + qubes_whitelisted_appmenus):
            if verbose:
                print "--> Creating default whitelisted apps list: {0}".\
                    format(self.dir_path + '/' + qubes_whitelisted_appmenus)
            shutil.copy(source_template.dir_path + '/vm-' + qubes_whitelisted_appmenus,
                    self.dir_path + '/' + qubes_whitelisted_appmenus)

        if self.is_updateable():
            template_root = source_template.root_img
            if verbose:
                print "--> Copying the template's root image: {0}".\
                        format(template_root)

            # We prefer to use Linux's cp, because it nicely handles sparse files
            retcode = subprocess.call (["cp", template_root, self.root_img])
            if retcode != 0:
                raise IOError ("Error while copying {0} to {1}".\
                               format(template_root, self.root_img))

        # Create volatile.img
        self.reset_volatile_storage(source_template = source_template, verbose=verbose)

    def create_appmenus(self, verbose, source_template = None):
        if source_template is None:
            source_template = self.template_vm

        try:
            if source_template is not None:
                subprocess.check_call ([qubes_appmenu_create_cmd, source_template.appmenus_templates_dir, self.name])
            else:
                # Only add apps to menu
                subprocess.check_call ([qubes_appmenu_create_cmd, "none", self.name, vmtype])
        except subprocess.CalledProcessError:
            print "Ooops, there was a problem creating appmenus for {0} VM!".format (self.name)

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
            source_template = self.template_vm

        # Only makes sense on template based VM
        if source_template is None:
            return

        if verbose:
            print "--> Cleaning volatile image: {0}...".format (self.volatile_img)
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
        root = xml.etree.ElementTree.Element(
                "QubesFirwallRules",
                policy = "allow" if conf["allow"] else "deny",
                dns = "allow" if conf["allowDns"] else "deny",
                icmp = "allow" if conf["allowIcmp"] else "deny"
        )

        for rule in conf["rules"]:
            element = xml.etree.ElementTree.Element(
                    "rule",
                    address=rule["address"],
                    port=str(rule["portBegin"]),
            )
            if rule["netmask"] is not None and rule["netmask"] != 32:
                element.set("netmask", str(rule["netmask"]))
            if rule["portEnd"] is not None:
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
            print "{0}: save error: {1}".format(
                    os.path.basename(sys.argv[0]), err)
            return False

        return True

    def has_firewall(self):
        return os.path.exists (self.firewall_conf)

    def get_firewall_conf(self):
        conf = { "rules": list(), "allow": True, "allowDns": True, "allowIcmp": True }

        try:
            tree = xml.etree.ElementTree.parse(self.firewall_conf)
            root = tree.getroot()

            conf["allow"] = (root.get("policy") == "allow")
            conf["allowDns"] = (root.get("dns") == "allow")
            conf["allowIcmp"] = (root.get("icmp") == "allow")

            for element in root:
                rule = {}
                attr_list = ("address", "netmask", "port", "toport")

                for attribute in attr_list:
                    rule[attribute] = element.get(attribute)

                if rule["netmask"] is not None:
                    rule["netmask"] = int(rule["netmask"])
                else:
                    rule["netmask"] = 32

                rule["portBegin"] = int(rule["port"])

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

    def start(self, debug_console = False, verbose = False, preparing_dvm = False):
        if dry_run:
            return

        if self.is_running():
            raise QubesException ("VM is already running!")

        if self.netvm_vm is not None:
            if self.netvm_vm.qid != 0:
                if not self.netvm_vm.is_running():
                    if verbose:
                        print "--> Starting NetVM {0}...".format(self.netvm_vm.name)
                    self.netvm_vm.start()

        self.reset_volatile_storage(verbose=verbose)
        if verbose:
            print "--> Loading the VM (type = {0})...".format(self.type)

        # refresh config file
        self.create_config_file()

        mem_required = int(self.memory) * 1024 * 1024
        qmemman_client = QMemmanClient()
        if not qmemman_client.request_memory(mem_required):
            qmemman_client.close()
            raise MemoryError ("ERROR: insufficient memory to start this VM")

        # Bind pci devices to pciback driver
        for pci in self.pcidevs:
            subprocess.check_call(['sudo', qubes_pciback_cmd, pci])

        xl_cmdline = ['sudo', '/usr/sbin/xl', 'create', self.conf_file, '-p']

        try:
            subprocess.check_call(xl_cmdline)
        except:
            raise QubesException("Failed to load VM config")
        finally:
            qmemman_client.close() # let qmemman_daemon resume balancing

        xid = self.get_xid()
        self.xid = xid

        if verbose:
            print "--> Setting Xen Store info for the VM..."
        self.create_xenstore_entries(xid)

        qvm_collection = QubesVmCollection()
        qvm_collection.lock_db_for_reading()
        qvm_collection.load()
        qvm_collection.unlock_db()

        if verbose:
            print "--> Updating firewall rules..."
        for vm in qvm_collection.values():
            if vm.is_proxyvm() and vm.is_running():
                vm.write_iptables_xenstore_entry()

        if verbose:
            print "--> Starting the VM..."
        xc.domain_unpause(xid)

        if not preparing_dvm:
            if verbose:
                print "--> Starting the qrexec daemon..."
            retcode = subprocess.call ([qrexec_daemon_path, str(xid)])
            if (retcode != 0) :
                self.force_shutdown()
                raise OSError ("ERROR: Cannot execute qrexec_daemon!")

        if preparing_dvm:
            if verbose:
                print "--> Preparing config template for DispVM"
            self.create_config_file(file_path = self.dir_path + '/dvm.conf', prepare_dvm = True)

        # perhaps we should move it before unpause and fork?
        # FIXME: this uses obsolete xm api
        if debug_console:
            from xen.xm import console
            if verbose:
                print "--> Starting debug console..."
            console.execConsole (xid)

        return xid

    def force_shutdown(self):
        if dry_run:
            return

        subprocess.call (['/usr/sbin/xl', 'destroy', self.name])
        #xc.domain_destroy(self.get_xid())

    def remove_from_disk(self):
        if dry_run:
            return


        shutil.rmtree (self.dir_path)

    def get_xml_attrs(self):
        attrs = {}
        attrs["qid"]  = str(self.qid)
        attrs["name"] = self.name
        attrs["dir_path"] = self.dir_path
        attrs["conf_file"] = self.conf_file
        attrs["root_img"] = self.root_img
        attrs["volatile_img"] = self.volatile_img
        attrs["private_img"] = self.private_img
        attrs["uses_default_netvm"] = str(self.uses_default_netvm)
        attrs["netvm_qid"] = str(self.netvm_vm.qid) if self.netvm_vm is not None else "none"
        attrs["installed_by_rpm"] = str(self.installed_by_rpm)
        attrs["template_qid"] = str(self.template_vm.qid) if self.template_vm and not self.is_updateable() else "none"
        attrs["updateable"] = str(self.updateable)
        attrs["label"] = self.label.name
        attrs["memory"] = str(self.memory)
        attrs["maxmem"] = str(self.maxmem)
        attrs["pcidevs"] = str(self.pcidevs)
        attrs["vcpus"] = str(self.vcpus)
        attrs["internal"] = str(self.internal)
        attrs["uses_default_kernel"] = str(self.uses_default_kernel)
        attrs["kernel"] = str(self.kernel)
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
    def __init__(self, **kwargs):

        if "dir_path" not in kwargs or kwargs["dir_path"] is None:
            kwargs["dir_path"] = qubes_templates_dir + "/" + kwargs["name"]

        if "updateable" not in kwargs or kwargs["updateable"] is None :
            kwargs["updateable"] = True

        if "label" not in kwargs or kwargs["label"] == None:
            kwargs["label"] = default_template_label

        super(QubesTemplateVm, self).__init__(**kwargs)

        dir_path = kwargs["dir_path"]

        # Clean image for root-cow and swap (AppVM side)
        self.clean_volatile_img = self.dir_path + "/" + default_clean_volatile_img

        # Image for template changes
        self.rootcow_img = self.dir_path + "/" + default_rootcow_img

        self.appmenus_templates_dir = self.dir_path + "/" + default_appmenus_templates_subdir
        self.appvms = QubesVmCollection()

    @property
    def type(self):
        return "TemplateVM"

    def set_updateable(self):
        if self.is_updateable():
            return

        assert not self.is_running()
        # Make sure that all the AppVMs are non-updateable...
        for appvm in self.appvms.values():
            if appvm.is_updateable():
                raise QubesException("One of the AppVMs ('{0}')is also 'updateable'\
                                     -- cannot make the TemplateVM {'{1}'} 'nonupdatable'".\
                                     format (appvm.name, self.name))
        self.updateable = True

    def get_rootdev(self, source_template=None):
        return "'script:origin:{dir}/root.img:{dir}/root-cow.img,xvda,w',".format(dir=self.dir_path)

    def clone_disk_files(self, src_template_vm, verbose):
        if dry_run:
            return


        assert not src_template_vm.is_running(), "Attempt to clone a running Template VM!"

        if verbose:
            print "--> Creating directory: {0}".format(self.dir_path)
        os.mkdir (self.dir_path)

        if verbose:
            print "--> Creating VM config file: {0}".\
                    format(self.conf_file)
        self.create_config_file(source_template=src_template_vm)

        if verbose:
            print "--> Copying the template's private image:\n{0} ==>\n{1}".\
                    format(src_template_vm.private_img, self.private_img)
        # We prefer to use Linux's cp, because it nicely handles sparse files
        retcode = subprocess.call (["cp", src_template_vm.private_img, self.private_img])
        if retcode != 0:
            raise IOError ("Error while copying {0} to {1}".\
                           format(src_template_vm.private_img, self.private_img))

        if verbose:
            print "--> Copying the template's root image:\n{0} ==>\n{1}".\
                    format(src_template_vm.root_img, self.root_img)
        # We prefer to use Linux's cp, because it nicely handles sparse files
        retcode = subprocess.call (["cp", src_template_vm.root_img, self.root_img])
        if retcode != 0:
            raise IOError ("Error while copying {0} to {1}".\
                           format(src_template_vm.root_img, self.root_img))
        if verbose:
            print "--> Copying the template's clean volatile image:\n{0} ==>\n{1}".\
                    format(src_template_vm.clean_volatile_img, self.clean_volatile_img)
        # We prefer to use Linux's cp, because it nicely handles sparse files
        retcode = subprocess.call (["cp", src_template_vm.clean_volatile_img, self.clean_volatile_img])
        if retcode != 0:
            raise IOError ("Error while copying {0} to {1}".\
                           format(src_template_vm.clean_volatile_img, self.clean_volatile_img))
        if verbose:
            print "--> Copying the template's volatile image:\n{0} ==>\n{1}".\
                    format(self.clean_volatile_img, self.volatile_img)
        # We prefer to use Linux's cp, because it nicely handles sparse files
        retcode = subprocess.call (["cp", self.clean_volatile_img, self.volatile_img])
        if retcode != 0:
            raise IOError ("Error while copying {0} to {1}".\
                           format(self.clean_volatile_img, self.volatile_img))
        if verbose:
            print "--> Copying the template's appmenus templates dir:\n{0} ==>\n{1}".\
                    format(src_template_vm.appmenus_templates_dir, self.appmenus_templates_dir)
        shutil.copytree (src_template_vm.appmenus_templates_dir, self.appmenus_templates_dir)

        if os.path.exists(src_template_vm.dir_path + '/' + qubes_whitelisted_appmenus):
            if verbose:
                print "--> Copying whitelisted apps list: {0}".\
                    format(self.dir_path + '/' + qubes_whitelisted_appmenus)
            shutil.copy(src_template_vm.dir_path + '/' + qubes_whitelisted_appmenus,
                    self.dir_path + '/' + qubes_whitelisted_appmenus)

        if os.path.exists(src_template_vm.dir_path + '/vm-' + qubes_whitelisted_appmenus):
            if verbose:
                print "--> Copying default whitelisted apps list: {0}".\
                    format(self.dir_path + '/vm-' + qubes_whitelisted_appmenus)
            shutil.copy(src_template_vm.dir_path + '/vm-' + qubes_whitelisted_appmenus,
                    self.dir_path + '/vm-' + qubes_whitelisted_appmenus)

        icon_path = "/usr/share/qubes/icons/template.png"
        if verbose:
            print "--> Creating icon symlink: {0} -> {1}".format(self.icon_path, icon_path)
        os.symlink (icon_path, self.icon_path)

        # Create root-cow.img
        self.commit_changes(verbose=verbose)

        # Create appmenus
        self.create_appmenus(verbose, source_template = src_template_vm)

    def create_appmenus(self, verbose, source_template = None):
        if source_template is None:
            source_template = self.template_vm

        try:
            subprocess.check_call ([qubes_appmenu_create_cmd, self.appmenus_templates_dir, self.name, "vm-templates"])
        except subprocess.CalledProcessError:
            print "Ooops, there was a problem creating appmenus for {0} VM!".format (self.name)

    def remove_from_disk(self):
        if dry_run:
            return

        subprocess.check_call ([qubes_appmenu_remove_cmd, self.name, "vm-templates"])
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

    def start(self, debug_console = False, verbose = False, preparing_dvm=False):
        if dry_run:
            return

        self.reset_volatile_storage(verbose=verbose)

        if not self.is_updateable():
            raise QubesException ("Cannot start Template VM that is marked \"nonupdatable\"")

        # TODO?: check if none of running appvms are outdated

        return super(QubesTemplateVm, self).start(debug_console=debug_console, verbose=verbose)

    def reset_volatile_storage(self, verbose = False):
        assert not self.is_running(), "Attempt to clean volatile image of running Template VM!"

        if verbose:
            print "--> Cleaning volatile image: {0}...".format (self.volatile_img)
        if dry_run:
            return
        if os.path.exists (self.volatile_img):
           os.remove (self.volatile_img)

        retcode = subprocess.call (["tar", "xf", self.clean_volatile_img, "-C", self.dir_path])
        if retcode != 0:
            raise IOError ("Error while unpacking {0} to {1}".\
                           format(self.template_vm.clean_volatile_img, self.volatile_img))

    def commit_changes (self, verbose = False):

        assert not self.is_running(), "Attempt to commit changes on running Template VM!"

        if verbose:
            print "--> Commiting template updates... COW: {0}...".format (self.rootcow_img)

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

    def get_xml_attrs(self):
        attrs = super(QubesTemplateVm, self).get_xml_attrs()
        attrs["clean_volatile_img"] = self.clean_volatile_img
        attrs["rootcow_img"] = self.rootcow_img
        return attrs

class QubesNetVm(QubesVm):
    """
    A class that represents a NetVM. A child of QubesCowVM.
    """
    def __init__(self, **kwargs):
        netid = kwargs.pop("netid")
        self.netid = netid
        self.__network = "10.137.{0}.0".format(netid)
        self.netprefix = "10.137.{0}.".format(netid)
        self.dispnetprefix = "10.138.{0}.".format(netid)
        self.__netmask = vm_default_netmask
        self.__gateway = self.netprefix + "1"
        self.__secondary_dns = self.netprefix + "254"

        if "dir_path" not in kwargs or kwargs["dir_path"] is None:
            kwargs["dir_path"] = qubes_servicevms_dir + "/" + kwargs["name"]
        self.__external_ip_allowed_xids = set()

        if "label" not in kwargs or kwargs["label"] is None:
            kwargs["label"] = default_servicevm_label

        if "vcpus" not in kwargs or kwargs["vcpus"] is None:
            kwargs["vcpus"] = default_servicevm_vcpus

        if "memory" not in kwargs or kwargs["memory"] is None:
            kwargs["memory"] = 200

        kwargs["maxmem"] = kwargs["memory"]

        super(QubesNetVm, self).__init__(**kwargs)
        self.connected_vms = QubesVmCollection()

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

    def get_config_params(self, source_template=None):
        args = super(QubesNetVm, self).get_config_params(source_template)
        args['kernelopts'] = ' swiotlb=force pci=nomsi'
        return args

    def create_xenstore_entries(self, xid):
        if dry_run:
            return

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

        command.append("r{0}".format(xid,xid))
        command.append("w{0}".format(xid,xid))

        for id in self.__external_ip_allowed_xids:
            command.append("r{0}".format(id))

        return subprocess.check_call(command)

    def start(self, debug_console = False, verbose = False, preparing_dvm=False):
        if dry_run:
            return

        xid=super(QubesNetVm, self).start(debug_console=debug_console, verbose=verbose)

        # Connect vif's of already running VMs
        for vm in self.connected_vms.values():
            if not vm.is_running():
                continue

            if verbose:
                print "--> Attaching network to '{0}'...".format(vm.name)

            # Cleanup stale VIFs
            vm.cleanup_vifs()

            xm_cmdline = ["/usr/sbin/xl", "network-attach", vm.name, "script=vif-route-qubes", "ip="+vm.ip, "backend="+self.name ]
            retcode = subprocess.call (xm_cmdline)
            if retcode != 0:
                print ("WARNING: Cannot attach to network to '{0}'!".format(vm.name))
        return xid

    def add_external_ip_permission(self, xid):
        if int(xid) < 0:
            return
        self.__external_ip_allowed_xids.add(int(xid))
        self.update_external_ip_permissions()

    def remove_external_ip_permission(self, xid):
        self.__external_ip_allowed_xids.discard(int(xid))
        self.update_external_ip_permissions()

    def get_xml_attrs(self):
        attrs = super(QubesNetVm, self).get_xml_attrs()
        attrs.pop("netvm_qid")
        attrs.pop("uses_default_netvm")
        attrs["netid"] = str(self.netid)
        return attrs

class QubesProxyVm(QubesNetVm):
    """
    A class that represents a ProxyVM, ex FirewallVM. A child of QubesNetVM.
    """
    def __init__(self, **kwargs):
        kwargs["uses_default_netvm"] = False
        super(QubesProxyVm, self).__init__(**kwargs)
        self.rules_applied = None

    @property
    def type(self):
        return "ProxyVM"

    def start(self, debug_console = False, verbose = False, preparing_dvm = False):
        if dry_run:
            return
        retcode = super(QubesProxyVm, self).start(debug_console=debug_console, verbose=verbose, preparing_dvm=preparing_dvm)
        self.netvm_vm.add_external_ip_permission(self.get_xid())
        self.write_netvm_domid_entry()
        return retcode

    def force_shutdown(self):
        if dry_run:
            return
        self.netvm_vm.remove_external_ip_permission(self.get_xid())
        super(QubesProxyVm, self).force_shutdown()

    def create_xenstore_entries(self, xid):
        if dry_run:
            return

        super(QubesProxyVm, self).create_xenstore_entries(xid)
        xs.write('', "/local/domain/{0}/qubes_iptables_error".format(xid), '')
        xs.set_permissions('', "/local/domain/{0}/qubes_iptables_error".format(xid),
                [{ 'dom': xid, 'write': True }])
        self.write_iptables_xenstore_entry()

    def write_netvm_domid_entry(self, xid = -1):
        if xid < 0:
            xid = self.get_xid()

        xs.write('', "/local/domain/{0}/qubes_netvm_domid".format(xid),
                "{0}".format(self.netvm_vm.get_xid()))

    def write_iptables_xenstore_entry(self):
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

        vms = [vm for vm in self.connected_vms.values()]
        for vm in vms:
            if vm.has_firewall():
                conf = vm.get_firewall_conf()
            else:
                conf = { "rules": list(), "allow": True, "allowDns": True, "allowIcmp": True }

            xid = vm.get_xid()
            if xid < 0: # VM not active ATM
                continue

            iptables += "# '{0}' VM:\n".format(vm.name)
            iptables += "-A FORWARD ! -s {0}/32 -i vif{1}.+ -j DROP\n".format(vm.ip, xid)

            accept_action = "ACCEPT"
            reject_action = "REJECT --reject-with icmp-host-prohibited"

            if conf["allow"]:
                default_action = accept_action
                rules_action = reject_action
            else:
                default_action = reject_action
                rules_action = accept_action

            for rule in conf["rules"]:
                iptables += "-A FORWARD -i vif{0}.+ -d {1}".format(xid, rule["address"])
                if rule["netmask"] != 32:
                    iptables += "/{0}".format(rule["netmask"])

                if rule["portBegin"] is not None and rule["portBegin"] > 0:
                    iptables += " -p tcp --dport {0}".format(rule["portBegin"])
                    if rule["portEnd"] is not None and rule["portEnd"] > rule["portBegin"]:
                        iptables += ":{0}".format(rule["portEnd"])

                iptables += " -j {0}\n".format(rules_action)

            if conf["allowDns"]:
                # PREROUTING does DNAT to NetVM DNSes, so we need self.netvm_vm. properties
                iptables += "-A FORWARD -i vif{0}.+ -p udp -d {1} --dport 53 -j ACCEPT\n".format(xid,self.netvm_vm.gateway)
                iptables += "-A FORWARD -i vif{0}.+ -p udp -d {1} --dport 53 -j ACCEPT\n".format(xid,self.netvm_vm.secondary_dns)
            if conf["allowIcmp"]:
                iptables += "-A FORWARD -i vif{0}.+ -p icmp -j ACCEPT\n".format(xid)

            iptables += "-A FORWARD -i vif{0}.+ -j {1}\n".format(xid, default_action)

        iptables += "#End of VM rules\n"
        iptables += "-A FORWARD -j DROP\n"

        iptables += "COMMIT"

        self.write_netvm_domid_entry()

        self.rules_applied = None
        xs.write('', "/local/domain/{0}/qubes_iptables".format(self.get_xid()), iptables)

    def get_xml_attrs(self):
        attrs = super(QubesProxyVm, self).get_xml_attrs()
        attrs["netvm_qid"] = str(self.netvm_vm.qid) if self.netvm_vm is not None else "none"
        return attrs

class QubesDom0NetVm(QubesNetVm):
    def __init__(self):
        super(QubesDom0NetVm, self).__init__(qid=0, name="dom0", netid=0,
                                             dir_path=None,
                                             private_img = None,
                                             template_vm = None,
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

    def start(self, debug_console = False, verbose = False):
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
    def __init__(self, **kwargs):

        template_vm = kwargs["template_vm"]
        assert template_vm is not None, "Missing template_vm for DisposableVM!"

        self.dispid = kwargs.pop("dispid")

        super(QubesDisposableVm, self).__init__(dir_path="/nonexistent", **kwargs)

    @property
    def type(self):
        return "DisposableVM"

    @property
    def ip(self):
        if self.netvm_vm is not None:
            return self.netvm_vm.get_ip_for_dispvm(self.dispid)
        else:
            return None


    def get_xml_attrs(self):
        attrs = {}
        attrs["qid"] = str(self.qid)
        attrs["name"] = self.name
        attrs["dispid"] = str(self.dispid)
        attrs["template_qid"] = str(self.template_vm.qid)
        attrs["label"] = self.label.name
        return attrs

    def verify_files(self):
        return True


class QubesAppVm(QubesVm):
    """
    A class that represents an AppVM. A child of QubesVm.
    """
    def __init__(self, **kwargs):

        if "dir_path" not in kwargs or kwargs["dir_path"] is None:
            kwargs["dir_path"] = qubes_appvms_dir + "/" + kwargs["name"]

        super(QubesAppVm, self).__init__(**kwargs)

    @property
    def type(self):
        return "AppVM"

    def create_on_disk(self, verbose, source_template = None):
        if dry_run:
            return

        super(QubesAppVm, self).create_on_disk(verbose, source_template=source_template)

        if verbose:
            print "--> Creating icon symlink: {0} -> {1}".format(self.icon_path, self.label.icon_path)
        os.symlink (self.label.icon_path, self.icon_path)

        if not self.internal:
            self.create_appmenus (verbose, source_template=source_template)

    def remove_from_disk(self):
        if dry_run:
            return

        subprocess.check_call ([qubes_appmenu_remove_cmd, self.name])
        super(QubesAppVm, self).remove_from_disk()


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


    def add_new_appvm(self, name, template_vm,
                      dir_path = None, conf_file = None,
                      private_img = None,
                      updateable = False,
                      label = None):

        qid = self.get_new_unused_qid()
        vm = QubesAppVm (qid=qid, name=name, template_vm=template_vm,
                         dir_path=dir_path, conf_file=conf_file,
                         private_img=private_img,
                         netvm_vm = self.get_default_netvm_vm(),
                         kernel = self.get_default_kernel(),
                         uses_default_kernel = True,
                         updateable=updateable,
                         label=label)

        if not self.verify_new_vm (vm):
            assert False, "Wrong VM description!"
        self[vm.qid]=vm
        return vm

    def add_new_disposablevm(self, name, template_vm, dispid,
                      label = None):

        qid = self.get_new_unused_qid()
        vm = QubesDisposableVm (qid=qid, name=name, template_vm=template_vm,
                         netvm_vm = self.get_default_netvm_vm(),
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
                              netvm_vm = self.get_default_netvm_vm(),
                              kernel = self.get_default_kernel(),
                              uses_default_kernel = True)

        if not self.verify_new_vm (vm):
            assert False, "Wrong VM description!"
        self[vm.qid]=vm

        if self.default_template_qid is None:
            self.set_default_template_vm(vm)

        return vm

    def clone_templatevm(self, src_template_vm, name, dir_path = None, verbose = False):

        assert not src_template_vm.is_running(), "Attempt to clone a running Template VM!"

        vm = self.add_new_templatevm (name=name, dir_path=dir_path, installed_by_rpm = False)

        return vm


    def add_new_netvm(self, name, template_vm,
                      dir_path = None, conf_file = None,
                      private_img = None, installed_by_rpm = False,
                      label = None, updateable = False):

        qid = self.get_new_unused_qid()
        netid = self.get_new_unused_netid()
        vm = QubesNetVm (qid=qid, name=name, template_vm=template_vm,
                         netid=netid, label=label,
                         private_img=private_img, installed_by_rpm=installed_by_rpm,
                         updateable=updateable,
                         kernel = self.get_default_kernel(),
                         uses_default_kernel = True,
                         dir_path=dir_path, conf_file=conf_file)

        if not self.verify_new_vm (vm):
            assert False, "Wrong VM description!"
        self[vm.qid]=vm

        if self.default_fw_netvm_qid is None:
            self.set_default_fw_netvm_vm(vm)

        return vm

    def add_new_proxyvm(self, name, template_vm,
                     dir_path = None, conf_file = None,
                     private_img = None, installed_by_rpm = False,
                     label = None, updateable = False):

        qid = self.get_new_unused_qid()
        netid = self.get_new_unused_netid()
        vm = QubesProxyVm (qid=qid, name=name, template_vm=template_vm,
                              netid=netid, label=label,
                              private_img=private_img, installed_by_rpm=installed_by_rpm,
                              dir_path=dir_path, conf_file=conf_file,
                              updateable=updateable,
                              kernel = self.get_default_kernel(),
                              uses_default_kernel = True,
                              netvm_vm = self.get_default_fw_netvm_vm())

        if not self.verify_new_vm (vm):
            assert False, "Wrong VM description!"
        self[vm.qid]=vm

        if self.default_netvm_qid is None:
            self.set_default_netvm_vm(vm)

        if self.updatevm_qid is None:
            self.set_updatevm_vm(vm)

        return vm

    def set_default_template_vm(self, vm):
        assert vm.is_template(), "VM {0} is not a TemplateVM!".format(vm.name)
        self.default_template_qid = vm.qid

    def get_default_template_vm(self):
        if self.default_template_qid is None:
            return None
        else:
            return self[self.default_template_qid]

    def set_default_netvm_vm(self, vm):
        assert vm.is_netvm(), "VM {0} does not provide network!".format(vm.name)
        self.default_netvm_qid = vm.qid

    def get_default_netvm_vm(self):
        if self.default_netvm_qid is None:
            return None
        else:
            return self[self.default_netvm_qid]

    def set_default_kernel(self, kernel):
        assert os.path.exists(qubes_kernels_base_dir + '/' + kernel), "Kerel {0} not installed!".format(kernel)
        self.default_kernel = kernel

    def get_default_kernel(self):
        return self.default_kernel

    def set_default_fw_netvm_vm(self, vm):
        assert vm.is_netvm(), "VM {0} does not provide network!".format(vm.name)
        self.default_fw_netvm_qid = vm.qid

    def get_default_fw_netvm_vm(self):
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
                   if (vm.template_vm and vm.template_vm.qid == template_qid)])
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
                print "ERROR: The qid={0} is already used by VM '{1}'!".\
                        format(vm.qid, vm.name)
                return False

        # Verify that name is unique
        for vm in self.values():
            if vm.name == new_vm.name:
                print "ERROR: The name={0} is already used by other VM with qid='{1}'!".\
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
                "installed_by_rpm", "updateable", "internal",
                "uses_default_netvm", "label", "memory", "vcpus", "pcidevs",
                "maxmem", "kernel", "uses_default_kernel" )

        for attribute in common_attr_list:
            kwargs[attribute] = element.get(attribute)

        kwargs["qid"] = int(kwargs["qid"])
        if kwargs["updateable"] is not None:
            kwargs["updateable"] = True if kwargs["updateable"] == "True" else False

        if "installed_by_rpm" in kwargs:
            kwargs["installed_by_rpm"] = True if kwargs["installed_by_rpm"] == "True" else False

        if "internal" in kwargs:
            kwargs["internal"] = True if kwargs["internal"] == "True" else False

        if "template_qid" in kwargs:
            if kwargs["template_qid"] == "none" or kwargs["template_qid"] is None:
                kwargs.pop("template_qid")
            else:
                kwargs["template_qid"] = int(kwargs["template_qid"])
                template_vm = self[kwargs.pop("template_qid")]
                if template_vm is None:
                    print "ERROR: VM '{0}' uses unkown template qid='{1}'!".\
                            format(kwargs["name"], kwargs["template_qid"])

                kwargs["template_vm"] = template_vm

        if kwargs["label"] is not None:
            if kwargs["label"] not in QubesVmLabels:
                print "ERROR: incorrect label for VM '{0}'".format(kwargs["name"])
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
            netvm_vm = self.get_default_netvm_vm()
            kwargs.pop("netvm_qid")
        else:
            if kwargs["netvm_qid"] == "none" or kwargs["netvm_qid"] is None:
                netvm_vm = None
                kwargs.pop("netvm_qid")
            else:
                netvm_qid = int(kwargs.pop("netvm_qid"))
                if netvm_qid not in self:
                    netvm_vm = None
                else:
                    netvm_vm = self[netvm_qid]

        vm.netvm_vm = netvm_vm
        if netvm_vm:
            netvm_vm.connected_vms[vm.qid] = vm

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

        default_fw_netvm = element.get("default_netvm")
        if default_fw_netvm is not None:
            self.default_fw_netvm_qid = int(default_fw_netvm) \
                    if default_fw_netvm != "None" else None
            #assert self.default_netvm_qid is not None

        updatevm = element.get("updatevm")
        if updatevm is not None:
            self.updatevm_qid = int(updatevm) \
                    if updatevm != "None" else None
            #assert self.default_netvm_qid is not None

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

        # Really finally, read in the DisposableVMs
        for element in tree.findall("QubesDisposableVm"):
            try:
                kwargs = {}
                attr_list = ("qid", "name",
                             "template_qid",
                             "label", "dispid")

                for attribute in attr_list:
                    kwargs[attribute] = element.get(attribute)

                kwargs["qid"] = int(kwargs["qid"])
                kwargs["dispid"] = int(kwargs["dispid"])
                kwargs["template_qid"] = int(kwargs["template_qid"])

                template_vm = self[kwargs.pop("template_qid")]
                if template_vm is None:
                    print "ERROR: DisposableVM '{0}' uses unkown template qid='{1}'!".\
                            format(kwargs["name"], kwargs["template_qid"])

                kwargs["template_vm"] = template_vm
                kwargs["netvm_vm"] = self.get_default_netvm_vm()

                if kwargs["label"] is not None:
                    if kwargs["label"] not in QubesVmLabels:
                        print "ERROR: incorrect label for VM '{0}'".format(kwargs["name"])
                        kwargs.pop ("label")
                    else:
                        kwargs["label"] = QubesVmLabels[kwargs["label"]]

                vm = QubesDisposableVm(**kwargs)

                self[vm.qid] = vm
            except (ValueError, LookupError) as err:
                print("{0}: import error (DisposableAppVm): {1}".format(
                    os.path.basename(sys.argv[0]), err))
                return False

        return True




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
            print "Path {0} doesn't exist, assuming stale pidfile.".format(proc_path)
            return True

        f = open (proc_path)
        cmdline = f.read ()
        f.close()

#       The following doesn't work with python -- one would have to get argv[1] and compare it with self.name...
#        if not cmdline.strip().endswith(self.name):
#            print "{0} = {1} doesn't seem to point to our process ({2}), assuming stale pidile.".format(proc_path, cmdline, self.name)
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
