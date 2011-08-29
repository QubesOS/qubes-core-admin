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

Name:		qubes-core-appvm
Version:	%{version}
Release:	1%{dist}
Summary:	The Qubes core files for AppVM

Group:		Qubes
Vendor:		Invisible Things Lab
License:	GPL
URL:		http://www.qubes-os.org
Requires:	/usr/bin/xenstore-read
Requires:   fedora-release
Requires:	/usr/bin/mimeopen
Requires:	qubes-core-commonvm
BuildRequires:  gcc
BuildRequires:  xen-devel
Provides:   qubes-core-vm

%define _builddir %(pwd)/appvm

%define kde_service_dir /usr/share/kde4/services/ServiceMenus 

%description
The Qubes core files for installation inside a Qubes AppVM.

%pre

if [ "$1" !=  1 ] ; then
# do this whole %pre thing only when updating for the first time...
exit 0
fi

adduser --create-home user
su user -c 'mkdir -p /home/user/.local/share'
su user -c 'mkdir -p /home/user/.gnome2/nautilus-scripts'
su user -c 'ln -s /usr/lib/qubes/qvm-copy-to-vm2.gnome /home/user/.gnome2/nautilus-scripts/"Copy to other AppVM"'
su user -c 'ln -s /usr/bin/qvm-open-in-dvm2 /home/user/.gnome2/nautilus-scripts/"Open in DisposableVM"'

mkdir -p $RPM_BUILD_ROOT/var/lib/qubes

%build
make clean all
make -C ../common
make -C ../u2mfn
make -C ../vchan
make -C ../qrexec

%install

mkdir -p $RPM_BUILD_ROOT/etc/init.d
cp qubes_core_appvm $RPM_BUILD_ROOT/etc/init.d/
mkdir -p $RPM_BUILD_ROOT/var/lib/qubes
mkdir -p $RPM_BUILD_ROOT/usr/bin
cp qubes_timestamp qvm-open-in-dvm2 $RPM_BUILD_ROOT/usr/bin
cp qvm-open-in-vm $RPM_BUILD_ROOT/usr/bin
cp qvm-copy-to-vm $RPM_BUILD_ROOT/usr/bin
cp qvm-run $RPM_BUILD_ROOT/usr/bin
mkdir -p $RPM_BUILD_ROOT/usr/lib/qubes
cp wrap_in_html_if_url.sh $RPM_BUILD_ROOT/usr/lib/qubes
cp qvm-copy-to-vm2.kde $RPM_BUILD_ROOT/usr/lib/qubes
cp qvm-copy-to-vm2.gnome $RPM_BUILD_ROOT/usr/lib/qubes
cp ../qrexec/qrexec_agent $RPM_BUILD_ROOT/usr/lib/qubes
cp ../qrexec/qrexec_client_vm $RPM_BUILD_ROOT/usr/lib/qubes
cp ../qrexec/qubes_rpc_multiplexer $RPM_BUILD_ROOT/usr/lib/qubes
cp vm-file-editor qfile-agent qopen-in-vm qfile-unpacker $RPM_BUILD_ROOT/usr/lib/qubes
cp vm-shell qrun-in-vm $RPM_BUILD_ROOT/usr/lib/qubes
cp ../common/meminfo-writer $RPM_BUILD_ROOT/usr/lib/qubes
mkdir -p $RPM_BUILD_ROOT/%{kde_service_dir}
cp qvm-copy.desktop qvm-dvm.desktop $RPM_BUILD_ROOT/%{kde_service_dir}
mkdir -p $RPM_BUILD_ROOT/mnt/removable
mkdir -p $RPM_BUILD_ROOT/etc/qubes_rpc
cp qubes.Filecopy $RPM_BUILD_ROOT/etc/qubes_rpc
cp qubes.OpenInVM $RPM_BUILD_ROOT/etc/qubes_rpc
cp qubes.VMShell $RPM_BUILD_ROOT/etc/qubes_rpc
mkdir -p $RPM_BUILD_ROOT/var/lib/qubes/dom0-updates

