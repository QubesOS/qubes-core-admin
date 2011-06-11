#!/bin/sh

UPDATEABLE=`/usr/bin/xenstore-read qubes_vm_updateable`

if [ "$UPDATEABLE" = "True" ]; then
    echo -n SYNC > /var/run/qubes/qrexec_agent
fi
