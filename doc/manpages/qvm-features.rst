.. program:: qvm-features

:program:`qvm-features` -- manage domain's features
===================================================

Synopsis
--------

:command:`qvm-features` [-h] [--verbose] [--quiet] *VMNAME* [*FEATURE* [*VALUE*]]

Options
-------

.. option:: --help, -h

   show this help message and exit

.. option:: --verbose, -v

   increase verbosity

.. option:: --quiet, -q

   decrease verbosity

Description
-----------

This command is used to manually manage the *features* of the domain. The
features are key-value pairs with both key and value being strings. They are
used by extensions to store information about the domain and make policy
decisions based on them. For example, they may indicate that some specific
software package was installed inside the template and the domains based on it
have some specific capability.

.. warning::

   The features are normally managed by the extensions themselves and you should
   not change them directly. Strange things might happen otherwise.

Some extensions interpret the values as boolean. In this case, the empty string
means :py:obj:`False` and non-empty string (commonly ``'1'``) means
:py:obj:`True`. An absence of the feature means "default", which is
extension-dependent.

Authors
-------

| Joanna Rutkowska <joanna at invisiblethingslab dot com>
| Marek Marczykowski <marmarek at invisiblethingslab dot com>
| Wojtek Porczyk <woju at invisiblethingslab dot com>

.. vim: ts=3 sw=3 et tw=80
