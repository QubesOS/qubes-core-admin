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

# TODO list properties for all classes
# TODO list only non-default properties

from __future__ import print_function

import sys

import qubes
import qubes.tools
import qubes.utils
import qubes.vm


parser = qubes.tools.QubesArgumentParser(
    want_force_root=True,
    vmname_nargs=1)

parser.add_argument('--help-properties',
    action=qubes.tools.HelpPropertiesAction,
    klass=qubes.vm.qubesvm.QubesVM)

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
    args.domain = args.domains.pop()

    if args.property is None:
        properties = args.domain.property_list()
        width = max(len(prop.__name__) for prop in properties)

        for prop in sorted(properties):
            try:
                value = getattr(args.domain, prop.__name__)
            except AttributeError:
                print('{name:{width}s}  U'.format(
                    name=prop.__name__, width=width))
                continue

            if args.domain.property_is_default(prop):
                print('{name:{width}s}  D  {value!s}'.format(
                    name=prop.__name__, width=width, value=value))
            else:
                print('{name:{width}s}  -  {value!s}'.format(
                    name=prop.__name__, width=width, value=value))

        return 0

    if args.property not in [prop.__name__
                             for prop in args.domain.property_list()]:
        parser.error('no such property: {!r}'.format(args.property))

    if args.value is not None:
        setattr(args.domain, args.property, args.value)
        args.app.save()
        return 0

    if args.delete:
        delattr(args.domain, args.property)
        args.app.save()
        return 0

    print(str(getattr(args.domain, args.property)))

    return 0


if __name__ == '__main__':
    sys.exit(main())
