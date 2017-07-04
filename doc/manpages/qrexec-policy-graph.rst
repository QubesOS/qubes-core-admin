.. program:: qrexec-policy-graph

:program:`qrexec-policy-graph` -- Graph qrexec policy
=====================================================

Synopsis
--------

:command:`qrexec-policy-graph` [-h] [--include-ask] [--source *SOURCE* [*SOURCE* ...]] [--target *TARGET* [*TARGET* ...]] [--service *SERVICE* [*SERVICE* ...]] [--output *OUTPUT*] [--policy-dir POLICY_DIR] [--system-info SYSTEM_INFO]


Options
-------

.. option:: --help, -h

   show this help message and exit

.. option:: --include-ask

   Include `ask` action in graph. In most cases produce unreadable graphs
   because many services contains `$anyvm $anyvm ask` rules. It's recommended to
   limit graph using other options.

.. option:: --source

   Limit graph to calls from *source*. You can specify multiple names.

.. option:: --target

   Limit graph to calls to *target*. You can specify multiple names.

.. option:: --service

   Limit graph to *service*. You can specify multiple names. This can be either
   bare service name, or service with argument (joined with `+`). If bare
   service name is given, output will contain also policies for specific
   arguments.

.. option:: --output

   Write to *output* instead of stdout. The file will be overwritten without
   confirmation.

.. option:: --policy-dir

   Look for policy in *policy-dir*. This can be useful to process policy
   extracted from other system. This option adjust only base directory, if any
   policy file contains `$include:path` with absolute path, it will try to load
   the file from that location.
   See also --system-info option.

.. option:: --system-info

   Load system information from file instead of querying local qubesd instance.
   The file should be in json format, as returned by `internal.GetSystemInfo`
   qubesd method. This can be obtained by running in dom0:

        qubesd-query -e -c /var/run/qubesd.internal.sock dom0 \
        internal.GetSystemInfo dom0 | cut -b 3-

.. option:: --skip-labels

   Do not include service names on the graph. Also, include only a single
   connection between qubes if any service call is allowed there.


Authors
-------

| Marek Marczykowski-Górecki <marmarek at invisiblethingslab dot com>

.. vim: ts=3 sw=3 et tw=80
