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
Requires:	qubes-core-libs
Requires:       python-lxml
Conflicts:      qubes-gui-dom0 < 1.1.13
Requires:       xen >= 4.1.0-2
Requires:       xen-hvm
Requires:       createrepo
Requires:       gnome-packagekit
Requires:       cronie
%define _builddir %(pwd)

%description
The Qubes core files for installation on Dom0.

%prep
# we operate on the current directory, so no need to unpack anything
# symlink is to generate useful debuginfo packages
rm -f %{name}-%{version}
ln -sf . %{name}-%{version}
%setup -T -D

%build
python -m compileall dom0/qvm-core dom0/qmemman
python -O -m compileall dom0/qvm-core dom0/qmemman
for dir in dom0/restore dom0/qubes_rpc misc; do
  (cd $dir; make)
done
(cd vchan; make -f Makefile.linux)
(cd qrexec; make)

%install

cd dom0

mkdir -p $RPM_BUILD_ROOT/etc/init.d
cp init.d/qubes_core $RPM_BUILD_ROOT/etc/init.d/
cp init.d/qubes_netvm $RPM_BUILD_ROOT/etc/init.d/
cp init.d/qubes_setupdvm $RPM_BUILD_ROOT/etc/init.d/

mkdir -p $RPM_BUILD_ROOT/usr/bin/
cp qvm-tools/qvm-* $RPM_BUILD_ROOT/usr/bin
cp qvm-tools/qubes-* $RPM_BUILD_ROOT/usr/bin
cp clipboard_notifier/qclipd $RPM_BUILD_ROOT/usr/bin

mkdir -p $RPM_BUILD_ROOT/etc/xen/scripts
cp restore/block.qubes $RPM_BUILD_ROOT/etc/xen/scripts
cp ../network/vif-route-qubes $RPM_BUILD_ROOT/etc/xen/scripts
cp ../misc/block-snapshot $RPM_BUILD_ROOT/etc/xen/scripts
ln -s block-snapshot $RPM_BUILD_ROOT/etc/xen/scripts/block-origin

mkdir -p $RPM_BUILD_ROOT/etc/udev/rules.d
cp ../misc/qubes_block.rules $RPM_BUILD_ROOT/etc/udev/rules.d/99-qubes_block.rules
cp ../misc/qubes_usb.rules $RPM_BUILD_ROOT/etc/udev/rules.d/99-qubes_usb.rules

mkdir -p $RPM_BUILD_ROOT%{python_sitearch}/qubes
cp qvm-core/qubes.py $RPM_BUILD_ROOT%{python_sitearch}/qubes
cp qvm-core/qubes.py[co] $RPM_BUILD_ROOT%{python_sitearch}/qubes
cp qvm-core/qubesutils.py $RPM_BUILD_ROOT%{python_sitearch}/qubes
cp qvm-core/qubesutils.py[co] $RPM_BUILD_ROOT%{python_sitearch}/qubes
cp qvm-core/guihelpers.py $RPM_BUILD_ROOT%{python_sitearch}/qubes
cp qvm-core/guihelpers.py[co] $RPM_BUILD_ROOT%{python_sitearch}/qubes
cp qvm-core/__init__.py $RPM_BUILD_ROOT%{python_sitearch}/qubes
cp qvm-core/__init__.py[co] $RPM_BUILD_ROOT%{python_sitearch}/qubes
cp qmemman/qmemman*py $RPM_BUILD_ROOT%{python_sitearch}/qubes
cp qmemman/qmemman*py[co] $RPM_BUILD_ROOT%{python_sitearch}/qubes

mkdir -p $RPM_BUILD_ROOT%{_sysconfdir}/qubes
cp misc/qmemman.conf $RPM_BUILD_ROOT%{_sysconfdir}/qubes/

