#
# The Qubes OS Project, https://www.qubes-os.org/
#
# Copyright (C) 2010-2015  Joanna Rutkowska <joanna@invisiblethingslab.com>
# Copyright (C) 2011-2015  Marek Marczykowski-Górecki
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

import collections
import errno
import functools
import grp
import logging
import os
import random
import subprocess
import sys
import tempfile
import time
import uuid

import lxml.etree

import jinja2
import libvirt

try:
    import xen.lowlevel.xs  # pylint: disable=wrong-import-order
    import xen.lowlevel.xc  # pylint: disable=wrong-import-order
except ImportError:
    pass

if os.name == 'posix':
    # pylint: disable=wrong-import-order
    import fcntl
elif os.name == 'nt':
    # pylint: disable=import-error
    import win32con
    import win32file
    import pywintypes
else:
    raise RuntimeError("Qubes works only on POSIX or WinNT systems")

# pylint: disable=wrong-import-position
import qubes
import qubes.ext
import qubes.utils
import qubes.storage
import qubes.vm
import qubes.vm.adminvm
import qubes.vm.qubesvm
import qubes.vm.templatevm
# pylint: enable=wrong-import-position

class VirDomainWrapper(object):
    # pylint: disable=too-few-public-methods

    def __init__(self, connection, vm):
        self._connection = connection
        self._vm = vm

    def _reconnect_if_dead(self):
        is_dead = not self._vm.connect().isAlive()
        if is_dead:
            # pylint: disable=protected-access
            self._connection._reconnect_if_dead()
            self._vm = self._connection._conn.lookupByUUID(self._vm.UUID())
        return is_dead

    def __getattr__(self, attrname):
        attr = getattr(self._vm, attrname)
        if not isinstance(attr, collections.Callable):
            return attr

        @functools.wraps(attr)
        def wrapper(*args, **kwargs):
            try:
                return attr(*args, **kwargs)
            except libvirt.libvirtError:
                if self._reconnect_if_dead():
                    return getattr(self._vm, attrname)(*args, **kwargs)
                raise
        return wrapper


class VirConnectWrapper(object):
    # pylint: disable=too-few-public-methods

    def __init__(self, uri):
        self._conn = libvirt.open(uri)

    def _reconnect_if_dead(self):
        is_dead = not self._conn.isAlive()
        if is_dead:
            self._conn = libvirt.open(self._conn.getURI())
            # TODO: re-register event handlers
        return is_dead

    def _wrap_domain(self, ret):
        if isinstance(ret, libvirt.virDomain):
            ret = VirDomainWrapper(self, ret)
        return ret

    def __getattr__(self, attrname):
        attr = getattr(self._conn, attrname)
        if not isinstance(attr, collections.Callable):
            return attr
        if attrname == 'close':
            return attr

        @functools.wraps(attr)
        def wrapper(*args, **kwargs):
            try:
                return self._wrap_domain(attr(*args, **kwargs))
            except libvirt.libvirtError:
                if self._reconnect_if_dead():
                    return self._wrap_domain(
                        getattr(self._conn, attrname)(*args, **kwargs))
                raise
        return wrapper


