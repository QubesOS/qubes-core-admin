.. program:: qvm-block

:program:`qvm-block` -- Qubes volume and block device managment
===============================================================

Synopsis
--------
| :command:`qvm-block` [*options*] -l
| :command:`qvm-block` [*options*] -a <*device*> <*vm-name*>
| :command:`qvm-block` [*options*] -d <*device*>
| :command:`qvm-block` [*options*] -d <*vm-name*>


Options
-------

.. option:: --help, -h

   Show this help message and exit

.. option:: --list, -l

   List block devices

.. option:: --attach, -a

   Attach block device to specified domain

.. option:: --detach, -d

   Detach block device


.. option:: -D, --devtype

   Device type. Default is disk

.. option:: --ro

   Force read-only mode

.. option:: --no-auto-detach

   Fail when device already connected to other domain

Authors
-------

| Joanna Rutkowska <joanna at invisiblethingslab dot com>
| Rafal Wojtczuk <rafal at invisiblethingslab dot com>
| Marek Marczykowski <marmarek at invisiblethingslab dot com>
| Bahtiar `kalkin-` Gadimov <bahtiar at gadimov  dot de> 

.. vim: ts=3 sw=3 et tw=80
