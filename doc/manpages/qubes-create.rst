.. program:: qubes-create

:program:`qubes-create` -- Create new Qubes OS store.
=====================================================

This command is the only supported way to create new qubes.xml. It is intended
to be readable though, so you can probably create it manually if you like.

Synopsis
--------

:command:`qubes-create` [-h] [--qubesxml *XMLFILE*] [--property *NAME*=*VALUE*]

Options
-------

.. option:: --help, -h

   show help message and exit

.. option:: --qubesxml=XMLFILE

   Where to put this new file in question.

.. option:: --property=NAME=VALUE, --prop=NAME=VALUE, -p NAME=VALUE

   On creation, set global property *NAME* to *VALUE*.

Authors
-------

| Wojtek Porczyk <woju at invisiblethingslab dot com>

.. vim: ts=3 sw=3 et tw=80