class VMMConnection(object):
    '''Connection to Virtual Machine Manager (libvirt)'''

    def __init__(self, offline_mode=None):
        '''

        :param offline_mode: enable/disable offline mode; default is to
        enable when running in chroot as root, otherwise disable
        '''
        self._libvirt_conn = None
        self._xs = None
        self._xc = None
        if offline_mode is None:
            offline_mode = bool(os.getuid() == 0 and
                os.stat('/') != os.stat('/proc/1/root/.'))
        self._offline_mode = offline_mode

    @property
    def offline_mode(self):
        '''Check or enable offline mode (do not actually connect to vmm)'''
        return self._offline_mode

    def _libvirt_error_handler(self, ctx, error):
        pass

    def init_vmm_connection(self):
        '''Initialise connection

        This method is automatically called when getting'''
        if self._libvirt_conn is not None:
            # Already initialized
            return
        if self._offline_mode:
            # Do not initialize in offline mode
            raise qubes.exc.QubesException(
                'VMM operations disabled in offline mode')

        if 'xen.lowlevel.xs' in sys.modules:
            self._xs = xen.lowlevel.xs.xs()
        if 'xen.lowlevel.xc' in sys.modules:
            self._xc = xen.lowlevel.xc.xc()
        self._libvirt_conn = VirConnectWrapper(
            qubes.config.defaults['libvirt_uri'])
        libvirt.registerErrorHandler(self._libvirt_error_handler, None)

    @property
    def libvirt_conn(self):
        '''Connection to libvirt'''
        self.init_vmm_connection()
        return self._libvirt_conn

    @property
    def xs(self):
        '''Connection to Xen Store

        This property in available only when running on Xen.
        '''

        # XXX what about the case when we run under KVM,
        # but xen modules are importable?
        if 'xen.lowlevel.xs' not in sys.modules:
            raise AttributeError(
                'xs object is available under Xen hypervisor only')

        self.init_vmm_connection()
        return self._xs

    @property
    def xc(self):
        '''Connection to Xen

        This property in available only when running on Xen.
        '''

        # XXX what about the case when we run under KVM,
        # but xen modules are importable?
        if 'xen.lowlevel.xc' not in sys.modules:
            raise AttributeError(
                'xc object is available under Xen hypervisor only')

        self.init_vmm_connection()
        return self._xc

    def register_event_handlers(self, app):
        '''Register libvirt event handlers, which will translate libvirt
        events into qubes.events. This function should be called only in
        'qubesd' process and only when mainloop has been already set.
        '''
        self.libvirt_conn.domainEventRegisterAny(
            None,  # any domain
            libvirt.VIR_DOMAIN_EVENT_ID_LIFECYCLE,
            self._domain_event_callback,
            app
        )

    @staticmethod
    def _domain_event_callback(_conn, domain, event, _detail, opaque):
        '''Generic libvirt event handler (virConnectDomainEventCallback),
        translate libvirt event into qubes.events.
        '''
        app = opaque
        try:
            vm = app.domains[domain.name()]
        except KeyError:
            # ignore events for unknown domains
            return

        if event == libvirt.VIR_DOMAIN_EVENT_STOPPED:
            vm.fire_event('domain-shutdown')

    def __del__(self):
        if self._libvirt_conn:
            self._libvirt_conn.close()


class QubesHost(object):
    '''Basic information about host machine

    :param qubes.Qubes app: Qubes application context (must have \
        :py:attr:`Qubes.vmm` attribute defined)
    '''

    def __init__(self, app):
        self.app = app
        self._no_cpus = None
        self._total_mem = None
        self._physinfo = None


    def _fetch(self):
        if self._no_cpus is not None:
            return

        # pylint: disable=unused-variable
        (model, memory, cpus, mhz, nodes, socket, cores, threads) = \
            self.app.vmm.libvirt_conn.getInfo()
        self._total_mem = int(memory) * 1024
        self._no_cpus = cpus

        self.app.log.debug('QubesHost: no_cpus={} memory_total={}'.format(
            self.no_cpus, self.memory_total))
        try:
            self.app.log.debug('QubesHost: xen_free_memory={}'.format(
                self.get_free_xen_memory()))
        except NotImplementedError:
            pass


    @property
    def memory_total(self):
        '''Total memory, in kbytes'''

        if self.app.vmm.offline_mode:
            return 2**64-1
        self._fetch()
        return self._total_mem


    @property
    def no_cpus(self):
        '''Number of CPUs'''

        if self.app.vmm.offline_mode:
            return 42

        self._fetch()
        return self._no_cpus


    def get_free_xen_memory(self):
        '''Get free memory from Xen's physinfo.

        :raises NotImplementedError: when not under Xen
        '''
        try:
            self._physinfo = self.app.xc.physinfo()
        except AttributeError:
            raise NotImplementedError('This function requires Xen hypervisor')
        return int(self._physinfo['free_memory'])


    def get_vm_stats(self, previous_time=None, previous=None, only_vm=None):
        '''Measure cpu usage for all domains at once.

        If previous measurements are given, CPU usage will be given in
        percents of time. Otherwise only absolute value (seconds).

        Return a tuple of (measurements_time, measurements),
        where measurements is a dictionary with key: domid, value: dict:
         - cpu_time - absolute CPU usage (seconds since its startup)
         - cpu_usage - CPU usage in %
         - memory_kb - current memory assigned, in kb

        This function requires Xen hypervisor.

        ..warning:

           This function may return info about implementation-specific VMs,
           like stubdomains for HVM

        :param previous: previous measurement
        :param previous_time: time of previous measurement
        :param only_vm: get measurements only for this VM

        :raises NotImplementedError: when not under Xen
        '''

        if (previous_time is None) != (previous is None):
            raise ValueError(
                'previous and previous_time must be given together (or none)')

        if previous is None:
            previous = {}

        current_time = time.time()
        current = {}
        try:
            if only_vm:
                xid = only_vm.xid
                if xid < 0:
                    raise qubes.exc.QubesVMNotRunningError(only_vm)
                info = self.app.vmm.xc.domain_getinfo(xid, 1)
                if info[0]['domid'] != xid:
                    raise qubes.exc.QubesVMNotRunningError(only_vm)
            else:
                info = self.app.vmm.xc.domain_getinfo(0, 1024)
        except AttributeError:
            raise NotImplementedError(
                'This function requires Xen hypervisor')
        # TODO: add stubdomain stats to actual VMs
        for vm in info:
            domid = vm['domid']
            current[domid] = {}
            current[domid]['memory_kb'] = vm['mem_kb']
            current[domid]['cpu_time'] = int(
                vm['cpu_time'] / max(vm['online_vcpus'], 1))
            if domid in previous:
                current[domid]['cpu_usage'] = int(
                    (current[domid]['cpu_time'] - previous[domid]['cpu_time'])
                    / 1000 ** 3 * 100 / (current_time - previous_time))
                if current[domid]['cpu_usage'] < 0:
                    # VM has been rebooted
                    current[domid]['cpu_usage'] = 0
            else:
                current[domid]['cpu_usage'] = 0

        return (current_time, current)


