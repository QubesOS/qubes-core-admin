#!/bin/bash
get_encoded_script()
{
	if ! [ -f "$1" ] ; then
		echo $1 is not a file ?
		exit 1
	fi	
	ENCODED_SCRIPT=`cat "$1" | perl -e 'use MIME::Base64 qw(encode_base64); local($/) = undef;print encode_base64(<STDIN>)'|tr -d "\n"`
}

if [ $# != 2 -a $# != 3 ] ; then
	echo usage: $0 domainname savefile_to_be_created [preload script]
	exit 1
fi
export PATH=$PATH:/sbin:/usr/sbin
if [ $# = 3 ] ; then
	get_encoded_script $3
fi
VMDIR=/var/lib/qubes/appvms/$1
if ! [ -d $VMDIR ] ; then
	echo $VMDIR does not exist ?
	exit 1
fi
if ! qvm-start $1 --no-guid --dvm ; then
	exit 1
fi

ID=none
for i in $(xenstore-list /local/domain) ; do
	name=$(xenstore-read /local/domain/$i/name)
	if [ "x"$name = "x"$1 ] ; then
		ID=$i
	fi
done
if [ $ID = none ] ; then 
	echo cannot get domain id
	exit 1
fi
echo "Waiting for DVM domainid=$ID ..."
if [ -n "$ENCODED_SCRIPT" ] ; then
	xenstore-write /local/domain/$ID/qubes_save_script "$ENCODED_SCRIPT"
fi
#set -x
xenstore-write /local/domain/$ID/qubes_save_request 1 
xenstore-watch-qubes /local/domain/$ID/device/qubes_used_mem
xenstore-read /local/domain/$ID/qubes_gateway | \
	cut -d . -f 3 | tr -d "\n" > $VMDIR/netvm_id.txt
xl block-detach $1 xvdb
MEM=$(xenstore-read /local/domain/$ID/device/qubes_used_mem)
echo "DVM boot complete, memory used=$MEM. Saving image..."
QMEMMAN_STOP=/var/run/qubes/do-not-membalance
touch $QMEMMAN_STOP
xl mem-set $1 $(($MEM/1000))
sleep 1
touch $2
if ! xl save $1 $2 $VMDIR/$1.conf; then 
	rm -f $QMEMMAN_STOP
	exit 1
fi
rm -f $QMEMMAN_STOP
cd $VMDIR
# Fix start memory
sed -i -e "s/^memory.*/memory = $((MEM/1000))/" dvm.conf
tar -Scvf saved_cows.tar volatile.img
echo "DVM savefile created successfully."
