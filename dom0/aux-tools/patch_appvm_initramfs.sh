#!/bin/sh
#
# The Qubes OS Project, http://www.qubes-os.org
#
# Copyright (C) 2010  Joanna Rutkowska <joanna@invisiblethingslab.com>
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.
#
#

#
# This script can be used to patch the initramfs of the Qubes AppVM
# It inserts an additional script that is responsible for setting up
# COW-based root fs and VM private fs
# 

INITRAMFS=$1
INITRAMFS_QUBES=$2
QUBES_COW_SETUP_FILE=$3


TMP_DIR=`mktemp -d /tmp/qubes-initramfs-patching-XXXXXXX`

if [ $# != 3 ] ; then
    echo "usage: $0 <original initramfs to patch> <patched initramfs file> <qubes_cow_setup_file>"
    exit 0
fi

if [ x$INITRAMFS = x ] ; then
    echo "INITRAMFS missing!"
    exit 1
fi

if [ x$INITRAMFS_QUBES = x ] ; then
    echo "INITRAMFS_QUBES missing!"
    exit 1
fi

if [ x$QUBES_COW_SETUP_FILE = x ] ; then
    echo "$QUBES_COW_SETUP_FILE missing!"
    exit 1
fi


ID=$(id -ur)

if [ $ID != 0 ] ; then
    echo "This script should be run as root user. Apparently the initramfs files must have root.root owener..."
    exit 1
fi

mkdir $TMP_DIR/initramfs.qubes || exit 1

cp $INITRAMFS $TMP_DIR/initramfs.cpio.gz

pushd $TMP_DIR/initramfs.qubes

gunzip < ../initramfs.cpio.gz | cpio -i --quiet || exit 1

cp $QUBES_COW_SETUP_FILE pre-trigger/90_qubes_cow_setup.sh || exit 1

find ./ | cpio -H newc -o --quiet > $TMP_DIR/initramfs.qubes.cpio || exit 1

popd

gzip $TMP_DIR/initramfs.qubes.cpio || exit 1

mv $TMP_DIR/initramfs.qubes.cpio.gz $INITRAMFS_QUBES || exit 1

rm -fr $TMP_DIR || exit 1
