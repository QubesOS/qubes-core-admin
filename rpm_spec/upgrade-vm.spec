Name:		qubes-upgrade-vm
Version:	1.0
Release:	1%{?dist}
Summary:	Qubes upgrade VM package

Group:		Qubes
Vendor:		Invisible Things Lab
License:	GPL
URL:		http://www.qubes-os.org

%define _builddir %(pwd)

%description
Upgrade package for Qubes VM.

This package contains only minimal file set required to upgrade Qubes VM
template to next Qubes release.

%install
mkdir -p $RPM_BUILD_ROOT/etc/pki/rpm-gpg
install -m 644 misc/RPM-GPG-KEY-upgrade-qubes-* $RPM_BUILD_ROOT/etc/pki/rpm-gpg/

mkdir -p $RPM_BUILD_ROOT/etc/yum.repos.d
install -m 644 misc/qubes-upgrade.repo $RPM_BUILD_ROOT/etc/yum.repos.d/

%files
/etc/yum.repos.d/qubes-upgrade.repo
/etc/pki/rpm-gpg/RPM-GPG-KEY-upgrade-qubes*
