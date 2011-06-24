#!/bin/sh

UPDATEVM=`qvm-get-updatevm`

if [ -n "$UPDATEVM" ]; then
    qvm-run -u root --pass_io --localcmd='tar c /var/lib/rpm /etc/yum.repos.d' "$UPDATEVM" 'tar x -C /var/lib/qubes/dom0-updates'
fi

# Ignore errors (eg VM not running)
exit 0
