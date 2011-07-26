#!/bin/sh
trap "exit 1" USR1 TERM
export SHELL_PID=$$
(
	echo "1"
	if ! qvm-create-default-dvm --default-template --default-script >/var/run/qubes/qvm-create-default-dvm.stdout </dev/null ; then 
		kill -USR1 $SHELL_PID
	fi
        echo 100 
) | zenity --progress --pulsate --auto-close \
	--text="Please wait (up to 120s) while the DispVM savefile is being updated. This only happens when you have updated the template, next time will be much faster." \
	--title="Updating default DispVM savefile"
exit 0
                  