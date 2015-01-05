#!/usr/bin/python -O

import collections
import unittest

import qubes.events

class TestEmitter(qubes.events.Emitter):
    '''Dummy event emitter which records events fired on it.

    Events are counted in :py:attr:`fired_events` attribute, which is
    :py:class:`collections.Counter` instance. For each event, ``(event, args,
    kwargs)`` object is counted. *event* is event name (a string), *args* is
    tuple with positional arguments and *kwargs* is sorted tuple of items from
    keyword arguments.

    >>> emitter = TestEmitter()
    >>> emitter.fired_events
    Counter()
    >>> emitter.fire_event('event', 1, 2, 3, spam='eggs', foo='bar')
    >>> emitter.fired_events
    Counter({('event', (1, 2, 3), (('foo', 'bar'), ('spam', 'eggs'))): 1})
    '''
    def __init__(self, *args, **kwargs):
        super(TestEmitter, self).__init__(*args, **kwargs)

        #: :py:class:`collections.Counter` instance
        self.fired_events = collections.Counter()

    def fire_event(self, event, *args, **kwargs):
        super(TestEmitter, self).fire_event(event, *args, **kwargs)
        self.fired_events[(event, args, tuple(sorted(kwargs.items())))] += 1

    def fire_event_pre(self, event, *args, **kwargs):
        super(TestEmitter, self).fire_event_pre(event, *args, **kwargs)
        self.fired_events[(event, args, tuple(sorted(kwargs.items())))] += 1


class QubesTestCase(unittest.TestCase):
    '''Base class for Qubes unit tests.

    '''
    def __str__(self):
        return '{}/{}/{}'.format(
            '.'.join(self.__class__.__module__.split('.')[2:]),
            self.__class__.__name__,
            self._testMethodName)


    def assertEventFired(self, emitter, event, args=[], kwargs=[]):
        '''Check whether event was fired on given emitter and fail if it did
        not.

        :param TestEmitter emitter: emitter which is being checked
        :param str event: event identifier
        :param list args: when given, all items must appear in args passed to event
        :param list kwargs: when given, all items must appear in kwargs passed to event
        '''

        for ev, ev_args, ev_kwargs in emitter.fired_events:
            if ev != event:
                continue
            if any(i not in ev_args for i in args):
                continue
            if any(i not in ev_kwargs for i in kwargs):
                continue

            return

        self.fail('event {!r} did not fire on {!r}'.format(event, emitter))


    def assertEventNotFired(self, emitter, event, args=[], kwargs=[]):
        '''Check whether event was fired on given emitter. Fail if it did.

        :param TestEmitter emitter: emitter which is being checked
        :param str event: event identifier
        :param list args: when given, all items must appear in args passed to event
        :param list kwargs: when given, all items must appear in kwargs passed to event
        '''

        for ev, ev_args, ev_kwargs in emitter.fired_events:
            if ev != event:
                continue
            if any(i not in ev_args for i in args):
                continue
            if any(i not in ev_kwargs for i in kwargs):
                continue

            self.fail('event {!r} did fire on {!r}'.format(event, emitter))

        return
