#!/bin/sh

ref=`kdialog --title="Updating default DispVM savefile" \
--progressbar \
"<center>
    <font>
        <b>Please wait (up to 120s) while the DispVM savefile is being updated.</b>
        <br>
        <i><small>
            This only happens when you have updated the template.<br>
            Next time will be much faster.
        </small></i>
    </font>
</center>" 0`;

trap "qdbus $ref close" EXIT

#qdbus $ref showCancelButton true;

ret=0

if ! qvm-create-default-dvm --used-template --default-script >/var/run/qubes/qvm-create-default-dvm.stdout </dev/null ; then
	ret=1
fi

exit $ret
