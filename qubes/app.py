#
# The Qubes OS Project, https://www.qubes-os.org/
#
# Copyright (C) 2010-2015  Joanna Rutkowska <joanna@invisiblethingslab.com>
# Copyright (C) 2011-2015  Marek Marczykowski-Górecki
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

import asyncio
import collections.abc
import copy
import functools
import grp
import itertools
import logging
import os
import random
import sys
import time
import traceback
import uuid
from contextlib import suppress

import jinja2
import libvirt
import lxml.etree

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
import qubes.storage.reflink
import qubes.vm
import qubes.vm.adminvm
import qubes.vm.qubesvm
import qubes.vm.templatevm

# pylint: enable=wrong-import-position


class VirDomainWrapper:
    # pylint: disable=too-few-public-methods

    def __init__(self, connection, vm):
        self._connection = connection
        self._vm = vm

    def _reconnect_if_dead(self):
        try:
            is_dead = not self._vm.connect().isAlive()
        except libvirt.libvirtError as ex:
            if ex.get_error_code() == libvirt.VIR_ERR_INVALID_CONN:
                # connection to libvirt was re-established in the meantime
                is_dead = True
            else:
                raise
        if is_dead:
            # pylint: disable=protected-access
            self._connection._reconnect_if_dead()
            self._vm = self._connection._conn.lookupByUUID(self._vm.UUID())
        return is_dead

    def __getattr__(self, attrname):
        attr = getattr(self._vm, attrname)
        if not isinstance(attr, collections.abc.Callable):
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


class VirConnectWrapper:
    # pylint: disable=too-few-public-methods

    def __init__(self, uri, reconnect_cb=None):
        self._conn = libvirt.open(uri)
        self._reconnect_cb = reconnect_cb

    def _reconnect_if_dead(self):
        is_dead = not self._conn.isAlive()
        if is_dead:
            uri = self._conn.getURI()
            old_conn = self._conn
            self._conn = libvirt.open(uri)
            if callable(self._reconnect_cb):
                self._reconnect_cb(old_conn)
            old_conn.close()
        return is_dead

    def _wrap_domain(self, ret):
        if isinstance(ret, libvirt.virDomain):
            ret = VirDomainWrapper(self, ret)
        return ret

    def __getattr__(self, attrname):
        attr = getattr(self._conn, attrname)
        if not isinstance(attr, collections.abc.Callable):
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


class VMMConnection:
    """Connection to Virtual Machine Manager (libvirt)"""

    def __init__(self, offline_mode=None, libvirt_reconnect_cb=None):
        """

        :param offline_mode: enable/disable offline mode; default is to
        enable when running in chroot as root, otherwise disable
        :param libvirt_reconnect_cb: callable to be called when connection to
        libvirt is re-established; the callback is called with old connection
        as argument
        """
        if offline_mode is None:
            offline_mode = bool(os.getuid() == 0 and
                                os.stat('/') != os.stat('/proc/1/root/.'))
        self._offline_mode = offline_mode
        self._libvirt_reconnect_cb = libvirt_reconnect_cb

        self._libvirt_conn = None
        self._xs = None
        self._xc = None

    @property
    def offline_mode(self):
        """Check or enable offline mode (do not actually connect to vmm)"""
        return self._offline_mode

    def _libvirt_error_handler(self, ctx, error):
        pass

    def init_vmm_connection(self):
        """Initialise connection

        This method is automatically called when getting"""
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
            qubes.config.defaults['libvirt_uri'],
            reconnect_cb=self._libvirt_reconnect_cb)
        libvirt.registerErrorHandler(self._libvirt_error_handler, None)

    @property
    def libvirt_conn(self):
        """Connection to libvirt"""
        self.init_vmm_connection()
        return self._libvirt_conn

    @property
    def xs(self):
        """Connection to Xen Store

        This property is available only when running on Xen.
        """

        # XXX what about the case when we run under KVM,
        # but xen modules are importable?
        if 'xen.lowlevel.xs' not in sys.modules:
            raise AttributeError(
                'xs object is available under Xen hypervisor only')

        self.init_vmm_connection()
        return self._xs

    @property
    def xc(self):
        """Connection to Xen

        This property is available only when running on Xen.
        """

        # XXX what about the case when we run under KVM,
        # but xen modules are importable?
        if 'xen.lowlevel.xc' not in sys.modules:
            raise AttributeError(
                'xc object is available under Xen hypervisor only')

        self.init_vmm_connection()
        return self._xc

    def close(self):
        libvirt.registerErrorHandler(None, None)
        if self._xs:
            self._xs.close()
            self._xs = None
        if self._libvirt_conn:
            self._libvirt_conn.close()
            self._libvirt_conn = None
        self._xc = None  # and pray it will get garbage-collected


