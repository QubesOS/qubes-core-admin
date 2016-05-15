.. program:: qvm-kill

:program:`qvm-kill` -- forceful shutdown of a domain
====================================================

Synopsis
--------

:command:`qvm-kill` [-h] [--verbose] [--quiet] [--all] [--exclude *EXCLUDE*] [*VMNAME* [*VMNAME* ...]]

Options
-------

.. option:: --all

   Kill all qubes. You can use :option:`--exclude` to limit the
   qubes set. dom0 is not killed.

.. option:: --exclude

   Exclude the qube from :option:`--all`.

.. option:: --help, -h

   show this help message and exit

.. option:: --verbose, -v

   increase verbosity

.. option:: --quiet, -q

   decrease verbosity


Authors
-------

| Joanna Rutkowska <joanna at invisiblethingslab dot com>
| Rafal Wojtczuk <rafal at invisiblethingslab dot com>
| Marek Marczykowski <marmarek at invisiblethingslab dot com>
| Wojtek Porczyk <woju at invisiblethingslab dot com>

.. vim: ts=3 sw=3 et tw=80
