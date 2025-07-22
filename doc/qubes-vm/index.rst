:py:mod:`qubes.vm` -- Different Virtual Machine types
=====================================================

Qubes is composed of several virtual machines that are interconnected in
several ways. From now on they will be called „domains”, as they may not
actually be true virtual machines -- we plan to support LXC containers for
example. Because of Xen-only legacy of Qubes code, it is custom to refer to them
in long/plural as ``domains`` and in short/singular as ``vm``.


Domain object
-------------

There are couple of programming objects that refer to domain. The main is the
instance of :py:class:`qubes.vm.QubesVM`. This is the main „porcelain” object,
which carries other objects and supplies convenience methods like
:py:meth:`qubes.vm.qubesvm.QubesVM.start`. This class is actually divided in
two, the :py:class:`qubes.vm.qubesvm.QubesVM` cares about Qubes-specific
actions, that are more or less directly related to security model. It is
intended to be easily auditable by non-expert programmers (ie. we don't use
Python's magic there). The second class is its parent,
:py:class:`qubes.vm.LocalVM`, which is concerned about technicalities like XML
serialising/deserialising. It is of less concern to threat model auditors, but
still relevant to overall security of the Qubes OS. It is written for
programmers by programmers.

The second object is the XML node that refers to the domain. It can be accessed
as :py:attr:`Qubes.vm.LocalVM.xml` attribute of the domain object. The third one
is :py:attr:`Qubes.vm.qubesvm.QubesVM.libvirt_domain` object for directly
interacting with libvirt. Those objects are intended to be used from core and/or
plugins, but not directly by user or from qvm-tools. They are however public, so
there are no restrictions.


Domain classes
--------------

There are several different types of VM, because not every Qubes domain is equal
-- some of them perform specific functions, like NetVM; others have different
life cycle, like DisposableVM. For that, different domains have different Python
classes. They are all defined in this package, generally one class per module,
but some modules contain private globals that serve this particular class.


Package contents
----------------

Main public classes
^^^^^^^^^^^^^^^^^^^

.. autoclass:: qubes.vm.LocalVM
   :members:
   :show-inheritance:

Helper classes and functions
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. autoclass:: qubes.features.Features
   :members:
   :show-inheritance:

.. autoclass:: qubes.vm.mix.net.NetVMMixin
   :members:
   :show-inheritance:

.. autoclass:: qubes.vm.mix.dvmtemplate.DVMTemplateMixin
   :members:
   :show-inheritance:

Particular VM classes
^^^^^^^^^^^^^^^^^^^^^

Main types:

.. toctree::
   :maxdepth: 1

   qubesvm
   appvm
   templatevm

Special VM types:

.. toctree::
   :maxdepth: 1

   dispvm
   adminvm

.. standalonevm

.. vim: ts=3 sw=3 et
