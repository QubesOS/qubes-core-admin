#!/usr/bin/python
from xen.util import vusb_util
import sys
import os

if len(sys.argv)!=5:
    print 'usage: xl-qvm-usb-attach.py domain device frontend backend'
    sys.exit(1)

domain=sys.argv[1]
device=sys.argv[2]

frontend=sys.argv[3].split('-')
if len(frontend)!=2:
    print 'frontend in controller/port format'
    sys.exit(1)
(controller, port)=frontend

backend=sys.argv[4]

# FIXME command injection
os.system("xenstore-write /local/domain/%s/backend/vusb/%s/%s/port/%s %s"
	% (backend, domain, controller, port, device))

vusb_util.bind_usb_device(device)
