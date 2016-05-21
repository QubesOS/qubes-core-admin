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

from __future__ import absolute_import

import base64
import datetime
import itertools
import lxml
import os
import os.path
import re
import shutil
import subprocess
import sys
import time
import uuid
import warnings

import libvirt

import qubes
import qubes.config
import qubes.exc
import qubes.storage
import qubes.utils
import qubes.vm
import qubes.vm.mix.net
import qubes.tools.qvm_ls

qmemman_present = False
try:
    import qubes.qmemman.client
    qmemman_present = True
except ImportError:
    pass


def _setter_qid(self, prop, value):
    # pylint: disable=unused-argument
    value = int(value)
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

    # this regexp does not contain '+'; if it had it, we should specifically
    # disallow 'lost+found' #1440
    if re.match(r"^[a-zA-Z][a-zA-Z0-9_-]*$", value) is None:
        raise ValueError('{} value contains illegal characters'.format(
            prop.__name__))
    if self.is_running():
        raise qubes.exc.QubesVMNotHaltedError(
            self, 'Cannot change name of running VM')

    try:
        if self.installed_by_rpm:
            raise qubes.exc.QubesException('Cannot rename VM installed by RPM '
                '-- first clone VM and then use yum to remove package.')
    except AttributeError:
        pass

    if value in self.app.domains:
        raise qubes.exc.QubesException(
            'VM named {} alread exists'.format(value))

    return value


def _setter_kernel(self, prop, value):
    # pylint: disable=unused-argument
    if value is None:
        return value
    value = str(value)
    dirname = os.path.join(
        qubes.config.system_path['qubes_base_dir'],
        qubes.config.system_path['qubes_kernels_base_dir'],
        value)
    if not os.path.exists(dirname):
        raise qubes.exc.QubesPropertyValueError(self, prop, value,
            'Kernel {!r} not installed'.format(value))
    for filename in ('vmlinuz', 'initramfs'):
        if not os.path.exists(os.path.join(dirname, filename)):
            raise qubes.exc.QubesPropertyValueError(self, prop, value,
                'Kernel {!r} not properly installed: missing {!r} file'.format(
                    value, filename))
    return value


def _setter_label(self, prop, value):
    # pylint: disable=unused-argument
    if isinstance(value, qubes.Label):
        return value
    if isinstance(value, basestring) and value.startswith('label-'):
        return self.app.labels[int(value.split('-', 1)[1])]

    return self.app.get_label(value)

def _setter_positive_int(self, prop, value):
    value = int(value)
    if value <= 0:
        raise ValueError('Value must be positive')
    return value


class QubesVM(qubes.vm.mix.net.NetVMMixin, qubes.vm.BaseVM):
    '''Base functionality of Qubes VM shared between all VMs.'''

    #
    # per-class properties
    #

    #: directory in which domains of this class will reside
    dir_path_prefix = qubes.config.system_path['qubes_appvms_dir']

    #
    # properties loaded from XML
    #

    label = qubes.property('label',
        setter=_setter_label,
        saver=(lambda self, prop, value: 'label-{}'.format(value.index)),
        ls_width=14,
        doc='''Colourful label assigned to VM. This is where the colour of the
            padlock is set.''')

#   provides_network = qubes.property('provides_network',
#       type=bool, setter=qubes.property.bool,
#       doc='`True` if it is NetVM or ProxyVM, false otherwise.')

    qid = qubes.property('qid', type=int, write_once=True,
        setter=_setter_qid,
        clone=False,
        ls_width=3,
        doc='''Internal, persistent identificator of particular domain. Note
            this is different from Xen domid.''')

    name = qubes.property('name', type=str,
        clone=False,
        ls_width=31,
        doc='User-specified name of the domain.')

    uuid = qubes.property('uuid', type=uuid.UUID, write_once=True,
        clone=False,
        ls_width=36,
        doc='UUID from libvirt.')

    hvm = qubes.property('hvm',
        type=bool, setter=qubes.property.bool,
        default=False,
        doc='''Use full virtualisation (HVM) for this qube,
            instead of paravirtualisation (PV)''')

    # XXX this should be part of qubes.xml
    firewall_conf = qubes.property('firewall_conf', type=str,
        default='firewall.xml')

    installed_by_rpm = qubes.property('installed_by_rpm',
        type=bool, setter=qubes.property.bool,
        default=False,
        doc='''If this domain's image was installed from package tracked by
            package manager.''')

    memory = qubes.property('memory', type=int,
        setter=_setter_positive_int,
        default=(lambda self:
            qubes.config.defaults['hvm_memory' if self.hvm else 'memory']),
        doc='Memory currently available for this VM.')

    maxmem = qubes.property('maxmem', type=int,
        setter=_setter_positive_int,
        default=(lambda self: self.app.host.memory_total / 1024 / 2),
        doc='''Maximum amount of memory available for this VM (for the purpose
            of the memory balancer).''')

    internal = qubes.property('internal', default=False,
        type=bool, setter=qubes.property.bool,
        doc='''Internal VM (not shown in qubes-manager, don't create appmenus
            entries.''')

    # FIXME self.app.host could not exist - only self.app.vm required by API
    vcpus = qubes.property('vcpus',
        type=int,
        setter=_setter_positive_int,
        default=(lambda self: self.app.host.no_cpus),
        ls_width=2,
        doc='FIXME')

    pool_name = qubes.property('pool_name',
        default='default',
        doc='storage pool for this qube devices')

    dir_path = property( (lambda self: os.path.join(qubes.config.system_path['qubes_base_dir'], self.dir_path_prefix, self.name)),
        doc='Root directory for files related to this domain')

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
            else self.template.kernelopts if hasattr(self, 'template') \
            else qubes.config.defaults['kernelopts']),
        ls_width=30,
        doc='Kernel command line passed to domain.')

    debug = qubes.property('debug', type=bool, default=False,
        setter=qubes.property.bool,
        doc='Turns on debugging features.')

    # XXX what this exactly does?
    # XXX shouldn't this go to standalone VM and TemplateVM, and leave here
    #     only plain property?
    default_user = qubes.property('default_user', type=str,
        default=(lambda self: self.template.default_user
            if hasattr(self, 'template') else 'user'),
        ls_width=12,
        doc='FIXME')