class VMCollection(object):
    '''A collection of Qubes VMs

    VMCollection supports ``in`` operator. You may test for ``qid``, ``name``
    and whole VM object's presence.

    Iterating over VMCollection will yield machine objects.
    '''

    def __init__(self, app):
        self.app = app
        self._dict = dict()


    def __repr__(self):
        return '<{} {!r}>'.format(
            self.__class__.__name__, list(sorted(self.keys())))


    def items(self):
        '''Iterate over ``(qid, vm)`` pairs'''
        for qid in self.qids():
            yield (qid, self[qid])


    def qids(self):
        '''Iterate over all qids

        qids are sorted by numerical order.
        '''

        return iter(sorted(self._dict.keys()))

    keys = qids


    def names(self):
        '''Iterate over all names

        names are sorted by lexical order.
        '''

        return iter(sorted(vm.name for vm in self._dict.values()))


    def vms(self):
        '''Iterate over all machines

        vms are sorted by qid.
        '''

        return iter(sorted(self._dict.values()))

    __iter__ = vms
    values = vms

    def add(self, value, _enable_events=True):
        '''Add VM to collection

        :param qubes.vm.BaseVM value: VM to add
        :raises TypeError: when value is of wrong type
        :raises ValueError: when there is already VM which has equal ``qid``
        '''

        # this violates duck typing, but is needed
        # for VMProperty to function correctly
        if not isinstance(value, qubes.vm.BaseVM):
            raise TypeError('{} holds only BaseVM instances'.format(
                self.__class__.__name__))

        if value.qid in self:
            raise ValueError('This collection already holds VM that has '
                'qid={!r} ({!r})'.format(value.qid, self[value.qid]))
        if value.name in self:

            raise ValueError('A VM named {!s} already exists'
                .format(value.name))

        self._dict[value.qid] = value
        if _enable_events:
            value.events_enabled = True
            self.app.fire_event('domain-add', vm=value)

        return value

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._dict[key]

        if isinstance(key, str):
            for vm in self:
                if vm.name == key:
                    return vm
            raise KeyError(key)

        if isinstance(key, qubes.vm.BaseVM):
            key = key.uuid

        if isinstance(key, uuid.UUID):
            for vm in self:
                if vm.uuid == key:
                    return vm
            raise KeyError(key)

        raise KeyError(key)

    def __delitem__(self, key):
        vm = self[key]
        if not vm.is_halted():
            raise qubes.exc.QubesVMNotHaltedError(vm)
        self.app.fire_event('domain-pre-delete', pre_event=True, vm=vm)
        try:
            vm.libvirt_domain.undefine()
        except libvirt.libvirtError as e:
            if e.get_error_code() == libvirt.VIR_ERR_NO_DOMAIN:
                # already undefined
                pass
        del self._dict[vm.qid]
        self.app.fire_event('domain-delete', vm=vm)

    def __contains__(self, key):
        return any((key == vm or key == vm.qid or key == vm.name)
                   for vm in self)


    def __len__(self):
        return len(self._dict)


    def get_vms_based_on(self, template):
        template = self[template]
        return set(vm for vm in self
            if hasattr(vm, 'template') and vm.template == template)


    def get_vms_connected_to(self, netvm):
        new_vms = set([self[netvm]])
        dependent_vms = set()

        # Dependency resolving only makes sense on NetVM (or derivative)