mkdir -p $RPM_BUILD_ROOT/usr/lib/qubes
cp aux-tools/unbind_pci_device.sh $RPM_BUILD_ROOT/usr/lib/qubes
cp aux-tools/unbind_all_network_devices $RPM_BUILD_ROOT/usr/lib/qubes
cp aux-tools/convert_apptemplate2vm.sh $RPM_BUILD_ROOT/usr/lib/qubes
cp aux-tools/convert_dirtemplate2vm.sh $RPM_BUILD_ROOT/usr/lib/qubes
cp aux-tools/create_apps_for_appvm.sh $RPM_BUILD_ROOT/usr/lib/qubes
cp aux-tools/remove_appvm_appmenus.sh $RPM_BUILD_ROOT/usr/lib/qubes
cp aux-tools/cleanup_dispvms $RPM_BUILD_ROOT/usr/lib/qubes
cp qmemman/server.py $RPM_BUILD_ROOT/usr/lib/qubes/qmemman_daemon.py
cp ../misc/meminfo-writer $RPM_BUILD_ROOT/usr/lib/qubes/
cp ../qrexec/qrexec_daemon $RPM_BUILD_ROOT/usr/lib/qubes/
cp ../qrexec/qrexec_client $RPM_BUILD_ROOT/usr/lib/qubes/
cp ../qrexec/qrexec_policy $RPM_BUILD_ROOT/usr/lib/qubes/
cp qubes_rpc/qfile-dom0-unpacker $RPM_BUILD_ROOT/usr/lib/qubes/
cp qubes_rpc/qubes-notify-updates $RPM_BUILD_ROOT/usr/lib/qubes/
cp qubes_rpc/qubes-receive-appmenus $RPM_BUILD_ROOT/usr/lib/qubes/
cp qubes_rpc/qubes-receive-updates $RPM_BUILD_ROOT/usr/lib/qubes/
cp ../misc/block_add_change $RPM_BUILD_ROOT/usr/lib/qubes/
cp ../misc/block_remove $RPM_BUILD_ROOT/usr/lib/qubes/
cp ../misc/block_cleanup $RPM_BUILD_ROOT/usr/lib/qubes/
cp ../misc/usb_add_change $RPM_BUILD_ROOT/usr/lib/qubes/
cp ../misc/usb_remove $RPM_BUILD_ROOT/usr/lib/qubes/
cp ../misc/vusb-ctl.py $RPM_BUILD_ROOT/usr/lib/qubes/
cp ../misc/xl-qvm-usb-attach.py $RPM_BUILD_ROOT/usr/lib/qubes/
cp ../misc/xl-qvm-usb-detach.py $RPM_BUILD_ROOT/usr/lib/qubes/
cp aux-tools/block_cleaner_daemon.py $RPM_BUILD_ROOT/usr/lib/qubes/
cp aux-tools/fix_dir_perms.sh $RPM_BUILD_ROOT/usr/lib/qubes/

mkdir -p $RPM_BUILD_ROOT/etc/qubes_rpc/policy
cp ../qubes_rpc/qubes.Filecopy.policy $RPM_BUILD_ROOT/etc/qubes_rpc/policy/qubes.Filecopy
cp ../qubes_rpc/qubes.OpenInVM.policy $RPM_BUILD_ROOT/etc/qubes_rpc/policy/qubes.OpenInVM
cp ../qubes_rpc/qubes.VMShell.policy $RPM_BUILD_ROOT/etc/qubes_rpc/policy/qubes.VMShell
cp qubes_rpc/qubes.SyncAppMenus.policy $RPM_BUILD_ROOT/etc/qubes_rpc/policy/qubes.SyncAppMenus
cp qubes_rpc/qubes.SyncAppMenus $RPM_BUILD_ROOT/etc/qubes_rpc/
cp ../qrexec/qubes_rpc_multiplexer $RPM_BUILD_ROOT/usr/lib/qubes
cp qubes_rpc/qubes.NotifyUpdates.policy $RPM_BUILD_ROOT/etc/qubes_rpc/policy/qubes.NotifyUpdates
cp qubes_rpc/qubes.NotifyUpdates $RPM_BUILD_ROOT/etc/qubes_rpc/
cp qubes_rpc/qubes.ReceiveUpdates.policy $RPM_BUILD_ROOT/etc/qubes_rpc/policy/qubes.ReceiveUpdates
cp qubes_rpc/qubes.ReceiveUpdates $RPM_BUILD_ROOT/etc/qubes_rpc/
install -D aux-tools/qubes-dom0.modules $RPM_BUILD_ROOT/etc/sysconfig/modules/qubes-dom0.modules
install -D aux-tools/cpufreq-xen.modules $RPM_BUILD_ROOT/etc/sysconfig/modules/cpufreq-xen.modules
install -D aux-tools/qubes-dom0-updates.cron $RPM_BUILD_ROOT/etc/cron.daily/qubes-dom0-updates.cron
install -D aux-tools/qubes-sync-clock.cron $RPM_BUILD_ROOT/etc/cron.d/qubes-sync-clock.cron

