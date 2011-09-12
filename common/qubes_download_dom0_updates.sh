#!/bin/bash

DOM0_UPDATES_DIR=/var/lib/qubes/dom0-updates

DOIT=0
GUI=1
CLEAN=0
OPTS="--installroot $DOM0_UPDATES_DIR"
PKGLIST=
while [ -n "$1" ]; do
    case "$1" in
        --doit)
            DOIT=1
            ;;
        --nogui)
            GUI=0
            ;;
        --clean)
            CLEAN=1
            ;;
        -*)
            OPTS="$OPTS $1"
            ;;
        *)
            PKGLIST="$PKGLIST $1"
            ;;
    esac
    shift
done

if ! [ -d "$DOM0_UPDATES_DIR" ]; then
    echo "Dom0 updates dir does not exists: $DOM0_UPDATES_DIR"
    exit 1
fi

mkdir -p $DOM0_UPDATES_DIR/etc
cp /etc/yum.conf $DOM0_UPDATES_DIR/etc/

if [ "x$CLEAN" = "1" ]; then
    yum $OPTS clean all
fi

if [ "x$PKGLIST" = "x" ]; then
    echo "Checking for dom0 updates..."
    PKGLIST=`yum $OPTS check-update -q | cut -f 1 -d ' '`
else
    PKGS_FROM_CMDLINE=1
fi

if [ -z "$PKGLIST" ]; then
    # No new updates
    exit 0
fi

if [ "$DOIT" != "1" -a "$PKGS_FROM_CMDLINE" != "1" ]; then
    PKGCOUNT=`echo $PKGLIST|wc -w`
    zenity --question --title="Qubes Dom0 updates" \
      --text="$PKGCOUNT updates for dom0 available. Do you want to download its now?" || exit 0
fi

if [ "$PKGS_FROM_CMDLINE" == 1 ]; then
    OPTS="$OPTS --resolve"
    GUI=0
fi

mkdir -p "$DOM0_UPDATES_DIR/packages"

set -e

if [ "$GUI" = 1 ]; then
    ( echo "1"
    yumdownloader --destdir "$DOM0_UPDATES_DIR/packages" $OPTS $PKGLIST
    echo 100 ) | zenity --progress --pulsate --auto-close --auto-kill \
         --text="Downloading updates for Dom0, please wait..." --title="Qubes Dom0 updates"
else
    yumdownloader --destdir "$DOM0_UPDATES_DIR/packages" $OPTS $PKGLIST
fi

if ls $DOM0_UPDATES_DIR/packages/*.rpm > /dev/null 2>&1; then
    /usr/lib/qubes/qrexec_client_vm dom0 qubes.ReceiveUpdates /usr/lib/qubes/qfile-agent $DOM0_UPDATES_DIR/packages/*.rpm
else
    echo "No packages downloaded"
fi
