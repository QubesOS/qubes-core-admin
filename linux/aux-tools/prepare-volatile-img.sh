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

# Loop until we can obtain a lock
counter=1
while [ $counter -le 10 ]; do
  exec 200< $0
  if flock -n 200; then
    loopdev=`losetup -f --show --partscan "$FILENAME"`
    udevadm settle
    mkswap -f ${loopdev}p1 > /dev/null
    losetup -d ${loopdev} || :
    chown --reference `dirname "$FILENAME"` "$FILENAME"
    break
  else
    counter=$((counter++))
    echo "Lock is already obtained.. waiting 5 seconds til we try again (attempt #${counter})"
    sleep 5
  fi
done
