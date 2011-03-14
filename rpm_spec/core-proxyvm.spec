#
# The Qubes OS Project, http://www.qubes-os.org
#
# Copyright (C) 2010  Joanna Rutkowska <joanna@invisiblethingslab.com>
# Copyright (C) 2010  Rafal Wojtczuk  <rafal@invisiblethingslab.com>
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

%{!?version: %define version %(cat version_vm)}

Name:		qubes-core-proxyvm
Version:	%{version}
Release:	1
Summary:	The Qubes core files for NetVM

Group:		Qubes
Vendor:		Invisible Things Lab
License:	GPL
URL:		http://www.qubes-os.org
Requires:	/usr/bin/xenstore-read
Requires:   /sbin/ethtool
Requires:   fedora-release = 13
Requires:   qubes-core-netvm

%define _builddir %(pwd)/proxyvm

%description
The Qubes core files for installation inside a Qubes ProxyVM in addition to NetVM scripts.

%pre

%build

%install

mkdir -p $RPM_BUILD_ROOT/etc/init.d
cp init.d/qubes_firewall $RPM_BUILD_ROOT/etc/init.d/
cp init.d/qubes_netwatcher $RPM_BUILD_ROOT/etc/init.d/
mkdir -p $RPM_BUILD_ROOT/usr/sbin
cp bin/qubes_firewall $RPM_BUILD_ROOT/usr/sbin/
cp bin/qubes_netwatcher $RPM_BUILD_ROOT/usr/sbin/

%post

chkconfig --add qubes_firewall || echo "WARNING: Cannot add service qubes_core!"
chkconfig qubes_firewall on || echo "WARNING: Cannot enable service qubes_core!"

chkconfig --add qubes_netwatcher || echo "WARNING: Cannot add service qubes_core!"
chkconfig qubes_netwatcher on || echo "WARNING: Cannot enable service qubes_core!"

%preun
if [ "$1" = 0 ] ; then
    # no more packages left
    chkconfig qubes_firewall off
    chkconfig qubes_netwatcher off
fi

%clean
rm -rf $RPM_BUILD_ROOT

%files
%defattr(-,root,root,-)
/etc/init.d/qubes_firewall
/etc/init.d/qubes_netwatcher
/usr/sbin/qubes_firewall
/usr/sbin/qubes_netwatcher
