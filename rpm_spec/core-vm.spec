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

Name:		qubes-core-vm
Version:	%{version}
Release:	1%{dist}
Summary:	The Qubes core files for VM

Group:		Qubes
Vendor:		Invisible Things Lab
License:	GPL
URL:		http://www.qubes-os.org
Requires:	/usr/bin/xenstore-read
Requires:   fedora-release
Requires:   yum-plugin-post-transaction-actions
Requires:   NetworkManager >= 0.8.1-1
Requires:	/usr/bin/mimeopen
Requires:   /sbin/ethtool
Provides:   qubes-core-vm
Obsoletes:  qubes-core-commonvm
Obsoletes:  qubes-core-appvm
Obsoletes:  qubes-core-netvm
Obsoletes:  qubes-core-proxyvm
BuildRequires: xen-devel

%define _builddir %(pwd)

%define kde_service_dir /usr/share/kde4/services/ServiceMenus

%description
The Qubes core files for installation inside a Qubes VM.

%build
make -C u2mfn
make -C vchan
make -C misc
make -C qubes_rpc
make -C qrexec

%pre

if [ "$1" !=  1 ] ; then
# do this whole %pre thing only when updating for the first time...
exit 0
fi

mkdir -p /var/lib/qubes
if [ -e /etc/fstab ] ; then 
mv /etc/fstab /var/lib/qubes/fstab.orig
fi

adduser --create-home user
su user -c 'mkdir -p /home/user/.local/share'
su user -c 'mkdir -p /home/user/.gnome2/nautilus-scripts'
su user -c 'ln -s /usr/lib/qubes/qvm-copy-to-vm.gnome /home/user/.gnome2/nautilus-scripts/"Copy to other AppVM"'
su user -c 'ln -s /usr/bin/qvm-open-in-dvm /home/user/.gnome2/nautilus-scripts/"Open in DisposableVM"'
su user -c 'touch /home/user/.gnome2/nautilus-scripts/.scripts_created'
su user -c 'touch /home/user/.gnome2/nautilus-scripts/.scripts_created2'

%install

