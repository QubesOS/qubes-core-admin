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

Name:		qubes-core-netvm
Version:	%{version}
Release:	1%{dist}
Summary:	The Qubes core files for NetVM

Group:		Qubes
Vendor:		Invisible Things Lab
License:	GPL
URL:		http://www.qubes-os.org
Requires:	/usr/bin/xenstore-read
Requires:   fedora-release
Requires:       NetworkManager >= 0.8.1-1
Requires:   qubes-core-commonvm
Provides:   qubes-core-vm

%define _builddir %(pwd)/netvm

%description
The Qubes core files for installation inside a Qubes NetVM.

%pre

%build
make -C ../vchan
make -C ../u2mfn

%install

mkdir -p $RPM_BUILD_ROOT/etc
mkdir -p $RPM_BUILD_ROOT/etc/init.d
cp qubes_core_netvm $RPM_BUILD_ROOT/etc/init.d/
mkdir -p $RPM_BUILD_ROOT/var/lib/qubes
mkdir -p $RPM_BUILD_ROOT/usr/lib/qubes
cp ../common/qubes_setup_dnat_to_ns $RPM_BUILD_ROOT/usr/lib/qubes
cp ../common/qubes_fix_nm_conf.sh $RPM_BUILD_ROOT/usr/lib/qubes
mkdir -p $RPM_BUILD_ROOT/etc/dhclient.d
ln -s /usr/lib/qubes/qubes_setup_dnat_to_ns $RPM_BUILD_ROOT/etc/dhclient.d/qubes_setup_dnat_to_ns.sh 
mkdir -p $RPM_BUILD_ROOT/etc/NetworkManager/dispatcher.d/
cp ../common/qubes_nmhook $RPM_BUILD_ROOT/etc/NetworkManager/dispatcher.d/
cp ../netvm/30-qubes_external_ip $RPM_BUILD_ROOT/etc/NetworkManager/dispatcher.d/
mkdir -p $RPM_BUILD_ROOT/var/run/qubes
mkdir -p $RPM_BUILD_ROOT/etc/xen/scripts
cp ../common/vif-route-qubes $RPM_BUILD_ROOT/etc/xen/scripts

%post

# Create NetworkManager configuration if we do not have it
if ! [ -e /etc/NetworkManager/NetworkManager.conf ]; then
echo '[main]' > /etc/NetworkManager/NetworkManager.conf
echo 'plugins = keyfile' >> /etc/NetworkManager/NetworkManager.conf
echo '[keyfile]' >> /etc/NetworkManager/NetworkManager.conf
fi
/usr/lib/qubes/qubes_fix_nm_conf.sh

chkconfig --add qubes_core_netvm || echo "WARNING: Cannot add service qubes_core!"
chkconfig qubes_core_netvm on || echo "WARNING: Cannot enable service qubes_core!"

# Remove ip_forward setting from sysctl, so NM will not reset it
sed 's/^net.ipv4.ip_forward.*/#\0/'  -i /etc/sysctl.conf

%preun
if [ "$1" = 0 ] ; then
    # no more packages left
    chkconfig qubes_core_netvm off
fi

%clean
rm -rf $RPM_BUILD_ROOT

%files
%defattr(-,root,root,-)
/etc/init.d/qubes_core_netvm
/usr/lib/qubes/qubes_setup_dnat_to_ns
/usr/lib/qubes/qubes_fix_nm_conf.sh
/etc/dhclient.d/qubes_setup_dnat_to_ns.sh
/etc/NetworkManager/dispatcher.d/qubes_nmhook
/etc/NetworkManager/dispatcher.d/30-qubes_external_ip
/etc/xen/scripts/vif-route-qubes
