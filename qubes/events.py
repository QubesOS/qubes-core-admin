#!/usr/bin/python2 -O

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

    def decorator(f):
        f.ha_events = events
        return f

    return decorator


def ishandler(o):
    '''Test if a method is hooked to an event.

    :param object o: suspected hook
    :return: :py:obj:`True` when function is a hook, :py:obj:`False` otherwise
    :rtype: bool
    '''

    return callable(o) \
        and hasattr(o, 'ha_events')


class EmitterMeta(type):
    '''Metaclass for :py:class:`Emitter`'''
    def __init__(cls, name, bases, dict_):
        super(type, cls).__init__(name, bases, dict_)
        cls.__handlers__ = collections.defaultdict(set)

        try:
            propnames = set(prop.__name__ for prop in cls.get_props_list())
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
    '''Subject that can emit events
    '''

    __metaclass__ = EmitterMeta

    def __init__(self, *args, **kwargs):
        super(Emitter, self).__init__(*args, **kwargs)
        self.events_enabled = True


    @classmethod
    def add_handler(cls, event, handler):
        '''Add event handler to subject's class

        :param str event: event identificator
        :param collections.Callable handler: handler callable
        '''

        cls.__handlers__[event].add(handler)


    def _fire_event_in_order(self, order, event, *args, **kwargs):
        '''Fire event for classes in given order.

        Do not use this method. Use :py:meth:`fire_event` or
        :py:meth:`fire_event_pre`.
        '''

        if not self.events_enabled:
            return

        for cls in order:
            if not hasattr(cls, '__handlers__'):
                continue
            for handler in sorted(cls.__handlers__[event],
                    key=(lambda handler: hasattr(handler, 'ha_bound')),
                    reverse=True):
                handler(self, event, *args, **kwargs)


    def fire_event(self, event, *args, **kwargs):
        '''Call all handlers for an event.

        Handlers are called for class and all parent classess, in **reversed**
        method resolution order. For each class first are called bound handlers
        (specified in class definition), then handlers from extensions. Aside
        from above, remaining order is undefined.

        .. seealso::
            :py:meth:`fire_event_pre`

        :param str event: event identificator

        All *args* and *kwargs* are passed verbatim. They are different for
        different events.
        '''

        self._fire_event_in_order(reversed(self.__class__.__mro__), event,
            *args, **kwargs)


    def fire_event_pre(self, event, *args, **kwargs):
        '''Call all handlers for an event.

        Handlers are called for class and all parent classess, in **true**
        method resolution order. This is intended for ``-pre-`` events, where
        order of invocation should be reversed.

        .. seealso::
            :py:meth:`fire_event`

        :param str event: event identificator

        All *args* and *kwargs* are passed verbatim. They are different for
        different events.
        '''

        self._fire_event_in_order(self.__class__.__mro__, event,
            *args, **kwargs)
