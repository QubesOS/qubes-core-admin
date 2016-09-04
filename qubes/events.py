#!/usr/bin/python2 -O
# vim: fileencoding=utf-8

#
# The Qubes OS Project, https://www.qubes-os.org/
#
# Copyright (C) 2014-2015  Joanna Rutkowska <joanna@invisiblethingslab.com>
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

'''Qubes events.

Events are fired when something happens, like VM start or stop, property change
etc.
'''

import collections


def handler(*events):
    '''Event handler decorator factory.

    To hook an event, decorate a method in your plugin class with this
    decorator.

    It probably makes no sense to specify more than one handler for specific
    event in one class, because handlers are not run concurrently and there is
    no guarantee of the order of execution.

    .. note::
        For hooking events from extensions, see :py:func:`qubes.ext.handler`.

    :param str event: event type
    '''

    def decorator(func):
        # pylint: disable=missing-docstring
        func.ha_events = events
        # mark class own handler (i.e. not from extension)
        func.ha_bound = True
        return func

    return decorator


def ishandler(obj):
    '''Test if a method is hooked to an event.

    :param object o: suspected hook
    :return: :py:obj:`True` when function is a hook, :py:obj:`False` otherwise
    :rtype: bool
    '''

    return callable(obj) \
        and hasattr(obj, 'ha_events')


class EmitterMeta(type):
    '''Metaclass for :py:class:`Emitter`'''
    def __init__(cls, name, bases, dict_):
        super(EmitterMeta, cls).__init__(name, bases, dict_)
        cls.__handlers__ = collections.defaultdict(set)

        try:
            propnames = set(prop.__name__ for prop in cls.property_list())
        except AttributeError:
            propnames = set()

        for attr in dict_:
            if attr in propnames:
                # we have to be careful, not to getattr() on properties which
                # may be unset
                continue

            attr = dict_[attr]
            if not ishandler(attr):
                continue

            for event in attr.ha_events:
                cls.add_handler(event, attr)


class Emitter(object):
    '''Subject that can emit events.

    By default all events are disabled not to interfere with loading from XML.
    To enable event dispatch, set :py:attr:`events_enabled` to :py:obj:`True`.
    '''

    __metaclass__ = EmitterMeta

    def __init__(self, *args, **kwargs):
        super(Emitter, self).__init__(*args, **kwargs)
        if not hasattr(self, 'events_enabled'):
            self.events_enabled = False


    @classmethod
    def add_handler(cls, event, func):
        '''Add event handler to subject's class.

        :param str event: event identificator
        :param collections.Callable handler: handler callable
        '''

        # pylint: disable=no-member
        cls.__handlers__[event].add(func)


    def _fire_event_in_order(self, order, event, *args, **kwargs):
        '''Fire event for classes in given order.

        Do not use this method. Use :py:meth:`fire_event` or
        :py:meth:`fire_event_pre`.
        '''

        if not self.events_enabled:
            return []

        effects = []
        for cls in order:
            if not hasattr(cls, '__handlers__'):
                continue
            for func in sorted(cls.__handlers__[event],
                    key=(lambda handler: hasattr(handler, 'ha_bound')),
                    reverse=True):
                effect = func(self, event, *args, **kwargs)
                if effect is not None:
                    effects.extend(effect)
        return effects


    def fire_event(self, event, *args, **kwargs):
        '''Call all handlers for an event.

        Handlers are called for class and all parent classess, in **reversed**
        method resolution order. For each class first are called bound handlers
        (specified in class definition), then handlers from extensions. Aside
        from above, remaining order is undefined.

        .. seealso::
            :py:meth:`fire_event_pre`

        :param str event: event identificator
        :returns: list of effects

        All *args* and *kwargs* are passed verbatim. They are different for
        different events.
        '''

        return self._fire_event_in_order(reversed(self.__class__.__mro__),
            event, *args, **kwargs)


    def fire_event_pre(self, event, *args, **kwargs):
        '''Call all handlers for an event.

        Handlers are called for class and all parent classess, in **true**
        method resolution order. This is intended for ``-pre-`` events, where
        order of invocation should be reversed.

        .. seealso::
            :py:meth:`fire_event`

        :param str event: event identificator
        :returns: list of effects

        All *args* and *kwargs* are passed verbatim. They are different for
        different events.
        '''

        return self._fire_event_in_order(self.__class__.__mro__,
            event, *args, **kwargs)
