#!/bin/sh

# Find all networking devices currenly installed...
HIDE_PCI=`lspci -mm -n | grep '^[^ ]* "02'|awk '{ ORS="";print "(" $1 ")";}'`

# ... and hide them so that Dom0 doesn't load drivers for them
modprobe pciback hide=$HIDE_PCI 2> /dev/null || modprobe xen-pciback hide=$HIDE_PCI

