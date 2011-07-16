#!/bin/sh

# 6h
UPDATES_SLEEP=21600
UPDATES_VM=`qvm-get-updatevm`

QREXEC_CLIENT=/usr/lib/qubes/qrexec_client

if [ -z "$UPDATES_VM" ]; then
    echo "UpdateVM not set, exiting!" >&2
    exit 1
fi

if ! xl domid "$UPDATES_VM" > /dev/null 2>&1; then
    echo "UpdateVM not started, exiting!"
    exit 1
fi

(
# Allow only one instance
flock --nonblock -s 200 || exit 1
/usr/lib/qubes/sync_rpmdb_updatevm.sh
while true; do
    # Output of this script is UNTRUSTED!
    $QREXEC_CLIENT -d $UPDATES_VM "user:/usr/lib/qubes/qubes_check_for_updates.sh" |\
    while IFS=: read -n 819200 domain packages; do
        if [ "x$domain" = "xtemplate" -a -n "$packages" ]; then
            TEMPLATE_UPDATE_COUNT=`echo "$packages" | wc -w`
            NOTIFY_UPDATE_COUNT=`cat /var/run/qubes/template_update_last_notify_count 2> /dev/null`
            if [ "$NOTIFY_UPDATE_COUNT" != "$TEMPLATE_UPDATE_COUNT" ]; then
                echo -n $TEMPLATE_UPDATE_COUNT > /var/run/qubes/template_update_last_notify_count
                NOTIFY_PID=`cat /var/run/qubes/template_update_notify.pid 2> /dev/null`
                if [ -z "$NOTIFY_PID" ] || ! kill -0 $NOTIFY_PID; then
                    # Actually this is for one TemplateVM, the base of
                    # UpdatesVM. But most likely this can apply to other
                    # templates too (based on the same system - Fedora 14
                    # currently)
                    NOTIFY_TITLE="Template update"
                    NOTIFY_TEXT="There are $TEMPLATE_UPDATE_COUNT updates available for TemplateVM"
                    NOTIFY_INFO="$NOTIFY_TEXT. Start TemplateVM to update it."
                    ( zenity --notification --text "$NOTIFY_TEXT"; zenity --warning --title "$NOTIFY_TITLE" --text "$NOTIFY_INFO") &
                    echo $! > /var/run/qubes/template_update_notify.pid
                fi
            fi
        elif [ "x$domain" = "dom0" -a -n "$packages" ]; then
            PKGCOUNT=`echo -- "$packages" | wc -w`
            if zenity --question --title="Qubes Dom0 updates" \
               --text="$PKGCOUNT updates for dom0 available. Do you want to download its now?"; then
                $QREXEC_CLIENT -d $UPDATES_VM "user:/usr/lib/qubes/qubes_download_dom0_updates.sh --doit"
                # Wait for download completed
                while pidof -x qubes-receive-updates >/dev/null; do sleep 0.5; done
                # Yes, I know that it will block future checking for updates,
                # but it is intentional (to not flood user with updates
                # notification)
                gpk-update-viewer
            fi
        fi
    done
    
    # At the end synchronize clock
    UNTRUSTED_CURRENT_TIME="`$QREXEC_CLIENT -d $UPDATES_VM 'user:date +%s.%N'`"
    # I believe that date has safe input parsing...
    sudo date -s "$UNTRUSTED_CURRENT_TIME"
    sleep $UPDATES_SLEEP
done


) 200> /var/run/qubes/updates-watch-lock