class QubesHost:
    """Basic information about host machine

    :param qubes.Qubes app: Qubes application context (must have \
        :py:attr:`Qubes.vmm` attribute defined)
    """

    def __init__(self, app):
        self.app = app
        self._no_cpus = None
        self._total_mem = None
        self._physinfo = None
        self._cpu_family = None
        self._cpu_model = None

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
        with suppress(NotImplementedError):
            self.app.log.debug('QubesHost: xen_free_memory={}'.format(
                self.get_free_xen_memory()))

    @property
    def memory_total(self):
        """Total memory, in kbytes"""

        if self.app.vmm.offline_mode:
            return 2 ** 64 - 1
        self._fetch()
        return self._total_mem

    @property
    def no_cpus(self):
        """Number of CPUs"""

        if self.app.vmm.offline_mode:
            return 42

        self._fetch()
        return self._no_cpus

    @property
    def cpu_family_model(self):
        """Get CPU family and model"""
        if self._cpu_family is None or self._cpu_model is None:
            family = None
            model = None
            with open('/proc/cpuinfo', encoding='ascii') as cpuinfo:
                for line in cpuinfo.readlines():
                    line = line.strip()
                    if not line:
                        # take info from the first core
                        break
                    field, value = line.split(':', 1)
                    if field.strip() == 'model':
                        model = int(value.strip())
                    elif field.strip() == 'cpu family':
                        family = int(value.strip())
            self._cpu_family = family
            self._cpu_model = model
        return self._cpu_family, self._cpu_model

    def get_free_xen_memory(self):
        """Get free memory from Xen's physinfo.

        :raises NotImplementedError: when not under Xen
        """
        try:
            self._physinfo = self.app.vmm.xc.physinfo()
        except AttributeError:
            raise NotImplementedError('This function requires Xen hypervisor')
        return int(self._physinfo['free_memory'])

    def is_iommu_supported(self):
        """Check if IOMMU is supported on this platform"""
        if self._physinfo is None:
            try:
                self._physinfo = self.app.vmm.xc.physinfo()
            except AttributeError:
                raise NotImplementedError(
                    'This function requires Xen hypervisor')
        return 'hvm_directio' in self._physinfo['virt_caps']

    def get_vm_stats(self, previous_time=None, previous=None, only_vm=None):
        """Measure cpu usage for all domains at once.

        If previous measurements are given, CPU usage will be given in
        percents of time. Otherwise only absolute value (seconds).

        Return a tuple of (measurements_time, measurements),
        where measurements is a dictionary with key: domid, value: dict:
         - cpu_time - absolute CPU usage (seconds since its startup)
         - cpu_usage_raw - CPU usage in %
         - cpu_usage - CPU usage in % (normalized to number of vcpus)
         - memory_kb - current memory assigned, in kb

        This function requires Xen hypervisor.

        ..warning:

           This function may return info about implementation-specific VMs,
           like stubdomains for HVM

        :param previous: previous measurement
        :param previous_time: time of previous measurement
        :param only_vm: get measurements only for this VM

        :raises NotImplementedError: when not under Xen
        """

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
            current[domid]['cpu_time'] = int(vm['cpu_time'])
            vcpus = max(vm['online_vcpus'], 1)
            if domid in previous:
                current[domid]['cpu_usage_raw'] = int(
                    (current[domid]['cpu_time'] - previous[domid]['cpu_time'])
                    / 1000 ** 3 * 100 / (current_time - previous_time))
                if current[domid]['cpu_usage_raw'] < 0:
                    # VM has been rebooted
                    current[domid]['cpu_usage_raw'] = 0
            else:
                current[domid]['cpu_usage_raw'] = 0
            current[domid]['cpu_usage'] = \
                int(current[domid]['cpu_usage_raw'] / vcpus)

        return current_time, current


