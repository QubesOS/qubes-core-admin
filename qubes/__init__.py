#!/usr/bin/python2 -O
# -*- coding: utf-8 -*-

from __future__ import absolute_import

'''
Qubes OS

:copyright: © 2010-2014 Invisible Things Lab
'''

__author__ = 'Invisible Things Lab'
__license__ = 'GPLv2 or later'
__version__ = 'R3'

import ast
import atexit
import collections
import grp
import os
import os.path
import sys
import tempfile
import time
import warnings

import __builtin__

import lxml.etree
import xml.parsers.expat

import qubes.ext


if os.name == 'posix':
    import fcntl
elif os.name == 'nt':
    import win32con
    import win32file
    import pywintypes
else:
    raise RuntimeError, "Qubes works only on POSIX or WinNT systems"

import libvirt
try:
    import xen.lowlevel.xs
    import xen.lowlevel.xc
except ImportError:
    pass

#: FIXME documentation
MAX_QID = 253

#: FIXME documentation
MAX_NETID = 253


class QubesException(Exception):
    '''Exception that can be shown to the user'''
    pass

class VMMConnection(object):
    '''Connection to Virtual Machine Manager (libvirt)'''
    def __init__(self):
        self._libvirt_conn = None
        self._xs = None
        self._xc = None
        self._offline_mode = False

    @__builtin__.property
    def offline_mode(self):
        '''Check or enable offline mode (do not actually connect to vmm)'''
        return self._offline_mode

    @offline_mode.setter
    def offline_mode(self, value):
        if value and self._libvirt_conn is not None:
            raise QubesException("Cannot change offline mode while already connected")

        self._offline_mode = value

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
            raise QubesException("VMM operations disabled in offline mode")

        if 'xen.lowlevel.xs' in sys.modules:
            self._xs = xen.lowlevel.xs.xs()
        if 'xen.lowlevel.cs' in sys.modules:
            self._xc = xen.lowlevel.xc.xc()
        self._libvirt_conn = libvirt.open(defaults['libvirt_uri'])
        if self._libvirt_conn == None:
            raise QubesException("Failed connect to libvirt driver")
        libvirt.registerErrorHandler(self._libvirt_error_handler, None)
        atexit.register(self._libvirt_conn.close)

    @__builtin__.property
    def libvirt_conn(self):
        '''Connection to libvirt'''
        self.init_vmm_connection()
        return self._libvirt_conn

    @__builtin__.property
    def xs(self):
        '''Connection to Xen Store

        This property in available only when running on Xen.
        '''

        # XXX what about the case when we run under KVM, but xen modules are importable?
        if 'xen.lowlevel.xs' not in sys.modules:
            raise AttributeError('xs object is available under Xen hypervisor only')

        self.init_vmm_connection()
        return self._xs

    @__builtin__.property
    def xc(self):
        '''Connection to Xen

        This property in available only when running on Xen.
        '''

        # XXX what about the case when we run under KVM, but xen modules are importable?
        if 'xen.lowlevel.xc' not in sys.modules:
            raise AttributeError('xc object is available under Xen hypervisor only')

        self.init_vmm_connection()
        return self._xs


