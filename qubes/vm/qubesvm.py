#!/usr/bin/python2 -O
# vim: fileencoding=utf-8

#
# The Qubes OS Project, https://www.qubes-os.org/
#
# Copyright (C) 2010-2015  Joanna Rutkowska <joanna@invisiblethingslab.com>
# Copyright (C) 2013-2015  Marek Marczykowski-Górecki
#                              <marmarek@invisiblethingslab.com>
# Copyright (C) 2014-2015  Wojtek Porczyk <woju@invisiblethingslab.com>
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

import datetime
import lxml.etree
import os
import os.path
import re
import shutil
import subprocess
import sys
import time
import uuid
import libvirt

import qubes
import qubes.config
#import qubes.qdb
#import qubes.qmemman
#import qubes.qmemman_algo
import qubes.storage
import qubes.utils
import qubes.vm
import qubes.tools.qvm_ls

qmemman_present = False
try:
    # pylint: disable=import-error
    import qubes.qmemman_client
    qmemman_present = True
except ImportError:
    pass


def _setter_qid(self, prop, value):
    # pylint: disable=unused-argument
    if not 0 <= value <= qubes.config.max_qid:
        raise ValueError(
            '{} value must be between 0 and qubes.config.max_qid'.format(
                prop.__name__))
    return value


def _setter_name(self, prop, value):
    if not isinstance(value, basestring):
        raise TypeError('{} value must be string, {!r} found'.format(
            prop.__name__, type(value).__name__))
    if len(value) > 31:
        raise ValueError('{} value must be shorter than 32 characters'.format(
            prop.__name__))
    if re.match(r"^[a-zA-Z][a-zA-Z0-9_-]*$", value) is None:
        raise ValueError('{} value contains illegal characters'.format(
            prop.__name__))
    if self.is_running():
        raise qubes.QubesException('Cannot change name of running VM')

    try:
        if self.installed_by_rpm:
            raise qubes.QubesException('Cannot rename VM installed by RPM -- '
                'first clone VM and then use yum to remove package.')
    except AttributeError:
        pass

    return value


def _setter_kernel(self, prop, value):
    # pylint: disable=unused-argument
    if not os.path.exists(os.path.join(
            qubes.config.system_path['qubes_kernels_base_dir'], value)):
        raise qubes.QubesException('Kernel {!r} not installed'.format(value))
    for filename in ('vmlinuz', 'modules.img'):
        if not os.path.exists(os.path.join(
                qubes.config.system_path['qubes_kernels_base_dir'],
                    value, filename)):
            raise qubes.QubesException(
                'Kernel {!r} not properly installed: missing {!r} file'.format(
                    value, filename))
    return value


def _default_conf_file(self, name=None):
    return (name or self.name) + '.conf'


class QubesVM(qubes.vm.BaseVM):
    '''Base functionality of Qubes VM shared between all VMs.'''

    #
    # properties loaded from XML
    #

    label = qubes.property('label',
        setter=(lambda self, prop, value: self.app.labels[
            int(value.rsplit('-', 1)[1])]),
        ls_width=14,
        doc='''Colourful label assigned to VM. This is where the colour of the
            padlock is set.''')

    # XXX swallowed uses_default_netvm
    netvm = qubes.VMProperty('netvm', load_stage=4, allow_none=True,
        default=(lambda self: self.app.default_fw_netvm if self.provides_network
            else self.app.default_netvm),
        ls_width=31,
        doc='''VM that provides network connection to this domain. When
            `None`, machine is disconnected. When absent, domain uses default
            NetVM.''')

    provides_network = qubes.property('provides_network',
        type=bool, setter=qubes.property.bool,
        doc='`True` if it is NetVM or ProxyVM, false otherwise.')

    qid = qubes.property('qid', type=int,
        setter=_setter_qid,
        ls_width=3,
        doc='''Internal, persistent identificator of particular domain. Note
            this is different from Xen domid.''')

    name = qubes.property('name', type=str,
        ls_width=31,
        doc='User-specified name of the domain.')

    uuid = qubes.property('uuid', type=uuid.UUID, default=None,
        ls_width=36,
        doc='UUID from libvirt.')

    # TODO meaningful default
    # TODO setter to ensure absolute/relative path?
    dir_path = qubes.property('dir_path', type=str, default=None,
        doc='FIXME')

    conf_file = qubes.property('conf_file', type=str,
        default=_default_conf_file,
        saver=(lambda self, prop, value: self.relative_path(value)),
        doc='XXX libvirt config file?')

    # XXX this should be part of qubes.xml
    firewall_conf = qubes.property('firewall_conf', type=str,
        default='firewall.xml')

    installed_by_rpm = qubes.property('installed_by_rpm',
        type=bool, setter=qubes.property.bool,
        default=False,
        doc='''If this domain's image was installed from package tracked by
            package manager.''')

    memory = qubes.property('memory', type=int,
        default=qubes.config.defaults['memory'],
        doc='Memory currently available for this VM.')

    maxmem = qubes.property('maxmem', type=int, default=None,
        doc='''Maximum amount of memory available for this VM (for the purpose
            of the memory balancer).''')

    internal = qubes.property('internal', default=False,
        type=bool, setter=qubes.property.bool,
        doc='''Internal VM (not shown in qubes-manager, don't create appmenus
            entries.''')

    # XXX what is that
    vcpus = qubes.property('vcpus', default=None,
        ls_width=2,
        doc='FIXME')

    # XXX swallowed uses_default_kernel
    # XXX not applicable to HVM?
    kernel = qubes.property('kernel', type=str,
        setter=_setter_kernel,
        default=(lambda self: self.app.default_kernel),
        ls_width=12,
        doc='Kernel used by this domain.')

    # XXX swallowed uses_default_kernelopts
    # XXX not applicable to HVM?
    kernelopts = qubes.property('kernelopts', type=str, load_stage=4,
        default=(lambda self: qubes.config.defaults['kernelopts_pcidevs'] \
            if len(self.devices['pci']) > 0 \
            else qubes.config.defaults['kernelopts']),
        ls_width=30,
        doc='Kernel command line passed to domain.')

    mac = qubes.property('mac', type=str,
        default=(lambda self: '00:16:3E:5E:6C:{:02X}'.format(self.qid)),
        ls_width=17,
        doc='MAC address of the NIC emulated inside VM')

    debug = qubes.property('debug', type=bool, default=False,
        setter=qubes.property.bool,
        doc='Turns on debugging features.')

    # XXX what this exactly does?
    # XXX shouldn't this go to standalone VM and TemplateVM, and leave here
    #     only plain property?
    default_user = qubes.property('default_user', type=str,
        default=(lambda self: self.template.default_user),
        ls_width=12,
        doc='FIXME')