cp restore/qvm-create-default-dvm $RPM_BUILD_ROOT/usr/bin
cp restore/xenstore-watch $RPM_BUILD_ROOT/usr/bin/xenstore-watch-qubes
cp restore/qubes_restore $RPM_BUILD_ROOT/usr/lib/qubes
cp restore/qubes_prepare_saved_domain.sh  $RPM_BUILD_ROOT/usr/lib/qubes
cp restore/qubes_update_dispvm_savefile_with_progress.sh  $RPM_BUILD_ROOT/usr/lib/qubes
cp restore/qfile-daemon-dvm $RPM_BUILD_ROOT/usr/lib/qubes

mkdir -p $RPM_BUILD_ROOT/etc/yum.real.repos.d
cp qubes-cached.repo $RPM_BUILD_ROOT/etc/yum.real.repos.d/

mkdir -p $RPM_BUILD_ROOT/var/lib/qubes
mkdir -p $RPM_BUILD_ROOT/var/lib/qubes/vm-templates
mkdir -p $RPM_BUILD_ROOT/var/lib/qubes/appvms
mkdir -p $RPM_BUILD_ROOT/var/lib/qubes/servicevms
mkdir -p $RPM_BUILD_ROOT/var/lib/qubes/vm-kernels

mkdir -p $RPM_BUILD_ROOT/var/lib/qubes/backup
mkdir -p $RPM_BUILD_ROOT/var/lib/qubes/dvmdata

mkdir -p $RPM_BUILD_ROOT/var/lib/qubes/updates

mkdir -p $RPM_BUILD_ROOT/usr/share/qubes/icons
cp icons/*.png $RPM_BUILD_ROOT/usr/share/qubes/icons
cp misc/qubes-vm.directory.template $RPM_BUILD_ROOT/usr/share/qubes/
cp misc/qubes-templatevm.directory.template $RPM_BUILD_ROOT/usr/share/qubes/
cp misc/qubes-servicevm.directory.template $RPM_BUILD_ROOT/usr/share/qubes/
cp misc/qubes-dispvm.directory $RPM_BUILD_ROOT/usr/share/qubes/
cp misc/qubes-dispvm-firefox.desktop $RPM_BUILD_ROOT/usr/share/qubes/
cp misc/qubes-appmenu-select.desktop $RPM_BUILD_ROOT/usr/share/qubes/
cp misc/qubes-start.desktop $RPM_BUILD_ROOT/usr/share/qubes/
cp misc/vm-template.conf $RPM_BUILD_ROOT/usr/share/qubes/
cp misc/vm-template-hvm.conf $RPM_BUILD_ROOT/usr/share/qubes/
cp misc/Fedora-13-comps.xml $RPM_BUILD_ROOT/usr/share/qubes/

mkdir -p $RPM_BUILD_ROOT/usr/bin
cp ../network/qubes_setup_dnat_to_ns $RPM_BUILD_ROOT/usr/lib/qubes
cp ../network/qubes_fix_nm_conf.sh $RPM_BUILD_ROOT/usr/lib/qubes
mkdir -p $RPM_BUILD_ROOT/etc/dhclient.d
ln -s /usr/lib/qubes/qubes_setup_dnat_to_ns $RPM_BUILD_ROOT/etc/dhclient.d/qubes_setup_dnat_to_ns.sh 
mkdir -p $RPM_BUILD_ROOT/etc/NetworkManager/dispatcher.d/
cp ../network/qubes_nmhook $RPM_BUILD_ROOT/etc/NetworkManager/dispatcher.d/
mkdir -p $RPM_BUILD_ROOT/etc/sysconfig
cp ../network/iptables $RPM_BUILD_ROOT/etc/sysconfig
cp ../network/ip6tables $RPM_BUILD_ROOT/etc/sysconfig
mkdir -p $RPM_BUILD_ROOT/etc/security/limits.d
cp misc/limits-qubes.conf $RPM_BUILD_ROOT/etc/security/limits.d/99-qubes.conf

mkdir -p $RPM_BUILD_ROOT/usr/lib64/pm-utils/sleep.d
cp pm-utils/01qubes-sync-vms-clock $RPM_BUILD_ROOT/usr/lib64/pm-utils/sleep.d/
cp pm-utils/51qubes-suspend-netvm $RPM_BUILD_ROOT/usr/lib64/pm-utils/sleep.d/
cp pm-utils/52qubes-pause-vms $RPM_BUILD_ROOT/usr/lib64/pm-utils/sleep.d/

mkdir -p $RPM_BUILD_ROOT/var/log/qubes
mkdir -p $RPM_BUILD_ROOT/var/run/qubes

install -d $RPM_BUILD_ROOT/etc/sudoers.d
install -m 0440 qubes.sudoers $RPM_BUILD_ROOT/etc/sudoers.d/qubes

install -d $RPM_BUILD_ROOT/etc/xdg/autostart
install -m 0644 qubes-guid.desktop $RPM_BUILD_ROOT/etc/xdg/autostart/

mkdir -p $RPM_BUILD_ROOT/etc/dracut.conf.d
cp dracut/dracut.conf.d/* $RPM_BUILD_ROOT/etc/dracut.conf.d/

mkdir -p $RPM_BUILD_ROOT/usr/share/dracut/modules.d
cp -r dracut/modules.d/* $RPM_BUILD_ROOT/usr/share/dracut/modules.d/

%post

# Create NetworkManager configuration if we do not have it
if ! [ -e /etc/NetworkManager/NetworkManager.conf ]; then
echo '[main]' > /etc/NetworkManager/NetworkManager.conf
echo 'plugins = keyfile' >> /etc/NetworkManager/NetworkManager.conf
echo '[keyfile]' >> /etc/NetworkManager/NetworkManager.conf
fi
/usr/lib/qubes/qubes_fix_nm_conf.sh

sed 's/^net.ipv4.ip_forward.*/net.ipv4.ip_forward = 1/'  -i /etc/sysctl.conf

