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
Release:	1
Summary:	The Qubes core files for AppVM

Group:		Qubes
Vendor:		Invisible Things Lab
License:	GPL
URL:		http://www.qubes-os.org
Requires:	/usr/bin/xenstore-read
Requires:   fedora-release = 13
Requires:	/usr/bin/mimeopen
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

mkdir -p $RPM_BUILD_ROOT/var/lib/qubes
if [ -e $RPM_BUILD_ROOT/etc/fstab ] ; then 
mv $RPM_BUILD_ROOT/etc/fstab $RPM_BUILD_ROOT/var/lib/qubes/fstab.orig
fi

%build
make clean all
make -C ../common
make -C ../qrexec
make -C ../vchan
make -C ../u2mfn

%install

mkdir -p $RPM_BUILD_ROOT/etc
cp fstab $RPM_BUILD_ROOT/etc/fstab
mkdir -p $RPM_BUILD_ROOT/etc/init.d
cp qubes_core $RPM_BUILD_ROOT/etc/init.d/
mkdir -p $RPM_BUILD_ROOT/var/lib/qubes
mkdir -p $RPM_BUILD_ROOT/usr/bin
cp qubes_timestamp qvm-copy-to-vm qvm-open-in-dvm qvm-open-in-dvm2 $RPM_BUILD_ROOT/usr/bin
mkdir -p $RPM_BUILD_ROOT/usr/lib/qubes
cp qubes_add_pendrive_script qubes_penctl qvm-copy-to-vm.kde $RPM_BUILD_ROOT/usr/lib/qubes
cp ../qrexec/qrexec_agent $RPM_BUILD_ROOT/usr/lib/qubes
cp dvm_file_editor qfile-agent qfile-agent-dvm qfile-unpacker $RPM_BUILD_ROOT/usr/lib/qubes
ln -s /usr/bin/qvm-open-in-dvm $RPM_BUILD_ROOT/usr/lib/qubes/qvm-dvm-transfer 
cp ../common/meminfo-writer $RPM_BUILD_ROOT/usr/lib/qubes
mkdir -p $RPM_BUILD_ROOT/%{kde_service_dir}
cp qvm-copy.desktop qvm-dvm.desktop $RPM_BUILD_ROOT/%{kde_service_dir}
mkdir -p $RPM_BUILD_ROOT/etc/udev/rules.d
cp qubes.rules $RPM_BUILD_ROOT/etc/udev/rules.d
mkdir -p $RPM_BUILD_ROOT/etc/sysconfig
cp iptables $RPM_BUILD_ROOT/etc/sysconfig/
mkdir -p $RPM_BUILD_ROOT/mnt/incoming
mkdir -p $RPM_BUILD_ROOT/mnt/outgoing
mkdir -p $RPM_BUILD_ROOT/mnt/removable
mkdir -p $RPM_BUILD_ROOT/etc/yum.repos.d
cp ../appvm/qubes.repo $RPM_BUILD_ROOT/etc/yum.repos.d
mkdir -p $RPM_BUILD_ROOT/sbin   
cp ../common/qubes_serial_login $RPM_BUILD_ROOT/sbin
mkdir -p $RPM_BUILD_ROOT/etc
cp ../common/serial.conf $RPM_BUILD_ROOT/var/lib/qubes/

mkdir -p $RPM_BUILD_ROOT/etc/X11
cp xorg-preload-apps.conf $RPM_BUILD_ROOT/etc/X11

mkdir -p $RPM_BUILD_ROOT/home_volatile/user
chown 500:500 $RPM_BUILD_ROOT/home_volatile/user

install -D ../vchan/libvchan.h $RPM_BUILD_ROOT/usr/include/libvchan.h
install -D ../u2mfn/u2mfnlib.h $RPM_BUILD_ROOT/usr/include/u2mfnlib.h
install -D ../u2mfn/u2mfn-kernel.h $RPM_BUILD_ROOT/usr/include/u2mfn-kernel.h

install -D ../vchan/libvchan.so $RPM_BUILD_ROOT/%{_libdir}/libvchan.so
install -D ../u2mfn/libu2mfn.so $RPM_BUILD_ROOT/%{_libdir}/libu2mfn.so

mkdir -p $RPM_BUILD_ROOT/var/run/qubes

%triggerin -- initscripts
cp /var/lib/qubes/serial.conf /etc/init/serial.conf

%post

if [ "$1" !=  1 ] ; then
# do this whole %post thing only when updating for the first time...
exit 0
fi

usermod -L root
usermod -L user
if ! [ -f /var/lib/qubes/serial.orig ] ; then
	cp /etc/init/serial.conf /var/lib/qubes/serial.orig
