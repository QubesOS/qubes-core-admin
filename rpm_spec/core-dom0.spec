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

%{!?version: %define version %(cat version)}

%define _dracutmoddir	/usr/lib/dracut/modules.d
%if %{fedora} < 17
%define _dracutmoddir   /usr/share/dracut/modules.d
%endif

Name:		qubes-core-dom0
Version:	%{version}
Release:	1%{dist}
Summary:	The Qubes core files (Dom0-side)

Group:		Qubes
Vendor:		Invisible Things Lab
License:	GPL
URL:		http://www.qubes-os.org
BuildRequires:  xen-devel
BuildRequires:  ImageMagick
BuildRequires:	systemd-units
Requires(post): systemd-units
Requires(preun): systemd-units
Requires(postun): systemd-units
Requires:	python, xen-runtime, pciutils, python-inotify, python-daemon
Requires:       qubes-core-dom0-linux >= 2.0.24
Requires:       python-lxml
Requires:       python-psutil
# TODO: R: qubes-gui-dom0 >= 2.1.11
Conflicts:      qubes-gui-dom0 < 1.1.13
Requires:       xen >= 4.1.0-2
Requires:       xen-hvm
Requires:       createrepo
Requires:       gnome-packagekit
Requires:       cronie
# for qubes-hcl-report
Requires:       dmidecode

# Prevent preupgrade from installation (it pretend to provide distribution upgrade)
Obsoletes:	preupgrade < 2.0
Provides:	preupgrade = 2.0
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
python -m compileall core core-modules qmemman tests
python -O -m compileall core dom/core-modules qmemman tests
for dir in dispvm qmemman; do
  (cd $dir; make)
done

%install

mkdir -p $RPM_BUILD_ROOT/usr/lib/systemd/system
cp linux/systemd/qubes-block-cleaner.service $RPM_BUILD_ROOT%{_unitdir}
cp linux/systemd/qubes-core.service $RPM_BUILD_ROOT%{_unitdir}
cp linux/systemd/qubes-setupdvm.service $RPM_BUILD_ROOT%{_unitdir}
cp linux/systemd/qubes-netvm.service $RPM_BUILD_ROOT%{_unitdir}
cp linux/systemd/qubes-qmemman.service $RPM_BUILD_ROOT%{_unitdir}
cp linux/systemd/qubes-vm@.service $RPM_BUILD_ROOT%{_unitdir}
cp linux/systemd/qubes-reload-firewall@.service $RPM_BUILD_ROOT%{_unitdir}
cp linux/systemd/qubes-reload-firewall@.timer $RPM_BUILD_ROOT%{_unitdir}

mkdir -p $RPM_BUILD_ROOT/usr/bin/
cp qvm-tools/qvm-* $RPM_BUILD_ROOT/usr/bin
cp qvm-tools/qubes-* $RPM_BUILD_ROOT/usr/bin

mkdir -p $RPM_BUILD_ROOT/etc/xen/scripts
cp dispvm/block.qubes $RPM_BUILD_ROOT/etc/xen/scripts
cp linux/system-config/vif-route-qubes $RPM_BUILD_ROOT/etc/xen/scripts
cp linux/system-config/block-snapshot $RPM_BUILD_ROOT/etc/xen/scripts
ln -s block-snapshot $RPM_BUILD_ROOT/etc/xen/scripts/block-origin

