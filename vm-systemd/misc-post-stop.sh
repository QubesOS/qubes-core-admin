#!/bin/sh

# Save default applications for DispVM

su -c 'mkdir -p /home_volatile/user/.local/share/applications' user
su -c 'cp -a /usr/share/applications/defaults.list /home_volatile/user/.local/share/applications/' user
if [ -r '/home/user/.local/share/applications/defaults.list' ]; then
    su -c 'cat /home/user/.local/share/applications/defaults.list >> /home_volatile/user/.local/share/applications/defaults.list' user
fi

exit 0