class QubesHost(object):
    '''Basic information about host machine

    :param qubes.Qubes app: Qubes application context (must have :py:attr:`Qubes.vmm` attribute defined)
    '''

    def __init__(self, app):
        self._app = app
        self._no_cpus = None


    def _fetch(self):
        if self._no_cpus is not None:
            return

        (model, memory, cpus, mhz, nodes, socket, cores, threads) = \
            self._app.vmm.libvirt_conn.getInfo()
        self._total_mem = long(memory)*1024
        self._no_cpus = cpus

        self.app.log.debug('QubesHost: no_cpus={} memory_total={}'.format(self.no_cpus, self.memory_total))
        try:
            self.app.log.debug('QubesHost: xen_free_memory={}'.format(self.get_free_xen_memory()))
        except NotImplementedError:
            pass


    @__builtin__.property
    def memory_total(self):
        '''Total memory, in bytes'''

        self._fetch()
        return self._total_mem


    @__builtin__.property
    def no_cpus(self):
        '''Number of CPUs'''

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
        return long(self._physinfo['free_memory'])


    def measure_cpu_usage(self, previous_time=None, previous=None,
            wait_time=1):
        '''Measure cpu usage for all domains at once.

        This function requires Xen hypervisor.

        .. versionchanged:: 3.0
            argument order to match return tuple

        :raises NotImplementedError: when not under Xen
        '''

        if previous is None:
            previous_time = time.time()
            previous = {}
            try:
                info = self._app.vmm.xc.domain_getinfo(0, qubes_max_qid)
            except AttributeError:
                raise NotImplementedError(
                    'This function requires Xen hypervisor')

            for vm in info:
                previous[vm['domid']] = {}
                previous[vm['domid']]['cpu_time'] = (
                        vm['cpu_time'] / vm['online_vcpus'])
                previous[vm['domid']]['cpu_usage'] = 0
            time.sleep(wait_time)

        current_time = time.time()
        current = {}
        try:
            info = self._app.vmm.xc.domain_getinfo(0, qubes_max_qid)
        except AttributeError:
            raise NotImplementedError(
                'This function requires Xen hypervisor')
        for vm in info:
            current[vm['domid']] = {}
            current[vm['domid']]['cpu_time'] = (
                    vm['cpu_time'] / max(vm['online_vcpus'], 1))
            if vm['domid'] in previous.keys():
                current[vm['domid']]['cpu_usage'] = (
                    float(current[vm['domid']]['cpu_time'] -
                        previous[vm['domid']]['cpu_time']) /
                    long(1000**3) / (current_time-previous_time) * 100)
                if current[vm['domid']]['cpu_usage'] < 0:
                    # VM has been rebooted
                    current[vm['domid']]['cpu_usage'] = 0
            else:
                current[vm['domid']]['cpu_usage'] = 0

        return (current_time, current)


class Label(object):
    '''Label definition for virtual machines

    Label specifies colour of the padlock displayed next to VM's name.
    When this is a :py:class:`qubes.vm.dispvm.DispVM`, padlock is overlayed
    with recycling pictogram.

    :param int index: numeric identificator of label
    :param str color: colour specification as in HTML (``#abcdef``)
    :param str name: label's name like "red" or "green"
    '''

    def __init__(self, index, color, name):
        #: numeric identificator of label
        self.index = index

        #: colour specification as in HTML (``#abcdef``)
        self.color = color

        #: label's name like "red" or "green"
        self.name = name

        #: freedesktop icon name, suitable for use in :py:meth:`PyQt4.QtGui.QIcon.fromTheme`
        self.icon = 'appvm-' + name

        #: freedesktop icon name, suitable for use in :py:meth:`PyQt4.QtGui.QIcon.fromTheme`
        #: on DispVMs
        self.icon_dispvm = 'dispvm-' + name


    @classmethod
    def fromxml(cls, xml):
        '''Create label definition from XML node

        :param lxml.etree._Element xml: XML node reference
        :rtype: :py:class:`qubes.Label`
        '''

        index = int(xml.get('id').split('-', 1)[1])
        color = xml.get('color')
        name = xml.text

        return cls(index, color, name)


    def __xml__(self):
        element = lxml.etree.Element('label', id='label-' + self.index, color=self.color)
        element.text = self.name
        return element


    def __repr__(self):
        return '{}({!r}, {!r}, {!r}, dispvm={!r})'.format(
            self.__class__.__name__,
            self.index,
            self.color,
            self.name)


    @__builtin__.property
    def icon_path(self):
        '''Icon path

        .. deprecated:: 2.0
           use :py:meth:`PyQt4.QtGui.QIcon.fromTheme` and :py:attr:`icon`
        '''
        return os.path.join(system_path['qubes_icon_dir'], self.icon) + ".png"


    @__builtin__.property
    def icon_path_dispvm(self):
        '''Icon path

        .. deprecated:: 2.0
           use :py:meth:`PyQt4.QtGui.QIcon.fromTheme` and :py:attr:`icon_dispvm`
        '''
        return os.path.join(system_path['qubes_icon_dir'], self.icon_dispvm) + ".png"


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
        return '<{} {!r}>'.format(self.__class__.__name__, list(sorted(self.keys())))


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


    def add(self, value):
        '''Add VM to collection

        :param qubes.vm.BaseVM value: VM to add
        :raises TypeError: when value is of wrong type
        :raises ValueError: when there is already VM which has equal ``qid``
        '''

        # this violates duck typing, but is needed
        # for VMProperty to function correctly
        if not isinstance(value, qubes.vm.BaseVM):
            raise TypeError('{} holds only BaseVM instances'.format(self.__class__.__name__))

        if not hasattr(value, 'qid'):
            value.qid = self.domains.get_new_unused_qid()

        if value.qid in self:
            raise ValueError('This collection already holds VM that has qid={!r} (!r)'.format(
                value.qid, self[value.qid]))
        if value.name in self:
            raise ValueError('This collection already holds VM that has name={!r} (!r)'.format(
                value.name, self[value.name]))

        self._dict[value.qid] = value
        self.app.fire_event('domain-added', value)


    def __getitem__(self, key):
        if isinstance(key, int):
            return self._dict[key]

        if isinstance(key, basestring):
            for vm in self:
                if (vm.name == key):
                    return vm
            raise KeyError(key)

        if isinstance(key, qubes.vm.BaseVM):
            if key in self:
                return key
            raise KeyError(key)

        raise KeyError(key)


    def __delitem__(self, key):
        vm = self[key]
        del self._dict[vm.qid]
        self.app.fire_event('domain-deleted', vm)


    def __contains__(self, key):
        return any((key == vm or key == vm.qid or key == vm.name) for vm in self)


    def __len__(self):
        return len(self._dict)


    def get_vms_based_on(self, template):
        template = self[template]
        return set(vm for vm in self if vm.template == template)


    def get_vms_connected_to(self, netvm):
        new_vms = set([netvm])
        dependend_vms = set()

        # Dependency resolving only makes sense on NetVM (or derivative)
