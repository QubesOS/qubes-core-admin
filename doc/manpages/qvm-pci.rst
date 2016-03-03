.. program:: qvm-pci

=============================================
:program:`qvm-pci` -- List/set VM PCI devices
=============================================

Synopsis
========
| :command:`qvm-pci` [*options*] -l <*vm-name*>
| :command:`qvm-pci` [*options*] -a <*vm-name*> <*device*>
| :command:`qvm-pci` [*options*] -d <*vm-name*> <*device*>

Options
=======

.. option:: --help, -h

    Show this help message and exit

.. option:: --list, -l

    List VM PCI devices

.. option:: --add, -a

    Add a PCI device to specified VM

.. option:: --add-class, -C

    Add all devices of given class:
        net - network interfaces
        usb - USB controllers

.. option:: --delete, -d

    Remove a PCI device from specified VM

Authors
=======
| Joanna Rutkowska <joanna at invisiblethingslab dot com>
| Rafal Wojtczuk <rafal at invisiblethingslab dot com>
| Marek Marczykowski <marmarek at invisiblethingslab dot com>
