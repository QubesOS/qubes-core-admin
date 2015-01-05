:py:mod:`qubes.tests` -- Writing tests for qubes
================================================

Writing tests is very important for ensuring quality of code that is delivered.
Given test case may check for variety of conditions, but they generally fall
inside those two categories of conformance tests:

* Unit tests: these test smallest units of code, probably methods of functions,
  or even combination of arguments for one specific method.

* Integration tests: these test interworking of units.

We are interested in both categories.

There is also distinguished category of regression tests (both unit- and
integration-level), which are included because they check for specific bugs that
were fixed in the past and should not happen in the future. Those should be
accompanied with reference to closed ticked that describes the bug.

Qubes' tests are written using :py:mod:`unittest` module from Python Standard
Library for both unit test and integration tests.

Test case organisation
----------------------

Every module (like :py:mod:`qubes.vm.qubesvm`) should have its companion (like
``qubes.tests.vm.qubesvm``). Packages ``__init__.py`` files should be
accompanied by ``init.py`` inside respective directory under :file:`tests/`.
Inside tests module there should be one :py:class:`qubes.tests.QubesTestCase`
class for each class in main module plus one class for functions and global
variables. :py:class:`qubes.tests.QubesTestCase` classes should be named
``TC_xx_ClassName``, where ``xx`` is two-digit number. Test functions should be
named ``test_xxx_test_name``, where ``xxx`` is three-digit number. You may
introduce some structure of your choice in this number.

FIXME: where are placed integration tests?

Writing tests
-------------

First of all, testing is art, not science. Testing is not panaceum and won't
solve all of your problems. Rules given in this guide and elsewhere should be
followed, but shouldn't be worshipped.

When writing test, you should think about order of execution. Tests should be
written bottom-to-top, that is, tests that are ran later may depend on features
that are tested after but not the other way around. This is important, because
when encountering failure we expect the reason happen *before*, and not after
failure occured. Therefore, when encountering multiple errors, we may instantly
focus on fixing the first one and not wondering if any later problems may be
relevant or not. This is the reason of numbers in names of the classes and test
methods.

You may, when it makes sense, manipulate private members of classes under tests.
This violates one of the founding principles of object-oriented programming, but
may be required to write tests in correct order if your class provides public
methods with circular dependencies. For example containers may check if added
item is already in container, but you can't test ``__contains__`` method without
something already inside. Don't forget to test the other method later.

Special Qubes-specific considerations
-------------------------------------

Events
^^^^^^

:py:class:`qubes.tests.QubesTestCase` provides convenient methods for checking
if event fired or not: :py:meth:`qubes.tests.QubesTestCase.assertEventFired` and 
:py:meth:`qubes.tests.QubesTestCase.assertEventNotFired`. These require that
emitter is subclass of :py:class:`qubes.tests.TestEmitter`. You may instantiate
it directly::

   import qubes.tests

   class TC_10_SomeClass(qubes.tests.QubesTestCase):
       def test_000_event(self):
           emitter = qubes.tests.TestEmitter()
           emitter.fire_event('did-fire')
           self.assertEventFired(emitter, 'did-fire')

If you need to snoop specific class (which already is a child of
:py:class:`qubes.events.Emitter`, possibly indirect), you can define derivative
class which uses :py:class:`qubes.tests.TestEmitter` as mix-in::

   import qubes
   import qubes.tests

   class TestHolder(qubes.tests.TestEmitter, qubes.PropertyHolder):
      pass

   class TC_20_PropertyHolder(qubes.tests.QubesTestCase):
       def test_000_event(self):
           emitter = TestHolder()
           self.assertEventNotFired(emitter, 'did-not-fire')

Dom0
^^^^

Qubes is a complex piece of software and depends on number other complex pieces,
notably VM hypervisor or some other isolation provider. Not everything may be
testable under all conditions. Some tests (mainly unit tests) are expected to
run during compilation, but many tests (probably all of the integration tests
and more) can run only inside already deployed Qubes installation. There is
special decorator, :py:func:`qubes.tests.skipUnlessDom0` which causes test (or
even entire class) to be skipped outside dom0. Use it freely::

   import qubes.tests

   class TC_30_SomeClass(qubes.tests.QubesTestCase):
       @qubes.tests.skipUnlessDom0
       def test_000_inside_dom0(self):
           # this is skipped outside dom0
           pass

   @qubes.tests.skipUnlessDom0
   class TC_31_SomeOtherClass(qubes.tests.QubesTestCase):
       # all tests in this class are skipped
       pass


Module contents
---------------

.. automodule:: qubes.tests
   :members:
   :show-inheritance:

.. vim: ts=3 sw=3 et tw=80