#       if not self[netvm_qid].is_netvm():
#           return set([])

        while len(new_vms) > 0:
            cur_vm = new_vms.pop()
            for vm in cur_vm.connected_vms.values():
                if vm in dependend_vms:
                    continue
                dependend_vms.add(vm.qid)
#               if vm.is_netvm():
                new_vms.append(vm.qid)

        return dependent_vms


    # XXX with Qubes Admin Api this will probably lead to race condition
    # whole process of creating and adding should be synchronised
    def get_new_unused_qid(self):
        used_ids = set(self.qids())
        for i in range(1, MAX_QID):
            if i not in used_ids:
                return i
        raise LookupError("Cannot find unused qid!")


    def get_new_unused_netid(self):
        used_ids = set([vm.netid for vm in self]) # if vm.is_netvm()])
        for i in range(1, MAX_NETID):
            if i not in used_ids:
                return i
        raise LookupError("Cannot find unused netid!")


class property(object):
    '''Qubes property.

    This class holds one property that can be saved to and loaded from
    :file:`qubes.xml`. It is used for both global and per-VM properties.

    Property can be unset by ordinary ``del`` statement or assigning
    :py:attr:`DEFAULT` special value to it. After deletion (or before first
    assignment/load) attempting to read a property will get its default value
    or, when no default, py:class:`exceptions.AttributeError`.

    :param str name: name of the property
    :param collections.Callable setter: if not :py:obj:`None`, this is used to initialise value; first parameter to the function is holder instance and the second is value; this is called before ``type``
    :param collections.Callable saver: function to coerce value to something readable by setter
    :param type type: if not :py:obj:`None`, value is coerced to this type
    :param object default: default value; if callable, will be called with holder as first argument
    :param int load_stage: stage when property should be loaded (see :py:class:`Qubes` for description of stages)
    :param int order: order of evaluation (bigger order values are later)
    :param str doc: docstring; you may use RST markup

    Setters and savers have following signatures:

        .. :py:function:: setter(self, prop, value)
            :noindex:

            :param self: instance of object that is holding property
            :param prop: property object
            :param value: value being assigned

        .. :py:function:: saver(self, prop, value)
            :noindex:

            :param self: instance of object that is holding property
            :param prop: property object
            :param value: value being saved
            :rtype: str
            :raises property.DontSave: when property should not be saved at all

    '''

    #: Assigning this value to property means setting it to its default value.
    #: If property has no default value, this will unset it.
    DEFAULT = object()

    # internal use only
    _NO_DEFAULT = object()

    def __init__(self, name, setter=None, saver=None, type=None, default=_NO_DEFAULT,
            load_stage=2, order=0, save_via_ref=False, doc=None):
        self.__name__ = name
        self._setter = setter
        self._saver = saver if saver is not None else (lambda self, prop, value: str(value))
        self._type = type
        self._default = default
        self.order = order
        self.load_stage = load_stage
        self.save_via_ref = save_via_ref
        self.__doc__ = doc
        self._attr_name = '_qubesprop_' + name


    def __get__(self, instance, owner):
