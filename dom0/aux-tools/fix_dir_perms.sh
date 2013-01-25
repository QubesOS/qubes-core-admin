#!/bin/sh
chgrp qubes /etc/xen
chmod 710 /etc/xen
chgrp qubes /var/run/xenstored/*
chmod 660 /var/run/xenstored/*
chgrp qubes /var/lib/xen
chmod 770 /var/lib/xen
chgrp qubes /var/log/xen
chmod 770 /var/log/xen
chgrp qubes /proc/xen/privcmd
chmod 660 /proc/xen/privcmd
chgrp qubes /proc/xen/xenbus
chmod 660 /proc/xen/xenbus
chgrp qubes /dev/xen/evtchn
chmod 660 /dev/xen/evtchn
mkdir -p /var/run/qubes
chgrp qubes /var/run/qubes
chmod 770 /var/run/qubes
touch /var/run/qubes/xl-lock
chgrp qubes /var/run/qubes/xl-lock
chmod 660 /var/run/qubes/xl-lock
chgrp -R qubes /var/log/xen
chmod -R g+rX /var/log/xen
chmod g+s /var/log/xen/console
mkdir -p /var/run/xen-hotplug
