#!/usr/bin/env python2
# -*- encoding: utf8 -*-
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

''' Remove domains from the system '''

from __future__ import print_function

import sys

from qubes.tools import QubesArgumentParser

parser = QubesArgumentParser(description=__doc__,
                             want_app=True,
                             want_force_root=True,
                             vmname_nargs='+')
parser.add_argument('--just-db',
                    action='store_true',
                    help='Remove only from db, don\'t remove files')


def main(args=None):  # pylint: disable=missing-docstring
    args = parser.parse_args(args)
    for vm in args.domains:
        del args.app.domains[vm.qid]
        args.app.save()
        if not args.just_db:
            vm.remove_from_disk()

    return 0


if __name__ == '__main__':
    sys.exit(main())
