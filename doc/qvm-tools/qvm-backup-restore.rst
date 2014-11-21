.. program:: qvm-backup-restore

===============================================================
:program:`qvm-backup-restore` -- Restores Qubes VMs from backup
===============================================================

Synopsis
========
| qvm-backup-restore [options] <backup-dir>

Options
=======

.. option:: --help, -h

    Show this help message and exit

.. option:: --skip-broken

    Do not restore VMs that have missing templates or netvms

.. option:: --ignore-missing

    Ignore missing templates or netvms, restore VMs anyway

.. option:: --skip-conflicting

    Do not restore VMs that are already present on the host

.. option:: --force-root

    Force to run, even with root privileges

.. option:: --replace-template=REPLACE_TEMPLATE

    Restore VMs using another template, syntax:
    ``old-template-name:new-template-name`` (might be repeated)

.. option:: --exclude=EXCLUDE, -x EXCLUDE

    Skip restore of specified VM (might be repeated)

.. option:: --skip-dom0-home

    Do not restore dom0 user home dir

.. option:: --ignore-username-mismatch

    Ignore dom0 username mismatch while restoring homedir

Authors
=======
| Joanna Rutkowska <joanna at invisiblethingslab dot com>
| Rafal Wojtczuk <rafal at invisiblethingslab dot com>
| Marek Marczykowski <marmarek at invisiblethingslab dot com>
