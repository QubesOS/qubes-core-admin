#!/bin/sh -x

d=/home/abb/qubes-core

# Install
cp $d/misc/qubes_usb.rules /etc/udev/rules.d/99-qubes_usb.rules

for f in usb_add_change usb_remove xl-qvm-usb-attach.py ; do
	cp $d/misc/$f /usr/lib/qubes/$f
done

cp $d/dom0/qvm-core/qubesutils.py /usr/lib64/python2.6/site-packages/qubes/qubesutils.py
cp $d/dom0/qvm-tools/qvm-usb /usr/bin/qvm-usb

udevadm control --reload-rules

# Rerun
xenstore-rm qubes-usb-devices
udevadm trigger --action=change
#sleep 1
#xenstore-ls -f qubes-usb-devices

