#!/usr/bin/python2
# vim: fileencoding=utf8
#
# The Qubes OS Project, http://www.qubes-os.org
#
# Copyright (C) 2010-2016  Joanna Rutkowska <joanna@invisiblethingslab.com>
# Copyright (C) 2011-2016  Marek Marczykowski-Górecki
#                                              <marmarek@invisiblethingslab.com>
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

from __future__ import print_function

import sys
import time

import qubes.config
import qubes.tools

parser = qubes.tools.QubesArgumentParser(
    description='gracefully shut down a qube', vmname_nargs='+')

parser.add_argument('--force',
    action='store_true', default=False,
    help='force operation, even if may damage other VMs (eg. shutdown of'
        ' network provider)')

parser.add_argument('--wait',
    action='store_true', default=False,
    help='wait for the VMs to shut down')

parser.add_argument('--timeout',
    action='store', type=float,
    default=qubes.config.defaults['shutdown_counter_max'],
    help='timeout after which domains are killed when using --wait'
        ' (default: %d)')


def main(args=None):
    args = parser.parse_args(args)

    for vm in args.domains:
        vm.shutdown(force=args.force)

    if not args.wait:
        return

    timeout = args.timeout
    current_vms = list(sorted(args.domains))
    while timeout >= 0:
        current_vms = [vm for vm in current_vms
            if vm.get_power_state() != 'Halted']
        args.app.log.info('Waiting for shutdown ({}): {}'.format(
            timeout, ', '.join(map(str, current_vms))))
        time.sleep(1)
        timeout -= 1

    args.app.log.notice(
        'Killing remaining qubes: {}'.format(', '.join(map(str, current_vms))))
    for vm in current_vms:
        vm.force_shutdown()


if __name__ == '__main__':
    sys.exit(main())
