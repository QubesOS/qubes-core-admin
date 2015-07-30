#!/bin/sh

if [ "`id -u`" != "0" ]; then
	exec sudo $0 $*
fi

set -e

FILENAME=$1
ROOT_SIZE=$2
SWAP_SIZE=$[ 1024 ]

if [ -z "$ROOT_SIZE" -o -z "$FILENAME" ]; then
	echo "Usage: $0 <filename> <root.img size in MB>"
	exit 1
fi

if [ -e "$FILENAME" ]; then
	echo "$FILENAME already exists, not overriding"
	exit 1
fi

TOTAL_SIZE=$[ $ROOT_SIZE + $SWAP_SIZE + 512 ]
truncate -s ${TOTAL_SIZE}M "$FILENAME"
sfdisk --no-reread -u M "$FILENAME" > /dev/null 2> /dev/null <<EOF
0,${SWAP_SIZE},S
,${ROOT_SIZE},L
EOF

loopdev=`losetup -f --show --partscan "$FILENAME"`
udevadm settle
created=
if [ ! -e ${loopdev}p1 ]; then
	# device wasn't created automatically, probably udev isn't running;
	# create devs manually
	for partdev in /sys/block/$(basename ${loopdev})/loop*p*; do
		mknod /dev/$(basename ${partdev}) b $(cat ${partdev}/dev | tr : ' ')
	done
	created=yes
fi
mkswap -f ${loopdev}p1 > /dev/null
if [ "$created" = "yes" ]; then
	rm -f ${loopdev}p*
fi
losetup -d ${loopdev} || :
chown --reference `dirname "$FILENAME"` "$FILENAME"