#       if not self[netvm_qid].is_netvm():
#           return set([])

        while new_vms:
            cur_vm = new_vms.pop()
            for vm in cur_vm.connected_vms:
                if vm in dependent_vms:
                    continue
                dependent_vms.add(vm)
#               if vm.is_netvm():
                new_vms.add(vm)

        return dependent_vms


    # XXX with Qubes Admin Api this will probably lead to race condition
    # whole process of creating and adding should be synchronised
    def get_new_unused_qid(self):
        used_ids = set(self.qids())
        for i in range(1, qubes.config.max_qid):
            if i not in used_ids:
                return i
        raise LookupError("Cannot find unused qid!")


    def get_new_unused_netid(self):
        used_ids = set([vm.netid for vm in self])  # if vm.is_netvm()])
        for i in range(1, qubes.config.max_netid):
            if i not in used_ids:
                return i
        raise LookupError("Cannot find unused netid!")


    def get_new_unused_dispid(self):
        for _ in range(int(qubes.config.max_dispid ** 0.5)):
            dispid = random.SystemRandom().randrange(qubes.config.max_dispid)
            if not any(getattr(vm, 'dispid', None) == dispid for vm in self):
                return dispid
        raise LookupError((
            'https://xkcd.com/221/',
            'http://dilbert.com/strip/2001-10-25')[random.randint(0, 1)])

def _default_pool(app):
    ''' Default storage pool.

    1. If there is one named 'default', use it.
    2. Check if root fs is on LVM thin - use that
    3. Look for file-based pool pointing /var/lib/qubes
    4. Fail
    '''
    if 'default' in app.pools:
        return app.pools['default']
    else:
        rootfs = os.stat('/')
        root_major = (rootfs.st_dev & 0xff00) >> 8
        root_minor = rootfs.st_dev & 0xff
        for pool in app.pools.values():
            if pool.config.get('driver', None) != 'lvm_thin':
                continue
            thin_pool = pool.config['thin_pool']
            thin_volumes = subprocess.check_output(
                ['lvs', '--select', 'pool_lv=' + thin_pool,
                '-o', 'lv_kernel_major,lv_kernel_minor', '--noheadings'])
            if any((str(root_major), str(root_minor)) == thin_vol.split()
                    for thin_vol in thin_volumes.splitlines()):
                return pool
        # not a thin volume? look for file pools
        for pool in app.pools.values():
            if pool.config.get('driver', None) != 'file':
                continue
            if pool.config['dir_path'] == qubes.config.qubes_base_dir:
                return pool
        raise AttributeError('Cannot determine default storage pool')

def _setter_pool(app, prop, value):
    if isinstance(value, qubes.storage.Pool):
        return value
    try:
        return app.pools[value]
    except KeyError:
        raise qubes.exc.QubesPropertyValueError(app, prop, value,
            'No such storage pool')

