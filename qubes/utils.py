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

import hashlib
import os
import re
import subprocess

import docutils
import docutils.core
import docutils.io

import qubes.exc


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
                '-inum', str(tz_info.st_ino), '-print', '-quit'],
                stdout=subprocess.PIPE)
            tz_path = p.communicate()[0].strip()
            return tz_path.replace('/usr/share/zoneinfo/', '')
    return None


def format_doc(docstring):
    '''Return parsed documentation string, stripping RST markup.
    '''

    if not docstring:
        return ''

    # pylint: disable=unused-variable
    output, pub = docutils.core.publish_programmatically(
        source_class=docutils.io.StringInput,
        source=' '.join(docstring.strip().split()),
        source_path=None,
        destination_class=docutils.io.NullOutput, destination=None,
        destination_path=None,
        reader=None, reader_name='standalone',
        parser=None, parser_name='restructuredtext',
        writer=None, writer_name='null',
        settings=None, settings_spec=None, settings_overrides=None,
        config_section=None, enable_exit_status=None)
    return pub.writer.document.astext()

# FIXME those are wrong, k/M/G are SI prefixes and means 10**3
# maybe adapt https://code.activestate.com/recipes/578019
def parse_size(size):
    units = [
        ('K', 1000), ('KB', 1000),
        ('M', 1000 * 1000), ('MB', 1000 * 1000),
        ('G', 1000 * 1000 * 1000), ('GB', 1000 * 1000 * 1000),
        ('Ki', 1024), ('KiB', 1024),
        ('Mi', 1024 * 1024), ('MiB', 1024 * 1024),
        ('Gi', 1024 * 1024 * 1024), ('GiB', 1024 * 1024 * 1024),
    ]

    size = size.strip().upper()
    if size.isdigit():
        return int(size)

    for unit, multiplier in units:
        if size.endswith(unit):
            size = size[:-len(unit)].strip()
            return int(size) * multiplier

    raise qubes.exc.QubesException("Invalid size: {0}.".format(size))

def mbytes_to_kmg(size):
    if size > 1024:
        return "%d GiB" % (size / 1024)
    else:
        return "%d MiB" % size


def kbytes_to_kmg(size):
    if size > 1024:
        return mbytes_to_kmg(size / 1024)
    else:
        return "%d KiB" % size


def bytes_to_kmg(size):
    if size > 1024:
        return kbytes_to_kmg(size / 1024)
    else:
        return "%d B" % size


def size_to_human(size):
    """Humane readable size, with 1/10 precision"""
    if size < 1024:
        return str(size)
    elif size < 1024 * 1024:
        return str(round(size / 1024.0, 1)) + ' KiB'
    elif size < 1024 * 1024 * 1024:
        return str(round(size / (1024.0 * 1024), 1)) + ' MiB'
    else:
        return str(round(size / (1024.0 * 1024 * 1024), 1)) + ' GiB'


def urandom(size):
    rand = os.urandom(size)
    if rand is None:
        raise IOError('failed to read urandom')
    return hashlib.sha512(rand).digest()
