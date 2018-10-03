# pylint: disable=invalid-name

#
# The Qubes OS Project, https://www.qubes-os.org/
#
# Copyright (C) 2014-2015  Joanna Rutkowska <joanna@invisiblethingslab.com>
# Copyright (C) 2014-2015
#                   Marek Marczykowski-Górecki <marmarek@invisiblethingslab.com>
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

"""
.. warning::
    The test suite hereby claims any domain whose name starts with
    :py:data:`VMPREFIX` as fair game. This is needed to enforce sane
    test executing environment. If you have domains named ``test-*``,
    don't run the tests.
"""

import asyncio
import collections
import functools
import logging
import os
import pathlib
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
import unittest
import warnings
from distutils import spawn

import gc
import lxml.etree
import pkg_resources

import qubes
import qubes.api
import qubes.api.admin
import qubes.api.internal
import qubes.backup
import qubes.config
import qubes.devices
import qubes.events
import qubes.exc
import qubes.ext.pci
import qubes.vm.standalonevm
import qubes.vm.templatevm

XMLPATH = '/var/lib/qubes/qubes-test.xml'
CLASS_XMLPATH = '/var/lib/qubes/qubes-class-test.xml'
TEMPLATE = 'fedora-23'
VMPREFIX = 'test-inst-'
CLSVMPREFIX = 'test-cls-'


if 'DEFAULT_LVM_POOL' in os.environ.keys():
    DEFAULT_LVM_POOL = os.environ['DEFAULT_LVM_POOL']
else:
    DEFAULT_LVM_POOL = 'qubes_dom0/pool00'


POOL_CONF = {'name': 'test-lvm',
             'driver': 'lvm_thin',
             'volume_group': DEFAULT_LVM_POOL.split('/')[0],
             'thin_pool': DEFAULT_LVM_POOL.split('/')[1]}

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

if in_dom0:
    import libvirtaio
    libvirt_event_impl = libvirtaio.virEventRegisterAsyncIOImpl()
else:
    libvirt_event_impl = None

try:
    in_git = subprocess.check_output(
        ['git', 'rev-parse', '--show-toplevel']).decode().strip()
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

