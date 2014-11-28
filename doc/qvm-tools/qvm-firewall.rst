.. program:: qvm-firewall

=======================================================
:program:`qvm-firewall` -- Qubes firewall configuration
=======================================================

Synopsis
========
:command:`qvm-firewall` [-n] <*vm-name*> [*action*] [*rule spec*]

Rule specification can be one of:
    1. *address*\ |\ *hostname*\ [/*netmask*] tcp|udp *port*\ [-*port*]
    2. *address*\ |\ *hostname*\ [/*netmask*] tcp|udp *service_name*
    3. *address*\ |\ *hostname*\ [/*netmask*] any

Options
=======

.. option:: --help, -h

    Show this help message and exit

.. option:: --list, -l

    List firewall settings (default action)

.. option:: --add, -a

    Add rule

.. option:: --del, -d

    Remove rule (given by number or by rule spec)

.. option:: --policy=SET_POLICY, -P SET_POLICY

    Set firewall policy (allow/deny)

.. option:: --icmp=SET_ICMP, -i SET_ICMP

    Set ICMP access (allow/deny)

.. option:: --dns=SET_DNS, -D SET_DNS

    Set DNS access (allow/deny)

.. option:: --yum-proxy=SET_YUM_PROXY, -Y SET_YUM_PROXY

    Set access to Qubes yum proxy (allow/deny).

    .. note::
       if set to "deny", access will be rejected even if policy set to "allow"

.. option:: --numeric, -n

    Display port numbers instead of services (makes sense only with :option:`--list`)

Authors
=======
| Joanna Rutkowska <joanna at invisiblethingslab dot com>
| Rafal Wojtczuk <rafal at invisiblethingslab dot com>
| Marek Marczykowski <marmarek at invisiblethingslab dot com>
