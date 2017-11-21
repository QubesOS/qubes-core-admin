#
# The Qubes OS Project, https://www.qubes-os.org/
#
# Copyright (C) 2010-2015  Joanna Rutkowska <joanna@invisiblethingslab.com>
# Copyright (C) 2013-2015  Marek Marczykowski-Górecki
#                              <marmarek@invisiblethingslab.com>
# Copyright (C) 2014-2015  Wojtek Porczyk <woju@invisiblethingslab.com>
#
# This library is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 2.1 of the License, or (at your option) any later version.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with this library; if not, see <https://www.gnu.org/licenses/>.
#

from __future__ import absolute_import

import asyncio
import base64
import datetime
import errno
import grp
import os
import os.path
import shutil
import string
import subprocess
import sys
import uuid
import warnings

import libvirt  # pylint: disable=import-error
import lxml

import qubes
import qubes.config
import qubes.exc
import qubes.storage
import qubes.storage.file
import qubes.utils
import qubes.vm
import qubes.vm.mix.net

qmemman_present = False
try:
    import qubes.qmemman.client  # pylint: disable=wrong-import-position
    qmemman_present = True
except ImportError:
    pass

MEM_OVERHEAD_BASE = (3 + 1) * 1024 * 1024
MEM_OVERHEAD_PER_VCPU = 3 * 1024 * 1024 / 2


def _setter_kernel(self, prop, value):
    ''' Helper for setting the domain kernel and running sanity checks on it.
    '''  # pylint: disable=unused-argument
    if not value:
        return ''
    value = str(value)
    if '/' in value:
        raise qubes.exc.QubesPropertyValueError(self, prop, value,
            'Kernel name cannot contain \'/\'')
    return value


def _setter_positive_int(self, prop, value):
    ''' Helper for setting a positive int. Checks that the int is >= 0 '''
    # pylint: disable=unused-argument
    value = int(value)
    if value <= 0:
        raise ValueError('Value must be positive')
    return value


def _setter_default_user(self, prop, value):
    ''' Helper for setting default user '''
    value = str(value)
    # specifically forbid: ':', ' ', ''', '"'
    allowed_chars = string.ascii_letters + string.digits + '_-+,.'
    if not all(c in allowed_chars for c in value):
        raise qubes.exc.QubesPropertyValueError(self, prop, value,
            'Username can contain only those characters: ' + allowed_chars)
    return value

def _setter_virt_mode(self, prop, value):
    value = str(value)
    value = value.lower()
    if value not in ('hvm', 'pv', 'pvh'):
        raise qubes.exc.QubesPropertyValueError(self, prop, value,
            'Invalid virtualization mode, supported values: hvm, pv, pvh')
    return value


