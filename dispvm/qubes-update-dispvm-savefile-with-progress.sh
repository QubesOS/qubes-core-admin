#!/bin/sh

line1="<b>Please wait (up to 120s) while the DispVM savefile is being updated.</b>"
line2="<i><small>This only happens when you have updated the template.</small></i>"
line3="<i><small>Next time will be much faster.</small></i>"

if type kdialog &> /dev/null; then
    ref=`kdialog --title="Updating default DispVM savefile" \
        --progressbar \
"<center>
    <font>
        $line1<br>
        $line2<br>
        $line3
    </font>
</center>" 0`;

    trap "qdbus $ref close" EXIT
else
    pipe=/tmp/qvm-create-default-dvm-$$.progress
    mkfifo $pipe
    zenity --progress --pulsate --auto-close --text "$line1\n$line2\n$line3" < $pipe &
    exec 5>$pipe
    echo 0 >&5
    trap "echo 100 >&5" EXIT
fi

#qdbus $ref showCancelButton true;

ret=0

rm -f /var/run/qubes/qvm-create-default-dvm.stdout
if ! qvm-create-default-dvm --used-template --default-script >/var/run/qubes/qvm-create-default-dvm.stdout </dev/null ; then
	ret=1
fi

exit $ret
