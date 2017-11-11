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

'''Qubes Virtual Machines

'''
import asyncio
import re
import string
import uuid

import lxml.etree

import qubes
import qubes.devices
import qubes.events
import qubes.log

VM_ENTRY_POINT = 'qubes.vm'

def validate_name(holder, prop, value):
    ''' Check if value is syntactically correct VM name '''
    if not isinstance(value, str):
        raise TypeError('VM name must be string, {!r} found'.format(
            type(value).__name__))
    if len(value) > 31:
        if holder is not None and prop is not None:
            raise qubes.exc.QubesPropertyValueError(holder, prop, value,
                '{} value must be shorter than 32 characters'.format(
                    prop.__name__))
        else:
            raise qubes.exc.QubesValueError(
                'VM name must be shorter than 32 characters')

    # this regexp does not contain '+'; if it had it, we should specifically
    # disallow 'lost+found' #1440
    if re.match(r"^[a-zA-Z][a-zA-Z0-9_-]*$", value) is None:
        if holder is not None and prop is not None:
            raise qubes.exc.QubesPropertyValueError(holder, prop, value,
                '{} value contains illegal characters'.format(prop.__name__))
        else:
            raise qubes.exc.QubesValueError(
                'VM name contains illegal characters')
    if value in ('none', 'default'):
        raise qubes.exc.QubesValueError(
            'VM name cannot be \'none\' nor \'default\'')

def setter_label(self, prop, value):
    ''' Helper for setting the domain label '''
    # pylint: disable=unused-argument
    if isinstance(value, qubes.Label):
        return value
    if isinstance(value, str) and value.startswith('label-'):
        return self.app.labels[int(value.split('-', 1)[1])]

    return self.app.get_label(value)


def _setter_qid(self, prop, value):
    ''' Helper for setting the domain qid '''
    # pylint: disable=unused-argument
    value = int(value)
    if not 0 <= value <= qubes.config.max_qid:
        raise ValueError(
            '{} value must be between 0 and qubes.config.max_qid'.format(
                prop.__name__))
    return value

class Features(dict):
    '''Manager of the features.

    Features can have three distinct values: no value (not present in mapping,
    which is closest thing to :py:obj:`None`), empty string (which is
    interpreted as :py:obj:`False`) and non-empty string, which is
    :py:obj:`True`. Anything assigned to the mapping is coerced to strings,
    however if you assign instances of :py:class:`bool`, they are converted as
    described above. Be aware that assigning the number `0` (which is considered
    false in Python) will result in string `'0'`, which is considered true.

    This class inherits from dict, but has most of the methods that manipulate
    the item disarmed (they raise NotImplementedError). The ones that are left
    fire appropriate events on the qube that owns an instance of this class.
    '''

    #
    # Those are the methods that affect contents. Either disarm them or make
    # them report appropriate events. Good approach is to rewrite them carefully
    # using official documentation, but use only our (overloaded) methods.
    #
    def __init__(self, vm, other=None, **kwargs):
        super(Features, self).__init__()
        self.vm = vm
        self.update(other, **kwargs)

    def __delitem__(self, key):
        super(Features, self).__delitem__(key)
        self.vm.fire_event('domain-feature-delete', feature=key)

    def __setitem__(self, key, value):
        if value is None or isinstance(value, bool):
            value = '1' if value else ''
        else:
            value = str(value)
        try:
            oldvalue = self[key]
            has_oldvalue = True
        except KeyError:
            has_oldvalue = False
        super(Features, self).__setitem__(key, value)
        if has_oldvalue:
            self.vm.fire_event('domain-feature-set', feature=key, value=value,
                oldvalue=oldvalue)
        else:
            self.vm.fire_event('domain-feature-set', feature=key, value=value)

    def clear(self):
        for key in tuple(self):
            del self[key]

    def pop(self, _key, _default=None):
        '''Not implemented
        :raises: NotImplementedError
        '''
        raise NotImplementedError()

    def popitem(self):
        '''Not implemented
        :raises: NotImplementedError
        '''
        raise NotImplementedError()

    def setdefault(self, _key, _default=None):
        '''Not implemented
        :raises: NotImplementedError
        '''
        raise NotImplementedError()

    def update(self, other=None, **kwargs):
        if other is not None:
            if hasattr(other, 'keys'):
                for key in other:
                    self[key] = other[key]
            else:
                for key, value in other:
                    self[key] = value

        for key in kwargs:
            self[key] = kwargs[key]

    #
    # end of overriding
    #

    _NO_DEFAULT = object()

    def check_with_template(self, feature, default=_NO_DEFAULT):
        ''' Check if the vm's template has the specified feature. '''
        if feature in self:
            return self[feature]

        if hasattr(self.vm, 'template') and self.vm.template is not None:
            return self.vm.template.features.check_with_template(feature,
                default)

        if default is self._NO_DEFAULT:
            raise KeyError(feature)

        return default