class VMCollection:
    """A collection of Qubes VMs

    VMCollection supports ``in`` operator. You may test for ``qid``, ``name``
    and whole VM object's presence.

    Iterating over VMCollection will yield machine objects.
    """

    def __init__(self, app):
        self.app = app
        self._dict = {}

    def close(self):
        del self.app
        self._dict.clear()
        del self._dict

    def __repr__(self):
        return '<{} {!r}>'.format(
            self.__class__.__name__, list(sorted(self.keys())))

    def items(self):
        """Iterate over ``(qid, vm)`` pairs"""
        for qid in self.qids():
            yield (qid, self[qid])

    def qids(self):
        """Iterate over all qids

        qids are sorted by numerical order.
        """

        return iter(sorted(self._dict.keys()))

    keys = qids

    def names(self):
        """Iterate over all names

        names are sorted by lexical order.
        """

        return iter(sorted(vm.name for vm in self._dict.values()))

    def vms(self):
        """Iterate over all machines

        vms are sorted by qid.
        """

        return iter(sorted(self._dict.values()))

    __iter__ = vms
    values = vms

    def add(self, value, _enable_events=True):
        """Add VM to collection

        :param qubes.vm.BaseVM value: VM to add
        :param _enable_events:
        :raises TypeError: when value is of wrong type
        :raises ValueError: when there is already VM which has equal ``qid``
        """

        # this violates duck typing, but is needed
        # for VMProperty to function correctly
        if not isinstance(value, qubes.vm.BaseVM):
            raise TypeError('{} holds only BaseVM instances'.format(
                self.__class__.__name__))

        if value.qid in self:
            raise ValueError('This collection already holds VM that has '
                             'qid={!r} ({!r})'.format(value.qid,
                                                      self[value.qid]))
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
            if vm.libvirt_domain:
                vm.libvirt_domain.undefine()
            # pylint: disable=protected-access
            vm._libvirt_domain = None
        except libvirt.libvirtError as e:
            if e.get_error_code() == libvirt.VIR_ERR_NO_DOMAIN:
                # already undefined
                pass
        del self._dict[vm.qid]
        self.app.fire_event('domain-delete', vm=vm)

    def __contains__(self, key):
        return any((key in (vm, vm.qid, vm.name))
                   for vm in self)

    def __len__(self):
        return len(self._dict)

    def get_vms_based_on(self, template):
        template = self[template]
        return set(vm for vm in self
                   if hasattr(vm, 'template') and vm.template == template)

    def get_vms_connected_to(self, netvm):
        new_vms = {self[netvm]}
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

    def get_new_unused_dispid(self):
        for _ in range(int(qubes.config.max_dispid ** 0.5)):
            dispid = random.SystemRandom().randrange(qubes.config.max_dispid)
            if not any(getattr(vm, 'dispid', None) == dispid for vm in self):
                return dispid
        raise LookupError((
                              'https://xkcd.com/221/',
                              'http://dilbert.com/strip/2001-10-25')[
                              random.randint(0, 1)])


def _default_pool(app):
    """ Default storage pool.

    1. If there is one named 'default', use it.
    2. Check if root fs is on LVM thin - use that
    3. Look for file(-reflink)-based pool pointing to /var/lib/qubes
    4. Fail
    """
    if 'default' in app.pools:
        return app.pools['default']

    if 'DEFAULT_LVM_POOL' in os.environ:
        thin_pool = os.environ['DEFAULT_LVM_POOL']
        for pool in app.pools.values():
            if pool.config.get('driver', None) != 'lvm_thin':
                continue
            if pool.config['thin_pool'] == thin_pool:
                return pool
    # no DEFAULT_LVM_POOL, or pool not defined
    root_volume_group, root_thin_pool = \
        qubes.storage.DirectoryThinPool.thin_pool('/')
    if root_thin_pool:
        for pool in app.pools.values():
            if pool.config.get('driver', None) != 'lvm_thin':
                continue
            if (pool.config['volume_group'] == root_volume_group and
                    pool.config['thin_pool'] == root_thin_pool):
                return pool

    # not a thin volume? look for file pools
    for pool in app.pools.values():
        if pool.config.get('driver', None) not in ('file', 'file-reflink'):
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


def _setter_default_netvm(app, prop, value):
    # skip netvm loop check while loading qubes.xml, to avoid tricky loading
    # order
    if not app.events_enabled:
        return value

    if value is None:
        return value
    # forbid setting to a value that would result in netvm loop
    for vm in app.domains:
        if not hasattr(vm, 'netvm'):
            continue
        if not vm.property_is_default('netvm'):
            continue
        if value == vm \
                or value in app.domains.get_vms_connected_to(vm):
            raise qubes.exc.QubesPropertyValueError(
                app, prop, value, 'Network loop on \'{!s}\''.format(vm))
    return value