mkdir -p $RPM_BUILD_ROOT%{python_sitearch}/qubes
cp core/qubes.py $RPM_BUILD_ROOT%{python_sitearch}/qubes
cp core/qubes.py[co] $RPM_BUILD_ROOT%{python_sitearch}/qubes
cp core/qubesutils.py $RPM_BUILD_ROOT%{python_sitearch}/qubes
cp core/qubesutils.py[co] $RPM_BUILD_ROOT%{python_sitearch}/qubes
cp core/guihelpers.py $RPM_BUILD_ROOT%{python_sitearch}/qubes
cp core/guihelpers.py[co] $RPM_BUILD_ROOT%{python_sitearch}/qubes
cp core/notify.py $RPM_BUILD_ROOT%{python_sitearch}/qubes
cp core/notify.py[co] $RPM_BUILD_ROOT%{python_sitearch}/qubes
cp core/backup.py $RPM_BUILD_ROOT%{python_sitearch}/qubes
cp core/backup.py[co] $RPM_BUILD_ROOT%{python_sitearch}/qubes
cp qmemman/qmemman*py $RPM_BUILD_ROOT%{python_sitearch}/qubes
cp qmemman/qmemman*py[co] $RPM_BUILD_ROOT%{python_sitearch}/qubes
mkdir -p $RPM_BUILD_ROOT%{python_sitearch}/qubes/modules
cp core-modules/0*.py $RPM_BUILD_ROOT%{python_sitearch}/qubes/modules
cp core-modules/0*.py[co] $RPM_BUILD_ROOT%{python_sitearch}/qubes/modules
cp core-modules/__init__.py $RPM_BUILD_ROOT%{python_sitearch}/qubes/modules
cp core-modules/__init__.py[co] $RPM_BUILD_ROOT%{python_sitearch}/qubes/modules
mkdir -p $RPM_BUILD_ROOT%{python_sitearch}/qubes/tests
cp tests/*.py $RPM_BUILD_ROOT%{python_sitearch}/qubes/tests/
cp tests/*.py[co] $RPM_BUILD_ROOT%{python_sitearch}/qubes/tests/

mkdir -p $RPM_BUILD_ROOT%{_sysconfdir}/qubes
cp qmemman/qmemman.conf $RPM_BUILD_ROOT%{_sysconfdir}/qubes/

mkdir -p $RPM_BUILD_ROOT/usr/lib/qubes
cp linux/aux-tools/unbind-pci-device.sh $RPM_BUILD_ROOT/usr/lib/qubes
cp linux/aux-tools/cleanup-dispvms $RPM_BUILD_ROOT/usr/lib/qubes
cp linux/aux-tools/startup-dvm.sh $RPM_BUILD_ROOT/usr/lib/qubes
cp linux/aux-tools/startup-misc.sh $RPM_BUILD_ROOT/usr/lib/qubes
cp linux/aux-tools/prepare-volatile-img.sh $RPM_BUILD_ROOT/usr/lib/qubes
cp qmemman/server.py $RPM_BUILD_ROOT/usr/lib/qubes/qmemman_daemon.py
cp qubes-rpc/qubes-notify-tools $RPM_BUILD_ROOT/usr/lib/qubes/
cp qubes-rpc/qubes-notify-updates $RPM_BUILD_ROOT/usr/lib/qubes/
cp linux/aux-tools/vusb-ctl.py $RPM_BUILD_ROOT/usr/lib/qubes/
cp linux/aux-tools/xl-qvm-usb-attach.py $RPM_BUILD_ROOT/usr/lib/qubes/
cp linux/aux-tools/xl-qvm-usb-detach.py $RPM_BUILD_ROOT/usr/lib/qubes/
cp linux/aux-tools/block-cleaner-daemon.py $RPM_BUILD_ROOT/usr/lib/qubes/
cp linux/aux-tools/fix-dir-perms.sh $RPM_BUILD_ROOT/usr/lib/qubes/

mkdir -p $RPM_BUILD_ROOT/etc/qubes-rpc/policy
cp qubes-rpc-policy/qubes.Filecopy.policy $RPM_BUILD_ROOT/etc/qubes-rpc/policy/qubes.Filecopy
cp qubes-rpc-policy/qubes.GetImageRGBA.policy $RPM_BUILD_ROOT/etc/qubes-rpc/policy/qubes.GetImageRGBA
cp qubes-rpc-policy/qubes.OpenInVM.policy $RPM_BUILD_ROOT/etc/qubes-rpc/policy/qubes.OpenInVM
cp qubes-rpc-policy/qubes.VMShell.policy $RPM_BUILD_ROOT/etc/qubes-rpc/policy/qubes.VMShell
cp qubes-rpc-policy/qubes.NotifyTools.policy $RPM_BUILD_ROOT/etc/qubes-rpc/policy/qubes.NotifyTools
cp qubes-rpc/qubes.NotifyTools $RPM_BUILD_ROOT/etc/qubes-rpc/
cp qubes-rpc-policy/qubes.NotifyUpdates.policy $RPM_BUILD_ROOT/etc/qubes-rpc/policy/qubes.NotifyUpdates
cp qubes-rpc/qubes.NotifyUpdates $RPM_BUILD_ROOT/etc/qubes-rpc/

cp dispvm/xenstore-watch $RPM_BUILD_ROOT/usr/bin/xenstore-watch-qubes
cp dispvm/qubes-prepare-saved-domain.sh  $RPM_BUILD_ROOT/usr/lib/qubes
cp dispvm/qubes-update-dispvm-savefile-with-progress.sh  $RPM_BUILD_ROOT/usr/lib/qubes
cp dispvm/qfile-daemon-dvm $RPM_BUILD_ROOT/usr/lib/qubes

mkdir -p $RPM_BUILD_ROOT/var/lib/qubes
mkdir -p $RPM_BUILD_ROOT/var/lib/qubes/vm-templates
mkdir -p $RPM_BUILD_ROOT/var/lib/qubes/appvms
mkdir -p $RPM_BUILD_ROOT/var/lib/qubes/servicevms
mkdir -p $RPM_BUILD_ROOT/var/lib/qubes/vm-kernels

mkdir -p $RPM_BUILD_ROOT/var/lib/qubes/backup
mkdir -p $RPM_BUILD_ROOT/var/lib/qubes/dvmdata

mkdir -p $RPM_BUILD_ROOT/usr/share/qubes
cp xen-vm-config/vm-template.xml $RPM_BUILD_ROOT/usr/share/qubes/xen-vm-template.xml
cp xen-vm-config/vm-template-hvm.xml $RPM_BUILD_ROOT/usr/share/qubes/

mkdir -p $RPM_BUILD_ROOT/usr/bin

mkdir -p $RPM_BUILD_ROOT/var/log/qubes
mkdir -p $RPM_BUILD_ROOT/var/run/qubes

install -d $RPM_BUILD_ROOT/etc/xdg/autostart
install -m 0644 linux/system-config/qubes-guid.desktop $RPM_BUILD_ROOT/etc/xdg/autostart/

%post

# Create NetworkManager configuration if we do not have it
if ! [ -e /etc/NetworkManager/NetworkManager.conf ]; then
echo '[main]' > /etc/NetworkManager/NetworkManager.conf
echo 'plugins = keyfile' >> /etc/NetworkManager/NetworkManager.conf
echo '[keyfile]' >> /etc/NetworkManager/NetworkManager.conf
fi

sed '/^autoballoon=/d;/^lockfile=/d' -i /etc/xen/xl.conf
echo 'autoballoon=0' >> /etc/xen/xl.conf
echo 'lockfile="/var/run/qubes/xl-lock"' >> /etc/xen/xl.conf

sed 's/^PRELINKING\s*=.*/PRELINKING=no/' -i /etc/sysconfig/prelink

