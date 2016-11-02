#!/usr/bin/python2 -O
# vim: fileencoding=utf-8

#
# The Qubes OS Project, https://www.qubes-os.org/
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
'''qvm-start - Start a domain'''

# TODO notification in tray

import argparse
import os
import sys

import qubes


class DriveAction(argparse.Action):
    '''Action for argument parser that stores drive image path.'''

    # pylint: disable=redefined-builtin,too-few-public-methods
    def __init__(self,
            option_strings,
            dest='drive',
            prefix='cdrom:',
            metavar='IMAGE',
            required=False,
            help='Attach drive'):
        super(DriveAction, self).__init__(option_strings, dest,
            metavar=metavar, help=help)
        self.prefix = prefix

    def __call__(self, parser, namespace, values, option_string=None):
        # pylint: disable=redefined-outer-name
        setattr(namespace, self.dest, self.prefix + values)


parser = qubes.tools.QubesArgumentParser(vmname_nargs=1,
                                         description='start a domain')

parser_drive = parser.add_mutually_exclusive_group()

parser_drive.add_argument('--drive', metavar='DRIVE',
    help='temporarily attach specified drive as CD/DVD or hard disk (can be'
        ' specified with prefix "hd:" or "cdrom:", default is cdrom)')

parser_drive.add_argument('--hddisk',
    action=DriveAction, prefix='hd:',
    help='temporarily attach specified drive as hard disk')

parser_drive.add_argument('--cdrom', metavar='IMAGE',
    action=DriveAction, prefix='cdrom:',
    help='temporarily attach specified drive as CD/DVD')

parser_drive.add_argument('--install-windows-tools',
    action='store_const', dest='drive', default=False,
    const='cdrom:dom0:/usr/lib/qubes/qubes-windows-tools.iso',
    help='temporarily attach Windows tools CDROM to the domain')


parser.add_argument('--conf-file', metavar='FILE',
    help='use custom libvirt config instead of Qubes-generated one')

parser.add_argument('--debug',
    action='store_true', default=False,
    help='enable debug mode for this domain (until its shutdown)')

parser.add_argument('--preparing-dvm',
    action='store_true', default=False,
    help='do actions necessary when preparing DVM image')

parser.add_argument('--no-start-guid',
    action='store_false', dest='start_guid', default=True,
    help='do not start the gui daemon')

parser.add_argument('--no-guid',
    action='store_false', dest='start_guid',
    help='same as --no-start-guid')

parser.add_argument('--skip-if-running',
    action='store_true', default=False,
    help='Do not fail if the qube is already runnning')

#parser.add_option ("--tray", action="store_true", dest="tray", default=False,
#                   help="Use tray notifications instead of stdout" )

parser.set_defaults(drive=None)


def main(args=None):
    '''Main routine of :program:`qvm-start`.

    :param list args: Optional arguments to override those delivered from \
        command line.
    '''

    args = parser.parse_args(args)

#   if options.tray:
#       tray_notify_init()

    vm = args.domains[0]

    if args.skip_if_running and vm.is_running():
        return

    if args.drive is not None:
        if 'drive' not in (prop.__name__ for prop in vm.property_list()):
            parser.error(
                'domain {!r} does not support attaching drives'.format(vm.name))
    else:
        if args.drive == 'cdrom:dom0:/usr/lib/qubes/qubes-windows-tools.iso':
            path = args.drive.split(':', 2)[2]
            if not os.path.exists(path):
                parser.error('qubes-windows-tools package not installed')

    if args.conf_file is not None:
        vm.conf_file = args.conf_file

    if args.debug:
        vm.debug = args.debug

    if args.debug:
        vm.start(
            preparing_dvm=args.preparing_dvm,
            start_guid=args.start_guid)
    else:
        try:
            vm.start(
                preparing_dvm=args.preparing_dvm,
                start_guid=args.start_guid)
        except qubes.exc.QubesException as e:
            parser.error_runtime('Qubes error: {!r}'.format(e))
    return 0


if __name__ == '__main__':
    sys.exit(main())