mkdir -p $RPM_BUILD_ROOT/etc/X11
cp xorg-preload-apps.conf $RPM_BUILD_ROOT/etc/X11

mkdir -p $RPM_BUILD_ROOT/home_volatile/user
chown 500:500 $RPM_BUILD_ROOT/home_volatile/user

install -D ../vchan/libvchan.h $RPM_BUILD_ROOT/usr/include/libvchan.h
install -D ../u2mfn/u2mfnlib.h $RPM_BUILD_ROOT/usr/include/u2mfnlib.h
install -D ../u2mfn/u2mfn-kernel.h $RPM_BUILD_ROOT/usr/include/u2mfn-kernel.h

install -D ../vchan/libvchan.so $RPM_BUILD_ROOT/%{_libdir}/libvchan.so
install -D ../u2mfn/libu2mfn.so $RPM_BUILD_ROOT/%{_libdir}/libu2mfn.so

install -d $RPM_BUILD_ROOT/etc/sudoers.d
install -m 0440 qubes.sudoers $RPM_BUILD_ROOT/etc/sudoers.d/qubes

mkdir -p $RPM_BUILD_ROOT/var/run/qubes

%triggerin -- initscripts
cp /var/lib/qubes/serial.conf /etc/init/serial.conf

%post

chkconfig --add qubes_core_appvm || echo "WARNING: Cannot add service qubes_core!"
chkconfig qubes_core_appvm on || echo "WARNING: Cannot enable service qubes_core!"

if [ "$1" !=  1 ] ; then
# do this whole %post thing only when updating for the first time...
exit 0
fi

usermod -L user

%preun
if [ "$1" = 0 ] ; then
    # no more packages left
    chkconfig qubes_core_appvm off
fi

%clean
rm -rf $RPM_BUILD_ROOT

%files
%defattr(-,root,root,-)
/etc/init.d/qubes_core_appvm
/usr/bin/qvm-copy-to-vm
/usr/lib/qubes/qvm-copy-to-vm2.kde
/usr/lib/qubes/qvm-copy-to-vm2.gnome
/usr/bin/qvm-open-in-dvm2
/usr/bin/qvm-open-in-vm
/usr/bin/qvm-run
/usr/lib/qubes/meminfo-writer
/usr/lib/qubes/vm-file-editor
%{kde_service_dir}/qvm-copy.desktop
%{kde_service_dir}/qvm-dvm.desktop
/usr/lib/qubes/qrexec_agent
/usr/lib/qubes/qrexec_client_vm
/usr/lib/qubes/qubes_rpc_multiplexer
/usr/lib/qubes/qfile-agent
/usr/lib/qubes/qopen-in-vm
/usr/lib/qubes/qfile-unpacker
/usr/lib/qubes/vm-shell
/usr/lib/qubes/qrun-in-vm
/usr/lib/qubes/wrap_in_html_if_url.sh
%dir /mnt/removable
%dir /etc/qubes_rpc
/etc/qubes_rpc/qubes.Filecopy
/etc/qubes_rpc/qubes.OpenInVM
/etc/qubes_rpc/qubes.VMShell
/usr/bin/qubes_timestamp
%dir /home_volatile
%attr(700,user,user) /home_volatile/user
/etc/X11/xorg-preload-apps.conf
%dir /var/run/qubes
%dir %attr(0775,user,user) /var/lib/qubes/dom0-updates
/etc/sudoers.d/qubes

%package devel
Summary:        Include files for qubes core libraries
License:        GPL v2 only
Group:          Development/Sources 

%description devel

%files devel
/usr/include/libvchan.h
/usr/include/u2mfnlib.h
/usr/include/u2mfn-kernel.h

%package libs
Summary:        Qubes core libraries
License:        GPL v2 only
Group:          Development/Sources 

%description libs

%files libs
%{_libdir}/libvchan.so
%{_libdir}/libu2mfn.so

