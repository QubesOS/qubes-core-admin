#!/bin/sh -xe

#usbvm=usbvm
usbvm=
appvm=netvm

# --- Copy files ---------------------------------------------------------
for vm in $usbvm $appvm ; do
	(cd .. && tar c qubes-core) | qvm-run -p $vm 'tar x'
done

# --- Init dom0 ----------------------------------------------------------
sudo ./install-pvusb-dom0.sh

# --- Init usbvm (or dom0) -----------------------------------------------
if [ -z "$usbvm" ] ; then
	sudo ./install-pvusb-backend.sh
else
	qvm-run -p $usbvm 'script -qc "cd qubes-core && sudo ./install-pvusb-backend.sh" /dev/null'

	usbvm_xid=`xl list | awk "(\\$1==\"$usbvm\"){print \\$2}"`
        if [ -z "$usbvm_xid" ] ; then
		echo "Can't determine usbvm_xid"
	else
		xenstore-write /local/domain/${usbvm_xid}/qubes-usb-devices ''
		xenstore-chmod /local/domain/${usbvm_xid}/qubes-usb-devices n0 b${usbvm_xid}
	fi
fi

# --- Init appvm ---------------------------------------------------------
qvm-run -p $appvm 'script -qc "cd qubes-core && sudo ./install-pvusb-frontend.sh" /dev/null'
