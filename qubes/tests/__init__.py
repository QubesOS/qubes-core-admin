#!/usr/bin/python -O

import collections
import unittest

import lxml.etree

import qubes.config
import qubes.events


#: :py:obj:`True` if running in dom0, :py:obj:`False` otherwise
in_dom0 = False

try:
    import libvirt
    libvirt.openReadOnly(qubes.config.defaults['libvirt_uri']).close()
    in_dom0 = True
    del libvirt
except libvirt.libvirtError:
    pass


def skipUnlessDom0(test_item):
    '''Decorator that skips test outside dom0.

    Some tests (especially integration tests) have to be run in more or less
    working dom0. This is checked by connecting to libvirt.
    '''

    return unittest.skipUnless(in_dom0, 'outside dom0')(test_item)


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


    def assertXMLEqual(self, xml1, xml2):
        '''Check for equality of two XML objects.

        :param xml1: first element
        :param xml2: second element
        :type xml1: :py:class:`lxml.etree._Element`
        :type xml2: :py:class:`lxml.etree._Element`
        '''
        self.assertEqual(xml1.tag, xml2.tag)
        self.assertEqual(xml1.text, xml2.text)
        self.assertItemsEqual(xml1.keys(), xml2.keys())
        for key in xml1.keys():
            self.assertEqual(xml1.get(key), xml2.get(key))


    def assertEventFired(self, emitter, event, args=[], kwargs=[]):
        '''Check whether event was fired on given emitter and fail if it did
        not.

        :param emitter: emitter which is being checked
        :type emitter: :py:class:`TestEmitter`
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

        :param emitter: emitter which is being checked
        :type emitter: :py:class:`TestEmitter`
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


    def assertXMLIsValid(self, xml, file=None, schema=None):
        '''Check whether given XML fulfills Relax NG schema.

        Schema can be given in a couple of ways:

        - As separate file. This is most common, and also the only way to
          handle file inclusion. Call with file name as second argument. 

        - As string containing actual schema. Put that string in *schema*
          keyword argument.

        :param lxml.etree._Element xml: XML element instance to check
        :param str file: filename of Relax NG schema
        :param str schema: optional explicit schema string
        '''

        if schema is not None and file is None:
            relaxng = schema
            if isinstance(relaxng, str):
                relaxng = lxml.etree.XML(relaxng)
            if isinstance(relaxng, lxml.etree._Element):
                relaxng = lxml.etree.RelaxNG(relaxng)

        elif file is not None and schema is None:
            relaxng = lxml.etree.RelaxNG(file=file)

        else:
            raise TypeError("There should be excactly one of 'file' and "
                "'schema' arguments specified.")

        # We have to be extra careful here in case someone messed up with
        # self.failureException. It should by default be AssertionError, just
        # what is spewed by RelaxNG(), but who knows what might happen.
        try:
            relaxng.assert_(xml)
        except self.failureException:
            raise
        except AssertionError as e:
            self.fail(str(e))
