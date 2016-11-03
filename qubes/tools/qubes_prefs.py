#!/usr/bin/python2
# -*- encoding: utf8 -*-
#
# The Qubes OS Project, http://www.qubes-os.org
#
# Copyright (C) 2010-2015  Joanna Rutkowska <joanna@invisiblethingslab.com>
# Copyright (C) 2015       Wojtek Porczyk <woju@invisiblethingslab.com>
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

# TODO merge printing with qvm-prefs
# TODO list only non-default properties

from __future__ import print_function

import argparse
import sys

import qubes
import qubes.tools
import qubes.utils


parser = qubes.tools.QubesArgumentParser()

# keep it here for compatibility with earlier and possibly future versions
parser.add_argument('--force-root',
    action='store_true', help=argparse.SUPPRESS)

parser.add_argument('--help-properties',
    action=qubes.tools.HelpPropertiesAction)

parser.add_argument('--get', '-g',
    action='store_true',
    help='Ignored; for compatibility with older scripts.')

parser.add_argument('--set', '-s',
    action='store_true',
    help='Ignored; for compatibility with older scripts.')

parser.add_argument('property', metavar='PROPERTY',
    nargs='?',
    help='name of the property to show or change')

parser_value = parser.add_mutually_exclusive_group()

parser_value.add_argument('value', metavar='VALUE',
    nargs='?',
    help='new value of the property')

parser.add_argument('--unset', '--default', '--delete', '-D',
    dest='delete',
    action='store_true',
    help='unset the property; if property has default value, it will be used'
        ' instead')


def main(args=None):
    args = parser.parse_args(args)

    if args.property is None:
        properties = args.app.property_list()
        width = max(len(prop.__name__) for prop in properties)

        for prop in sorted(properties):
            try:
                value = getattr(args.app, prop.__name__)
            except AttributeError:
                print('{name:{width}s}  U'.format(
                    name=prop.__name__, width=width))
                continue

            if args.app.property_is_default(prop):
                print('{name:{width}s}  D  {value!s}'.format(
                    name=prop.__name__, width=width, value=value))
            else:
                print('{name:{width}s}  -  {value!s}'.format(
                    name=prop.__name__, width=width, value=value))

        return 0
    else:
        args.property = args.property.replace('-', '_')


    if args.value is not None:
        setattr(args.app, args.property, args.value)
        args.app.save()
        return 0

    if args.delete:
        delattr(args.app, args.property)
        args.app.save()
        return 0


    print(str(getattr(args.app, args.property)))

    return 0


if __name__ == '__main__':
    sys.exit(main())
