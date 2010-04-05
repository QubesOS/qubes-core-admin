#!/bin/sh

echo "--> Removing unnecessary Dom0 Appmenus..."
find /usr/share/applications -name *.desktop -exec /usr/lib/qubes/check_and_remove_appmenu.sh {} \; 

xdg-desktop-menu forceupdate
