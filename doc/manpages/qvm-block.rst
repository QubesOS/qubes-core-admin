.. program:: qvm-block

:program:`qvm-block` -- Qubes volume and block device managment
===============================================================

Synopsis
--------

| :command:`qvm-block` *COMMAND* [-h] [--verbose] [--quiet] [options] [arguments]

Description
-----------

.. TODO Add description

Options
-------

.. option:: --help, -h

   Show help message and exit

.. option:: --verbose, -v

   Increase verbosity.

.. option:: --quiet, -q

   Decrease verbosity.

Commands
--------

list
^^^^

| :command:`qvm-block list` [-h] [--verbose] [--quiet] [-p *POOL_NAME*] [-i] [*VMNAME* [*VMNAME* ...]]

List block devices. By default the internal devices are hidden. When the
stdout is connected to a TTY `qvm-block list` will print a pretty table by
omitting redundant data. This behaviour is disabled when `--full` option is
passed or stdout is redirected to a pipe or file.

.. option:: -p, --pool

   list volumes from specified pool

.. option:: -i, --internal

   list internal devices

.. option:: --full

   print domain names

.. option:: --all

   List volumes from all qubes. You can use :option:`--exclude` to limit the
   qubes set. Don't forget — internal devices are hidden by default!

.. option:: --exclude

   Exclude the qube from :option:`--all`.

aliases: ls, l

attach
^^^^^^

| :command:`qvm-block attach` [-h] [--verbose] [--quiet] [--ro] *VMNAME* *POOL_NAME:VOLUME_ID*

Attach the volume with *VOLUME_ID* from *POOL_NAME* to the domain *VMNAME*

.. option:: --ro

   attach device read-only

aliases: a, at

detach
^^^^^^

| :command:`qvm-block detach` [-h] [--verbose] [--quiet] *VMNAME* *POOL_NAME:VOLUME_ID*

Detach the volume with *POOL_NAME:VOLUME_ID* from domain *VMNAME*

aliases: d, dt

Authors
-------

| Joanna Rutkowska <joanna at invisiblethingslab dot com>
| Rafal Wojtczuk <rafal at invisiblethingslab dot com>
| Marek Marczykowski <marmarek at invisiblethingslab dot com>
| Bahtiar `kalkin-` Gadimov <bahtiar at gadimov dot de> 

.. vim: ts=3 sw=3 et tw=80
