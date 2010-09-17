#!/bin/sh
FILE=/etc/NetworkManager/NetworkManager.conf
VIFMAC=mac:fe:ff:ff:ff:ff:ff
if ! grep -q ^plugins.*keyfile $FILE ; then
	sed -i 's/^plugins.*$/&,keyfile/' $FILE
	echo '[keyfile]' >> $FILE
fi
if ! grep -q ^unmanaged-devices $FILE ; then
	sed -i 's/^\[keyfile\]$/\[keyfile\]\x0aunmanaged-devices='$VIFMAC/ $FILE
fi
if ! grep -q ^unmanaged-devices.*$VIFMAC $FILE ; then
	sed -i 's/^unmanaged-devices.*$/&,'$VIFMAC/ $FILE
fi
exit 0
