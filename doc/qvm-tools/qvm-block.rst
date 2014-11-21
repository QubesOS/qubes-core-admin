.. program:: qvm-block

===============================================
:program:`qvm-block` -- List/set VM PCI devices
===============================================

Synopsis
========
| qvm-block -l [options]
| qvm-block -a [options] <device> <vm-name>
| qvm-block -d [options] <device>
| qvm-block -d [options] <vm-name>


Options
=======

.. option:: --help, -h

    Show this help message and exit

.. option:: --list, -l

    List block devices            

.. option:: --attach, -a

    Attach block device to specified VM

.. option:: --detach, -d

    Detach block device

.. option:: --frontend=FRONTEND, -f FRONTEND

    Specify device name at destination VM [default: xvdi]

.. option:: --ro

    Force read-only mode

.. option:: --no-auto-detach

    Fail when device already connected to other VM

Authors
=======
| Joanna Rutkowska <joanna at invisiblethingslab dot com>
| Rafal Wojtczuk <rafal at invisiblethingslab dot com>
| Marek Marczykowski <marmarek at invisiblethingslab dot com>
