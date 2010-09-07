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

# Do not use XenAPI or create/read any VM files
# This is for testing only!
dry_run = False
#dry_run = True


if not dry_run:
    # Xen API
    import xmlrpclib
    from xen.xm import XenAPI
    from xen.xend import sxp


qubes_guid_path = "/usr/bin/qubes_guid"

qubes_base_dir   = "/var/lib/qubes"

qubes_appvms_dir = qubes_base_dir + "/appvms" 
qubes_templates_dir = qubes_base_dir + "/vm-templates" 
qubes_servicevms_dir = qubes_base_dir + "/servicevms" 
qubes_store_filename = qubes_base_dir + "/qubes.xml"

qubes_max_qid = 254*254
qubes_max_netid = 254
vm_default_netmask = "255.255.0.0"

default_root_img = "root.img"
default_rootcow_img = "root-cow.img"
default_swapcow_img = "swap-cow.img"
default_private_img = "private.img"
default_appvms_conf_file = "appvm-template.conf"
default_templatevm_conf_template = "templatevm.conf" # needed for TemplateVM cloning
default_appmenus_templates_subdir = "apps.templates"
default_kernels_subdir = "kernels"

# do not allow to start a new AppVM if Dom0 mem was to be less than this
dom0_min_memory = 700*1024*1024

# We need this global reference, as each instance of QubesVM
# must be able to ask Dom0 VM about how much memory it currently has...
dom0_vm = None

qubes_appmenu_create_cmd = "/usr/lib/qubes/create_apps_for_appvm.sh"
qubes_appmenu_remove_cmd = "/usr/lib/qubes/remove_appvm_appmenus.sh"

# TODO: we should detect the actual size of the AppVM's swap partition
# rather than using this ugly hardcoded value, which was choosen here
# as "should be good for everyone"
swap_cow_sz = 1024*1024*1024

VM_TEMPLATE = 'TempleteVM'
VM_APPVM = 'AppVM'
VM_NETVM = 'NetVM'

class XendSession(object):
    def __init__(self):
        self.get_xend_session_old_api()
        self.get_xend_session_new_api()

    def get_xend_session_old_api(self):
        from xen.xend import XendClient
        from xen.util.xmlrpcclient import ServerProxy
        self.xend_server = ServerProxy(XendClient.uri)
        if self.xend_server is None:
            print "get_xend_session_old_api(): cannot open session!"


    def get_xend_session_new_api(self):
        xend_socket_uri = "httpu:///var/run/xend/xen-api.sock"
        self.session = XenAPI.Session (xend_socket_uri)
        self.session.login_with_password ("", "")
        if self.session is None:
            print "get_xend_session_new_api(): cannot open session!"


if not dry_run:
    xend_session = XendSession()
 
