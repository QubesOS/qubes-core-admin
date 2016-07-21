.. program:: qvm-clone

:program:`qvm-clone` -- Clones an existing VM by copying all its disk files
===========================================================================

Synopsis
--------
:command:`qvm-clone` [-h] [--verbose] [--quiet] [-p *POOL:VOLUME* | -P POOL] *VMNAME* *NEWVM*

Options
-------

.. option:: --help, -h

    Show this help message and exit

.. option:: -P POOL

    Pool to use for the new domain. All volumes besides snapshots volumes are
    imported in to the specified POOL. ~HIS IS WHAT YOU WANT TO USE NORMALLY.

.. option:: --pool=POOL:VOLUME, -p POOL:VOLUME

    Specify the pool to use for the specific volume

.. option:: --quiet, -q

    Be quiet

.. option:: --verbose, -v

    Increase verbosity

Authors
-------
| Joanna Rutkowska <joanna at invisiblethingslab dot com>
| Rafal Wojtczuk <rafal at invisiblethingslab dot com>
| Marek Marczykowski <marmarek at invisiblethingslab dot com>
| Bahtiar `kalkin-` Gadimov <bahtiar at gadimov dot de> 
