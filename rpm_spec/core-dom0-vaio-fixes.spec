%{!?version: %define version %(cat version_vaio_fixes)}

Name:		qubes-core-dom0-vaio-fixes
Version:	%{version}
Release:	1%{?dist}
Summary:    Additional scripts for supporting suspend on Vaio Z laptops
Requires:   alsa-utils

Group:		Qubes
Vendor:		Invisible Things Lab
License:	GPL
URL:		http://www.qubes-os.org

%define _builddir %(pwd)/dom0

%description
Additional scripts for supporting suspend on Vaio Z laptops.

Due to broken Linux GPU drivers we need to do some additional actions during
suspend/resume.

%install
mkdir -p $RPM_BUILD_ROOT/usr/lib64/pm-utils/sleep.d
cp vaio_fixes/00sony-vaio-audio $RPM_BUILD_ROOT/usr/lib64/pm-utils/sleep.d/
cp vaio_fixes/99sony-vaio-audio $RPM_BUILD_ROOT/usr/lib64/pm-utils/sleep.d/
cp vaio_fixes/01sony-vaio-display $RPM_BUILD_ROOT/usr/lib64/pm-utils/sleep.d/
mkdir -p $RPM_BUILD_ROOT/etc/modprobe.d/
cp vaio_fixes/snd-hda-intel-sony-vaio.conf $RPM_BUILD_ROOT/etc/modprobe.d/

%post
grubby --update-kernel=/boot/vmlinuz-2.6.34.1-14.xenlinux.qubes.x86_64 --args="i8042.nopnp=1"

%triggerin -- kernel
grubby --update-kernel=/boot/vmlinuz-2.6.34.1-14.xenlinux.qubes.x86_64 --args="i8042.nopnp=1"

%postun
if [ "$1" = 0 ] ; then
	# no more packages left
    grubby --update-kernel=/boot/vmlinuz-2.6.34.1-14.xenlinux.qubes.x86_64 --remove-args="i8042.nopnp=1"
fi

%files
/usr/lib64/pm-utils/sleep.d/00sony-vaio-audio
/usr/lib64/pm-utils/sleep.d/99sony-vaio-audio
/usr/lib64/pm-utils/sleep.d/01sony-vaio-display
/etc/modprobe.d/snd-hda-intel-sony-vaio.conf
