#!/bin/sh

# Save default applications for DispVM

su -c 'mkdir -p /home_volatile/user/.local/share/applications' user
su -c 'cp -a /home/user/.local/share/applications/defaults.list /home_volatile/user/.local/share/applications/' user

exit 0