sed '/^\s*XENCONSOLED_LOG_\(HYPERVISOR\|GUESTS\)\s*=.*/d' -i /etc/sysconfig/xenconsoled
echo XENCONSOLED_LOG_HYPERVISOR=yes >> /etc/sysconfig/xenconsoled
echo XENCONSOLED_LOG_GUESTS=yes >> /etc/sysconfig/xenconsoled


systemctl --no-reload enable qubes-core.service >/dev/null 2>&1
systemctl --no-reload enable qubes-netvm.service >/dev/null 2>&1
systemctl --no-reload enable qubes-setupdvm.service >/dev/null 2>&1

# Conflicts with libxl stack, so disable it
systemctl --no-reload disable xend.service >/dev/null 2>&1
systemctl --no-reload disable xendomains.service >/dev/null 2>&1
systemctl daemon-reload >/dev/null 2>&1 || :

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
    qubes-prefs -s default-kernel `ls /var/lib/qubes/vm-kernels|head -n 1` 2> /dev/null
fi

# Because we now have an installer
# this script is always executed during upgrade
# and we decided not to restart core during upgrade
#service qubes_core start

if [ "x"$HAD_SYSCONFIG_NETWORK = "xno" ]; then
    rm -f /etc/sysconfig/network
fi

%clean
rm -rf $RPM_BUILD_ROOT
rm -f %{name}-%{version}

%pre
if ! grep -q ^qubes: /etc/group ; then
		groupadd qubes
fi

%triggerin -- xen-runtime
sed -i 's/\/block /\/block.qubes /' /etc/udev/rules.d/xen-backend.rules
/usr/lib/qubes/fix-dir-perms.sh