#   @property
#   def default_user(self):
#       if self.template is not None:
#           return self.template.default_user
#       else:
#           return self._default_user

    qrexec_timeout = qubes.property('qrexec_timeout', type=int, default=60,
        ls_width=3,
        doc='''Time in seconds after which qrexec connection attempt is deemed
            failed. Operating system inside VM should be able to boot in this
            time.''')

    autostart = qubes.property('autostart', default=False,
        type=bool, setter=qubes.property.bool,
        doc='''Setting this to `True` means that VM should be autostarted on
            dom0 boot.''')

    # XXX I don't understand backups
    include_in_backups = qubes.property('include_in_backups', default=True,
        type=bool, setter=qubes.property.bool,
        doc='If this domain is to be included in default backup.')

    backup_content = qubes.property('backup_content', default=False,
        type=bool, setter=qubes.property.bool,
        doc='FIXME')

    backup_size = qubes.property('backup_size', type=int, default=0,
        doc='FIXME')

    backup_path = qubes.property('backup_path', type=str, default='',
        doc='FIXME')

    # format got changed from %s to str(datetime.datetime)
    backup_timestamp = qubes.property('backup_timestamp', default=None,
        setter=(lambda self, prop, value:
            datetime.datetime.fromtimestamp(value)),
        saver=(lambda self, prop, value: value.strftime('%s')),
        doc='FIXME')


    #
    # static, class-wide properties
    #

    # config file should go away to storage/backend class
    #: template for libvirt config file (XML)
    config_file_template = qubes.config.system_path["config_template_pv"]

    #
    # properties not loaded from XML, calculated at run-time
    #

    # VMM-related

    @qubes.tools.qvm_ls.column(width=3)
    @property
    def xid(self):
        '''Xen ID.

        Or not Xen, but ID.
        '''

        if self.libvirt_domain is None:
            return -1
        return self.libvirt_domain.ID()


    @property
    def libvirt_domain(self):
        '''Libvirt domain object from libvirt.

        May be :py:obj:`None`, if libvirt knows nothing about this domain.
        '''

        if self._libvirt_domain is not None:
            return self._libvirt_domain

        # XXX _update_libvirt_domain?
        try:
            if self.uuid is not None:
                self._libvirt_domain = self.app.vmm.libvirt_conn.lookupByUUID(
                    self.uuid.bytes)
            else:
                self._libvirt_domain = self.app.vmm.libvirt_conn.lookupByName(
                    self.name)
                self.uuid = uuid.UUID(bytes=self._libvirt_domain.UUID())
        except libvirt.libvirtError:
            if self.app.vmm.libvirt_conn.virConnGetLastError()[0] == \
                    libvirt.VIR_ERR_NO_DOMAIN:
                self._update_libvirt_domain()
            else:
                raise
        return self._libvirt_domain


    @property
    def qdb(self):
        '''QubesDB handle for this domain.'''
        if self._qdb_connection is None:
            if self.is_running():
                self._qdb_connection = qubes.qdb.QubesDB(self.name)
        return self._qdb_connection


    # XXX this should go to to AppVM?
    @property
    def private_img(self):
        '''Location of private image of the VM (that contains :file:`/rw` \
        and :file:`/home`).'''
        return self.storage.private_img


    # XXX this should go to to AppVM? or TemplateVM?
    @property
    def root_img(self):
        '''Location of root image.'''
        return self.storage.root_img


    # XXX and this should go to exactly where? DispVM has it.
    @property
    def volatile_img(self):
        '''Volatile image that overlays :py:attr:`root_img`.'''
        return self.storage.volatile_img


    @property
    def kernels_dir(self):
        '''Directory where kernel resides.

        If :py:attr:`self.kernel` is :py:obj:`None`, the this points inside
        :py:attr:`self.dir_path`
        '''
        return os.path.join(
            qubes.config.system_path['qubes_kernels_base_dir'], self.kernel) \
            if self.kernel is not None \
        else os.path.join(self.dir_path,
            qubes.config.vm_files['kernels_subdir'])


    # XXX shouldn't this go elsewhere?
    @property
    def updateable(self):
        '''True if this machine may be updated on its own.'''
        return not hasattr(self, 'template')


    @property
    def uses_custom_config(self):
        '''True if this machine has config in non-standard place.'''
        return not self.property_is_default('conf_file')
#       return self.conf_file != self.storage.abspath(self.name + '.conf')

    @property
    def icon_path(self):
        return self.dir_path and os.path.join(self.dir_path, "icon.png")


    # XXX I don't know what to do with these; probably should be isinstance(...)