class Tags(set):
    '''Manager of the tags.

    Tags are simple: tag either can be present on qube or not. Tag is a
    simple string consisting of ASCII alphanumeric characters, plus `_` and
    `-`.

    This class inherits from set, but has most of the methods that manipulate
    the item disarmed (they raise NotImplementedError). The ones that are left
    fire appropriate events on the qube that owns an instance of this class.
    '''

    #
    # Those are the methods that affect contents. Either disarm them or make
    # them report appropriate events. Good approach is to rewrite them carefully
    # using official documentation, but use only our (overloaded) methods.
    #
    def __init__(self, vm, seq=()):
        super(Tags, self).__init__()
        self.vm = vm
        self.update(seq)

    def clear(self):
        '''Remove all tags'''
        for item in tuple(self):
            self.remove(item)

    def symmetric_difference_update(self, *args, **kwargs):
        '''Not implemented
        :raises: NotImplementedError
        '''
        raise NotImplementedError()

    def intersection_update(self, *args, **kwargs):
        '''Not implemented
        :raises: NotImplementedError
        '''
        raise NotImplementedError()

    def pop(self):
        '''Not implemented
        :raises: NotImplementedError
        '''
        raise NotImplementedError()

    def discard(self, elem):
        '''Remove a tag if present'''
        if elem in self:
            self.remove(elem)

    def update(self, *others):
        '''Add tags from iterable(s)'''
        for other in others:
            for elem in other:
                self.add(elem)

    def add(self, elem):
        '''Add a tag'''
        allowed_chars = string.ascii_letters + string.digits + '_-'
        if any(i not in allowed_chars for i in elem):
            raise ValueError('Invalid character in tag')
        if elem in self:
            return
        super(Tags, self).add(elem)
        self.vm.fire_event('domain-tag-add', tag=elem)

    def remove(self, elem):
        '''Remove a tag'''
        super(Tags, self).remove(elem)
        self.vm.fire_event('domain-tag-delete', tag=elem)

    #
    # end of overriding
    #

    @staticmethod
    def validate_tag(tag):
        safe_set = string.ascii_letters + string.digits + '-_'
        assert all((x in safe_set) for x in tag)


