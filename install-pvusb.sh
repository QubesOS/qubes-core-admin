#!/bin/sh -xe

dom0_usbvm=y
usbvms="usbvm"
appvms="netvm qdvp"

# --- Copy files ---------------------------------------------------------
for vm in $usbvms $appvms ; do
	(cd .. && tar c qubes-core) | qvm-run -p $vm 'tar x'
done

# --- Init dom0 ----------------------------------------------------------
sudo ./install-pvusb-dom0.sh

# --- Init dom0 as usbvm -------------------------------------------------
if [ "$dom0_usbvm" = "y" ] ; then
	sudo ./install-pvusb-backend.sh
fi

# --- Init usbvms --------------------------------------------------------
for usbvm in $usbvms ; do
	usbvm_xid=`xl list | awk "(\\$1==\"$usbvm\"){print \\$2}"`
        if [ -z "$usbvm_xid" ] ; then
		echo "Can't determine xid for $usbvm"
	else
		xenstore-write /local/domain/${usbvm_xid}/qubes-usb-devices ''
		xenstore-chmod /local/domain/${usbvm_xid}/qubes-usb-devices n0 b${usbvm_xid}
	fi

	qvm-run -p $usbvm 'script -qc "cd qubes-core && sudo ./install-pvusb-backend.sh" /dev/null'
done

# --- Init appvm ---------------------------------------------------------
for appvm in $appvms ; do
	qvm-run -p $appvm 'script -qc "cd qubes-core && sudo ./install-pvusb-frontend.sh" /dev/null'
done