class QubesVM(qubes.vm.mix.net.NetVMMixin, qubes.vm.BaseVM):
    '''Base functionality of Qubes VM shared between all VMs.

    The following events are raised on this class or its subclasses:

        .. event:: domain-init (subject, event)

            Fired at the end of class' constructor.

            :param subject: Event emitter (the qube object)
            :param event: Event name (``'domain-init'``)

        .. event:: domain-load (subject, event)

            Fired after the qube was loaded from :file:`qubes.xml`

            :param subject: Event emitter (the qube object)
            :param event: Event name (``'domain-loaded'``)

        .. event:: domain-pre-start \
                (subject, event, start_guid, mem_required)

            Fired at the beginning of :py:meth:`start` method.

            Handler for this event can be asynchronous (a coroutine).

            :param subject: Event emitter (the qube object)
            :param event: Event name (``'domain-pre-start'``)

            *other arguments are as in :py:meth:`start`*

        .. event:: domain-spawn (subject, event, start_guid)

            Fired after creating libvirt domain.

            :param subject: Event emitter (the qube object)
            :param event: Event name (``'domain-spawn'``)

            Handler for this event can be asynchronous (a coroutine).

            *other arguments are as in :py:meth:`start`*

        .. event:: domain-start (subject, event, start_guid)

            Fired at the end of :py:meth:`start` method.

            Handler for this event can be asynchronous (a coroutine).

            :param subject: Event emitter (the qube object)
            :param event: Event name (``'domain-start'``)

            *other arguments are as in :py:meth:`start`*

        .. event:: domain-shutdown (subject, event)

            Fired when domain has been shut down.

            :param subject: Event emitter (the qube object)
            :param event: Event name (``'domain-shutdown'``)

        .. event:: domain-pre-shutdown (subject, event, force)

            Fired at the beginning of :py:meth:`shutdown` method.

            Handler for this event can be asynchronous (a coroutine).

            :param subject: Event emitter (the qube object)
            :param event: Event name (``'domain-pre-shutdown'``)
            :param force: If the shutdown is to be forceful

        .. event:: domain-cmd-pre-run (subject, event, start_guid)

            Fired at the beginning of :py:meth:`run_service` method.

            Handler for this event can be asynchronous (a coroutine).

            :param subject: Event emitter (the qube object)
            :param event: Event name (``'domain-cmd-pre-run'``)
            :param start_guid: If the gui daemon can be started

        .. event:: domain-create-on-disk (subject, event)

            Fired at the end of :py:meth:`create_on_disk` method.

            Handler for this event can be asynchronous (a coroutine).

            :param subject: Event emitter (the qube object)
            :param event: Event name (``'domain-create-on-disk'``)

        .. event:: domain-remove-from-disk (subject, event)

            Fired at the beginning of :py:meth:`remove_from_disk` method, before
            the qube directory is removed.

            Handler for this event can be asynchronous (a coroutine).

            :param subject: Event emitter (the qube object)
            :param event: Event name (``'domain-remove-from-disk'``)

        .. event:: domain-clone-files (subject, event, src)

            Fired at the end of :py:meth:`clone_disk_files` method.

            Handler for this event can be asynchronous (a coroutine).

            :param subject: Event emitter (the qube object)
            :param event: Event name (``'domain-clone-files'``)
            :param src: source qube

        .. event:: domain-verify-files (subject, event)

            Fired at the end of :py:meth:`clone_disk_files` method.

            :param subject: Event emitter (the qube object)
            :param event: Event name (``'domain-verify-files'``)

            If you think some files are missing or damaged, raise an exception.

        .. event:: domain-is-fully-usable (subject, event)

            Fired at the end of :py:meth:`clone_disk_files` method.

            :param subject: Event emitter (the qube object)
            :param event: Event name (``'domain-is-fully-usable'``)

            You may ``yield False`` from the handler if you think the qube is
            not fully usable. This will cause the domain to be in "transient"
            state in the domain lifecycle.

        .. event:: domain-qdb-create (subject, event)

            Fired at the end of :py:meth:`create_qdb_entries` method.

            :param subject: Event emitter (the qube object)
            :param event: Event name (``'domain-qdb-create'``)

            This event is a good place to add your custom entries to the qdb.

        .. event:: domain-qdb-change:watched-path (subject, event, path)

            Fired when watched QubesDB entry is changed. See
            :py:meth:`watch_qdb_path`. *watched-path* part of event name is
            what path was registered for watching, *path* in event argument
            is what actually have changed (which may be different if watching a
            directory, i.e. a path with `/` at the end).

            :param subject: Event emitter (the qube object)
            :param event: Event name (``'domain-qdb-change'``)
            :param path: changed QubesDB path

        .. event:: backup-get-files (subject, event)

            Collects additional file to be included in a backup.

            :param subject: Event emitter (the qube object)
            :param event: Event name (``'backup-get-files'``)

            Handlers should yield paths of the files.

        .. event:: domain-restore (subject, event)

            Domain was just restored from backup, although the storage was not
            yet verified and the app object was not yet saved.

            :param subject: Event emitter (the qube object)
            :param event: Event name (``'domain-restore'``)

        .. event:: domain-feature-set (subject, event, feature, value
            [, oldvalue])

            A feature was changed.
            *oldvalue* is present only when there was any.

            :param subject: Event emitter (the qube object)
            :param event: Event name (``'domain-feature-set'``)
            :param feature: feature name
            :param value: new value
            :param oldvalue: old value, if any

        .. event:: domain-feature-delete (subject, event, feature)

            A feature was removed.

            :param subject: Event emitter (the qube object)
            :param event: Event name (``'domain-feature-delete'``)
            :param feature: feature name

        .. event:: domain-tag-add (subject, event, tag)

            A tag was added.

            :param subject: Event emitter (the qube object)
            :param event: Event name (``'domain-tag-add'``)
            :param tag: tag name

        .. event:: domain-tag-delete (subject, event, tag)

            A feature was removed.

            :param subject: Event emitter (the qube object)
            :param event: Event name (``'domain-tag-delete'``)
            :param tag: tag name

        .. event:: feature-request (subject, event, *, untrusted_features)

            The domain is performing a feature request.

            :param subject: Event emitter (the qube object)
            :param event: Event name (``'feature-request'``)
            :param untrusted_features: :py:class:`dict` containing the feature \
            request

            The content of the `untrusted_features` variable is, as the name
            implies, **UNTRUSTED**. The remind this to programmer, the variable
            name has to be exactly as provided.

            It is up to the extensions to decide, what to do with request,
            ranging from plainly ignoring the request to verbatim copy into
            :py:attr:`features` with only minimal sanitisation.

        .. event:: monitor-layout-change (subject, event, monitor_layout)

            Desktop layout was changed, probably because a display was plugged
            in or out.

            :param subject: Event emitter (the qube object)
            :param event: Event name (``'monitor-layout-change'``)
            :param monitor_layout: The new layout

        .. event:: firewall-changed (subject, event)

            Firewall was changed.

            :param subject: Event emitter (the qube object)
            :param event: Event name (``'firewall-changed'``)

        .. event:: net-domain-connect (subject, event, vm)

            Fired after connecting a domiain to this vm.

            :param subject: Event emitter (the qube object)
            :param event: Event name (``'net-domain-connect'``)
            :param vm: The domain that was just connected.

            On the `vm` object there was probably ``property-set:netvm`` fired
            earlier.
    '''

    #
    # per-class properties
    #

    #: directory in which domains of this class will reside
    dir_path_prefix = qubes.config.system_path['qubes_appvms_dir']

    #
    # properties loaded from XML
    #

    virt_mode = qubes.property('virt_mode',
        type=str, setter=_setter_virt_mode,
        default='hvm',
        doc='''Virtualisation mode: full virtualisation ("hvm"),
            or paravirtualisation ("pv")''')

    installed_by_rpm = qubes.property('installed_by_rpm',
        type=bool, setter=qubes.property.bool,
        default=False,
        doc='''If this domain's image was installed from package tracked by
            package manager.''')

    memory = qubes.property('memory', type=int,
        setter=_setter_positive_int,
        default=(lambda self:
            qubes.config.defaults[
                'hvm_memory' if self.virt_mode == 'hvm' else 'memory']),
        doc='Memory currently available for this VM.')

    maxmem = qubes.property('maxmem', type=int,
        setter=_setter_positive_int,
        default=(lambda self:
            int(min(self.app.host.memory_total / 1024 / 2, 4000))),
        doc='''Maximum amount of memory available for this VM (for the purpose
            of the memory balancer).''')

    stubdom_mem = qubes.property('stubdom_mem', type=int,
        setter=_setter_positive_int,
        default=None,
        doc='Memory ammount allocated for the stubdom')

    vcpus = qubes.property('vcpus',
        type=int,
        setter=_setter_positive_int,
        default=2,
        doc='Number of virtual CPUs for a qube')

    # CORE2: swallowed uses_default_kernel
    kernel = qubes.property('kernel', type=str,
        setter=_setter_kernel,
        default=(lambda self: self.app.default_kernel),
        doc='Kernel used by this domain.')

    # CORE2: swallowed uses_default_kernelopts
    # pylint: disable=no-member
    kernelopts = qubes.property('kernelopts', type=str, load_stage=4,
        default=(lambda self: qubes.config.defaults['kernelopts_pcidevs']
            # pylint: disable=no-member
            if list(self.devices['pci'].persistent())
            else self.template.kernelopts if hasattr(self, 'template')
            else qubes.config.defaults['kernelopts']),
        doc='Kernel command line passed to domain.')

    debug = qubes.property('debug', type=bool, default=False,
        setter=qubes.property.bool,
        doc='Turns on debugging features.')

    # XXX what this exactly does?
    # XXX shouldn't this go to standalone VM and TemplateVM, and leave here
    #     only plain property?
    default_user = qubes.property('default_user', type=str,
        # pylint: disable=no-member
        default=(lambda self: self.template.default_user
            if hasattr(self, 'template') else 'user'),
        setter=_setter_default_user,
        doc='FIXME')

    # pylint: enable=no-member

