#!/bin/sh -xe

##
## Run this script in usbvm as root.
## FIXME: this has to be done after each reboot
##

# Copy files
cp misc/usb_add_change /usr/lib/qubes/usb_add_change
cp misc/usb_remove /usr/lib/qubes/usb_remove
cp misc/misc/vusb-ctl.py /usr/lib/qubes/misc/vusb-ctl.py
cp misc/qubes_usb.rules /etc/udev/rules.d/99-qubes_usb.rules

# Reload PVUSB backend and cleanup xenstore
rmmod xen-usbback > /dev/null 2>&1 || true
modprobe xen-usbback
xenstore-rm qubes-usb-devices > /dev/null 2>&1 || true

# Configure udevd and make it re-populate xenstore
udevadm control --reload-rules
udevadm trigger --action=change