class QubesException (Exception) : pass

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

    def __init__(self, qid, name, type,
                 dir_path, conf_file = None,
                 uses_default_netvm = True,
                 netvm_vm = None,
                 installed_by_rpm = False,
                 updateable = False,
                 label = None):


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

        self.__type = type
        self.uses_default_netvm = uses_default_netvm
        self.netvm_vm = netvm_vm

        # We use it in remove from disk to avoid removing rpm files (for templates and netvms)
        self.installed_by_rpm = installed_by_rpm

        self.updateable = updateable
        self.label = label if label is not None else QubesVmLabels["red"]
        self.icon_path = self.dir_path + "/icon.png"

        if not dry_run and xend_session.session is not None:
            self.refresh_xend_session()

    @property
    def qid(self):
        return self.__qid

    @property
    def type(self):
        return self.__type

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


    def set_nonupdateable(self):
        if not self.is_updateable():
            return

        assert not self.is_running()
        # We can always downgrade a VM to non-updateable...
        self.updateable = False

    def is_templete(self):
        if self.type == VM_TEMPLATE:
            return True
        else:
            return False

    def is_appvm(self):
        if self.type == VM_APPVM:
            return True
        else:
            return False

    def is_netvm(self):
        if self.type == VM_NETVM:
            return True
        else:
            return False

    def add_to_xen_storage(self):
        if dry_run:
            return

        retcode = subprocess.call (["/usr/sbin/xm", "new", "-q",  self.conf_file])
        if retcode != 0:
            raise OSError ("Cannot add VM '{0}' to Xen Store!".format(self.name))

        return True

    def remove_from_xen_storage(self):
        if dry_run:
            return

        retcode = subprocess.call (["/usr/sbin/xm", "delete", self.name])
        if retcode != 0:
            raise OSError ("Cannot remove VM '{0}' from Xen Store!".format(self.name))

        self.in_xen_storage = False

    def refresh_xend_session(self):
        uuids = xend_session.session.xenapi.VM.get_by_name_label (self.name)
        self.session_uuid = uuids[0] if len (uuids) > 0 else None
        if self.session_uuid is not None:
            self.session_metrics = xend_session.session.xenapi.VM.get_metrics(self.session_uuid)
        else:
            self.session_metrics = None

    def update_xen_storage(self):
        self.remove_from_xen_storage()
        self.add_to_xen_storage()
        if not dry_run and xend_session.session is not None:
            self.refresh_xend_session()

    def get_xid(self):
        if dry_run:
            return 666

        try:
            xid = int (xend_session.session.xenapi.VM.get_domid (self.session_uuid))
        except XenAPI.Failure:
            self.refresh_xend_session()
            xid = int (xend_session.session.xenapi.VM.get_domid (self.session_uuid))

        return xid

    def get_mem(self):
        if dry_run:
            return 666

        try:
            mem = int (xend_session.session.xenapi.VM_metrics.get_memory_actual (self.session_metrics))
        except XenAPI.Failure:
            self.refresh_xend_session()
            mem = int (xend_session.session.xenapi.VM_metrics.get_memory_actual (self.session_metrics))

        return mem

    def get_mem_static_max(self):
        if dry_run:
            return 666

        try:
            mem = int(xend_session.session.xenapi.VM.get_memory_static_max(self.session_uuid))
        except XenAPI.Failure:
            self.refresh_xend_session()
            mem = int(xend_session.session.xenapi.VM.get_memory_static_max(self.session_uuid))

        return mem


    def get_cpu_total_load(self):
        if dry_run:
            import random
            return random.random() * 100

        try:
            cpus_util = xend_session.session.xenapi.VM_metrics.get_VCPUs_utilisation (self.session_metrics)
        except XenAPI.Failure:
            self.refresh_xend_session()
            cpus_util = xend_session.session.xenapi.VM_metrics.get_VCPUs_utilisation (self.session_metrics)

        if len (cpus_util) == 0:
            return 0

        cpu_total_load = 0.0
        for cpu in cpus_util:
            cpu_total_load += cpus_util[cpu]
        cpu_total_load /= len(cpus_util)
        p = 100*cpu_total_load 
        if p > 100:
            p = 100
        return p

    def get_power_state(self):
        if dry_run:
            return "NA"

        try:
            power_state = xend_session.session.xenapi.VM.get_power_state (self.session_uuid)
        except XenAPI.Failure:
            self.refresh_xend_session()
            if self.session_uuid is None:
                return "NA"
            power_state = xend_session.session.xenapi.VM.get_power_state (self.session_uuid)

        return power_state

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

    def create_xenstore_entries(self, xid):
        if dry_run:
            return

        # Set Xen Store entires with VM networking info:

        retcode = subprocess.check_call ([
                "/usr/bin/xenstore-write",
                "/local/domain/{0}/qubes_vm_type".format(xid),
                self.type])

        if self.is_netvm():
            retcode = subprocess.check_call ([
                "/usr/bin/xenstore-write",
                "/local/domain/{0}/qubes_netvm_gateway".format(xid),
                self.gateway])

            retcode = subprocess.check_call ([
                "/usr/bin/xenstore-write",
                "/local/domain/{0}/qubes_netvm_secondary_dns".format(xid),
                self.secondary_dns])

            retcode = subprocess.check_call ([
                "/usr/bin/xenstore-write",
                "/local/domain/{0}/qubes_netvm_netmask".format(xid),
                self.netmask])

            retcode = subprocess.check_call ([
                "/usr/bin/xenstore-write",
                "/local/domain/{0}/qubes_netvm_network".format(xid),
                self.network])
 
        elif self.netvm_vm is not None:
            retcode = subprocess.check_call ([
                "/usr/bin/xenstore-write",
                "/local/domain/{0}/qubes_ip".format(xid),
                self.ip])

            retcode = subprocess.check_call ([
                "/usr/bin/xenstore-write",
                "/local/domain/{0}/qubes_netmask".format(xid),
                self.netmask])

            retcode = subprocess.check_call ([
                "/usr/bin/xenstore-write",
                "/local/domain/{0}/qubes_gateway".format(xid),
                self.gateway])

            retcode = subprocess.check_call ([
                "/usr/bin/xenstore-write",
                "/local/domain/{0}/qubes_secondary_dns".format(xid),
                self.secondary_dns])
        else:
            pass

    def get_free_xen_memory(self):
        hosts = xend_session.session.xenapi.host.get_all()
        host_record = xend_session.session.xenapi.host.get_record(hosts[0])
        host_metrics_record = xend_session.session.xenapi.host_metrics.get_record(host_record["metrics"])
        ret = host_metrics_record["memory_free"]
        return long(ret)

    def start(self, debug_console = False, verbose = False, preparing_dvm = False):
        if dry_run:
            return

        if self.is_running():
            raise QubesException ("VM is already running!")

        if verbose:
            print "--> Rereading the VM's conf file ({0})...".format(self.conf_file)
        self.update_xen_storage()

        if verbose:
            print "--> Loading the VM (type = {0})...".format(self.type)

        mem_required = self.get_mem_static_max()
        dom0_mem = dom0_vm.get_mem()
        dom0_mem_new = dom0_mem - mem_required + self.get_free_xen_memory()
        if verbose:
            print "--> AppVM required mem     : {0}".format(mem_required)
            print "--> Dom0 mem after launch  : {0}".format(dom0_mem_new)

        if dom0_mem_new < dom0_min_memory:
            raise MemoryError ("ERROR: starting this VM would cause Dom0 memory to go below {0}B".format(dom0_min_memory))

        try:
            xend_session.session.xenapi.VM.start (self.session_uuid, True) # Starting a VM paused
        except XenAPI.Failure:
            self.refresh_xend_session()
            xend_session.session.xenapi.VM.start (self.session_uuid, True) # Starting a VM paused

        xid = int (xend_session.session.xenapi.VM.get_domid (self.session_uuid))

        if verbose:
            print "--> Setting Xen Store info for the VM..."
        self.create_xenstore_entries(xid)

        if not self.is_netvm() and self.netvm_vm is not None:
            assert self.netvm_vm is not None
            if verbose:
                print "--> Attaching to the network backend (netvm={0})...".format(self.netvm_vm.name)
            if preparing_dvm:
                actual_ip = "254.254.254.254"
            else:
                actual_ip = self.ip
            xm_cmdline = ["/usr/sbin/xm", "network-attach", self.name, "script=vif-route-qubes", "ip="+actual_ip]
            if self.netvm_vm.qid != 0:
                if not self.netvm_vm.is_running():
                    print "ERROR: NetVM not running, please start it first"
                    self.force_shutdown()
                    raise QubesException ("NetVM not running")
                retcode = subprocess.call (xm_cmdline + ["backend={0}".format(self.netvm_vm.name)])
                if retcode != 0:
                    self.force_shutdown()
                    raise OSError ("ERROR: Cannot attach to network backend!")

            else:
                retcode = subprocess.call (xm_cmdline)
                if retcode != 0:
                    self.force_shutdown()
                    raise OSError ("ERROR: Cannot attach to network backend!")

        if verbose:
            print "--> Starting the VM..."
        xend_session.session.xenapi.VM.unpause (self.session_uuid) 

        # perhaps we should move it before unpause and fork?
        if debug_console:
            from xen.xm import console
            if verbose:
                print "--> Starting debug console..."
            console.execConsole (xid)

        return xid

    def force_shutdown(self):
        if dry_run:
            return

        try:
            xend_session.session.xenapi.VM.hard_shutdown (self.session_uuid)
        except XenAPI.Failure:
            self.refresh_xend_session()
            xend_session.session.xenapi.VM.hard_shutdown (self.session_uuid)

    def remove_from_disk(self):
        if dry_run:
            return


        shutil.rmtree (self.dir_path)


