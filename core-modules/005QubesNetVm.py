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
import sys
import os.path
import libvirt

from qubes.qubes import QubesVm,register_qubes_vm_class,vmm,dry_run
from qubes.qubes import defaults,system_path,vm_files
from qubes.qubes import QubesVmCollection,QubesException

class QubesNetVm(QubesVm):
    """
    A class that represents a NetVM. A child of QubesCowVM.
    """

    # In which order load this VM type from qubes.xml
    load_order = 70

    def get_attrs_config(self):
        attrs_config = super(QubesNetVm, self).get_attrs_config()
        attrs_config['dir_path']['func'] = \
            lambda value: value if value is not None else \
                os.path.join(system_path["qubes_servicevms_dir"], self.name)
        attrs_config['uses_default_netvm']['func'] = lambda x: False
        attrs_config['label']['default'] = defaults["servicevm_label"]
        attrs_config['memory']['default'] = 300

        # New attributes
        attrs_config['netid'] = {
            'save': lambda: str(self.netid),
            'order': 30,
            'func': lambda value: value if value is not None else
            self._collection.get_new_unused_netid() }
        attrs_config['netprefix'] = {
            'func': lambda x: "10.137.{0}.".format(self.netid) }
        attrs_config['dispnetprefix'] = {
            'func': lambda x: "10.138.{0}.".format(self.netid) }

        # Dont save netvm prop
        attrs_config['netvm'].pop('save')
        attrs_config['uses_default_netvm'].pop('save')

        return attrs_config

    def __init__(self, **kwargs):
        super(QubesNetVm, self).__init__(**kwargs)
        self.connected_vms = QubesVmCollection()

        self.__network = "10.137.{0}.0".format(self.netid)
        self.__netmask = defaults["vm_default_netmask"]
        self.__gateway = self.netprefix + "1"
        self.__secondary_dns = self.netprefix + "254"

        self.__external_ip_allowed_xids = set()

        self.log.debug('network={} netmask={} gateway={} secondary_dns={}'.format(
            self.network, self.netmask, self.gateway, self.secondary_dns))

    @property
    def type(self):
        return "NetVM"

    def is_netvm(self):
        return True

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

    def update_external_ip_permissions(self, xid = -1):
        # TODO: VMs in __external_ip_allowed_xids should be notified via RPC
        # service on exteran IP change
        pass

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
            try:
                vm.cleanup_vifs()
            except QubesException as ex:
                print >> sys.stderr, ("WARNING: Failed to detach stale netvm from '{0}': {1}".format(vm.name, ex))

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

        # detach network interfaces of connected VMs before shutting down,
        # otherwise libvirt will not notice it and will try to detach them
        # again (which would fail, obviously).
        # This code can be removed when #1426 got implemented
        for vm in self.connected_vms.values():
            if vm.is_running():
                try:
                    vm.detach_network()
                except (QubesException, libvirt.libvirtError):
                    # ignore errors
                    pass

        super(QubesNetVm, self).shutdown(force=force)

    def add_external_ip_permission(self, xid):
        if int(xid) < 0:
            return
        self.__external_ip_allowed_xids.add(int(xid))
        self.update_external_ip_permissions()

    def remove_external_ip_permission(self, xid):
        self.__external_ip_allowed_xids.discard(int(xid))
        self.update_external_ip_permissions()

register_qubes_vm_class(QubesNetVm)
