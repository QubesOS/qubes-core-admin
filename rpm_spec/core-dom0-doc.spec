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

%{!?version: %define version %(cat version)}


Name:		qubes-core-dom0-doc
Version:	%{version}
Release:	1
Summary:	The Qubes docs for dom0 tools

Group:		Qubes
Vendor:		Invisible Things Lab
License:	GPL
URL:		http://www.qubes-os.org
BuildRequires: python3-sphinx
BuildRequires: python3-lxml
BuildArch: noarch
Obsoletes:	qubes-doc-dom0 <= 2.0
Provides:	qubes-doc-dom0

%define _builddir %(pwd)/doc

%description
The Qubes docs for dom0 tools

%build
make PYTHON=%{__python3} SPHINXBUILD=sphinx-build-%{python3_version} man

%install

make DESTDIR=$RPM_BUILD_ROOT \
    PYTHON=%{__python3} SPHINXBUILD=sphinx-build-%{python3_version} \
    install

%clean
rm -rf $RPM_BUILD_ROOT

%files
%defattr(-,root,root,-)
%{_mandir}/man1/qubes*.1*
