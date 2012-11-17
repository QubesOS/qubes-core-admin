#!/bin/sh

possibly_run_save_script()
{
	ENCODED_SCRIPT=$(xenstore-read qubes_save_script)
	if [ -z "$ENCODED_SCRIPT" ] ; then return ; fi
	echo $ENCODED_SCRIPT|perl -e 'use MIME::Base64 qw(decode_base64); local($/) = undef;print decode_base64(<STDIN>)' >/tmp/qubes_save_script
	chmod 755 /tmp/qubes_save_script
	Xorg -config /etc/X11/xorg-preload-apps.conf :0 &
	while ! [ -S /tmp/.X11-unix/X0 ]; do sleep 0.5; done
	DISPLAY=:0 su - user -c /tmp/qubes_save_script
	killall Xorg
}

if xenstore-read qubes_save_request 2>/dev/null ; then
    if [ -L /home ]; then
        rm /home
        mkdir /home
    fi
    mount --bind /home_volatile /home
    touch /etc/this_is_dvm
    mount /rw
    possibly_run_save_script
    umount /rw
    dmesg -c >/dev/null
    free | grep Mem: | 
        (read a b c d ; xenstore-write device/qubes_used_mem $c)
    # we're still running in DispVM template
    echo "Waiting for save/restore..."
    # ... wait until qubes_restore.c (in Dom0) recreates VM-specific keys
    while ! xenstore-read qubes_restore_complete 2>/dev/null ; do 
        usleep 10
    done
    echo Back to life.
fi

