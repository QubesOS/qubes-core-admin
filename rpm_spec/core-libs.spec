#
# The Qubes OS Project, http://www.qubes-os.org
#
# Copyright (C) 2010  Joanna Rutkowska <joanna@invisiblethingslab.com>
# Copyright (C) 2010  Rafal Wojtczuk  <rafal@invisiblethingslab.com>
# Copyright (C) 2012  Marek Marczykowski <marmarek@invisiblethingslab.com>
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

%{!?version: %define version %(cat version_libs)}

Name:		qubes-core-libs
Version:	%{version}
Release:	1%{dist}

Summary:	Qubes core libraries
License:	GPL v2 only
Group:		Development/Sources 
Group:		Qubes
Vendor:		Invisible Things Lab
URL:		http://www.qubes-os.org
Obsoletes:	qubes-core-appvm-libs
Obsoletes:	qubes-core-vm-libs
BuildRequires: xen-devel

%define _builddir %(pwd)

%description
The Qubes core libraries for installation inside a Qubes Dom0 and VM.

%prep
# we operate on the current directory, so no need to unpack anything
# symlink is to generate useful debuginfo packages
rm -f %{name}-%{version}
ln -sf . %{name}-%{version}
%setup -T -D

%build
(cd u2mfn; make)
(cd vchan; make -f Makefile.linux)

%install
install -D -m 0644 vchan/libvchan.h $RPM_BUILD_ROOT/usr/include/libvchan.h
install -D -m 0644 u2mfn/u2mfnlib.h $RPM_BUILD_ROOT/usr/include/u2mfnlib.h
install -D -m 0644 u2mfn/u2mfn-kernel.h $RPM_BUILD_ROOT/usr/include/u2mfn-kernel.h

install -D vchan/libvchan.so $RPM_BUILD_ROOT/%{_libdir}/libvchan.so
install -D u2mfn/libu2mfn.so $RPM_BUILD_ROOT/%{_libdir}/libu2mfn.so

%clean
rm -rf $RPM_BUILD_ROOT
rm -f %{name}-%{version}

%files
%{_libdir}/libvchan.so
%{_libdir}/libu2mfn.so

%package devel
Summary:        Include files for qubes core libraries
License:        GPL v2 only
Group:          Development/Sources 
Obsoletes:      qubes-core-appvm-devel
Obsoletes:      qubes-core-vm-devel

%description devel

%files devel
/usr/include/libvchan.h
/usr/include/u2mfnlib.h
/usr/include/u2mfn-kernel.h
