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

'''
Qubes OS

:copyright: © 2010-2015 Invisible Things Lab
'''

import builtins
import collections.abc
import os
import os.path
import string

import lxml.etree
import qubes.config
import qubes.events
import qubes.exc

__author__ = 'Invisible Things Lab'
__license__ = 'GPLv2 or later'
__version__ = 'R3'


class Label:
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

    def __str__(self):
        return self.name

    def __repr__(self):
        return '{}({!r}, {!r}, {!r})'.format(
            self.__class__.__name__,
            self.index,
            self.color,
            self.name)

    def __eq__(self, other):
        if isinstance(other, Label):
            return self.name == other.name
        return NotImplemented

    def __hash__(self):
        return hash(self.name)

    @builtins.property
    def icon_path(self):
        '''Icon path

        .. deprecated:: 2.0
           use :py:meth:`PyQt4.QtGui.QIcon.fromTheme` and :py:attr:`icon`
        '''
        return os.path.join(qubes.config.system_path['qubes_icon_dir'],
            self.icon) + ".png"


    @builtins.property
    def icon_path_dispvm(self):
        '''Icon path

        .. deprecated:: 2.0
           use :py:meth:`PyQt4.QtGui.QIcon.fromTheme` and :py:attr:`icon_dispvm`
        '''
        return os.path.join(qubes.config.system_path['qubes_icon_dir'],
            self.icon_dispvm) + ".png"