fi

#echo "--> Disabling SELinux..."
sed -e s/^SELINUX=.*$/SELINUX=disabled/ </etc/selinux/config >/etc/selinux/config.processed
mv /etc/selinux/config.processed /etc/selinux/config
setenforce 0 2>/dev/null

#echo "--> Turning off unnecessary services..."
# FIXME: perhaps there is more elegant way to do this? 
for f in /etc/init.d/*
do
        srv=`basename $f`
        [ $srv = 'functions' ] && continue
        [ $srv = 'killall' ] && continue
        [ $srv = 'halt' ] && continue
        [ $srv = 'single' ] && continue
        chkconfig $srv off
done

#echo "--> Enabling essential services..."
chkconfig rsyslog on
chkconfig haldaemon on
chkconfig messagebus on
chkconfig cups on
chkconfig iptables on
chkconfig --add qubes_core || echo "WARNING: Cannot add service qubes_core!"
chkconfig qubes_core on || echo "WARNING: Cannot enable service qubes_core!"


# TODO: make this not display the silly message about security context...
sed -i s/^id:.:initdefault:/id:3:initdefault:/ /etc/inittab

# Remove most of the udev scripts to speed up the VM boot time
# Just leave the xen* scripts, that are needed if this VM was
# ever used as a net backend (e.g. as a VPN domain in the future)
#echo "--> Removing unnecessary udev scripts..."
mkdir -p /var/lib/qubes/removed-udev-scripts
for f in /etc/udev/rules.d/*
do
    if [ $(basename $f) == "xen-backend.rules" ] ; then
        continue
    fi

    if [ $(basename $f) == "xend.rules" ] ; then
        continue
    fi

    if [ $(basename $f) == "qubes.rules" ] ; then
        continue
    fi

    if [ $(basename $f) == "90-hal.rules" ] ; then
        continue
    fi


    mv $f /var/lib/qubes/removed-udev-scripts/
done
mkdir -p /rw
#rm -f /etc/mtab
#echo "--> Removing HWADDR setting from /etc/sysconfig/network-scripts/ifcfg-eth0"
#mv /etc/sysconfig/network-scripts/ifcfg-eth0 /etc/sysconfig/network-scripts/ifcfg-eth0.orig
#grep -v HWADDR /etc/sysconfig/network-scripts/ifcfg-eth0.orig > /etc/sysconfig/network-scripts/ifcfg-eth0

%preun
if [ "$1" = 0 ] ; then
    # no more packages left
    chkconfig qubes_core off
    mv /var/lib/qubes/fstab.orig /etc/fstab
    mv /var/lib/qubes/removed-udev-scripts/* /etc/udev/rules.d/
    mv /var/lib/qubes/serial.orig /etc/init/serial.conf
fi

%clean
rm -rf $RPM_BUILD_ROOT

%files
%defattr(-,root,root,-)
/etc/fstab
/etc/init.d/qubes_core
/usr/bin/qvm-copy-to-vm
/usr/lib/qubes/qvm-copy-to-vm.kde
%attr(4755,root,root) /usr/bin/qvm-open-in-dvm
/usr/bin/qvm-open-in-dvm2
/usr/lib/qubes/qvm-dvm-transfer
/usr/lib/qubes/meminfo-writer
/usr/lib/qubes/dvm_file_editor
%{kde_service_dir}/qvm-copy.desktop
%{kde_service_dir}/qvm-dvm.desktop
%attr(4755,root,root) /usr/lib/qubes/qubes_penctl
/usr/lib/qubes/qubes_add_pendrive_script
/usr/lib/qubes/qrexec_agent
/usr/lib/qubes/qfile-agent
/usr/lib/qubes/qfile-agent-dvm
/usr/lib/qubes/qfile-unpacker
/etc/udev/rules.d/qubes.rules
/etc/sysconfig/iptables
/var/lib/qubes
%dir /mnt/incoming
%dir /mnt/outgoing
%dir /mnt/removable
/etc/yum.repos.d/qubes.repo
/sbin/qubes_serial_login
/usr/bin/qubes_timestamp
%dir /home_volatile
%attr(700,user,user) /home_volatile/user
/etc/X11/xorg-preload-apps.conf
/usr/include/libvchan.h
%{_libdir}/libvchan.so
%{_libdir}/libu2mfn.so
%dir /var/run/qubes


%package devel
Summary:        Include files for qubes core libraries
License:        GPL v2 only
Group:          Development/Sources 

%description devel

%files devel
/usr/include/libvchan.h
/usr/include/u2mfnlib.h
/usr/include/u2mfn-kernel.h
