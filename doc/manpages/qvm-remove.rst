.. program:: qvm-remove

:program:`qvm-remove` -- remove domain
======================================

Synopsis
--------
:command:`qvm-remove` [-h] [--verbose] [--quiet] [--force-root] [--just-db] *VMNAME* [*VMNAME* ...]


Options
-------

.. option:: --help, -h

    Show this help message and exit

.. option:: --quiet, -q

    Be quiet

.. option:: --just-db

    Remove only from the Qubes Xen DB, do not remove any files

.. option:: --force-root

    Force to run, even with root privileges

Authors
-------

| Joanna Rutkowska <joanna at invisiblethingslab dot com>
| Rafal Wojtczuk <rafal at invisiblethingslab dot com>
| Marek Marczykowski <marmarek at invisiblethingslab dot com>
| Bahtiar `kalkin-` Gadimov <bahtiar at gadimov dot de> 

.. vim: ts=3 sw=3 et tw=80