sed '/^autoballoon=/d;/^lockfile=/d' -i /etc/xen/xl.conf
echo 'autoballoon=0' >> /etc/xen/xl.conf
echo 'lockfile="/var/run/qubes/xl-lock"' >> /etc/xen/xl.conf

sed '/^reposdir\s*=/d' -i /etc/yum.conf
echo reposdir=/etc/yum.real.repos.d >> /etc/yum.conf

sed '/^installonlypkgs\s*=/d' -i /etc/yum.conf
echo 'installonlypkgs = kernel, kernel-qubes-vm' >> /etc/yum.conf

sed 's/^PRELINKING\s*=.*/PRELINKING=no/' -i /etc/sysconfig/prelink

sed '/^\s*XENCONSOLED_LOG_\(HYPERVISOR\|GUESTS\)\s*=.*/d' -i /etc/sysconfig/xenconsoled
echo XENCONSOLED_LOG_HYPERVISOR=yes >> /etc/sysconfig/xenconsoled
echo XENCONSOLED_LOG_GUESTS=yes >> /etc/sysconfig/xenconsoled

chkconfig --add qubes_core || echo "WARNING: Cannot add service qubes_core!"
chkconfig --add qubes_netvm || echo "WARNING: Cannot add service qubes_netvm!"
chkconfig --add qubes_setupdvm || echo "WARNING: Cannot add service qubes_setupdvm!"

chkconfig --level 5 qubes_core on || echo "WARNING: Cannot enable service qubes_core!"
chkconfig --level 5 qubes_netvm on || echo "WARNING: Cannot enable service qubes_netvm!"
chkconfig --level 5 qubes_setupdvm on || echo "WARNING: Cannot enable service qubes_setupdvm!"

# Conflicts with libxl stack, so disable it
service xend stop
chkconfig --level 5 xend off

HAD_SYSCONFIG_NETWORK=yes
if ! [ -e /etc/sysconfig/network ]; then
    HAD_SYSCONFIG_NETWORK=no
    # supplant empty one so NetworkManager init script does not complain
    touch /etc/sysconfig/network
fi

# Load evtchn module - xenstored needs it
modprobe evtchn 2> /dev/null || modprobe xen-evtchn
service xenstored start

