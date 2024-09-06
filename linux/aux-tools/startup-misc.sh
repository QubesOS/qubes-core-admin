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

bind_to_pciback() {
    local sbdf="$1"

    if [ -e "/sys/bus/pci/devices/$sbdf/driver" ]; then
        echo "$sbdf" > "/sys/bus/pci/devices/$sbdf/driver/unbind"
    fi
    echo "$sbdf" > /sys/bus/pci/drivers/pciback/new_slot
    echo "$sbdf" > /sys/bus/pci/drivers/pciback/bind
}

# try to figure out desired suspend mode:
# 1. explicit 'suspend-s0ix' set to '1' or '' take precence
# 2. otherwise look for `mem_sleep_default` kernel param
# 3. if none of the above is set, default to S3 if supported

suspend_mode=
if suspend_s0ix=$(qvm-features dom0 suspend-s0ix); then
    if [ "$suspend_s0ix" = "1" ]; then
        suspend_mode=s0ix
    else
        suspend_mode=s3
    fi
fi
if [ -z "$suspend_mode" ] && kopt=$(grep -o 'mem_sleep_default=[^ ]*' /proc/cmdline); then
    # take the last one
    kopt="$(printf '%s' "$kopt" | tail -n 1)"
    if [ "$kopt" = "mem_sleep_default=s2idle" ]; then
        suspend_mode=s0ix
    elif [ "$kopt" = "mem_sleep_default=deep" ]; then
        suspend_mode=s3
    fi
fi
if [ -z "$suspend_mode" ] && grep -q deep /sys/power/mem_sleep; then
    suspend_mode=s3
fi

# at this point $suspend_mode may still be empty as we don't enable s0ix
# implicitly (yet)

if [ "$suspend_mode" = "s0ix" ]; then
    # assign thunderbolt root ports to pciback as workaround for suspend
    # issue without PCI hotplut enabled, see
    # https://github.com/QubesOS/qubes-linux-kernel/pull/903 for details
    for dev in /sys/bus/pci/devices/0000:00:*; do
        [ -h "$dev" ] || continue
        sbdf=$(basename "$dev")
        read -r dev_class < "$dev/class"
        # PCIe bridge
        if [ "$dev_class" = "0x060400" ]; then
            # There seems to be no property saying it's thunderbolt other than product id...
            lspci -s "$sbdf" | grep -q Thunderbolt || continue

            bind_to_pciback "$sbdf"
            echo "$sbdf" > /sys/bus/pci/drivers/pciback/qubes_exp_pm_suspend
            echo "$sbdf" > /sys/bus/pci/drivers/pciback/qubes_exp_pm_suspend_force
        elif [ "$dev_class" = "0x0c0340" ]; then
            # Thunderbolt 4 NIH device
            bind_to_pciback "$sbdf"
            echo "$sbdf" > /sys/bus/pci/drivers/pciback/qubes_exp_pm_suspend
        fi
    done
    echo s2idle > /sys/power/mem_sleep
elif [ "$suspend_mode" = "s3" ]; then
    echo deep > /sys/power/mem_sleep
fi