class QubesTemplateVm(QubesVm):
    """
    A class that represents an TemplateVM. A child of QubesVM.
    """
    def __init__(self, **kwargs):

        if "dir_path" not in kwargs or kwargs["dir_path"] is None:
            kwargs["dir_path"] = qubes_templates_dir + "/" + kwargs["name"]

        if "updateable" not in kwargs or kwargs["updateable"] is None :
            kwargs["updateable"] = True

        root_img = kwargs.pop("root_img") if "root_img" in kwargs else None
        private_img = kwargs.pop("private_img") if "private_img" in kwargs else None
        appvms_conf_file = kwargs.pop("appvms_conf_file") if "appvms_conf_file" in kwargs else None

        super(QubesTemplateVm, self).__init__(type=VM_TEMPLATE, label = default_template_label, **kwargs)

        dir_path = kwargs["dir_path"]

        # TempleteVM doesn't use root-cow image
        if root_img is not None and os.path.isabs(root_img):
            self.root_img = root_img
        else:
            self.root_img = dir_path + "/" + (
                root_img if root_img is not None else default_root_img)

        if private_img is not None and os.path.isabs(private_img):
            self.private_img = private_img
        else:
            self.private_img = dir_path + "/" + (
                private_img if private_img is not None else default_private_img)

        if appvms_conf_file is not None and os.path.isabs(appvms_conf_file):
            self.appvms_conf_file = appvms_conf_file
        else:
            self.appvms_conf_file = dir_path + "/" + (
                appvms_conf_file if appvms_conf_file is not None else default_appvms_conf_file)

        self.templatevm_conf_template = self.dir_path + "/" + default_templatevm_conf_template
        self.kernels_dir = self.dir_path + "/" + default_kernels_subdir
        self.appmenus_templates_dir = self.dir_path + "/" + default_appmenus_templates_subdir
        self.appvms = QubesVmCollection()

    def set_updateable(self):
        if self.is_updateable():
            return

        assert not self.is_running()
        # Make sure that all the AppVMs are non-updateable...
        for appvm in self.appvms.values():
            if appvm.is_updateable():
                raise QubesException("One of the AppVMs ('{0}')is also 'updateable'\
                                     -- cannot make the TempleteVM {'{1}'} 'nonupdatable'".\
                                     format (appvm.name, self.name))
        self.updateable = True


    def clone_disk_files(self, src_template_vm, verbose):
        if dry_run:
            return


        assert not src_template_vm.is_running(), "Attempt to clone a running Template VM!"

        if verbose:
            print "--> Creating directory: {0}".format(self.dir_path)
        os.mkdir (self.dir_path)

        if verbose:
            print "--> Copying the VM config file:\n{0} =*>\n{1}".\
                    format(src_template_vm.templatevm_conf_template, self.conf_file)
        conf_templatevm_template = open (src_template_vm.templatevm_conf_template, "r")
        conf_file = open(self.conf_file, "w")
        rx_templatename = re.compile (r"%TEMPLATENAME%")

        for line in conf_templatevm_template:
            line = rx_templatename.sub (self.name, line)
            conf_file.write(line)

        conf_templatevm_template.close()
        conf_file.close()

        if verbose:
            print "--> Copying the VM config template :\n{0} ==>\n{1}".\
                    format(src_template_vm.templatevm_conf_template, self.templatevm_conf_template)
        shutil.copy (src_template_vm.templatevm_conf_template, self.templatevm_conf_template)

        if verbose:
            print "--> Copying the VM config template :\n{0} ==>\n{1}".\
                    format(src_template_vm.appvms_conf_file, self.appvms_conf_file)
        shutil.copy (src_template_vm.appvms_conf_file, self.appvms_conf_file)

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
            print "--> Copying the template's kernel dir:\n{0} ==>\n{1}".\
                    format(src_template_vm.kernels_dir, self.kernels_dir)
        shutil.copytree (src_template_vm.kernels_dir, self.kernels_dir)

        if verbose:
            print "--> Copying the template's appvm templates dir:\n{0} ==>\n{1}".\
                    format(src_template_vm.appmenus_templates_dir, self.appmenus_templates_dir)
        shutil.copytree (src_template_vm.appmenus_templates_dir, self.appmenus_templates_dir)
 
 
    def get_disk_utilization_root_img(self):
        return self.get_disk_usage(self.root_img)

    def get_root_img_sz(self):
        if not os.path.exists(self.root_img):
            return 0
 
        return os.path.getsize(self.root_img)

    def verify_files(self):
        if dry_run:
            return


        if not os.path.exists (self.dir_path):
            raise QubesException (
                "VM directory doesn't exist: {0}".\
                format(self.dir_path))

        if not os.path.exists (self.conf_file):
            raise QubesException (
                "VM config file doesn't exist: {0}".\
                format(self.conf_file))

        if not os.path.exists (self.appvms_conf_file):
            raise QubesException (
                "Appvm template config file doesn't exist: {0}".\
                format(self.appvms_conf_file))

        if not os.path.exists (self.root_img):
            raise QubesException (
                "VM root image file doesn't exist: {0}".\
                format(self.root_img))

        if not os.path.exists (self.private_img):
            raise QubesException (
                "VM private image file doesn't exist: {0}".\
                format(self.private_img))

        if not os.path.exists (self.kernels_dir):
            raise QubesException (
                "VM's kernels directory does not exist: {0}".\
                format(self.kernels_dir))
 
        return True

    def start(self, debug_console = False, verbose = False):
        if dry_run:
            return


        if not self.is_updateable():
            raise QubesException ("Cannot start Template VM that is marked \"nonupdatable\"")

        # First ensure that none of our appvms is running:
        for appvm in self.appvms.values():
            if appvm.is_running():
                raise QubesException ("Cannot start TemplateVM when one of its AppVMs is running!")

        return super(QubesTemplateVm, self).start(debug_console=debug_console, verbose=verbose)

    def create_xml_element(self):
        element = xml.etree.ElementTree.Element(
            "QubesTemplateVm",
            qid=str(self.qid),
            name=self.name,
            dir_path=self.dir_path,
            conf_file=self.conf_file,
            appvms_conf_file=self.appvms_conf_file,
            root_img=self.root_img,
            private_img=self.private_img,
            uses_default_netvm=str(self.uses_default_netvm),
            netvm_qid=str(self.netvm_vm.qid) if self.netvm_vm is not None else "none",
            installed_by_rpm=str(self.installed_by_rpm),
            updateable=str(self.updateable),
            )
        return element

