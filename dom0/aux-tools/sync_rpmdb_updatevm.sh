#!/bin/sh

UPDATEVM=`qvm-get-updatevm`

if [ -n "$UPDATEVM" ]; then
    /usr/lib/qubes/qrexec_client -d "$UPDATEVM" -l 'tar c /var/lib/rpm /etc/yum.repos.d 2>/dev/null' 'user:tar x -C /var/lib/qubes/dom0-updates'
fi

# Ignore errors (eg VM not running)
exit 0
