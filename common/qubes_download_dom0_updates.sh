#!/bin/bash

DOM0_UPDATES_DIR=/var/lib/qubes/dom0-updates

DOIT=0
GUI=1
while [ -n "$1" ]; do
    if [ "x--doit" = "x$1" ]; then
        DOIT=1
    elif [ "x--nogui" = "x$1" ]; then
        GUI=0
    fi
    shift
done

if ! [ -d "$DOM0_UPDATES_DIR" ]; then
    echo "Dom0 updates dir does not exists: $DOM0_UPDATES_DIR"
    exit 1
fi

mkdir -p $DOM0_UPDATES_DIR/etc
cp /etc/yum.conf $DOM0_UPDATES_DIR/etc/

# check also for template updates
echo "Checking for template updates..."
TEMPLATEPKGLIST=`yum check-update -q | cut -f 1 -d ' '`
if [ -n "$TEMPLATEPKGLIST" ] && [ "$GUI" = 1 ]; then
    TEMPLATE_UPDATE_COUNT=`echo "$TEMPLATEPKGLIST" | wc -w`
    NOTIFY_UPDATE_COUNT=`cat /var/run/qubes/template_update_last_notify_count 2> /dev/null`
    if [ "$NOTIFY_UPDATE_COUNT" != "$TEMPLATE_UPDATE_COUNT" ]; then
        echo -n $TEMPLATE_UPDATE_COUNT > /var/run/qubes/template_update_last_notify_count
        NOTIFY_PID=`cat /var/run/qubes/template_update_notify.pid 2> /dev/null`
        if [ -z "$NOTIFY_PID" ] || ! kill -0 $NOTIFY_PID; then
            NOTIFY_TITLE="Template update"
            NOTIFY_TEXT="There are $TEMPLATE_UPDATE_COUNT updates available for TemplateVM"
            NOTIFY_INFO="$NOTIFY_TEXT. Start TemplateVM to update it."
            ( zenity --notification --text "$NOTIFY_TEXT"; zenity --warning --title "$NOTIFY_TITLE" --text "$NOTIFY_INFO") &
            echo $! > /var/run/qubes/template_update_notify.pid
        fi
    fi
fi

echo "Checking for dom0 updates..."
PKGLIST=`yum --installroot $DOM0_UPDATES_DIR check-update -q | cut -f 1 -d ' '`

if [ -z $PKGLIST ]; then
    # No new updates
    exit 0
fi

if [ "$DOIT" != "1" ]; then
    zenity --question --title="Qubes Dom0 updates" \
      --text="Updates for dom0 available. Do you want to download its now?" || exit 0
fi

mkdir -p "$DOM0_UPDATES_DIR/packages"

set -e

if [ "$GUI" = 1 ]; then
    ( echo "1"
    yumdownloader --destdir "$DOM0_UPDATES_DIR/packages" --installroot "$DOM0_UPDATES_DIR" $PKGLIST
    echo 100 ) | zenity --progress --pulsate --auto-close --auto-kill \
         --text="Downloading updates for Dom0, please wait..." --title="Qubes Dom0 updates"
else
    yumdownloader --destdir "$DOM0_UPDATES_DIR/packages" --installroot "$DOM0_UPDATES_DIR" $PKGLIST
fi

# qvm-copy-to-vm works only from user
su -c "/usr/lib/qubes/qrexec_client_vm dom0 qubes.ReceiveUpdates /usr/lib/qubes/qfile-agent $DOM0_UPDATES_DIR/packages/*.rpm" user