#   @property
#   def default_user(self):
#       if self.template is not None:
#           return self.template.default_user
#       else:
#           return self._default_user

    qrexec_timeout = qubes.property('qrexec_timeout', type=int, default=60,
        setter=_setter_positive_int,
        ls_width=3,
        doc='''Time in seconds after which qrexec connection attempt is deemed
            failed. Operating system inside VM should be able to boot in this
            time.''')

    autostart = qubes.property('autostart', default=False,
        type=bool, setter=qubes.property.bool,
        doc='''Setting this to `True` means that VM should be autostarted on
            dom0 boot.''')

    include_in_backups = qubes.property('include_in_backups',
        default=(lambda self: not self.internal),
        type=bool, setter=qubes.property.bool,
        doc='If this domain is to be included in default backup.')

    # format got changed from %s to str(datetime.datetime)
    backup_timestamp = qubes.property('backup_timestamp', default=None,
        setter=(lambda self, prop, value:
            value if isinstance(value, datetime.datetime) else
            datetime.datetime.fromtimestamp(int(value))),
        saver=(lambda self, prop, value: value.strftime('%s')),
        doc='FIXME')


    #
    # static, class-wide properties
    #

    #
    # properties not loaded from XML, calculated at run-time
    #

    def __str__(self):
        return self.name

    # VMM-related

    @qubes.tools.qvm_ls.column(width=3)
    @property
    def xid(self):
        '''Xen ID.

        Or not Xen, but ID.
        '''

        if self.libvirt_domain is None:
            return -1
        try:
            return self.libvirt_domain.ID()
        except libvirt.libvirtError as e:
            if e.get_error_code() == libvirt.VIR_ERR_NO_DOMAIN:
                return -1
            else:
                self.log.exception('libvirt error code: {!r}'.format(
                    e.get_error_code()))
                raise


    @property
    def libvirt_domain(self):
        '''Libvirt domain object from libvirt.

        May be :py:obj:`None`, if libvirt knows nothing about this domain.
        '''

        if self._libvirt_domain is not None:
            return self._libvirt_domain

        # XXX _update_libvirt_domain?
        try:
            self._libvirt_domain = self.app.vmm.libvirt_conn.lookupByUUID(
                self.uuid.bytes)
        except libvirt.libvirtError:
            if self.app.vmm.libvirt_conn.virConnGetLastError()[0] == \
                    libvirt.VIR_ERR_NO_DOMAIN:
                self._update_libvirt_domain()
            else:
                raise
        return self._libvirt_domain

    @property
    def block_devices(self):
        ''' Return all :py:class:`qubes.devices.BlockDevice`s for current domain
            for serialization in the libvirt XML template as <disk>.
        '''
        return [v.block_device() for v in self.volumes.values()]

    @property
    def qdb(self):
        '''QubesDB handle for this domain.'''
        if self._qdb_connection is None:
            if self.is_running():
                import qubesdb
                self._qdb_connection = qubesdb.QubesDB(self.name)
        return self._qdb_connection


    # XXX this should go to to AppVM?
    @property
    def private_img(self):
        '''Location of private image of the VM (that contains :file:`/rw` \
        and :file:`/home`).'''
        warnings.warn("volatile_img is deprecated, use volumes['private'].vid",
                      DeprecationWarning)
        return self.volumes['private'].vid


    # XXX this should go to to AppVM? or TemplateVM?
    @property
    def root_img(self):
        '''Location of root image.'''
        warnings.warn("root_img is deprecated, use volumes['root'].vid",
                      DeprecationWarning)
        return self.volumes['root'].vid


    # XXX and this should go to exactly where? DispVM has it.
    @property
    def volatile_img(self):
        '''Volatile image that overlays :py:attr:`root_img`.'''
        warnings.warn("volatile_img is deprecated, use volumes['volatile'].vid",
                      DeprecationWarning)
        return self.volumes['volatile'].vid


    # XXX shouldn't this go elsewhere?
    @property
    def updateable(self):
        '''True if this machine may be updated on its own.'''
        return not hasattr(self, 'template')


    @property
    def icon_path(self):
        return os.path.join(self.dir_path, 'icon.png')


    @property
    def conf_file(self):
        return os.path.join(self.dir_path, 'libvirt.xml')


    # XXX I don't know what to do with these; probably should be isinstance(...)
    def is_template(self):
        warnings.warn('vm.is_template() is deprecated, use isinstance()',
            DeprecationWarning)
        import qubes.vm.templatevm
        return isinstance(self, qubes.vm.templatevm.TemplateVM)

    def is_appvm(self):
        warnings.warn('vm.is_appvm() is deprecated, use isinstance()',
            DeprecationWarning)
        import qubes.vm.appvm
        return isinstance(self, qubes.vm.appvm.AppVM)

    def is_proxyvm(self):
        warnings.warn('vm.is_proxyvm() is deprecated',
            DeprecationWarning)
        return self.netvm is not None and self.provides_network

    def is_disposablevm(self):
        warnings.warn('vm.is_disposable() is deprecated, use isinstance()',
            DeprecationWarning)
        import qubes.vm.dispvm
        return isinstance(self, qubes.vm.dispvm.DispVM)

    def is_netvm(self):
        warnings.warn('vm.is_netvm() is deprecated, use isinstance()',
            DeprecationWarning)
        return isinstance(self, qubes.vm.mix.net.NetVMMixin) \
               and self.provides_network


    # network-related


    #
    # constructor
    #

    def __init__(self, app, xml, volume_config={}, **kwargs):
        super(QubesVM, self).__init__(app, xml, **kwargs)
        self.volumes = {}
        if hasattr(self, 'volume_config'):
            if xml is not None:
                for node in xml.xpath('volume-config/volume'):
                    name = node.get('name')
                    assert name
                    for k, v in node.items():
                        self.volume_config[name][k] = v

            for name, conf in volume_config.items():
                for k, v in conf.items():
                    self.volume_config[name][k] = v
        elif volume_config:
            raise TypeError(
                'volume_config specified, but {} did not expect that.' %
                self.__class__.__name__)

        import qubes.vm.adminvm  # pylint: disable=redefined-outer-name

        # Init private attrs

        self._libvirt_domain = None
        self._qdb_connection = None

        if xml is None:
            # we are creating new VM and attributes came through kwargs
            assert hasattr(self, 'qid')
            assert hasattr(self, 'name')

        # Linux specific cap: max memory can't scale beyond 10.79*init_mem
        # see https://groups.google.com/forum/#!topic/qubes-devel/VRqkFj1IOtA
        if self.maxmem > self.memory * 10:
            self.maxmem = self.memory * 10

        # By default allow use all VCPUs
