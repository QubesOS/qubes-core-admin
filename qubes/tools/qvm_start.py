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
import qubes

class DriveAction(argparse.Action):
    '''Action for argument parser that stores drive image path.'''
    # pylint: disable=redefined-builtin
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
        setattr(namespace, self.dest, prefix + value)


parser = qubes.tools.get_parser_base(description='start a domain')


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
    help='temporarily ttach Windows tools CDROM to the domain')


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
    help='do actions necessary when preparing DVM image')

#parser.add_option ("--no-guid", action="store_true", dest="noguid", default=False,
#            help="Do not start the GUId (ignored)")
#parser.add_option ("--tray", action="store_true", dest="tray", default=False,
#                   help="Use tray notifications instead of stdout" )

parser.add_argument('name', metavar='VMNAME',
    help='domain to start')

parser.set_defaults(drive=None)

def main(args=None):
    '''Main routine of :program:`qvm-start`.

    :param list args: Optional arguments to override those delivered from \
        command line.
    '''

    args = parser.parse_args(args)
    qubes.tools.set_verbosity(parser, args)
    app = qubes.Qubes(args.xml)

#   if options.tray:
#       tray_notify_init()

    try:
        vm = app.domains[args.name]
    except KeyError:
        parser.error('no such domain: {!r}'.format(args.name))

    if args.drive is not None:
        if 'drive' not in (prop.__name__ for prop in vm.property_list()):
            parser.error(
                'domain {!r} does not support attaching drives'.format(vm.name))

    if args.conf_file is not None:
        vm.conf_file = args.conf_file

    if args.debug:
        vm.debug = args.debug

    try:
        vm.verify_files()
    except (IOError, OSError) as e:
        parser.error(
            'error verifying files for domain {!r}: {!r}'.format(vm.name, e))

    try:
        xid = vm.start(
            preparing_dvm=args.preparing_dvm,
            start_guid=args.start_guid)
            # notify_function=
    except MemoryError:
        # TODO tray
        parser.error('not enough memory to start domain {!r}'.format(vm.name))
    except qubes.QubesException as e:
        parser.error('Qubes error: {!r}'.format(e))

    return True


if __name__ == '__main__':
    sys.exit(not main())
