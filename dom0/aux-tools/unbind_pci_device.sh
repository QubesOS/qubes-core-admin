#!/bin/sh
#
# The Qubes OS Project, http://www.qubes-os.org
#
# Copyright (C) 2010  Joanna Rutkowska <joanna@invisiblethingslab.com>
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.
#
#

BDF=$1
if [ x$BDF = x ] ; then
    echo "usage: $0 <BDF>"
    exit 0
fi
BDF=0000:$BDF
#echo -n "Binding device $BDF to xen-pciback..."
if [ -e /sys/bus/pci/drivers/pciback/$BDF ]; then
    # Already bound to pciback
    # Check if device not assigned to any RUNNING VM
    XS_PATH=/local/domain/0/backend/pci
    GREP_RE="^$XS_PATH/[0-9]*/[0-9]*/dev-[0-9]* = \"$BDF\""
    if xenstore-ls -f $XS_PATH | grep -q "$GREP_RE"; then
        DOMID=`xenstore-ls -f $XS_PATH | grep  "$GREP_RE"|cut -d/ -f7`
        echo "ERROR: Device already attached to the running VM '`xl domname $DOMID`'" >&2
        exit 1
    fi
    exit 0
fi

if [ -e /sys/bus/pci/devices/$BDF/driver/unbind ] ; then 
    echo -n $BDF > /sys/bus/pci/devices/$BDF/driver/unbind || exit 1
fi
echo -n $BDF > /sys/bus/pci/drivers/pciback/new_slot || exit 1
echo -n $BDF > /sys/bus/pci/drivers/pciback/bind || exit 1
#echo ok
