#!/usr/bin/python2 -O
# vim: fileencoding=utf-8

#
# The Qubes OS Project, https://www.qubes-os.org/
#
# Copyright (C) 2010-2016  Joanna Rutkowska <joanna@invisiblethingslab.com>
# Copyright (C) 2013-2016  Marek Marczykowski-Górecki
#                              <marmarek@invisiblethingslab.com>
# Copyright (C) 2014-2016  Wojtek Porczyk <woju@invisiblethingslab.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
#

import os
import shutil
import time
import weakref

import libvirt
import lxml.etree

import qubes
import qubes.exc

class NetVMMixin(object):
    mac = qubes.property('mac', type=str,
        default=(lambda self: '00:16:3E:5E:6C:{:02X}'.format(self.qid)),
        ls_width=17,
        doc='MAC address of the NIC emulated inside VM')

    # XXX swallowed uses_default_netvm
    netvm = qubes.VMProperty('netvm', load_stage=4, allow_none=True,
        default=(lambda self: self.app.default_fw_netvm if self.provides_network
            else self.app.default_netvm),
        ls_width=31,
        doc='''VM that provides network connection to this domain. When
            `None`, machine is disconnected. When absent, domain uses default
            NetVM.''')

    provides_network = qubes.property('provides_network', default=False,
        type=bool, setter=qubes.property.bool,
        doc='''If this domain can act as network provider (formerly known as
            NetVM or ProxyVM)''')


    #
    # used in networked appvms or proxyvms (netvm is not None)
    #

    @qubes.tools.qvm_ls.column(width=15)
    @property
    def ip(self):
        '''IP address of this domain.'''
        if not self.is_networked():
            return None
        if self.netvm is not None:
            return self.netvm.get_ip_for_vm(self)
        else:
            return self.get_ip_for_vm(self)


    #
    # used in netvms (provides_network=True)
    # those properties and methods are most likely accessed as vm.netvm.<prop>
    #

    @staticmethod
    def get_ip_for_vm(vm):
        '''Get IP address for (appvm) domain connected to this (netvm) domain.
        '''
        import qubes.vm.dispvm # pylint: disable=redefined-outer-name
        if isinstance(vm, qubes.vm.dispvm.DispVM):
            return '10.138.{}.{}'.format((vm.dispid >> 8) & 7, vm.dispid & 7)

        # VM technically can get address which ends in '.0'. This currently
        # does not happen, because qid < 253, but may happen in the future.
        return '10.137.{}.{}'.format((vm.qid >> 8) & 7, vm.qid & 7)

    @qubes.tools.qvm_ls.column(head='IPBACK', width=15)
    @property
    def gateway(self):
        '''Gateway for other domains that use this domain as netvm.'''
        return self.ip if self.provides_network else None

    @qubes.tools.qvm_ls.column(width=15)
    @property
    def netmask(self):
        '''Netmask for gateway address.'''
        return '255.255.255.255' if self.is_networked() else None

    @qubes.tools.qvm_ls.column(width=7)
    @property
    def vif(self):
        '''Name of the network interface backend in netvm that is connected to
        NIC inside this domain.'''
        if self.xid < 0:
            return None
        if self.netvm is None:
            return None
        return "vif{0}.+".format(self.xid)


    #
    # used in both
    #

    @qubes.tools.qvm_ls.column(width=15)
    @property
    def dns(self):
        '''Secondary DNS server set up for this domain.'''
        if self.netvm is not None or self.provides_network:
            return (
                '10.139.1.1',
                '10.139.1.2',
            )
        else:
            return None


    def __init__(self, *args, **kwargs):
        super(NetVMMixin, self).__init__(*args, **kwargs)
        self.connected_vms = weakref.WeakSet()


    @qubes.events.handler('domain-started')
    def start_net(self):
        '''Connect this domain to its downstream domains.

        This is needed when starting netvm *after* its connected domains.
        '''

        for vm in self.connected_vms:
            if not vm.is_running():
                continue
            vm.log.info('Attaching network')
            # 1426
            vm.cleanup_vifs()

            try:
                # 1426
                vm.run('modprobe -r xen-netfront xennet',
                    user='root', wait=True)
            except:
                pass

            try:
                vm.attach_network(wait=False)
            except qubes.exc.QubesException:
                vm.log.warning('Cannot attach network', exc_info=1)


    @qubes.events.handler('pre-domain-shutdown')
    def shutdown_net(self, force=False):
        connected_vms = [vm for vm in self.connected_vms if vm.is_running()]
        if connected_vms and not force:
            raise qubes.exc.QubesVMError(
                'There are other VMs connected to this VM: {}'.format(
                    ', '.join(vm.name for vm in connected_vms)))

        # detach network interfaces of connected VMs before shutting down,
        # otherwise libvirt will not notice it and will try to detach them
        # again (which would fail, obviously).
        # This code can be removed when #1426 got implemented
        for vm in connected_vms:
            if vm.is_running():
                try:
                    vm.detach_network()
                except (qubes.exc.QubesException, libvirt.libvirtError):
                    # ignore errors
                    pass


    # TODO maybe this should be other way: backend.devices['net'].attach(self)
    def attach_network(self):
        '''Attach network in this machine to it's netvm.'''

        if not self.is_running():
            raise qubes.exc.QubesVMNotRunningError(self)
        assert self.netvm is not None

        if not self.netvm.is_running():
            self.log.info('Starting NetVM ({0})'.format(self.netvm.name))
            self.netvm.start()

        self.libvirt_domain.attachDevice(lxml.etree.ElementTree(
            self.lvxml_net_dev(self.ip, self.mac, self.netvm)).tostring())


    def detach_network(self):
        '''Detach machine from it's netvm'''

        if not self.is_running():
            raise qubes.exc.QubesVMNotRunningError(self)
        assert self.netvm is not None

        self.libvirt_domain.detachDevice(lxml.etree.ElementTree(
            self.lvxml_net_dev(self.ip, self.mac, self.netvm)).tostring())


    def is_networked(self):
        '''Check whether this VM can reach network (firewall notwithstanding).

        :returns: :py:obj:`True` if is machine can reach network, \
            :py:obj:`False` otherwise.
        :rtype: bool
        '''

        if self.provides_network:
            return True

        return self.netvm is not None


    def cleanup_vifs(self):
        '''Remove stale network device backends.

        Libvirt does not remove vif when backend domain is down, so we must do
        it manually. This method is one big hack for #1426.
        '''

        # FIXME: remove this?
        if not self.is_running():
            return

        dev_basepath = '/local/domain/%d/device/vif' % self.xid
        for dev in self.app.vmm.xs.ls('', dev_basepath):
            # check if backend domain is alive
            backend_xid = int(self.app.vmm.xs.read('',
                '{}/{}/backend-id'.format(dev_basepath, dev)))
            if backend_xid in self.app.vmm.libvirt_conn.listDomainsID():
                # check if device is still active
                if self.app.vmm.xs.read('',
                        '{}/{}/state'.format(dev_basepath, dev)) == '4':
                    continue
            # remove dead device
            self.app.vmm.xs.rm('', '{}/{}'.format(dev_basepath, dev))


    @qubes.events.handler('property-del:netvm')
    def on_property_del_netvm(self, event, name, old_netvm):
        # pylint: disable=unused-argument
        # we are changing to default netvm
        new_netvm = self.netvm
        if new_netvm == old_netvm:
            return
        self.fire_event('property-set:netvm', 'netvm', new_netvm, old_netvm)


    @qubes.events.handler('property-set:netvm')
    def on_property_set_netvm(self, event, name, new_netvm, old_netvm=None):
        # pylint: disable=unused-argument
        # TODO offline_mode
        if self.is_running() and new_netvm is not None \
                and not new_netvm.is_running():
            raise qubes.exc.QubesVMNotStartedError(new_netvm,
                'Cannot dynamically attach to stopped NetVM: {!r}'.format(
                    new_netvm))

        if self.netvm is not None:
            self.netvm.connected_vms.remove(self)
            if self.is_running():
                self.detach_network()

                # TODO change to domain-removed event handler in netvm
#               if hasattr(self.netvm, 'post_vm_net_detach'):
#                   self.netvm.post_vm_net_detach(self)

        if new_netvm is not None:
            new_netvm.connected_vms.add(self)

        if new_netvm is None:
            return

        if self.is_running():
            # refresh IP, DNS etc
            self.create_qdb_entries()
            self.attach_network()

            # TODO documentation
            new_netvm.fire_event('net-domain-connect', self)