class property:  # pylint: disable=redefined-builtin,invalid-name
    '''Qubes property.

    This class holds one property that can be saved to and loaded from
    :file:`qubes.xml`. It is used for both global and per-VM properties.

    Property can be unset by ordinary ``del`` statement or assigning
    :py:attr:`DEFAULT` special value to it. After deletion (or before first
    assignment/load) attempting to read a property will get its default value
    or, when no default, py:class:`exceptions.AttributeError`.

    :param str name: name of the property
    :param collections.abc.Callable setter: if not :py:obj:`None`, this is \
        used to initialise value; first parameter to the function is holder \
        instance and the second is value; this is called before ``type``
    :param collections.abc.Callable saver: function to coerce value to \
        something readable by setter
    :param type type: if not :py:obj:`None`, value is coerced to this type
    :param object default: default value; if callable, will be called with \
        holder as first argument
    :param int load_stage: stage when property should be loaded (see \
        :py:class:`Qubes` for description of stages)
    :param int order: order of evaluation (bigger order values are later)
    :param bool clone: :py:meth:`PropertyHolder.clone_properties` will not \
        include this property by default if :py:obj:`False`
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
            save_via_ref=False, clone=True,
            doc=None):
        # pylint: disable=redefined-builtin
        self.__name__ = name
        if setter is None and type is bool:
            setter = qubes.property.bool
        self._setter = setter
        self._saver = saver if saver is not None else (
            lambda self, prop, value: str(value))
        self.type = type
        self._default = default
        self._default_function = None
        if isinstance(default, collections.abc.Callable):
            self._default_function = default

        self._write_once = write_once
        self.order = order
        self.load_stage = load_stage
        self.save_via_ref = save_via_ref
        self.clone = clone
        self.__doc__ = doc
        self._attr_name = '_qubesprop_' + name

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
            return self.get_default(instance)

    def get_default(self, instance):
        if self._default is self._NO_DEFAULT:
            raise AttributeError(
                'property {!r} have no default'.format(self.__name__))
        if self._default_function:
            return self._default_function(instance)
        return self._default

    def __set__(self, instance, value):
        self._enforce_write_once(instance)

        if value is self.__class__.DEFAULT:
            self.__delete__(instance)
            return

        try:
            if instance.events_enabled:
                oldvalue = getattr(instance, self.__name__)
                has_oldvalue = True
            else:
                has_oldvalue = False
        except AttributeError:
            has_oldvalue = False

        if self._setter is not None:
            value = self._setter(instance, self, value)
        if self.type not in (None, type(value)):
            value = self.type(value)

        if has_oldvalue:
            instance.fire_event('property-pre-set:' + self.__name__,
                pre_event=True,
                name=self.__name__, newvalue=value, oldvalue=oldvalue)
        else:
            instance.fire_event('property-pre-set:' + self.__name__,
                pre_event=True,
                name=self.__name__, newvalue=value)

        instance._property_init(self, value)  # pylint: disable=protected-access

        if has_oldvalue:
            instance.fire_event('property-set:' + self.__name__,
                name=self.__name__, newvalue=value, oldvalue=oldvalue)
        else:
            instance.fire_event('property-set:' + self.__name__,
                name=self.__name__, newvalue=value)


    def __delete__(self, instance):
        self._enforce_write_once(instance)

        try:
            oldvalue = getattr(instance, self.__name__)
            has_oldvalue = True
        except AttributeError:
            has_oldvalue = False

        if has_oldvalue:
            instance.fire_event('property-pre-reset:' + self.__name__,
                pre_event=True,
                name=self.__name__, oldvalue=oldvalue)
            # deprecated, to be removed in Qubes 5.0
            instance.fire_event('property-pre-del:' + self.__name__,
                pre_event=True,
                name=self.__name__, oldvalue=oldvalue)
            try:
                delattr(instance, self._attr_name)
            except AttributeError:
                pass
            instance.fire_event('property-reset:' + self.__name__,
                name=self.__name__, oldvalue=oldvalue)
            # deprecated, to be removed in Qubes 5.0
            instance.fire_event('property-del:' + self.__name__,
                name=self.__name__, oldvalue=oldvalue)

        else:
            instance.fire_event('property-pre-reset:' + self.__name__,
                pre_event=True,
                name=self.__name__)
            # deprecated, to be removed in Qubes 5.0
            instance.fire_event('property-pre-del:' + self.__name__,
                pre_event=True,
                name=self.__name__)
            instance.fire_event('property-reset:' + self.__name__,
                name=self.__name__)
            # deprecated, to be removed in Qubes 5.0
            instance.fire_event('property-del:' + self.__name__,
                name=self.__name__)


    def __repr__(self):
        default = ' default={!r}'.format(self._default) \
            if self._default is not self._NO_DEFAULT \
            else ''
        return '<{} object at {:#x} name={!r}{}>'.format(
            self.__class__.__name__, id(self), self.__name__, default)

    def __str__(self):
        return self.__name__

    def __hash__(self):
        return hash(self.__name__)

    def __lt__(self, other):
        if isinstance(other, property):
            return (self.load_stage, self.order, self.__name__) <\
                   (other.load_stage, other.order, other.__name__)
        return NotImplemented

    def __eq__(self, other):
        if isinstance(other, str):
            return self.__name__ == other
        return isinstance(other, property) and self.__name__ == other.__name__


    def _enforce_write_once(self, instance):
        if self._write_once and not instance.property_is_default(self):
            raise AttributeError(
                'property {!r} is write-once and already set'.format(
                    self.__name__))

    def sanitize(self, *, untrusted_newvalue):
        '''Coarse sanitization of value to be set, before sending it to a
        setter. Can raise QubesValueError if the value is invalid.

        :param untrusted_newvalue: value to be validated
        :return: sanitized value
        :raises: qubes.exc.QubesValueError
        '''
        # do not treat type='str' as sufficient validation
        if self.type is not None and self.type is not str:
            # assume specific type will preform enough validation
            try:
                untrusted_newvalue = untrusted_newvalue.decode('ascii',
                    errors='strict')
            except UnicodeDecodeError:
                raise qubes.exc.QubesValueError
            if self.type is bool:
                return self.bool(None, None, untrusted_newvalue)
            try:
                return self.type(untrusted_newvalue)
            except ValueError:
                raise qubes.exc.QubesValueError
        else:
            # 'str' or not specified type
            try:
                untrusted_newvalue = untrusted_newvalue.decode('ascii',
                    errors='strict')
            except UnicodeDecodeError:
                raise qubes.exc.QubesValueError
            allowed_set = string.printable
            if not all(x in allowed_set for x in untrusted_newvalue):
                raise qubes.exc.QubesValueError(
                    'Invalid characters in property value')
            return untrusted_newvalue


    #
    # exceptions
    #

    class DontSave(Exception):
        '''This exception may be raised from saver to sign that property should
        not be saved.
        '''

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

        :throws qubes.exc.QubesPropertyValueError: always
        ''' # pylint: disable=bad-staticmethod-argument,unused-argument

        raise qubes.exc.QubesPropertyValueError(
            self, self.property_get_def(prop), value,
            'property {!r} on {} instance cannot be set'.format(
                prop.__name__, self.__class__.__name__))


    @staticmethod
    def bool(self, prop, value):
        '''Property setter for boolean properties.

        It accepts (case-insensitive) ``'0'``, ``'no'`` and ``false`` as
        :py:obj:`False` and ``'1'``, ``'yes'`` and ``'true'`` as
        :py:obj:`True`.
        ''' # pylint: disable=bad-staticmethod-argument,unused-argument

        if isinstance(value, str):
            lcvalue = value.lower()
            if lcvalue in ('0', 'no', 'false', 'off'):
                return False
            if lcvalue in ('1', 'yes', 'true', 'on'):
                return True
            raise qubes.exc.QubesValueError(
                'Invalid literal for boolean property: {!r}'.format(value))

        return bool(value)


