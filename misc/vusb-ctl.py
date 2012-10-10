#!/usr/bin/python

##
## Python script wrapper around xen.util.vusb_util bind_usb_device() and unbind_usb_device() methods
## Run as root in usbvm
##

from xen.util import vusb_util
import sys
import os

if len(sys.argv)!=3:
    print 'usage: vusb-ctl <bind|unbind> device'
    sys.exit(1)

device=sys.argv[2]
if sys.argv[1] == 'bind':
    vusb_util.bind_usb_device(device)
elif sys.argv[1] == 'ubind':
    vusb_util.unbind_usb_device(device)
else
    print "Invalid command, must be 'bind' or 'unbind'"
    sys.exit(1)

