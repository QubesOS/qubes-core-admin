#
# This is the SPEC file for creating binary RPMs for the Dom0.
#
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

%{!?python_sitearch: %define python_sitearch %(%{__python} -c "from distutils.sysconfig import get_python_lib; print get_python_lib(1)")}

%{!?version: %define version %(cat version_dom0)}

Name:		qubes-core-dom0
Version:	%{version}
Release:	1
Summary:	The Qubes core files (Dom0-side)

Group:		Qubes
Vendor:		Invisible Things Lab
License:	GPL
URL:		http://www.qubes-os.org
Requires:	python, xen-runtime, pciutils, python-inotify, python-daemon, kernel-qubes-dom0

%define _builddir %(pwd)/dom0

%description
The Qubes core files for installation on Dom0.

%build
python -m compileall qvm-core
python -O -m compileall qvm-core
make -C restore

%install

mkdir -p $RPM_BUILD_ROOT/etc/init.d
cp init.d/qubes_core $RPM_BUILD_ROOT/etc/init.d/
cp init.d/qubes_netvm $RPM_BUILD_ROOT/etc/init.d/

mkdir -p $RPM_BUILD_ROOT/usr/bin/
cp qvm-tools/qvm-* $RPM_BUILD_ROOT/usr/bin
cp clipboard_notifier/qclipd $RPM_BUILD_ROOT/usr/bin
cp pendrive_swapper/qfilexchgd $RPM_BUILD_ROOT/usr/bin

mkdir -p $RPM_BUILD_ROOT/etc/xen/scripts
cp restore/block.qubes $RPM_BUILD_ROOT/etc/xen/scripts

mkdir -p $RPM_BUILD_ROOT%{python_sitearch}/qubes
cp qvm-core/qubes.py $RPM_BUILD_ROOT%{python_sitearch}/qubes
cp qvm-core/qubes.py[co] $RPM_BUILD_ROOT%{python_sitearch}/qubes
cp qvm-core/__init__.py $RPM_BUILD_ROOT%{python_sitearch}/qubes
cp qvm-core/__init__.py[co] $RPM_BUILD_ROOT%{python_sitearch}/qubes

mkdir -p $RPM_BUILD_ROOT/usr/lib/qubes
cp aux-tools/patch_appvm_initramfs.sh $RPM_BUILD_ROOT/usr/lib/qubes
cp aux-tools/unbind_pci_device.sh $RPM_BUILD_ROOT/usr/lib/qubes
cp aux-tools/unbind_all_network_devices $RPM_BUILD_ROOT/usr/lib/qubes
cp aux-tools/convert_apptemplate2vm.sh $RPM_BUILD_ROOT/usr/lib/qubes
cp aux-tools/convert_dirtemplate2vm.sh $RPM_BUILD_ROOT/usr/lib/qubes
cp aux-tools/create_apps_for_appvm.sh $RPM_BUILD_ROOT/usr/lib/qubes
cp aux-tools/remove_appvm_appmenus.sh $RPM_BUILD_ROOT/usr/lib/qubes
cp pendrive_swapper/qubes_pencmd $RPM_BUILD_ROOT/usr/lib/qubes

cp restore/xenstore-watch restore/qvm-create-default-dvm $RPM_BUILD_ROOT/usr/bin
cp restore/qubes_restore restore/xenfreepages $RPM_BUILD_ROOT/usr/lib/qubes
cp restore/qubes_prepare_saved_domain.sh  $RPM_BUILD_ROOT/usr/lib/qubes

mkdir -p $RPM_BUILD_ROOT/var/lib/qubes
mkdir -p $RPM_BUILD_ROOT/var/lib/qubes/vm-templates
mkdir -p $RPM_BUILD_ROOT/var/lib/qubes/appvms

mkdir -p $RPM_BUILD_ROOT/var/lib/qubes/backup
mkdir -p $RPM_BUILD_ROOT/var/lib/qubes/dvmdata

