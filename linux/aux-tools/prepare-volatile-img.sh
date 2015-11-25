#!/bin/sh

if [ "`id -u`" != "0" ]; then
	exec sudo $0 $*
fi

set -e

if ! echo $PATH | grep -q sbin; then
	PATH=$PATH:/sbin:/usr/sbin
fi

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