class QubesServiceVm(QubesVm):
    """
    A class that represents a ServiceVM, e.g. NetVM. A child of QubesVM.
    """
    def __init__(self, **kwargs):

        if "dir_path" not in kwargs or kwargs["dir_path"] is None:
            kwargs["dir_path"] = qubes_servicevms_dir + "/" + kwargs["name"]

        root_img = kwargs.pop("root_img") if "root_img" in kwargs else None
        private_img = kwargs.pop("private_img") if "private_img" in kwargs else None

        kwargs["updateable"] = True
        super(QubesServiceVm, self).__init__(**kwargs)

        dir_path = kwargs["dir_path"]
        assert dir_path is not None

        if root_img is not None and os.path.isabs(root_img):
            self.root_img = root_img
        else:
            self.root_img = dir_path + "/" + (
                root_img if root_img is not None else default_root_img)

        if private_img is not None and os.path.isabs(private_img):
            self.private_img = private_img
        else:
            self.private_img = dir_path + "/" + (
                private_img if private_img is not None else default_private_img)

    def set_updateable(self):
        if self.is_updateable():
            return
        # ServiceVMs are standalone, we can always make it updateable
        # In fact there is no point in making it unpdatebale...
        # So, this is just for completncess
        assert not self.is_running()
        self.updateable = True 

    def get_disk_utilization_root_img(self):
        return self.get_disk_usage(self.root_img)

    def get_root_img_sz(self):
        if not os.path.exists(self.root_img):
            return 0
 
        return os.path.getsize(self.root_img)

    def verify_files(self):
        if dry_run:
            return


        if not os.path.exists (self.dir_path):
            raise QubesException (
                "VM directory doesn't exist: {0}".\
                format(self.dir_path))

        if not os.path.exists (self.conf_file):
            raise QubesException (
                "VM config file doesn't exist: {0}".\
                format(self.conf_file))

        if not os.path.exists (self.root_img):
            raise QubesException (
                "VM root image file doesn't exist: {0}".\
                format(self.root_img))

        return True

    def create_xml_element(self):
        raise NotImplementedError

