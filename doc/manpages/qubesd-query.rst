.. program:: qubesd-query

:program:`qubesd-query` -- low-level qubesd interrogation tool
==============================================================

Synopsis
--------

:command:`qubesd-query` [-h] [--connect *PATH*] *SRC* *METHOD* *DEST* [*ARGUMENT*]

Options
-------

.. option:: --help, -h

   Show the help message and exit.

.. option:: --connect=PATH, -c PATH

   Change path to qubesd UNIX socket from default.

.. option:: --empty, -e

   Send empty payload. Do not attempt to read anything from standard input, but
   send the request immediately.

.. option:: --fail

   Exit with non-0 exit code when qubesd response is not-OK. By default the tool
   will exit with 0 when request is successfully delivered to qubesd, regardless
   of response.

.. option:: --single-line

   Read a single line from standard input and send it to qubesd.  The line must
   only consist of bytes between 0x20 and 0x7E inclusive, and is terminated by
   an ASCII newline (0x10).  Input is read one byte at a time to ensure that
   too many bytes are not read.  There is a limit of 1024 bytes in this mode.

.. option:: --max-bytes

   To prevent excessive memory use, qubesd-query imposes a limit on the amount
   of bytes it will read.  This limit defaults to 65536 if ``--single-line``
   is not passed, and 1024 otherwise.  This option can be used to lower this
   value, though not raise it.

Description
-----------

This tool is used to directly invoke qubesd. The parameters of RPC call shall be
given as arguments to the command. Payload should be written to standard input.
Result can be read from standard output.

Authors
-------

| Joanna Rutkowska <joanna at invisiblethingslab dot com>
| Rafal Wojtczuk <rafal at invisiblethingslab dot com>
| Marek Marczykowski-Górecki <marmarek at invisiblethingslab dot com>
| Wojtek Porczyk <woju at invisiblethingslab dot com>
| Demi Marie Obenour <demi@invisiblethingslab.com>

.. vim: ts=3 sw=3 et tw=80
