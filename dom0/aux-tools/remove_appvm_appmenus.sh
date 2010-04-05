#!/bin/sh
VMNAME=$1
VMDIR=/var/lib/qubes/appvms/$VMNAME
APPSDIR=$VMDIR/apps

if [ $# != 1 ]; then
    echo "usage: $0 <vmname>"
    exit
fi

xdg-desktop-menu uninstall $APPSDIR/*.directory $APPSDIR/*.desktop

