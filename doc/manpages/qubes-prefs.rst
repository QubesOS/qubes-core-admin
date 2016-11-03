.. program:: qubes-prefs

:program:`qubes-prefs` -- List/set various global properties
============================================================

Synopsis
--------

:command:`qubes-prefs` [-h] [--verbose] [--quiet] [--force-root] [--help-properties] [*PROPERTY* [*VALUE*\|--delete]]

Options
-------

.. option:: --help, -h

   Show help message and exit.

.. option:: --help-properties

   List available properties with short descriptions and exit.

.. option:: --verbose, -v

   Increase verbosity.

.. option:: --quiet, -q

   Decrease verbosity.

.. option:: --unset, --default, --delete, -D

   Unset the property. If is has default value, it will be used instead.

.. option:: --get, -g

   Ignored; for compatibility with older scripts.

.. option:: --set, -s

   Ignored; for compatibility with older scripts.


Common properties
=================

This list is non-exhaustive. For authoritative listing, see
:option:`--help-properties` and documentation of the source code.

.. warning::

   This list is from the core2. It is wrong in many cases, some of them obvious,
   some of them not.

- clock VM
- update VM
- default template
- default firewallVM
- default kernel
- default netVM

Authors
-------

| Joanna Rutkowska <joanna at invisiblethingslab dot com>
| Rafal Wojtczuk <rafal at invisiblethingslab dot com>
| Marek Marczykowski <marmarek at invisiblethingslab dot com>
| Wojtek Porczyk <woju at invisiblethingslab dot com>

.. vim: ts=3 sw=3 et tw=80
