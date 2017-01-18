#
# The Qubes OS Project, http://www.qubes-os.org
#
# Copyright (C) 2016 Bahtiar `kalkin-` Gadimov <bahtiar@gadimov.de>
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

''' Clone a domain '''

import sys

from qubes.tools import QubesArgumentParser, SinglePropertyAction

parser = QubesArgumentParser(description=__doc__, vmname_nargs=1)
parser.add_argument('new_name',
                    metavar='NEWVM',
                    action=SinglePropertyAction,
                    help='name of the domain to create')

group = parser.add_mutually_exclusive_group()
group.add_argument('-P',
                    metavar='POOL',
                    dest='one_pool',
                    default='',
                    help='pool to use for the new domain')

group.add_argument('-p',
                    '--pool',
                    action='append',
                    metavar='POOL:VOLUME',
                    help='specify the pool to use for the specific volume')


def main(args=None):
    ''' Clones an existing VM by copying all its disk files '''
    args = parser.parse_args(args)
    app = args.app
    src_vm = args.domains[0]
    new_name = args.properties['new_name']
    dst_vm = app.add_new_vm(src_vm.__class__, name=new_name)
    dst_vm.clone_properties(src_vm)

    if args.one_pool:
        dst_vm.clone_disk_files(src_vm, pool=args.one_pool)
    elif hasattr(args, 'pools') and args.pools:
        dst_vm.clone_disk_files(src_vm, pools=args.pools)
    else:
        dst_vm.clone_disk_files(src_vm)

#   try:
    app.save()  # HACK remove_from_disk on exception hangs for some reason
#   except Exception as e:  # pylint: disable=broad-except
#       dst_vm.remove_from_disk()
#       parser.print_error(e)
#   return 0

if __name__ == '__main__':
    sys.exit(main())
