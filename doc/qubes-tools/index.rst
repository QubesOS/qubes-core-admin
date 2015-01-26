:py:mod:`qubes.tools` -- Command line utilities
===============================================

Those are Python modules that house actual functionality of CLI tools -- the
files installed in :file:`/usr/bin` only import these modules and run ``main()``
function.

The modules should make available for import theirs command line parsers
(instances of :py:class:`argparse.ArgumentParser`) as either ``.parser``
attribute or function ``get_parser()``, which returns parser. Manual page will
be automatically checked during generation if its "Options" section contains all
options from this parser (and only those).


Module contents
---------------

.. automodule:: qubes.tools
   :members:
   :show-inheritance:


All CLI tools
-------------

.. toctree::
   :maxdepth: 1
   :glob:

   *

.. vim: ts=3 sw=3 et tw=80
