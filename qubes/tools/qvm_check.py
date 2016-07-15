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

parser = qubes.tools.QubesArgumentParser(description=__doc__, vmname_nargs='+')


def main(args=None):
    args = parser.parse_args(args)
    domains = args.domains
    if args.verbose:
        if len(domains) == 1:
            print("VM {!s} exist".format(domains[0]))
        else:
            txt = ", ".join([vm.name for vm in domains]).strip()
            msg = "VMs {!s} exist".format(txt)
            print(msg.format(txt))


if __name__ == '__main__':
    sys.exit(main())
