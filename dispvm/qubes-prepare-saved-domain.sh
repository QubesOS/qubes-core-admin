#!/bin/bash

set -o pipefail

get_encoded_script()
{
	ENCODED_SCRIPT=`
		if [ "$1" == "vm-default" ]; then
			echo /usr/lib/qubes/dispvm-prerun.sh
		else
			cat "$1"
		fi | base64 -w0` || exit 1
}

if [ $# != 2 -a $# != 3 ] ; then
	echo "usage: $0 domainname savefile_to_be_created [preload script]" >&2
	exit 1
fi
export PATH=$PATH:/sbin:/usr/sbin
if [ $# = 3 ] ; then
	get_encoded_script $3
fi
VMDIR=/var/lib/qubes/appvms/$1
if ! [ -d $VMDIR ] ; then
	echo "$VMDIR does not exist ?" >&2
	exit 1
fi
if ! qvm-start $1 --dvm ; then
	exit 1
fi

ID=`virsh -c xen:/// domid $1`
echo "Waiting for DVM $1 ..." >&2
if [ -n "$ENCODED_SCRIPT" ] ; then
	qubesdb-write -d $1 /qubes-save-script "$ENCODED_SCRIPT"
fi
#set -x
qubesdb-write -d $1 /qubes-save-request 1
qubesdb-watch -d $1 /qubes-used-mem
qubesdb-read -d $1 /qubes-gateway | \
	cut -d . -f 3 | tr -d "\n" > $VMDIR/netvm-id.txt
kill `cat /var/run/qubes/guid-running.$ID`
# FIXME: get connection URI from core scripts
virsh -c xen:/// detach-disk $1 xvdb
MEM=$(qubesdb-read -d $1 /qubes-used-mem | grep '^[0-9]\+$' | head -n 1)
echo "DVM boot complete, memory used=$MEM. Saving image..." >&2
QMEMMAN_STOP=/var/run/qubes/do-not-membalance
touch $QMEMMAN_STOP
virsh -c xen:/// setmem $1 $MEM
# Add some safety margin
virsh -c xen:/// setmaxmem $1 $[ $MEM + 1024 ]
# Stop qubesdb daemon now, so VM can restart it later
kill `cat /var/run/qubes/qubesdb.$1.pid`
sleep 1
touch $2
if ! virsh -c xen:/// save $1 $2; then
	rm -f $QMEMMAN_STOP
	qvm-kill $1
	exit 1
fi
rm -f $QMEMMAN_STOP
# Do not allow smaller allocation than 400MB. If that small number comes from
# an error, it would prevent further savefile regeneration (because VM would
# not start with too little memory). Also 'maxmem' depends on 'memory', so
# 400MB is sane compromise.
if [ "$MEM" -lt 409600 ]; then
    qvm-prefs -s $1 memory 400
else
    qvm-prefs -s $1 memory $[ $MEM / 1024 ]
fi
ln -snf $VMDIR /var/lib/qubes/dvmdata/vmdir
cd $VMDIR
fstype=`df --output=fstype $VMDIR | tail -n 1`
if [ "$fstype" = "tmpfs" ]; then
    # bsdtar doesn't work on tmpfs because FS_IOC_FIEMAP ioctl isn't supported
    # there
    tar -cSf saved-cows.tar volatile.img
else
    bsdtar -cSf saved-cows.tar volatile.img
fi
echo "DVM savefile created successfully."