#   def is_template(self):
#       return False
#
#   def is_appvm(self):
#       return False
#
#   def is_proxyvm(self):
#       return False
#
#   def is_disposablevm(self):
#       return False


    # network-related

    @qubes.tools.qvm_ls.column(width=15)
    @property
    def ip(self):
        '''IP address of this domain.'''
        if self.netvm is not None:
            return self.netvm.get_ip_for_vm(self.qid)
        else:
            return None

    @qubes.tools.qvm_ls.column(width=15)
    @property
    def netmask(self):
        '''Netmask for this domain's IP address.'''
        if self.netvm is not None:
            return self.netvm.netmask
        else:
            return None

    @qubes.tools.qvm_ls.column(head='IPBACK', width=15)
    @property
    def gateway(self):
        '''Gateway for other domains that use this domain as netvm.'''
        # pylint: disable=no-self-use

        # This is gateway IP for _other_ VMs, so make sense only in NetVMs
        return None

    @qubes.tools.qvm_ls.column(width=15)
    @property
    def secondary_dns(self):
        '''Secondary DNS server set up for this domain.'''
        if self.netvm is not None:
            return self.netvm.secondary_dns
        else:
            return None

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
    # constructor
    #

    def __init__(self, app, xml, **kwargs):
        super(QubesVM, self).__init__(app, xml, **kwargs)

        #Init private attrs

        self._libvirt_domain = None
        self._qdb_connection = None

        assert self.qid < qubes.config.max_qid, "VM id out of bounds!"
        assert self.name is not None

        # Not in generic way to not create QubesHost() to frequently
        # XXX this doesn't apply, host is instantiated once
        if self.maxmem is None and not self.app.vmm.offline_mode:
            total_mem_mb = self.app.host.memory_total/1024
            self.maxmem = total_mem_mb/2

        # Linux specific cap: max memory can't scale beyond 10.79*init_mem
        # see https://groups.google.com/forum/#!topic/qubes-devel/VRqkFj1IOtA
        if self.maxmem > self.memory * 10:
            self.maxmem = self.memory * 10

        # By default allow use all VCPUs
        if not hasattr(self, 'vcpus') and not self.app.vmm.offline_mode:
            self.vcpus = self.app.host.no_cpus

        # Always set if meminfo-writer should be active or not
        if 'meminfo-writer' not in self.services:
            self.services['meminfo-writer'] = not len(self.devices['pci']) > 0

        # Additionally force meminfo-writer disabled when VM have PCI devices
        if len(self.devices['pci']) > 0:
            self.services['meminfo-writer'] = False

        # Initialize VM image storage class
        self.storage = qubes.storage.get_storage(self)

        if self.kernels_dir is not None: # it is None for AdminVM
            self.storage.modules_img = os.path.join(self.kernels_dir,
                'modules.img')
            self.storage.modules_img_rw = self.kernel is None

        # fire hooks
        self.fire_event('domain-init')


    #
    # event handlers
    #

    @qubes.events.handler('property-set:label')
    def on_property_set_label(self, event, name, new_label, old_label=None):
        # pylint: disable=unused-argument
        if self.icon_path:
            try:
                os.remove(self.icon_path)
            except:
                pass
            if hasattr(os, "symlink"):
                os.symlink(new_label.icon_path, self.icon_path)
                # FIXME: some os-independent wrapper?
                subprocess.call(['sudo', 'xdg-icon-resource', 'forceupdate'])
            else:
                shutil.copy(new_label.icon_path, self.icon_path)


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
        if self.is_running() and new_netvm is not None \
                and not new_netvm.is_running():
            raise qubes.QubesException(
                'Cannot dynamically attach to stopped NetVM')

        if self.netvm is not None:
            del self.netvm.connected_vms[self]
            if self.is_running():
                self.detach_network()

                # TODO change to domain-removed event handler in netvm
#               if hasattr(self.netvm, 'post_vm_net_detach'):
#                   self.netvm.post_vm_net_detach(self)

        if new_netvm is None:
#           if not self._do_not_reset_firewall:
            # Set also firewall to block all traffic as discussed in #370
            if os.path.exists(self.firewall_conf):
                shutil.copy(self.firewall_conf,
                    os.path.join(qubes.config.system_path['qubes_base_dir'],
                        'backup',
                        '%s-firewall-%s.xml' % (self.name,
                            time.strftime('%Y-%m-%d-%H:%M:%S'))))
            self.write_firewall_conf({'allow': False, 'allowDns': False,
                'allowIcmp': False, 'allowYumProxy': False, 'rules': []})
        else:
            new_netvm.connected_vms.add(self)

        if new_netvm is None:
            return

        if self.is_running():
            # refresh IP, DNS etc
            self.create_qdb_entries()
            self.attach_network()

            # TODO domain-added event handler in netvm
