.. program:: qvm-remove

:program:`qvm-remove` -- remove domain
======================================

Synopsis
--------
:command:`qvm-remove` [-h] [--verbose] [--quiet] [--force-root] [--all] [--exclude *EXCLUDE*] [--just-db] [*VMNAME* [*VMNAME* ...]]

Options
-------

.. option:: --all

   Remove  all qubes. You can use :option:`--exclude` to limit the
   qubes set. dom0 is not removed

.. option:: --exclude

   Exclude the qube from :option:`--all`.

.. option:: --help, -h

    Show this help message and exit

.. option:: --force-root

    Force to run, even with root privileges

.. option:: --just-db

    Remove only from the Qubes Xen DB, do not remove any files

.. option:: --verbose, -v

   increase verbosity

.. option:: --quiet, -q

   decrease verbosity

Authors
-------

| Joanna Rutkowska <joanna at invisiblethingslab dot com>
| Rafal Wojtczuk <rafal at invisiblethingslab dot com>
| Marek Marczykowski <marmarek at invisiblethingslab dot com>
| Bahtiar `kalkin-` Gadimov <bahtiar at gadimov dot de> 

.. vim: ts=3 sw=3 et tw=80
