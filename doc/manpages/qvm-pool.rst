.. program:: qvm-pool

:program:`qvm-pool` -- manage pools
===================================

Synopsis
--------
:command:`qvm-pool` [-h] [--verbose] [--quiet] [--help-drivers] [-o options] [-l | -i *NAME* | -a *NAME* *DRIVER* | -r *NAME*]

Options
-------

.. option:: --help, -h

    Show this help message and exit

.. option:: --quiet, -q

    Be quiet

.. option:: --verbose, -v

    Increase verbosity

.. option:: --help-drivers

    List all known drivers with their options. The listed driver options can be
    used with the ``-o options`` switch.

.. option:: -o options

    Comma separated list of driver options. See ``--help-drivers`` for a list of
    driver options.
    
.. option:: --list, -l

    List all pools.

.. option:: --info NAME, -i NAME

    Show information about a pool

.. option:: --add NAME DRIVER, -a NAME DRIVER

    Add a pool. For supported drivers and their options see ``--help-drivers``.
    Most of the drivers expect some kind of options.

.. option:: --remove NAME, -r NAME

    Remove a pool. This removes only the information about the pool in
    qubes.xml, but does not delete any content.

Examples
--------

Create a pool backed by the default `xen` driver. 
    
::

    qvm-pool -o dir_path=/mnt/foo -a foo xen

Authors
-------
| Bahtiar \`kalkin-\` Gadimov <bahtiar at gadimov dot de> 