#           if hasattr(self.netvm, 'post_vm_net_attach'):
#               self.netvm.post_vm_net_attach(self)


    @qubes.events.handler('property-pre-set:name')
    def on_property_pre_set_name(self, event, name, newvalue, oldvalue=None):
        # pylint: disable=unused-argument
        # TODO not self.is_stopped() would be more appropriate
        if self.is_running():
            raise qubes.QubesException('Cannot change name of running domain')


    @qubes.events.handler('property-pre-set:dir_path')
    def on_property_pre_set_dir_path(self, event, name, newvalue,
            oldvalue=None):
        # pylint: disable=unused-argument
        # TODO not self.is_stopped() would be more appropriate
        if self.is_running():
            raise qubes.QubesException(
                'Cannot change dir_path of running domain')


    @qubes.events.handler('property-set:dir_path')
    def on_property_set_dir_path(self, event, name, newvalue, oldvalue=None):
        # pylint: disable=unused-argument
        self.storage.rename(newvalue, oldvalue)


    @qubes.events.handler('property-set:name')
    def on_property_set_name(self, event, name, new_name, old_name=None):
        # pylint: disable=unused-argument
        if self._libvirt_domain is not None:
            self.libvirt_domain.undefine()
            self._libvirt_domain = None
        if self._qdb_connection is not None:
            self._qdb_connection.close()
            self._qdb_connection = None

        # move: dir_path, conf_file
        self.dir_path = self.dir_path.replace(
            '/{}/', '/{}/'.format(old_name, new_name))

        if self.property_is_default('conf_file'):
            new_conf = os.path.join(
                self.dir_path, _default_conf_file(self, old_name))
            old_conf = os.path.join(
                self.dir_path, _default_conf_file(self, old_name))
            self.storage.rename(old_conf, new_conf)

            self.fire_event('property-set:conf_file', 'conf_file',
                new_conf, old_conf)

        self._update_libvirt_domain()


    @qubes.events.handler('property-pre-set:autostart')
    def on_property_pre_set_autostart(self, event, prop, name, value,
            oldvalue=None):
        # pylint: disable=unused-argument
        if subprocess.call(['sudo', 'systemctl',
                ('enable' if value else 'disable'),
                'qubes-vm@{}.service'.format(self.name)]):
            raise qubes.QubesException(
                'Failed to set autostart for VM via systemctl')


    @qubes.events.handler('device-pre-attached:pci')
    def on_device_pre_attached_pci(self, event, pci):
        # pylint: disable=unused-argument
        if not os.path.exists('/sys/bus/pci/devices/0000:{}'.format(pci)):
            raise qubes.QubesException('Invalid PCI device: {}'.format(pci))

        if not self.is_running():
            return

        try:
            # TODO: libvirt-ise
            subprocess.check_call(
                ['sudo', qubes.config.system_path['qubes_pciback_cmd'], pci])
            subprocess.check_call(
                ['sudo', 'xl', 'pci-attach', str(self.xid), pci])
        except Exception as e:
            print >>sys.stderr, "Failed to attach PCI device on the fly " \
                "(%s), changes will be seen after VM restart" % str(e)


    @qubes.events.handler('device-pre-detached:pci')
    def on_device_pre_detached_pci(self, event, pci):
        # pylint: disable=unused-argument
        if not self.is_running():
            return

        # TODO: libvirt-ise
        p = subprocess.Popen(['xl', 'pci-list', str(self.xid)],
                stdout=subprocess.PIPE)
        result = p.communicate()
        m = re.search(r"^(\d+.\d+)\s+0000:%s$" % pci, result[0],
            flags=re.MULTILINE)
        if not m:
            print >>sys.stderr, "Device %s already detached" % pci
            return
        vmdev = m.group(1)
        try:
            self.run_service("qubes.DetachPciDevice",
                user="root", input="00:%s" % vmdev)
            subprocess.check_call(
                ['sudo', 'xl', 'pci-detach', str(self.xid), pci])
        except Exception as e:
            print >>sys.stderr, "Failed to detach PCI device on the fly " \
                "(%s), changes will be seen after VM restart" % str(e)


    #
    # methods for changing domain state
    #

    def start(self, preparing_dvm=False, start_guid=True,
            notify_function=None, mem_required=None):
        '''Start domain

        :param bool preparing_dvm: FIXME
        :param bool start_guid: FIXME
        :param collections.Callable notify_function: FIXME
        :param int mem_required: FIXME
        '''

        # Intentionally not used is_running(): eliminate also "Paused",
        # "Crashed", "Halting"
        if self.get_power_state() != 'Halted':
            raise qubes.QubesException('VM is already running!')

        self.log.info('Starting {}'.format(self.name))

        self.verify_files()

        if self.netvm is not None:
            if self.netvm.qid != 0:
                if not self.netvm.is_running():
                    self.netvm.start(start_guid=start_guid,
                        notify_function=notify_function)

        self.storage.prepare_for_vm_startup()
        self._update_libvirt_domain()

        if mem_required is None:
            mem_required = int(self.memory) * 1024 * 1024
        if qmemman_present:
            qmemman_client = qubes.qmemman_client.QMemmanClient()
            try:
                got_memory = qmemman_client.request_memory(mem_required)
            except IOError as e:
                raise IOError('Failed to connect to qmemman: {!s}'.format(e))
            if not got_memory:
                qmemman_client.close()
                raise MemoryError(
                    'Insufficient memory to start VM {!r}'.format(self.name))

        # Bind pci devices to pciback driver
        for pci in self.devices['pci']:
            node = self.app.vmm.libvirt_conn.nodeDeviceLookupByName(
                'pci_0000_' + pci.replace(':', '_').replace('.', '_'))
            try:
                node.dettach()
            except libvirt.libvirtError:
                if self.app.vmm.libvirt_conn.virConnGetLastError()[0] == \
                        libvirt.VIR_ERR_INTERNAL_ERROR:
                    # already detached
                    pass
                else:
                    raise

        self.libvirt_domain.createWithFlags(libvirt.VIR_DOMAIN_START_PAUSED)

        if preparing_dvm:
            self.services['qubes-dvm'] = True

        self.log.info('Setting Qubes DB info for the VM')
        self.start_qubesdb()
        self.create_qdb_entries()

        self.log.info('Updating firewall rules')

        for vm in self.app.domains:
            if vm.is_proxyvm() and vm.is_running():
                vm.write_iptables_xenstore_entry()

        self.fire_event('domain-started',
            preparing_dvm=preparing_dvm, start_guid=start_guid)


        self.log.warning('Activating the {} VM'.format(self.name))
        self.libvirt_domain.resume()

        # close() is not really needed, because the descriptor is close-on-exec
        # anyway, the reason to postpone close() is that possibly xl is not done
        # constructing the domain after its main process exits
        # so we close() when we know the domain is up
        # the successful unpause is some indicator of it
        if qmemman_present:
            qmemman_client.close()

