#!/usr/bin/python2 -O

'''Qubes events.

Events are fired when something happens, like VM start or stop, property change
etc.

'''

import collections


def handler(event):
    '''Event handler decorator factory.

    To hook an event, decorate a method in your plugin class with this
    decorator.

    .. note::
        For hooking events from extensions, see :py:func:`qubes.ext.handler`.

    :param str event: event type
    '''

    def decorator(f):
        f.ha_event = event
        f.ha_bound = True
        return f

    return decorator


def ishandler(o):
    '''Test if a method is hooked to an event.

    :param object o: suspected hook
    :return: :py:obj:`True` when function is a hook, :py:obj:`False` otherwise
    :rtype: bool
    '''

    return callable(o) \
        and hasattr(o, 'ha_event')


class EmitterMeta(type):
    '''Metaclass for :py:class:`Emitter`'''
    def __init__(cls, name, bases, dict_):
        super(type, cls).__init__(name, bases, dict_)
        cls.__handlers__ = collections.defaultdict(set)


class Emitter(object):
    '''Subject that can emit events
    '''

    __metaclass__ = EmitterMeta

    def __init__(self, *args, **kwargs):
        super(Emitter, self).__init__(*args, **kwargs)
        self.events_enabled = True

        try:
            propnames = set(prop.__name__ for prop in self.get_props_list())
        except AttributeError:
            propnames = set()

        for attr in dir(self):
            if attr in propnames:
                # we have to be careful, not to getattr() on properties which
                # may be unset
                continue

            attr = getattr(self, attr)
            if not ishandler(attr):
                continue

            self.add_handler(attr.ha_event, attr)


    @classmethod
    def add_handler(cls, event, handler):
        '''Add event handler to subject's class

        :param str event: event identificator
        :param collections.Callable handler: handler callable
        '''

        cls.__handlers__[event].add(handler)


    def fire_event(self, event, *args, **kwargs):
        '''Call all handlers for an event

        :param str event: event identificator

        All *args* and *kwargs* are passed verbatim. They are different for
        different events.
        '''

        if not self.events_enabled:
            return

        for handler in self.__handlers__[event]:
            if hasattr(handler, 'ha_bound'):
                # this is our (bound) method, self is implicit
                handler(event, *args, **kwargs)
            else:
                # this is from extension or hand-added, so we see method as
                # unbound, therefore we need to pass self
                handler(self, event, *args, **kwargs)