class QubesNetVm(QubesServiceVm):
    """
    A class that represents a NetVM. A child of QubesServiceVM.
    """
    def __init__(self, **kwargs):
        netid = kwargs.pop("netid")
        self.netid = netid
        self.__network = "10.{0}.0.0".format(netid)
        self.netprefix = "10.{0}.".format(netid)
        self.__netmask = vm_default_netmask
        self.__gateway = self.netprefix + "0.1"
        self.__secondary_dns = self.netprefix + "255.254"

        if "label" not in kwargs or kwargs["label"] is None:
            kwargs["label"] = default_servicevm_label
        super(QubesNetVm, self).__init__(type=VM_NETVM, installed_by_rpm=True, **kwargs)

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
        hi = qid / 253
        lo = qid % 253 + 2 
        assert hi >= 0 and hi <= 254 and lo >= 2 and lo <= 254, "Wrong IP address for VM"
        return self.netprefix  + "{0}.{1}".format(hi,lo)

    def create_xml_element(self):
        element = xml.etree.ElementTree.Element(
            "QubesNetVm",
            qid=str(self.qid),
            netid=str(self.netid),
            name=self.name,
            dir_path=self.dir_path,
            conf_file=self.conf_file,
            root_img=self.root_img,
            private_img=self.private_img,
            installed_by_rpm=str(self.installed_by_rpm),
            )
        return element