#       if not hasattr(self, 'vcpus') and not self.app.vmm.offline_mode:
#           self.vcpus = self.app.host.no_cpus

        if len(self.devices['pci']) > 0:
            # Force meminfo-writer disabled when VM have PCI devices
            self.features['meminfo-writer'] = None
        elif not isinstance(self, qubes.vm.adminvm.AdminVM) \
                and 'meminfo-writer' not in self.features:
            # Always set if meminfo-writer should be active or not
            self.features['meminfo-writer'] = '1'

        if xml is None:
            # new qube, disable updates check if requested for new qubes
            # TODO: when features (#1637) are done, migrate to plugin
            if not self.app.check_updates_vm:
                self.features['check-updates'] = None

        # will be initialized after loading all the properties

        # fire hooks
        if xml is None:
            self.events_enabled = True
        self.fire_event('domain-init')

    def __xml__(self):
        element = super(QubesVM, self).__xml__()
        if hasattr(self, 'volumes'):
            volume_config_node = lxml.etree.Element('volume-config')
            for volume in self.volumes.values():
                volume_config_node.append(volume.__xml__())

            element.append(volume_config_node)

                
        return element

    #
    # event handlers
    #

    @qubes.events.handler('domain-init', 'domain-load')
    def on_domain_init_loaded(self, event):
        # pylint: disable=unused-argument
        if not hasattr(self, 'uuid'):
            self.uuid = uuid.uuid4()

        # Initialize VM image storage class
        self.storage = qubes.storage.Storage(self)


    @qubes.events.handler('property-set:label')
    def on_property_set_label(self, event, name, new_label, old_label=None):
        # pylint: disable=unused-argument
        if self.icon_path:
            try:
                os.remove(self.icon_path)
            except OSError:
                pass
            if hasattr(os, "symlink"):
                os.symlink(new_label.icon_path, self.icon_path)
                # FIXME: some os-independent wrapper?
                subprocess.call(['sudo', 'xdg-icon-resource', 'forceupdate'])
            else:
                shutil.copy(new_label.icon_path, self.icon_path)

    @qubes.events.handler('property-pre-set:name')
    def on_property_pre_set_name(self, event, name, newvalue, oldvalue=None):
        # pylint: disable=unused-argument
        if newvalue in [d.name for d in self.app.domains.values()]:
            raise qubes.exc.QubesValueError(
                "A domain with name %s already exists", newvalue)

        # TODO not self.is_stopped() would be more appropriate
        if self.is_running():
            raise qubes.exc.QubesVMNotHaltedError(
                'Cannot change name of running domain {!r}'.format(oldvalue))

        if self.autostart:
            subprocess.check_call(['sudo', 'systemctl', '-q', 'disable',
                                   'qubes-vm@{}.service'.format(oldvalue)])

        try:
            self.app.domains[newvalue]
        except KeyError:
            pass
        else:
            raise qubes.exc.QubesValueError(
                'VM named {!r} already exists'.format(newvalue))

    @qubes.events.handler('property-set:name')
    def on_property_set_name(self, event, name, new_name, old_name=None):
        # pylint: disable=unused-argument
        self.init_log()

        if self._libvirt_domain is not None:
            self.libvirt_domain.undefine()
            self._libvirt_domain = None
        if self._qdb_connection is not None:
            self._qdb_connection.close()
            self._qdb_connection = None

        self.storage.rename(old_name, new_name)

        self._update_libvirt_domain()

        if self.autostart:
            self.autostart = self.autostart

    @qubes.events.handler('property-pre-set:autostart')
    def on_property_pre_set_autostart(self, event, prop, value,
            oldvalue=None):
        # pylint: disable=unused-argument
        # workaround https://bugzilla.redhat.com/show_bug.cgi?id=1181922
        if value:
            retcode = subprocess.call(
                ["sudo", "ln", "-sf",
                 "/usr/lib/systemd/system/qubes-vm@.service",
                 "/etc/systemd/system/multi-user.target.wants/qubes-vm@{"
                 "}".format(self.name)])
        else:
            retcode = subprocess.call(
                ['sudo', 'systemctl', 'disable',
                    'qubes-vm@{}.service'.format(self.name)])
        if retcode:
            raise qubes.exc.QubesException(
                'Failed to set autostart for VM in systemd')


    @qubes.events.handler('device-pre-attach:pci')
    def on_device_pre_attached_pci(self, event, pci):
        # pylint: disable=unused-argument
        if not os.path.exists('/sys/bus/pci/devices/0000:{}'.format(pci)):
            raise qubes.exc.QubesException('Invalid PCI device: {}'.format(pci))

        if not self.is_running():
            return

        try:
            # TODO: libvirt-ise
            subprocess.check_call(
                ['sudo', qubes.config.system_path['qubes_pciback_cmd'], pci])
            subprocess.check_call(
                ['sudo', 'xl', 'pci-attach', str(self.xid), pci])
        except subprocess.CalledProcessError as e:
            self.log.exception('Failed to attach PCI device {!r} on the fly,'
                ' changes will be seen after VM restart.'.format(pci), e)


    @qubes.events.handler('device-pre-detach:pci')
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
        except subprocess.CalledProcessError as e:
            self.log.exception('Failed to detach PCI device {!r} on the fly,'
                ' changes will be seen after VM restart.'.format(pci), e)


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
            raise qubes.exc.QubesVMNotHaltedError(self)

        self.log.info('Starting {}'.format(self.name))

        self.fire_event_pre('domain-pre-start', preparing_dvm=preparing_dvm,
            start_guid=start_guid, mem_required=mem_required)

        self.verify_files()

        if self.netvm is not None:
            if self.netvm.qid != 0:
                if not self.netvm.is_running():
                    self.netvm.start(start_guid=start_guid,
                        notify_function=notify_function)

        self.storage.start()
        self._update_libvirt_domain()

        qmemman_client = self.request_memory(mem_required)

        # Bind pci devices to pciback driver
        for pci in self.devices['pci']:
            try:
                node = self.app.vmm.libvirt_conn.nodeDeviceLookupByName(
                    'pci_0000_' + pci.replace(':', '_').replace('.', '_'))
            except libvirt.libvirtError as e:
                if e.get_error_code() == libvirt.VIR_ERR_NO_NODE_DEVICE:
                    raise qubes.exc.QubesException(
                        'PCI device {!r} does not exist (domain {!r})'.format(
                            pci, self.name))

            try:
                node.dettach()
            except libvirt.libvirtError as e:
                if e.get_error_code() == libvirt.VIR_ERR_INTERNAL_ERROR:
                    # allreaddy dettached
                    pass
                else:
                    raise

        self.libvirt_domain.createWithFlags(libvirt.VIR_DOMAIN_START_PAUSED)

        try:
            self.fire_event('domain-spawn',
                preparing_dvm=preparing_dvm, start_guid=start_guid)

            self.log.info('Setting Qubes DB info for the VM')
            self.start_qubesdb()
            self.create_qdb_entries()

            if preparing_dvm:
                self.qdb.write('/dvm', '1')

            self.log.warning('Activating the {} VM'.format(self.name))
            self.libvirt_domain.resume()

            # close() is not really needed, because the descriptor is
            # close-on-exec anyway, the reason to postpone close() is that
            # possibly xl is not done constructing the domain after its main
            # process exits so we close() when we know the domain is up the
            # successful unpause is some indicator of it
            if qmemman_client:
                qmemman_client.close()

