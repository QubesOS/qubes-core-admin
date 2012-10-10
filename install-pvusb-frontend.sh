#!/bin/sh -xe

##
## Run this script in appvm as root
## FIXME: now this has to be done after each reboot
##

modprobe xen-usbfront