#   @property
#   def default_user(self):
#       if self.template is not None:
#           return self.template.default_user
#       else:
#           return self._default_user

    qrexec_timeout = qubes.property('qrexec_timeout', type=int, default=60,
        setter=_setter_positive_int,
        doc='''Time in seconds after which qrexec connection attempt is deemed
            failed. Operating system inside VM should be able to boot in this
            time.''')

    autostart = qubes.property('autostart', default=False,
        type=bool, setter=qubes.property.bool,
        doc='''Setting this to `True` means that VM should be autostarted on
            dom0 boot.''')

    include_in_backups = qubes.property('include_in_backups',
        default=True,
        type=bool, setter=qubes.property.bool,
        doc='If this domain is to be included in default backup.')

    # format got changed from %s to str(datetime.datetime)
    backup_timestamp = qubes.property('backup_timestamp', default=None,
        setter=(lambda self, prop, value:
            value if isinstance(value, datetime.datetime) else
            datetime.datetime.fromtimestamp(int(value))),
        saver=(lambda self, prop, value: value.strftime('%s')),
        doc='FIXME')

    default_dispvm = qubes.VMProperty('default_dispvm',
        load_stage=4,
        allow_none=True,
        default=(lambda self: self.app.default_dispvm),
        doc='Default VM to be used as Disposable VM for service calls.')

    updateable = qubes.property('updateable',
        default=(lambda self: not hasattr(self, 'template')),
        type=bool,
        setter=qubes.property.forbidden,
        doc='True if this machine may be updated on its own.')

    #
    # static, class-wide properties
    #

    #
    # properties not loaded from XML, calculated at run-time
    #

    def __str__(self):
        return self.name

    # VMM-related

    @qubes.stateless_property
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

    @qubes.stateless_property
    def stubdom_xid(self):
        if not self.is_running():
            return -1

        if self.app.vmm.xs is None:
            return -1

        stubdom_xid_str = self.app.vmm.xs.read('',
            '/local/domain/{}/image/device-model-domid'.format(self.xid))
        if stubdom_xid_str is None or not stubdom_xid_str.isdigit():
            return -1

        return int(stubdom_xid_str)

    @property
    def attached_volumes(self):
        result = []
        xml_desc = self.libvirt_domain.XMLDesc()
        xml = lxml.etree.fromstring(xml_desc)
        for disk in xml.xpath("//domain/devices/disk"):
            if disk.find('backenddomain') is not None:
                pool_name = 'p_%s' % disk.find('backenddomain').get('name')
                pool = self.app.pools[pool_name]
                vid = disk.find('source').get('dev').split('/dev/')[1]
                for volume in pool.volumes:
                    if volume.vid == vid:
                        result += [volume]
                        break

        return result + list(self.volumes.values())

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
        except libvirt.libvirtError as e:
            if e.get_error_code() == libvirt.VIR_ERR_NO_DOMAIN:
                self._update_libvirt_domain()
            else:
                raise
        return self._libvirt_domain

    @property
    def block_devices(self):
        ''' Return all :py:class:`qubes.storage.BlockDevice` for current domain
        for serialization in the libvirt XML template as <disk>.
        '''
        for v in self.volumes.values():
            block_dev = v.block_device()
            if block_dev is not None:
                yield block_dev

    @property
    def untrusted_qdb(self):
        '''QubesDB handle for this domain.'''
        if self._qdb_connection is None:
            if self.is_running():
                import qubesdb  # pylint: disable=import-error
                self._qdb_connection = qubesdb.QubesDB(self.name)
        return self._qdb_connection

    @property
    def dir_path(self):
        '''Root directory for files related to this domain'''
        return os.path.join(
            qubes.config.qubes_base_dir,
            self.dir_path_prefix,
            self.name)

    @property
    def icon_path(self):
        return os.path.join(self.dir_path, 'icon.png')

    @property
    def conf_file(self):
        return os.path.join(self.dir_path, 'libvirt.xml')

    # network-related

    #
    # constructor
    #

    def __init__(self, app, xml, volume_config=None, **kwargs):
        # migrate renamed properties
        if xml is not None:
            node_hvm = xml.find('./properties/property[@name=\'hvm\']')
            if node_hvm is not None:
                if qubes.property.bool(None, None, node_hvm.text):
                    kwargs['virt_mode'] = 'hvm'
                else:
                    kwargs['virt_mode'] = 'pv'
                node_hvm.getparent().remove(node_hvm)

        super(QubesVM, self).__init__(app, xml, **kwargs)

        if volume_config is None:
            volume_config = {}

        if hasattr(self, 'volume_config'):
            if xml is not None:
                for node in xml.xpath('volume-config/volume'):
                    name = node.get('name')
                    assert name
                    for key, value in node.items():
                        # pylint: disable=no-member
                        if value == 'True':
                            value = True
                        try:
                            self.volume_config[name][key] = value
                        except KeyError:
                            self.volume_config[name] = {key: value}

            for name, conf in volume_config.items():
                for key, value in conf.items():
                    # pylint: disable=no-member
                    try:
                        self.volume_config[name][key] = value
                    except KeyError:
                        self.volume_config[name] = {key: value}

        elif volume_config:
            raise TypeError(
                'volume_config specified, but {} did not expect that.'.format(
                self.__class__.__name__))

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

        if xml is None:
            # new qube, disable updates check if requested for new qubes
            # SEE: 1637 when features are done, migrate to plugin
            if not self.app.check_updates_vm:
                self.features['check-updates'] = False

        # will be initialized after loading all the properties

        #: operations which shouldn't happen simultaneously with qube startup
        #  (including another startup of the same qube)
        self.startup_lock = asyncio.Lock()

        # fire hooks
        if xml is None:
            self.events_enabled = True
        self.fire_event('domain-init')

    def close(self):
        if self._qdb_connection is not None:
            self._qdb_connection.close()
            self._qdb_connection = None
        if self._libvirt_domain is not None:
            self._libvirt_domain = None
        super().close()

    def __hash__(self):
        return self.qid

    def __lt__(self, other):
        return self.name < other.name

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

        # Initialize VM image storage class;
        # it might be already initialized by a recursive call from a child VM
        if self.storage is None:
            self.storage = qubes.storage.Storage(self)

        if not self.app.vmm.offline_mode and self.is_running():
            self.start_qdb_watch()

    @qubes.events.handler('property-set:label')
    def on_property_set_label(self, event, name, newvalue, oldvalue=None):
        # pylint: disable=unused-argument
        if self.icon_path:
            try:
                os.remove(self.icon_path)
            except OSError:
                pass
            if hasattr(os, "symlink"):
                os.symlink(newvalue.icon_path, self.icon_path)
                subprocess.call(['sudo', 'xdg-icon-resource', 'forceupdate'])
            else:
                shutil.copy(newvalue.icon_path, self.icon_path)

    @qubes.events.handler('property-pre-set:kernel')
    def on_property_pre_set_kernel(self, event, name, newvalue, oldvalue=None):
        # pylint: disable=unused-argument
        if not newvalue:
            return
        dirname = os.path.join(
            qubes.config.qubes_base_dir,
            qubes.config.system_path['qubes_kernels_base_dir'],
            newvalue)
        if not os.path.exists(dirname):
            raise qubes.exc.QubesPropertyValueError(self,
                self.property_get_def(name), newvalue,
                'Kernel {!r} not installed'.format(newvalue))
        for filename in ('vmlinuz', 'initramfs'):
            if not os.path.exists(os.path.join(dirname, filename)):
                raise qubes.exc.QubesPropertyValueError(self,
                    self.property_get_def(name), newvalue,
                    'Kernel {!r} not properly installed: '
                    'missing {!r} file'.format(newvalue, filename))

    @qubes.events.handler('property-pre-set:autostart')
    def on_property_pre_set_autostart(self, event, name, newvalue,
            oldvalue=None):
        # pylint: disable=unused-argument
        # workaround https://bugzilla.redhat.com/show_bug.cgi?id=1181922
        if newvalue:
            retcode = subprocess.call(
                ["sudo", "ln", "-sf",
                 "/usr/lib/systemd/system/qubes-vm@.service",
                 "/etc/systemd/system/multi-user.target.wants/qubes-vm@"
                 "{}.service".format(self.name)])
        else:
            retcode = subprocess.call(
                ['sudo', 'systemctl', 'disable',
                    'qubes-vm@{}.service'.format(self.name)])
        if retcode:
            raise qubes.exc.QubesException(
                'Failed to set autostart for VM in systemd')

    @qubes.events.handler('property-pre-del:autostart')
    def on_property_pre_del_autostart(self, event, name, oldvalue=None):
        # pylint: disable=unused-argument
        if oldvalue:
            retcode = subprocess.call(
                ['sudo', 'systemctl', 'disable',
                    'qubes-vm@{}.service'.format(self.name)])
            if retcode:
                raise qubes.exc.QubesException(
                    'Failed to reset autostart for VM in systemd')

    #
    # methods for changing domain state
    #

    @asyncio.coroutine
    def start(self, start_guid=True, notify_function=None,
            mem_required=None):
        '''Start domain

        :param bool start_guid: FIXME
        :param collections.Callable notify_function: FIXME
        :param int mem_required: FIXME
        '''

        with (yield from self.startup_lock):
            # Intentionally not used is_running(): eliminate also "Paused",
            # "Crashed", "Halting"
            if self.get_power_state() != 'Halted':
                return

            self.log.info('Starting {}'.format(self.name))

            yield from self.fire_event_async('domain-pre-start',
                pre_event=True,
                start_guid=start_guid, mem_required=mem_required)

            try:
                yield from self.storage.verify()

                if self.netvm is not None:
                    # pylint: disable = no-member
                    if self.netvm.qid != 0:
                        if not self.netvm.is_running():
                            yield from self.netvm.start(start_guid=start_guid,
                                notify_function=notify_function)

                qmemman_client = yield from asyncio.get_event_loop().\
                    run_in_executor(None, self.request_memory, mem_required)

            except Exception as exc:
                # let anyone receiving domain-pre-start know that startup failed
                yield from self.fire_event_async('domain-start-failed',
                    reason=str(exc))
                raise

            try:
                yield from self.storage.start()
                self._update_libvirt_domain()

                self.libvirt_domain.createWithFlags(
                    libvirt.VIR_DOMAIN_START_PAUSED)

            except Exception as exc:
                # let anyone receiving domain-pre-start know that startup failed
                yield from self.fire_event_async('domain-start-failed',
                    reason=str(exc))
                raise

            finally:
                if qmemman_client:
                    qmemman_client.close()

            try:
                yield from self.fire_event_async('domain-spawn',
                    start_guid=start_guid)

                self.log.info('Setting Qubes DB info for the VM')
                yield from self.start_qubesdb()
                self.create_qdb_entries()
                self.start_qdb_watch()

                self.log.warning('Activating the {} VM'.format(self.name))
                self.libvirt_domain.resume()

                yield from self.start_qrexec_daemon()

                yield from self.fire_event_async('domain-start',
                    start_guid=start_guid)

            except Exception as exc:  # pylint: disable=bare-except
                if self.is_running() or self.is_paused():
                    # This avoids losing the exception if an exception is
                    # raised in self.force_shutdown(), because the vm is not
                    # running or paused
                    yield from self.kill()  # pylint: disable=not-an-iterable

                # let anyone receiving domain-pre-start know that startup failed
                yield from self.fire_event_async('domain-start-failed',
                    reason=str(exc))
                raise

        return self

    @asyncio.coroutine
    def on_domain_shutdown_coro(self):
        '''Coroutine for executing cleanup after domain shutdown.
        Do not allow domain to be started again until this finishes.
        '''
        with (yield from self.startup_lock):
            try:
                yield from self.storage.stop()
            except qubes.storage.StoragePoolException:
                self.log.exception('Failed to stop storage for domain %s',
                    self.name)

    @qubes.events.handler('domain-shutdown')
    def on_domain_shutdown(self, _event, **_kwargs):
        '''Cleanup after domain shutdown'''
        # TODO: ensure that domain haven't been started _before_ this
        # coroutine got a chance to acquire a lock
        asyncio.ensure_future(self.on_domain_shutdown_coro())

    @asyncio.coroutine
    def shutdown(self, force=False, wait=False):
        '''Shutdown domain.

        :raises qubes.exc.QubesVMNotStartedError: \
            when domain is already shut down.
        '''

        if self.is_halted():
            raise qubes.exc.QubesVMNotStartedError(self)

        yield from self.fire_event_async('domain-pre-shutdown', pre_event=True,
            force=force)

        self.libvirt_domain.shutdown()

        while wait and not self.is_halted():
            yield from asyncio.sleep(0.25)

        return self

    @asyncio.coroutine
    def kill(self):
        '''Forcefuly shutdown (destroy) domain.

        :raises qubes.exc.QubesVMNotStartedError: \
            when domain is already shut down.
        '''

        if not self.is_running() and not self.is_paused():
            raise qubes.exc.QubesVMNotStartedError(self)

        self.libvirt_domain.destroy()

        return self

    def force_shutdown(self, *args, **kwargs):
        '''Deprecated alias for :py:meth:`kill`'''
        warnings.warn(
            'Call to deprecated function force_shutdown(), use kill() instead',
            DeprecationWarning, stacklevel=2)
        return self.kill(*args, **kwargs)

    @asyncio.coroutine
    def suspend(self):
        '''Suspend (pause) domain.

        :raises qubes.exc.QubesVMNotRunnignError: \
            when domain is already shut down.
        '''

        if not self.is_running() and not self.is_paused():
            raise qubes.exc.QubesVMNotRunningError(self)

        if list(self.devices['pci'].attached()):
            yield from self.run_service_for_stdio('qubes.SuspendPre',
                user='root')
            self.libvirt_domain.pMSuspendForDuration(
                libvirt.VIR_NODE_SUSPEND_TARGET_MEM, 0, 0)
        else:
            self.libvirt_domain.suspend()

        return self

    @asyncio.coroutine
    def pause(self):
        '''Pause (suspend) domain.'''

        if not self.is_running():
            raise qubes.exc.QubesVMNotRunningError(self)

        self.libvirt_domain.suspend()

        return self

    @asyncio.coroutine
    def resume(self):
        '''Resume suspended domain.

        :raises qubes.exc.QubesVMNotSuspendedError: when machine is not paused
        :raises qubes.exc.QubesVMError: when machine is suspended
        '''

        # pylint: disable=not-an-iterable
        if self.get_power_state() == "Suspended":
            self.libvirt_domain.pMWakeup()
            yield from self.run_service_for_stdio('qubes.SuspendPost',
                user='root')
        else:
            yield from self.unpause()

        return self

    @asyncio.coroutine
    def unpause(self):
        '''Resume (unpause) a domain'''
        if not self.is_paused():
            raise qubes.exc.QubesVMNotPausedError(self)

        self.libvirt_domain.resume()

        return self

    @asyncio.coroutine
    def run_service(self, service, source=None, user=None,
            filter_esc=False, autostart=False, gui=False, **kwargs):
        '''Run service on this VM

        :param str service: service name
        :param qubes.vm.qubesvm.QubesVM source: source domain as presented to
            this VM
        :param str user: username to run service as
        :param bool filter_esc: filter escape sequences to protect terminal \
            emulator
        :param bool autostart: if :py:obj:`True`, machine will be started if \
            it is not running
        :param bool gui: when autostarting, also start gui daemon
        :rtype: asyncio.subprocess.Process

        .. note::
            User ``root`` is redefined to ``SYSTEM`` in the Windows agent code
        '''

        # UNSUPPORTED from previous incarnation:
        #   localcmd, wait, passio*, notify_function, `-e` switch
        #
        # - passio* and friends depend on params to command (like in stdlib)
        # - the filter_esc is orthogonal to passio*
        # - input: see run_service_for_stdio
        # - wait has no purpose since this is asynchronous
        # - notify_function is gone

        source = 'dom0' if source is None else self.app.domains[source].name

        if user is None:
            user = self.default_user

        if self.is_paused():
            # XXX what about autostart?
            raise qubes.exc.QubesVMNotRunningError(
                self, 'Domain {!r} is paused'.format(self.name))
        elif not self.is_running():
            if not autostart:
                raise qubes.exc.QubesVMNotRunningError(self)
            yield from self.start(start_guid=gui)

        if not self.is_qrexec_running():
            raise qubes.exc.QubesVMError(
                self, 'Domain {!r}: qrexec not connected'.format(self.name))

        yield from self.fire_event_async('domain-cmd-pre-run', pre_event=True,
            start_guid=gui)

        return (yield from asyncio.create_subprocess_exec(
            qubes.config.system_path['qrexec_client_path'],
            '-d', str(self.name),
            *(('-t',) if filter_esc else ()),
            *(('-T',) if filter_esc or os.isatty(sys.stderr.fileno()) else ()),
            '{}:QUBESRPC {} {}'.format(user, service, source),
            **kwargs))

    @asyncio.coroutine
    def run_service_for_stdio(self, *args, input=None, **kwargs):
        '''Run a service, pass an optional input and return (stdout, stderr).

        Raises an exception if return code != 0.

        *args* and *kwargs* are passed verbatim to :py:meth:`run_service`.

        .. warning::
            There are some combinations if stdio-related *kwargs*, which are
            not filtered for problems originating between the keyboard and the
            chair.
        '''  # pylint: disable=redefined-builtin

        kwargs.setdefault('stdin', subprocess.PIPE)
        kwargs.setdefault('stdout', subprocess.PIPE)
        kwargs.setdefault('stderr', subprocess.PIPE)
        p = yield from self.run_service(*args, **kwargs)

        # this one is actually a tuple, but there is no need to unpack it
        stdouterr = yield from p.communicate(input=input)

        if p.returncode:
            raise subprocess.CalledProcessError(p.returncode,
                args[0], *stdouterr)

        return stdouterr

    @staticmethod
    def _prepare_input_for_vmshell(command, input):
        '''Prepare shell input for the given command and optional (real) input
        '''  # pylint: disable=redefined-builtin
        if input is None:
            input = b''
        return b''.join((command.rstrip('\n').encode('utf-8'), b'\n', input))

    def run(self, command, user=None, **kwargs):
        '''Run a shell command inside the domain using qrexec.

        This method is a coroutine.
        '''  # pylint: disable=redefined-builtin

        if user is None:
            user = self.default_user

        return asyncio.create_subprocess_exec(
            qubes.config.system_path['qrexec_client_path'],
            '-d', str(self.name),
            *(('-T',) if os.isatty(sys.stderr.fileno()) else ()),
            '{}:{}'.format(user, command),
            **kwargs)

    @asyncio.coroutine
    def run_for_stdio(self, *args, input=None, **kwargs):
        '''Run a shell command inside the domain using qubes.VMShell qrexec.

        This method is a coroutine.

        *kwargs* are passed verbatim to :py:meth:`run_service_for_stdio`.
        See disclaimer there.
        '''  # pylint: disable=redefined-builtin

        kwargs.setdefault('stdin', subprocess.PIPE)
        kwargs.setdefault('stdout', subprocess.PIPE)
        kwargs.setdefault('stderr', subprocess.PIPE)
        p = yield from self.run(*args, **kwargs)
        stdouterr = yield from p.communicate(input=input)

        if p.returncode:
            raise subprocess.CalledProcessError(p.returncode,
                args[0], *stdouterr)

        return stdouterr

    def request_memory(self, mem_required=None):
        # overhead of per-qube/per-vcpu Xen structures,
        # taken from OpenStack nova/virt/xenapi/driver.py
        # see https://wiki.openstack.org/wiki/XenServer/Overhead
        # add an extra MB because Nova rounds up to MBs

        if not qmemman_present:
            return

        if mem_required is None:
            if self.virt_mode == 'hvm':
                if self.stubdom_mem:
                    stubdom_mem = self.stubdom_mem
                else:
                    if self.features.check_with_template('linux-stubdom', True):
                        stubdom_mem = 128 # from libxl_create.c
                    else:
                        stubdom_mem = 28 # from libxl_create.c
                stubdom_mem += 16 # video ram
            else:
                stubdom_mem = 0

            mem_required = int(self.memory + stubdom_mem) * 1024 * 1024

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

    @staticmethod
    @asyncio.coroutine
    def start_daemon(*command, input=None, **kwargs):
        '''Start a daemon for the VM

        This function take care to run it as appropriate user.

        :param command: command to run (array for
            :py:meth:`subprocess.check_call`)
        :param kwargs: args for :py:meth:`subprocess.check_call`
        :return: None
        '''  # pylint: disable=redefined-builtin

        if os.getuid() == 0:
            # try to always have VM daemons running as normal user, otherwise
            # some files (like clipboard) may be created as root and cause
            # permission problems
            qubes_group = grp.getgrnam('qubes')
            command = ['runuser', '-u', qubes_group.gr_mem[0], '--'] + \
                list(command)
        p = yield from asyncio.create_subprocess_exec(*command, **kwargs)
        stdout, stderr = yield from p.communicate(input=input)
        if p.returncode:
            raise subprocess.CalledProcessError(p.returncode, command,
                output=stdout, stderr=stderr)

    @asyncio.coroutine
    def start_qrexec_daemon(self):
        '''Start qrexec daemon.

        :raises OSError: when starting fails.
        '''

        self.log.debug('Starting the qrexec daemon')
        qrexec_args = [str(self.xid), self.name, self.default_user]
        if not self.debug:
            qrexec_args.insert(0, "-q")

        qrexec_env = os.environ.copy()
        if not self.features.check_with_template('qrexec', False):
            self.log.debug(
                'Starting the qrexec daemon in background, because of features')
            qrexec_env['QREXEC_STARTUP_NOWAIT'] = '1'
        else:
            qrexec_env['QREXEC_STARTUP_TIMEOUT'] = str(self.qrexec_timeout)

        try:
            yield from self.start_daemon(
                qubes.config.system_path['qrexec_daemon_path'], *qrexec_args,
                env=qrexec_env)
        except subprocess.CalledProcessError:
            raise qubes.exc.QubesVMError(self, 'Cannot execute qrexec-daemon!')

    @asyncio.coroutine
    def start_qubesdb(self):
        '''Start QubesDB daemon.

        :raises OSError: when starting fails.
        '''

        # drop old connection to QubesDB, if any
        self._qdb_connection = None

        self.log.info('Starting Qubes DB')
        try:
            yield from self.start_daemon(
                qubes.config.system_path['qubesdb_daemon_path'],
                str(self.xid),
                self.name)
        except subprocess.CalledProcessError:
            raise qubes.exc.QubesException('Cannot execute qubesdb-daemon')

    @asyncio.coroutine
    def create_on_disk(self, pool=None, pools=None):
        '''Create files needed for VM.
        '''

        self.log.info('Creating directory: {0}'.format(self.dir_path))
        os.makedirs(self.dir_path, mode=0o775)

        if pool or pools:
            # pylint: disable=attribute-defined-outside-init
            self.volume_config = _patch_volume_config(self.volume_config, pool,
                                                      pools)
            self.storage = qubes.storage.Storage(self)

        try:
            yield from self.storage.create()
        except:
            try:
                yield from self.storage.remove()
                os.rmdir(self.dir_path)
            except:  # pylint: disable=bare-except
                self.log.exception('failed to cleanup {} after failed VM '
                                   'creation'.format(self.dir_path))
            raise

        self.log.info('Creating icon symlink: {} -> {}'.format(
            self.icon_path, self.label.icon_path))
        if hasattr(os, "symlink"):
            os.symlink(self.label.icon_path, self.icon_path)
        else:
            shutil.copy(self.label.icon_path, self.icon_path)

        # fire hooks
        yield from self.fire_event_async('domain-create-on-disk')

    @asyncio.coroutine
    def remove_from_disk(self):
        '''Remove domain remnants from disk.'''
        if not self.is_halted():
            raise qubes.exc.QubesVMNotHaltedError(
                "Can't remove VM {!s}, beacuse it's in state {!r}.".format(
                    self, self.get_power_state()))

        yield from self.fire_event_async('domain-remove-from-disk')
        try:
            # TODO: make it async?
            shutil.rmtree(self.dir_path)
        except OSError as e:
            if e.errno == errno.ENOENT:
                pass
            else:
                raise
        yield from self.storage.remove()

    @asyncio.coroutine
    def clone_disk_files(self, src, pool=None, pools=None, ):
        '''Clone files from other vm.

        :param qubes.vm.qubesvm.QubesVM src: source VM
        '''

        # If the current vm name is not a part of `self.app.domains.keys()`,
        # then the current vm is in creation process. Calling
        # `self.is_halted()` at this point, would instantiate libvirt, we want
        # avoid that.
        if self.name in self.app.domains.keys() and not self.is_halted():
            raise qubes.exc.QubesVMNotHaltedError(
                self, 'Cannot clone a running domain {!r}'.format(self.name))

        msg = "Destination {!s} already exists".format(self.dir_path)
        assert not os.path.exists(self.dir_path), msg

        self.log.info('Creating directory: {0}'.format(self.dir_path))
        os.makedirs(self.dir_path, mode=0o775)

        if pool or pools:
            # pylint: disable=attribute-defined-outside-init
            self.volume_config = _patch_volume_config(self.volume_config, pool,
                                                      pools)

        self.storage = qubes.storage.Storage(self)
        yield from self.storage.clone(src)
        self.storage.verify()
        assert self.volumes != {}

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
        yield from self.fire_event_async('domain-clone-files', src=src)

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
        ``'Paused'``    Machine is paused.
        ``'Suspended'`` Machine is S3-suspended.
        ``'Halting'``   Machine is in process of shutting down.
        ``'Dying'``     Machine crashed and is unusable.
        ``'Crashed'``   Machine crashed and is unusable, probably because of
                        bug in dom0.
        ``'NA'``        Machine is in unknown state (most likely libvirt domain
                        is undefined).
        =============== ========================================================

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
                    [label="suspend()" URL="#qubes.vm.qubesvm.QubesVM.suspend"
                        color=gray50 fontcolor=gray50];
                Paused -> Running
                    [label="unpause()" URL="#qubes.vm.qubesvm.QubesVM.unpause"
                        color=gray75 fontcolor=gray75];
                Suspended -> Running
                    [label="resume()" URL="#qubes.vm.qubesvm.QubesVM.resume"
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
        '''  # pylint: disable=too-many-return-statements

        # don't try to define libvirt domain, if it isn't there, VM surely
        # isn't running
        # reason for this "if": allow vm.is_running() in PCI (or other
        # device) extension while constructing libvirt XML
        if self.app.vmm.offline_mode:
            return 'Halted'
        if self._libvirt_domain is None:
            try:
                self._libvirt_domain = self.app.vmm.libvirt_conn.lookupByUUID(
                    self.uuid.bytes)
            except libvirt.libvirtError as e:
                if e.get_error_code() == libvirt.VIR_ERR_NO_DOMAIN:
                    return 'Halted'
                else:
                    raise

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
                elif libvirt_domain.state()[0] == libvirt.VIR_DOMAIN_PMSUSPENDED:  # nopep8
                    return "Suspended"
                else:
                    if not self.is_fully_usable():
                        return "Transient"

                    return "Running"

            return 'Halted'
        except libvirt.libvirtError as e:
            if e.get_error_code() == libvirt.VIR_ERR_NO_DOMAIN:
                return 'Halted'
            raise

        assert False

    def is_halted(self):
        ''' Check whether this domain's state is 'Halted'
            :returns: :py:obj:`True` if this domain is halted, \
                :py:obj:`False` otherwise.
            :rtype: bool
        '''
        return self.get_power_state() == 'Halted'

    def is_running(self):
        '''Check whether this domain is running.

        :returns: :py:obj:`True` if this domain is started, \
            :py:obj:`False` otherwise.
        :rtype: bool
        '''

        if self.app.vmm.offline_mode:
            return False

        # don't try to define libvirt domain, if it isn't there, VM surely
        # isn't running
        # reason for this "if": allow vm.is_running() in PCI (or other
        # device) extension while constructing libvirt XML
        if self._libvirt_domain is None:
            try:
                self._libvirt_domain = self.app.vmm.libvirt_conn.lookupByUUID(
                    self.uuid.bytes)
            except libvirt.libvirtError as e:
                if e.get_error_code() == libvirt.VIR_ERR_NO_DOMAIN:
                    return False
                else:
                    raise

        return self.libvirt_domain.isActive()

    def is_paused(self):
        '''Check whether this domain is paused.

        :returns: :py:obj:`True` if this domain is paused, \
            :py:obj:`False` otherwise.
        :rtype: bool
        '''

        return self.libvirt_domain \
            and self.libvirt_domain.state()[0] == libvirt.VIR_DOMAIN_PAUSED

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
        '''  # pylint: disable=unused-argument

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
                    libvirt.VIR_ERR_INTERNAL_ERROR):
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
                    libvirt.VIR_ERR_INTERNAL_ERROR):
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
                    libvirt.VIR_ERR_INTERNAL_ERROR):
                return 0

            else:
                self.log.exception(
                    'libvirt error code: {!r}'.format(e.get_error_code()))
                raise

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

        return None

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

        self.untrusted_qdb.write('/name', self.name)
        self.untrusted_qdb.write('/type', self.__class__.__name__)
        self.untrusted_qdb.write('/qubes-vm-updateable', str(self.updateable))
        self.untrusted_qdb.write('/qubes-vm-persistence',
            'full' if self.updateable else 'rw-only')
        self.untrusted_qdb.write('/qubes-debug-mode', str(int(self.debug)))
        try:
            self.untrusted_qdb.write('/qubes-base-template', self.template.name)
        except AttributeError:
            self.untrusted_qdb.write('/qubes-base-template', '')

        self.untrusted_qdb.write('/qubes-random-seed',
            base64.b64encode(qubes.utils.urandom(64)))

        if self.provides_network:
            # '/qubes-netvm-network' value is only checked for being non empty
            self.untrusted_qdb.write('/qubes-netvm-network', self.gateway)
            self.untrusted_qdb.write('/qubes-netvm-gateway', self.gateway)
            self.untrusted_qdb.write('/qubes-netvm-netmask', self.netmask)

            for i, addr in zip(('primary', 'secondary'), self.dns):
                self.untrusted_qdb.write('/qubes-netvm-{}-dns'.format(i), addr)

        if self.netvm is not None:
            self.untrusted_qdb.write('/qubes-ip', self.visible_ip)
            self.untrusted_qdb.write('/qubes-netmask', self.visible_netmask)
            self.untrusted_qdb.write('/qubes-gateway', self.visible_gateway)

            for i, addr in zip(('primary', 'secondary'), self.dns):
                self.untrusted_qdb.write('/qubes-{}-dns'.format(i), addr)


        tzname = qubes.utils.get_timezone()
        if tzname:
            self.untrusted_qdb.write('/qubes-timezone', tzname)

        self.untrusted_qdb.write('/qubes-block-devices', '')

        self.untrusted_qdb.write('/qubes-usb-devices', '')

        # TODO: Currently the whole qmemman is quite Xen-specific, so stay with
        # xenstore for it until decided otherwise
        if qmemman_present:
            self.app.vmm.xs.set_permissions('',
                '/local/domain/{}/memory'.format(self.xid),
                [{'dom': self.xid}])

        self.fire_event('domain-qdb-create')

    # TODO async; update this in constructor
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
        if domain.mem_used is None:
            # apparently invalid xenstore content
            return 0
        domain.memory_maximum = self.get_mem_static_max() * 1024

        return qubes.qmemman.algo.prefmem(domain) / 1024


