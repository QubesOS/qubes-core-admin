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
Release:	1%{dist}
Summary:	The Qubes core files (Dom0-side)

Group:		Qubes
Vendor:		Invisible Things Lab
License:	GPL
URL:		http://www.qubes-os.org
BuildRequires:  xen-devel
Requires:	python, xen-runtime, pciutils, python-inotify, python-daemon, kernel-qubes-dom0
Conflicts:      qubes-gui-dom0 < 1.1.13
Requires:       NetworkManager >= 0.8.1-1
Requires:       xen >= 3.4.3-6
%define _builddir %(pwd)/dom0

%description
The Qubes core files for installation on Dom0.

%build
python -m compileall qvm-core qmemman
python -O -m compileall qvm-core qmemman
make -C restore
make -C ../common
make -C ../vchan
make -C ../u2mfn
make -C ../qrexec

%install

mkdir -p $RPM_BUILD_ROOT/etc/init.d
cp init.d/qubes_core $RPM_BUILD_ROOT/etc/init.d/
cp init.d/qubes_netvm $RPM_BUILD_ROOT/etc/init.d/

mkdir -p $RPM_BUILD_ROOT/usr/bin/
cp qvm-tools/qvm-* $RPM_BUILD_ROOT/usr/bin
cp clipboard_notifier/qclipd $RPM_BUILD_ROOT/usr/bin

mkdir -p $RPM_BUILD_ROOT/etc/xen/scripts
cp restore/block.qubes $RPM_BUILD_ROOT/etc/xen/scripts
cp ../common/vif-route-qubes $RPM_BUILD_ROOT/etc/xen/scripts
cp ../common/block-snapshot $RPM_BUILD_ROOT/etc/xen/scripts
ln -s block-snapshot $RPM_BUILD_ROOT/etc/xen/scripts/block-origin

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
cp qmemman/server.py $RPM_BUILD_ROOT/usr/lib/qubes/qmemman_daemon.py
cp ../common/meminfo-writer $RPM_BUILD_ROOT/usr/lib/qubes/
cp ../qrexec/qrexec_daemon $RPM_BUILD_ROOT/usr/lib/qubes/
cp ../qrexec/qrexec_client $RPM_BUILD_ROOT/usr/lib/qubes/

cp restore/xenstore-watch restore/qvm-create-default-dvm $RPM_BUILD_ROOT/usr/bin
cp restore/qubes_restore restore/xenfreepages $RPM_BUILD_ROOT/usr/lib/qubes
cp restore/qubes_prepare_saved_domain.sh  $RPM_BUILD_ROOT/usr/lib/qubes
cp restore/qfile-daemon-dvm $RPM_BUILD_ROOT/usr/lib/qubes
cp restore/qfile-daemon $RPM_BUILD_ROOT/usr/lib/qubes

mkdir -p $RPM_BUILD_ROOT/var/lib/qubes
mkdir -p $RPM_BUILD_ROOT/var/lib/qubes/vm-templates
mkdir -p $RPM_BUILD_ROOT/var/lib/qubes/appvms
mkdir -p $RPM_BUILD_ROOT/var/lib/qubes/servicevms

mkdir -p $RPM_BUILD_ROOT/var/lib/qubes/backup
mkdir -p $RPM_BUILD_ROOT/var/lib/qubes/dvmdata

mkdir -p $RPM_BUILD_ROOT/usr/share/qubes/icons
cp icons/*.png $RPM_BUILD_ROOT/usr/share/qubes/icons

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
cp pm-utils/01qubes-suspend-netvm $RPM_BUILD_ROOT/usr/lib64/pm-utils/sleep.d/
cp pm-utils/02qubes-pause-vms $RPM_BUILD_ROOT/usr/lib64/pm-utils/sleep.d/

# Optional scripts for Vaio (they go into separate package)
cp vaio_fixes/00sony-vaio-audio $RPM_BUILD_ROOT/usr/lib64/pm-utils/sleep.d/
cp vaio_fixes/99sony-vaio-audio $RPM_BUILD_ROOT/usr/lib64/pm-utils/sleep.d/
cp vaio_fixes/01sony-vaio-display $RPM_BUILD_ROOT/usr/lib64/pm-utils/sleep.d/

mkdir -p $RPM_BUILD_ROOT/var/log/qubes
mkdir -p $RPM_BUILD_ROOT/var/run/qubes

install -D ../vchan/libvchan.so $RPM_BUILD_ROOT/%{_libdir}/libvchan.so
install -D ../u2mfn/libu2mfn.so $RPM_BUILD_ROOT/%{_libdir}/libu2mfn.so

install -d $RPM_BUILD_ROOT/etc/sudoers.d
install -m 0440 qubes.sudoers $RPM_BUILD_ROOT/etc/sudoers.d/qubes

install -d $RPM_BUILD_ROOT/etc/xdg/autostart
install -m 0644 qubes-guid.desktop $RPM_BUILD_ROOT/etc/xdg/autostart/

%post

# Create NetworkManager configuration if we do not have it
if ! [ -e /etc/NetworkManager/NetworkManager.conf ]; then
echo '[main]' > /etc/NetworkManager/NetworkManager.conf
echo 'plugins = keyfile' >> /etc/NetworkManager/NetworkManager.conf
echo '[keyfile]' >> /etc/NetworkManager/NetworkManager.conf
fi
/usr/lib/qubes/qubes_fix_nm_conf.sh

sed 's/^net.ipv4.ip_forward.*/net.ipv4.ip_forward = 1/'  -i /etc/sysctl.conf

