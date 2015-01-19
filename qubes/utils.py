#!/usr/bin/python2 -O
# vim: fileencoding=utf-8

#
# The Qubes OS Project, https://www.qubes-os.org/
#
# Copyright (C) 2010-2015  Joanna Rutkowska <joanna@invisiblethingslab.com>
# Copyright (C) 2013-2015  Marek Marczykowski-Górecki
#                              <marmarek@invisiblethingslab.com>
# Copyright (C) 2014-2015  Wojtek Porczyk <woju@invisiblethingslab.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
#

import os
import re
import subprocess


def get_timezone():
    # fc18
    if os.path.islink('/etc/localtime'):
        return '/'.join(os.readlink('/etc/localtime').split('/')[-2:])
    # <=fc17
    elif os.path.exists('/etc/sysconfig/clock'):
        clock_config = open('/etc/sysconfig/clock', "r")
        clock_config_lines = clock_config.readlines()
        clock_config.close()
        zone_re = re.compile(r'^ZONE="(.*)"')
        for line in clock_config_lines:
            line_match = zone_re.match(line)
            if line_match:
                return line_match.group(1)
    else:
        # last resort way, some applications makes /etc/localtime
        # hardlink instead of symlink...
        tz_info = os.stat('/etc/localtime')
        if not tz_info:
            return None
        if tz_info.st_nlink > 1:
            p = subprocess.Popen(['find', '/usr/share/zoneinfo',
                                   '-inum', str(tz_info.st_ino)],
                                  stdout=subprocess.PIPE)
            tz_path = p.communicate()[0].strip()
            return tz_path.replace('/usr/share/zoneinfo/', '')
    return None

