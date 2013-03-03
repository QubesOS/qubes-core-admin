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
%if %{fedora} >= 18
# Fedora >= 18 defaults to firewalld, which isn't supported nor needed by Qubes
Requires:   iptables-services
Conflicts:  firewalld
%endif
Requires:	/usr/bin/mimeopen
Requires:   ethtool
Requires:   tinyproxy
Requires:   ntpdate
Requires:   net-tools
Requires:   nautilus-actions
Requires:   qubes-core-vm-kernel-placeholder
Requires:   qubes-core-libs
Provides:   qubes-core-vm
Obsoletes:  qubes-core-commonvm
Obsoletes:  qubes-core-appvm
Obsoletes:  qubes-core-netvm
Obsoletes:  qubes-core-proxyvm
Obsoletes:  qubes-upgrade-vm < 2.0
BuildRequires: xen-devel

%define _builddir %(pwd)

%define kde_service_dir /usr/share/kde4/services/ServiceMenus

%description
The Qubes core files for installation inside a Qubes VM.

%prep
# we operate on the current directory, so no need to unpack anything
# symlink is to generate useful debuginfo packages
rm -f %{name}-%{version}
ln -sf . %{name}-%{version}
%setup -T -D

%build
(cd vchan; make -f Makefile.linux)
(cd qrexec; make)
for dir in qubes_rpc misc; do
  (cd $dir; make)
done

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

%install

