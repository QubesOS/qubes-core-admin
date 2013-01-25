#!/bin/bash

install() {
    inst_hook cmdline 02 "$moddir/qubes-pciback.sh"
    inst lspci
    inst grep
    inst awk
}

installkernel() {
    modinfo -k $kernel pciback > /dev/null 2>&1 && instmods pciback
    modinfo -k $kernel xen-pciback > /dev/null 2>&1 && instmods xen-pciback
}
