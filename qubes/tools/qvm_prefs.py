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
# TODO indicate default values

from __future__ import print_function

import argparse
import os
import subprocess
import sys
import textwrap

import qubes
import qubes.tools
import qubes.utils
import qubes.vm


class _HelpPropertiesAction(argparse.Action):
    '''Action for argument parser that displays all properties and exits.'''
    # pylint: disable=redefined-builtin
    def __init__(self,
            option_strings,
            dest=argparse.SUPPRESS,
            default=argparse.SUPPRESS,
            help='list all available properties with short descriptions'
                ' and exit'):
        super(_HelpPropertiesAction, self).__init__(
            option_strings=option_strings,
            dest=dest,
            default=default,
            nargs=0,
            help=help)

    def __call__(self, parser, namespace, values, option_string=None):
        properties = qubes.vm.qubesvm.QubesVM.property_list()
        width = max(len(prop.__name__) for prop in properties)
        wrapper = textwrap.TextWrapper(width=80,
            initial_indent='  ', subsequent_indent=' ' * (width + 6))

        text = 'Common properties:\n' + '\n'.join(
            wrapper.fill('{name:{width}s}  {doc}'.format(
                name=prop.__name__,
                doc=qubes.utils.format_doc(prop.__doc__) if prop.__doc__ else'',
                width=width))
            for prop in sorted(properties))
        parser.exit(message=text
            + '\n\nThere may be more properties in specific domain classes.\n')


parser = qubes.tools.get_parser_base(want_force_root=True)

#parser.add_argument('--property', '--prop', '-p',
#    action=qubes.tools.PropertyAction,
#    help='set domain\'s property (may be given multiple times)')

parser.add_argument('name', metavar='VMNAME',
    help='name of the domain to change')

parser.add_argument('property', metavar='PROPERTY',
    nargs='?',
    help='name of the property to show or change')

parser.add_argument('value', metavar='VALUE',
    nargs='?',
    help='new value of the property')

parser.add_argument('--help-properties', action=_HelpPropertiesAction)


def main():
    args = parser.parse_args()
    qubes.tools.set_verbosity(parser, args)
    qubes.tools.dont_run_as_root(parser, args)

    app = qubes.Qubes(args.xml)
    try:
        domain = app.domains[args.name]
    except KeyError:
        parser.error('no such domain: {!r}'.format(args.name))

    if args.property is None:
        properties = domain.property_list()
        width = max(len(prop.__name__) for prop in properties)

        for prop in sorted(properties):
            try:
                value = getattr(domain, prop.__name__)
            except AttributeError:
                print('{name:{width}s}  U'.format(
                    name=prop.__name__, width=width))
                continue

            if domain.property_is_default(prop):
                print('{name:{width}s}  D  {value!r}'.format(
                    name=prop.__name__, width=width, value=value))
            else:
                print('{name:{width}s}  -  {value!r}'.format(
                    name=prop.__name__, width=width, value=value))

        return True


    if args.value is None:
        print(str(getattr(domain, args.property)))
        return True

    setattr(domain, args.property, args.value)
    app.save()

    return True


if __name__ == '__main__':
    sys.exit(not main())