if ! [ -e /var/lib/qubes/qubes.xml ]; then
#    echo "Initializing Qubes DB..."
    umask 007; sg qubes -c qvm-init-storage
fi
for i in /usr/share/qubes/icons/*.png ; do
	xdg-icon-resource install --novendor --size 48 $i
done

xdg-desktop-menu install /usr/share/qubes/qubes-dispvm.directory /usr/share/qubes/qubes-dispvm-firefox.desktop

# Because we now have an installer
# this script is always executed during upgrade
# and we decided not to restart core during upgrade
#service qubes_core start

if [ "x"$HAD_SYSCONFIG_NETWORK = "xno" ]; then
    rm -f /etc/sysconfig/network
fi

# Remove unnecessary udev rules that causes problems in dom0 (#605)
mkdir -p /var/lib/qubes/removed-udev-scripts
mv -f /lib/udev/rules.d/69-xorg-vmmouse.rules /var/lib/qubes/removed-udev-scripts/ 2> /dev/null || :

%clean
rm -rf $RPM_BUILD_ROOT
rm -f %{name}-%{version}

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

%triggerin -- xen-runtime
sed -i 's/\/block /\/block.qubes /' /etc/udev/rules.d/xen-backend.rules
/usr/lib/qubes/fix_dir_perms.sh

%triggerin -- xorg-x11-drv-vmmouse
mv -f /lib/udev/rules.d/69-xorg-vmmouse.rules /var/lib/qubes/removed-udev-scripts/ 2> /dev/null || :

%preun
if [ "$1" = 0 ] ; then
	# no more packages left
    /etc/init.d/qubes_netvm stop
    /etc/init.d/qubes_core stop

	for i in /usr/share/qubes/icons/*.png ; do
		xdg-icon-resource uninstall --novendor --size 48 $i
	done

    xdg-desktop-menu uninstall /usr/share/qubes/qubes-dispvm.directory /usr/share/qubes/qubes-dispvm-firefox.desktop
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
%config(noreplace) %attr(0664,root,qubes) %{_sysconfdir}/qubes/qmemman.conf
/usr/bin/qvm-*
/usr/bin/qubes-*
/usr/bin/qclipd
%{python_sitearch}/qubes/qubes.py
%{python_sitearch}/qubes/qubes.pyc
%{python_sitearch}/qubes/qubes.pyo
%{python_sitearch}/qubes/qubesutils.py
%{python_sitearch}/qubes/qubesutils.pyc
%{python_sitearch}/qubes/qubesutils.pyo
%{python_sitearch}/qubes/guihelpers.py
%{python_sitearch}/qubes/guihelpers.pyc
%{python_sitearch}/qubes/guihelpers.pyo
%{python_sitearch}/qubes/__init__.py
%{python_sitearch}/qubes/__init__.pyc
%{python_sitearch}/qubes/__init__.pyo
%{python_sitearch}/qubes/qmemman*.py*
/usr/lib/qubes/unbind_pci_device.sh
/usr/lib/qubes/unbind_all_network_devices
/usr/lib/qubes/cleanup_dispvms
/usr/lib/qubes/convert_apptemplate2vm.sh
/usr/lib/qubes/convert_dirtemplate2vm.sh
/usr/lib/qubes/create_apps_for_appvm.sh
/usr/lib/qubes/remove_appvm_appmenus.sh
/usr/lib/qubes/qmemman_daemon.py*
/usr/lib/qubes/meminfo-writer
/usr/lib/qubes/qfile-daemon-dvm*
/usr/lib/qubes/qubes-notify-updates
/usr/lib/qubes/qubes-receive-appmenus
/usr/lib/qubes/qubes-receive-updates
/usr/lib/qubes/block_add_change
/usr/lib/qubes/block_remove
/usr/lib/qubes/block_cleanup
/usr/lib/qubes/block_cleaner_daemon.py*
/usr/lib/qubes/usb_add_change
/usr/lib/qubes/usb_remove
/usr/lib/qubes/vusb-ctl.py*
/usr/lib/qubes/xl-qvm-usb-attach.py*
/usr/lib/qubes/xl-qvm-usb-detach.py*
/usr/lib/qubes/fix_dir_perms.sh
%attr(4750,root,qubes) /usr/lib/qubes/qfile-dom0-unpacker
%attr(0770,root,qubes) %dir /var/lib/qubes
%attr(0770,root,qubes) %dir /var/lib/qubes/vm-templates
%attr(0770,root,qubes) %dir /var/lib/qubes/appvms
%attr(0770,root,qubes) %dir /var/lib/qubes/servicevms
%attr(0770,root,qubes) %dir /var/lib/qubes/backup
%attr(0770,root,qubes) %dir /var/lib/qubes/dvmdata
%attr(0770,root,qubes) %dir /var/lib/qubes/updates
%attr(0770,root,qubes) %dir /var/lib/qubes/vm-kernels
/usr/share/qubes/icons/*.png
/usr/share/qubes/qubes-vm.directory.template
/usr/share/qubes/qubes-templatevm.directory.template
/usr/share/qubes/qubes-servicevm.directory.template
/usr/share/qubes/qubes-dispvm.directory
/usr/share/qubes/qubes-dispvm-firefox.desktop
/usr/share/qubes/qubes-appmenu-select.desktop
/usr/share/qubes/qubes-start.desktop
/usr/share/qubes/vm-template.conf
/usr/share/qubes/vm-template-hvm.conf
/usr/share/qubes/Fedora-13-comps.xml
/usr/lib/qubes/qubes_setup_dnat_to_ns
/usr/lib/qubes/qubes_fix_nm_conf.sh
/etc/dhclient.d/qubes_setup_dnat_to_ns.sh
/etc/NetworkManager/dispatcher.d/qubes_nmhook
/etc/sysconfig/iptables
/etc/sysconfig/ip6tables
/etc/sysconfig/modules/qubes-dom0.modules
/etc/sysconfig/modules/cpufreq-xen.modules
/usr/lib64/pm-utils/sleep.d/01qubes-sync-vms-clock
/usr/lib64/pm-utils/sleep.d/51qubes-suspend-netvm
/usr/lib64/pm-utils/sleep.d/52qubes-pause-vms
/usr/bin/xenstore-watch-qubes
/usr/lib/qubes/qubes_restore
/usr/lib/qubes/qubes_prepare_saved_domain.sh
/usr/lib/qubes/qubes_update_dispvm_savefile_with_progress.sh
/etc/xen/scripts/block.qubes
/etc/xen/scripts/block-snapshot
/etc/xen/scripts/block-origin
/etc/xen/scripts/vif-route-qubes
/usr/lib/qubes/qrexec_client
/usr/lib/qubes/qubes_rpc_multiplexer
/usr/lib/qubes/qrexec_policy
%dir /etc/qubes_rpc/policy
%attr(0664,root,qubes) %config(noreplace) /etc/qubes_rpc/policy/qubes.Filecopy
%attr(0664,root,qubes) %config(noreplace) /etc/qubes_rpc/policy/qubes.OpenInVM
%attr(0664,root,qubes) %config(noreplace) /etc/qubes_rpc/policy/qubes.SyncAppMenus
%attr(0664,root,qubes) %config(noreplace) /etc/qubes_rpc/policy/qubes.NotifyUpdates
%attr(0664,root,qubes) %config(noreplace) /etc/qubes_rpc/policy/qubes.ReceiveUpdates
%attr(0664,root,qubes) %config(noreplace) /etc/qubes_rpc/policy/qubes.VMShell
/etc/qubes_rpc/qubes.SyncAppMenus
/etc/qubes_rpc/qubes.NotifyUpdates
/etc/qubes_rpc/qubes.ReceiveUpdates
%attr(4750,root,qubes) /usr/lib/qubes/qrexec_daemon
%attr(2770,root,qubes) %dir /var/log/qubes
%attr(0770,root,qubes) %dir /var/run/qubes
/etc/yum.real.repos.d/qubes-cached.repo
/etc/sudoers.d/qubes
/etc/xdg/autostart/qubes-guid.desktop
/etc/security/limits.d/99-qubes.conf
/etc/udev/rules.d/99-qubes_block.rules
/etc/udev/rules.d/99-qubes_usb.rules
%attr(0644,root,root) /etc/cron.daily/qubes-dom0-updates.cron
%attr(0644,root,root) /etc/cron.d/qubes-sync-clock.cron
/etc/dracut.conf.d/*
%dir /usr/share/dracut/modules.d/90qubes-pciback
/usr/share/dracut/modules.d/90qubes-pciback/*
