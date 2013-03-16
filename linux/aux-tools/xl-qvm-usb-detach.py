#!/usr/bin/python

##
## This script is for dom0
## The syntax is modelled after "xl block-attach"
## FIXME: should be modelled after block-detach instead
##

import sys
import os
import xen.lowlevel.xl

# parse command line
if (len(sys.argv)<4) or (len(sys.argv)>5):
    print 'usage: xl-qvm-usb-detach.py <frontendvm-xid> <backendvm-device> <frontendvm-device> [<backendvm-xid>]'
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

cmd = "/usr/lib/qubes/vusb-ctl.py unbind '%s'" % backendvm_device
if backendvm_xid == 0:
    os.system("sudo %s" % cmd)
else:
    from qubes.qubes import QubesVmCollection
    qvm_collection = QubesVmCollection()
    qvm_collection.lock_db_for_reading()
    qvm_collection.load()
    qvm_collection.unlock_db()

    # launch
    qvm_collection.get_vm_by_name(backendvm_name).run(cmd, user="root")

# FIXME: command injection
os.system("xenstore-write /local/domain/%s/backend/vusb/%s/%s/port/%s ''"
	% (backendvm_xid, frontendvm_xid, controller, port))

