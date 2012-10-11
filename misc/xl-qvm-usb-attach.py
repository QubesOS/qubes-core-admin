#!/usr/bin/python

##
## This script is for dom0
## The syntax is modelled after "xl block-attach"
##

import sys
import os
import xen.lowlevel.xl


# parse command line
if (len(sys.argv)<4) or (len(sys.argv)>5):
    print 'usage: xl-qvm-usb-attach.py <frontendvm-xid> <backendvm-device> <frontendvm-device> [<backendvm-xid>]'
    sys.exit(1)

frontendvm_xid=sys.argv[1]
backendvm_device=sys.argv[2]

frontend=sys.argv[3].split('-')
if len(frontend)!=2:
    print 'Error: frontendvm-device must be in <controller>-<port> format'
    sys.exit(1)
(controller, port)=frontend

if len(sys.argv)>4:
    backendvm_xid=int(sys.argv[4])
    backendvm_name=xen.lowlevel.xl.ctx().domid_to_name(backendvm_xid)
else:
    backendvm_xid=0

# FIXME: command injection
os.system("xenstore-write /local/domain/%s/backend/vusb/%s/%s/port/%s %s"
	% (backendvm_xid, frontendvm_xid, controller, port, backendvm_device))

# FIXME: vm.run
cmd = "sudo /usr/lib/qubes/vusb-ctl.py bind %s" % backendvm_device
if backendvm_xid == 0:
    os.system(cmd)
else:
    os.system("qvm-run -p %s '%s'" % (backendvm_name, cmd))