def skipUnlessEnv(varname):
    '''Decorator generator for skipping tests without environment variable set.

    Some tests require working X11 display, like those using GTK library, which
    segfaults without connection to X.
    Other require their own, custom variables.
    '''

    return unittest.skipUnless(os.getenv(varname), 'no {} set'.format(varname))


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
    >>> emitter.fire_event('event', spam='eggs', foo='bar')
    >>> emitter.fired_events
    Counter({('event', (1, 2, 3), (('foo', 'bar'), ('spam', 'eggs'))): 1})
    '''

    def __init__(self, *args, **kwargs):
        super(TestEmitter, self).__init__(*args, **kwargs)

        #: :py:class:`collections.Counter` instance
        self.fired_events = collections.Counter()

    def fire_event(self, event, **kwargs):
        effects = super(TestEmitter, self).fire_event(event, **kwargs)
        ev_kwargs = frozenset(
            (key,
                frozenset(value.items()) if isinstance(value, dict)
                else tuple(value) if isinstance(value, list)
                else value)
            for key, value in kwargs.items()
        )
        self.fired_events[(event, ev_kwargs)] += 1
        return effects

    @asyncio.coroutine
    def fire_event_async(self, event, pre_event=False, **kwargs):
        effects = yield from super(TestEmitter, self).fire_event_async(
            event, pre_event=pre_event, **kwargs)
        ev_kwargs = frozenset(
            (key,
                frozenset(value.items()) if isinstance(value, dict) else value)
            for key, value in kwargs.items()
        )
        self.fired_events[(event, ev_kwargs)] += 1
        return effects


def expectedFailureIfTemplate(templates):
    """
    Decorator for marking specific test as expected to fail only for some
    templates. Template name is compared as substring, so 'whonix' will
    handle both 'whonix-ws' and 'whonix-gw'.
    templates can be either a single string, or an iterable
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(self, *args, **kwargs):
            template = self.template
            if isinstance(templates, str):
                should_expect_fail = template in templates
            else:
                should_expect_fail = any([template in x for x in templates])
            if should_expect_fail:
                try:
                    func(self, *args, **kwargs)
                except Exception:
                    raise unittest.case._ExpectedFailure(sys.exc_info())
                raise unittest.case._UnexpectedSuccess()
            else:
                # Call directly:
                func(self, *args, **kwargs)
        return wrapper
    return decorator

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

        if issubclass(exc_type, self.expected):
            raise self.failureException(
                "{!r} raised, traceback:\n{!s}".format(
                    exc_value, ''.join(traceback.format_tb(tb))))
        else:
            # pass through
            return False

        self.exception = exc_value  # store for later retrieval

class _QrexecPolicyContext(object):
    '''Context manager for SystemTestCase.qrexec_policy'''

    def __init__(self, service, source, destination, allow=True, action=None):
        try:
            source = source.name
        except AttributeError:
            pass

        try:
            destination = destination.name
        except AttributeError:
            pass

        self._filename = pathlib.Path('/etc/qubes-rpc/policy') / service
        if action is None:
            action = 'allow' if allow else 'deny'
        self._rule = '{} {} {}\n'.format(source, destination, action)
        self._did_create = False
        self._handle = None

    def load(self):
        if self._handle is None:
            try:
                self._handle = self._filename.open('r+')
            except FileNotFoundError:
                self._handle = self._filename.open('w+')
                self._did_create = True
        self._handle.seek(0)
        return self._handle.readlines()

    def save(self, rules):
        assert self._handle is not None
        self._handle.truncate(0)
        self._handle.seek(0)
        self._handle.write(''.join(rules))
        self._handle.flush()

    def close(self):
        assert self._handle is not None
        self._handle.close()
        self._handle = None

    def __enter__(self):
        rules = self.load()
        rules.insert(0, self._rule)
        self.save(rules)
        return self

    def __exit__(self, exc_type, exc_value, tb):
        if not self._did_create:
            try:
                rules = self.load()
                rules.remove(self._rule)
                self.save(rules)
            finally:
                self.close()
        else:
            self.close()
            self._filename.unlink()

class substitute_entry_points(object):
    '''Monkey-patch pkg_resources to substitute one group in iter_entry_points

    This is for testing plugins, like device classes.

    :param str group: The group that is to be overloaded.
    :param str tempgroup: The substitute group.

    Inside this context, if one iterates over entry points in overloaded group,
    the iteration actually happens over the other group.

    This context manager is stackable. To substitute more than one entry point
    group, just nest two contexts.
    ''' # pylint: disable=invalid-name

    def __init__(self, group, tempgroup):
        self.group = group
        self.tempgroup = tempgroup
        self._orig_iter_entry_points = None

    def _iter_entry_points(self, group, *args, **kwargs):
        if group == self.group:
            group = self.tempgroup
        return self._orig_iter_entry_points(group, *args, **kwargs)

    def __enter__(self):
        self._orig_iter_entry_points = pkg_resources.iter_entry_points
        pkg_resources.iter_entry_points = self._iter_entry_points
        return self

    def __exit__(self, exc_type, exc_value, tb):
        pkg_resources.iter_entry_points = self._orig_iter_entry_points
        self._orig_iter_entry_points = None


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
        self.addTypeEqualityFunc(qubes.devices.DeviceManager,
            self.assertDevicesEqual)

        self.loop = None


    def __str__(self):
        return '{}/{}/{}'.format(
            self.__class__.__module__,
            self.__class__.__name__,
            self._testMethodName)


    def setUp(self):
        super().setUp()
        self.addCleanup(self.cleanup_gc)

        self.loop = asyncio.get_event_loop()
        self.addCleanup(self.cleanup_loop)
        self.addCleanup(self.cleanup_traceback)
        self.addCleanup(qubes.ext.pci._cache_get.cache_clear)

    def cleanup_traceback(self):
        '''Remove local variables reference from tracebacks to allow garbage
        collector to clean all Qubes*() objects, otherwise file descriptors
        held by them will leak'''
        for test_case, exc_info in self._outcome.errors:
            if test_case is not self:
                continue
            if exc_info is None:
                continue
            ex = exc_info[1]
            while ex is not None:
                traceback.clear_frames(ex.__traceback__)
                ex = ex.__context__

    def cleanup_gc(self):
        gc.collect()
        leaked = [obj for obj in gc.get_objects() + gc.garbage
            if isinstance(obj,
                (qubes.Qubes, qubes.vm.BaseVM,
                libvirt.virConnect, libvirt.virDomain))]

        if leaked:
            try:
                import objgraph
                objgraph.show_backrefs(leaked,
                    max_depth=15, extra_info=extra_info,
                    filename='/tmp/objgraph-{}.png'.format(self.id()))
            except ImportError:
                pass

        # do not keep leaked object references in locals()
        leaked = bool(leaked)
        assert not leaked

    def cleanup_loop(self):
        '''Check if the loop is empty'''
        # XXX BEWARE this is touching undocumented, implementation-specific
        # attributes of the loop. This is most certainly unsupported and likely
        # will break when messing with: Python version, kernel family, loop
        # implementation, a combination thereof, or other things.
        # KEYWORDS for searching:
        #   win32, SelectorEventLoop, ProactorEventLoop, uvloop, gevent

        global libvirt_event_impl

        # really destroy all objects that could have used loop and/or libvirt
        gc.collect()

        # Check for unfinished libvirt business.
        if libvirt_event_impl is not None:
            try:
                self.loop.run_until_complete(asyncio.wait_for(
                    libvirt_event_impl.drain(), timeout=4))
            except asyncio.TimeoutError:
                raise AssertionError('libvirt event impl drain timeout')

        # this is stupid, but apparently it requires two passes
        # to cleanup SIGCHLD handlers
        self.loop.stop()
        self.loop.run_forever()
        self.loop.stop()
        self.loop.run_forever()

        # Check there are no Tasks left.
        assert not self.loop._ready
        assert not self.loop._scheduled

        # Check the loop watches no descriptors.
        # NOTE the loop has a pipe for self-interrupting, created once per
        # lifecycle, and it is unwatched only at loop.close(); so we cannot just
        # check selector for non-emptiness
        assert len(self.loop._selector.get_map()) \
            == int(self.loop._ssock is not None)

        del self.loop

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


    def assertXMLEqual(self, xml1, xml2, msg=''):
        '''Check for equality of two XML objects.

        :param xml1: first element
        :param xml2: second element
        :type xml1: :py:class:`lxml.etree._Element`
        :type xml2: :py:class:`lxml.etree._Element`
        '''

        self.assertEqual(xml1.tag, xml2.tag)
        msg += '/' + str(xml1.tag)

        if xml1.text is not None and xml2.text is not None:
            self.assertEqual(xml1.text.strip(), xml2.text.strip(), msg)
        else:
            self.assertEqual(xml1.text, xml2.text, msg)
        self.assertCountEqual(xml1.keys(), xml2.keys(), msg)
        for key in xml1.keys():
            self.assertEqual(xml1.get(key), xml2.get(key), msg)

        self.assertEqual(len(xml1), len(xml2), msg + ' children count')
        for child1, child2 in zip(xml1, xml2):
            self.assertXMLEqual(child1, child2, msg=msg)

    def assertDevicesEqual(self, devices1, devices2, msg=None):
        self.assertEqual(devices1.keys(), devices2.keys(), msg)
        for dev_class in devices1.keys():
            self.assertEqual(
                [str(dev) for dev in devices1[dev_class]],
                [str(dev) for dev in devices2[dev_class]],
                "Devices of class {} differs{}".format(
                    dev_class, (": " + msg) if msg else "")
            )

    def assertEventFired(self, subject, event, kwargs=None):
        '''Check whether event was fired on given emitter and fail if it did
        not.

        :param subject: emitter which is being checked
        :type emitter: :py:class:`TestEmitter`
        :param str event: event identifier
        :param dict kwargs: when given, all items must appear in kwargs passed \
            to an event
        '''

        will_not_match = object()
        for ev, ev_kwargs in subject.fired_events:
            if ev != event:
                continue
            if kwargs is not None:
                ev_kwargs = dict(ev_kwargs)
                if any(ev_kwargs.get(k, will_not_match) != v
                        for k, v in kwargs.items()):
                    continue

            return

        self.fail('event {!r} {}did not fire on {!r}'.format(
            event, ('' if kwargs is None else '{!r} '.format(kwargs)), subject))


    def assertEventNotFired(self, subject, event, kwargs=None):
        '''Check whether event was fired on given emitter. Fail if it did.

        :param subject: emitter which is being checked
        :type emitter: :py:class:`TestEmitter`
        :param str event: event identifier
        :param list kwargs: when given, all items must appear in kwargs passed \
            to an event
        '''

        will_not_match = object()
        for ev, ev_kwargs in subject.fired_events:
            if ev != event:
                continue
            if kwargs is not None:
                ev_kwargs = dict(ev_kwargs)
                if any(ev_kwargs.get(k, will_not_match) != v
                        for k, v in kwargs.items()):
                    continue

            self.fail('event {!r} {}did fire on {!r}'.format(
                event,
                ('' if kwargs is None else '{!r} '.format(kwargs)),
                subject))

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

    @staticmethod
    def make_vm_name(name, class_teardown=False):
        if class_teardown:
            return CLSVMPREFIX + name
        else:
            return VMPREFIX + name


class SystemTestCase(QubesTestCase):
    """
    Mixin for integration tests. All the tests here should use self.app
    object and when need qubes.xml path - should use :py:data:`XMLPATH`
    defined in this file.
    Every VM created by test, must use :py:meth:`SystemTestCase.make_vm_name`
    for VM name.
    By default self.app represents empty collection, if anything is needed
    there from the real collection it can be imported from self.host_app in
    :py:meth:`SystemTestCase.setUp`. But *can not be modified* in any way -
    this include both changing attributes in
    :py:attr:`SystemTestCase.host_app` and modifying files of such imported
    VM. If test need to make some modification, it must clone the VM first.

    If some group of tests needs class-wide initialization, first of all the
    author should consider if it is really needed. But if so, setUpClass can
    be used to create Qubes(CLASS_XMLPATH) object and create/import required
    stuff there. VMs created in :py:meth:`TestCase.setUpClass` should
    use self.make_vm_name('...', class_teardown=True) for name creation.
    Such (group of) test need to take care about
    :py:meth:`TestCase.tearDownClass` implementation itself.
    """
    # noinspection PyAttributeOutsideInit
    def setUp(self):
        if not in_dom0:
            self.skipTest('outside dom0')
        super(SystemTestCase, self).setUp()
        self.remove_test_vms()

        # need some information from the real qubes.xml - at least installed
        # templates; should not be used for testing, only to initialize self.app
        self.host_app = qubes.Qubes(os.path.join(
            qubes.config.qubes_base_dir,
            qubes.config.system_path['qubes_store_filename']))
        if os.path.exists(CLASS_XMLPATH):
            shutil.copy(CLASS_XMLPATH, XMLPATH)
        else:
            shutil.copy(self.host_app.store, XMLPATH)
        self.app = qubes.Qubes(XMLPATH)
        os.environ['QUBES_XML_PATH'] = XMLPATH
        self.app.register_event_handlers()

        self.qubesd = self.loop.run_until_complete(
            qubes.api.create_servers(
                qubes.api.admin.QubesAdminAPI,
                qubes.api.internal.QubesInternalAPI,
                app=self.app, debug=True))

        self.addCleanup(self.cleanup_app)

        self.app.add_handler('domain-delete', self.close_qdb_on_remove)

    def close_qdb_on_remove(self, app, event, vm, **kwargs):
        # only close QubesDB connection, do not perform other (destructive)
        # actions of vm.close()
        if vm._qdb_connection_watch is not None:
            asyncio.get_event_loop().remove_reader(
                vm._qdb_connection_watch.watch_fd())
            vm._qdb_connection_watch.close()
            vm._qdb_connection_watch = None

    def cleanup_app(self):
        self.remove_test_vms()

        server = None
        for server in self.qubesd:
            for sock in server.sockets:
                os.unlink(sock.getsockname())
            server.close()
        del server

        # close all existing connections, especially this will interrupt
        # running admin.Events calls, which do keep reference to Qubes() and
        # libvirt connection
        conn = None
        for conn in qubes.api.QubesDaemonProtocol.connections:
            if conn.transport:
                conn.transport.abort()
        del conn

        self.loop.run_until_complete(asyncio.wait([
            server.wait_closed() for server in self.qubesd]))
        del self.qubesd

        # remove all references to any complex qubes objects, to release
        # resources - most importantly file descriptors; this object will live
        # during the whole test run, but all the file descriptors would be
        # depleted earlier
        self.app.close()
        self.host_app.close()
        del self.app
        del self.host_app
        for attr in dir(self):
            obj_type = type(getattr(self, attr))
            if obj_type.__module__.startswith('qubes'):
                delattr(self, attr)

        # then trigger garbage collector to really destroy those objects
        gc.collect()

    def init_default_template(self, template=None):
        if template is None:
            template = self.host_app.default_template
        elif isinstance(template, str):
            template = self.host_app.domains[template]

        self.app.default_template = str(template)

    def init_networking(self):
        if not self.app.default_template:
            self.skipTest('Default template required for testing networking')
        default_netvm = self.host_app.default_netvm
        # if testing Whonix Workstation based VMs, try to use sys-whonix instead
        if self.app.default_template.name.startswith('whonix-ws'):
            if 'sys-whonix' in self.host_app.domains:
                default_netvm = self.host_app.domains['sys-whonix']
        if default_netvm is None:
            self.skipTest('Default netvm required')
        if not default_netvm.is_running():
            self.skipTest('VM {} required to be running'.format(
                default_netvm.name))

        self.app.default_netvm = str(default_netvm)


    def _find_pool(self, volume_group, thin_pool):
        ''' Returns the pool matching the specified ``volume_group`` &
            ``thin_pool``, or None.
        '''
        pools = [p for p in self.app.pools
                 if issubclass(p.__class__, qubes.storage.lvm.ThinPool)]
        for pool in pools:
            if pool.volume_group == volume_group \
                    and pool.thin_pool == thin_pool:
                return pool
        return None

    def init_lvm_pool(self):
        volume_group, thin_pool = DEFAULT_LVM_POOL.split('/', 1)
        path = "/dev/mapper/{!s}-{!s}".format(volume_group, thin_pool)
        if not os.path.exists(path):
            self.skipTest('LVM thin pool {!r} does not exist'.
                format(DEFAULT_LVM_POOL))
        self.pool = self._find_pool(volume_group, thin_pool)
        if not self.pool:
            self.pool = self.app.add_pool(**POOL_CONF)
            self.created_pool = True

    def _remove_vm_qubes(self, vm):
        vmname = vm.name
        app = vm.app

        # avoid race with DispVM.auto_cleanup=True
        try:
            self.loop.run_until_complete(
                asyncio.wait_for(vm.startup_lock.acquire(), 10))
        except asyncio.TimeoutError:
            pass

        try:
            # XXX .is_running() may throw libvirtError if undefined
            if vm.is_running():
                self.loop.run_until_complete(vm.kill())
        except:  # pylint: disable=bare-except
            pass

        try:
            self.loop.run_until_complete(vm.remove_from_disk())
        except:  # pylint: disable=bare-except
            pass

        try:
            del app.domains[vm.qid]
        except KeyError:
            pass
        vm.close()
        del vm

        app.save()
        del app

        # Now ensure it really went away. This may not have happened,
        # for example if vm.libvirt_domain malfunctioned.
        try:
            conn = libvirt.open(qubes.config.defaults['libvirt_uri'])
        except:  # pylint: disable=bare-except
            pass
        else:
            try:
                dom = conn.lookupByName(vmname)
            except:  # pylint: disable=bare-except
                pass
            else:
                self._remove_vm_libvirt(dom)
            conn.close()

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
            dirpath = os.path.join(qubes.config.qubes_base_dir,
                qubes.config.system_path[dirspec], vmname)
            if os.path.exists(dirpath):
                if os.path.isdir(dirpath):
                    shutil.rmtree(dirpath)
                else:
                    os.unlink(dirpath)

    @staticmethod
    def _remove_vm_disk_lvm(prefix=VMPREFIX):
        ''' Remove LVM volumes with given prefix

        This is "a bit" drastic, as it removes volumes regardless of volume
        group, thin pool etc. But we assume no important data on test system.
        '''
        try:
            volumes = subprocess.check_output(
                ['lvs', '--noheadings', '-o', 'vg_name,name',
                    '--separator', '/']).decode()
            if ('/vm-' + prefix) not in volumes:
                return
            subprocess.check_call(['sudo', 'lvremove', '-f'] +
                [vol.strip() for vol in volumes.splitlines()
                    if ('/vm-' + prefix) in vol],
                stdout=subprocess.DEVNULL)
        except subprocess.CalledProcessError:
            pass

    def remove_vms(self, vms):
        vms = list(vms)
        if not vms:
            return
        # break dependencies
        for vm in vms:
            vm.default_dispvm = None
        # then remove in reverse topological order (wrt netvm), using naive
        # algorithm
        # this heavily depends on lack of netvm loops
        while vms:
            vm = vms.pop(0)
            # make sure that all connected VMs are going to be removed,
            # otherwise this will loop forever
            assert all(x in vms for x in vm.connected_vms)
            if list(vm.connected_vms):
                # if still something use this VM, put it at the end of queue
                # and try next one
                vms.append(vm)
                continue
            self._remove_vm_qubes(vm)

    def remove_test_vms(self, xmlpath=XMLPATH, prefix=VMPREFIX):
        '''Aggresively remove any domain that has name in testing namespace.
        '''

        # first, remove them Qubes-way
        if os.path.exists(xmlpath):
            try:
                try:
                    app = self.app
                except AttributeError:
                    app = qubes.Qubes(xmlpath)
                try:
                    host_app = self.host_app
                except AttributeError:
                    host_app = qubes.Qubes()
                self.remove_vms([vm for vm in app.domains
                    if vm.name.startswith(prefix) or
                       (isinstance(vm, qubes.vm.dispvm.DispVM) and vm.name
                        not in host_app.domains)])
                if not hasattr(self, 'host_app'):
                    host_app.close()
                del host_app
                if not hasattr(self, 'app'):
                    app.close()
                del app
            except qubes.exc.QubesException:
                pass
            os.unlink(xmlpath)

        # now remove what was only in libvirt
        conn = libvirt.open(qubes.config.defaults['libvirt_uri'])
        for dom in conn.listAllDomains():
            if dom.name().startswith(prefix):
                self._remove_vm_libvirt(dom)
        conn.close()

        # finally remove anything that is left on disk
        vmnames = set()
        for dirspec in (
                'qubes_appvms_dir',
                'qubes_servicevms_dir',
                'qubes_templates_dir'):
            dirpath = os.path.join(qubes.config.qubes_base_dir,
                qubes.config.system_path[dirspec])
            if not os.path.exists(dirpath):
                continue
            for name in os.listdir(dirpath):
                if name.startswith(prefix):
                    vmnames.add(name)
        for vmname in vmnames:
            self._remove_vm_disk(vmname)
        self._remove_vm_disk_lvm(prefix)

    def qrexec_policy(self, service, source, destination, allow=True,
            action=None):
        """
        Allow qrexec calls for duration of the test
        :param service: service name
        :param source: source VM name
        :param destination: destination VM name
        :param allow: add rule with 'allow' action, otherwise 'deny'
        :param action: custom action, if specified *allow* argument is ignored
        :return:
        """

        return _QrexecPolicyContext(service, source, destination,
            allow=allow, action=action)

    def wait_for_window(self, title, timeout=30, show=True):
        """
        Wait for a window with a given title. Depending on show parameter,
        it will wait for either window to show or to disappear.

        :param title: title of the window to wait for
        :param timeout: timeout of the operation, in seconds
        :param show: if True - wait for the window to be visible,
            otherwise - to not be visible
        :return: None
        """

        wait_count = 0
        while subprocess.call(['xdotool', 'search', '--name', title],
                stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT) \
                != int(not show):
            wait_count += 1
            if wait_count > timeout*10:
                self.fail("Timeout while waiting for {} window to {}".format(
                    title, "show" if show else "hide")
                )
            self.loop.run_until_complete(asyncio.sleep(0.1))

    def enter_keys_in_window(self, title, keys):
        """
        Search for window with given title, then enter listed keys there.
        The function will wait for said window to appear.

        :param title: title of window
        :param keys: list of keys to enter, as for `xdotool key`
        :return: None
        """

        # 'xdotool search --sync' sometimes crashes on some race when
        # accessing window properties
        self.wait_for_window(title)
        command = ['xdotool', 'search', '--name', title,
                   'windowactivate', '--sync',
                   'key'] + keys
        subprocess.check_call(command)

    def shutdown_and_wait(self, vm, timeout=60):
        self.loop.run_until_complete(vm.shutdown())
        while timeout > 0:
            if not vm.is_running():
                return
            self.loop.run_until_complete(asyncio.sleep(1))
            timeout -= 1
        name = vm.name
        del vm
        self.fail("Timeout while waiting for VM {} shutdown".format(name))

    def prepare_hvm_system_linux(self, vm, init_script, extra_files=None):
        if not os.path.exists('/usr/lib/grub/i386-pc'):
            self.skipTest('grub2 not installed')
        if not spawn.find_executable('grub2-install'):
            self.skipTest('grub2-tools not installed')
        if not spawn.find_executable('dracut'):
            self.skipTest('dracut not installed')
        # create a single partition
        p = subprocess.Popen(['sfdisk', '-q', '-L', vm.storage.root_img],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT)
        p.communicate('2048,\n')
        assert p.returncode == 0, 'sfdisk failed'
        # TODO: check if root_img is really file, not already block device
        p = subprocess.Popen(['sudo', 'losetup', '-f', '-P', '--show',
            vm.storage.root_img], stdout=subprocess.PIPE)
        (loopdev, _) = p.communicate()
        loopdev = loopdev.strip()
        looppart = loopdev + 'p1'
        assert p.returncode == 0, 'losetup failed'
        subprocess.check_call(['sudo', 'mkfs.ext2', '-q', '-F', looppart])
        mountpoint = tempfile.mkdtemp()
        subprocess.check_call(['sudo', 'mount', looppart, mountpoint])
        try:
            subprocess.check_call(['sudo', 'grub2-install',
                '--target', 'i386-pc',
                '--modules', 'part_msdos ext2',
                '--boot-directory', mountpoint, loopdev],
                stderr=subprocess.DEVNULL
            )
            grub_cfg = '{}/grub2/grub.cfg'.format(mountpoint)
            subprocess.check_call(
                ['sudo', 'chown', '-R', os.getlogin(), mountpoint])
            with open(grub_cfg, 'w') as f:
                f.write(
                    "set timeout=1\n"
                    "menuentry 'Default' {\n"
                    "  linux /vmlinuz root=/dev/xvda1 "
                    "rd.driver.blacklist=bochs_drm "
                    "rd.driver.blacklist=uhci_hcd console=hvc0\n"
                    "  initrd /initrd\n"
                    "}"
                )
            p = subprocess.Popen(['uname', '-r'], stdout=subprocess.PIPE)
            (kernel_version, _) = p.communicate()
            kernel_version = kernel_version.strip()
            kernel = '/boot/vmlinuz-{}'.format(kernel_version)
            shutil.copy(kernel, os.path.join(mountpoint, 'vmlinuz'))
            init_path = os.path.join(mountpoint, 'init')
            with open(init_path, 'w') as f:
                f.write(init_script)
            os.chmod(init_path, 0o755)
            dracut_args = [
                '--kver', kernel_version,
                '--include', init_path,
                '/usr/lib/dracut/hooks/pre-pivot/initscript.sh',
                '--no-hostonly', '--nolvmconf', '--nomdadmconf',
            ]
            if extra_files:
                dracut_args += ['--install', ' '.join(extra_files)]
            subprocess.check_call(
                ['dracut'] + dracut_args + [os.path.join(mountpoint,
                    'initrd')],
                stderr=subprocess.DEVNULL
            )
        finally:
            subprocess.check_call(['sudo', 'umount', mountpoint])
            shutil.rmtree(mountpoint)
            subprocess.check_call(['sudo', 'losetup', '-d', loopdev])

    def create_bootable_iso(self):
        '''Create simple bootable ISO image.
        Type 'poweroff' to it to terminate that VM.
        '''
        isolinux_cfg = (
            'prompt 1\n'
            'label poweroff\n'
            '   kernel poweroff.c32\n'
        )
        output_fd, output_path = tempfile.mkstemp('.iso')
        with tempfile.TemporaryDirectory() as tmp_dir:
            try:
                shutil.copy('/usr/share/syslinux/isolinux.bin', tmp_dir)
                shutil.copy('/usr/share/syslinux/ldlinux.c32', tmp_dir)
                shutil.copy('/usr/share/syslinux/poweroff.c32', tmp_dir)
                with open(os.path.join(tmp_dir, 'isolinux.cfg'), 'w') as cfg:
                    cfg.write(isolinux_cfg)
                subprocess.check_call(['genisoimage', '-o', output_path,
                    '-c', 'boot.cat',
                    '-b', 'isolinux.bin',
                    '-no-emul-boot',
                    '-boot-load-size', '4',
                    '-boot-info-table',
                    '-q',
                    tmp_dir])
            except FileNotFoundError:
                self.skipTest('syslinux or genisoimage not installed')
        os.close(output_fd)
        self.addCleanup(os.unlink, output_path)
        return output_path

    def create_local_file(self, filename, content, mode='w'):
        with open(filename, mode) as file:
            file.write(content)
        self.addCleanup(os.unlink, filename)

    def create_remote_file(self, vm, filename, content):
        self.loop.run_until_complete(vm.run_for_stdio(
            'cat > {}'.format(shlex.quote(filename)),
            user='root', input=content.encode('utf-8')))

    @asyncio.coroutine
    def wait_for_session(self, vm):
        yield from asyncio.wait_for(
            vm.run_service_for_stdio(
                'qubes.WaitForSession', input=vm.default_user.encode()),
            timeout=30)


_templates = None
def list_templates():
    '''Returns tuple of template names available in the system.'''
    global _templates
    if _templates is None:
        if 'QUBES_TEST_TEMPLATES' in os.environ:
            _templates = os.environ['QUBES_TEST_TEMPLATES'].split()
    if _templates is None:
        try:
            app = qubes.Qubes()
            _templates = tuple(vm.name for vm in app.domains
                if isinstance(vm, qubes.vm.templatevm.TemplateVM) and
                    vm.features.get('os', None) != 'Windows')
            app.close()
            del app
        except OSError:
            _templates = ()
    return _templates

def create_testcases_for_templates(name, *bases, module, **kwds):
    '''Do-it-all helper for generating per-template tests via load_tests proto

    This does several things:
        - creates per-template classes
        - adds them to module's :py:func:`globals`
        - returns an iterable suitable for passing to loader.loadTestsFromNames

    TestCase classes created by this function have implicit `.template`
    attribute, which contains name of the respective template. They are also
    named with given prefix, underscore and template name. If template name
    contains characters not valid as part of Python identifier, they are
    impossible to get via standard ``.`` operator, though :py:func:`getattr` is
    still usable.

    >>> class MyTestsMixIn:
    ...     def test_000_my_test(self):
    ...         assert self.template.startswith('debian')
    >>> def load_tests(loader, tests, pattern):
    ...     tests.addTests(loader.loadTestsFromNames(
    ...         qubes.tests.create_testcases_for_templates(
    ...             'TC_00_MyTests', MyTestsMixIn, qubes.tests.SystemTestCase,
    ...             module=sys.modules[__name__])))

    *NOTE* adding ``module=sys.modules[__name__]`` is *mandatory*, and to allow
    enforcing this, it uses keyword-only argument syntax, which is only in
    Python 3.
    '''
    # Do not attempt to grab the module from traceback, since we are actually
    # a generator and loadTestsFromNames may also be a generator, so it's not
    # possible to correctly guess frame from stack. Explicit is better than
    # implicit!

    for template in list_templates():
        clsname = name + '_' + template
        cls = type(clsname, bases, {'template': template, **kwds})
        cls.__module__ = module.__name__
        # XXX I wonder what other __dunder__ attrs did I miss
        setattr(module, clsname, cls)
        yield '.'.join((module.__name__, clsname))

def extra_info(obj):
    '''Return short info identifying object.

    For example, if obj is a qube, return its name. This is for use with
    :py:mod:`objgraph` package.
    '''
    # Feel free to extend to other cases.

    if isinstance(obj, qubes.vm.qubesvm.QubesVM):
        try:
            return obj.name
        except AttributeError:
            pass
    if isinstance(obj, unittest.TestCase):
        return obj.id()

    return ''

def load_tests(loader, tests, pattern): # pylint: disable=unused-argument
    # discard any tests from this module, because it hosts base classes
    tests = unittest.TestSuite()

    for modname in (
            # unit tests
            'qubes.tests.events',
            'qubes.tests.devices',
            'qubes.tests.devices_block',
            'qubes.tests.firewall',
            'qubes.tests.init',
            'qubes.tests.vm.init',
            'qubes.tests.storage',
            'qubes.tests.storage_file',
            'qubes.tests.storage_reflink',
            'qubes.tests.storage_lvm',
            'qubes.tests.storage_kernels',
            'qubes.tests.ext',
            'qubes.tests.vm.qubesvm',
            'qubes.tests.vm.mix.net',
            'qubes.tests.vm.adminvm',
            'qubes.tests.vm.appvm',
            'qubes.tests.vm.dispvm',
            'qubes.tests.app',
            'qubes.tests.tarwriter',
            'qubes.tests.api',
            'qubes.tests.api_admin',
            'qubes.tests.api_misc',
            'qubespolicy.tests',
            'qubespolicy.tests.cli',
            ):
        tests.addTests(loader.loadTestsFromName(modname))

    # GTK/Glib is way too old there
    if 'TRAVIS' not in os.environ:
        for modname in (
                'qubespolicy.tests.gtkhelpers',
                'qubespolicy.tests.rpcconfirmation',
                ):
            tests.addTests(loader.loadTestsFromName(modname))

    tests.addTests(loader.discover(
        os.path.join(os.path.dirname(__file__), 'tools')))

    if not in_dom0:
        return tests

    for modname in (
            # integration tests
            'qubes.tests.integ.basic',
            'qubes.tests.integ.storage',
            'qubes.tests.integ.pvgrub',
            'qubes.tests.integ.devices_pci',
            'qubes.tests.integ.dom0_update',
            'qubes.tests.integ.network',
            'qubes.tests.integ.dispvm',
            'qubes.tests.integ.vm_qrexec_gui',
            'qubes.tests.integ.mime',
            'qubes.tests.integ.salt',
            'qubes.tests.integ.backup',
            'qubes.tests.integ.backupcompatibility',
#           'qubes.tests.regressions',

            # external modules
            'qubes.tests.extra',
            ):
        tests.addTests(loader.loadTestsFromName(modname))

    return tests
