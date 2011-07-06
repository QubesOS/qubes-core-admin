#!/bin/sh

UPDATEABLE=`/usr/bin/xenstore-read qubes_vm_updateable`

if [ "$UPDATEABLE" = "True" ]; then
    /usr/lib/qubes/qrexec_vm /bin/grep dom0 qubes.SyncAppMenus -H = /usr/share/applications/*.desktop
fi