#       sys.stderr.write('{!r}.__get__({}, {!r})\n'.format(self.__name__, hex(id(instance)), owner))
        if instance is None:
            return self

        # XXX this violates duck typing, shall we keep it?
        if not isinstance(instance, PropertyHolder):
            raise AttributeError(
                'qubes.property should be used on qubes.PropertyHolder instances only')

#       sys.stderr.write('  __get__ try\n')
        try:
            return getattr(instance, self._attr_name)

        except AttributeError:
#           sys.stderr.write('  __get__ except\n')
            if self._default is self._NO_DEFAULT:
                raise AttributeError('property {!r} not set'.format(self.__name__))
            elif isinstance(self._default, collections.Callable):
                return self._default(instance)
            else:
                return self._default


    def __set__(self, instance, value):
        if value is self.__class__.DEFAULT:
            self.__delete__(instance)
            return

        try:
            oldvalue = getattr(instance, self.__name__)
            has_oldvalue = True
        except AttributeError:
            has_oldvalue = False

        if self._setter is not None:
            value = self._setter(instance, self, value)
        if self._type is not None:
            value = self._type(value)

        if has_oldvalue:
            instance.fire_event_pre('property-pre-set:' + self.__name__, value, oldvalue)
        else:
            instance.fire_event_pre('property-pre-set:' + self.__name__, value)

        instance._init_property(self, value)

        if has_oldvalue:
            instance.fire_event('property-set:' + self.__name__, value, oldvalue)
        else:
            instance.fire_event('property-set:' + self.__name__, value)


    def __delete__(self, instance):
        try:
            oldvalue = getattr(instance, self.__name__)
            has_oldvalue = True
        except AttributeError:
            has_oldvalue = False

        if has_oldvalue:
            instance.fire_event_pre('property-pre-deleted:' + self.__name__, oldvalue)
        else:
            instance.fire_event_pre('property-pre-deleted:' + self.__name__)

        delattr(instance, self._attr_name)

        if has_oldvalue:
            instance.fire_event('property-deleted:' + self.__name__, oldvalue)
        else:
            instance.fire_event('property-deleted:' + self.__name__)


    def __repr__(self):
        return '<{} object at {:#x} name={!r} default={!r}>'.format(
            self.__class__.__name__, id(self), self.__name__, self._default)


    def __hash__(self):
        return hash(self.__name__)


    def __eq__(self, other):
        return self.__name__ == other.__name__


    #
    # exceptions
    #

    class DontSave(Exception):
        '''This exception may be raised from saver to sing that property should
        not be saved.
        '''
        pass

    @staticmethod
    def dontsave(self, prop, value):
        '''Dummy saver that never saves anything.'''
        raise DontSave()

    #
    # some setters provided
    #

    @staticmethod
    def forbidden(self, prop, value):
        '''Property setter that forbids loading a property.

        This is used to effectively disable property in classes which inherit
        unwanted property. When someone attempts to load such a property, it

        :throws AttributeError: always
        '''

        raise AttributeError('setting {} property on {} instance is forbidden'.format(
            prop.__name__, self.__class__.__name__))


    @staticmethod
    def bool(self, prop, value):
        '''Property setter for boolean properties.

        It accepts (case-insensitive) ``'0'``, ``'no'`` and ``false`` as
        :py:obj:`False` and ``'1'``, ``'yes'`` and ``'true'`` as
        :py:obj:`True`.
        '''

        lcvalue = value.lower()
        if lcvalue in ('0', 'no', 'false'): return False
        if lcvalue in ('1', 'yes', 'true'): return True
        raise ValueError('Invalid literal for boolean property: {!r}'.format(value))



