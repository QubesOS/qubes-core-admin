#!/bin/sh -x

d=/home/abb/qubes-core

# Install
ln -sf $d/misc/qubes_usb.rules /etc/udev/rules.d/99-qubes_usb.rules

for f in usb_add_change usb_remove ; do
	ln -sf $d/misc/$f /usr/lib/qubes/$f
done

udevadm control --reload-rules

# Rerun
xenstore-rm qubes-usb-devices
udevadm trigger --action=change
sleep 1
xenstore-ls qubes-usb-devices