#           if self._start_guid_first and start_guid and not preparing_dvm \
#                   and os.path.exists('/var/run/shm.id'):
#               self.start_guid()

            if not preparing_dvm:
                self.start_qrexec_daemon()

            self.fire_event('domain-start',
                preparing_dvm=preparing_dvm, start_guid=start_guid)

        except:  # pylint: disable=bare-except
            if self.is_running() or self.is_paused():
                # This avoids losing the exception if an exception is raised in
                # self.force_shutdown(), because the vm is not running or paused
                self.force_shutdown()
            raise


    def shutdown(self, force=False):
        '''Shutdown domain.

        :raises qubes.exc.QubesVMNotStartedError: \
            when domain is already shut down.
        '''

        if not self.is_running(): # TODO not self.is_halted()
            raise qubes.exc.QubesVMNotStartedError(self)

        self.fire_event_pre('domain-pre-shutdown', force=force)

        # try to gracefully detach PCI devices before shutdown, to mitigate
        # timeouts on forcible detach at domain destroy; if that fails, too bad
        for pci in self.devices['pci']:
            try:
                self.libvirt_domain.detachDevice(self.lvxml_pci_dev(pci))
            except libvirt.libvirtError as e:
                self.log.warning(
                    'error while gracefully detaching PCI device ({!r}) during'
                    ' shutdown of {!r}; error code: {!r}; continuing'
                    ' anyway'.format(pci, self.name, e.get_error_code()),
                    exc_info=1)

        self.libvirt_domain.shutdown()
        self.storage.stop()


    def kill(self):
        '''Forcefuly shutdown (destroy) domain.

        :raises qubes.exc.QubesVMNotStartedError: \
            when domain is already shut down.
        '''

        if not self.is_running() and not self.is_paused():
            raise qubes.exc.QubesVMNotStartedError(self)

        self.libvirt_domain.destroy()
        self.storage.stop()


    def force_shutdown(self, *args, **kwargs):
        '''Deprecated alias for :py:meth:`kill`'''
        warnings.warn(
            'Call to deprecated function force_shutdown(), use kill() instead',
            DeprecationWarning, stacklevel=2)
        self.kill(*args, **kwargs)


    def suspend(self):
        '''Suspend (pause) domain.

        :raises qubes.exc.QubesVMNotRunnignError: \
            when domain is already shut down.
        :raises qubes.exc.QubesNotImplemetedError: \
            when domain has PCI devices attached.
        '''

        if not self.is_running() and not self.is_paused():
            raise qubes.exc.QubesVMNotRunningError(self)

        if len(self.devices['pci']) > 0:
            raise qubes.exc.QubesNotImplementedError(
                'Cannot suspend domain {!r} which has PCI devices attached' \
                    .format(self.name))
        else:
            if self.hvm:
                self.libvirt_domain.pause()
            else:
                self.libvirt_domain.suspend()


    def pause(self):
        '''Pause (suspend) domain. This currently delegates to \
        :py:meth:`suspend`.'''

        if not self.is_running():
            raise qubes.exc.QubesVMNotRunningError(self)

        self.suspend()


    def resume(self):
        '''Resume suspended domain.

        :raises qubes.exc.QubesVMNotSuspendedError: when machine is not paused
        :raises qubes.exc.QubesVMError: when machine is suspended
        '''

        if self.get_power_state() == "Suspended":
            raise qubes.exc.QubesVMError(self,
                'Cannot resume suspended domain {!r}'.format(self.name))
        else:
            self.unpause()


    def unpause(self):
        '''Resume (unpause) a domain'''
        if not self.is_paused():
            raise qubes.exc.QubesVMNotPausedError(self)

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
                raise qubes.exc.QubesVMNotRunningError(self)

            if notify_function is not None:
                notify_function('info',
                    'Starting the {!r} VM...'.format(self.name))
            self.start(start_guid=gui, notify_function=notify_function)

        if self.is_paused():
            # XXX what about autostart?
            raise qubes.exc.QubesVMNotRunningError(
                self, 'Domain {!r} is paused'.format(self.name))

        if not self.is_qrexec_running():
            raise qubes.exc.QubesVMError(
                self, 'Domain {!r}: qrexec not connected'.format(self.name))

        self.fire_event_pre('domain-cmd-pre-run', start_guid=gui)

        args = [qubes.config.system_path['qrexec_client_path'],
            '-d', str(self.name),
            '{}:{}'.format(user, command)]
        if localcmd is not None:
            args += ['-l', localcmd]
        if filter_esc:
            args += ['-t']
        if os.isatty(sys.stderr.fileno()):
            args += ['-T']

        call_kwargs = {}
        if ignore_stderr or not passio:
            null = open("/dev/null", "r+")
            call_kwargs['stderr'] = null
        if not passio:
            call_kwargs['stdin'] = null
            call_kwargs['stdout'] = null

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
        if not wait and not passio:
            args += ["-e"]
        retcode = subprocess.call(args, **call_kwargs)
        if null:
            null.close()
        return retcode


    def run_service(self, service, source=None, user=None,
                    passio_popen=False, input=None, localcmd=None, gui=False,
                    wait=True, passio_stderr=False):
        '''Run service on this VM

        **passio_popen** and **input** are mutually exclusive.

        :param str service: service name
        :param qubes.vm.qubesvm.QubesVM: source domain as presented to this VM
        :param str user: username to run service as
        :param bool passio_popen: passed verbatim to :py:meth:`run`
        :param str input: string passed as input to service
        ''' # pylint: disable=redefined-builtin

        if len([i for i in (input, passio_popen, localcmd) if i]) > 1:
            raise TypeError(
                'input, passio_popen and localcmd cannot be used together')

        if not wait and (localcmd or input):
            raise ValueError("Cannot use wait=False with input or "
                             "localcmd specified")

        if passio_stderr and not passio_popen:
            raise TypeError('passio_stderr can be used only with passio_popen')

        if input:
            # Internally use passio_popen, but do not return POpen object to
            # the user - use internally for p.communicate()
            passio_popen = True

        source = 'dom0' if source is None else self.app.domains[source].name

        p = self.run('QUBESRPC {} {}'.format(service, source),
            localcmd=localcmd, passio_popen=passio_popen, user=user, wait=wait,
            gui=gui, passio_stderr=passio_stderr)
        if input:
            p.communicate(input)
            return p.returncode
        else:
            return p

    def request_memory(self, mem_required=None):
        # overhead of per-qube/per-vcpu Xen structures,
        # taken from OpenStack nova/virt/xenapi/driver.py
        # see https://wiki.openstack.org/wiki/XenServer/Overhead
        # add an extra MB because Nova rounds up to MBs

        if not qmemman_present:
            return

        MEM_OVERHEAD_BASE = (3 + 1) * 1024 * 1024
        MEM_OVERHEAD_PER_VCPU = 3 * 1024 * 1024 / 2

        if mem_required is None:
            mem_required = int(self.memory) * 1024 * 1024

        qmemman_client = qubes.qmemman.client.QMemmanClient()
        try:
            mem_required_with_overhead = mem_required + MEM_OVERHEAD_BASE \
                + self.vcpus * MEM_OVERHEAD_PER_VCPU
            got_memory = qmemman_client.request_memory(
                mem_required_with_overhead)

        except IOError as e:
            raise IOError('Failed to connect to qmemman: {!s}'.format(e))

        if not got_memory:
            qmemman_client.close()
            raise qubes.exc.QubesMemoryError(self)

        return qmemman_client


    def start_qrexec_daemon(self):
        '''Start qrexec daemon.

        :raises OSError: when starting fails.
        '''

        self.log.debug('Starting the qrexec daemon')
        qrexec_args = [str(self.xid), self.name, self.default_user]
        if not self.debug:
            qrexec_args.insert(0, "-q")

        qrexec_env = os.environ.copy()
        if not self.features.check_with_template('qrexec', not self.hvm):
            self.log.debug(
                'Starting the qrexec daemon in background, because of features')
            qrexec_env['QREXEC_STARTUP_NOWAIT'] = '1'
        else:
            qrexec_env['QREXEC_STARTUP_TIMEOUT'] = str(self.qrexec_timeout)

        try:
            subprocess.check_call(
                [qubes.config.system_path["qrexec_daemon_path"]] + qrexec_args,
                env=qrexec_env)
        except subprocess.CalledProcessError:
            raise qubes.exc.QubesVMError(self, 'Cannot execute qrexec-daemon!')


    def start_qubesdb(self):
        '''Start QubesDB daemon.

        :raises OSError: when starting fails.
        '''

        self.log.info('Starting Qubes DB')

        # FIXME #1694 #1241
        retcode = subprocess.call([
            qubes.config.system_path["qubesdb_daemon_path"],
            str(self.xid),
            self.name])
        if retcode != 0:
            raise qubes.exc.QubesException('Cannot execute qubesdb-daemon')


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


    # TODO rename to create
    def create_on_disk(self, source_template=None):
        '''Create files needed for VM.

        :param qubes.vm.templatevm.TemplateVM source_template: Template to use
            (if :py:obj:`None`, use domain's own template
        '''

        if source_template is None and hasattr(self, 'template'):
            # pylint: disable=no-member
            source_template = self.template

        self.storage.create_on_disk(source_template)

        self.log.info('Creating icon symlink: {} -> {}'.format(
            self.icon_path, self.label.icon_path))
        if hasattr(os, "symlink"):
            os.symlink(self.label.icon_path, self.icon_path)
        else:
            shutil.copy(self.label.icon_path, self.icon_path)

        # fire hooks
        self.fire_event('domain-create-on-disk', source_template)


    # TODO move to storage
    def resize_private_img(self, size):
        '''Resize private image.'''

        warnings.warn(
            "resize_private_img is deprecated, use volumes[name].resize()",
            DeprecationWarning)

        self.volumes['private'].resize(size)

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
            raise qubes.exc.QubesException('resize2fs failed')

    def resize_root_img(self, size, allow_start=False):
        warnings.warn(
            "resize_root_img is deprecated, use volumes[name].resize()",
            DeprecationWarning)

        self.volumes['root'].resize(size)

        if not allow_start:
            raise qubes.exc.QubesException(
                'The qube has to be started to complete the operation, but is'
                ' required not to start. Either run the operation again'
                ' allowing  starting of the qube this time, or run resize2fs'
                ' in the qube manually.')

        self.start(start_guid=False)

        # TODO run_service #1695
        self.run('resize2fs /dev/mapper/dmroot', user='root',
             wait=True, gui=False)

        self.shutdown()
        while self.is_running(): #1696
            time.sleep(1)

    def remove_from_disk(self):
        '''Remove domain remnants from disk.'''
        self.fire_event('domain-remove-from-disk')
        self.storage.remove()
        shutil.rmtree(self.dir_path)

    def clone_disk_files(self, src):
        '''Clone files from other vm.

        :param qubes.vm.qubesvm.QubesVM src: source VM
        '''

        if src.is_running():  # XXX what about paused?
            raise qubes.exc.QubesVMNotHaltedError(
                self, 'Cannot clone a running domain {!r}'.format(self.name))

        if hasattr(src, 'volume_config'):
            self.volume_config = src.volume_config
        self.storage = qubes.storage.Storage(self)
        self.storage.clone(src)

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
        self.fire_event('domain-clone-files', src)


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
            return 'Halted'

        try:
            if libvirt_domain.isActive():
                # pylint: disable=line-too-long
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
                return 'Halted'
            else:
                raise

        assert False


    def is_running(self):
        '''Check whether this domain is running.

        :returns: :py:obj:`True` if this domain is started, \
            :py:obj:`False` otherwise.
        :rtype: bool
        '''

        if self.app.vmm.offline_mode:
            return False

        # TODO context manager #1693
        return self.libvirt_domain and self.libvirt_domain.isActive()


    def is_paused(self):
        '''Check whether this domain is paused.

        :returns: :py:obj:`True` if this domain is paused, \
            :py:obj:`False` otherwise.
        :rtype: bool
        '''

        return self.libvirt_domain \
            and self.libvirt_domain.state() == libvirt.VIR_DOMAIN_PAUSED


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
        return all(self.fire_event('domain-is-fully-usable'))


    @qubes.events.handler('domain-is-fully-usable')
    def on_domain_is_fully_usable(self, event):
        '''Check whether domain is running and sane.

        Currently this checks for running qrexec.
        '''

        # Running gui-daemon implies also VM running
        if not self.is_qrexec_running():
            yield False


    # memory and disk

    def get_mem(self):
        '''Get current memory usage from VM.

        :returns: Memory usage [FIXME unit].
        :rtype: FIXME
        '''

        if self.libvirt_domain is None:
            return 0

        try:
            if not self.libvirt_domain.isActive():
                return 0
            return self.libvirt_domain.info()[1]

        except libvirt.libvirtError as e:
            if e.get_error_code() in (
                    # qube no longer exists
                    libvirt.VIR_ERR_NO_DOMAIN,

                    # libxl_domain_info failed (race condition from isActive)
                    libvirt.VIR_ERR_INTERNAL_ERROR,
                    ):
                return 0

            else:
                self.log.exception(
                    'libvirt error code: {!r}'.format(e.get_error_code()))
                raise


    def get_mem_static_max(self):
        '''Get maximum memory available to VM.

        :returns: Memory limit [FIXME unit].
        :rtype: FIXME
        '''

        if self.libvirt_domain is None:
            return 0

        try:
            return self.libvirt_domain.maxMemory()

        except libvirt.libvirtError as e:
            if e.get_error_code() in (
                    # qube no longer exists
                    libvirt.VIR_ERR_NO_DOMAIN,

                    # libxl_domain_info failed (race condition from isActive)
                    libvirt.VIR_ERR_INTERNAL_ERROR,
                    ):
                return 0

            else:
                self.log.exception(
                    'libvirt error code: {!r}'.format(e.get_error_code()))
                raise


    def get_cputime(self):
        '''Get total CPU time burned by this domain since start.

        :returns: CPU time usage [FIXME unit].
        :rtype: FIXME
        '''

        if self.libvirt_domain is None:
            return 0

        if self.libvirt_domain is None:
            return 0
        if not self.libvirt_domain.isActive():
            return 0

        try:
            if not self.libvirt_domain.isActive():
                return 0

        # this does not work, because libvirt