class PropertyHolder(qubes.events.Emitter):
    '''Abstract class for holding :py:class:`qubes.property`

    Events fired by instances of this class:

        .. event:: property-load (subject, event)

            Fired once after all properties are loaded from XML. Individual
            ``property-set`` events are not fired.

        .. event:: property-set:<propname> (subject, event, name, newvalue[, oldvalue])

            Fired when property changes state. Signature is variable,
            *oldvalue* is present only if there was an old value.

            :param name: Property name
            :param newvalue: New value of the property
            :param oldvalue: Old value of the property

        .. event:: property-pre-set:<propname> (subject, event, name, newvalue[, oldvalue])

            Fired before property changes state. Signature is variable,
            *oldvalue* is present only if there was an old value.

            :param name: Property name
            :param newvalue: New value of the property
            :param oldvalue: Old value of the property

        .. event:: property-del:<propname> (subject, event, name[, oldvalue])

            Fired when property gets deleted (is set to default). Signature is
            variable, *oldvalue* is present only if there was an old value.

            :param name: Property name
            :param oldvalue: Old value of the property

        .. event:: property-pre-del:<propname> (subject, event, name[, oldvalue])

            Fired before property gets deleted (is set to default). Signature
            is variable, *oldvalue* is present only if there was an old value.

            :param name: Property name
            :param oldvalue: Old value of the property

    Members:
    '''

    def __init__(self, xml, *args, **kwargs):
        super(PropertyHolder, self).__init__(*args, **kwargs)
        self.xml = xml


    def get_props_list(self, load_stage=None):
        '''List all properties attached to this VM

        :param load_stage: Filter by load stage
        :type load_stage: :py:func:`int` or :py:obj:`None`
        '''

#       sys.stderr.write('{!r}.get_props_list(load_stage={})\n'.format('self', load_stage))
        props = set()
        for class_ in self.__class__.__mro__:
            props.update(prop for prop in class_.__dict__.values()
                if isinstance(prop, property))
        if load_stage is not None:
            props = set(prop for prop in props
                if prop.load_stage == load_stage)
#       sys.stderr.write('  props={!r}\n'.format(props))
        return sorted(props, key=lambda prop: (prop.load_stage, prop.order, prop.__name__))


    def _init_property(self, prop, value):
        '''Initialise property to a given value, without side effects.

        :param qubes.property prop: property object of particular interest
        :param value: value
        '''

        setattr(self, self.get_property_def(prop)._attr_name, value)


    def property_is_default(self, prop):
        '''Check whether property is in it's default value.

        Properties when unset may return some default value, so
        ``hasattr(vm, prop.__name__)`` is wrong in some circumstances. This
        method allows for checking if the value returned is in fact it's
        default value.

        :param qubes.property prop: property object of particular interest
        :rtype: bool
        '''

        return hasattr(self, self.get_property_def(prop)._attr_name)


    def get_property_def(self, prop):
        '''Return property definition object.

        If prop is already :py:class:`qubes.property` instance, return the same
        object.

        :param prop: property object or name
        :type prop: qubes.property or str
        :rtype: qubes.property
        '''

        if isinstance(prop, qubes.property):
            return prop

        for p in self.get_props_list():
            if p.__name__ == prop:
                return p

        raise AttributeError('No property {!r} found in {!r}'.format(
            prop, self.__class__))


    def load_properties(self, load_stage=None):
        '''Load properties from immediate children of XML node.

        ``property-set`` events are not fired for each individual property.

        :param lxml.etree._Element xml: XML node reference
        '''

#       sys.stderr.write('<{}>.load_properties(load_stage={}) xml={!r}\n'.format(hex(id(self)), load_stage, self.xml))

        self.events_enabled = False
        all_names = set(prop.__name__ for prop in self.get_props_list(load_stage))
#       sys.stderr.write('  all_names={!r}\n'.format(all_names))
        for node in self.xml.xpath('./properties/property'):
            name = node.get('name')
            value = node.get('ref') or node.text

#           sys.stderr.write('  load_properties name={!r} value={!r}\n'.format(name, value))
            if not name in all_names:
                raise AttributeError(
                    'No property {!r} found in {!r}'.format(
                        name, self.__class__))

            setattr(self, name, value)

        self.events_enabled = True
        self.fire_event('property-loaded')