mkdir -p $RPM_BUILD_ROOT/usr/share/qubes/icons
cp icons/*.png $RPM_BUILD_ROOT/usr/share/qubes/icons

mkdir -p $RPM_BUILD_ROOT/etc/yum.repos.d
cp ../dom0/qubes.repo $RPM_BUILD_ROOT/etc/yum.repos.d

mkdir -p $RPM_BUILD_ROOT/usr/bin
cp ../common/qubes_setup_dnat_to_ns $RPM_BUILD_ROOT/usr/lib/qubes
mkdir -p $RPM_BUILD_ROOT/etc/dhclient.d
ln -s /usr/lib/qubes/qubes_setup_dnat_to_ns $RPM_BUILD_ROOT/etc/dhclient.d/qubes_setup_dnat_to_ns.sh 
mkdir -p $RPM_BUILD_ROOT/etc/NetworkManager/dispatcher.d/
cp ../common/qubes_nmhook $RPM_BUILD_ROOT/etc/NetworkManager/dispatcher.d/
mkdir -p $RPM_BUILD_ROOT/etc/sysconfig
cp init.d/iptables $RPM_BUILD_ROOT/etc/sysconfig

mkdir -p $RPM_BUILD_ROOT/usr/lib64/pm-utils/sleep.d
cp pm-utils/01qubes-sync-vms-clock $RPM_BUILD_ROOT/usr/lib64/pm-utils/sleep.d/
cp pm-utils/02qubes-pause-vms $RPM_BUILD_ROOT/usr/lib64/pm-utils/sleep.d/

%triggerin -- xen-runtime
sed -i 's/\/block /\/block.qubes /' /etc/udev/rules.d/xen-backend.rules

%post

if [ -e /etc/yum.repos.d/qubes-r1-dom0.repo ]; then
# we want the user to use the repo that comes with qubes-code-dom0 packages instead
rm -f /etc/yum.repos.d/qubes-r1-dom0.repo
fi

if [ "$1" !=  1 ] ; then
# do this whole %post thing only when updating for the first time...
exit 0
fi

# TODO: This is only temporary, until we will have our own installer
for f in /etc/init.d/*
do
        srv=`basename $f`
        [ $srv = 'functions' ] && continue
        [ $srv = 'killall' ] && continue
        [ $srv = 'halt' ] && continue
        chkconfig $srv off
done

chkconfig iptables on
chkconfig NetworkManager on
chkconfig rsyslog on
chkconfig haldaemon on
chkconfig messagebus on
chkconfig xenstored on
chkconfig xend on
chkconfig xenconsoled on

sed 's/^net.ipv4.ip_forward.*/net.ipv4.ip_forward = 1/'  -i /etc/sysctl.conf

chkconfig --add qubes_core || echo "WARNING: Cannot add service qubes_core!"
chkconfig --add qubes_netvm || echo "WARNING: Cannot add service qubes_netvm!"

chkconfig qubes_core on || echo "WARNING: Cannot enable service qubes_core!"
chkconfig qubes_netvm on || echo "WARNING: Cannot enable service qubes_netvm!"

if ! [ -e /var/lib/qubes/qubes.xml ]; then
#    echo "Initializing Qubes DB..."
    umask 007; sg qubes -c qvm-init-storage
fi
for i in /usr/share/qubes/icons/*.png ; do
	xdg-icon-resource install --novendor --size 48 $i
done

%clean
rm -rf $RPM_BUILD_ROOT

%pre
if ! grep -q ^qubes: /etc/group ; then
		groupadd qubes
fi

%preun
if [ "$1" = 0 ] ; then
	for i in /usr/share/qubes/icons/*.png ; do
		xdg-icon-resource uninstall --novendor --size 48 $i
	done
fi

%postun
if [ "$1" = 0 ] ; then
	# no more packages left
    chgrp root /etc/xen
    chmod 700 /etc/xen
    groupdel qubes
    sed -i 's/\/block.qubes /\/block /' /etc/udev/rules.d/xen-backend.rules
fi

%files
%defattr(-,root,root,-)
/etc/init.d/qubes_core
/etc/init.d/qubes_netvm
/usr/bin/qvm-*
/usr/bin/qclipd
/usr/bin/qfilexchgd
%{python_sitearch}/qubes/qubes.py
%{python_sitearch}/qubes/qubes.pyc
%{python_sitearch}/qubes/qubes.pyo
%{python_sitearch}/qubes/__init__.py
%{python_sitearch}/qubes/__init__.pyc
%{python_sitearch}/qubes/__init__.pyo
/usr/lib/qubes/patch_appvm_initramfs.sh
/usr/lib/qubes/unbind_pci_device.sh
/usr/lib/qubes/unbind_all_network_devices
/usr/lib/qubes/convert_apptemplate2vm.sh
/usr/lib/qubes/convert_dirtemplate2vm.sh
/usr/lib/qubes/create_apps_for_appvm.sh
/usr/lib/qubes/remove_appvm_appmenus.sh
/usr/lib/qubes/qubes_pencmd
%attr(770,root,qubes) %dir /var/lib/qubes
%attr(770,root,qubes) %dir /var/lib/qubes/vm-templates
%attr(770,root,qubes) %dir /var/lib/qubes/appvms
%attr(770,root,qubes) %dir /var/lib/qubes/backup
%attr(770,root,qubes) %dir /var/lib/qubes/dvmdata
%dir /usr/share/qubes/icons/*.png
/etc/yum.repos.d/qubes.repo
/usr/lib/qubes/qubes_setup_dnat_to_ns
/etc/dhclient.d/qubes_setup_dnat_to_ns.sh
/etc/NetworkManager/dispatcher.d/qubes_nmhook
/etc/sysconfig/iptables
/usr/lib64/pm-utils/sleep.d/01qubes-sync-vms-clock
/usr/lib64/pm-utils/sleep.d/02qubes-pause-vms
/usr/bin/xenstore-watch
/usr/bin/qvm-create-default-dvm
/usr/lib/qubes/qubes_restore
/usr/lib/qubes/qubes_prepare_saved_domain.sh
/etc/xen/scripts/block.qubes
%attr(4750,root,qubes) /usr/lib/qubes/xenfreepages
