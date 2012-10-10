#!/bin/sh -xe

##
## Run this script in usbvm as root.
## FIXME: this has to be done after each reboot
##

# Copy files
for f in usb_add_change usb_remove xl-qvm-usb-attach.py ; do
	cp misc/$f /usr/lib/qubes/$f
done

cp dom0/qvm-core/qubesutils.py /usr/lib64/python2.6/site-packages/qubes/qubesutils.py
cp dom0/qvm-tools/qvm-usb /usr/bin/qvm-usb

cp misc/qubes_usb.rules /etc/udev/rules.d/99-qubes_usb.rules

# Reload PVUSB backend and cleanup xenstore
rmmod xen-usbback || true
modprobe xen-usbback
xenstore-rm qubes-usb-devices

# Configure udevd and make it re-populate xenstore
udevadm control --reload-rules
udevadm trigger --action=change
