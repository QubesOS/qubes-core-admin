#!/bin/sh

line1="<b>Please wait (up to 120s) while the DispVM savefile is being updated.</b>"
line2="<i><small>This only happens when you have updated the template.</small></i>"
line3="<i><small>Next time will be much faster.</small></i>"

if [ -n "$KDE_FULL_SESSION" ]; then
    br="<br/>"
else
    br="
"
fi
notify-send --icon=/usr/share/qubes/icons/qubes.png --expire-time=120000 \
                   "Updating default DispVM savefile" "$line1$br$line2$br$line3"

ret=0

rm -f /var/run/qubes/qvm-create-default-dvm.stdout
if ! qvm-create-default-dvm --used-template --default-script >/var/run/qubes/qvm-create-default-dvm.stdout </dev/null ; then
	ret=1
fi

exit $ret
