#
# The Qubes OS Project, http://www.qubes-os.org
#
# Copyright (C) 2010  Joanna Rutkowska <joanna@invisiblethingslab.com>
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.
#
#

Name:		qubes-dom0-cleanup
Version:	0.2.2
Release:	1
Summary:	Additional tools that cleans up some unnecessary stuff in Qubes's Dom0

Group:		Qubes
Vendor:		Invisible Things Lab
License:	GPL
URL:		http://www.qubes-os.org
Requires:	qubes-core-dom0

%define _builddir %(pwd)/dom0

%description
Additional tools that cleans up some unnecessary stuff in Qubes's Dom0

%install

mkdir -p $RPM_BUILD_ROOT/usr/lib/qubes
cp aux-tools/check_and_remove_appmenu.sh $RPM_BUILD_ROOT/usr/lib/qubes
cp aux-tools/remove_dom0_appmenus.sh $RPM_BUILD_ROOT/usr/lib/qubes

%post
echo "--> Turning off unnecessary services..."
# FIXME: perhaps there is more elegant way to do this? 
for f in /etc/init.d/*
do
        srv=`basename $f`
        [ $srv = 'functions' ] && continue
        [ $srv = 'killall' ] && continue
        [ $srv = 'halt' ] && continue
        chkconfig $srv off
done

#echo "--> Enabling essential services..."
chkconfig abrtd on
chkconfig haldaemon on
chkconfig messagebus on
chkconfig xenstored on
chkconfig xend on
chkconfig xenconsoled on
chkconfig qubes_core on || echo "WARNING: Cannot enable service qubes_core!"
chkconfig qubes_netvm on || echo "WARNING: Cannot enable service qubes_core!"

/usr/lib/qubes/remove_dom0_appmenus.sh

%clean
rm -rf $RPM_BUILD_ROOT

%postun

mv /var/lib/qubes/backup/removed-apps/* /usr/share/applications
xdg-desktop-menu forceupdate

%files
/usr/lib/qubes/check_and_remove_appmenu.sh
/usr/lib/qubes/remove_dom0_appmenus.sh