install -m 0644 -D misc/fstab $RPM_BUILD_ROOT/etc/fstab
install -d $RPM_BUILD_ROOT/etc/init.d
install vm-init.d/* $RPM_BUILD_ROOT/etc/init.d/

install -d $RPM_BUILD_ROOT/lib/systemd/system $RPM_BUILD_ROOT/usr/lib/qubes/init
install -m 0755 vm-systemd/*.sh $RPM_BUILD_ROOT/usr/lib/qubes/init/
install -m 0644 vm-systemd/qubes-*.service $RPM_BUILD_ROOT/lib/systemd/system/
install -m 0644 vm-systemd/qubes-*.timer $RPM_BUILD_ROOT/lib/systemd/system/
install -m 0644 vm-systemd/NetworkManager.service $RPM_BUILD_ROOT/usr/lib/qubes/init/
install -m 0644 vm-systemd/NetworkManager-wait-online.service $RPM_BUILD_ROOT/usr/lib/qubes/init/
install -m 0644 vm-systemd/cups.service $RPM_BUILD_ROOT/usr/lib/qubes/init/
install -m 0644 vm-systemd/ntpd.service $RPM_BUILD_ROOT/usr/lib/qubes/init/

install -D -m 0440 misc/qubes.sudoers $RPM_BUILD_ROOT/etc/sudoers.d/qubes
install -D -m 0644 misc/qubes.repo $RPM_BUILD_ROOT/etc/yum.repos.d/qubes.repo
install -D -m 0644 misc/serial.conf $RPM_BUILD_ROOT/usr/lib/qubes/serial.conf
install -D misc/qubes_serial_login $RPM_BUILD_ROOT/sbin/qubes_serial_login
install -d $RPM_BUILD_ROOT/usr/share/glib-2.0/schemas/
install -m 0644 misc/org.gnome.settings-daemon.plugins.updates.gschema.override $RPM_BUILD_ROOT/usr/share/glib-2.0/schemas/
install -d $RPM_BUILD_ROOT/usr/lib/yum-plugins/
install -m 0644 misc/yum-qubes-hooks.py* $RPM_BUILD_ROOT/usr/lib/yum-plugins/
install -D -m 0644 misc/yum-qubes-hooks.conf $RPM_BUILD_ROOT/etc/yum/pluginconf.d/yum-qubes-hooks.conf

install -d $RPM_BUILD_ROOT/var/lib/qubes

install -d -m 755 $RPM_BUILD_ROOT/etc/pki/rpm-gpg
install -m 644 misc/RPM-GPG-KEY-qubes* $RPM_BUILD_ROOT/etc/pki/rpm-gpg/
install -D misc/xenstore-watch $RPM_BUILD_ROOT/usr/bin/xenstore-watch-qubes
install -d $RPM_BUILD_ROOT/etc/udev/rules.d
install -m 0644 misc/qubes_misc.rules $RPM_BUILD_ROOT/etc/udev/rules.d/50-qubes_misc.rules
install -m 0644 misc/qubes_block.rules $RPM_BUILD_ROOT/etc/udev/rules.d/99-qubes_block.rules
install -m 0644 misc/qubes_usb.rules $RPM_BUILD_ROOT/etc/udev/rules.d/99-qubes_usb.rules
install -d $RPM_BUILD_ROOT/usr/lib/qubes/
install misc/qubes_download_dom0_updates.sh $RPM_BUILD_ROOT/usr/lib/qubes/
install misc/{block_add_change,block_remove,block_cleanup} $RPM_BUILD_ROOT/usr/lib/qubes/
install misc/{usb_add_change,usb_remove} $RPM_BUILD_ROOT/usr/lib/qubes/
install misc/vusb-ctl.py $RPM_BUILD_ROOT/usr/lib/qubes/
install misc/qubes_trigger_sync_appmenus.sh $RPM_BUILD_ROOT/usr/lib/qubes/
install -D -m 0644 misc/qubes_trigger_sync_appmenus.action $RPM_BUILD_ROOT/etc/yum/post-actions/qubes_trigger_sync_appmenus.action
install -D misc/polkit-1-qubes-allow-all.pkla $RPM_BUILD_ROOT/etc/polkit-1/localauthority/50-local.d/qubes-allow-all.pkla
install -D misc/polkit-1-qubes-allow-all.rules $RPM_BUILD_ROOT/etc/polkit-1/rules.d/00-qubes-allow-all.rules
mkdir -p $RPM_BUILD_ROOT/usr/lib/qubes

if [ -r misc/dispvm-dotfiles.%{dist}.tbz ]; then
    install misc/dispvm-dotfiles.%{dist}.tbz $RPM_BUILD_ROOT/etc/dispvm-dotfiles.tbz
else
    install misc/dispvm-dotfiles.tbz $RPM_BUILD_ROOT/etc/dispvm-dotfiles.tbz
fi
install misc/dispvm-prerun.sh $RPM_BUILD_ROOT/usr/lib/qubes/dispvm-prerun.sh

install -D misc/qubes_core.modules $RPM_BUILD_ROOT/etc/sysconfig/modules/qubes_core.modules
install -D misc/qubes_misc.modules $RPM_BUILD_ROOT/etc/sysconfig/modules/qubes_misc.modules

install -m 0644 network/qubes_network.rules $RPM_BUILD_ROOT/etc/udev/rules.d/99-qubes_network.rules
install network/qubes_setup_dnat_to_ns $RPM_BUILD_ROOT/usr/lib/qubes
install network/qubes_fix_nm_conf.sh $RPM_BUILD_ROOT/usr/lib/qubes
install network/setup_ip $RPM_BUILD_ROOT/usr/lib/qubes/
install network/network-manager-prepare-conf-dir $RPM_BUILD_ROOT/usr/lib/qubes/
install -d $RPM_BUILD_ROOT/etc/dhclient.d
ln -s /usr/lib/qubes/qubes_setup_dnat_to_ns $RPM_BUILD_ROOT/etc/dhclient.d/qubes_setup_dnat_to_ns.sh 
install -d $RPM_BUILD_ROOT/etc/NetworkManager/dispatcher.d/
install network/{qubes_nmhook,30-qubes_external_ip} $RPM_BUILD_ROOT/etc/NetworkManager/dispatcher.d/
install -D network/vif-route-qubes $RPM_BUILD_ROOT/etc/xen/scripts/vif-route-qubes
install -m 0400 -D network/iptables $RPM_BUILD_ROOT/etc/sysconfig/iptables
install -m 0400 -D network/ip6tables $RPM_BUILD_ROOT/etc/sysconfig/ip6tables
install -m 0644 -D network/tinyproxy-qubes-yum.conf $RPM_BUILD_ROOT/etc/tinyproxy/tinyproxy-qubes-yum.conf
install -m 0644 -D network/filter-qubes-yum $RPM_BUILD_ROOT/etc/tinyproxy/filter-qubes-yum

install -d $RPM_BUILD_ROOT/etc/yum.conf.d
touch $RPM_BUILD_ROOT/etc/yum.conf.d/qubes-proxy.conf

install -d $RPM_BUILD_ROOT/usr/sbin
install network/qubes_firewall $RPM_BUILD_ROOT/usr/sbin/
install network/qubes_netwatcher $RPM_BUILD_ROOT/usr/sbin/

install -d $RPM_BUILD_ROOT/usr/bin

install qubes_rpc/{qvm-open-in-dvm,qvm-open-in-vm,qvm-copy-to-vm,qvm-run,qvm-mru-entry} $RPM_BUILD_ROOT/usr/bin
install qubes_rpc/wrap_in_html_if_url.sh $RPM_BUILD_ROOT/usr/lib/qubes
install qubes_rpc/qvm-copy-to-vm.kde $RPM_BUILD_ROOT/usr/lib/qubes
install qubes_rpc/qvm-copy-to-vm.gnome $RPM_BUILD_ROOT/usr/lib/qubes
install qubes_rpc/{vm-file-editor,qfile-agent,qopen-in-vm,qfile-unpacker} $RPM_BUILD_ROOT/usr/lib/qubes
install qubes_rpc/qrun-in-vm $RPM_BUILD_ROOT/usr/lib/qubes
install qubes_rpc/sync-ntp-clock $RPM_BUILD_ROOT/usr/lib/qubes
install qubes_rpc/prepare-suspend $RPM_BUILD_ROOT/usr/lib/qubes
install -d $RPM_BUILD_ROOT/%{kde_service_dir}
install -m 0644 qubes_rpc/{qvm-copy.desktop,qvm-dvm.desktop} $RPM_BUILD_ROOT/%{kde_service_dir}
install -d $RPM_BUILD_ROOT/etc/qubes_rpc
install -m 0644 qubes_rpc/{qubes.Filecopy,qubes.OpenInVM,qubes.VMShell,qubes.SyncNtpClock} $RPM_BUILD_ROOT/etc/qubes_rpc
install -m 0644 qubes_rpc/{qubes.SuspendPre,qubes.SuspendPost,qubes.GetAppmenus} $RPM_BUILD_ROOT/etc/qubes_rpc
install -m 0644 qubes_rpc/qubes.WaitForSession $RPM_BUILD_ROOT/etc/qubes_rpc

install -d $RPM_BUILD_ROOT/usr/share/file-manager/actions
install -m 0644 qubes_rpc/*-gnome.desktop $RPM_BUILD_ROOT/usr/share/file-manager/actions

install -D misc/nautilus-actions.conf $RPM_BUILD_ROOT/etc/xdg/nautilus-actions/nautilus-actions.conf

install qrexec/qrexec_agent $RPM_BUILD_ROOT/usr/lib/qubes
install qrexec/qrexec_client_vm $RPM_BUILD_ROOT/usr/lib/qubes
install qrexec/qubes_rpc_multiplexer $RPM_BUILD_ROOT/usr/lib/qubes

install misc/meminfo-writer $RPM_BUILD_ROOT/usr/lib/qubes
install -d $RPM_BUILD_ROOT/mnt/removable
install -d $RPM_BUILD_ROOT/var/lib/qubes/dom0-updates

install -D -m 0644 misc/xorg-preload-apps.conf $RPM_BUILD_ROOT/etc/X11/xorg-preload-apps.conf

install -d $RPM_BUILD_ROOT/var/run/qubes
install -d $RPM_BUILD_ROOT/home_volatile/user

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
		echo 'NotShowIn=QUBES;' >> /etc/xdg/autostart/$F.desktop
	fi
done

# don't want it in DisposableVM
for F in gcm-apply ; do
	if [ -e /etc/xdg/autostart/$F.desktop ]; then
		remove_ShowIn $F
		echo 'NotShowIn=DisposableVM;' >> /etc/xdg/autostart/$F.desktop
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

# Install firmware link only on system which haven't it yet
if ! [ -e /lib/firmware/updates ]; then
  ln -s /lib/modules/firmware /lib/firmware/updates
fi

if ! grep -q '/etc/yum\.conf\.d/qubes-proxy\.conf' /etc/yum.conf; then
  echo >> /etc/yum.conf
  echo '# Yum does not support inclusion of config dir...' >> /etc/yum.conf
  echo 'include=file:///etc/yum.conf.d/qubes-proxy.conf' >> /etc/yum.conf
fi

# Revert 'Prevent unnecessary updates in VMs':
sed -i -e '/^exclude = kernel/d' /etc/yum.conf

# qubes-core-vm has been broken for some time - it overrides /etc/hosts; restore original content
if ! grep -q localhost /etc/hosts; then
  cat <<EOF > /etc/hosts
127.0.0.1   localhost localhost.localdomain localhost4 localhost4.localdomain4 `hostname`
::1         localhost localhost.localdomain localhost6 localhost6.localdomain6
EOF
fi

if [ "$1" !=  1 ] ; then
# do the rest of %post thing only when updating for the first time...
exit 0
fi

if [ -e /etc/init/serial.conf ] && ! [ -f /var/lib/qubes/serial.orig ] ; then
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

    if [ $(basename $f) == "50-qubes_misc.rules" ] ; then
        continue
    fi

    if [ $(basename $f) == "99-qubes_network.rules" ] ; then
        continue
    fi

    if [ $(basename $f) == "99-qubes_block.rules" ] ; then
        continue
    fi

    if [ $(basename $f) == "99-qubes_usb.rules" ] ; then
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
    if [ -e /var/lib/qubes/fstab.orig ] ; then
    mv /var/lib/qubes/fstab.orig /etc/fstab
    fi
    mv /var/lib/qubes/removed-udev-scripts/* /etc/udev/rules.d/
    if [ -e /var/lib/qubes/serial.orig ] ; then
    mv /var/lib/qubes/serial.orig /etc/init/serial.conf
    fi
fi

%postun
if [ $1 -eq 0 ] ; then
    /usr/bin/glib-compile-schemas %{_datadir}/glib-2.0/schemas &> /dev/null || :

    if [ -l /lib/firmware/updates ]; then
      rm /lib/firmware/updates
    fi
fi

%posttrans
    /usr/bin/glib-compile-schemas %{_datadir}/glib-2.0/schemas &> /dev/null || :

%clean
rm -rf $RPM_BUILD_ROOT
rm -f %{name}-%{version}

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
/etc/dispvm-dotfiles.tbz
/etc/dhclient.d/qubes_setup_dnat_to_ns.sh
/etc/fstab
/etc/pki/rpm-gpg/RPM-GPG-KEY-qubes*
/etc/polkit-1/localauthority/50-local.d/qubes-allow-all.pkla
/etc/polkit-1/rules.d/00-qubes-allow-all.rules
%dir /etc/qubes_rpc
/etc/qubes_rpc/qubes.Filecopy
/etc/qubes_rpc/qubes.OpenInVM
/etc/qubes_rpc/qubes.GetAppmenus
/etc/qubes_rpc/qubes.VMShell
/etc/qubes_rpc/qubes.SyncNtpClock
/etc/qubes_rpc/qubes.SuspendPre
/etc/qubes_rpc/qubes.SuspendPost
/etc/qubes_rpc/qubes.WaitForSession
/etc/sudoers.d/qubes
%config(noreplace) /etc/sysconfig/iptables
%config(noreplace) /etc/sysconfig/ip6tables
/etc/sysconfig/modules/qubes_core.modules
/etc/sysconfig/modules/qubes_misc.modules
%config(noreplace) /etc/tinyproxy/filter-qubes-yum
%config(noreplace) /etc/tinyproxy/tinyproxy-qubes-yum.conf
/etc/udev/rules.d/50-qubes_misc.rules
/etc/udev/rules.d/99-qubes_block.rules
/etc/udev/rules.d/99-qubes_network.rules
/etc/udev/rules.d/99-qubes_usb.rules
/etc/xdg/nautilus-actions/nautilus-actions.conf
/etc/xen/scripts/vif-route-qubes
%config(noreplace) /etc/yum.conf.d/qubes-proxy.conf
%config(noreplace) /etc/yum.repos.d/qubes.repo
/etc/yum/pluginconf.d/yum-qubes-hooks.conf
/etc/yum/post-actions/qubes_trigger_sync_appmenus.action
/sbin/qubes_serial_login
/usr/bin/qvm-copy-to-vm
/usr/bin/qvm-open-in-dvm
/usr/bin/qvm-open-in-vm
/usr/bin/qvm-run
/usr/bin/qvm-mru-entry
/usr/bin/xenstore-watch-qubes
%dir /usr/lib/qubes
/usr/lib/qubes/block_add_change
/usr/lib/qubes/block_cleanup
/usr/lib/qubes/block_remove
/usr/lib/qubes/usb_add_change
/usr/lib/qubes/usb_remove
/usr/lib/qubes/vusb-ctl.py*
/usr/lib/qubes/dispvm-prerun.sh
/usr/lib/qubes/sync-ntp-clock
/usr/lib/qubes/prepare-suspend
/usr/lib/qubes/meminfo-writer
/usr/lib/qubes/network-manager-prepare-conf-dir
/usr/lib/qubes/qfile-agent
%attr(4755,root,root) /usr/lib/qubes/qfile-unpacker
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
/usr/lib/qubes/wrap_in_html_if_url.sh
/usr/lib/yum-plugins/yum-qubes-hooks.py*
/usr/sbin/qubes_firewall
/usr/sbin/qubes_netwatcher
/usr/share/glib-2.0/schemas/org.gnome.settings-daemon.plugins.updates.gschema.override
/usr/share/file-manager/actions/qvm-copy-gnome.desktop
/usr/share/file-manager/actions/qvm-dvm-gnome.desktop
%dir /home_volatile
%attr(700,user,user) /home_volatile/user
%dir /mnt/removable

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
/etc/init.d/qubes-firewall
/etc/init.d/qubes-netwatcher
/etc/init.d/qubes-yum-proxy

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
chkconfig ip6tables on
chkconfig --add qubes_core || echo "WARNING: Cannot add service qubes_core!"
chkconfig qubes_core on || echo "WARNING: Cannot enable service qubes_core!"
chkconfig --add qubes_core_netvm || echo "WARNING: Cannot add service qubes_core_netvm!"
chkconfig qubes_core_netvm on || echo "WARNING: Cannot enable service qubes_core_netvm!"
chkconfig --add qubes_core_appvm || echo "WARNING: Cannot add service qubes_core_appvm!"
chkconfig qubes_core_appvm on || echo "WARNING: Cannot enable service qubes_core_appvm!"
chkconfig --add qubes-firewall || echo "WARNING: Cannot add service qubes-firewall!"
chkconfig qubes-firewall on || echo "WARNING: Cannot enable service qubes-firewall!"
chkconfig --add qubes-netwatcher || echo "WARNING: Cannot add service qubes-netwatcher!"
chkconfig qubes-netwatcher on || echo "WARNING: Cannot enable service qubes-netwatcher!"
chkconfig --add qubes-yum-proxy || echo "WARNING: Cannot add service qubes-yum-proxy!"
chkconfig qubes-yum-proxy on || echo "WARNING: Cannot enable service qubes-yum-proxy!"

# TODO: make this not display the silly message about security context...
sed -i s/^id:.:initdefault:/id:3:initdefault:/ /etc/inittab

%preun sysvinit
if [ "$1" = 0 ] ; then
    # no more packages left
    chkconfig qubes_core off
    chkconfig qubes_core_netvm off
    chkconfig qubes_core_appvm off
    chkconfig qubes-firewall off
    chkconfig qubes-netwatcher off
    chkconfig qubes-yum-proxy off
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
/lib/systemd/system/qubes-update-check.service
/lib/systemd/system/qubes-update-check.timer
/lib/systemd/system/qubes-yum-proxy.service
%dir /usr/lib/qubes/init
/usr/lib/qubes/init/prepare-dvm.sh
/usr/lib/qubes/init/network-proxy-setup.sh
/usr/lib/qubes/init/misc-post.sh
/usr/lib/qubes/init/misc-post-stop.sh
/usr/lib/qubes/init/qubes-sysinit.sh
/usr/lib/qubes/init/NetworkManager.service
/usr/lib/qubes/init/NetworkManager-wait-online.service
/usr/lib/qubes/init/cups.service
/usr/lib/qubes/init/ntpd.service
%ghost %attr(0644,root,root) /etc/systemd/system/NetworkManager.service
%ghost %attr(0644,root,root) /etc/systemd/system/NetworkManager-wait-online.service
%ghost %attr(0644,root,root) /etc/systemd/system/cups.service

%post systemd

for srv in qubes-dvm qubes-meminfo-writer qubes-qrexec-agent qubes-sysinit qubes-misc-post qubes-netwatcher qubes-network qubes-firewall qubes-yum-proxy; do
    /bin/systemctl enable $srv.service 2> /dev/null
done

/bin/systemctl enable qubes-update-check.timer 2> /dev/null

# Install overriden services only when original exists
for srv in cups NetworkManager NetworkManager-wait-online ntpd; do
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
        chkconfig $srv off 2> /dev/null
done

DISABLE_SERVICES="alsa-store alsa-restore auditd avahi avahi-daemon backuppc cpuspeed crond"
DISABLE_SERVICES="$DISABLE_SERVICES fedora-autorelabel fedora-autorelabel-mark ipmi hwclock-load hwclock-save"
DISABLE_SERVICES="$DISABLE_SERVICES mdmonitor multipathd openct rpcbind mcelog fedora-storage-init fedora-storage-init-late"
DISABLE_SERVICES="$DISABLE_SERVICES plymouth-start plymouth-read-write plymouth-quit plymouth-quit-wait"
DISABLE_SERVICES="$DISABLE_SERVICES sshd tcsd sm-client sendmail mdmonitor-takeover"
for srv in $DISABLE_SERVICES; do
    if [ -f /lib/systemd/system/$srv.service ]; then
        if fgrep -q '[Install]' /lib/systemd/system/$srv.service; then
            /bin/systemctl disable $srv.service 2> /dev/null
        else
            # forcibly disable
            ln -sf /dev/null /etc/systemd/system/$srv.service
        fi
    fi
done

rm -f /etc/systemd/system/getty.target.wants/getty@tty*.service

# Enable some services
/bin/systemctl enable iptables.service 2> /dev/null
/bin/systemctl enable ip6tables.service 2> /dev/null
/bin/systemctl enable rsyslog.service 2> /dev/null
/bin/systemctl enable ntpd.service 2> /dev/null
# Disable original service to enable overriden one
/bin/systemctl disable NetworkManager.service 2> /dev/null
# Disable D-BUS activation of NetworkManager - in AppVm it causes problems (eg PackageKit timeouts)
/bin/systemctl mask dbus-org.freedesktop.NetworkManager.service 2> /dev/null
/bin/systemctl enable NetworkManager.service 2> /dev/null

# Enable cups only when it is real SystemD service
[ -e /lib/systemd/system/cups.service ] && /bin/systemctl enable cups.service 2> /dev/null

exit 0

%postun systemd

#Do not run this part on upgrades
if [ "$1" != 0 ] ; then
    exit 0
fi

for srv in qubes-dvm qubes-meminfo-writer qubes-qrexec-agent qubes-sysinit qubes-misc-post qubes-netwatcher qubes-network; do
    /bin/systemctl disable $srv.service
do
