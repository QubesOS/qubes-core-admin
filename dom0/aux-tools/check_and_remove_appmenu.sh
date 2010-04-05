#!/bin/sh
if grep -q X-Qubes-VmName $1 ; then
	exit 0
fi

if grep -q "Categories=.*\(System\|Settings\)" $1 ; then
	#echo "Leaving file: $1"
	exit 0
fi
BACKUP_DIR="/var/lib/qubes/backup/removed-apps/"
mkdir -p $BACKUP_DIR
#echo "Moving file: $1 to $BACKUP_DIR
mv $1 $BACKUP_DIR

