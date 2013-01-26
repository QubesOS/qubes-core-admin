#!/bin/sh

# Setup DispVM things at Qubes system startup

printf "\x00\x00\x00\x00" > /var/run/qubes/dispVM_seq
chown root:qubes /var/run/qubes/dispVM_seq
chmod 660 /var/run/qubes/dispVM_seq
DEFAULT=/var/lib/qubes/dvmdata/default_savefile
DEFAULT_CONFIG=/var/lib/qubes/dvmdata/default_dvm.conf
# setup DispVM files only when they exists
if [ -r $DEFAULT ]; then
    ln -s $DEFAULT_CONFIG /var/run/qubes/current_dvm.conf
    if [ -f /var/lib/qubes/dvmdata/dont_use_shm ] ; then
	ln -s $DEFAULT /var/run/qubes/current_savefile
    else
	mkdir -m 770 /dev/shm/qubes
	chown root.qubes /dev/shm/qubes
	cp -a $(readlink $DEFAULT) /dev/shm/qubes/current_savefile
	chown root.qubes /dev/shm/qubes/current_savefile
	chmod 660 /dev/shm/qubes/current_savefile
	ln -s /dev/shm/qubes/current_savefile /var/run/qubes/current_savefile
    fi
fi

