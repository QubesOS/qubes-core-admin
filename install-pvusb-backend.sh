#!/bin/sh -xe

##
## Run this script in usbvm as root.
## FIXME: this has to be done after each reboot
##

# Copy files
cp misc/usb_add_change /usr/lib/qubes/usb_add_change
cp misc/usb_remove /usr/lib/qubes/usb_remove
# FIXME cp misc/xen-vusb-helper.py /usr/lib/qubes/xen-vusb-helper.py
cp misc/qubes_usb.rules /etc/udev/rules.d/99-qubes_usb.rules

# Reload PVUSB backend and cleanup xenstore
rmmod xen-usbback || true
modprobe xen-usbback
xenstore-rm qubes-usb-devices

# Configure udevd and make it re-populate xenstore
udevadm control --reload-rules
udevadm trigger --action=change