install -D misc/fstab $RPM_BUILD_ROOT/etc/fstab
install -d $RPM_BUILD_ROOT/etc/init.d
install vm-init.d/* $RPM_BUILD_ROOT/etc/init.d/

install -d $RPM_BUILD_ROOT/lib/systemd/system $RPM_BUILD_ROOT/usr/lib/qubes/init
install -m 0755 vm-systemd/*.sh $RPM_BUILD_ROOT/usr/lib/qubes/init/
install -m 0644 vm-systemd/qubes-*.service $RPM_BUILD_ROOT/lib/systemd/system/
install -m 0644 vm-systemd/NetworkManager.service $RPM_BUILD_ROOT/usr/lib/qubes/init/
install -m 0644 vm-systemd/cups.service $RPM_BUILD_ROOT/usr/lib/qubes/init/
install -m 0644 vm-systemd/ntpd.service $RPM_BUILD_ROOT/usr/lib/qubes/init/

install -D -m 0440 misc/qubes.sudoers $RPM_BUILD_ROOT/etc/sudoers.d/qubes
install -D misc/qubes.repo $RPM_BUILD_ROOT/etc/yum.repos.d/qubes.repo
install -D misc/serial.conf $RPM_BUILD_ROOT/usr/lib/qubes/serial.conf
install -D misc/qubes_serial_login $RPM_BUILD_ROOT/sbin/qubes_serial_login
install -d $RPM_BUILD_ROOT/usr/share/glib-2.0/schemas/
install misc/org.gnome.settings-daemon.plugins.updates.gschema.override $RPM_BUILD_ROOT/usr/share/glib-2.0/schemas/

install -d $RPM_BUILD_ROOT/var/lib/qubes

install -d -m 755 $RPM_BUILD_ROOT/etc/pki/rpm-gpg
install -m 644 misc/RPM-GPG-KEY-qubes* $RPM_BUILD_ROOT/etc/pki/rpm-gpg/
install -D misc/xenstore-watch $RPM_BUILD_ROOT/usr/bin/xenstore-watch-qubes
install -d $RPM_BUILD_ROOT/etc/udev/rules.d
install  misc/qubes_memory.rules $RPM_BUILD_ROOT/etc/udev/rules.d/50-qubes_memory.rules
install  misc/qubes_block.rules $RPM_BUILD_ROOT/etc/udev/rules.d/99-qubes_block.rules
install -d $RPM_BUILD_ROOT/usr/lib/qubes/
install misc/qubes_download_dom0_updates.sh $RPM_BUILD_ROOT/usr/lib/qubes/
install misc/{block_add_change,block_remove,block_cleanup} $RPM_BUILD_ROOT/usr/lib/qubes/
install misc/qubes_trigger_sync_appmenus.sh $RPM_BUILD_ROOT/usr/lib/qubes/
install -D misc/qubes_trigger_sync_appmenus.action $RPM_BUILD_ROOT/etc/yum/post-actions/qubes_trigger_sync_appmenus.action
mkdir -p $RPM_BUILD_ROOT/usr/lib/qubes

install -D misc/qubes_core.modules $RPM_BUILD_ROOT/etc/sysconfig/modules/qubes_core.modules

install network/qubes_network.rules $RPM_BUILD_ROOT/etc/udev/rules.d/99-qubes_network.rules
install network/qubes_setup_dnat_to_ns $RPM_BUILD_ROOT/usr/lib/qubes
install network/qubes_fix_nm_conf.sh $RPM_BUILD_ROOT/usr/lib/qubes
install network/setup_ip $RPM_BUILD_ROOT/usr/lib/qubes/
install -d $RPM_BUILD_ROOT/etc/dhclient.d
ln -s /usr/lib/qubes/qubes_setup_dnat_to_ns $RPM_BUILD_ROOT/etc/dhclient.d/qubes_setup_dnat_to_ns.sh 
install -d $RPM_BUILD_ROOT/etc/NetworkManager/dispatcher.d/
install network/{qubes_nmhook,30-qubes_external_ip} $RPM_BUILD_ROOT/etc/NetworkManager/dispatcher.d/
install -D network/vif-route-qubes $RPM_BUILD_ROOT/etc/xen/scripts/vif-route-qubes
install -D network/iptables $RPM_BUILD_ROOT/etc/sysconfig/iptables

install -d $RPM_BUILD_ROOT/usr/sbin
install network/qubes_firewall $RPM_BUILD_ROOT/usr/sbin/
install network/qubes_netwatcher $RPM_BUILD_ROOT/usr/sbin/

install -d $RPM_BUILD_ROOT/lib/firmware
ln -s /lib/modules/firmware $RPM_BUILD_ROOT/lib/firmware/updates

install -d $RPM_BUILD_ROOT/usr/bin

install qubes_rpc/{qvm-open-in-dvm,qvm-open-in-vm,qvm-copy-to-vm,qvm-run} $RPM_BUILD_ROOT/usr/bin
install qubes_rpc/wrap_in_html_if_url.sh $RPM_BUILD_ROOT/usr/lib/qubes
install qubes_rpc/qvm-copy-to-vm.kde $RPM_BUILD_ROOT/usr/lib/qubes
install qubes_rpc/qvm-copy-to-vm.gnome $RPM_BUILD_ROOT/usr/lib/qubes
install qubes_rpc/{vm-file-editor,qfile-agent,qopen-in-vm,qfile-unpacker} $RPM_BUILD_ROOT/usr/lib/qubes
install qubes_rpc/{vm-shell,qrun-in-vm} $RPM_BUILD_ROOT/usr/lib/qubes
install -d $RPM_BUILD_ROOT/%{kde_service_dir}
install qubes_rpc/{qvm-copy.desktop,qvm-dvm.desktop} $RPM_BUILD_ROOT/%{kde_service_dir}
install -d $RPM_BUILD_ROOT/etc/qubes_rpc
install qubes_rpc/{qubes.Filecopy,qubes.OpenInVM,qubes.VMShell} $RPM_BUILD_ROOT/etc/qubes_rpc

install qrexec/qrexec_agent $RPM_BUILD_ROOT/usr/lib/qubes
install qrexec/qrexec_client_vm $RPM_BUILD_ROOT/usr/lib/qubes
install qrexec/qubes_rpc_multiplexer $RPM_BUILD_ROOT/usr/lib/qubes

install misc/meminfo-writer $RPM_BUILD_ROOT/usr/lib/qubes
install -d $RPM_BUILD_ROOT/mnt/removable
install -d $RPM_BUILD_ROOT/var/lib/qubes/dom0-updates

install -D misc/xorg-preload-apps.conf $RPM_BUILD_ROOT/etc/X11/xorg-preload-apps.conf

install -d $RPM_BUILD_ROOT/var/run/qubes
install -d $RPM_BUILD_ROOT/home_volatile/user

install -D vchan/libvchan.h $RPM_BUILD_ROOT/usr/include/libvchan.h
install -D u2mfn/u2mfnlib.h $RPM_BUILD_ROOT/usr/include/u2mfnlib.h
install -D u2mfn/u2mfn-kernel.h $RPM_BUILD_ROOT/usr/include/u2mfn-kernel.h

install -D vchan/libvchan.so $RPM_BUILD_ROOT/%{_libdir}/libvchan.so
install -D u2mfn/libu2mfn.so $RPM_BUILD_ROOT/%{_libdir}/libu2mfn.so

%triggerin -- initscripts
cp /usr/lib/qubes/serial.conf /etc/init/serial.conf

%post

# disable some Upstart services
for F in plymouth-shutdown prefdm splash-manager start-ttys tty ; do
	if [ -e /etc/init/$F.conf ]; then
		mv -f /etc/init/$F.conf /etc/init/$F.conf.disabled
	fi
done

remove_ShowIn () {
	if [ -e /etc/xdg/autostart/$1.desktop ]; then
		sed -i '/^\(Not\|Only\)ShowIn/d' /etc/xdg/autostart/$1.desktop
	fi
}

# don't want it at all
for F in abrt-applet deja-dup-monitor imsettings-start krb5-auth-dialog pulseaudio restorecond sealertauto gnome-power-manager gnome-sound-applet gnome-screensaver orca-autostart; do
	if [ -e /etc/xdg/autostart/$F.desktop ]; then
		remove_ShowIn $F
		echo 'NotShowIn=QUBES' >> /etc/xdg/autostart/$F.desktop
	fi
done

# don't want it in DisposableVM
for F in gcm-apply ; do
	if [ -e /etc/xdg/autostart/$F.desktop ]; then
		remove_ShowIn $F
		echo 'NotShowIn=DisposableVM' >> /etc/xdg/autostart/$F.desktop
	fi
done

# want it in AppVM only
for F in gnome-keyring-gpg gnome-keyring-pkcs11 gnome-keyring-secrets gnome-keyring-ssh gnome-settings-daemon user-dirs-update-gtk gsettings-data-convert ; do
	if [ -e /etc/xdg/autostart/$F.desktop ]; then
		remove_ShowIn $F
		echo 'OnlyShowIn=GNOME;AppVM;' >> /etc/xdg/autostart/$F.desktop
	fi
done

# remove existing rule to add own later
for F in gpk-update-icon nm-applet ; do
	remove_ShowIn $F
done

echo 'OnlyShowIn=GNOME;UpdateableVM;' >> /etc/xdg/autostart/gpk-update-icon.desktop || :
echo 'OnlyShowIn=GNOME;NetVM;' >> /etc/xdg/autostart/nm-applet.desktop || :

usermod -p '' root
usermod -L user

# Create NetworkManager configuration if we do not have it
if ! [ -e /etc/NetworkManager/NetworkManager.conf ]; then
echo '[main]' > /etc/NetworkManager/NetworkManager.conf
echo 'plugins = keyfile' >> /etc/NetworkManager/NetworkManager.conf
echo '[keyfile]' >> /etc/NetworkManager/NetworkManager.conf
fi
/usr/lib/qubes/qubes_fix_nm_conf.sh


# Remove ip_forward setting from sysctl, so NM will not reset it
sed 's/^net.ipv4.ip_forward.*/#\0/'  -i /etc/sysctl.conf