#       if self._start_guid_first and start_guid and not preparing_dvm \
#               and os.path.exists('/var/run/shm.id'):
#           self.start_guid()

        if not preparing_dvm:
            self.start_qrexec_daemon()

        if start_guid and not preparing_dvm \
                and os.path.exists('/var/run/shm.id'):
            self.start_guid()


    def shutdown(self):
        '''Shutdown domain.

        :raises QubesException: when domain is already shut down.
        '''

        if not self.is_running():
            raise qubes.QubesException("VM already stopped!")

        self.libvirt_domain.shutdown()


    def force_shutdown(self):
        '''Forcefuly shutdown (destroy) domain.

        :raises QubesException: when domain is already shut down.
        '''

        if not self.is_running() and not self.is_paused():
            raise qubes.QubesException('VM already stopped!')

        self.libvirt_domain.destroy()


    def suspend(self):
        '''Suspend (pause) domain.

        :raises qubes.QubesException: when domain is already shut down.
        :raises NotImplemetedError: when domain has PCI devices attached.
        '''

        if not self.is_running() and not self.is_paused():
            raise qubes.QubesException('VM already stopped!')

        if len(self.devices['pci']) > 0:
            raise NotImplementedError()
        else:
            self.libvirt_domain.suspend()


    def pause(self):
        '''Pause (suspend) domain. This currently delegates to \
        :py:meth:`suspend`.'''

        if not self.is_running():
            raise qubes.QubesException('VM not running!')

        self.suspend()


    def resume(self):
        '''Resume suspended domain.

        :raises NotImplemetedError: when machine is alread suspended.
        '''

        if self.get_power_state() == "Suspended":
            raise NotImplementedError()
        else:
            self.unpause()

    def unpause(self):
        '''Resume (unpause) a domain'''
        if not self.is_paused():
            raise qubes.QubesException('VM not paused!')

        self.libvirt_domain.resume()


    def run(self, command, user=None, autostart=False, notify_function=None,
            passio=False, passio_popen=False, passio_stderr=False,
            ignore_stderr=False, localcmd=None, wait=False, gui=True,
            filter_esc=False):
        '''Run specified command inside domain

        :param str command: the command to be run
        :param str user: user to run the command as
        :param bool autostart: if :py:obj:`True`, machine will be started if \
            it is not running
        :param collections.Callable notify_function: FIXME, may go away
        :param bool passio: FIXME
        :param bool passio_popen: if :py:obj:`True`, \
            :py:class:`subprocess.Popen` object has connected ``stdin`` and \
            ``stdout``
        :param bool passio_stderr: if :py:obj:`True`, \
            :py:class:`subprocess.Popen` has additionaly ``stderr`` connected
        :param bool ignore_stderr: if :py:obj:`True`, ``stderr`` is connected \
            to :file:`/dev/null`
        :param str localcmd: local command to communicate with remote command
        :param bool wait: if :py:obj:`True`, wait for command completion
        :param bool gui: when autostarting, also start gui daemon
        :param bool filter_esc: filter escape sequences to protect terminal \
            emulator
        '''

        if user is None:
            user = self.default_user
        null = None
        if not self.is_running() and not self.is_paused():
            if not autostart:
                raise qubes.QubesException('VM not running')

            try:
                if notify_function is not None:
                    notify_function('info',
                        'Starting the {!r} VM...'.format(self.name))
                self.start(start_guid=gui, notify_function=notify_function)

            except (IOError, OSError, qubes.QubesException) as e:
                raise qubes.QubesException(
                    'Error while starting the {!r} VM: {!s}'.format(
                        self.name, e))
            except MemoryError:
                raise qubes.QubesException('Not enough memory to start {!r} VM!'
                    ' Close one or more running VMs and try again.'.format(
                        self.name))

        if self.is_paused():
            raise qubes.QubesException('VM is paused')
        if not self.is_qrexec_running():
            raise qubes.QubesException(
                "Domain '{}': qrexec not connected.".format(self.name))

        if gui and os.getenv("DISPLAY") is not None \
                and not self.is_guid_running():
            self.start_guid()

        args = [qubes.config.system_path['qrexec_client_path'],
            '-d', str(self.name),
            '{}:{}'.format(user, command)]
        if localcmd is not None:
            args += ['-l', localcmd]
        if filter_esc:
            args += ['-t']
        if os.isatty(sys.stderr.fileno()):
            args += ['-T']

        # TODO: QSB#13
        if passio:
            if os.name == 'nt':
                # wait for qrexec-client to exit, otherwise client is not
                # properly attached to console if qvm-run is executed from
                # cmd.exe
                ret = subprocess.call(args)
                exit(ret)
            os.execv(qubes.config.system_path['qrexec_client_path'], args)
            exit(1)

        call_kwargs = {}
        if ignore_stderr:
            null = open("/dev/null", "w")
            call_kwargs['stderr'] = null

        if passio_popen:
            popen_kwargs = {'stdout': subprocess.PIPE}
            popen_kwargs['stdin'] = subprocess.PIPE
            if passio_stderr:
                popen_kwargs['stderr'] = subprocess.PIPE
            else:
                popen_kwargs['stderr'] = call_kwargs.get('stderr', None)
            p = subprocess.Popen(args, **popen_kwargs)
            if null:
                null.close()
            return p
        if not wait:
            args += ["-e"]
        retcode = subprocess.call(args, **call_kwargs)
        if null:
            null.close()
        return retcode


    def run_service(self, service, source=None, user=None,
                    passio_popen=False, input=None):
        '''Run service on this VM

        **passio_popen** and **input** are mutually exclusive.

        :param str service: service name
        :param qubes.vm.qubesvm.QubesVM: source domain as presented to this VM
        :param str user: username to run service as
        :param bool passio_popen: passed verbatim to :py:meth:`run`
        :param str input: string passed as input to service
        ''' # pylint: disable=redefined-builtin

        if input is not None and passio_popen is not None:
            raise ValueError("'input' and 'passio_popen' cannot be used "
                "together")

        source = 'dom0' if source is None else self.app.domains[source].name

        # XXX TODO FIXME this looks bad...
        if input:
            return self.run("QUBESRPC %s %s" % (service, source),
                        localcmd="echo %s" % input, user=user, wait=True)
        else:
            return self.run("QUBESRPC %s %s" % (service, source),
                        passio_popen=passio_popen, user=user, wait=True)



    def start_guid(self, extra_guid_args=None):
        '''Launch gui daemon.

        GUI daemon securely displays windows from domain.

        :param list extra_guid_args: Extra argv to pass to :program:`guid`.
        '''

        self.log.info('Starting gui daemon')

        guid_cmd = [qubes.config.system_path['qubes_guid_path'],
            '-d', str(self.xid), "-N", self.name,
            '-c', self.label.color,
            '-i', self.label.icon_path,
            '-l', str(self.label.index)]
        if extra_guid_args is not None:
            guid_cmd += extra_guid_args

        if self.debug:
            guid_cmd += ['-v', '-v']