class BaseVM(qubes.PropertyHolder):
    '''Base class for all VMs

    :param app: Qubes application context
    :type app: :py:class:`qubes.Qubes`
    :param xml: xml node from which to deserialise
    :type xml: :py:class:`lxml.etree._Element` or :py:obj:`None`

    This class is responsible for serializing and deserialising machines and
    provides basic framework. It contains no management logic. For that, see
    :py:class:`qubes.vm.qubesvm.QubesVM`.
    '''
    # pylint: disable=no-member

    uuid = qubes.property('uuid', type=uuid.UUID, write_once=True,
        clone=False,
        doc='UUID from libvirt.')

    name = qubes.property('name', type=str, write_once=True,
        clone=False,
        doc='User-specified name of the domain.')

    qid = qubes.property('qid', type=int, write_once=True,
        setter=_setter_qid,
        clone=False,
        doc='''Internal, persistent identificator of particular domain. Note
            this is different from Xen domid.''')

    label = qubes.property('label',
        setter=setter_label,
        doc='''Colourful label assigned to VM. This is where the colour of the
            padlock is set.''')

    def __init__(self, app, xml, features=None, devices=None, tags=None,
            **kwargs):
        # pylint: disable=redefined-outer-name

        self._qdb_watch_paths = set()
        self._qdb_connection_watch = None

        # self.app must be set before super().__init__, because some property
        # setters need working .app attribute
        #: mother :py:class:`qubes.Qubes` object
        self.app = app

        super(BaseVM, self).__init__(xml, **kwargs)

        #: dictionary of features of this qube
        self.features = Features(self, features)

        #: :py:class:`DeviceManager` object keeping devices that are attached to
        #: this domain
        self.devices = devices or qubes.devices.DeviceManager(self)

        #: user-specified tags
        self.tags = Tags(self, tags or ())

        #: logger instance for logging messages related to this VM
        self.log = None

        #: storage volumes
        self.volumes = {}

        #: storage manager
        self.storage = None

        if hasattr(self, 'name'):
            self.init_log()

    def close(self):
        super().close()

        if self._qdb_connection_watch is not None:
            asyncio.get_event_loop().remove_reader(
                self._qdb_connection_watch.watch_fd())
            self._qdb_connection_watch.close()
            del self._qdb_connection_watch

        del self.app
        del self.features
        del self.storage
        # TODO storage may have circ references, but it doesn't leak fds
        del self.devices
        del self.tags

    def load_extras(self):
        # features
        for node in self.xml.xpath('./features/feature'):
            self.features[node.get('name')] = node.text

        # devices (pci, usb, ...)
        for parent in self.xml.xpath('./devices'):
            devclass = parent.get('class')
            for node in parent.xpath('./device'):
                options = {}
                for option in node.xpath('./option'):
                    options[option.get('name')] = option.text

                device_assignment = qubes.devices.DeviceAssignment(
                    self.app.domains[node.get('backend-domain')],
                    node.get('id'),
                    options,
                    persistent=True
                )
                self.devices[devclass].load_persistent(device_assignment)

        # tags
        for node in self.xml.xpath('./tags/tag'):
            self.tags.add(node.get('name'))

        # SEE:1815 firewall, policy.

    def init_log(self):
        '''Initialise logger for this domain.'''
        self.log = qubes.log.get_vm_logger(self.name)

    def __xml__(self):
        element = lxml.etree.Element('domain')
        element.set('id', 'domain-' + str(self.qid))
        element.set('class', self.__class__.__name__)

        element.append(self.xml_properties())

        features = lxml.etree.Element('features')
        for feature in self.features:
            node = lxml.etree.Element('feature', name=feature)
            node.text = self.features[feature]
            features.append(node)
        element.append(features)

        for devclass in self.devices:
            devices = lxml.etree.Element('devices')
            devices.set('class', devclass)
            for device in self.devices[devclass].assignments(persistent=True):
                node = lxml.etree.Element('device')
                node.set('backend-domain', device.backend_domain.name)
                node.set('id', device.ident)
                for key, val in device.options.items():
                    option_node = lxml.etree.Element('option')
                    option_node.set('name', key)
                    option_node.text = val
                    node.append(option_node)
                devices.append(node)
            element.append(devices)

        tags = lxml.etree.Element('tags')
        for tag in self.tags:
            node = lxml.etree.Element('tag', name=tag)
            tags.append(node)
        element.append(tags)

        return element

    def __repr__(self):
        proprepr = []
        for prop in self.property_list():
            if prop.__name__ in ('name', 'qid'):
                continue
            try:
                proprepr.append('{}={!s}'.format(
                    prop.__name__, getattr(self, prop.__name__)))
            except AttributeError:
                continue

        return '<{} at {:#x} name={!r} qid={!r} {}>'.format(type(self).__name__,
            id(self), self.name, self.qid, ' '.join(proprepr))

    #
    # xml serialising methods
    #

    def create_config_file(self):
        '''Create libvirt's XML domain config file

        '''
        domain_config = self.app.env.select_template([
                'libvirt/xen/by-name/{}.xml'.format(self.name),
                'libvirt/xen-user.xml',
                'libvirt/xen-dist.xml',
                'libvirt/xen.xml',
            ]).render(vm=self)
        return domain_config

    def watch_qdb_path(self, path):
        '''Add a QubesDB path to be watched.

        Each change to the path will cause `domain-qdb-change:path` event to be
        fired.
        You can call this method for example in response to
        `domain-init` and `domain-load` events.
        '''

        if path not in self._qdb_watch_paths:
            self._qdb_watch_paths.add(path)
            if self._qdb_connection_watch:
                self._qdb_connection_watch.watch(path)

    def _qdb_watch_reader(self, loop):
        '''Callback when self._qdb_connection_watch.watch_fd() FD is
        readable.

        Read reported event (watched path change) and fire appropriate event.
        '''
        import qubesdb  # pylint: disable=import-error
        try:
            path = self._qdb_connection_watch.read_watch()
            for watched_path in self._qdb_watch_paths:
                if watched_path == path or (
                            watched_path.endswith('/') and
                            path.startswith(watched_path)):
                    self.fire_event('domain-qdb-change:' + watched_path,
                        path=path)
        except qubesdb.DisconnectedError:
            loop.remove_reader(self._qdb_connection_watch.watch_fd())
            self._qdb_connection_watch.close()
            self._qdb_connection_watch = None

    def start_qdb_watch(self, loop=None):
        '''Start watching QubesDB

        Calling this method in appropriate time is responsibility of child
        class.
        '''
        # cleanup old watch connection first, if any
        if self._qdb_connection_watch is not None:
            asyncio.get_event_loop().remove_reader(
                self._qdb_connection_watch.watch_fd())
            self._qdb_connection_watch.close()

        import qubesdb  # pylint: disable=import-error
        self._qdb_connection_watch = qubesdb.QubesDB(self.name)
        if loop is None:
            loop = asyncio.get_event_loop()
        loop.add_reader(self._qdb_connection_watch.watch_fd(),
            self._qdb_watch_reader, loop)
        for path in self._qdb_watch_paths:
            self._qdb_connection_watch.watch(path)

    @qubes.stateless_property
    def klass(self):
        '''Domain class name'''
        return type(self).__name__

    def libvirt_connected(self):
        pass

    def libvirt_lifecycle_event(self, event, detail):
        pass

