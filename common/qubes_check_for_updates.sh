#!/bin/sh

DOM0_UPDATES_DIR=/var/lib/qubes/dom0-updates

if ! [ -d "$DOM0_UPDATES_DIR" ]; then
    echo "Dom0 updates dir does not exists: $DOM0_UPDATES_DIR" >&2
    exit 1
fi

mkdir -p $DOM0_UPDATES_DIR/etc
sed -i '/^reposdir\s*=/d' $DOM0_UPDATES_DIR/etc/yum.conf

# check also for template updates
echo "Checking for template updates..." >&2
TEMPLATEPKGLIST=`yum check-update -q | cut -f 1 -d ' '`
echo "template:$TEMPLATEPKGLIST"

echo "Checking for dom0 updates..." >&2
PKGLIST=`yum --installroot $DOM0_UPDATES_DIR check-update -q | cut -f 1 -d ' '`
echo "dom0:$PKGLIST"