class QubesDom0NetVm(QubesNetVm):
    def __init__(self):
        super(QubesDom0NetVm, self).__init__(qid=0, name="dom0", netid=0,
                                             dir_path=None, root_img = None,
                                             private_img = None,
                                             label = default_template_label)
        if not dry_run and xend_session.session is not None:
            self.session_hosts = xend_session.session.xenapi.host.get_all()
            self.session_cpus = xend_session.session.xenapi.host.get_host_CPUs(self.session_hosts[0])


    def is_running(self):
        return True

    def get_cpu_total_load(self):
        if dry_run:
            import random
            return random.random() * 100

        cpu_total_load = 0.0
        for cpu in self.session_cpus:
            cpu_total_load += xend_session.session.xenapi.host_cpu.get_utilisation(cpu)
        cpu_total_load /= len(self.session_cpus)
        p = 100*cpu_total_load 
        if p > 100:
            p = 100
        return p

    def get_mem(self):

        # Unfortunately XenAPI provides only info about total memory, not the one actually usable by Dom0...
        #session = get_xend_session_new_api()
        #hosts = session.xenapi.host.get_all()
        #metrics = session.xenapi.host.get_metrics(hosts[0])
        #memory_total = int(session.xenapi.metrics.get_memory_total(metrics))

        # ... so we must read /proc/meminfo, just like free command does
        f = open ("/proc/meminfo")
        for line in f:
            match = re.match(r"^MemTotal\:\s*(\d+) kB", line)
            if match is not None:
                break
        f.close()
        assert match is not None
        return int(match.group(1))*1024

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

    def create_xml_element(self):
        return None

    def verify_files(self):
        return True


class QubesAppVm(QubesVm):
    """
    A class that represents an AppVM. A child of QubesVM.
    """
    def __init__(self, **kwargs):

        if "dir_path" not in kwargs or kwargs["dir_path"] is None:
            kwargs["dir_path"] = qubes_appvms_dir + "/" + kwargs["name"]

        if "updateable" not in kwargs or kwargs["updateable"] is None:
            kwargs["updateable"] = False

        private_img = kwargs.pop("private_img")
        template_vm = kwargs.pop("template_vm")


        super(QubesAppVm, self).__init__(type=VM_APPVM, **kwargs)
        qid = kwargs["qid"]
        dir_path = kwargs["dir_path"]

        assert template_vm is not None, "Missing template_vm for AppVM!"
        if not template_vm.is_templete():
            print "ERROR: template_qid={0} doesn't point to a valid TempleteVM".\
                    format(new_vm.template_vm.qid)
            return False

        self.template_vm = template_vm
        template_vm.appvms[qid] = self

        # AppVM doesn't have its own root_img, it uses the one provided by the TemplateVM
        if private_img is not None and os.path.isabs(private_img):
            self.private_img = private_img
        else:
            self.private_img = dir_path + "/" + (
                private_img if private_img is not None else default_private_img)

        self.rootcow_img = dir_path + "/" + default_rootcow_img
        self.swapcow_img = dir_path + "/" + default_swapcow_img


    def set_updateable(self):
        if self.is_updateable():
            return

        assert not self.is_running()
        # Check if the TemaplteVM is *non* updatable...
        if not self.template_vm.is_updateable():
            self.updateable = True
            self.reset_cow_storage()
            self.reset_swap_cow_storage()
        else:
            # Temaplate VM is Updatable itself --> can't make the AppVM updateable too
            # as this would cause COW-backed storage incoherency
            raise QubesException ("TemaplteVM is updateable: cannot make the AppVM '{0}' updateable".format(self.name))

    def create_on_disk(self, verbose):
        if dry_run:
            return


        if verbose:
            print "--> Creating directory: {0}".format(self.dir_path)
        os.mkdir (self.dir_path)

        if verbose:
            print "--> Creating the VM config file: {0}".format(self.conf_file)
 
        conf_template = open (self.template_vm.appvms_conf_file, "r")
        conf_appvm = open(self.conf_file, "w")
        rx_vmname = re.compile (r"%VMNAME%")
        rx_vmdir = re.compile (r"%VMDIR%")
        rx_template = re.compile (r"%TEMPLATEDIR%")

        for line in conf_template:
            line = rx_vmname.sub (self.name, line)
            line = rx_vmdir.sub (self.dir_path, line)
            line = rx_template.sub (self.template_vm.dir_path, line)
            conf_appvm.write(line)

        conf_template.close()
        conf_appvm.close()

        template_priv = self.template_vm.private_img
        if verbose:
            print "--> Copying the template's private image: {0}".\
                    format(template_priv)
 
        # We prefer to use Linux's cp, because it nicely handles sparse files
        retcode = subprocess.call (["cp", template_priv, self.private_img])
        if retcode != 0:
            raise IOError ("Error while copying {0} to {1}".\
                           format(template_priv, self.private_img))

        if verbose:
            print "--> Creating icon symlink: {0} -> {1}".format(self.icon_path, self.label.icon_path)
        os.symlink (self.label.icon_path, self.icon_path)

        self.create_appmenus (verbose)

    def create_appmenus(self, verbose):
        subprocess.check_call ([qubes_appmenu_create_cmd, self.template_vm.appmenus_templates_dir, self.name])

    def get_disk_utilization_root_img(self):
        return 0

    def get_root_img_sz(self):
        return 0


    def verify_files(self):
        if dry_run:
            return


        if not os.path.exists (self.dir_path):
            raise QubesException (
                "VM directory doesn't exist: {0}".\
                format(self.dir_path))

        if not os.path.exists (self.conf_file):
            raise QubesException (
                "VM config file doesn't exist: {0}".\
                format(self.conf_file))

        if not os.path.exists (self.private_img):
            raise QubesException (
                "VM private image file doesn't exist: {0}".\
                format(self.private_img))
        return True


    def create_xml_element(self):
        element = xml.etree.ElementTree.Element(
            "QubesAppVm",
            qid=str(self.qid),
            name=self.name,
            dir_path=self.dir_path,
            conf_file=self.conf_file,
            template_qid=str(self.template_vm.qid),
            uses_default_netvm=str(self.uses_default_netvm),
            netvm_qid=str(self.netvm_vm.qid) if self.netvm_vm is not None else "none",
            private_img=self.private_img,
            installed_by_rpm=str(self.installed_by_rpm),
            updateable=str(self.updateable),
            label=self.label.name)
        return element

    def start(self, debug_console = False, verbose = False, preparing_dvm = False):
        if dry_run:
            return

        if self.is_running():
            raise QubesException("VM is already running!")

        # First ensure that our template is *not* running:
        if self.template_vm.is_running():
            raise QubesException ("Cannot start AppVM when its template is running!")

        if not self.is_updateable():
            self.reset_cow_storage()
        self.reset_swap_cow_storage()

        return super(QubesAppVm, self).start(debug_console=debug_console, verbose=verbose, preparing_dvm=preparing_dvm)

    def reset_cow_storage (self):

        print "--> Resetting the COW storage: {0}...".format (self.rootcow_img)

        if dry_run:
            return
        # this is probbaly not needed, as open (..., "w") should remove the previous file
        if os.path.exists (self.rootcow_img):
           os.remove (self.rootcow_img)


        f_cow = open (self.rootcow_img, "w")
        f_root = open (self.template_vm.root_img, "r")
        f_root.seek(0, os.SEEK_END)
        f_cow.truncate (f_root.tell()) # make empty sparse file of the same size as root.img
        f_cow.close ()
        f_root.close()

    def reset_swap_cow_storage (self):
        print "--> Resetting the swap COW storage: {0}...".format (self.swapcow_img)
        if os.path.exists (self.swapcow_img):
           os.remove (self.swapcow_img)

        f_swap_cow = open (self.swapcow_img, "w")
        f_swap_cow.truncate (swap_cow_sz)
        f_swap_cow.close()

    def remove_from_disk(self):
        if dry_run:
            return


        subprocess.check_call ([qubes_appmenu_remove_cmd, self.name])
        shutil.rmtree (self.dir_path)



