#!/bin/sh
VMNAME=$1
VMTYPE=$2
if [ -z "$VMTYPE" ]; then
    VMTYPE=appvms
fi
VMDIR=/var/lib/qubes/$VMTYPE/$VMNAME
APPSDIR=$VMDIR/apps

if [ $# != 1 ]; then
    echo "usage: $0 <vmname>"
    exit
fi

if ls $APPSDIR/*.directory $APPSDIR/*.desktop > /dev/null 2>&1; then
    xdg-desktop-menu uninstall $APPSDIR/*.directory $APPSDIR/*.desktop
fi

