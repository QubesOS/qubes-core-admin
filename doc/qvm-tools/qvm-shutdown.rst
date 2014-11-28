.. program:: qvm-shutdown

====================================================
:program:`qvm-shutdown` -- Gracefully shut down a VM
====================================================

Synopsis
========
:command:`qvm-shutdown` [*options*] <*vm-name*>

Options
=======

.. option:: --help, -h

    Show this help message and exit

.. option:: --quiet, -q

    Be quiet           

.. option:: --force

    Force operation, even if may damage other VMs (eg. shutdown of NetVM)

.. option:: --wait

    Wait for the VM(s) to shutdown

.. option:: --all

    Shutdown all running VMs

.. option:: --exclude=EXCLUDE_LIST

    When :option:`--all` is used: exclude this VM name (might be repeated)

Authors
=======
| Joanna Rutkowska <joanna at invisiblethingslab dot com>
| Rafal Wojtczuk <rafal at invisiblethingslab dot com>
| Marek Marczykowski <marmarek at invisiblethingslab dot com>
