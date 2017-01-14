#
# The Qubes OS Project, https://www.qubes-os.org/
#
# Copyright (C) 2010-2016  Joanna Rutkowska <joanna@invisiblethingslab.com>
# Copyright (C) 2016       Wojtek Porczyk <woju@invisiblethingslab.com>
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

'''qvm-features - Manage domain's features'''

from __future__ import print_function

import argparse
import sys

import qubes

parser = qubes.tools.QubesArgumentParser(
    vmname_nargs=1,
    description='manage domain\'s features')

parser.add_argument('--request',
    action='store_true', default=False,
    help=argparse.SUPPRESS)

parser.add_argument('feature', metavar='FEATURE',
    action='store', nargs='?',
    help='name of the feature')

parser.add_argument('value', metavar='VALUE',
    action='store', nargs='?',
    help='new value of the feature')

parser.add_argument('--unset', '--default', '--delete', '-D',
    dest='delete',
    action='store_true',
    help='unset the feature')


def main(args=None):
    '''Main routine of :program:`qvm-features`.

    :param list args: Optional arguments to override those delivered from \
        command line.
    '''

    args = parser.parse_args(args)
    vm = args.domains[0]

    if args.request:
        # Request mode: instead of setting the features directly,
        # let the extensions handle them first.
        vm.fire_event('feature-request', untrusted_features=args.features)
        return 0

    if args.feature is None:
        if args.delete:
            parser.error('--unset requires a feature')

        width = max(len(feature) for feature in vm.features)
        for feature in sorted(vm.features):
            print('{name:{width}s}  {value}'.format(
                name=feature, value=vm.features[feature], width=width))

        return 0

    if args.delete:
        if args.value is not None:
            parser.error('cannot both set and unset a value')
        try:
            del vm.features[args.feature]
            args.app.save()
        except KeyError:
            pass
        return 0

    if args.value is None:
        try:
            print(vm.features[args.feature])
            return 0
        except KeyError:
            return 1

    vm.features[args.feature] = args.value
    args.app.save()
    return 0


if __name__ == '__main__':
    sys.exit(main())
