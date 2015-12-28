#!/usr/bin/python2 -O
# vim: fileencoding=utf-8

#
# The Qubes OS Project, https://www.qubes-os.org/
#
# Copyright (C) 2015  Joanna Rutkowska <joanna@invisiblethingslab.com>
# Copyright (C) 2015  Wojtek Porczyk <woju@invisiblethingslab.com>
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

'''qvm-kill - forceful shutdown'''


import sys
import qubes.exc
import qubes.tools

parser = qubes.tools.QubesArgumentParser(
    description='forceful shutdown of a domain',
    want_vm=True)


def main(args=None):
    '''Main routine of :program:`qvm-kill`.

    :param list args: Optional arguments to override those delivered from \
        command line.
    '''

    args = parser.parse_args(args)

    try:
        args.vm.force_shutdown()
    except (IOError, OSError, qubes.exc.QubesException) as e:
        parser.error_runtime(str(e))

    return 0


if __name__ == '__main__':
    sys.exit(main())
