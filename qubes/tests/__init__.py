#!/usr/bin/python2 -O
# vim: fileencoding=utf-8
# pylint: disable=invalid-name

#
# The Qubes OS Project, https://www.qubes-os.org/
#
# Copyright (C) 2014-2015  Joanna Rutkowska <joanna@invisiblethingslab.com>
# Copyright (C) 2014-2015
#                   Marek Marczykowski-Górecki <marmarek@invisiblethingslab.com>
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

import collections
import multiprocessing
import logging
import os
import shutil
import subprocess
import sys
import unittest

import lxml.etree

import qubes.config
import qubes.events

XMLPATH = '/var/lib/qubes/qubes-test.xml'
TEMPLATE = 'fedora-23'
VMPREFIX = 'test-'


#: :py:obj:`True` if running in dom0, :py:obj:`False` otherwise
in_dom0 = False

#: :py:obj:`False` if outside of git repo,
#: path to root of the directory otherwise
in_git = False

try:
    import libvirt
    libvirt.openReadOnly(qubes.config.defaults['libvirt_uri']).close()
    in_dom0 = True
except libvirt.libvirtError:
    pass

try:
    in_git = subprocess.check_output(
        ['git', 'rev-parse', '--show-toplevel']).strip()
    qubes.log.LOGPATH = '/tmp'
    qubes.log.LOGFILE = '/tmp/qubes.log'
except subprocess.CalledProcessError:
    # git returned nonzero, we are outside git repo
    pass
except OSError:
    # command not found; let's assume we're outside
    pass


def skipUnlessDom0(test_item):
    '''Decorator that skips test outside dom0.

    Some tests (especially integration tests) have to be run in more or less
    working dom0. This is checked by connecting to libvirt.
    '''

    return unittest.skipUnless(in_dom0, 'outside dom0')(test_item)


def skipUnlessGit(test_item):
    '''Decorator that skips test outside git repo.

    There are very few tests that an be run only in git. One example is
    correctness of example code that won't get included in RPM.
    '''

    return unittest.skipUnless(in_git, 'outside git tree')(test_item)


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


class _AssertNotRaisesContext(object):
    """A context manager used to implement TestCase.assertNotRaises methods.

    Stolen from unittest and hacked. Regexp support stripped.
    """ # pylint: disable=too-few-public-methods

    def __init__(self, expected, test_case, expected_regexp=None):
        if expected_regexp is not None:
            raise NotImplementedError('expected_regexp is unsupported')

        self.expected = expected
        self.exception = None

        self.failureException = test_case.failureException


    def __enter__(self):
        return self


    def __exit__(self, exc_type, exc_value, tb):
        if exc_type is None:
            return True

        try:
            exc_name = self.expected.__name__
        except AttributeError:
            exc_name = str(self.expected)

        if issubclass(exc_type, self.expected):
            raise self.failureException(
                "{0} raised".format(exc_name))
        else:
            # pass through
            return False

        self.exception = exc_value # store for later retrieval


class BeforeCleanExit(BaseException):
    '''Raised from :py:meth:`QubesTestCase.tearDown` when
    :py:attr:`qubes.tests.run.QubesDNCTestResult.do_not_clean` is set.'''
    pass


