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
Conflicts:   qubes-gui-dom0 < 1.1.13
Requires:       NetworkManager >= 0.8.1-1
%define _builddir %(pwd)/dom0

%description
The Qubes core files for installation on Dom0.

%build
python -m compileall qvm-core qmemman
python -O -m compileall qvm-core qmemman
make -C restore
make -C ../common
make -C ../qrexec

%install

mkdir -p $RPM_BUILD_ROOT/etc/init.d
cp init.d/qubes_core $RPM_BUILD_ROOT/etc/init.d/
cp init.d/qubes_netvm $RPM_BUILD_ROOT/etc/init.d/
cp init.d/qubes_setupdvm $RPM_BUILD_ROOT/etc/init.d/

mkdir -p $RPM_BUILD_ROOT/usr/bin/
cp qvm-tools/qvm-* $RPM_BUILD_ROOT/usr/bin
cp clipboard_notifier/qclipd $RPM_BUILD_ROOT/usr/bin
cp pendrive_swapper/qfilexchgd $RPM_BUILD_ROOT/usr/bin

mkdir -p $RPM_BUILD_ROOT/etc/xen/scripts
cp restore/block.qubes $RPM_BUILD_ROOT/etc/xen/scripts
cp ../common/vif-route-qubes $RPM_BUILD_ROOT/etc/xen/scripts

mkdir -p $RPM_BUILD_ROOT%{python_sitearch}/qubes
cp qvm-core/qubes.py $RPM_BUILD_ROOT%{python_sitearch}/qubes
cp qvm-core/qubes.py[co] $RPM_BUILD_ROOT%{python_sitearch}/qubes
cp qvm-core/__init__.py $RPM_BUILD_ROOT%{python_sitearch}/qubes
cp qvm-core/__init__.py[co] $RPM_BUILD_ROOT%{python_sitearch}/qubes
cp qmemman/qmemman*py $RPM_BUILD_ROOT%{python_sitearch}/qubes
cp qmemman/qmemman*py[co] $RPM_BUILD_ROOT%{python_sitearch}/qubes

mkdir -p $RPM_BUILD_ROOT/usr/lib/qubes
cp aux-tools/patch_appvm_initramfs.sh $RPM_BUILD_ROOT/usr/lib/qubes
cp aux-tools/unbind_pci_device.sh $RPM_BUILD_ROOT/usr/lib/qubes
cp aux-tools/unbind_all_network_devices $RPM_BUILD_ROOT/usr/lib/qubes
cp aux-tools/convert_apptemplate2vm.sh $RPM_BUILD_ROOT/usr/lib/qubes
cp aux-tools/convert_dirtemplate2vm.sh $RPM_BUILD_ROOT/usr/lib/qubes
cp aux-tools/create_apps_for_appvm.sh $RPM_BUILD_ROOT/usr/lib/qubes
cp aux-tools/remove_appvm_appmenus.sh $RPM_BUILD_ROOT/usr/lib/qubes
cp aux-tools/reset_vm_configs.py  $RPM_BUILD_ROOT/usr/lib/qubes
cp pendrive_swapper/qubes_pencmd $RPM_BUILD_ROOT/usr/lib/qubes
cp qmemman/server.py $RPM_BUILD_ROOT/usr/lib/qubes/qmemman_daemon.py
cp ../common/meminfo-writer $RPM_BUILD_ROOT/usr/lib/qubes/
cp ../qrexec/qrexec_daemon $RPM_BUILD_ROOT/usr/lib/qubes/
cp ../qrexec/qrexec_client $RPM_BUILD_ROOT/usr/lib/qubes/

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
cp ../common/qubes_fix_nm_conf.sh $RPM_BUILD_ROOT/usr/lib/qubes
mkdir -p $RPM_BUILD_ROOT/etc/dhclient.d
ln -s /usr/lib/qubes/qubes_setup_dnat_to_ns $RPM_BUILD_ROOT/etc/dhclient.d/qubes_setup_dnat_to_ns.sh 
mkdir -p $RPM_BUILD_ROOT/etc/NetworkManager/dispatcher.d/
cp ../common/qubes_nmhook $RPM_BUILD_ROOT/etc/NetworkManager/dispatcher.d/
mkdir -p $RPM_BUILD_ROOT/etc/sysconfig
cp ../common/iptables $RPM_BUILD_ROOT/etc/sysconfig

mkdir -p $RPM_BUILD_ROOT/usr/lib64/pm-utils/sleep.d
cp pm-utils/01qubes-sync-vms-clock $RPM_BUILD_ROOT/usr/lib64/pm-utils/sleep.d/
cp pm-utils/01qubes-swap-pci-devs $RPM_BUILD_ROOT/usr/lib64/pm-utils/sleep.d/
cp pm-utils/02qubes-pause-vms $RPM_BUILD_ROOT/usr/lib64/pm-utils/sleep.d/

mkdir -p $RPM_BUILD_ROOT/var/log/qubes
mkdir -p $RPM_BUILD_ROOT/var/run/qubes

%post

/usr/lib/qubes/qubes_fix_nm_conf.sh

