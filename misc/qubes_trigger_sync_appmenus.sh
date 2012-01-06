#!/bin/sh

UPDATEABLE=`/usr/bin/xenstore-read qubes_vm_updateable`

if [ "$UPDATEABLE" = "True" ]; then
    /usr/lib/qubes/qrexec_client_vm dom0 qubes.SyncAppMenus /bin/grep -H = /usr/share/applications/*.desktop
fi