# Prevent unnecessary updates in VMs:
sed -i -e '/^exclude = kernel/d' /etc/yum.conf
echo 'exclude = kernel, xorg-x11-drv-*, xorg-x11-drivers, xorg-x11-server-*' >> /etc/yum.conf

if [ "$1" !=  1 ] ; then
# do the rest of %post thing only when updating for the first time...
exit 0
fi

if ! [ -f /var/lib/qubes/serial.orig ] ; then
	cp /etc/init/serial.conf /var/lib/qubes/serial.orig
fi

#echo "--> Disabling SELinux..."
sed -e s/^SELINUX=.*$/SELINUX=disabled/ </etc/selinux/config >/etc/selinux/config.processed
mv /etc/selinux/config.processed /etc/selinux/config
setenforce 0 2>/dev/null

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

    if [ $(basename $f) == "99-qubes_network.rules" ] ; then
        continue
    fi

    if [ $(basename $f) == "99-qubes_block.rules" ] ; then
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
    mv /var/lib/qubes/fstab.orig /etc/fstab
    mv /var/lib/qubes/removed-udev-scripts/* /etc/udev/rules.d/
    mv /var/lib/qubes/serial.orig /etc/init/serial.conf
fi

%postun
if [ $1 -eq 0 ] ; then
    /usr/bin/glib-compile-schemas %{_datadir}/glib-2.0/schemas &> /dev/null || :
fi

%posttrans
    /usr/bin/glib-compile-schemas %{_datadir}/glib-2.0/schemas &> /dev/null || :

%clean
rm -rf $RPM_BUILD_ROOT

%files
%defattr(-,root,root,-)
%dir /var/lib/qubes
%dir /var/run/qubes
%dir %attr(0775,user,user) /var/lib/qubes/dom0-updates
%{kde_service_dir}/qvm-copy.desktop
%{kde_service_dir}/qvm-dvm.desktop
/etc/NetworkManager/dispatcher.d/30-qubes_external_ip
/etc/NetworkManager/dispatcher.d/qubes_nmhook
/etc/X11/xorg-preload-apps.conf
/etc/dhclient.d/qubes_setup_dnat_to_ns.sh
/etc/fstab
/etc/pki/rpm-gpg/RPM-GPG-KEY-qubes*
%dir /etc/qubes_rpc
/etc/qubes_rpc/qubes.Filecopy
/etc/qubes_rpc/qubes.OpenInVM
/etc/qubes_rpc/qubes.VMShell
/etc/sudoers.d/qubes
/etc/sysconfig/iptables
/etc/sysconfig/modules/qubes_core.modules
/etc/udev/rules.d/50-qubes_memory.rules
/etc/udev/rules.d/99-qubes_block.rules
/etc/udev/rules.d/99-qubes_network.rules
/etc/xen/scripts/vif-route-qubes
/etc/yum.repos.d/qubes.repo
/etc/yum/post-actions/qubes_trigger_sync_appmenus.action
/lib/firmware/updates
/sbin/qubes_serial_login
/usr/bin/qvm-copy-to-vm
/usr/bin/qvm-open-in-dvm
/usr/bin/qvm-open-in-vm
/usr/bin/qvm-run
/usr/bin/xenstore-watch-qubes
%dir /usr/lib/qubes
/usr/lib/qubes/block_add_change
/usr/lib/qubes/block_cleanup
/usr/lib/qubes/block_remove
/usr/lib/qubes/meminfo-writer
/usr/lib/qubes/qfile-agent
/usr/lib/qubes/qfile-unpacker
/usr/lib/qubes/qopen-in-vm
/usr/lib/qubes/qrexec_agent
/usr/lib/qubes/qrexec_client_vm
/usr/lib/qubes/qrun-in-vm
/usr/lib/qubes/qubes_download_dom0_updates.sh
/usr/lib/qubes/qubes_fix_nm_conf.sh
/usr/lib/qubes/qubes_rpc_multiplexer
/usr/lib/qubes/qubes_setup_dnat_to_ns
/usr/lib/qubes/qubes_trigger_sync_appmenus.sh
/usr/lib/qubes/qvm-copy-to-vm.gnome
/usr/lib/qubes/qvm-copy-to-vm.kde
/usr/lib/qubes/serial.conf
/usr/lib/qubes/setup_ip
/usr/lib/qubes/vm-file-editor
/usr/lib/qubes/vm-shell
/usr/lib/qubes/wrap_in_html_if_url.sh
/usr/sbin/qubes_firewall
/usr/sbin/qubes_netwatcher
/usr/share/glib-2.0/schemas/org.gnome.settings-daemon.plugins.updates.gschema.override
%dir /home_volatile
%attr(700,user,user) /home_volatile/user
%dir /mnt/removable


%package devel
Summary:        Include files for qubes core libraries
License:        GPL v2 only
Group:          Development/Sources 
Obsoletes:      qubes-core-appvm-devel

%description devel

%files devel
/usr/include/libvchan.h
/usr/include/u2mfnlib.h
/usr/include/u2mfn-kernel.h

%package libs
Summary:        Qubes core libraries
License:        GPL v2 only
Group:          Development/Sources 
Obsoletes:      qubes-core-appvm-libs

%description libs

%files libs
%{_libdir}/libvchan.so
%{_libdir}/libu2mfn.so

%package sysvinit
Summary:        Qubes unit files for SysV init style or upstart
License:        GPL v2 only
Group:          Qubes
Requires:       upstart
Requires:       qubes-core-vm
Provides:       qubes-core-vm-init-scripts
Conflicts:      qubes-core-vm-systemd

%description sysvinit
The Qubes core startup configuration for SysV init (or upstart).

%files sysvinit
/etc/init.d/qubes_core
/etc/init.d/qubes_core_appvm
/etc/init.d/qubes_core_netvm
/etc/init.d/qubes_firewall
/etc/init.d/qubes_netwatcher

%post sysvinit

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
chkconfig --add qubes_core_netvm || echo "WARNING: Cannot add service qubes_core!"
chkconfig qubes_core_netvm on || echo "WARNING: Cannot enable service qubes_core!"
chkconfig --add qubes_core_appvm || echo "WARNING: Cannot add service qubes_core!"
chkconfig qubes_core_appvm on || echo "WARNING: Cannot enable service qubes_core!"
chkconfig --add qubes_firewall || echo "WARNING: Cannot add service qubes_core!"
chkconfig qubes_firewall on || echo "WARNING: Cannot enable service qubes_core!"
chkconfig --add qubes_netwatcher || echo "WARNING: Cannot add service qubes_core!"
chkconfig qubes_netwatcher on || echo "WARNING: Cannot enable service qubes_core!"

# TODO: make this not display the silly message about security context...
sed -i s/^id:.:initdefault:/id:3:initdefault:/ /etc/inittab

%preun sysvinit
if [ "$1" = 0 ] ; then
    # no more packages left
    chkconfig qubes_core off
    chkconfig qubes_core_netvm off
    chkconfig qubes_core_appvm off
    chkconfig qubes_firewall off
    chkconfig qubes_netwatcher off
fi

%package systemd
Summary:        Qubes unit files for SystemD init style
License:        GPL v2 only
Group:          Qubes
Requires:       systemd
Requires(post): systemd-units
Requires(preun): systemd-units
Requires(postun): systemd-units
Requires:       qubes-core-vm
Provides:       qubes-core-vm-init-scripts
Conflicts:      qubes-core-vm-sysvinit

%description systemd
The Qubes core startup configuration for SystemD init.

%files systemd
%defattr(-,root,root,-)
/lib/systemd/system/qubes-dvm.service
/lib/systemd/system/qubes-meminfo-writer.service
/lib/systemd/system/qubes-qrexec-agent.service
/lib/systemd/system/qubes-misc-post.service
/lib/systemd/system/qubes-firewall.service
/lib/systemd/system/qubes-netwatcher.service
/lib/systemd/system/qubes-network.service
/lib/systemd/system/qubes-sysinit.service
%dir /usr/lib/qubes/init
/usr/lib/qubes/init/prepare-dvm.sh
/usr/lib/qubes/init/network-proxy-setup.sh
/usr/lib/qubes/init/misc-post.sh
/usr/lib/qubes/init/qubes-sysinit.sh
/usr/lib/qubes/init/NetworkManager.service
/usr/lib/qubes/init/cups.service
/usr/lib/qubes/init/ntpd.service
%ghost %attr(0644,root,root) /etc/systemd/system/NetworkManager.service
%ghost %attr(0644,root,root) /etc/systemd/system/cups.service

%post systemd

for srv in qubes-dvm qubes-meminfo-writer qubes-qrexec-agent qubes-sysinit qubes-misc-post qubes-netwatcher qubes-network; do
    /bin/systemctl enable $srv.service
done

# Install overriden services only when original exists
for srv in cups NetworkManager ntpd; do
    if [ -f /lib/systemd/system/$srv.service ]; then
        cp /usr/lib/qubes/init/$srv.service /etc/systemd/system/$srv.service
    fi
done

# Set default "runlevel"
rm -f /etc/systemd/system/default.target
ln -s /lib/systemd/system/multi-user.target /etc/systemd/system/default.target

# Services to disable
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

DISABLE_SERVICES="alsa-store alsa-restore auditd backuppc cpuspeed crond dbus-org.freedesktop.Avahi"
DISABLE_SERVICES="$DISABLE_SERVICES fedora-autorelabel fedora-autorelabel-mark ipmi hwclock-load hwclock-save"
DISABLE_SERVICES="$DISABLE_SERVICES mdmonitor multipathd openct rpcbind mcelog fedora-storage-init fedora-storage-init-late"
DISABLE_SERVICES="$DISABLE_SERVICES plymouth-start plymouth-read-write plymouth-quit plymouth-quit-wait"
for srv in $DISABLE_SERVICES; do
    if [ -f /lib/systemd/system/$srv.service ]; then
        if fgrep -q '[Install]' /lib/systemd/system/$srv.service; then
            /bin/systemctl disable $srv.service
        else
            # forcibly disable
            ln -sf /dev/null /etc/systemd/system/$srv.service
        fi
    fi
done

rm -f /etc/systemd/system/getty.target.wants/getty@tty*.service

# Enable some services
/bin/systemctl enable iptables.service
/bin/systemctl enable rsyslog.service
/bin/systemctl enable ntpd.service
/bin/systemctl enable NetworkManager.service
# Enable cups only when it is real SystemD service
[ -e /lib/systemd/system/cups.service ] && /bin/systemctl enable cups.service

exit 0

%postun systemd

#Do not run this part on upgrades
if [ "$1" != 0 ] ; then
    exit 0
fi

for srv in qubes-dvm qubes-meminfo-writer qubes-qrexec-agent qubes-sysinit qubes-misc-post qubes-netwatcher qubes-network; do
    /bin/systemctl disable $srv.service
do