class Qubes(qubes.PropertyHolder):
    '''Main Qubes application

    :param str store: path to ``qubes.xml``

    The store is loaded in stages:

    1.  In the first stage there are loaded some basic features from store
        (currently labels).

    2.  In the second stage stubs for all VMs are loaded. They are filled
        with their basic properties, like ``qid`` and ``name``.

    3.  In the third stage all global properties are loaded. They often
        reference VMs, like default netvm, so they should be filled after
        loading VMs.

    4.  In the fourth stage all remaining VM properties are loaded. They
        also need all VMs loaded, because they represent dependencies
        between VMs like aforementioned netvm.

    5.  In the fifth stage there are some fixups to ensure sane system
        operation.

    This class emits following events:

        .. event:: domain-add (subject, event, vm)

            When domain is added.

            :param subject: Event emitter
            :param event: Event name (``'domain-add'``)
            :param vm: Domain object

        .. event:: domain-pre-delete (subject, event, vm)

            When domain is deleted. VM still has reference to ``app`` object,
            and is contained within VMCollection. You may prevent removal by
            raising an exception.

            :param subject: Event emitter
            :param event: Event name (``'domain-pre-delete'``)
            :param vm: Domain object

        .. event:: domain-delete (subject, event, vm)

            When domain is deleted. VM still has reference to ``app`` object,
            but is not contained within VMCollection.

            :param subject: Event emitter
            :param event: Event name (``'domain-delete'``)
            :param vm: Domain object

    Methods and attributes:
    '''

    default_netvm = qubes.VMProperty('default_netvm', load_stage=3,
        default=None, allow_none=True,
        doc='''Default NetVM for AppVMs. Initial state is `None`, which means
            that AppVMs are not connected to the Internet.''')
    default_fw_netvm = qubes.VMProperty('default_fw_netvm', load_stage=3,
        default=None, allow_none=True,
        doc='''Default NetVM for ProxyVMs. Initial state is `None`, which means
            that ProxyVMs (including FirewallVM) are not connected to the
            Internet.''')
    default_template = qubes.VMProperty('default_template', load_stage=3,
        vmclass=qubes.vm.templatevm.TemplateVM,
        doc='Default template for new AppVMs')
    updatevm = qubes.VMProperty('updatevm', load_stage=3,
        allow_none=True,
        doc='''Which VM to use as `yum` proxy for updating AdminVM and
            TemplateVMs''')
    clockvm = qubes.VMProperty('clockvm', load_stage=3,
        allow_none=True,
        doc='Which VM to use as NTP proxy for updating AdminVM')
    default_kernel = qubes.property('default_kernel', load_stage=3,
        doc='Which kernel to use when not overriden in VM')
    default_dispvm = qubes.VMProperty('default_dispvm', load_stage=3,
        doc='Default DispVM base for service calls')

    default_pool = qubes.property('default_pool', load_stage=3,
        default=_default_pool,
        setter=_setter_pool,
        doc='Default storage pool')

    default_pool_private = qubes.property('default_pool_private', load_stage=3,
        default=lambda app: app.default_pool,
        setter=_setter_pool,
        doc='Default storage pool for private volumes')

    default_pool_root = qubes.property('default_pool_root', load_stage=3,
        default=lambda app: app.default_pool,
        setter=_setter_pool,
        doc='Default storage pool for root volumes')

    default_pool_volatile = qubes.property('default_pool_volatile',
        load_stage=3,
        default=lambda app: app.default_pool,
        setter=_setter_pool,
        doc='Default storage pool for volatile volumes')

    default_pool_kernel = qubes.property('default_pool_kernel', load_stage=3,
        default=lambda app: app.default_pool,
        setter=_setter_pool,
        doc='Default storage pool for kernel volumes')

    stats_interval = qubes.property('stats_interval',
        default=3,
        type=int,
        doc='Interval in seconds for VM stats reporting (memory, CPU usage)')

    # TODO #1637 #892
    check_updates_vm = qubes.property('check_updates_vm',
        type=bool, setter=qubes.property.bool,
        default=True,
        doc='check for updates inside qubes')

    def __init__(self, store=None, load=True, offline_mode=None, lock=False,
            **kwargs):
        #: logger instance for logging global messages
        self.log = logging.getLogger('app')

        self._extensions = qubes.ext.get_extensions()

        #: collection of all VMs managed by this Qubes instance
        self.domains = VMCollection(self)

        #: collection of all available labels for VMs
        self.labels = {}

        #: collection of all pools
        self.pools = {}

        #: Connection to VMM
        self.vmm = VMMConnection(offline_mode=offline_mode)

        #: Information about host system
        self.host = QubesHost(self)

        if store is not None:
            self._store = store
        else:
            self._store = os.environ.get('QUBES_XML_PATH',
                os.path.join(
                    qubes.config.qubes_base_dir,
                    qubes.config.system_path['qubes_store_filename']))

        super(Qubes, self).__init__(xml=None, **kwargs)

        self.__load_timestamp = None
        self.__locked_fh = None

        #: jinja2 environment for libvirt XML templates
        self.env = jinja2.Environment(
            loader=jinja2.FileSystemLoader([
                '/etc/qubes/templates',
                '/usr/share/qubes/templates',
            ]),
            undefined=jinja2.StrictUndefined)

        if load:
            self.load(lock=lock)

        self.events_enabled = True

    @property
    def store(self):
        return self._store

    def load(self, lock=False):
        '''Open qubes.xml

        :throws EnvironmentError: failure on parsing store
        :throws xml.parsers.expat.ExpatError: failure on parsing store
        :raises lxml.etree.XMLSyntaxError: on syntax error in qubes.xml
        '''

        fh = self._acquire_lock()
        self.xml = lxml.etree.parse(fh)

        # stage 1: load labels and pools
        for node in self.xml.xpath('./labels/label'):
            label = qubes.Label.fromxml(node)
            self.labels[label.index] = label

        for node in self.xml.xpath('./pools/pool'):
            name = node.get('name')
            assert name, "Pool name '%s' is invalid " % name
            try:
                self.pools[name] = self._get_pool(**node.attrib)
            except qubes.exc.QubesException as e:
                self.log.error(str(e))

        # stage 2: load VMs
        for node in self.xml.xpath('./domains/domain'):
            # pylint: disable=no-member
            cls = self.get_vm_class(node.get('class'))
            vm = cls(self, node)
            vm.load_properties(load_stage=2)
            vm.init_log()
            self.domains.add(vm, _enable_events=False)

        if 0 not in self.domains:
            self.domains.add(
                qubes.vm.adminvm.AdminVM(self, None, qid=0, name='dom0'),
                _enable_events=False)

        # stage 3: load global properties
        self.load_properties(load_stage=3)

        # stage 4: fill all remaining VM properties
        for vm in self.domains:
            vm.load_properties(load_stage=4)
            vm.load_extras()

        # stage 5: misc fixups

        self.property_require('default_fw_netvm', allow_none=True)
        self.property_require('default_netvm', allow_none=True)
        self.property_require('default_template')
        self.property_require('clockvm', allow_none=True)
        self.property_require('updatevm', allow_none=True)

        # Disable ntpd in ClockVM - to not conflict with ntpdate (both are
        # using 123/udp port)
        if hasattr(self, 'clockvm') and self.clockvm is not None:
            if self.clockvm.features.get('service.ntpd', False):
                self.log.warning(
                    'VM set as clockvm (%r) has enabled \'ntpd\' service! '
                    'Expect failure when syncing time in dom0.',
                    self.clockvm)
            else:
                self.clockvm.features['service.ntpd'] = ''

        for vm in self.domains:
            vm.events_enabled = True
            vm.fire_event('domain-load')

        # get a file timestamp (before closing it - still holding the lock!),
        #  to detect whether anyone else have modified it in the meantime
        self.__load_timestamp = os.path.getmtime(self._store)

        if not lock:
            self._release_lock()


    def __xml__(self):
        element = lxml.etree.Element('qubes')

        element.append(self.xml_labels())

        pools_xml = lxml.etree.Element('pools')
        for pool in self.pools.values():
            xml = pool.__xml__()
            if xml is not None:
                pools_xml.append(xml)

        element.append(pools_xml)

        element.append(self.xml_properties())

        domains = lxml.etree.Element('domains')
        for vm in self.domains:
            domains.append(vm.__xml__())
        element.append(domains)

        return element


    def save(self, lock=True):
        '''Save all data to qubes.xml

        There are several problems with saving :file:`qubes.xml` which must be
        mitigated:

        - Running out of disk space. No space left should not result in empty
          file. This is done by writing to temporary file and then renaming.
        - Attempts to write two or more files concurrently. This is done by
          sophisticated locking.

        :param bool lock: keep file locked after saving
        :throws EnvironmentError: failure on saving
        '''

        if not self.__locked_fh:
            self._acquire_lock(for_save=True)

        fh_new = tempfile.NamedTemporaryFile(
            prefix=self._store, delete=False)
        lxml.etree.ElementTree(self.__xml__()).write(
            fh_new, encoding='utf-8', pretty_print=True)
        fh_new.flush()
        try:
            os.chown(fh_new.name, -1, grp.getgrnam('qubes').gr_gid)
            os.chmod(fh_new.name, 0o660)
        except KeyError:  # group 'qubes' not found
            # don't change mode if no 'qubes' group in the system
            pass
        os.rename(fh_new.name, self._store)

        # update stored mtime, in case of multiple save() calls without
        # loading qubes.xml again
        self.__load_timestamp = os.path.getmtime(self._store)

        # this releases lock for all other processes,
        # but they should instantly block on the new descriptor
        self.__locked_fh.close()
        self.__locked_fh = fh_new

        if not lock:
            self._release_lock()


    def _acquire_lock(self, for_save=False):
        assert self.__locked_fh is None, 'double lock'

        while True:
            try:
                fd = os.open(self._store,
                    os.O_RDWR | (os.O_CREAT * int(for_save)))
            except OSError as e:
                if not for_save and e.errno == errno.ENOENT:
                    raise qubes.exc.QubesException(
                        'Qubes XML store {!r} is missing; '
                        'use qubes-create tool'.format(self._store))
                raise

            # While we were waiting for lock, someone could have unlink()ed
            # (or rename()d) our file out of the filesystem. We have to
            # ensure we got lock on something linked to filesystem.
            # If not, try again.
            if os.fstat(fd) != os.stat(self._store):
                os.close(fd)
                continue

            if self.__load_timestamp and \
                    os.path.getmtime(self._store) != self.__load_timestamp:
                os.close(fd)
                raise qubes.exc.QubesException(
                    'Someone else modified qubes.xml in the meantime')

            break

        if os.name == 'posix':
            fcntl.lockf(fd, fcntl.LOCK_EX)
        elif os.name == 'nt':
            # pylint: disable=protected-access
            overlapped = pywintypes.OVERLAPPED()
            win32file.LockFileEx(
                win32file._get_osfhandle(fd),
                win32con.LOCKFILE_EXCLUSIVE_LOCK, 0, -0x10000, overlapped)

        self.__locked_fh = os.fdopen(fd, 'r+b')
        return self.__locked_fh


    def _release_lock(self):
        assert self.__locked_fh is not None, 'double release'

        # intentionally do not call explicit unlock to not unlock the file
        # before all buffers are flushed
        self.__locked_fh.close()
        self.__locked_fh = None


    def load_initial_values(self):
        self.labels = {
            1: qubes.Label(1, '0xcc0000', 'red'),
            2: qubes.Label(2, '0xf57900', 'orange'),
            3: qubes.Label(3, '0xedd400', 'yellow'),
            4: qubes.Label(4, '0x73d216', 'green'),
            5: qubes.Label(5, '0x555753', 'gray'),
            6: qubes.Label(6, '0x3465a4', 'blue'),
            7: qubes.Label(7, '0x75507b', 'purple'),
            8: qubes.Label(8, '0x000000', 'black'),
        }
        assert max(self.labels.keys()) == qubes.config.max_default_label

        # check if the default LVM Thin pool qubes_dom0/pool00 exists
        if os.path.exists('/dev/mapper/qubes_dom0-pool00-tpool'):
            self.add_pool(volume_group='qubes_dom0', thin_pool='pool00',
                          name='lvm', driver='lvm_thin')
        # pool based on /var/lib/qubes will be created here:
        for name, config in qubes.config.defaults['pool_configs'].items():
            self.pools[name] = self._get_pool(**config)

        self.default_pool_kernel = 'linux-kernel'

        self.domains.add(
            qubes.vm.adminvm.AdminVM(self, None, label='black'))

    @classmethod
    def create_empty_store(cls, *args, **kwargs):
        self = cls(*args, load=False, **kwargs)
        if os.path.exists(self.store):
            raise qubes.exc.QubesException(
                '{} already exists, aborting'.format(self.store))
        self.load_initial_values()
        # TODO py3 get lock= as keyword-only arg
        self.save(kwargs.get('lock'))

        return self


    def xml_labels(self):
        '''Serialise labels

        :rtype: lxml.etree._Element
        '''

        labels = lxml.etree.Element('labels')
        for label in sorted(self.labels.values(), key=lambda labl: labl.index):
            labels.append(label.__xml__())
        return labels

    @staticmethod
    def get_vm_class(clsname):
        '''Find the class for a domain.

        Classes are registered as setuptools' entry points in ``qubes.vm``
        group. Any package may supply their own classes.

        :param str clsname: name of the class
        :return type: class
        '''

        try:
            return qubes.utils.get_entry_point_one(
                qubes.vm.VM_ENTRY_POINT, clsname)
        except KeyError:
            raise qubes.exc.QubesException(
                'no such VM class: {!r}'.format(clsname))
        # don't catch TypeError

    def add_new_vm(self, cls, qid=None, **kwargs):
        '''Add new Virtual Machine to collection

        '''

        if qid is None:
            qid = self.domains.get_new_unused_qid()

        if isinstance(cls, str):
            cls = self.get_vm_class(cls)
        # handle default template; specifically allow template=None (do not
        # override it with default template)
        if 'template' not in kwargs and hasattr(cls, 'template'):
            kwargs['template'] = self.default_template
        elif 'template' in kwargs and isinstance(kwargs['template'], str):
            kwargs['template'] = self.domains[kwargs['template']]

        return self.domains.add(cls(self, None, qid=qid, **kwargs))

    def get_label(self, label):
        '''Get label as identified by index or name

        :throws KeyError: when label is not found
        '''

        # first search for index, verbatim
        try:
            return self.labels[label]
        except KeyError:
            pass

        # then search for name
        for i in self.labels.values():
            if i.name == label:
                return i

        # last call, if label is a number represented as str, search in indices
        try:
            return self.labels[int(label)]
        except (KeyError, ValueError):
            pass

        raise KeyError(label)

    def add_pool(self, name, **kwargs):
        """ Add a storage pool to config."""

        if name in self.pools.keys():
            raise qubes.exc.QubesException('pool named %s already exists \n' %
                                           name)

        kwargs['name'] = name
        pool = self._get_pool(**kwargs)
        pool.setup()
        self.pools[name] = pool
        return pool

    def remove_pool(self, name):
        """ Remove a storage pool from config file.  """
        try:
            pool = self.pools[name]
            del self.pools[name]
            pool.destroy()
        except KeyError:
            return


    def get_pool(self, pool):
        '''  Returns a :py:class:`qubes.storage.Pool` instance '''
        if isinstance(pool, qubes.storage.Pool):
            return pool
        try:
            return self.pools[pool]
        except KeyError:
            raise qubes.exc.QubesException('Unknown storage pool ' + pool)

    @staticmethod
    def _get_pool(**kwargs):
        try:
            name = kwargs['name']
            assert name, 'Name needs to be an non empty string'
        except KeyError:
            raise qubes.exc.QubesException('No pool name for pool')

        try:
            driver = kwargs['driver']
        except KeyError:
            raise qubes.exc.QubesException('No driver specified for pool ' +
                                           name)
        try:
            klass = qubes.utils.get_entry_point_one(
                qubes.storage.STORAGE_ENTRY_POINT, driver)
            del kwargs['driver']
            return klass(**kwargs)
        except KeyError:
            raise qubes.exc.QubesException('No driver %s for pool %s' %
                                           (driver, name))

    @qubes.events.handler('domain-pre-delete')
    def on_domain_pre_deleted(self, event, vm):
        # pylint: disable=unused-argument
        if isinstance(vm, qubes.vm.templatevm.TemplateVM):
            appvms = self.domains.get_vms_based_on(vm)
            if appvms:
                raise qubes.exc.QubesException(
                    'Cannot remove template that has dependent AppVMs. '
                    'Affected are: {}'.format(', '.join(
                        appvm.name for appvm in sorted(appvms))))


    @qubes.events.handler('domain-delete')
    def on_domain_deleted(self, event, vm):
        # pylint: disable=unused-argument
        for propname in (
                'default_netvm',
                'default_fw_netvm',
                'clockvm',
                'updatevm',
                'default_template',
                ):
            try:
                if getattr(self, propname) == vm:
                    delattr(self, propname)
            except AttributeError:
                pass


    @qubes.events.handler('property-pre-set:clockvm')
    def on_property_pre_set_clockvm(self, event, name, newvalue, oldvalue=None):
        # pylint: disable=unused-argument,no-self-use
        if newvalue is None:
            return
        if newvalue.features.get('service.ntpd', False):
            raise qubes.exc.QubesVMError(newvalue,
                'Cannot set {!r} as {!r} since it has ntpd enabled.'.format(
                    newvalue.name, name))
        else:
            newvalue.features['service.ntpd'] = ''


    @qubes.events.handler(
        'property-pre-set:default_netvm',
        'property-pre-set:default_fw_netvm')
    def on_property_pre_set_default_netvm(self, event, name, newvalue,
            oldvalue=None):
        # pylint: disable=unused-argument,invalid-name
        if newvalue is not None and oldvalue is not None \
                and oldvalue.is_running() and not newvalue.is_running() \
                and self.domains.get_vms_connected_to(oldvalue):
            raise qubes.exc.QubesVMNotRunningError(newvalue,
                'Cannot change {!r} to domain that '
                'is not running ({!r}).'.format(name, newvalue.name))


    @qubes.events.handler('property-set:default_fw_netvm')
    def on_property_set_default_fw_netvm(self, event, name, newvalue,
            oldvalue=None):
        # pylint: disable=unused-argument,invalid-name
        for vm in self.domains:
            if not vm.provides_network and vm.property_is_default('netvm'):
                # fire property-del:netvm as it is responsible for resetting
                # netvm to it's default value
                vm.fire_event('property-del:netvm',
                    name='netvm', newvalue=newvalue, oldvalue=oldvalue)


    @qubes.events.handler('property-set:default_netvm')
    def on_property_set_default_netvm(self, event, name, newvalue,
            oldvalue=None):
        # pylint: disable=unused-argument
        for vm in self.domains:
            if hasattr(vm, 'netvm') and vm.property_is_default('netvm'):
                # fire property-del:netvm as it is responsible for resetting
                # netvm to it's default value
                vm.fire_event('property-del:netvm',
                    name='netvm', oldvalue=oldvalue)
