#!/usr/bin/python2 -O
# vim: fileencoding=utf-8

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

'''
Qubes OS

:copyright: © 2010-2015 Invisible Things Lab
'''

from __future__ import absolute_import

__author__ = 'Invisible Things Lab'
__license__ = 'GPLv2 or later'
__version__ = 'R3'

import ast
import atexit
import collections
import errno
import grp
import logging
import os
import os.path
import sys
import tempfile
import time
import warnings

import __builtin__

import docutils.core
import docutils.io
import lxml.etree


import qubes.config
import qubes.events
import qubes.exc
import qubes.ext


if os.name == 'posix':
    import fcntl
elif os.name == 'nt':
    # pylint: disable=import-error
    import win32con
    import win32file
    import pywintypes
else:
    raise RuntimeError("Qubes works only on POSIX or WinNT systems")

import libvirt
try:
    import xen.lowlevel.xs
    import xen.lowlevel.xc
except ImportError:
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
            raise qubes.exc.QubesException(
                'Cannot change offline mode while already connected')

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
            raise qubes.exc.QubesException(
                'VMM operations disabled in offline mode')

        if 'xen.lowlevel.xs' in sys.modules:
            self._xs = xen.lowlevel.xs.xs()
        if 'xen.lowlevel.cs' in sys.modules:
            self._xc = xen.lowlevel.xc.xc()
        self._libvirt_conn = libvirt.open(qubes.config.defaults['libvirt_uri'])
        if self._libvirt_conn is None:
            raise qubes.exc.QubesException('Failed connect to libvirt driver')
        libvirt.registerErrorHandler(self._libvirt_error_handler, None)

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

        # XXX what about the case when we run under KVM,
        # but xen modules are importable?
        if 'xen.lowlevel.xs' not in sys.modules:
            raise AttributeError(
                'xs object is available under Xen hypervisor only')

        self.init_vmm_connection()
        return self._xs

    @__builtin__.property
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
        return self._xs

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
        self._total_mem = long(memory) * 1024
        self._no_cpus = cpus

        self.app.log.debug('QubesHost: no_cpus={} memory_total={}'.format(
            self.no_cpus, self.memory_total))
        try:
            self.app.log.debug('QubesHost: xen_free_memory={}'.format(
                self.get_free_xen_memory()))
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
                info = self.app.vmm.xc.domain_getinfo(0, qubes.config.max_qid)
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
            info = self.app.vmm.xc.domain_getinfo(0, qubes.config.max_qid)
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
                    long(1000 ** 3) / (current_time - previous_time) * 100)
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

        #: freedesktop icon name, suitable for use in
        #: :py:meth:`PyQt4.QtGui.QIcon.fromTheme`
        self.icon = 'appvm-' + name

        #: freedesktop icon name, suitable for use in
        #: :py:meth:`PyQt4.QtGui.QIcon.fromTheme` on DispVMs
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
        element = lxml.etree.Element(
            'label', id='label-{}'.format(self.index), color=self.color)
        element.text = self.name
        return element


    def __repr__(self):
        return '{}({!r}, {!r}, {!r})'.format(
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
        return os.path.join(qubes.config.system_path['qubes_icon_dir'],
            self.icon) + ".png"


    @__builtin__.property
    def icon_path_dispvm(self):
        '''Icon path

        .. deprecated:: 2.0
           use :py:meth:`PyQt4.QtGui.QIcon.fromTheme` and :py:attr:`icon_dispvm`
        '''
        return os.path.join(qubes.config.system_path['qubes_icon_dir'],
            self.icon_dispvm) + ".png"


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


    def add(self, value):
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
            raise ValueError('This collection already holds VM that has '
                'name={!r} ({!r})'.format(value.name, self[value.name]))

        self._dict[value.qid] = value
        value.events_enabled = True
        self.app.fire_event('domain-added', value)

        return value


    def __getitem__(self, key):
        if isinstance(key, int):
            return self._dict[key]

        if isinstance(key, basestring):
            for vm in self:
                if vm.name == key:
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
        return any((key == vm or key == vm.qid or key == vm.name)
                   for vm in self)


    def __len__(self):
        return len(self._dict)


    def get_vms_based_on(self, template):
        template = self[template]
        return set(vm for vm in self if vm.template == template)


    def get_vms_connected_to(self, netvm):
        new_vms = set([self[netvm]])
        dependent_vms = set()

        # Dependency resolving only makes sense on NetVM (or derivative)
#       if not self[netvm_qid].is_netvm():
#           return set([])

        while len(new_vms) > 0:
            cur_vm = new_vms.pop()
            for vm in cur_vm.connected_vms.values():
                if vm in dependent_vms:
                    continue
                dependent_vms.add(vm.qid)
#               if vm.is_netvm():
                new_vms.add(vm.qid)

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


class property(object): # pylint: disable=redefined-builtin,invalid-name
    '''Qubes property.

    This class holds one property that can be saved to and loaded from
    :file:`qubes.xml`. It is used for both global and per-VM properties.

    Property can be unset by ordinary ``del`` statement or assigning
    :py:attr:`DEFAULT` special value to it. After deletion (or before first
    assignment/load) attempting to read a property will get its default value
    or, when no default, py:class:`exceptions.AttributeError`.

    :param str name: name of the property
    :param collections.Callable setter: if not :py:obj:`None`, this is used to \
        initialise value; first parameter to the function is holder instance \
        and the second is value; this is called before ``type``
    :param collections.Callable saver: function to coerce value to something \
        readable by setter
    :param type type: if not :py:obj:`None`, value is coerced to this type
    :param object default: default value; if callable, will be called with \
        holder as first argument
    :param int load_stage: stage when property should be loaded (see \
        :py:class:`Qubes` for description of stages)
    :param int order: order of evaluation (bigger order values are later)
    :param str ls_head: column head for :program:`qvm-ls`
    :param int ls_width: column width in :program:`qvm-ls`
    :param str doc: docstring; this should be one paragraph of plain RST, no \
        sphinx-specific features

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

    def __init__(self, name, setter=None, saver=None, type=None,
            default=_NO_DEFAULT, write_once=False, load_stage=2, order=0,
            save_via_ref=False,
            ls_head=None, ls_width=None, doc=None):
        # pylint: disable=redefined-builtin
        self.__name__ = name
        self._setter = setter
        self._saver = saver if saver is not None else (
            lambda self, prop, value: str(value))
        self._type = type
        self._default = default
        self._write_once = write_once
        self.order = order
        self.load_stage = load_stage
        self.save_via_ref = save_via_ref
        self.__doc__ = doc
        self._attr_name = '_qubesprop_' + name

        if ls_head is not None or ls_width is not None:
            self.ls_head = ls_head or self.__name__.replace('_', '-').upper()
            self.ls_width = max(ls_width or 0, len(self.ls_head) + 1)


    def __get__(self, instance, owner):
        if instance is None:
            return self

        # XXX this violates duck typing, shall we keep it?
        if not isinstance(instance, PropertyHolder):
            raise AttributeError('qubes.property should be used on '
                'qubes.PropertyHolder instances only')

        try:
            return getattr(instance, self._attr_name)

        except AttributeError:
            if self._default is self._NO_DEFAULT:
                raise AttributeError(
                    'property {!r} not set'.format(self.__name__))
            elif isinstance(self._default, collections.Callable):
                return self._default(instance)
            else:
                return self._default


    def __set__(self, instance, value):
        self._enforce_write_once(instance)

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
        if self._type not in (None, type(value)):
            value = self._type(value)

        if has_oldvalue:
            instance.fire_event_pre('property-pre-set:' + self.__name__,
                self.__name__, value, oldvalue)
        else:
            instance.fire_event_pre('property-pre-set:' + self.__name__,
                self.__name__, value)

        instance._property_init(self, value) # pylint: disable=protected-access

        if has_oldvalue:
            instance.fire_event('property-set:' + self.__name__, self.__name__,
                value, oldvalue)
        else:
            instance.fire_event('property-set:' + self.__name__, self.__name__,
                value)


    def __delete__(self, instance):
        self._enforce_write_once(instance)

        try:
            oldvalue = getattr(instance, self.__name__)
            has_oldvalue = True
        except AttributeError:
            has_oldvalue = False

        if has_oldvalue:
            instance.fire_event_pre('property-pre-deleted:' + self.__name__,
                self.__name__, oldvalue)
        else:
            instance.fire_event_pre('property-pre-deleted:' + self.__name__,
                self.__name__)

        delattr(instance, self._attr_name)

        if has_oldvalue:
            instance.fire_event('property-deleted:' + self.__name__,
                self.__name__, oldvalue)
        else:
            instance.fire_event('property-deleted:' + self.__name__,
                self.__name__)


    def __repr__(self):
        default = ' default={!r}'.format(self._default) \
            if self._default is not self._NO_DEFAULT \
            else ''
        return '<{} object at {:#x} name={!r}{}>'.format(
            self.__class__.__name__, id(self), self.__name__, default) \


    def __hash__(self):
        return hash(self.__name__)


    def __eq__(self, other):
        return isinstance(other, property) and self.__name__ == other.__name__


    def _enforce_write_once(self, instance):
        if self._write_once and not instance.property_is_default(self):
            raise AttributeError(
                'property {!r} is write-once and already set'.format(
                    self.__name__))


    #
    # exceptions
    #

    class DontSave(Exception):
        '''This exception may be raised from saver to sign that property should
        not be saved.
        '''
        pass

    @staticmethod
    def dontsave(self, prop, value):
        '''Dummy saver that never saves anything.'''
        # pylint: disable=bad-staticmethod-argument,unused-argument
        raise property.DontSave()

    #
    # some setters provided
    #

    @staticmethod
    def forbidden(self, prop, value):
        '''Property setter that forbids loading a property.

        This is used to effectively disable property in classes which inherit
        unwanted property. When someone attempts to load such a property, it

        :throws AttributeError: always
        ''' # pylint: disable=bad-staticmethod-argument,unused-argument

        raise AttributeError(
            'setting {} property on {} instance is forbidden'.format(
                prop.__name__, self.__class__.__name__))


    @staticmethod
    def bool(self, prop, value):
        '''Property setter for boolean properties.

        It accepts (case-insensitive) ``'0'``, ``'no'`` and ``false`` as
        :py:obj:`False` and ``'1'``, ``'yes'`` and ``'true'`` as
        :py:obj:`True`.
        ''' # pylint: disable=bad-staticmethod-argument,unused-argument

        if isinstance(value, basestring):
            lcvalue = value.lower()
            if lcvalue in ('0', 'no', 'false', 'off'):
                return False
            if lcvalue in ('1', 'yes', 'true', 'on'):
                return True
            raise ValueError(
                'Invalid literal for boolean property: {!r}'.format(value))

        return bool(value)



class PropertyHolder(qubes.events.Emitter):
    '''Abstract class for holding :py:class:`qubes.property`

    Events fired by instances of this class:

        .. event:: property-load (subject, event)

            Fired once after all properties are loaded from XML. Individual
            ``property-set`` events are not fired.

        .. event:: property-set:<propname> \
                (subject, event, name, newvalue[, oldvalue])

            Fired when property changes state. Signature is variable,
            *oldvalue* is present only if there was an old value.

            :param name: Property name
            :param newvalue: New value of the property
            :param oldvalue: Old value of the property

        .. event:: property-pre-set:<propname> \
                (subject, event, name, newvalue[, oldvalue])

            Fired before property changes state. Signature is variable,
            *oldvalue* is present only if there was an old value.

            :param name: Property name
            :param newvalue: New value of the property
            :param oldvalue: Old value of the property

        .. event:: property-del:<propname> \
                (subject, event, name[, oldvalue])

            Fired when property gets deleted (is set to default). Signature is
            variable, *oldvalue* is present only if there was an old value.

            :param name: Property name
            :param oldvalue: Old value of the property

        .. event:: property-pre-del:<propname> \
                (subject, event, name[, oldvalue])

            Fired before property gets deleted (is set to default). Signature
            is variable, *oldvalue* is present only if there was an old value.

            :param name: Property name
            :param oldvalue: Old value of the property

    Members:
    '''

    def __init__(self, xml, **kwargs):
        self.xml = xml

        propvalues = {}

        all_names = set(prop.__name__ for prop in self.property_list())
        for key in list(kwargs.keys()):
            if not key in all_names:
                continue
            propvalues[key] = kwargs.pop(key)

        super(PropertyHolder, self).__init__(**kwargs)

        for key, value in propvalues.items():
            setattr(self, key, value)


    @classmethod
    def property_list(cls, load_stage=None):
        '''List all properties attached to this VM's class

        :param load_stage: Filter by load stage
        :type load_stage: :py:func:`int` or :py:obj:`None`
        '''

        props = set()
        for class_ in cls.__mro__:
            props.update(prop for prop in class_.__dict__.values()
                if isinstance(prop, property))
        if load_stage is not None:
            props = set(prop for prop in props
                if prop.load_stage == load_stage)
        return sorted(props,
            key=lambda prop: (prop.load_stage, prop.order, prop.__name__))


    def _property_init(self, prop, value):
        '''Initialise property to a given value, without side effects.

        :param qubes.property prop: property object of particular interest
        :param value: value
        '''

        # pylint: disable=protected-access
        setattr(self, self.property_get_def(prop)._attr_name, value)


    def property_is_default(self, prop):
        '''Check whether property is in it's default value.

        Properties when unset may return some default value, so
        ``hasattr(vm, prop.__name__)`` is wrong in some circumstances. This
        method allows for checking if the value returned is in fact it's
        default value.

        :param qubes.property prop: property object of particular interest
        :rtype: bool
        ''' # pylint: disable=protected-access

        # both property_get_def() and ._attr_name may throw AttributeError,
        # which we don't want to catch
        attrname = self.property_get_def(prop)._attr_name
        return not hasattr(self, attrname)


    @classmethod
    def property_get_def(cls, prop):
        '''Return property definition object.

        If prop is already :py:class:`qubes.property` instance, return the same
        object.

        :param prop: property object or name
        :type prop: qubes.property or str
        :rtype: qubes.property
        '''

        if isinstance(prop, qubes.property):
            return prop

        for p in cls.property_list():
            if p.__name__ == prop:
                return p

        raise AttributeError('No property {!r} found in {!r}'.format(
            prop, cls))


    def load_properties(self, load_stage=None):
        '''Load properties from immediate children of XML node.

        ``property-set`` events are not fired for each individual property.

        :param int load_stage: Stage of loading.
        '''

        if self.xml is None:
            return
        all_names = set(
            prop.__name__ for prop in self.property_list(load_stage))
        for node in self.xml.xpath('./properties/property'):
            name = node.get('name')
            value = node.get('ref') or node.text

            if not name in all_names:
                continue

            setattr(self, name, value)


    def xml_properties(self, with_defaults=False):
        '''Iterator that yields XML nodes representing set properties.

        :param bool with_defaults: If :py:obj:`True`, then it also includes \
            properties which were not set explicite, but have default values \
            filled.
        '''


        properties = lxml.etree.Element('properties')

        for prop in self.property_list():
            # pylint: disable=protected-access
            try:
                value = getattr(
                    self, (prop.__name__ if with_defaults else prop._attr_name))
            except AttributeError:
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
        :param list proplist: list of properties \
            (:py:obj:`None` for all properties)
        '''

        if proplist is None:
            proplist = self.property_list()
        else:
            proplist = [prop for prop in self.property_list()
                if prop.__name__ in proplist or prop in proplist]

        for prop in proplist:
            try:
                # pylint: disable=protected-access
                self._property_init(prop, getattr(src, prop._attr_name))
            except AttributeError:
                continue

        self.fire_event('cloned-properties', src, proplist)


    def property_require(self, prop, allow_none=False, hard=False):
        '''Complain badly when property is not set.

        :param prop: property name or object
        :type prop: qubes.property or str
        :param bool allow_none: if :py:obj:`True`, don't complain if \
            :py:obj:`None` is found
        :param bool hard: if :py:obj:`True`, raise :py:class:`AssertionError`; \
            if :py:obj:`False`, log warning instead
        '''

        if isinstance(prop, qubes.property):
            prop = prop.__name__

        try:
            value = getattr(self, prop)
            if value is None and not allow_none:
                raise AttributeError()
        except AttributeError:
            # pylint: disable=no-member
            msg = 'Required property {!r} not set on {!r}'.format(prop, self)
            if hard:
                raise AssertionError(msg)
            else:
                # pylint: disable=no-member
                self.log.fatal(msg)


import qubes.vm


class VMProperty(property):
    '''Property that is referring to a VM

    :param type vmclass: class that returned VM is supposed to be instance of

    and all supported by :py:class:`property` with the exception of ``type`` \
        and ``setter``
    '''

    _none_value = ''

    def __init__(self, name, vmclass=qubes.vm.BaseVM, allow_none=False,
            **kwargs):
        if 'type' in kwargs:
            raise TypeError(
                "'type' keyword parameter is unsupported in {}".format(
                    self.__class__.__name__))
        if 'setter' in kwargs:
            raise TypeError(
                "'setter' keyword parameter is unsupported in {}".format(
                    self.__class__.__name__))
        if not issubclass(vmclass, qubes.vm.BaseVM):
            raise TypeError(
                "'vmclass' should specify a subclass of qubes.vm.BaseVM")

        super(VMProperty, self).__init__(name,
            saver=(lambda self_, prop, value:
                self._none_value if value is None else value.name),
            **kwargs)
        self.vmclass = vmclass
        self.allow_none = allow_none


    def __set__(self, instance, value):
        if value == self._none_value:
            value = None
        if value is None:
            if self.allow_none:
                super(VMProperty, self).__set__(instance, value)
                return
            else:
                raise ValueError(
                    'Property {!r} does not allow setting to {!r}'.format(
                        self.__name__, value))

        app = instance if isinstance(instance, Qubes) else instance.app

        try:
            vm = app.domains[value]
        except KeyError:
            raise qubes.exc.QubesVMNotFoundError(value)

        if not isinstance(vm, self.vmclass):
            raise TypeError('wrong VM class: domains[{!r}] if of type {!s} '
                'and not {!s}'.format(value,
                    vm.__class__.__name__,
                    self.vmclass.__name__))

        super(VMProperty, self).__set__(instance, vm)


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

    default_netvm = VMProperty('default_netvm', load_stage=3,
        default=None, allow_none=True,
        doc='''Default NetVM for AppVMs. Initial state is `None`, which means
            that AppVMs are not connected to the Internet.''')
    default_fw_netvm = VMProperty('default_fw_netvm', load_stage=3,
        default=None, allow_none=True,
        doc='''Default NetVM for ProxyVMs. Initial state is `None`, which means
            that ProxyVMs (including FirewallVM) are not connected to the
            Internet.''')
    default_template = VMProperty('default_template', load_stage=3,
        vmclass=qubes.vm.templatevm.TemplateVM,
        doc='Default template for new AppVMs')
    updatevm = VMProperty('updatevm', load_stage=3,
        allow_none=True,
        doc='''Which VM to use as `yum` proxy for updating AdminVM and
            TemplateVMs''')
    clockvm = VMProperty('clockvm', load_stage=3,
        allow_none=True,
        doc='Which VM to use as NTP proxy for updating AdminVM')
    default_kernel = property('default_kernel', load_stage=3,
        doc='Which kernel to use when not overriden in VM')

    # TODO #1637 #892
    check_updates_vm = property('check_updates_vm',
        type=bool, setter=property.bool,
        default=True,
        doc='check for updates inside qubes')


    def __init__(self, store=None, load=True, **kwargs):
        #: logger instance for logging global messages
        self.log = logging.getLogger('app')

        # pylint: disable=no-member
        self._extensions = set(
            ext(self) for ext in qubes.ext.Extension.register.values())

        #: collection of all VMs managed by this Qubes instance
        self.domains = VMCollection(self)

        #: collection of all available labels for VMs
        self.labels = {}

        #: Connection to VMM
        self.vmm = VMMConnection()

        #: Information about host system
        self.host = QubesHost(self)

        self._store = store if store is not None else os.path.join(
            qubes.config.system_path['qubes_base_dir'],
            qubes.config.system_path['qubes_store_filename'])

        super(Qubes, self).__init__(xml=None, **kwargs)

        self.__load_timestamp = None

        if load:
            self.load()

        self.events_enabled = True


    def load(self):
        '''Open qubes.xml

        :throws EnvironmentError: failure on parsing store
        :throws xml.parsers.expat.ExpatError: failure on parsing store
        :raises lxml.etree.XMLSyntaxError: on syntax error in qubes.xml
        '''

        fd = os.open(self._store, os.O_RDWR) # no O_CREAT
        fh = os.fdopen(fd, 'rb')

        if os.name == 'posix':
            fcntl.lockf(fh, fcntl.LOCK_EX)
        elif os.name == 'nt':
            # pylint: disable=protected-access
            win32file.LockFileEx(
                win32file._get_osfhandle(fh.fileno()),
                win32con.LOCKFILE_EXCLUSIVE_LOCK,
                0, -0x10000,
                pywintypes.OVERLAPPED())

        self.xml = lxml.etree.parse(fh)

        # stage 1: load labels
        for node in self.xml.xpath('./labels/label'):
            label = Label.fromxml(node)
            self.labels[label.index] = label

        # stage 2: load VMs
        for node in self.xml.xpath('./domains/domain'):
            # pylint: disable=no-member
            cls = qubes.vm.BaseVM.register[node.get('class')]
            vm = cls(self, node)
            vm.load_properties(load_stage=2)
            vm.init_log()
            self.domains.add(vm)

        if not 0 in self.domains:
            self.domains.add(qubes.vm.adminvm.AdminVM(
                self, None, qid=0, name='dom0'))

        # stage 3: load global properties
        self.load_properties(load_stage=3)

        # stage 4: fill all remaining VM properties
        for vm in self.domains:
            vm.load_properties(load_stage=4)

        # stage 5: misc fixups

        self.property_require('default_fw_netvm', allow_none=True)
        self.property_require('default_netvm', allow_none=True)
        self.property_require('default_template')
        self.property_require('clockvm', allow_none=True)
        self.property_require('updatevm', allow_none=True)

        # Disable ntpd in ClockVM - to not conflict with ntpdate (both are
        # using 123/udp port)
        if hasattr(self, 'clockvm') and self.clockvm is not None:
            if 'ntpd' in self.clockvm.services:
                if self.clockvm.services['ntpd']:
                    self.log.warning("VM set as clockvm ({!r}) has enabled "
                        "'ntpd' service! Expect failure when syncing time in "
                        "dom0.".format(self.clockvm))
            else:
                self.clockvm.services['ntpd'] = False

        for vm in self.domains:
            vm.events_enabled = True
            vm.fire_event('domain-loaded')

        # get a file timestamp (before closing it - still holding the lock!),
        #  to detect whether anyone else have modified it in the meantime
        self.__load_timestamp = os.path.getmtime(self._store)
        # intentionally do not call explicit unlock
        fh.close()
        del fh


    def __xml__(self):
        element = lxml.etree.Element('qubes')

        element.append(self.xml_labels())
        element.append(self.xml_properties())

        domains = lxml.etree.Element('domains')
        for vm in self.domains:
            domains.append(vm.__xml__())
        element.append(domains)

        return element


    def save(self):
        '''Save all data to qubes.xml

        There are several problems with saving :file:`qubes.xml` which must be
        mitigated:

        - Running out of disk space. No space left should not result in empty
          file. This is done by writing to temporary file and then renaming.
        - Attempts to write two or more files concurrently. This is done by
          sophisticated locking.

        :throws EnvironmentError: failure on saving
        '''

        while True:
            fd_old = os.open(self._store, os.O_RDWR | os.O_CREAT)
            if os.name == 'posix':
                fcntl.lockf(fd_old, fcntl.LOCK_EX)
            elif os.name == 'nt':
                # pylint: disable=protected-access
                overlapped = pywintypes.OVERLAPPED()
                win32file.LockFileEx(
                    win32file._get_osfhandle(fd_old),
                    win32con.LOCKFILE_EXCLUSIVE_LOCK, 0, -0x10000, overlapped)

            # While we were waiting for lock, someone could have unlink()ed (or
            # rename()d) our file out of the filesystem. We have to ensure we
            # got lock on something linked to filesystem. If not, try again.
            if os.fstat(fd_old) == os.stat(self._store):
                break
            else:
                os.close(fd_old)

        if self.__load_timestamp:
            current_file_timestamp = os.path.getmtime(self._store)
            if current_file_timestamp != self.__load_timestamp:
                os.close(fd_old)
                raise qubes.exc.QubesException(
                    "Someone else modified qubes.xml in the meantime")

        fh_new = tempfile.NamedTemporaryFile(prefix=self._store, delete=False)
        lxml.etree.ElementTree(self.__xml__()).write(
            fh_new, encoding='utf-8', pretty_print=True)
        fh_new.flush()
        os.chmod(fh_new.name, 0660)
        os.chown(fh_new.name, -1, grp.getgrnam('qubes').gr_gid)
        os.rename(fh_new.name, self._store)

        # intentionally do not call explicit unlock to not unlock the file
        # before all buffers are flushed
        fh_new.close()
        # update stored mtime, in case of multiple save() calls without
        # loading qubes.xml again
        self.__load_timestamp = os.path.getmtime(self._store)
        os.close(fd_old)


    @classmethod
    def create_empty_store(cls, *args, **kwargs):
        self = cls(*args, load=False, **kwargs)
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
        self.domains.add(
            qubes.vm.adminvm.AdminVM(self, None, qid=0, name='dom0'))
        self.save()

        return self


    def xml_labels(self):
        '''Serialise labels

        :rtype: lxml.etree._Element
        '''

        labels = lxml.etree.Element('labels')
        for label in sorted(self.labels.values(), key=lambda labl: labl.index):
            labels.append(label.__xml__())
        return labels


    def add_new_vm(self, cls, qid=None, **kwargs):
        '''Add new Virtual Machine to colletion

        '''

        if qid is None:
            qid = self.domains.get_new_unused_qid()

        # handle default template; specifically allow template=None (do not
        # override it with default template)
        if 'template' not in kwargs and hasattr(cls, 'template'):
            kwargs['template'] = self.default_template

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


    @qubes.events.handler('domain-pre-deleted')
    def on_domain_pre_deleted(self, event, vm):
        # pylint: disable=unused-argument
        if isinstance(vm, qubes.vm.templatevm.TemplateVM):
            appvms = self.domains.get_vms_based_on(vm)
            if appvms:
                raise qubes.exc.QubesException(
                    'Cannot remove template that has dependent AppVMs. '
                    'Affected are: {}'.format(', '.join(
                        vm.name for name in sorted(appvms))))


    @qubes.events.handler('domain-deleted')
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
        if 'ntpd' in newvalue.services:
            if newvalue.services['ntpd']:
                raise qubes.exc.QubesVMError(newvalue,
                    'Cannot set {!r} as {!r} since it has ntpd enabled.'.format(
                        newvalue.name, name))
        else:
            newvalue.services['ntpd'] = False


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
                vm.fire_event('property-del:netvm', 'netvm', newvalue, oldvalue)


    @qubes.events.handler('property-set:default_netvm')
    def on_property_set_default_netvm(self, event, name, newvalue,
            oldvalue=None):
        # pylint: disable=unused-argument
        for vm in self.domains:
            if vm.provides_network and vm.property_is_default('netvm'):
                # fire property-del:netvm as it is responsible for resetting
                # netvm to it's default value
                vm.fire_event('property-del:netvm', 'netvm', newvalue, oldvalue)


# load plugins
import qubes._pluginloader