#           return self.libvirt_domain.getCPUStats(
#               libvirt.VIR_NODE_CPU_STATS_ALL_CPUS, 0)[0]['cpu_time']/10**9

            return self.libvirt_domain.info()[4]

        except libvirt.libvirtError as e:
            if e.get_error_code() in (
                    # qube no longer exists
                    libvirt.VIR_ERR_NO_DOMAIN,

                    # libxl_domain_info failed (race condition from isActive)
                    libvirt.VIR_ERR_INTERNAL_ERROR,
                    ):
                return 0

            else:
                self.log.exception(
                    'libvirt error code: {!r}'.format(e.get_error_code()))
                raise



    # XXX shouldn't this go only to vms that have root image?
    def get_disk_utilization_root_img(self):
        '''Get space that is actually ocuppied by :py:attr:`volumes['root']`.

           This is a temporary wrapper for backwards compatibility. You should
           call directly :py:attr:`volumes[name].utilization`
        :returns: domain's real disk image size [FIXME unit]
        :rtype: FIXME

        .. seealso:: :py:meth:`get_root_img_sz`
        '''

        warnings.warn(
            "get_disk_utilization_root_img is deprecated, use volumes['root'].utilization",
            DeprecationWarning)
        return qubes.storage.get_disk_usage(self.volumes['root'].utilization)


    # XXX shouldn't this go only to vms that have root image?
    def get_root_img_sz(self):
        '''Get the size of the :py:attr:`volumes['root']`.

        This is a temporary wrapper for backwards compatibility. You should
        call directly :py:attr:`volumes[name].size`
        :returns: domain's virtual disk size [FIXME unit]
        :rtype: FIXME

        .. seealso:: :py:meth:`get_disk_utilization_root_img`
        '''

        warnings.warn(
            "get_disk_root_img_sz is deprecated, use volumes['root'].size",
            DeprecationWarning)
        return qubes.storage.get_disk_usage(self.volumes['root'].size)

    def get_disk_utilization_private_img(self):
        '''Get space that is actually ocuppied by :py:attr:`volumes['private']`.

           This is a temporary wrapper for backwards compatibility. You should
           call directly :py:attr:`volumes[name].utilization`
        :returns: domain's real disk image size [FIXME unit]
        :rtype: FIXME
        '''

        warnings.warn(
            "get_disk_utilization_private_img is deprecated, use volumes['private'].utilization",
            DeprecationWarning)
        return qubes.storage.get_disk_usage(self.volumes[
            'private'].utilization)

    def get_private_img_sz(self):
        '''Get the size of the :py:attr:`volumes['private']`.

        This is a temporary wrapper for backwards compatibility. You should
        call directly :py:attr:`volumes[name].size`
        :returns: domain's virtual disk size [FIXME unit]
        :rtype: FIXME

        .. seealso:: :py:meth:`get_disk_utilization_private_img`
        '''

        warnings.warn(
            "get_disk_private_img_sz is deprecated, use volumes['private'].size",
            DeprecationWarning)
        return qubes.storage.get_disk_usage(self.volumes['private'].size)

    def get_disk_utilization(self):
        '''Return total space actually occuppied by all files belonging to \
            this domain.

        :returns: domain's total disk usage [FIXME unit]
        :rtype: FIXME
        '''

        return qubes.storage.get_disk_usage(self.dir_path)

    # TODO move to storage
    def verify_files(self):
        '''Verify that files accessed by this machine are sane.

        On success, returns normally. On failure, raises exception.
        '''

        self.storage.verify_files()

        self.fire_event('domain-verify-files')

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
        # pylint: disable=no-member

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
        used_dmdev = self.app.vmm.xs.read('',
            '/local/domain/0/backend/vbd/{}/51712/node'.format(self.xid))

        return used_dmdev != current_dmdev


    #
    # helper methods
    #

    def relative_path(self, path):
        '''Return path relative to py:attr:`dir_path`.

        :param str path: Path in question.
        :returns: Relative path.
        '''

        return os.path.relpath(path, self.dir_path)


    def create_qdb_entries(self):
        '''Create entries in Qubes DB.
        '''
        # pylint: disable=no-member

        self.qdb.write('/name', self.name)
        self.qdb.write('/type', self.__class__.__name__)
        self.qdb.write('/updateable', str(self.updateable))
        self.qdb.write('/persistence', 'full' if self.updateable else 'rw-only')
        self.qdb.write('/debug', str(int(self.debug)))
        try:
            self.qdb.write('/template', self.template.name)
        except AttributeError:
            self.qdb.write('/template', '')

        self.qdb.write('/random-seed',
            base64.b64encode(qubes.utils.urandom(64)))

        if self.provides_network:
            self.qdb.write('/network-provider/gateway', self.gateway)
            self.qdb.write('/network-provider/netmask', self.netmask)

            for i, addr in zip(itertools.count(start=1), self.dns):
                self.qdb.write('/network-provider/dns-{}'.format(i), addr)

        if self.netvm is not None:
            self.qdb.write('/network/ip', self.ip)
            self.qdb.write('/network/netmask', self.netvm.netmask)
            self.qdb.write('/network/gateway', self.netvm.gateway)

            for i, addr in zip(itertools.count(start=1), self.dns):
                self.qdb.write('/network/dns-{}'.format(i), addr)

        tzname = qubes.utils.get_timezone()
        if tzname:
            self.qdb.write('/timezone', tzname)

        for feature, value in self.features.items():
            self.qdb.write('/features/{0}'.format(feature),
                    str(value) if value else '')

        self.qdb.write('/devices/block', '')
        self.qdb.write('/devices/usb', '')

        # TODO: Currently the whole qmemman is quite Xen-specific, so stay with
        # xenstore for it until decided otherwise
        if qmemman_present:
            self.app.vmm.xs.set_permissions('',
                '/local/domain/{}/memory'.format(self.xid),
                [{'dom': self.xid}])

        self.fire_event('domain-qdb-create')


    def _update_libvirt_domain(self):
        '''Re-initialise :py:attr:`libvirt_domain`.'''
        domain_config = self.create_config_file()
        try:
            self._libvirt_domain = self.app.vmm.libvirt_conn.defineXML(
                domain_config)
        except libvirt.libvirtError as e:
            if e.get_error_code() == libvirt.VIR_ERR_OS_TYPE \
                    and e.get_str2() == 'hvm':
                raise qubes.exc.QubesVMError(self,
                    'HVM qubes are not supported on this machine. '
                    'Check BIOS settings for VT-x/AMD-V extensions.')
            else:
                raise


    #
    # workshop -- those are to be reworked later
    #

    def get_prefmem(self):
        # TODO: qmemman is still xen specific
        untrusted_meminfo_key = self.app.vmm.xs.read('',
            '/local/domain/{}/memory/meminfo'.format(self.xid))

        if untrusted_meminfo_key is None or untrusted_meminfo_key == '':
            return 0

        domain = qubes.qmemman.DomainState(self.xid)
        qubes.qmemman.algo.refresh_meminfo_for_domain(
            domain, untrusted_meminfo_key)
        domain.memory_maximum = self.get_mem_static_max() * 1024

        return qubes.qmemman.algo.prefmem(domain) / 1024



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