%preun
if [ "$1" = 0 ] ; then
	# no more packages left
    service qubes_netvm stop
    service qubes_core stop
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
%config(noreplace) %attr(0664,root,qubes) %{_sysconfdir}/qubes/qmemman.conf
/usr/bin/qvm-*
/usr/bin/qubes-*
%dir %{python_sitearch}/qubes
%{python_sitearch}/qubes/qubes.py
%{python_sitearch}/qubes/qubes.pyc
%{python_sitearch}/qubes/qubes.pyo
%{python_sitearch}/qubes/qubesutils.py
%{python_sitearch}/qubes/qubesutils.pyc
%{python_sitearch}/qubes/qubesutils.pyo
%{python_sitearch}/qubes/guihelpers.py
%{python_sitearch}/qubes/guihelpers.pyc
%{python_sitearch}/qubes/guihelpers.pyo
%{python_sitearch}/qubes/notify.py
%{python_sitearch}/qubes/notify.pyc
%{python_sitearch}/qubes/notify.pyo
%{python_sitearch}/qubes/backup.py
%{python_sitearch}/qubes/backup.pyc
%{python_sitearch}/qubes/backup.pyo
%{python_sitearch}/qubes/qmemman*.py*
%{python_sitearch}/qubes/modules/0*.py*
%{python_sitearch}/qubes/modules/__init__.py*
%{python_sitearch}/qubes/tests
/usr/lib/qubes/unbind-pci-device.sh
/usr/lib/qubes/cleanup-dispvms
/usr/lib/qubes/qmemman_daemon.py*
/usr/lib/qubes/qfile-daemon-dvm*
/usr/lib/qubes/qubes-notify-tools
/usr/lib/qubes/qubes-notify-updates
/usr/lib/qubes/block-cleaner-daemon.py*
/usr/lib/qubes/vusb-ctl.py*
/usr/lib/qubes/xl-qvm-usb-attach.py*
/usr/lib/qubes/xl-qvm-usb-detach.py*
/usr/lib/qubes/fix-dir-perms.sh
/usr/lib/qubes/startup-dvm.sh
/usr/lib/qubes/startup-misc.sh
/usr/lib/qubes/prepare-volatile-img.sh
%{_unitdir}/qubes-block-cleaner.service
%{_unitdir}/qubes-core.service
%{_unitdir}/qubes-setupdvm.service
%{_unitdir}/qubes-netvm.service
%{_unitdir}/qubes-qmemman.service
%{_unitdir}/qubes-vm@.service
%{_unitdir}/qubes-reload-firewall@.service
%{_unitdir}/qubes-reload-firewall@.timer
%attr(0770,root,qubes) %dir /var/lib/qubes
%attr(0770,root,qubes) %dir /var/lib/qubes/vm-templates
%attr(0770,root,qubes) %dir /var/lib/qubes/appvms
%attr(0770,root,qubes) %dir /var/lib/qubes/servicevms
%attr(0770,root,qubes) %dir /var/lib/qubes/backup
%attr(0770,root,qubes) %dir /var/lib/qubes/dvmdata
%attr(0770,root,qubes) %dir /var/lib/qubes/vm-kernels
/usr/share/qubes/xen-vm-template.xml
/usr/share/qubes/vm-template-hvm.xml
/usr/bin/xenstore-watch-qubes
/usr/lib/qubes/qubes-prepare-saved-domain.sh
/usr/lib/qubes/qubes-update-dispvm-savefile-with-progress.sh
/etc/xen/scripts/block.qubes
/etc/xen/scripts/block-snapshot
/etc/xen/scripts/block-origin
/etc/xen/scripts/vif-route-qubes
%attr(0664,root,qubes) %config(noreplace) /etc/qubes-rpc/policy/qubes.Filecopy
%attr(0664,root,qubes) %config(noreplace) /etc/qubes-rpc/policy/qubes.GetImageRGBA
%attr(0664,root,qubes) %config(noreplace) /etc/qubes-rpc/policy/qubes.OpenInVM
%attr(0664,root,qubes) %config(noreplace) /etc/qubes-rpc/policy/qubes.NotifyTools
%attr(0664,root,qubes) %config(noreplace) /etc/qubes-rpc/policy/qubes.NotifyUpdates
%attr(0664,root,qubes) %config(noreplace) /etc/qubes-rpc/policy/qubes.VMShell
/etc/qubes-rpc/qubes.NotifyTools
/etc/qubes-rpc/qubes.NotifyUpdates
%attr(2770,root,qubes) %dir /var/log/qubes
%attr(0770,root,qubes) %dir /var/run/qubes
/etc/xdg/autostart/qubes-guid.desktop
