#!/bin/sh
if ! [ $#  = 2 ] ; then
	echo usage: $0 domainname savefile_to_be_created
	exit 1
fi
export PATH=$PATH:/sbin:/usr/sbin
VMDIR=/var/lib/qubes/appvms/$1
if ! [ -d $VMDIR ] ; then
	echo $VMDIR does not exist ?
	exit 1
fi
if ! qvm-start $1 --no-guid ; then
	exit 1
fi

ID=none
for i in $(xenstore-list /local/domain) ; do
	name=$(xenstore-read /local/domain/$i/name)
	if [ "x"$name = "x"$1 ] ; then
		ID=$i
	fi
done
set -x
if [ $ID = none ] ; then 
	echo cannot get domain id
	exit 1
fi
echo domainid=$ID
xenstore-write /local/domain/$ID/qubes_save_request 1 
xenstore-watch /local/domain/$ID/device/qubes_used_mem
xenstore-read /local/domain/$ID/qubes_gateway | \
	cut -d . -f 2 | tr -d "\n" > $VMDIR/netvm_id.txt
xm block-detach $1 /dev/xvdb
MEM=$(xenstore-read /local/domain/$ID/device/qubes_used_mem)
echo MEM=$MEM
xm mem-set $1 $(($MEM/1000))
sleep 1
touch $2
xm save $1 $2
cd $VMDIR
tar -Scvf saved_cows.tar root-cow.img swap-cow.img


