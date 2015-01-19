:py:mod:`qubes.vm` -- Different Virtual Machine types
=====================================================

Main public classes
-------------------

.. autoclass:: qubes.vm.BaseVM
   :members:
   :show-inheritance:

Helper classes and functions
----------------------------

.. autoclass:: qubes.vm.BaseVMMeta
   :members:
   :show-inheritance:

.. autoclass:: qubes.vm.DeviceCollection
   :members:
   :show-inheritance:

.. autoclass:: qubes.vm.DeviceManager
   :members:
   :show-inheritance:

Particular VM classes
---------------------

Main types:

.. toctree::
   :maxdepth: 1

   qubesvm
   appvm
   templatevm

Special VM types:

.. toctree::
   :maxdepth: 1

   netvm
   proxyvm
   dispvm
   adminvm

HVMs:

.. toctree::
   :maxdepth: 1

   hvm

.. vim: ts=3 sw=3 et