def stateless_property(func):
    '''Decorator similar to :py:class:`builtins.property`, but for properties
    exposed through management API (including qvm-prefs etc)'''
    return property(func.__name__,
        setter=property.forbidden,
        saver=property.dontsave,
        default=func,
        doc=func.__doc__)


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

            This event is deprecated and will be removed in Qubes 5.0.
            Use property-reset instead.

            :param name: Property name
            :param oldvalue: Old value of the property

        .. event:: property-pre-del:<propname> \
                (subject, event, name[, oldvalue])

            Fired before property gets deleted (is set to default). Signature
            is variable, *oldvalue* is present only if there was an old value.

            This event is deprecated and will be removed in Qubes 5.0.
            Use property-pre-reset instead.

            :param name: Property name
            :param oldvalue: Old value of the property

        .. event:: property-reset:<propname> \
                (subject, event, name[, oldvalue])

            Fired when property gets reset to the (possibly dynamic) default.
            This even may be also fired when the property is already in
            "default" state, but the calculated default value changes.
            Signature is variable, *oldvalue* is present only if there was an
            old value.

            :param name: Property name
            :param oldvalue: Old value of the property

        .. event:: property-pre-reset:<propname> \
                (subject, event, name[, oldvalue])

            Fired before property gets reset to the (possibly dynamic) default.
            Signature is variable, *oldvalue* is present only if there was an
            old value.

            :param name: Property name
            :param oldvalue: Old value of the property

        .. event:: clone-properties (subject, event, src, proplist)

            :param src: object, from which we are cloning
            :param proplist: list of properties

    Members:
    '''

    def __init__(self, xml, **kwargs):
        self.xml = xml

        propvalues = {}

        all_names = self.property_dict()
        for key in list(kwargs):
            if not key in all_names:
                continue
            propvalues[key] = kwargs.pop(key)

        super().__init__(**kwargs)

        for key, value in propvalues.items():
            setattr(self, key, value)

        if self.xml is not None:
            # check if properties are appropriate
            for node in self.xml.xpath('./properties/property'):
                name = node.get('name')
                if name not in all_names:
                    raise TypeError(
                        'property {!r} not applicable to {!r}'.format(
                            name, self.__class__.__name__))

    # pylint: disable=too-many-nested-blocks
    @classmethod
    def property_dict(cls, load_stage=None):
        '''List all properties attached to this VM's class

        :param load_stage: Filter by load stage
        :type load_stage: :py:func:`int` or :py:obj:`None`
        '''

        # use cls.__dict__ since we must not look at parent classes
        if "_property_dict" not in cls.__dict__:
            cls._property_dict = {}
        memo = cls._property_dict

        if load_stage not in memo:
            props = {}
            if load_stage is None:
                for class_ in cls.__mro__:
                    for name, prop in class_.__dict__.items():
                        # don't overwrite props with those from base classes
                        if name not in props:
                            if isinstance(prop, property):
                                assert name == prop.__name__
                                props[name] = prop
            else:
                for prop in cls.property_dict().values():
                    if prop.load_stage == load_stage:
                        props[prop.__name__] = prop
            memo[load_stage] = props

        return memo[load_stage]

    @classmethod
    def property_list(cls, load_stage=None):
        '''List all properties attached to this VM's class

        :param load_stage: Filter by load stage
        :type load_stage: :py:func:`int` or :py:obj:`None`
        '''

        # use cls.__dict__ since we must not look at parent classes
        if "_property_list" not in cls.__dict__:
            cls._property_list = {}
        memo = cls._property_list

        if load_stage not in memo:
            memo[load_stage] = sorted(cls.property_dict(load_stage).values())

        return memo[load_stage]

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

    def property_get_default(self, prop):
        '''Get property default value.

        :param qubes.property or str prop: property object of particular
        interest
        '''

        return self.property_get_def(prop).get_default(self)


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

        props = cls.property_dict()
        if prop in props:
            return props[prop]

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
        :param iterable proplist: list of properties \
            (:py:obj:`None` or omit for all properties except those with \
            :py:attr:`property.clone` set to :py:obj:`False`)
        '''

        if proplist is None:
            proplist = [prop for prop in self.property_list()
                if prop.clone]
        else:
            proplist = [prop for prop in self.property_list()
                if prop.__name__ in proplist or prop in proplist]

        for prop in proplist:
            try:
                # pylint: disable=protected-access
                self._property_init(prop, getattr(src, prop._attr_name))
            except AttributeError:
                continue

        self.fire_event('clone-properties', src=src, proplist=proplist)


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
                msg = 'Property {!r} cannot be None'.format(prop)
                if hard:
                    raise ValueError(msg)
                self.log.fatal(msg)
        except AttributeError:
            # pylint: disable=no-member
            msg = 'Required property {!r} not set on {!r}'.format(prop, self)
            if hard:
                raise ValueError(msg)
            # pylint: disable=no-member
            self.log.fatal(msg)


    def close(self):
        super().close()

        # Remove all properties -- somewhere in them there are cyclic
        # references. This just removes all the properties, just in case.
        # They are removed directly, bypassing write_once.
        for prop in self.property_list():
            # pylint: disable=protected-access
            try:
                delattr(self, prop._attr_name)
            except AttributeError:
                pass


# pylint: disable=wrong-import-position
from qubes.vm import VMProperty
from qubes.app import Qubes

__all__ = [
    'Label',
    'PropertyHolder',
    'Qubes',
    'VMProperty',
    'property',
]
