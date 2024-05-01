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

if [ -n "$(qvm-features dom0 suspend-s0ix)" ]; then
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
fi