#       sys.stderr.write('  load_properties return\n')


    def save_properties(self, with_defaults=False):
        '''Iterator that yields XML nodes representing set properties.

        :param bool with_defaults: If :py:obj:`True`, then it also includes properties which were not set explicite, but have default values filled.
        '''

#       sys.stderr.write('{!r}.save_properties(with_defaults={})\n'.format(self, with_defaults))

        properties = lxml.etree.Element('properties')

        for prop in self.get_props_list():
            try:
                value = getattr(self, (prop.__name__ if with_defaults else prop._attr_name))
            except AttributeError, e:
#               sys.stderr.write('AttributeError: {!s}\n'.format(e))
                continue

            try:
                value = prop._saver(self, prop, value)
            except property.DontSave:
                continue

            element = lxml.etree.Element('property', name=prop.__name__)
            if prop.save_via_ref:
                element.set('ref', value)
            else:
                element.text = value
            properties.append(element)

        return properties


    # this was clone_attrs
    def clone_properties(self, src, proplist=None):
        '''Clone properties from other object.

        :param PropertyHolder src: source object
        :param list proplist: list of properties (:py:obj:`None` for all properties)
        '''

        if proplist is None:
            proplist = self.get_props_list()
        else:
            proplist = [prop for prop in self.get_props_list()
                if prop.__name__ in proplist or prop in proplist]

        for prop in self.proplist():
            try:
                self._init_property(self, prop, getattr(src, prop._attr_name))
            except AttributeError:
                continue

        self.fire_event('cloned-properties', src, proplist)


    def require_property(self, prop, allow_none=False, hard=False):
        '''Complain badly when property is not set.

        :param prop: property name or object
        :type prop: qubes.property or str
        :param bool allow_none: if :py:obj:`True`, don't complain if :py:obj:`None` is found
        :param bool hard: if :py:obj:`True`, raise :py:class:`AssertionError`; if :py:obj:`False`, log warning instead
        '''

        if isinstance(qubes.property, prop):
            prop = prop.__name__

        try:
            value = getattr(self, prop)
            if value is None and not allow_none:
                raise AttributeError()
        except AttributeError:
            msg = 'Required property {!r} not set on {!r}'.format(prop, self)
            if hard:
                raise AssertionError(msg)
            else:
                self.log(msg)


import qubes.vm


class VMProperty(property):
    '''Property that is referring to a VM

    :param type vmclass: class that returned VM is supposed to be instance of

    and all supported by :py:class:`property` with the exception of ``type`` and ``setter``
    '''

    def __init__(self, name, vmclass=qubes.vm.BaseVM, allow_none=False, **kwargs):
        if 'type' in kwargs:
            raise TypeError("'type' keyword parameter is unsupported in {}".format(
                self.__class__.__name__))
        if 'setter' in kwargs:
            raise TypeError("'setter' keyword parameter is unsupported in {}".format(
                self.__class__.__name__))
        if not issubclass(vmclass, qubes.vm.BaseVM):
            raise TypeError("'vmclass' should specify a subclass of qubes.vm.BaseVM")

        super(VMProperty, self).__init__(name, **kwargs)
        self.vmclass = vmclass
        self.allow_none = allow_none

    def __set__(self, instance, value):
        if value is None:
            if self.allow_none:
                super(VMProperty, self).__set__(self, instance, vm)
                return
            else:
                raise ValueError(
                    'Property {!r} does not allow setting to {!r}'.format(
                        self.__name__, value))

        # XXX this may throw LookupError; that's good until introduction
        # of QubesNoSuchVMException or whatever
        vm = instance.app.domains[value]

        if not isinstance(vm, self.vmclass):
            raise TypeError('wrong VM class: domains[{!r}] if of type {!s} and not {!s}'.format(
                value, vm.__class__.__name__, self.vmclass.__name__))

        super(VMProperty, self).__set__(self, instance, vm)


import qubes.vm.qubesvm
import qubes.vm.templatevm

