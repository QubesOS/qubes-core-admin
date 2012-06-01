#!/usr/bin/python

import xen.lowlevel.xs
import time
import subprocess

xs = xen.lowlevel.xs.xs()

domain_list = []

def setup_watches():
    global domain_list

    new_domain_list = xs.ls('', '/local/domain')
    for dom in new_domain_list:
        if dom not in domain_list:
            print "Adding: %s" % dom
            xs.watch('/local/domain/%s/backend/vbd' % dom, int(dom))
    for dom in domain_list:
        if dom not in new_domain_list:
            print "Removing: %s" % dom
            xs.unwatch('/local/domain/%s/backend/vbd' % dom, int(dom))
    domain_list = new_domain_list

def handle_vbd_state(path):
    state = xs.read('', path)
    if state == '6':
        # Closed state; wait a moment to not interrupt reconnect
        time.sleep(0.500)
        state = xs.read('', path)
        if state == '6':
            # If still closed, detach device
            path_components = path.split('/')
            # /local/domain/<BACK XID>/backend/vbd/<FRONT XID>/<DEV>/...
            vm_xid = path_components[6]
            vm_dev = path_components[7]
            if vm_xid in domain_list:
                subprocess.call('xl', 'block-detach', vm_xid, vm_dev)

def main():

    xs.watch('@introduceDomain', 'reload')
    xs.watch('@releaseDomain', 'reload')
    setup_watches()
    while True:
        (path, token) = xs.read_watch()
        if token == 'reload':
            setup_watches()
        else:
            if path.endswith('/state'):
                handle_vbd_state(path)

main()
