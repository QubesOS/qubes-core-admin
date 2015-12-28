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

# TODO list available classes
# TODO list labels (maybe in qvm-prefs)
# TODO services, devices, tags

from __future__ import print_function

import argparse
import os
import subprocess
import sys

import qubes
import qubes.tools


parser = qubes.tools.QubesArgumentParser(want_force_root=True)

parser.add_argument('--class', '-C', dest='cls',
    default='AppVM',
    help='specify the class of the new domain (default: %(default)s)')

parser.add_argument('--property', '--prop', '-p',
    action=qubes.tools.PropertyAction,
    help='set domain\'s property, like "internal", "memory" or "vcpus"')

parser.add_argument('--template', '-t',
    action=qubes.tools.SinglePropertyAction,
    help='specify the TemplateVM to use')

parser.add_argument('--label', '-l',
    action=qubes.tools.SinglePropertyAction,
    help='specify the label to use for the new domain'
        ' (e.g. red, yellow, green, ...)')

parser_root = parser.add_mutually_exclusive_group()
parser_root.add_argument('--root-copy-from', '-r', metavar='FILENAME',
    help='use provided root.img instead of default/empty one'
        ' (file will be COPIED)')
parser_root.add_argument('--root-move-from', '-R', metavar='FILENAME',
    help='use provided root.img instead of default/empty one'
        ' (file will be MOVED)')
parser_root.add_argument('--no-root',
    action='store_true', default=False,
    help=argparse.SUPPRESS)

parser.add_argument('name', metavar='VMNAME',
    action=qubes.tools.SinglePropertyAction,
    nargs='?',
    help='name of the domain to create')


def main(args=None):
    args = parser.parse_args(args)

    if 'label' not in args.properties:
        parser.error('--label option is mandatory')

    if 'name' not in args.properties:
        parser.error('VMNAME is mandatory')

    try:
        args.app.get_label(args.properties['label'])
    except KeyError:
        parser.error('no such label: {!r}; available: {}'.format(
            args.properties['label'],
            ', '.join(repr(l.name) for l in args.app.labels)))

    try:
        cls = qubes.vm.BaseVM.register[args.cls] # pylint: disable=no-member
    except KeyError:
        parser.error('no such domain class: {!r}'.format(args.cls))

    if 'template' in args.properties and \
            'template' not in (prop.__name__ for prop in cls.property_list()):
        parser.error('this domain class does not support template')

    vm = args.app.add_new_vm(cls, **args.properties)

    # pylint: disable=line-too-long

#   if not options.standalone and any([options.root_copy_from, options.root_move_from]):
#       print >> sys.stderr, "root.img can be specified only for standalone VMs"
#       exit (1)

#   if options.hvm_template and options.template is not None:
#       print >> sys.stderr, "Template VM cannot be based on another template"
#       exit (1)

#   if options.root_copy_from is not None and not os.path.exists(options.root_copy_from):
#       print >> sys.stderr, "File specified as root.img does not exists"
#       exit (1)

#   if options.root_move_from is not None and not os.path.exists(options.root_move_from):
#       print >> sys.stderr, "File specified as root.img does not exists"
#       exit (1)

#   elif not options.hvm and not options.hvm_template:
#       if qvm_collection.get_default_template() is None:
#           print >> sys.stderr, "No default TemplateVM defined!"
#           exit (1)
#       else:
#           template = qvm_collection.get_default_template()
#           if (options.verbose):
#               print('--> Using default TemplateVM: {0}'.format(template.name))

    if not args.no_root:
        try:
            vm.create_on_disk()

            if args.root_move_from is not None:
#               if (options.verbose):
#                   print "--> Replacing root.img with provided file"
                os.unlink(vm.root_img)
                os.rename(args.root_move_from, vm.root_img)
            elif args.root_copy_from is not None:
#               if (options.verbose):
#                   print "--> Replacing root.img with provided file"
                os.unlink(vm.root_img)
                # use 'cp' to preserve sparse file
                subprocess.check_call(['cp', args.root_copy_from, vm.root_img])

        except (IOError, OSError) as err:
            parser.error(str(err))

    args.app.save()

    return 0


if __name__ == '__main__':
    sys.exit(main())
