#!/bin/sh
#
# The Qubes OS Project, http://www.qubes-os.org
#
# Copyright (C) 2010  Joanna Rutkowska <joanna@invisiblethingslab.com>
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

SRCDIR=$1
VMNAME=$2
VMDIR=/var/lib/qubes/appvms/$VMNAME
APPSDIR=$VMDIR/apps

if [ $# != 2 ]; then
    echo "usage: $0 <apps_templates_dir> <vmname>"
    exit
fi
mkdir -p $APPSDIR

echo "--> Converting Appmenu Templates..."
find $SRCDIR -name "*.desktop" -exec /usr/lib/qubes/convert_apptemplate2vm.sh {} $APPSDIR $VMNAME $VMDIR \;

/usr/lib/qubes/convert_dirtemplate2vm.sh $SRCDIR/qubes-vm.directory.template $APPSDIR/$VMNAME-vm.directory $VMNAME $VMDIR

echo "--> Adding Apps to the Menu..."
xdg-desktop-menu install $APPSDIR/*.directory $APPSDIR/*.desktop

