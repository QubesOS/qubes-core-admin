#!/bin/sh

# Setup DispVM things at Qubes system startup

printf "\x00\x00\x00\x00" > /var/run/qubes/dispVM.seq
chown root:qubes /var/run/qubes/dispVM.seq
chmod 660 /var/run/qubes/dispVM.seq
DEFAULT=/var/lib/qubes/dvmdata/default-savefile
DEFAULT_CONFIG=/var/lib/qubes/dvmdata/default-dvm.conf
# setup DispVM files only when they exists
if [ -r $DEFAULT ]; then
    ln -s $DEFAULT_CONFIG /var/run/qubes/current-dvm.conf
    if [ -f /var/lib/qubes/dvmdata/dont-use-shm ] ; then
	ln -s $DEFAULT /var/run/qubes/current-savefile
    else
	mkdir -m 770 /dev/shm/qubes
	chown root.qubes /dev/shm/qubes
	cp -a $(readlink $DEFAULT) /dev/shm/qubes/current-savefile
	chown root.qubes /dev/shm/qubes/current-savefile
	chmod 660 /dev/shm/qubes/current-savefile
	ln -s /dev/shm/qubes/current-savefile /var/run/qubes/current-savefile
    fi
fi

