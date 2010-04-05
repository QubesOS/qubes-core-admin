#!/bin/sh
SRC=$1
DST=$2
VMNAME=$3
VMDIR=$4

sed -e "s/%VMNAME%/$VMNAME/" \
    -e "s %VMDIR% $VMDIR " \
        <$SRC >$DST


