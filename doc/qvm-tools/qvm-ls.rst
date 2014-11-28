.. program:: qvm-ls

================================================================
:program:`qvm-ls` -- List VMs and various information about them
================================================================

Synopsis
========
:command:`qvm-ls` [*options*] <*vm-name*>

Options
=======

.. option:: --help, -h

    Show help message and exit

.. option:: --network, -n

    Show network addresses assigned to VMs

.. option:: --cpu, -c

    Show CPU load

.. option:: --mem, -m

    Show memory usage

.. option:: --disk, -d

    Show VM disk utilization statistics

.. option:: --ids, -i

    Show Qubes and Xen id

.. option:: --kernel, -k

    Show VM kernel options

.. option:: --last-backup, -b

    Show date of last VM backup

.. option:: --raw-list

    List only VM names one per line

Authors
=======
| Joanna Rutkowska <joanna at invisiblethingslab dot com>
| Rafal Wojtczuk <rafal at invisiblethingslab dot com>
| Marek Marczykowski <marmarek at invisiblethingslab dot com>
