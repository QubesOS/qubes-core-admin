#!/bin/sh

# Misc dom0 startup setup

/usr/lib/qubes/fix-dir-perms.sh
DOM0_MAXMEM=$(/usr/sbin/xl list 0 | tail -1 | awk '{ print $3 }')
xenstore-write /local/domain/0/memory/static-max $[ $DOM0_MAXMEM * 1024 ]

xl sched-credit -d 0 -w 2000
cp /var/lib/qubes/qubes.xml /var/lib/qubes/backup/qubes-$(date +%F-%T).xml

/usr/lib/qubes/cleanup-dispvms

if [ -e /sys/module/grant_table/parameters/free_per_iteration ]; then
    echo 1000 > /sys/module/grant_table/parameters/free_per_iteration
fi

# Hide mounted devices from qubes-block list (at first udev run, only / is mounted)
udevadm trigger --action=change --subsystem-match=block
