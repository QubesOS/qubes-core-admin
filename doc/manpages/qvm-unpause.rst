.. program:: qvm-unpause

:program:`qvm-unpause` -- unpause a domain
==========================================

Synopsis
--------

:command:`qvm-unpause` [-h] [--verbose] [--quiet] *VMNAME*

Options
-------

.. option:: --help, -h

   Show the help message and exit.

.. option:: --verbose, -v

   Increase verbosity.

.. option:: --quiet, -q

   Decrease verbosity.

.. option:: --all

   Unause all the qubes.

.. option:: --exclude=EXCLUDE

   Exclude the qube from :option:`--all`.

Authors
-------

| Joanna Rutkowska <joanna at invisiblethingslab dot com>
| Rafal Wojtczuk <rafal at invisiblethingslab dot com>
| Marek Marczykowski <marmarek at invisiblethingslab dot com>
| Wojtek Porczyk <woju at invisiblethingslab dot com>

.. vim: ts=3 sw=3 et tw=80
