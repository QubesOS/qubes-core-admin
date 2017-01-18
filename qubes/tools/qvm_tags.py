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

'''qvm-features - Manage domain's tags'''

from __future__ import print_function

import sys

import qubes



parser = qubes.tools.QubesArgumentParser(
    vmname_nargs=1,
    description='manage domain\'s tags')


mode = parser.add_mutually_exclusive_group()

def mode_query(args):
    if args.tag is None:
        # list
        print('\n'.join(sorted(args.vm.tags)))
    else:
        # real query; logic is inverted, because this is exit code
        return int(args.tag not in args.vm.tags)
mode.add_argument('--query',
    dest='mode',
    action='store_const',
    const=mode_query,
    help='query for the tag; if no tag specified, list all tags;'
        ' this is the default')

def mode_set(args):
    if args.tag is None:
        parser.error('tag is mandatory for --set')
    args.vm.tags.add(args.tag)
    args.app.save()
mode.add_argument('--set', '-s',
    dest='mode',
    action='store_const',
    const=mode_set,
    help='set the tag; if tag is already set, do nothing')

def mode_unset(args):
    if args.tag is None:
        parser.error('tag is mandatory for --unset')
    args.vm.tags.discard(args.tag)
    args.app.save()
mode.add_argument('--unset', '--delete', '-D',
    dest='mode',
    action='store_const',
    const=mode_unset,
    help='unset the tag; if tag is not set, do nothing')


parser.add_argument('tag', metavar='TAG',
    action='store', nargs='?',
    help='name of the tag')

parser.set_defaults(mode=mode_query)


def main(args=None):
    '''Main routine of :program:`qvm-tags`.

    :param list args: Optional arguments to override those delivered from \
        command line.
    '''

    args = parser.parse_args(args)
    return args.mode(args)


if __name__ == '__main__':
    sys.exit(main())
