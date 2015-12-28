.. program:: qvm-run

:program:`qvm-run` -- Run a command in a specified VM
=====================================================

Synopsis
--------

:command:`qvm-run` [-h] [--verbose] [--quiet] [--all] [--exclude *EXCLUDE*] [--user *USER*] [--autostart] [--pass-io] [--localcmd *COMMAND*] [--gui] [--no-gui] [--colour-output *COLOR*] [--no-color-output] [--filter-escape-chars] [--no-filter-escape-chars] [*VMNAME*] *COMMAND*

Options
-------

.. option:: --help, -h

   Show the help message and exit.

.. option:: --verbose, -v

   Increase verbosity.

.. option:: --quiet, -q

   Decrease verbosity.

.. option:: --all

   Run the command on all qubes. You can use :option:`--exclude` to limit the
   qubes set. Command is never run on the dom0.

.. option:: --exclude

   Exclude the qube from :option:`--all`.

.. option:: --user=USER, -u USER

   Run command in a qube as *USER*.

.. option:: --auto, --autostart, -a

   Start the qube if it is not running.

.. option:: --pass-io, -p

   Pass standard input and output to and from the remote program.

.. option:: --localcmd=COMMAND

   With :option:`--pass-io`, pass standard input and output to and from the
   given program.

.. option:: --gui

   Run the command with GUI forwarding enabled, which is the default. This
   switch can be used to counter :option:`--no-gui`.

.. option:: --no-gui, --nogui

   Run the command without GUI forwarding enabled. Can be switched back with
   :option:`--gui`.

.. option:: --colour-output=COLOUR, --color-output=COLOR

   Mark the qube output with given ANSI colour (ie. "31" for red). The exact
   apping of numbers to colours and styles depends of the particular terminal
   emulator.

   Colouring can be disabled with :option:`--no-colour-output`.

.. option:: --no-colour-output, --no-color-output

   Disable colouring the stdio.

.. option:: --filter-escape-chars

   Filter terminal escape sequences (default if output is terminal).
   
   Terminal control characters are a security issue, which in worst case amount
   to arbitrary command execution. In the simplest case this requires two often
   found codes: terminal title setting (which puts arbitrary string in the
   window title) and title repo reporting (which puts that string on the shell's
   standard input.

.. option:: --no-filter-escape-chars

   Do not filter terminal escape sequences. This is DANGEROUS when output is
   a terminal emulator. See :option:`--filter-escape-chars` for explanation.

Authors
-------

| Joanna Rutkowska <joanna at invisiblethingslab dot com>
| Rafal Wojtczuk <rafal at invisiblethingslab dot com>
| Marek Marczykowski <marmarek at invisiblethingslab dot com>
| Wojtek Porczyk <woju at invisiblethingslab dot com>

.. vim: ts=3 sw=3 et tw=80
