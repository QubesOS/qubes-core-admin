#!/bin/sh

# Misc dom0 startup setup

/usr/lib/qubes/fix_dir_perms.sh
xenstore-write /local/domain/0/name dom0
DOM0_MAXMEM=`/usr/sbin/xl info | grep total_memory | awk '{ print $3 }'`
xenstore-write /local/domain/0/memory/static-max $[ $DOM0_MAXMEM * 1024 ]

xl sched-credit -d 0 -w 512
cp /var/lib/qubes/qubes.xml /var/lib/qubes/backup/qubes-$(date +%F-%T).xml

/usr/lib/qubes/cleanup_dispvms

# Hide mounted devices from qubes-block list (at first udev run, only / is mounted)
for dev in `xenstore-list /local/domain/0/qubes-block-devices 2> /dev/null`; do
    ( eval `udevadm info -q property -n $dev|sed -e 's/\([^=]*\)=\(.*\)/export \1="\2"/'`;
    /usr/lib/qubes/block_add_change > /dev/null
    )
done

