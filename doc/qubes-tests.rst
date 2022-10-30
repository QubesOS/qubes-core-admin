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

Integration tests for Qubes core features are stored in :file:`tests/integ/`
directory. Additional tests may be loaded from other packages (see extra test
loader below). Those tests are run only on real Qubes system and are not suitable
for running in VM or in Travis. Test classes of this category inherit from
:py:class:`qubes.tests.SystemTestCase`.

Writing tests
-------------

First of all, testing is art, not science. Testing is not panaceum and won't
solve all of your problems. Rules given in this guide and elsewhere should be
followed, but shouldn't be worshipped.

Test can be divided into three phases. The first part is setup phase. In this
part you should arrange for a test condition to occur. You intentionally put
system under test in some specific state. Phase two is executing test condition
-- for example you check some variable for equality or expect that some
exception is raised. Phase three is responsible for returning a verdict. This is
largely done by the framework.

When writing test, you should think about order of execution. This is the reason
of numbers in names of the classes and test methods. Tests should be written
bottom-to-top, that is, test setups that are ran later may depend on features
that are tested after but not the other way around. This is important, because
when encountering failure we expect the reason happen *before*, and not after
failure occured. Therefore, when encountering multiple errors, we may instantly
focus on fixing the first one and not wondering if any later problems may be
relevant or not. Some people also like to enable
:py:attr:`unittest.TestResult.failfast` feature, which stops on the first failed
test -- with wrong order this messes up their workflow.

Test should fail for one reason only and test one specific issue. This does not
mean that you can use one ``.assert*`` method per ``test_`` function: for
example when testing one regular expression you are welcome to test many valid
and/or invalid inputs, especcialy when test setup is complicated. However, if
you encounter problems during setup phase, you should *skip* the test, and not
fail it. This also aids interpretation of results.

You may, when it makes sense, manipulate private members of classes under tests.
This violates one of the founding principles of object-oriented programming, but
may be required to write tests in correct order if your class provides public
methods with circular dependencies. For example containers may check if added
item is already in container, but you can't test ``__contains__`` method without
something already inside. Don't forget to test the other method later.

When developing tests, it may be useful to pause the test on failure and inspect
running VMs manually. To do that, set ``QUBES_TEST_WAIT_ON_FAIL=1`` environment
variable. This will wait on keypress before cleaning up after a failed tests.
It's recommended to use this feature together with
:py:attr:`unittest.TestResult.failfast` feature (``-f`` option to unittest
runner).

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

VM tests
^^^^^^^^

Some integration tests verifies not only dom0 part of the system, but also VM
part. In those cases, it makes sense to iterate them for different templates.
Additionally, list of the templates can be dynamic (different templates
installed, only some considered for testing etc).
This can be achieved by creating a mixin class with the actual tests (a class
inheriting just from :py:class:`object`, instead of
:py:class:`qubes.tests.SystemTestCase` or :py:class:`unittest.TestCase`) and
then create actual test classes dynamically using
:py:func:`qubes.tests.create_testcases_for_templates`.
Test classes created this way will have :py:attr:`template` set to the template
name under test and also this template will be set as the default template
during the test execution.
The function takes a test class name prefix (template name will be appended to
it after '_' separator), a classes to inherit from (in most cases the just
created mixin and :py:class:`qubes.tests.SystemTestCase`) and a current module
object (use `sys.modules[__name__]`). The function will return created test
classes but also add them to the appropriate module (pointed by the *module*
parameter). This should be done in two cases:

* :py:func:`load_tests` function - when test loader request list of tests
* on module import time, using a wrapper
  :py:func:`qubes.tests.maybe_create_testcases_on_import` (will call the
  function only if explicit list of templates is given, to avoid loading
  :file:`qubes.xml` when just importing the module)

An example boilerplate looks like this::

   def create_testcases_for_templates():
       return qubes.tests.create_testcases_for_templates('TC_00_AppVM',
           TC_00_AppVMMixin, qubes.tests.SystemTestCase,
           module=sys.modules[__name__])

   def load_tests(loader, tests, pattern):
       tests.addTests(loader.loadTestsFromNames(
           create_testcases_for_templates()))
       return tests

   qubes.tests.maybe_create_testcases_on_import(create_testcases_for_templates)

This will by default create tests for all the templates installed in the system.
Additionally, it is possible to control this process using environment
variables:

* `QUBES_TEST_TEMPLATES` - space separated list of templates to test
* `QUBES_TEST_LOAD_ALL` - create tests for all the templates (by inspecting
  the :file:`qubes.xml` file), even at module import time

This is dynamic test creation is intentionally made compatible with Nose2 test
runner and its load_tests protocol implementation.

Extra tests
^^^^^^^^^^^

Most tests live in this package, but it is also possible to store tests in other
packages while still using infrastructure provided here and include them in the
common test run. Loading extra tests is implemented in
:py:mod:`qubes.tests.extra`. To write test to be loaded this way, you need to
create test class(es) as usual. You can also use helper class
:py:class:`qubes.tests.extra.ExtraTestCase` (instead of
:py:class:`qubes.tests.SystemTestCase`) which provide few convenient functions
and hide usage of asyncio for simple cases (like `vm.start()`, `vm.run()`).

The next step is to register the test class(es). You need to do this by defining
entry point for your package. There are two groups:

* `qubes.tests.extra` - for general tests (called once)
* `qubes.tests.extra.for_template` - for per-VM tests (called for each template
  under test)

As a name in the group, choose something unique, preferably package name. An
object reference should point at the function that returns a list of test
classes.

Example :file:`setup.py`::

   from setuptools import setup

   setup(
       name='splitgpg',
       version='1.0',
       packages=['splitgpg'],
       entry_points={
           'qubes.tests.extra.for_template':
               'splitgpg = splitgpg.tests:list_tests',
       }
   )

The test loading process can be additionally controlled with environment
variables:

* `QUBES_TEST_EXTRA_INCLUDE` - space separated list of tests to include (named
  by a name in an entry point, `splitgpg` in the above example); if defined, only
  those extra tests will be loaded

* `QUBES_TEST_EXTRA_EXCLUDE` - space separated list of tests to exclude


Module contents
---------------

.. automodule:: qubes.tests
   :members:
   :show-inheritance:

.. vim: ts=3 sw=3 et tw=80