class VMProperty(qubes.property):
    '''Property that is referring to a VM

    :param type vmclass: class that returned VM is supposed to be instance of

    and all supported by :py:class:`property` with the exception of ``type`` \
        and ``setter``
    '''

    _none_value = ''

    def __init__(self, name, vmclass=BaseVM, allow_none=False,
            **kwargs):
        if 'type' in kwargs:
            raise TypeError(
                "'type' keyword parameter is unsupported in {}".format(
                    self.__class__.__name__))
        if not issubclass(vmclass, BaseVM):
            raise TypeError(
                "'vmclass' should specify a subclass of qubes.vm.BaseVM")

        super(VMProperty, self).__init__(name,
            saver=(lambda self_, prop, value:
                self._none_value if value is None else value.name),
            **kwargs)
        self.vmclass = vmclass
        self.allow_none = allow_none

    def __set__(self, instance, value):
        if value is self.__class__.DEFAULT:
            self.__delete__(instance)
            return

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

        app = instance if isinstance(instance, qubes.Qubes) else instance.app

        try:
            vm = app.domains[value]
        except KeyError:
            raise qubes.exc.QubesVMNotFoundError(value)

        if not isinstance(vm, self.vmclass):
            raise TypeError('wrong VM class: domains[{!r}] is of type {!s} '
                'and not {!s}'.format(value,
                    vm.__class__.__name__,
                    self.vmclass.__name__))

        super(VMProperty, self).__set__(instance, vm)

    def sanitize(self, *, untrusted_newvalue):
        try:
            untrusted_vmname = untrusted_newvalue.decode('ascii')
        except UnicodeDecodeError:
            raise qubes.exc.QubesValueError
        if untrusted_vmname == '':
            # allow empty VM name for setting VMProperty value, because it's
            # string representation of None (see self._none_value)
            return untrusted_vmname
        validate_name(None, self, untrusted_vmname)
        return untrusted_vmname
