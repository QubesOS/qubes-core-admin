#!/bin/sh -xe

##
## Run this script in dom0
## FIXME: this has to be done after each reboot
##

# Copy files
cp misc/xl-qvm-usb-attach.py /usr/lib/qubes/xl-qvm-usb-attach.py
cp misc/xl-qvm-usb-detach.py /usr/lib/qubes/xl-qvm-usb-detach.py
cp dom0/qvm-core/qubesutils.py /usr/lib64/python2.6/site-packages/qubes/qubesutils.py
cp dom0/qvm-tools/qvm-usb /usr/bin/qvm-usb