if [ -e /etc/yum.repos.d/qubes-r1-dom0.repo ]; then
# we want the user to use the repo that comes with qubes-code-dom0 packages instead
rm -f /etc/yum.repos.d/qubes-r1-dom0.repo
fi

#if [ "$1" !=  1 ] ; then
## do this whole %post thing only when updating for the first time...
#exit 0
#fi

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
chkconfig --add qubes_setupdvm || echo "WARNING: Cannot add service qubes_setupdvm!"

chkconfig qubes_core on || echo "WARNING: Cannot enable service qubes_core!"
chkconfig qubes_netvm on || echo "WARNING: Cannot enable service qubes_netvm!"
chkconfig qubes_setupdvm on || echo "WARNING: Cannot enable service qubes_setupdvm!"

if ! [ -e /var/lib/qubes/qubes.xml ]; then
#    echo "Initializing Qubes DB..."
    umask 007; sg qubes -c qvm-init-storage
fi
for i in /usr/share/qubes/icons/*.png ; do
	xdg-icon-resource install --novendor --size 48 $i
done

/etc/init.d/qubes_core start

NETVM=$(qvm-get-default-netvm)
if [ "X"$NETVM = "X""dom0" ] ; then
    /etc/init.d/qubes_netvm start
fi


%clean
rm -rf $RPM_BUILD_ROOT

%pre
if ! grep -q ^qubes: /etc/group ; then
		groupadd qubes
fi

if [ "$1" -gt 1 ] ; then
    # upgrading already installed package...
    NETVM=$(qvm-get-default-netvm)
    if [ "X"$NETVM = "X""dom0" ] ; then
        /etc/init.d/qubes_netvm stop
    fi

    /etc/init.d/qubes_core stop
fi

%triggerin -- xen
/etc/init.d/qubes_core stop
/etc/init.d/qubes_core start

%triggerin -- xen-runtime
sed -i 's/\/block /\/block.qubes /' /etc/udev/rules.d/xen-backend.rules
/etc/init.d/qubes_core stop
/etc/init.d/qubes_core start


%preun
if [ "$1" = 0 ] ; then
	# no more packages left
    /etc/init.d/qubes_netvm stop
    /etc/init.d/qubes_core stop

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
/etc/init.d/qubes_setupdvm
/usr/bin/qvm-*
/usr/bin/qclipd
/usr/bin/qfilexchgd
%{python_sitearch}/qubes/qubes.py
%{python_sitearch}/qubes/qubes.pyc
%{python_sitearch}/qubes/qubes.pyo
%{python_sitearch}/qubes/__init__.py
%{python_sitearch}/qubes/__init__.pyc
%{python_sitearch}/qubes/__init__.pyo
%{python_sitearch}/qubes/qmemman*.py*
/usr/lib/qubes/patch_appvm_initramfs.sh
/usr/lib/qubes/unbind_pci_device.sh
/usr/lib/qubes/unbind_all_network_devices
/usr/lib/qubes/convert_apptemplate2vm.sh
/usr/lib/qubes/convert_dirtemplate2vm.sh
/usr/lib/qubes/create_apps_for_appvm.sh
/usr/lib/qubes/remove_appvm_appmenus.sh
/usr/lib/qubes/reset_vm_configs.py*
/usr/lib/qubes/qubes_pencmd
/usr/lib/qubes/qmemman_daemon.py*
/usr/lib/qubes/meminfo-writer
%attr(770,root,qubes) %dir /var/lib/qubes
%attr(770,root,qubes) %dir /var/lib/qubes/vm-templates
%attr(770,root,qubes) %dir /var/lib/qubes/appvms
%attr(770,root,qubes) %dir /var/lib/qubes/backup
%attr(770,root,qubes) %dir /var/lib/qubes/dvmdata
%dir /usr/share/qubes/icons/*.png
/etc/yum.repos.d/qubes.repo
/usr/lib/qubes/qubes_setup_dnat_to_ns
/usr/lib/qubes/qubes_fix_nm_conf.sh
/etc/dhclient.d/qubes_setup_dnat_to_ns.sh
/etc/NetworkManager/dispatcher.d/qubes_nmhook
/etc/sysconfig/iptables
/usr/lib64/pm-utils/sleep.d/01qubes-sync-vms-clock
/usr/lib64/pm-utils/sleep.d/01qubes-swap-pci-devs
/usr/lib64/pm-utils/sleep.d/02qubes-pause-vms
/usr/bin/xenstore-watch
/usr/bin/qvm-create-default-dvm
/usr/lib/qubes/qubes_restore
/usr/lib/qubes/qubes_prepare_saved_domain.sh
/etc/xen/scripts/block.qubes
/etc/xen/scripts/vif-route-qubes
/usr/lib/qubes/qrexec_client
%attr(4750,root,qubes) /usr/lib/qubes/qrexec_daemon
%attr(4750,root,qubes) /usr/lib/qubes/xenfreepages
%attr(2770,root,qubes) %dir /var/log/qubes
%attr(770,root,qubes) %dir /var/run/qubes
