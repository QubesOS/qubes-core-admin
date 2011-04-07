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

Name:		qubes-core-commonvm
Version:	%{version}
Release:	1%{dist}
Summary:	The Qubes core files for any VM

Group:		Qubes
Vendor:		Invisible Things Lab
License:	GPL
URL:		http://www.qubes-os.org
Requires:	/usr/bin/xenstore-read
Requires:   fedora-release
BuildRequires: xen-devel

%define _builddir %(pwd)/common

%description
The Qubes core files for installation inside a Qubes VM.

%build
make

%pre

if [ "$1" !=  1 ] ; then
# do this whole %pre thing only when updating for the first time...
exit 0
fi

mkdir -p $RPM_BUILD_ROOT/var/lib/qubes
if [ -e $RPM_BUILD_ROOT/etc/fstab ] ; then 
mv $RPM_BUILD_ROOT/etc/fstab $RPM_BUILD_ROOT/var/lib/qubes/fstab.orig
fi

%install

mkdir -p $RPM_BUILD_ROOT/etc
cp fstab $RPM_BUILD_ROOT/etc/fstab
mkdir -p $RPM_BUILD_ROOT/etc/init.d
cp qubes_core $RPM_BUILD_ROOT/etc/init.d/
mkdir -p $RPM_BUILD_ROOT/var/lib/qubes
mkdir -p $RPM_BUILD_ROOT/etc/sysconfig
cp iptables $RPM_BUILD_ROOT/etc/sysconfig/
mkdir -p $RPM_BUILD_ROOT/etc/yum.repos.d
cp qubes%{dist}.repo $RPM_BUILD_ROOT/etc/yum.repos.d
install -d -m 755 $RPM_BUILD_ROOT/etc/pki/rpm-gpg
install -m 644 RPM-GPG-KEY-qubes* $RPM_BUILD_ROOT/etc/pki/rpm-gpg/
mkdir -p $RPM_BUILD_ROOT/sbin
cp qubes_serial_login $RPM_BUILD_ROOT/sbin
mkdir -p $RPM_BUILD_ROOT/usr/bin
cp xenstore-watch $RPM_BUILD_ROOT/usr/bin
mkdir -p $RPM_BUILD_ROOT/etc
cp serial.conf $RPM_BUILD_ROOT/var/lib/qubes/

%triggerin -- initscripts
cp /var/lib/qubes/serial.conf /etc/init/serial.conf

%post

# Disable gpk-update-icon
sed 's/^NotShowIn=KDE;$/\0QUBES;/' -i /etc/xdg/autostart/gpk-update-icon.desktop

if [ "$1" !=  1 ] ; then
# do this whole %post thing only when updating for the first time...
exit 0
fi

usermod -L root
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
        [ $srv = 'reboot' ] && continue
        [ $srv = 'qubes_gui' ] && continue
        chkconfig $srv off
done

#echo "--> Enabling essential services..."
chkconfig rsyslog on
chkconfig haldaemon on
chkconfig messagebus on
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
/etc/sysconfig/iptables
/var/lib/qubes
/etc/yum.repos.d/qubes%{dist}.repo
/etc/pki/rpm-gpg/RPM-GPG-KEY-qubes*
/sbin/qubes_serial_login
/usr/bin/xenstore-watch