class QubesVmCollection(dict):
    """
    A collection of Qubes VMs indexed by Qubes id (qid)
    """

    def __init__(self, store_filename=qubes_store_filename):
        super(QubesVmCollection, self).__init__()
        self.default_netvm_qid = None
        self.default_template_qid = None
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
                      label = None):

        qid = self.get_new_unused_qid()
        vm = QubesAppVm (qid=qid, name=name, template_vm=template_vm,
                         dir_path=dir_path, conf_file=conf_file,
                         private_img=private_img,
                         netvm_vm = self.get_default_netvm_vm(),
                         label=label)

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
                              netvm_vm = self.get_default_netvm_vm())

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


    def add_new_netvm(self, name,
                      dir_path = None, conf_file = None,
                      root_img = None):

        qid = self.get_new_unused_qid()
        netid = self.get_new_unused_netid()
        vm = QubesNetVm (qid=qid, name=name, 
                         netid=netid,
                         dir_path=dir_path, conf_file=conf_file,
                         root_img=root_img)

        if not self.verify_new_vm (vm):
            assert False, "Wrong VM description!"
        self[vm.qid]=vm

        if self.default_netvm_qid is None:
            self.set_default_netvm_vm(vm)

        return vm

    def set_default_template_vm(self, vm):
        assert vm.is_templete(), "VM {0} is not a TempleteVM!".format(vm.name)
        self.default_template_qid = vm.qid

    def get_default_template_vm(self):
        if self.default_template_qid is None:
            return None
        else:
            return self[self.default_template_qid]

    def set_default_netvm_vm(self, vm):
        assert vm.is_netvm(), "VM {0} is not a NetVM!".format(vm.name)
        self.default_netvm_qid = vm.qid

    def get_default_netvm_vm(self):
        if self.default_netvm_qid is None:
            return None
        else:
            return self[self.default_netvm_qid]

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
                   if (vm.is_appvm() and vm.template_vm.qid == template_qid)])
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
            if self.default_netvm_qid is not None else "None"
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
            print("{0}: import error: {1}".format(
                os.path.basename(sys.argv[0]), err))
            return False
        return True

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

        # Read in the NetVMs first, because a reference to NetVM
        # is needed to create all other VMs
        for element in tree.findall("QubesNetVm"):
            try:
                kwargs = {}
                attr_list = ("qid", "netid", "name", "dir_path", "conf_file",
                              "private_img", "root_img",
                              )

                for attribute in attr_list:
                    kwargs[attribute] = element.get(attribute)

                kwargs["qid"] = int(kwargs["qid"])
                kwargs["netid"] = int(kwargs["netid"])

                vm = QubesNetVm(**kwargs)
                self[vm.qid] = vm
 
            except (ValueError, LookupError) as err:
                print("{0}: import error (QubesNetVM) {1}".format(
                    os.path.basename(sys.argv[0]), err))
                return False


        self.default_template_qid
        # Then, read in the TemplateVMs, because a reference to templete VM
        # is needed to create each AppVM 
        for element in tree.findall("QubesTemplateVm"):
            try:

                kwargs = {}
                attr_list = ("qid", "name", "dir_path", "conf_file",
                             "appvms_conf_file", "private_img", "root_img",
                             "installed_by_rpm", "updateable",
                             "uses_default_netvm", "netvm_qid")

                for attribute in attr_list:
                    kwargs[attribute] = element.get(attribute)

                kwargs["qid"] = int(kwargs["qid"])
                kwargs["installed_by_rpm"] = True if kwargs["installed_by_rpm"] == "True" else False
                if kwargs["updateable"] is not None:
                    kwargs["updateable"] = True if kwargs["updateable"] == "True" else False

                if "uses_default_netvm" not in kwargs:
                    kwargs["uses_default_netvm"] = True
                else:
                    kwargs["uses_default_netvm"] = True if kwargs["uses_default_netvm"] == "True" else False
                if kwargs["uses_default_netvm"] is True:
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

                kwargs["netvm_vm"] = netvm_vm
 
                vm = QubesTemplateVm(**kwargs)

                self[vm.qid] = vm
            except (ValueError, LookupError) as err:
                print("{0}: import error (QubesTemplateVm): {1}".format(
                    os.path.basename(sys.argv[0]), err))
                return False

        # Finally, read in the AppVMs
        for element in tree.findall("QubesAppVm"):
            try:
                kwargs = {}
                attr_list = ("qid", "name", "dir_path", "conf_file",
                             "private_img", "template_qid",
                             "updateable", "label", "netvm_qid",
                             "uses_default_netvm")

                for attribute in attr_list:
                    kwargs[attribute] = element.get(attribute)

                kwargs["qid"] = int(kwargs["qid"])
                kwargs["template_qid"] = int(kwargs["template_qid"])
                if kwargs["updateable"] is not None:
                    kwargs["updateable"] = True if kwargs["updateable"] == "True" else False

                template_vm = self[kwargs.pop("template_qid")]
                if template_vm is None:
                    print "ERROR: AppVM '{0}' uses unkown template qid='{1}'!".\
                            format(kwargs["name"], kwargs["template_qid"])

                kwargs["template_vm"] = template_vm

                if "uses_default_netvm" not in kwargs:
                    kwargs["uses_default_netvm"] = True
                else:
                    kwargs["uses_default_netvm"] = True if kwargs["uses_default_netvm"] == "True" else False
                if kwargs["uses_default_netvm"] is True:
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

                kwargs["netvm_vm"] = netvm_vm
 
                if kwargs["label"] is not None:
                    if kwargs["label"] not in QubesVmLabels:
                        print "ERROR: incorrect label for VM '{0}'".format(kwargs["name"])
                        kwargs.pop ("label")
                    else:
                        kwargs["label"] = QubesVmLabels[kwargs["label"]]

                vm = QubesAppVm(**kwargs)

                self[vm.qid] = vm
            except (ValueError, LookupError) as err:
                print("{0}: import error (QubesAppVm): {1}".format(
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