class Qubes(qubes.PropertyHolder):
    """Main Qubes application

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

        .. event:: pool-add (subject, event, pool)

            When storage pool is added.

            Handler for this event may be asynchronous.

            :param subject: Event emitter
            :param event: Event name (``'pool-add'``)
            :param pool: Pool object

        .. event:: pool-pre-delete (subject, event, pool)

            When pool is deleted. Pool is still contained within app.pools
            dictionary. You may prevent removal by raising an exception.

            Handler for this event may be asynchronous.

            :param subject: Event emitter
            :param event: Event name (``'pool-pre-delete'``)
            :param pool: Pool object

        .. event:: pool-delete (subject, event, pool)

            When storage pool is deleted. The pool is already removed at this
            point.

            Handler for this event may be asynchronous.

            :param subject: Event emitter
            :param event: Event name (``'pool-delete'``)
            :param pool: Pool object

        .. event:: qubes-close (subject, event)

            Fired when this Qubes() object instance is going to be closed
            and destroyed. In practice it is called only during tests, to
            cleanup objects from one test, before another.
            It is _not_ called when qubesd daemon is stopped.

            :param subject: Event emitter
            :param event: Event name (``'qubes-close'``)


    Methods and attributes:
    """
    default_guivm = qubes.VMProperty(
        'default_guivm',
        load_stage=3,
        default=lambda app: app.domains['dom0'], allow_none=True,
        doc='Default GuiVM for VMs.')

    default_audiovm = qubes.VMProperty(
        'default_audiovm',
        load_stage=3,
        default=lambda app: app.domains['dom0'], allow_none=True,
        doc='Default AudioVM for VMs.')

    default_netvm = qubes.VMProperty(
        'default_netvm',
        load_stage=3,
        default=None, allow_none=True,
        setter=_setter_default_netvm,
        doc="""Default NetVM for AppVMs. Initial state is `None`, which means
        that AppVMs are not connected to the Internet.""")
    default_template = qubes.VMProperty(
        'default_template', load_stage=3,
        vmclass=qubes.vm.templatevm.TemplateVM,
        doc='Default template for new AppVMs',
        allow_none=True)
    updatevm = qubes.VMProperty(
        'updatevm', load_stage=3,
        default=None, allow_none=True,
        doc="""Which VM to use as `yum` proxy for updating AdminVM and
        TemplateVMs""")
    clockvm = qubes.VMProperty(
        'clockvm', load_stage=3,
        default=None, allow_none=True,
        doc='Which VM to use as NTP proxy for updating '
            'AdminVM')
    default_kernel = qubes.property(
        'default_kernel', load_stage=3,
        doc='Which kernel to use when not overriden in VM')
    default_dispvm = qubes.VMProperty(
        'default_dispvm',
        load_stage=3,
        default=None,
        doc='Default DispVM base for service calls',
        allow_none=True)

    management_dispvm = qubes.VMProperty(
        'management_dispvm',
        load_stage=3,
        default=None,
        doc='Default DispVM base for managing VMs',
        allow_none=True)

    default_pool = qubes.property(
        'default_pool',
        load_stage=3,
        default=_default_pool,
        setter=_setter_pool,
        doc='Default storage pool')

    default_pool_private = qubes.property(
        'default_pool_private',
        load_stage=3,
        default=lambda app: app.default_pool,
        setter=_setter_pool,
        doc='Default storage pool for private volumes')

    default_pool_root = qubes.property(
        'default_pool_root',
        load_stage=3,
        default=lambda app: app.default_pool,
        setter=_setter_pool,
        doc='Default storage pool for root volumes')

    default_pool_volatile = qubes.property(
        'default_pool_volatile',
        load_stage=3,
        default=lambda app: app.default_pool,
        setter=_setter_pool,
        doc='Default storage pool for volatile volumes')

    default_pool_kernel = qubes.property(
        'default_pool_kernel',
        load_stage=3,
        default=lambda app: app.default_pool,
        setter=_setter_pool,
        doc='Default storage pool for kernel volumes')

    default_qrexec_timeout = qubes.property(
        'default_qrexec_timeout',
        load_stage=3,
        default=60,
        type=int,
        doc="""Default time in seconds after which qrexec connection attempt
        is deemed failed""")

    default_shutdown_timeout = qubes.property(
        'default_shutdown_timeout',
        load_stage=3,
        default=60,
        type=int,
        doc="""Default time in seconds for VM shutdown to complete""")

    stats_interval = qubes.property(
        'stats_interval',
        load_stage=3,
        default=3,
        type=int,
        doc='Interval in seconds for VM stats reporting (memory, CPU usage)')

    # TODO #1637 #892
    check_updates_vm = qubes.property(
        'check_updates_vm',
        type=bool,
        setter=qubes.property.bool,
        load_stage=3,
        default=True,
        doc='Check for updates inside qubes')

    def __init__(self, store=None, load=True, offline_mode=None, lock=False,
                 **kwargs):
        #: logger instance for logging global messages
        self.log = logging.getLogger('app')
        self.log.debug('init() -> %#x', id(self))
        self.log.debug('stack:')
        for frame in traceback.extract_stack():
            self.log.debug('%s', frame)

        self._extensions = qubes.ext.get_extensions()

        #: collection of all VMs managed by this Qubes instance
        self.domains = VMCollection(self)

        #: collection of all available labels for VMs
        self.labels = {}

        #: collection of all pools
        self.pools = {}

        #: Connection to VMM
        self.vmm = VMMConnection(
            offline_mode=offline_mode,
            libvirt_reconnect_cb=self.register_event_handlers)

        #: Information about host system
        self.host = QubesHost(self)

        if store is not None:
            self._store = store
        else:
            self._store = os.environ.get('QUBES_XML_PATH',
                                         os.path.join(
                                             qubes.config.qubes_base_dir,
                                             qubes.config.system_path[
                                                 'qubes_store_filename']))

        super().__init__(xml=None, **kwargs)

        self.__load_timestamp = None
        self.__locked_fh = None
        self._domain_event_callback_id = None

        #: jinja2 environment for libvirt XML templates
        self.env = jinja2.Environment(
            loader=jinja2.FileSystemLoader([
                '/etc/qubes/templates',
                '/usr/share/qubes/templates',
            ]),
            undefined=jinja2.StrictUndefined,
            autoescape=True)

        if load:
            self.load(lock=lock)

        self.events_enabled = True

    @property
    def store(self):
        return self._store

    def _migrate_global_properties(self):
        """Migrate renamed/dropped properties"""
        if self.xml is None:
            return

        # drop default_fw_netvm
        node_default_fw_netvm = self.xml.find(
            './properties/property[@name=\'default_fw_netvm\']')
        if node_default_fw_netvm is not None:
            node_default_netvm = self.xml.find(
                './properties/property[@name=\'default_netvm\']')
            try:
                default_fw_netvm = self.domains[node_default_fw_netvm.text]
                if node_default_netvm is None:
                    default_netvm = None
                else:
                    default_netvm = self.domains[node_default_netvm.text]
                if default_netvm != default_fw_netvm:
                    for vm in self.domains:
                        if not hasattr(vm, 'netvm'):
                            continue
                        if not getattr(vm, 'provides_network', False):
                            continue
                        node_netvm = vm.xml.find(
                            './properties/property[@name=\'netvm\']')
                        if node_netvm is not None:
                            # non-default netvm
                            continue
                        # this will unfortunately break "being default"
                        # property state, but the alternative (changing
                        # value behind user's back) is worse
                        properties = vm.xml.find('./properties')
                        element = lxml.etree.Element('property',
                                                     name='netvm')
                        element.text = default_fw_netvm.name
                        # manipulate xml directly, before loading netvm
                        # property, to avoid hitting netvm loop detection
                        properties.append(element)
            except KeyError:
                # if default_fw_netvm was set to invalid value, simply
                # drop it
                pass
            node_default_fw_netvm.getparent().remove(node_default_fw_netvm)

    def _migrate_labels(self):
        """Migrate changed labels"""
        if self.xml is None:
            return

        # fix grey being green
        grey_label = self.xml.find('./labels/label[@color=\'0x555753\']')
        if grey_label is not None:
            grey_label.set('color', '0x555555')

    def load(self, lock=False):
        """Open qubes.xml

        :throws EnvironmentError: failure on parsing store
        :throws xml.parsers.expat.ExpatError: failure on parsing store
        :raises lxml.etree.XMLSyntaxError: on syntax error in qubes.xml
        """

        fh = self._acquire_lock()
        self.xml = lxml.etree.parse(fh)

        self._migrate_labels()

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
                qubes.vm.adminvm.AdminVM(self, None),
                _enable_events=False)

        self._migrate_global_properties()

        # stage 3: load global properties
        self.load_properties(load_stage=3)

        # stage 4: fill all remaining VM properties
        for vm in self.domains:
            vm.load_properties(load_stage=4)
            vm.load_extras()

        # stage 5: misc fixups

        self.property_require('default_guivm', allow_none=True)
        self.property_require('default_netvm', allow_none=True)
        self.property_require('default_template', allow_none=True)
        self.property_require('clockvm', allow_none=True)
        self.property_require('updatevm', allow_none=True)

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

    def __str__(self):
        return type(self).__name__

    def save(self, lock=True):
        """Save all data to qubes.xml

        There are several problems with saving :file:`qubes.xml` which must be
        mitigated:

        - Running out of disk space. No space left should not result in empty
          file. This is done by writing to temporary file and then renaming.
        - Attempts to write two or more files concurrently. This is done by
          sophisticated locking.

        :param bool lock: keep file locked after saving
        :throws EnvironmentError: failure on saving
        """

        if not self.__locked_fh:
            self._acquire_lock(for_save=True)

        with qubes.utils.replace_file(self._store, permissions=0o660,
                                      close_on_success=False) as fh_new:
            lxml.etree.ElementTree(self.__xml__()).write(
                fh_new, encoding='utf-8', pretty_print=True)
            with suppress(KeyError):  # group not found
                os.fchown(fh_new.fileno(), -1, grp.getgrnam('qubes').gr_gid)

        # update stored mtime, in case of multiple save() calls without
        # loading qubes.xml again
        self.__load_timestamp = os.path.getmtime(self._store)

        # this releases lock for all other processes,
        # but they should instantly block on the new descriptor
        self.__locked_fh.close()
        self.__locked_fh = fh_new

        if not lock:
            self._release_lock()

    def close(self):
        """Deconstruct the object and break circular references

        After calling this the object is unusable, not even for saving."""

        self.log.debug('close() <- %#x', id(self))
        for frame in traceback.extract_stack():
            self.log.debug('%s', frame)

        # let all the extension cleanup things
        self.fire_event('qubes-close')

        super().close()

        if self._domain_event_callback_id is not None:
            self.vmm.libvirt_conn.domainEventDeregisterAny(
                self._domain_event_callback_id)
            self._domain_event_callback_id = None

        # Only our Lord, The God Almighty, knows what references
        # are kept in extensions.
        # NOTE: this doesn't really delete extension objects - Extension class
        # saves reference to instance, and also various registered (class level)
        # event handlers do that too
        del self._extensions

        for vm in self.domains:
            vm.close()
        self.domains.close()
        del self.domains

        self.vmm.close()
        del self.vmm

        del self.host

        if self.__locked_fh:
            self._release_lock()

    def _acquire_lock(self, for_save=False):
        assert self.__locked_fh is None, 'double lock'

        while True:
            try:
                fd = os.open(self._store,
                             os.O_RDWR | (os.O_CREAT * int(for_save)))
            except FileNotFoundError:
                if not for_save:
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
            5: qubes.Label(5, '0x555555', 'gray'),
            6: qubes.Label(6, '0x3465a4', 'blue'),
            7: qubes.Label(7, '0x75507b', 'purple'),
            8: qubes.Label(8, '0x000000', 'black'),
        }
        assert max(self.labels.keys()) == qubes.config.max_default_label

        pool_configs = copy.deepcopy(qubes.config.defaults['pool_configs'])

        for name, config in pool_configs.items():
            if 'driver' not in config and 'dir_path' in config:
                config['driver'] = 'file'
                try:
                    os.makedirs(config['dir_path'], exist_ok=True)
                    if qubes.storage.reflink.is_supported(config['dir_path']):
                        config['driver'] = 'file-reflink'
                        config['setup_check'] = False  # don't check twice
                except PermissionError:  # looks like a testing environment
                    pass  # stay with 'file'
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
        """Serialise labels

        :rtype: lxml.etree._Element
        """

        labels = lxml.etree.Element('labels')
        for label in sorted(self.labels.values(), key=lambda labl: labl.index):
            labels.append(label.__xml__())
        return labels

    @staticmethod
    def get_vm_class(clsname):
        """Find the class for a domain.

        Classes are registered as setuptools' entry points in ``qubes.vm``
        group. Any package may supply their own classes.

        :param str clsname: name of the class
        :return type: class
        """

        try:
            return qubes.utils.get_entry_point_one(
                qubes.vm.VM_ENTRY_POINT, clsname)
        except KeyError:
            raise qubes.exc.QubesException(
                'no such VM class: {!r}'.format(clsname))
        # don't catch TypeError

    def add_new_vm(self, cls, qid=None, **kwargs):
        """Add new Virtual Machine to collection

        """

        if qid is None:
            qid = self.domains.get_new_unused_qid()

        if isinstance(cls, str):
            cls = self.get_vm_class(cls)
        # handle default template; specifically allow template=None (do not
        # override it with default template)
        if 'template' not in kwargs and hasattr(cls, 'template'):
            if cls == self.get_vm_class('DispVM'):
                kwargs['template'] = self.default_dispvm
            else:
                kwargs['template'] = self.default_template
            if kwargs['template'] is None:
                raise qubes.exc.QubesValueError(
                    'Template for the qube not specified, nor default '
                    'template set.')
        elif 'template' in kwargs and isinstance(kwargs['template'], str):
            kwargs['template'] = self.domains[kwargs['template']]

        return self.domains.add(cls(self, None, qid=qid, **kwargs))

    def get_label(self, label):
        """Get label as identified by index or name

        :throws KeyError: when label is not found
        """

        # first search for index, verbatim
        with suppress(KeyError):
            return self.labels[label]

        # then search for name
        for i in self.labels.values():
            if i.name == label:
                return i

        # last call, if label is a number represented as str, search in indices
        with suppress(KeyError, ValueError):
            return self.labels[int(label)]

        raise qubes.exc.QubesLabelNotFoundError(label)

    async def setup_pools(self):
        """ Run implementation specific setup for each storage pool. """
        await qubes.utils.void_coros_maybe(
            pool.setup() for pool in self.pools.values())

    async def add_pool(self, name, **kwargs):
        """ Add a storage pool to config."""

        if name in self.pools:
            raise qubes.exc.QubesException('pool named %s already exists \n' %
                                           name)

        kwargs['name'] = name
        pool = self._get_pool(**kwargs)
        await qubes.utils.coro_maybe(pool.setup())
        self.pools[name] = pool
        await self.fire_event_async('pool-add', pool=pool)
        return pool

    async def remove_pool(self, name):
        """ Remove a storage pool from config file.  """
        try:
            pool = self.pools[name]
            volumes = [(vm, volume) for vm in self.domains
                       for volume in vm.volumes.values()
                       if volume.pool is pool]
            if volumes:
                raise qubes.exc.QubesPoolInUseError(pool)
            prop_suffixes = ['', '_kernel', '_private', '_root', '_volatile']
            for suffix in prop_suffixes:
                if getattr(self, 'default_pool' + suffix, None) is pool:
                    raise qubes.exc.QubesPoolInUseError(
                        pool,
                        'Storage pool is in use: '
                        'set as {}'.format('default_pool' + suffix))
            await self.fire_event_async('pool-pre-delete',
                                             pre_event=True, pool=pool)
            del self.pools[name]
            await qubes.utils.coro_maybe(pool.destroy())
            await self.fire_event_async('pool-delete', pool=pool)
        except KeyError:
            return

    def get_pool(self, pool):
        """  Returns a :py:class:`qubes.storage.Pool` instance """
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

    async def stop_storage(self):
        """
        Stop the storage of all domains that are not running.
        """
        async def stop(i):
            async with i.startup_lock:
                if not i.is_running():
                    await i.storage.stop()
        future = tuple(asyncio.create_task(stop(i)) for i in self.domains
                       if i.klass != 'AdminVM')
        finished = ()
        while future:
            qubes.utils.systemd_extend_timeout()
            finished, future = await asyncio.wait(future, timeout=30)
            for i in finished:
                try:
                    await i
                except Exception:  # pylint: disable=broad-except
                    self.log.exception(
                        'Stopping storage for a qube raised an exception')

    def register_event_handlers(self, old_connection=None):
        """Register libvirt event handlers, which will translate libvirt
        events into qubes.events. This function should be called only in
        'qubesd' process and only when mainloop has been already set.
        """
        if old_connection:
            try:
                old_connection.domainEventDeregisterAny(
                    self._domain_event_callback_id)
            except libvirt.libvirtError:
                # the connection is probably in a bad state; but call the above
                # anyway to cleanup the client structures
                pass
        self._domain_event_callback_id = (
            self.vmm.libvirt_conn.domainEventRegisterAny(
                None,  # any domain
                libvirt.VIR_DOMAIN_EVENT_ID_LIFECYCLE,
                self._domain_event_callback,
                None))
        if old_connection:
            # If this is libvirt restart, check if ensure no shutdown events
            # were missed. on_libvirt_domain_stopped() can deal with duplicated
            # events.
            for vm in self.domains.values():
                if not vm.is_running():
                    vm.on_libvirt_domain_stopped()

    def _domain_event_callback(self, _conn, domain, event, _detail, _opaque):
        """Generic libvirt event handler (virConnectDomainEventCallback),
        translate libvirt event into qubes.events.
        """
        if not self.events_enabled:
            return

        try:
            vm = self.domains[domain.name()]
        except KeyError:
            # ignore events for unknown domains
            return

        if event == libvirt.VIR_DOMAIN_EVENT_STOPPED:
            vm.on_libvirt_domain_stopped()
        elif event == libvirt.VIR_DOMAIN_EVENT_SUSPENDED:
            try:
                vm.fire_event('domain-paused')
            except Exception:  # pylint: disable=broad-except
                self.log.exception(
                    'Uncaught exception from domain-paused handler '
                    'for domain %s', vm.name)
        elif event == libvirt.VIR_DOMAIN_EVENT_RESUMED:
            try:
                vm.fire_event('domain-unpaused')
            except Exception:  # pylint: disable=broad-except
                self.log.exception(
                    'Uncaught exception from domain-unpaused handler '
                    'for domain %s', vm.name)

    @qubes.events.handler('domain-pre-delete')
    def on_domain_pre_deleted(self, event, vm):
        # pylint: disable=unused-argument
        for obj in itertools.chain(self.domains, (self,)):
            if obj is vm:
                # allow removed VM to reference itself
                continue
            for prop in obj.property_list():
                with suppress(AttributeError):
                    if isinstance(prop, qubes.vm.VMProperty) and \
                            getattr(obj, prop.__name__) == vm:
                        self.log.error(
                            'Cannot remove %s, used by %s.%s',
                            vm, obj, prop.__name__)
                        raise qubes.exc.QubesVMInUseError(
                            vm,
                            'Domain is in use: {!r};'
                            "see 'journalctl -u qubesd -e' in dom0 for "
                            'details'.format(
                                vm.name))

        assignments = vm.get_provided_assignments()
        if assignments:
            desc = ', '.join(
                assignment.ident for assignment in assignments)
            raise qubes.exc.QubesVMInUseError(
                vm,
                'VM has devices attached persistently to other VMs: ' +
                desc)

    @qubes.events.handler('domain-delete')
    def on_domain_deleted(self, event, vm):
        # pylint: disable=unused-argument
        for propname in (
                'default_guivm'
                'default_netvm',
                'default_fw_netvm',
                'clockvm',
                'updatevm',
                'default_template',
        ):
            with suppress(AttributeError):
                if getattr(self, propname) == vm:
                    delattr(self, propname)

    @qubes.events.handler('property-pre-set:clockvm')
    def on_property_pre_set_clockvm(self, event, name, newvalue, oldvalue=None):
        # pylint: disable=unused-argument
        if newvalue is None:
            return
        if 'service.clocksync' not in newvalue.features:
            newvalue.features['service.clocksync'] = True

    @qubes.events.handler('property-set:clockvm')
    def on_property_set_clockvm(self, event, name, newvalue, oldvalue=None):
        # pylint: disable=unused-argument
        if oldvalue == newvalue:
            return
        if oldvalue and oldvalue.features.get('service.clocksync', False):
            del oldvalue.features['service.clocksync']

    @qubes.events.handler('property-pre-set:default_netvm')
    def on_property_pre_set_default_netvm(self, event, name, newvalue,
                                          oldvalue=None):
        # pylint: disable=unused-argument,invalid-name
        if newvalue is not None and oldvalue is not None \
                and oldvalue.is_running() and not newvalue.is_running() \
                and self.domains.get_vms_connected_to(oldvalue):
            raise qubes.exc.QubesVMNotRunningError(
                newvalue,
                'Cannot change {!r} to domain that '
                'is not running ({!r}).'.format(
                    name, newvalue.name))

    @qubes.events.handler('property-set:default_netvm')
    def on_property_set_default_netvm(self, event, name, newvalue,
                                      oldvalue=None):
        # pylint: disable=unused-argument
        for vm in self.domains:
            if hasattr(vm, 'provides_network') and not vm.provides_network and \
                    hasattr(vm, 'netvm') and vm.property_is_default('netvm'):
                # fire property-reset:netvm as it is responsible for resetting
                # netvm to it's default value
                vm.fire_event('property-reset:netvm',
                              name='netvm', oldvalue=oldvalue)

    @qubes.events.handler('property-set:default_dispvm')
    def on_property_set_default_dispvm(self, event, name, newvalue,
                                      oldvalue=None):
        # pylint: disable=unused-argument
        for vm in self.domains:
            if hasattr(vm, 'default_dispvm') and \
                    vm.property_is_default('default_dispvm'):
                # fire property-reset:default_dispvm as it is responsible for
                # resetting dispvm to it's default value
                vm.fire_event('property-reset:default_dispvm',
                              name='default_dispvm', oldvalue=oldvalue)
