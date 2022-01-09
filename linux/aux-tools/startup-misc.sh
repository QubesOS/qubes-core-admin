#!/usr/bin/sh

# Misc dom0 startup setup
#### KVM:
. /usr/lib/qubes/hypervisor.sh
########

#### KVM:
if hypervisor xen; then
    /usr/lib/qubes/fix-dir-perms.sh
    DOM0_MAXMEM=$(/usr/sbin/xl list 0 | tail -1 | awk '{ print $3 }')
    xenstore-write /local/domain/0/memory/static-max $[ $DOM0_MAXMEM * 1024 ]

    xl sched-credit -d 0 -w 2000
fi
########

cp /var/lib/qubes/qubes.xml /var/lib/qubes/backup/qubes-$(date +%F-%T).xml
/usr/lib/qubes/cleanup-dispvms

# Hide mounted devices from qubes-block list (at first udev run, only / is mounted)
udevadm trigger --action=change --subsystem-match=block
