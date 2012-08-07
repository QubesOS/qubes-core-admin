# We don't install kernel pkg in VM, but some other pkgs depends on it.
# Done as separate subpackage because yum allows multiple versions of kernel
# pkg installed simultaneusly - and of course we don't want multiple versions
# of qubes-core-vm
Name:       qubes-core-vm-kernel-placeholder
Summary:    Placeholder for kernel package as it is managed by Dom0
Version:	1.0
Release:	1%{dist}
Vendor:		Invisible Things Lab
License:	GPL
Group:		Qubes
URL:		http://www.qubes-os.org
#  template released with 1.0-rc1 have kernel-debug installed by mistake. This
#  line is required to smooth upgrade.
Obsoletes:  kernel-debug
#  this driver require exact kernel-drm-nouveau version; as isn't needed in VM,
#  just remove it
Obsoletes:  xorg-x11-drv-nouveau
#  choose the oldest Qubes-supported VM kernel
Provides:   kernel = 3.2.7

%description
Placeholder for kernel package as it is managed by Dom0.

%files
