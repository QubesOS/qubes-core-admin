#!/bin/sh

# Return hypervisor name or match result if 'name' provided
hypervisor () {
    local name="$1"
    local hypervisor

    if [[ $(cat /sys/hypervisor/type 2>/dev/null) == 'xen' ]]; then
        hypervisor="xen"

    elif [ -e /sys/devices/virtual/misc/kvm ]; then
        hypervisor="kvm"
    fi

    if [ ! -z $hypervisor ]; then
        if [ -z "$name" ]; then
            echo "$hypervisor"
            return 0
        fi
        if [ "$name" == "$hypervisor" ]; then
            return 0
        fi
    fi
    return 1
}


(return 0 2>/dev/null) && sourced=1 || sourced=0
if (( ! sourced )); then
    hypervisor "$1"
fi