#       elif not verbose:
        guid_cmd += ['-q']

        retcode = subprocess.call(guid_cmd)
        if retcode != 0:
            raise qubes.QubesException('Cannot start qubes-guid!')

        self.log.info('Sending monitor layout')

        try:
            subprocess.call(
                [qubes.config.system_path['monitor_layout_notify_cmd'],
                    self.name])
        except Exception as e:
            self.log.error('ERROR: {!s}'.format(e))

        self.wait_for_session()


    def start_qrexec_daemon(self):
        '''Start qrexec daemon.

        :raises OSError: when starting fails.
        '''

        self.log.debug('Starting the qrexec daemon')
        qrexec_args = [str(self.xid), self.name, self.default_user]
        if not self.debug:
            qrexec_args.insert(0, "-q")
        qrexec_env = os.environ.copy()
        qrexec_env['QREXEC_STARTUP_TIMEOUT'] = str(self.qrexec_timeout)
        retcode = subprocess.call(
            [qubes.config.system_path["qrexec_daemon_path"]] + qrexec_args,
            env=qrexec_env)
        if retcode != 0:
            raise OSError('Cannot execute qrexec-daemon!')


    def start_qubesdb(self):
        '''Start QubesDB daemon.

        :raises OSError: when starting fails.
        '''

        self.log.info('Starting Qubes DB')

        retcode = subprocess.call([
            qubes.config.system_path["qubesdb_daemon_path"],
            str(self.xid),
            self.name])
        if retcode != 0:
            self.force_shutdown()
            raise OSError("ERROR: Cannot execute qubesdb-daemon!")


    def wait_for_session(self):
        '''Wait until machine finished boot sequence.

        This is done by executing qubes RPC call that checks if dummy system
        service (which is started late in standard runlevel) is active.
        '''

        self.log.info('Waiting for qubes-session')

        # Note : User root is redefined to SYSTEM in the Windows agent code
        p = self.run('QUBESRPC qubes.WaitForSession none',
            user="root", passio_popen=True, gui=False, wait=True)
        p.communicate(input=self.default_user)


    def create_on_disk(self, source_template=None):
        '''Create files needed for VM.

        :param qubes.vm.templatevm.TemplateVM source_template: Template to use
            (if :py:obj:`None`, use domain's own template
        '''

        if source_template is None:
            # pylint: disable=no-member
            source_template = self.template
        assert source_template is not None

        self.storage.create_on_disk(source_template)

        if self.updateable:
            kernels_dir = source_template.kernels_dir
            self.log.info(
                'Copying the kernel (unset kernel to use it): {0}'.format(
                    kernels_dir))

            os.mkdir(self.dir_path + '/kernels')
            for filename in ("vmlinuz", "initramfs", "modules.img"):
                shutil.copy(os.path.join(kernels_dir, filename),
                    os.path.join(self.dir_path,
                        qubes.config.vm_files["kernels_subdir"], filename))

        self.log.info('Creating icon symlink: {} -> {}'.format(
            self.icon_path, self.label.icon_path))
        if hasattr(os, "symlink"):
            os.symlink(self.label.icon_path, self.icon_path)
        else:
            shutil.copy(self.label.icon_path, self.icon_path)

        # fire hooks
        self.fire_event('domain-created-on-disk', source_template)


    def resize_private_img(self, size):
        '''Resize private image.'''

        # TODO QubesValueError, not assert
        assert size >= self.get_private_img_sz(), "Cannot shrink private.img"

        # resize the image
        self.storage.resize_private_img(size)

        # and then the filesystem
        # FIXME move this to qubes.storage.xen.XenVMStorage
        retcode = 0
        if self.is_running():
            retcode = self.run('''
                while [ "`blockdev --getsize64 /dev/xvdb`" -lt {0} ]; do
                    head /dev/xvdb >/dev/null;
                    sleep 0.2;
                done;
                resize2fs /dev/xvdb'''.format(size), user="root", wait=True)
        if retcode != 0:
            raise qubes.QubesException('resize2fs failed')


    def remove_from_disk(self):
        '''Remove domain remnants from disk.'''
        self.fire_event('domain-removed-from-disk')
        self.storage.remove_from_disk()


    def clone_disk_files(self, src):
        '''Clone files from other vm.

        :param qubes.vm.qubesvm.QubesVM src: source VM
        '''

        if src.is_running():
            raise qubes.QubesException('Attempt to clone a running VM!')

        self.storage.clone_disk_files(src, verbose=False)

        if src.icon_path is not None \
                and os.path.exists(src.dir_path) \
                and self.icon_path is not None:
            if os.path.islink(src.icon_path):
                icon_path = os.readlink(src.icon_path)
                self.log.info(
                    'Creating icon symlink {} -> {}'.format(
                        self.icon_path, icon_path))
                os.symlink(icon_path, self.icon_path)
            else:
                self.log.info(
                    'Copying icon {} -> {}'.format(
                        src.icon_path, self.icon_path))
                shutil.copy(src.icon_path, self.icon_path)

        # fire hooks
        self.fire_event('cloned-files', src)


    # TODO maybe this should be other way: backend.devices['net'].attach(self)
    def attach_network(self):
        '''Attach network in this machine to it's netvm.'''

        if not self.is_running():
            raise qubes.QubesException('VM not running!')

        if self.netvm is None:
            raise qubes.QubesException('NetVM not set!')

        if not self.netvm.is_running():
            self.log.info('Starting NetVM ({0})'.format(self.netvm.name))
            self.netvm.start()

        self.libvirt_domain.attachDevice(lxml.etree.ElementTree(
            self.lvxml_net_dev(self.ip, self.mac, self.netvm)).tostring())


    def detach_network(self):
        '''Detach machine from it's netvm'''

        if not self.is_running():
            raise qubes.QubesException('VM not running!')

        if self.netvm is None:
            raise qubes.QubesException('NetVM not set!')


        self.libvirt_domain.detachDevice(lxml.etree.ElementTree(
            self.lvxml_net_dev(self.ip, self.mac, self.netvm)).tostring())


    #
    # methods for querying domain state
    #

    # state of the machine

    def get_power_state(self):
        '''Return power state description string.

        Return value may be one of those:

        =============== ========================================================
        return value    meaning
        =============== ========================================================
        ``'Halted'``    Machine is not active.
        ``'Transient'`` Machine is running, but does not have :program:`guid`
                        or :program:`qrexec` available.
        ``'Running'``   Machine is ready and running.
        ``'Paused'``    Machine is paused (currently not available, see below).
        ``'Suspended'`` Machine is S3-suspended.
        ``'Halting'``   Machine is in process of shutting down.
        ``'Dying'``     Machine crashed and is unusable.
        ``'Crashed'``   Machine crashed and is unusable, probably because of
                        bug in dom0.
        ``'NA'``        Machine is in unknown state (most likely libvirt domain
                        is undefined).
        =============== ========================================================

        ``Paused`` state is currently unavailable because of missing code in
        libvirt/xen glue.

        FIXME: graph below may be incomplete and wrong. Click on method name to
        see its documentation.

        .. graphviz::

            digraph {
                node [fontname="sans-serif"];
                edge [fontname="mono"];


                Halted;
                NA;
                Dying;
                Crashed;
                Transient;
                Halting;
                Running;
                Paused [color=gray75 fontcolor=gray75];
                Suspended;

                NA -> Halted;
                Halted -> NA [constraint=false];

                Halted -> Transient
                    [xlabel="start()" URL="#qubes.vm.qubesvm.QubesVM.start"];
                Transient -> Running;

                Running -> Halting
                    [xlabel="shutdown()"
                        URL="#qubes.vm.qubesvm.QubesVM.shutdown"
                        constraint=false];
                Halting -> Dying -> Halted [constraint=false];

                /* cosmetic, invisible edges to put rank constraint */
                Dying -> Halting [style="invis"];
                Halting -> Transient [style="invis"];

                Running -> Halted
                    [label="force_shutdown()"
                        URL="#qubes.vm.qubesvm.QubesVM.force_shutdown"
                        constraint=false];

                Running -> Crashed [constraint=false];
                Crashed -> Halted [constraint=false];

                Running -> Paused
                    [label="pause()" URL="#qubes.vm.qubesvm.QubesVM.pause"
                        color=gray75 fontcolor=gray75];
                Running -> Suspended
                    [label="pause()" URL="#qubes.vm.qubesvm.QubesVM.pause"
                        color=gray50 fontcolor=gray50];
                Paused -> Running
                    [label="unpause()" URL="#qubes.vm.qubesvm.QubesVM.unpause"
                        color=gray75 fontcolor=gray75];
                Suspended -> Running
                    [label="unpause()" URL="#qubes.vm.qubesvm.QubesVM.unpause"
                        color=gray50 fontcolor=gray50];

                Running -> Suspended
                    [label="suspend()" URL="#qubes.vm.qubesvm.QubesVM.suspend"];
                Suspended -> Running
                    [label="resume()" URL="#qubes.vm.qubesvm.QubesVM.resume"];


                { rank=source; Halted NA };
                { rank=same; Transient Halting };
                { rank=same; Crashed Dying };
                { rank=sink; Paused Suspended };
            }

        .. seealso::

            http://wiki.libvirt.org/page/VM_lifecycle
                Description of VM life cycle from the point of view of libvirt.

            https://libvirt.org/html/libvirt-libvirt-domain.html#virDomainState
                Libvirt's enum describing precise state of a domain.
        ''' # pylint: disable=too-many-return-statements

        libvirt_domain = self.libvirt_domain
        if libvirt_domain is None:
            return "NA"

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


    def is_running(self):
        '''Check whether this domain is running.

        :returns: :py:obj:`True` if this domain is started, \
            :py:obj:`False` otherwise.
        :rtype: bool
        '''

        return self.libvirt_domain and self.libvirt_domain.isActive()


    def is_paused(self):
        '''Check whether this domain is paused.

        :returns: :py:obj:`True` if this domain is paused, \
            :py:obj:`False` otherwise.
        :rtype: bool
        '''

        return self.libvirt_domain \
            and self.libvirt_domain.state() == libvirt.VIR_DOMAIN_PAUSED


    def is_guid_running(self):
        '''Check whether gui daemon for this domain is available.

        :returns: :py:obj:`True` if guid is running, \
            :py:obj:`False` otherwise.
        :rtype: bool
        '''
        xid = self.xid
        if xid < 0:
            return False
        if not os.path.exists('/var/run/qubes/guid-running.%d' % xid):
            return False
        return True


    def is_qrexec_running(self):
        '''Check whether qrexec for this domain is available.

        :returns: :py:obj:`True` if qrexec is running, \
            :py:obj:`False` otherwise.
        :rtype: bool
        '''
        if self.xid < 0:
            return False
        return os.path.exists('/var/run/qubes/qrexec.%s' % self.name)


    def is_fully_usable(self):
        '''Check whether domain is running and sane.

        Currently this checks for running guid and qrexec.

        :returns: :py:obj:`True` if qrexec is running, \
            :py:obj:`False` otherwise.
        :rtype: bool
        '''

        # Running gui-daemon implies also VM running
        if not self.is_guid_running():
            return False
        if not self.is_qrexec_running():
            return False
        return True


    # memory and disk

    def get_mem(self):
        '''Get current memory usage from VM.

        :returns: Memory usage [FIXME unit].
        :rtype: FIXME
        '''

        if self.libvirt_domain is None:
            return 0
        if not self.libvirt_domain.isActive():
            return 0

        return self.libvirt_domain.info()[1]


    def get_mem_static_max(self):
        '''Get maximum memory available to VM.

        :returns: Memory limit [FIXME unit].
        :rtype: FIXME
        '''

        if self.libvirt_domain is None:
            return 0

        return self.libvirt_domain.maxMemory()


    def get_per_cpu_time(self):
        '''Get total CPU time burned by this domain since start.

        :returns: CPU time usage [FIXME unit].
        :rtype: FIXME
        '''

        if self.libvirt_domain is None:
            return 0
        if not self.libvirt_domain.isActive():
            return 0

        return self.libvirt_domain.getCPUStats(
            libvirt.VIR_NODE_CPU_STATS_ALL_CPUS, 0)[0]['cpu_time']/10**9


    # XXX shouldn't this go only to vms that have root image?
    def get_disk_utilization_root_img(self):
        '''Get space that is actually ocuppied by :py:attr:`root_img`.

        Root image is a sparse file, so it is probably much less than logical
        available space.

        :returns: domain's real disk image size [FIXME unit]
        :rtype: FIXME

        .. seealso:: :py:meth:`get_root_img_sz`
        '''

        return qubes.utils.get_disk_usage(self.root_img)


    # XXX shouldn't this go only to vms that have root image?
    def get_root_img_sz(self):
        '''Get image size of :py:attr:`root_img`.

        Root image is a sparse file, so it is probably much more than ocuppied
        physical space.

        :returns: domain's virtual disk size [FIXME unit]
        :rtype: FIXME

        .. seealso:: :py:meth:`get_disk_utilization_root_img`
        '''

        if not os.path.exists(self.root_img):
            return 0

        return os.path.getsize(self.root_img)


    def get_disk_utilization_private_img(self):
        '''Get space that is actually ocuppied by :py:attr:`private_img`.

        Private image is a sparse file, so it is probably much less than
        logical available space.

        :returns: domain's real disk image size [FIXME unit]
        :rtype: FIXME

        .. seealso:: :py:meth:`get_private_img_sz`
        ''' # pylint: disable=invalid-name

        return qubes.utils.get_disk_usage(self.private_img)


    def get_private_img_sz(self):
        '''Get image size of :py:attr:`private_img`.

        Private image is a sparse file, so it is probably much more than
        ocuppied physical space.

        :returns: domain's virtual disk size [FIXME unit]
        :rtype: FIXME

        .. seealso:: :py:meth:`get_disk_utilization_private_img`
        '''

        return self.storage.get_private_img_sz()


    def get_disk_utilization(self):
        '''Return total space actually occuppied by all files belonging to \
            this domain.

        :returns: domain's total disk usage [FIXME unit]
        :rtype: FIXME
        '''

        return qubes.utils.get_disk_usage(self.dir_path)


    def verify_files(self):
        '''Verify that files accessed by this machine are sane.

        On success, returns normally. On failure, raises exception.
        '''

        self.storage.verify_files()

        if not os.path.exists(os.path.join(self.kernels_dir, 'vmlinuz')):
            raise qubes.QubesException('VM kernel does not exist: {0}'.format(
                os.path.join(self.kernels_dir, 'vmlinuz')))

        if not os.path.exists(os.path.join(self.kernels_dir, 'initramfs')):
            raise qubes.QubesException(
                'VM initramfs does not exist: {0}'.format(
                    os.path.join(self.kernels_dir, 'initramfs')))

        self.fire_event('verify-files')

        return True


    # miscellanous

    def get_start_time(self):
        '''Tell when machine was started.

        :rtype: datetime.datetime
        '''
        if not self.is_running():
            return None

        # TODO shouldn't this be qubesdb?
        start_time = self.app.vmm.xs.read('',
            '/vm/{}/start_time'.format(self.uuid))
        if start_time != '':
            return datetime.datetime.fromtimestamp(float(start_time))
        else:
            return None


    # XXX this probably should go to AppVM
    def is_outdated(self):
        '''Check whether domain needs restart to update root image from \
            template.

        :returns: :py:obj:`True` if is outdated, :py:obj:`False` otherwise.
        :rtype: bool
        '''

        # Makes sense only on VM based on template
        if self.template is None:
            return False
        # pylint: disable=no-member

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
        used_dmdev = self.app.vmm.xs.read('',
            '/local/domain/0/backend/vbd/{}/51712/node'.format(self.xid))

        return used_dmdev != current_dmdev


    def is_networked(self):
        '''Check whether this VM can reach network (firewall notwithstanding).

        :returns: :py:obj:`True` if is machine can reach network, \
            :py:obj:`False` otherwise.
        :rtype: bool
        '''

        if self.provides_network:
            return True

        return self.netvm is not None


    #
    # helper methods
    #

    def relative_path(self, path):
        '''Return path relative to py:attr:`dir_path`.

        :param str path: Path in question.
        :returns: Relative path.
        '''

        return os.path.relpath(path, self.dir_path)
