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

Description
-----------

This tool is used to directly invoke qubesd. The parameters of RPC call shall be
given as arguments to the command. Payload should be written to standard input.
Result can be read from standard output.

Authors
-------

| Joanna Rutkowska <joanna at invisiblethingslab dot com>
| Rafal Wojtczuk <rafal at invisiblethingslab dot com>
| Marek Marczykowski <marmarek at invisiblethingslab dot com>
| Wojtek Porczyk <woju at invisiblethingslab dot com>

.. vim: ts=3 sw=3 et tw=80
