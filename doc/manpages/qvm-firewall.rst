.. program:: qvm-firewall

:program:`qvm-firewall` -- Manage VM outbound firewall
======================================================

Synopsis
--------

:command:`qvm-firewall` [-h] [--verbose] [--quiet] [--reload] *VMNAME* add *RULE*
:command:`qvm-firewall` [-h] [--verbose] [--quiet] [--reload] *VMNAME* del [--rule-no=*RULE_NUMBER*] [*RULE*]
:command:`qvm-firewall` [-h] [--verbose] [--quiet] [--reload] *VMNAME* list [--raw]
:command:`qvm-firewall` [-h] [--verbose] [--quiet] [--reload] *VMNAME* policy {accept,drop}

Options
-------

.. option:: --help, -h

   show help message and exit

.. option:: --verbose, -v

   increase verbosity

.. option:: --quiet, -q

   decrease verbosity

.. option:: --reload, -r

   force reloading rules even when unchanged

.. option:: --raw

   Print raw rules when listing


Actions description
-------------------

Available actions:

* add - add specified rule. See `Rule syntax` section below.

* del - delete specified rule. Can be selected either by rule number using
:option:`--rule-no`, or specifying rule itself.

* list - list all the rules for a given VM.

* policy - set default action if no rule matches.


Rule syntax
-----------

A single rule is built from:
 - action - either ``drop`` or ``accept``
 - zero or more matches

Selected action is applied on given packet when all specified matches do match,
further rules are not evaluated. If none of the rules match, default action
(``policy``) is applied.

Supported matches:
 - ``dsthost`` - destination host or network. Can be either IP address in CIDR
 notation, or a host name. Both IPv4 and IPv6 are supported by the rule syntax.
 - ``proto`` - specific IP protocol. Supported values: ``tcp``, ``udp``,
 ``icmp``.
 - ``dstports`` - destination port or ports range. Can be either a single port,
 or a range separated by ``-``. Valid only together with ``proto=udp`` or
 ``proto=tcp``.
 - ``icmptype`` - ICMP message type, specified as numeric value. Valid only
 together with ``proto=icmp``.
 - ``specialtarget`` - predefined target. Currently the only supported value is
 ``dns``. This can be combined with other matches to narrow it down.

Authors
-------

| Joanna Rutkowska <joanna at invisiblethingslab dot com>
| Rafal Wojtczuk <rafal at invisiblethingslab dot com>
| Marek Marczykowski <marmarek at invisiblethingslab dot com>
| Wojtek Porczyk <woju at invisiblethingslab dot com>

.. vim: ts=3 sw=3 et tw=80