class QubesTestCase(unittest.TestCase):
    '''Base class for Qubes unit tests.
    '''

    def __init__(self, *args, **kwargs):
        super(QubesTestCase, self).__init__(*args, **kwargs)
        self.longMessage = True
        self.log = logging.getLogger('{}.{}.{}'.format(
            self.__class__.__module__,
            self.__class__.__name__,
            self._testMethodName))


    def __str__(self):
        return '{}/{}/{}'.format(
            '.'.join(self.__class__.__module__.split('.')[2:]),
            self.__class__.__name__,
            self._testMethodName)


    def tearDown(self):
        super(QubesTestCase, self).tearDown()

        result = self._resultForDoCleanups
        failed_test_cases = result.failures \
            + result.errors \
            + [(tc, None) for tc in result.unexpectedSuccesses]

        if getattr(result, 'do_not_clean', False) \
                and any(tc is self for tc, exc in failed_test_cases):
            raise BeforeCleanExit()


    def assertNotRaises(self, excClass, callableObj=None, *args, **kwargs):
        """Fail if an exception of class excClass is raised
           by callableObj when invoked with arguments args and keyword
           arguments kwargs. If a different type of exception is
           raised, it will not be caught, and the test case will be
           deemed to have suffered an error, exactly as for an
           unexpected exception.

           If called with callableObj omitted or None, will return a
           context object used like this::

                with self.assertRaises(SomeException):
                    do_something()

           The context manager keeps a reference to the exception as
           the 'exception' attribute. This allows you to inspect the
           exception after the assertion::

               with self.assertRaises(SomeException) as cm:
                   do_something()
               the_exception = cm.exception
               self.assertEqual(the_exception.error_code, 3)
        """
        context = _AssertNotRaisesContext(excClass, self)
        if callableObj is None:
            return context
        with context:
            callableObj(*args, **kwargs)


    def assertXMLEqual(self, xml1, xml2):
        '''Check for equality of two XML objects.

        :param xml1: first element
        :param xml2: second element
        :type xml1: :py:class:`lxml.etree._Element`
        :type xml2: :py:class:`lxml.etree._Element`
        '''  # pylint: disable=invalid-name

        self.assertEqual(xml1.tag, xml2.tag)
        self.assertEqual(xml1.text, xml2.text)
        self.assertItemsEqual(xml1.keys(), xml2.keys())
        for key in xml1.keys():
            self.assertEqual(xml1.get(key), xml2.get(key))


    def assertEventFired(self, emitter, event, args=None, kwargs=None):
        '''Check whether event was fired on given emitter and fail if it did
        not.

        :param emitter: emitter which is being checked
        :type emitter: :py:class:`TestEmitter`
        :param str event: event identifier
        :param list args: when given, all items must appear in args passed to \
            an event
        :param list kwargs: when given, all items must appear in kwargs passed \
            to an event
        '''

        for ev, ev_args, ev_kwargs in emitter.fired_events:
            if ev != event:
                continue
            if args is not None and any(i not in ev_args for i in args):
                continue
            if kwargs is not None and any(i not in ev_kwargs for i in kwargs):
                continue

            return

        self.fail('event {!r} did not fire on {!r}'.format(event, emitter))


    def assertEventNotFired(self, emitter, event, args=None, kwargs=None):
        '''Check whether event was fired on given emitter. Fail if it did.

        :param emitter: emitter which is being checked
        :type emitter: :py:class:`TestEmitter`
        :param str event: event identifier
        :param list args: when given, all items must appear in args passed to \
            an event
        :param list kwargs: when given, all items must appear in kwargs passed \
            to an event
        '''

        for ev, ev_args, ev_kwargs in emitter.fired_events:
            if ev != event:
                continue
            if args is not None and any(i not in ev_args for i in args):
                continue
            if kwargs is not None and any(i not in ev_kwargs for i in kwargs):
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
        ''' # pylint: disable=redefined-builtin

        if schema is not None and file is None:
            relaxng = schema
            if isinstance(relaxng, str):
                relaxng = lxml.etree.XML(relaxng)
            # pylint: disable=protected-access
            if isinstance(relaxng, lxml.etree._Element):
                relaxng = lxml.etree.RelaxNG(relaxng)

        elif file is not None and schema is None:
            if not os.path.isabs(file):
                basedirs = ['/usr/share/doc/qubes/relaxng']
                if in_git:
                    basedirs.insert(0, os.path.join(in_git, 'relaxng'))
                for basedir in basedirs:
                    abspath = os.path.join(basedir, file)
                    if os.path.exists(abspath):
                        file = abspath
                        break
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


class SystemTestsMixin(object):
    def setUp(self):
        super(SystemTestsMixin, self).setUp()
        self.remove_test_vms()

    def tearDown(self):
        super(SystemTestsMixin, self).tearDown()
        self.remove_test_vms()


    @staticmethod
    def make_vm_name(name):
        return VMPREFIX + name


    def _remove_vm_qubes(self, vm):
        vmname = vm.name
        app = vm.app

        try:
            # XXX .is_running() may throw libvirtError if undefined
            if vm.is_running():
                vm.force_shutdown()
        except: # pylint: disable=bare-except
            pass

        try:
            vm.remove_from_disk()
        except: # pylint: disable=bare-except
            pass

        try:
            vm.libvirt_domain.undefine()
        except (AttributeError, libvirt.libvirtError):
            pass

        del app.domains[vm]
        del vm

        app.save()
        del app

        # Now ensure it really went away. This may not have happened,
        # for example if vm.libvirt_domain malfunctioned.
        try:
            conn = libvirt.open(qubes.config.defaults['libvirt_uri'])
            dom = conn.lookupByName(vmname)
        except: # pylint: disable=bare-except
            pass
        else:
            self._remove_vm_libvirt(dom)

        self._remove_vm_disk(vmname)


    @staticmethod
    def _remove_vm_libvirt(dom):
        try:
            dom.destroy()
        except libvirt.libvirtError: # not running
            pass
        dom.undefine()


    @staticmethod
    def _remove_vm_disk(vmname):
        for dirspec in (
                'qubes_appvms_dir',
                'qubes_servicevms_dir',
                'qubes_templates_dir'):
            dirpath = os.path.join(qubes.config.system_path['qubes_base_dir'],
                qubes.config.system_path[dirspec], vmname)
            if os.path.exists(dirpath):
                if os.path.isdir(dirpath):
                    shutil.rmtree(dirpath)
                else:
                    os.unlink(dirpath)


    def remove_vms(self, vms):
        for vm in vms:
            self._remove_vm_qubes(vm)


    def remove_test_vms(self):
        '''Aggresively remove any domain that has name in testing namespace.

        .. warning::
            The test suite hereby claims any domain whose name starts with
            :py:data:`VMPREFIX` as fair game. This is needed to enforce sane
            test executing environment. If you have domains named ``test-*``,
            don't run the tests.
        '''

        # first, remove them Qubes-way
        if os.path.exists(XMLPATH):
            self.remove_vms(vm for vm in qubes.Qubes(XMLPATH).domains
                if vm.name != TEMPLATE)
            os.unlink(XMLPATH)

        # now remove what was only in libvirt
        conn = libvirt.open(qubes.config.defaults['libvirt_uri'])
        for dom in conn.listAllDomains():
            if dom.name().startswith(VMPREFIX):
                self._remove_vm_libvirt(dom)

        # finally remove anything that is left on disk
        vmnames = set()
        for dirspec in (
                'qubes_appvms_dir',
                'qubes_servicevms_dir',
                'qubes_templates_dir'):
            dirpath = os.path.join(qubes.config.system_path['qubes_base_dir'],
                qubes.config.system_path[dirspec])
            for name in os.listdir(dirpath):
                if name.startswith(VMPREFIX):
                    vmnames.add(name)
        for vmname in vmnames:
            self._remove_vm_disk(vmname)


def load_tests(loader, tests, pattern): # pylint: disable=unused-argument
    # discard any tests from this module, because it hosts base classes
    tests = unittest.TestSuite()

    for modname in (
            # unit tests
            'qubes.tests.events',
            'qubes.tests.init1',
            'qubes.tests.vm.init',
            'qubes.tests.vm.qubesvm',
            'qubes.tests.vm.adminvm',
            'qubes.tests.init2',
            'qubes.tests.tools',

            # integration tests
#           'qubes.tests.int.basic',
#           'qubes.tests.dom0_update',
#           'qubes.tests.network',
#           'qubes.tests.vm_qrexec_gui',
#           'qubes.tests.backup',
#           'qubes.tests.backupcompatibility',
#           'qubes.tests.regressions',

            # tool tests
            'qubes.tests.int.tools.qubes_create',
            'qubes.tests.int.tools.qvm_run',
            ):
        tests.addTests(loader.loadTestsFromName(modname))

    return tests
