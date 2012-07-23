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
#  choose the oldest Qubes-supported VM kernel
Provides:   kernel = 3.2.7

%description
Placeholder for kernel package as it is managed by Dom0.

%files