def _clean_volume_config(config):
    common_attributes = ['name', 'pool', 'size',
                         'revisions_to_keep', 'rw', 'snap_on_start',
                         'save_on_stop', 'source']
    return {k: v for k, v in config.items() if k in common_attributes}


def _patch_pool_config(config, pool=None, pools=None):
    assert pool is not None or pools is not None
    is_snapshot = config['snap_on_start']
    is_rw = config['rw']

    name = config['name']

    if pool and not is_snapshot and is_rw:
        config['pool'] = str(pool)
    elif pool:
        pass
    elif pools and name in pools.keys():
        if not is_snapshot:
            config['pool'] = str(pools[name])
        else:
            msg = "Can't clone a snapshot volume {!s} to pool {!s} " \
                .format(name, pools[name])
            raise qubes.exc.QubesException(msg)
    return config

def _patch_volume_config(volume_config, pool=None, pools=None):
    assert not (pool and pools), \
        'You can not pass pool & pools parameter at same time'
    assert pool or pools

    result = {}

    for name, config in volume_config.items():
        # copy only the subset of volume_config key/values
        dst_config = _clean_volume_config(config)

        if pool is not None or pools is not None:
            dst_config = _patch_pool_config(dst_config, pool, pools)

        result[name] = dst_config

    return result
