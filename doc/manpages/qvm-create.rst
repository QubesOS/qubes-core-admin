.. program:: qvm-create

:program:`qvm-create` -- create new domain
==========================================

Synopsis
--------

:command:`qvm-create` [-h] [--xml *XMLFILE*] [--force-root] [--class *CLS*] [--property *NAME*=*VALUE*] [--template *VALUE*] [--label *VALUE*] [--root-copy-from *FILENAME* | --root-move-from *FILENAME*] *VMNAME*

Options
-------

.. option:: --help, -h

   show help message and exit

.. option:: --xml=XMLFILE

   Qubes OS store file

.. option:: --force-root

   Force to run as root.

.. option:: --class, -C

   The new domain class name (default: **AppVM** for
   :py:class:`qubes.vm.appvm.AppVM`).

.. option:: --prop=NAME=VALUE, --property=NAME=VALUE, -p NAME=VALUE

   Set domain's property, like "internal", "memory" or "vcpus". Any property may
   be set this way, even "qid".

.. option:: --template=VALUE, -t VALUE

   Specify the TemplateVM to use, when applicable. This is an alias for
   ``--property template=VALUE``.

.. option:: --label=VALUE, -l VALUE

   Specify the label to use for the new domain (e.g. red, yellow, green, ...).
   This in an alias for ``--property label=VALUE``.

.. option:: --root-copy-from=FILENAME, -r FILENAME

   Use provided :file:`root.img` instead of default/empty one (file will be
   *copied*). This option is mutually exclusive with :option:`--root-move-from`.

.. option:: --root-move-from=FILENAME, -R FILENAME

   Use provided :file:`root.img` instead of default/empty one (file will be
   *moved*). This option is mutually exclusive with :option:`--root-copy-from`.

Options for internal use
------------------------

Do not use if you don't know, what you are doing.

.. option:: --no-root

   Do not create :file:`root.img`. This option is mutually exclusive with
   :option:`--root-copy-from` and :option:`--root-move-from`.


Authors
-------

| Joanna Rutkowska <joanna at invisiblethingslab dot com>
| Rafal Wojtczuk <rafal at invisiblethingslab dot com>
| Marek Marczykowski <marmarek at invisiblethingslab dot com>
| Wojtek Porczyk <woju at invisiblethingslab dot com>

.. vim: ts=3 sw=3 et tw=80