class Qubes(PropertyHolder):
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

        .. event:: domain-added (subject, event, vm)

            When domain is added.

            :param subject: Event emitter
            :param event: Event name (``'domain-added'``)
            :param vm: Domain object

        .. event:: domain-deleted (subject, event, vm)

            When domain is deleted. VM still has reference to ``app`` object,
            but is not contained within VMCollection.

            :param subject: Event emitter
            :param event: Event name (``'domain-deleted'``)
            :param vm: Domain object

    Methods and attributes:
    '''

    default_netvm = VMProperty('default_netvm', load_stage=3, default=None,
        doc='''Default NetVM for AppVMs. Initial state is :py:obj:`None`, which
            means that AppVMs are not connected to the Internet.''')
    default_fw_netvm = VMProperty('default_fw_netvm', load_stage=3, default=None,
        doc='''Default NetVM for ProxyVMs. Initial state is :py:obj:`None`, which
            means that ProxyVMs (including FirewallVM) are not connected to the
            Internet.''')
    default_template = VMProperty('default_template', load_stage=3,
        vmclass=qubes.vm.templatevm.TemplateVM,
        doc='Default template for new AppVMs')
    updatevm = VMProperty('updatevm', load_stage=3,
        doc='Which VM to use as ``yum`` proxy for updating AdminVM and TemplateVMs')
    clockvm = VMProperty('clockvm', load_stage=3,
        doc='Which VM to use as NTP proxy for updating AdminVM')
    default_kernel = property('default_kernel', load_stage=3,
        doc='Which kernel to use when not overriden in VM')


    def __init__(self, store='/var/lib/qubes/qubes.xml'):
        self._extensions = set(ext(self) for ext in qubes.ext.Extension.register.values())

        #: collection of all VMs managed by this Qubes instance
        self.domains = VMCollection()

        #: collection of all available labels for VMs
        self.labels = {}

        #: Connection to VMM
        self.vmm = VMMConnection()

        #: Information about host system
        self.host = QubesHost(self)

        self._store = store

        try:
            self.load()
        except IOError:
            self._init()

        super(Qubes, self).__init__(xml=lxml.etree.parse(self.qubes_store_file))


    def _open_store(self):
        if hasattr(self, '_storefd'):
            return

        self._storefd = open(self._store, 'r+')

        if os.name == 'posix':
            fcntl.lockf (self.qubes_store_file, fcntl.LOCK_EX)
        elif os.name == 'nt':
            overlapped = pywintypes.OVERLAPPED()
            win32file.LockFileEx(win32file._get_osfhandle(self.qubes_store_file.fileno()),
                    win32con.LOCKFILE_EXCLUSIVE_LOCK, 0, -0x10000, overlapped)


    def load(self):
        '''
        :throws EnvironmentError: failure on parsing store
        :throws xml.parsers.expat.ExpatError: failure on parsing store
        '''
        self._open_store()

        # stage 1: load labels
        for node in self._xml.xpath('./labels/label'):
            label = Label.fromxml(node)
            self.labels[label.id] = label

        # stage 2: load VMs
        for node in self._xml.xpath('./domains/domain'):
            cls = qubes.vm.load(node.get("class"))
            vm = cls.fromxml(self, node)
            self.domains.add(vm)

        if not 0 in self.domains:
            self.domains.add(qubes.vm.adminvm.AdminVM(self))

        # stage 3: load global properties
        self.load_properties(self.xml, load_stage=3)

        # stage 4: fill all remaining VM properties
        for vm in self.domains:
            vm.load_properties(None, load_stage=4)

        # stage 5: misc fixups

        self.require_property('default_fw_netvm', allow_none=True)
        self.require_property('default_netvm', allow_none=True)
        self.require_property('default_template')
        self.require_property('clockvm')
        self.require_property('updatevm')

        # Disable ntpd in ClockVM - to not conflict with ntpdate (both are
        # using 123/udp port)
        if hasattr(self, 'clockvm'):
            if 'ntpd' in self.clockvm.services:
                if self.clockvm.services['ntpd']:
                    self.log.warning("VM set as clockvm ({!r}) has enabled "
                        "'ntpd' service! Expect failure when syncing time in "
                        "dom0.".format(self.clockvm))
            else:
                self.clockvm.services['ntpd'] = False


    def _init(self):
        self._open_store()

        self.labels = {
            1: Label(1, '0xcc0000', 'red'),
            2: Label(2, '0xf57900', 'orange'),
            3: Label(3, '0xedd400', 'yellow'),
            4: Label(4, '0x73d216', 'green'),
            5: Label(5, '0x555753', 'gray'),
            6: Label(6, '0x3465a4', 'blue'),
            7: Label(7, '0x75507b', 'purple'),
            8: Label(8, '0x000000', 'black'),
        }


    def __del__(self):
        # intentionally do not call explicit unlock to not unlock the file
        # before all buffers are flushed
        self._storefd.close()
        del self._storefd


    def __xml__(self):
        element = lxml.etree.Element('qubes')

        element.append(self.save_labels())
        element.append(self.save_properties())

        domains = lxml.etree.Element('domains')
        for vm in self.domains:
            domains.append(vm.__xml__())
        element.append(domains)

        return element


    def save(self):
        '''Save all data to qubes.xml
        '''
        self._storefd.seek(0)
        self._storefd.truncate()
        lxml.etree.ElementTree(self.__xml__()).write(
            self._storefd, encoding='utf-8', pretty_print=True)
        self._storefd.sync()
        os.chmod(self._store, 0660)
        os.chown(self._store, -1, grp.getgrnam('qubes').gr_gid)


    def save_labels(self):
        '''Serialise labels

        :rtype: lxml.etree._Element
        '''

        labels = lxml.etree.Element('labels')
        for label in self.labels:
            labels.append(label.__xml__())
        return labels


    def add_new_vm(self, vm):
        '''Add new Virtual Machine to colletion

        '''

        self.domains.add(vm)


    @qubes.events.handler('domain-pre-deleted')
    def on_domain_pre_deleted(self, event, vm):
        if isinstance(vm, qubes.vm.templatevm.TemplateVM):
            appvms = self.get_vms_based_on(vm)
            if appvms:
                raise QubesException(
                    'Cannot remove template that has dependent AppVMs. '
                    'Affected are: {}'.format(', '.join(
                        vm.name for name in sorted(appvms))))


    @qubes.events.handler('domain-deleted')
    def on_domain_deleted(self, event, vm):
        if self.default_netvm == vm:
            del self.default_netvm
        if self.default_fw_netvm == vm:
            del self.default_fw_netvm
        if self.clockvm == vm:
            del self.clockvm
        if self.updatevm == vm:
            del self.updatevm
        if self.default_template == vm:
            del self.default_template

        return super(QubesVmCollection, self).pop(qid)


    @qubes.events.handler('property-pre-set:clockvm')
    def on_property_pre_set_clockvm(self, event, name, newvalue, oldvalue=None):
        if 'ntpd' in newvalue.services:
            if newvalue.services['ntpd']:
                raise QubesException(
                    'Cannot set {!r} as {!r} property since it has ntpd enabled.'.format(
                        newvalue, name))
        else:
            newvalue.services['ntpd'] = False


    @qubes.events.handler('property-pre-set:default_netvm')
    def on_property_pre_set_default_netvm(self, event, name, newvalue, oldvalue=None):
        if newvalue is not None and oldvalue is not None \
                and oldvalue.is_running() and not newvalue.is_running() \
                and self.domains.get_vms_connected_to(oldvalue):
            raise QubesException(
                'Cannot change default_netvm to domain that is not running ({!r}).'.format(
                    newvalue))


    @qubes.events.handler('property-set:default_fw_netvm')
    def on_property_set_default_netvm(self, event, name, newvalue, oldvalue=None):
        for vm in self.domains:
            if not vm.provides_network and vm.property_is_default('netvm'):
                # fire property-del:netvm as it is responsible for resetting
                # netvm to it's default value
                vm.fire_event('property-del:netvm', 'netvm', newvalue, oldvalue)


    @qubes.events.handler('property-set:default_netvm')
    def on_property_set_default_netvm(self, event, name, newvalue, oldvalue=None):
        for vm in self.domains:
            if vm.provides_network and vm.property_is_default('netvm'):
                # fire property-del:netvm as it is responsible for resetting
                # netvm to it's default value
                vm.fire_event('property-del:netvm', 'netvm', newvalue, oldvalue)


# load plugins
import qubes._pluginloader