chkconfig --add qubes_core || echo "WARNING: Cannot add service qubes_core!"
chkconfig --add qubes_netvm || echo "WARNING: Cannot add service qubes_netvm!"

chkconfig qubes_core on || echo "WARNING: Cannot enable service qubes_core!"
chkconfig qubes_netvm on || echo "WARNING: Cannot enable service qubes_netvm!"

HAD_SYSCONFIG_NETWORK=yes
if ! [ -e /etc/sysconfig/network ]; then
    HAD_SYSCONFIG_NETWORK=no
    # supplant empty one so NetworkManager init script does not complain
    touch /etc/sysconfig/network
fi

# Load evtchn module - xenstored needs it
modprobe evtchn

# Now launch xend - we will need it for subsequent steps
service xenstored start
service xend start

if ! [ -e /var/lib/qubes/qubes.xml ]; then
#    echo "Initializing Qubes DB..."
    umask 007; sg qubes -c qvm-init-storage
fi
for i in /usr/share/qubes/icons/*.png ; do
	xdg-icon-resource install --novendor --size 48 $i
done

# Because we now have an installer
# this script is always executed during upgrade
# and we decided not to restart core during upgrade
#service qubes_core start


if [ "x"$HAD_SYSCONFIG_NETWORK = "xno" ]; then
    rm -f /etc/sysconfig/network
fi

%clean
rm -rf $RPM_BUILD_ROOT

%pre
if ! grep -q ^qubes: /etc/group ; then
		groupadd qubes
fi

#if [ "$1" -gt 1 ] ; then
    # upgrading already installed package...

# Do not restart core during upgrade
# most upgrades only modifies qvm-* tools
# and it makes no sense to force all VMs shutdown
#    /etc/init.d/qubes_core stop
#fi

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
/usr/bin/qvm-*
/usr/bin/qclipd
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
/usr/lib/qubes/qmemman_daemon.py*
/usr/lib/qubes/meminfo-writer
/usr/lib/qubes/qfile-daemon-dvm*
/usr/lib/qubes/qfile-daemon
%attr(770,root,qubes) %dir /var/lib/qubes
%attr(770,root,qubes) %dir /var/lib/qubes/vm-templates
%attr(770,root,qubes) %dir /var/lib/qubes/appvms
%attr(770,root,qubes) %dir /var/lib/qubes/servicevms
%attr(770,root,qubes) %dir /var/lib/qubes/backup
%attr(770,root,qubes) %dir /var/lib/qubes/dvmdata
%dir /usr/share/qubes/icons/*.png
/usr/lib/qubes/qubes_setup_dnat_to_ns
/usr/lib/qubes/qubes_fix_nm_conf.sh
/etc/dhclient.d/qubes_setup_dnat_to_ns.sh
/etc/NetworkManager/dispatcher.d/qubes_nmhook
/etc/sysconfig/iptables
/usr/lib64/pm-utils/sleep.d/01qubes-sync-vms-clock
/usr/lib64/pm-utils/sleep.d/01qubes-suspend-netvm
/usr/lib64/pm-utils/sleep.d/02qubes-pause-vms
/usr/bin/xenstore-watch
/usr/lib/qubes/qubes_restore
/usr/lib/qubes/qubes_prepare_saved_domain.sh
/etc/xen/scripts/block.qubes
/etc/xen/scripts/block-snapshot
/etc/xen/scripts/block-origin
/etc/xen/scripts/vif-route-qubes
/usr/lib/qubes/qrexec_client
%attr(4750,root,qubes) /usr/lib/qubes/qrexec_daemon
%attr(4750,root,qubes) /usr/lib/qubes/xenfreepages
%attr(2770,root,qubes) %dir /var/log/qubes
%attr(770,root,qubes) %dir /var/run/qubes
%{_libdir}/libvchan.so
%{_libdir}/libu2mfn.so
/etc/sudoers.d/qubes
/etc/xdg/autostart/qubes-guid.desktop

%package vaio-fixes
Summary: Additional scripts for supporting suspend on Vaio Z laptops
Requires: alsa-utils

%description vaio-fixes
Additional scripts for supporting suspend on Vaio Z laptops.

Due to broken Linux GPU drivers we need to do some additional actions during
suspend/resume.

%files vaio-fixes
/usr/lib64/pm-utils/sleep.d/00sony-vaio-audio
/usr/lib64/pm-utils/sleep.d/99sony-vaio-audio
/usr/lib64/pm-utils/sleep.d/01sony-vaio-display
