#!/bin/sh

# Setup gateway for all the VMs this netVM is serviceing...
network=$(/usr/bin/xenstore-read qubes_netvm_network 2>/dev/null)
if [ "x$network" != "x" ]; then
    gateway=$(/usr/bin/xenstore-read qubes_netvm_gateway)
    netmask=$(/usr/bin/xenstore-read qubes_netvm_netmask)
    secondary_dns=$(/usr/bin/xenstore-read qubes_netvm_secondary_dns)
    modprobe netbk 2> /dev/null || modprobe xen-netback
    echo "NS1=$gateway" > /var/run/qubes/qubes_ns
    echo "NS2=$secondary_dns" >> /var/run/qubes/qubes_ns
    /usr/lib/qubes/qubes_setup_dnat_to_ns
    echo "1" > /proc/sys/net/ipv4/ip_forward
fi
