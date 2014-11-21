.. program:: qvm-run

=====================================================
:program:`qvm-run` -- Run a command on a specified VM
=====================================================

Synopsis
========
| qvm-run [options] [<vm-name>] [<cmd>]

Options
=======

.. option:: --help, -h

    Show this help message and exit

.. option:: --quiet, -q

    Be quiet           

.. option:: --auto, -a

    Auto start the VM if not running

.. option:: --user=USER, -u USER

    Run command in a VM as a specified user

.. option:: --tray

    Use tray notifications instead of stdout

.. option:: --all

    Run command on all currently running VMs (or all paused, in case of :option:`--unpause`)

.. option:: --exclude=EXCLUDE_LIST

    When :option:`--all` is used: exclude this VM name (might be repeated)

.. option:: --wait

    Wait for the VM(s) to shutdown

.. option:: --shutdown

    Do 'xl shutdown' for the VM(s) (can be combined with :option:`--all` and
    :option:`--wait`)

    .. deprecated:: R2
       Use :manpage:`qvm-shutdown(1)` instead.

.. option:: --pause

    Do 'xl pause' for the VM(s) (can be combined with :option:`--all` and
    :option:`--wait`)

.. option:: --unpause

    Do 'xl unpause' for the VM(s) (can be combined with :option:`--all` and
    :option:`--wait`)

.. option:: --pass-io, -p

    Pass stdin/stdout/stderr from remote program

.. option:: --localcmd=LOCALCMD

    With :option:`--pass-io`, pass stdin/stdout/stderr to the given program

.. option:: --force

    Force operation, even if may damage other VMs (eg. shutdown of NetVM)

Authors
=======
| Joanna Rutkowska <joanna at invisiblethingslab dot com>
| Rafal Wojtczuk <rafal at invisiblethingslab dot com>
| Marek Marczykowski <marmarek at invisiblethingslab dot com>
