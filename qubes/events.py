#
# The Qubes OS Project, https://www.qubes-os.org/
#
# Copyright (C) 2014-2015  Joanna Rutkowska <joanna@invisiblethingslab.com>
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

'''Qubes events.

Events are fired when something happens, like VM start or stop, property change
etc.
'''
import asyncio
import collections
import fnmatch

import itertools


def handler(*events):
    '''Event handler decorator factory.

    To hook an event, decorate a method in your plugin class with this
    decorator.

    Some event handlers may be async functions.
    See appropriate event documentation for details.

    .. note::
        For hooking events from extensions, see :py:func:`qubes.ext.handler`.

    :param str events: events names, can contain basic wildcards (`*`, `?`)
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
                cls.__handlers__[event].add(attr)


class Emitter(metaclass=EmitterMeta):
    '''Subject that can emit events.

    By default all events are disabled not to interfere with loading from XML.
    To enable event dispatch, set :py:attr:`events_enabled` to :py:obj:`True`.
    '''

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not hasattr(self, 'events_enabled'):
            self.events_enabled = False
        self.__handlers__ = collections.defaultdict(set)

    def close(self):
        self.events_enabled = False

    def add_handler(self, event, func):
        '''Add event handler to subject's class.

        This is class method, it is invalid to call it on object instance.

        :param str event: event identificator
        :param collections.abc.Callable handler: handler callable
        '''

        # pylint: disable=no-member
        self.__handlers__[event].add(func)

    def remove_handler(self, event, func):
        '''Remove event handler from subject's class.

        This is class method, it is invalid to call it on object instance.

        This method must be called on the same class as
        :py:meth:`add_handler` was called to register the handler.

        :param str event: event identificator
        :param collections.abc.Callable handler: handler callable
        '''

        # pylint: disable=no-member
        self.__handlers__[event].remove(func)

    def _fire_event(self, event, kwargs, pre_event=False):
        '''Fire event for classes in given order.

        Do not use this method. Use :py:meth:`fire_event`.
        '''

        if not self.events_enabled:
            return [], []

        order = itertools.chain((self,), self.__class__.__mro__)
        if not pre_event:
            order = reversed(list(order))

        effects = []
        async_effects = []
        for i in order:
            try:
                handlers_dict = i.__handlers__
            except AttributeError:
                continue
            handlers = [h_func for h_name, h_func_set in handlers_dict.items()
                        for h_func in h_func_set
                        if fnmatch.fnmatch(event, h_name)]
            for func in sorted(handlers,
                    key=(lambda handler: hasattr(handler, 'ha_bound')),
                    reverse=True):
                effect = func(self, event, **kwargs)
                if asyncio.iscoroutinefunction(func):
                    async_effects.append(effect)
                elif effect is not None:
                    effects.extend(effect)
        return effects, async_effects

    def fire_event(self, event, pre_event=False, **kwargs):
        '''Call all handlers for an event.

        Handlers are called for class and all parent classes, in **reversed**
        or **true** (depending on *pre_event* parameter)
        method resolution order. For each class first are called bound handlers
        (specified in class definition), then handlers from extensions. Aside
        from above, remaining order is undefined.

        This method call only synchronous handlers. If any asynchronous
        handler is registered for the event, :py:class:``RuntimeError`` is
        raised.

        .. seealso::
            :py:meth:`fire_event_async`

        :param str event: event identifier
        :param pre_event: is this -pre- event? reverse handlers calling order
        :returns: list of effects

        All *kwargs* are passed verbatim. They are different for different
        events.
        '''

        sync_effects, async_effects = self._fire_event(event, kwargs,
            pre_event=pre_event)
        if async_effects:
            raise RuntimeError(
                'unexpected async-handler(s) {!r} for sync event {!s}'.format(
                    async_effects, event))
        return sync_effects


    async def fire_event_async(self, event, pre_event=False, **kwargs):
        '''Call all handlers for an event, allowing async calls.

        Handlers are called for class and all parent classes, in **reversed**
        or **true** (depending on *pre_event* parameter)
        method resolution order. For each class first are called bound handlers
        (specified in class definition), then handlers from extensions. Aside
        from above, remaining order is undefined.

        This method call both synchronous and asynchronous handlers. Order of
        asynchronous calls is, by definition, undefined.

        .. seealso::
            :py:meth:`fire_event`

        :param str event: event identifier
        :param pre_event: is this -pre- event? reverse handlers calling order
        :returns: list of effects

        All *kwargs* are passed verbatim. They are different for different
        events.
        '''

        sync_effects, async_effects = self._fire_event(event,
            kwargs, pre_event=pre_event)
        effects = sync_effects
        if async_effects:
            async_tasks, _ = await asyncio.wait(map(asyncio.create_task,
                                                    async_effects))
            for task in async_tasks:
                effect = task.result()
                if effect is not None:
                    effects.extend(effect)
        return effects
