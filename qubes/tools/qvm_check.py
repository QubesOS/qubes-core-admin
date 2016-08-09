#!/usr/bin/python2
# -*- encoding: utf8 -*-
# :pylint: disable=too-few-public-methods
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
''' Exits sucessfull if the provided domains exists, else returns failure '''

from __future__ import print_function

import sys

import qubes.tools
import qubes.vm.templatevm

parser = qubes.tools.QubesArgumentParser(description=__doc__, vmname_nargs='+')
parser.add_argument("--running", action="store_true", dest="running",
    default=False, help="Determine if (any of given) VM is running")
parser.add_argument("--paused", action="store_true", dest="paused",
    default=False, help="Determine if (any of given) VM is paused")
parser.add_argument("--template", action="store_true", dest="template",
    default=False, help="Determine if (any of given) VM is a template")


def print_msg(domains, what_single, what_plural):
    if len(domains) == 0:
        print("None of given VM {!s}".format(what_single))
    if len(domains) == 1:
        print("VM {!s} {!s}".format(domains[0], what_single))
    else:
        txt = ", ".join([vm.name for vm in domains])
        print("VMs {!s} {!s}".format(txt, what_plural))


def main(args=None):
    args = parser.parse_args(args)
    domains = args.domains
    if args.running:
        running = [vm for vm in domains if vm.is_running()]
        if args.verbose:
            print_msg(running, "is running", "are running")
        return 0 if running else 1
    elif args.paused:
        paused = [vm for vm in domains if vm.is_paused()]
        if args.verbose:
            print_msg(paused, "is paused", "are running")
        return 0 if paused else 1
    elif args.template:
        template = [vm for vm in domains if isinstance(vm,
            qubes.vm.templatevm.TemplateVM)]
        if args.verbose:
            print_msg(template, "is a template", "are templates")
        return 0 if template else 1
    else:
        if args.verbose:
            print_msg(domains, "exists", "exist")
        return 0 if domains else 1

if __name__ == '__main__':
    sys.exit(main())
