.. program:: qvm-start

============================================
:program:`qvm-start` -- Start a specified VM
============================================

Synopsis
========
| qvm-start [options] <vm-name>

Options
=======

.. option:: --help, -h

    Show this help message and exit

.. option:: --quiet, -q

    Be quiet           

.. option:: --no-guid

    Do not start the GUId (ignored)

.. option:: --console

    Attach debugging console to the newly started VM

.. option:: --dvm

    Do actions necessary when preparing DVM image

.. option:: --custom-config=CUSTOM_CONFIG

    Use custom Xen config instead of Qubes-generated one

Authors
=======
| Joanna Rutkowska <joanna at invisiblethingslab dot com>
| Rafal Wojtczuk <rafal at invisiblethingslab dot com>
| Marek Marczykowski <marmarek at invisiblethingslab dot com>