#       return arg.replace(self.dir_path + '/', '')


    def create_qdb_entries(self):
        '''Create entries in Qubes DB.
        '''
        self.qdb.write("/name", self.name)
        self.qdb.write("/qubes-vm-type", self.type)
        self.qdb.write("/qubes-vm-updateable", str(self.updateable))

        if self.provides_network:
            self.qdb.write("/qubes-netvm-gateway", self.gateway)
            self.qdb.write("/qubes-netvm-secondary-dns", self.secondary_dns)
            self.qdb.write("/qubes-netvm-netmask", self.netmask)
            self.qdb.write("/qubes-netvm-network", self.network)

        if self.netvm is not None:
            self.qdb.write("/qubes-ip", self.ip)
            self.qdb.write("/qubes-netmask", self.netvm.netmask)
            self.qdb.write("/qubes-gateway", self.netvm.gateway)
            self.qdb.write("/qubes-secondary-dns", self.netvm.secondary_dns)

        tzname = qubes.utils.get_timezone()
        if tzname:
            self.qdb.write("/qubes-timezone", tzname)

        for srv in self.services.keys():
            # convert True/False to "1"/"0"
            self.qdb.write("/qubes-service/{0}".format(srv),
                    str(int(self.services[srv])))

        self.qdb.write("/qubes-block-devices", '')

        self.qdb.write("/qubes-usb-devices", '')

        self.qdb.write("/qubes-debug-mode", str(int(self.debug)))

        # TODO: Currently the whole qmemman is quite Xen-specific, so stay with
        # xenstore for it until decided otherwise
        if qmemman_present:
            self.app.vmm.xs.set_permissions('',
                '/local/domain/{}/memory'.format(self.xid),
                [{'dom': self.xid}])

        self.fire_event('qdb-created')


    def _update_libvirt_domain(self):
        '''Re-initialise :py:attr:`libvirt_domain`.'''
        domain_config = self.create_config_file()
        if self._libvirt_domain is not None:
            self._libvirt_domain.undefine()
        try:
            self._libvirt_domain = self.app.vmm.libvirt_conn.defineXML(
                domain_config)
            self.uuid = uuid.UUID(bytes=self._libvirt_domain.UUID())
        except libvirt.libvirtError:
            if self.app.vmm.libvirt_conn.virConnGetLastError()[0] == \
                    libvirt.VIR_ERR_NO_DOMAIN:
                # accept the fact that libvirt doesn't know anything about this
                # domain...
                pass
            else:
                raise


    def cleanup_vifs(self):
        '''Remove stale network device backends.

        Xend does not remove vif when backend domain is down, so we must do it
        manually.
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











    #
    # workshop -- those are to be reworked later
    #

    def get_prefmem(self):
        # TODO: qmemman is still xen specific
        untrusted_meminfo_key = self.app.vmm.xs.read('',
            '/local/domain/{}/memory/meminfo'.format(self.xid))
        if untrusted_meminfo_key is None or untrusted_meminfo_key == '':
            return 0
        domain = qmemman.DomainState(self.xid)
        qmemman_algo.refresh_meminfo_for_domain(domain, untrusted_meminfo_key)
        domain.memory_maximum = self.get_mem_static_max()*1024
        return qmemman_algo.prefmem(domain)/1024



    #
    # landfill -- those are unneeded
    #




#       attrs = {
    # XXX probably will be obsoleted by .events_enabled
#   "_do_not_reset_firewall": { "func": lambda x: False },

#   "_start_guid_first": { "func": lambda x: False },
#   }

    # this function appears unused
#   def _cleanup_zombie_domains(self):
#       """
#       This function is workaround broken libxl (which leaves not fully
#       created domain on failure) and vchan on domain crash behaviour
#       @return: None
#       """
#       xc = self.get_xc_dominfo()
#       if xc and xc['dying'] == 1:
#           # GUID still running?
#           guid_pidfile = '/var/run/qubes/guid-running.%d' % xc['domid']
#           if os.path.exists(guid_pidfile):
#               guid_pid = open(guid_pidfile).read().strip()
#               os.kill(int(guid_pid), 15)
#           # qrexec still running?
#           if self.is_qrexec_running():
#               #TODO: kill qrexec daemon
#               pass
