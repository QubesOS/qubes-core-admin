.. program:: qvm-pci

=============================================
:program:`qvm-pci` -- List/set VM PCI devices
=============================================

Synopsis
========
| qvm-pci -l [options] <vm-name>
| qvm-pci -a [options] <vm-name> <device>
| qvm-pci -d [options] <vm-name> <device>
 
Options
=======

.. option:: --help, -h

    Show this help message and exit

.. option:: --list, -l

    List VM PCI devices    

.. option:: --add, -a

    Add a PCI device to specified VM

.. option:: --delete, -d

    Remove a PCI device from specified VM

Authors
=======
| Joanna Rutkowska <joanna at invisiblethingslab dot com>
| Rafal Wojtczuk <rafal at invisiblethingslab dot com>
| Marek Marczykowski <marmarek at invisiblethingslab dot com>
