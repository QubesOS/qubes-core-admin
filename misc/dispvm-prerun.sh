#!/bin/sh

apps="evince /usr/libexec/evinced soffice firefox"

#If user have customized DispVM settings, use its home instead of default dotfiles
if [ -e /rw/home/user/.qubes-dispvm-customized ]; then
	cp -af /rw/home/user /home/
else
	cat /etc/dispvm-dotfiles.tbz | tar -xjf- --overwrite -C /home/user --owner user 2>&1 >/tmp/dispvm-dotfiles-errors.log
fi

for app in $apps ; do
    echo "Launching: $app..."
    $app >>/tmp/dispvm_prerun_errors.log 2>&1 &
done

echo "Sleeping..."
PREV_IO=0
while true; do
	IO=`vmstat -D | awk '/read|write/ {IOs+=$1} END {print IOs}'`
	if [ $IO -lt $[ $PREV_IO + 50 ] ]; then
		break;
	fi
	PREV_IO=$IO
	sleep 1
done

ps ax > /tmp/dispvm-prerun-proclist.log

if [ -e /rw/home/user/.qubes-dispvm-customized ]; then
	cp -af /rw/home/user /home/
else
	cat /etc/dispvm-dotfiles.tbz | tar -xjf- --overwrite -C /home/user --owner user 2>&1 >>/tmp/dispvm-dotfiles-errors.log
fi

echo done.
