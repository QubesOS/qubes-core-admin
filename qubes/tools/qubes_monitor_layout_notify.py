#!/usr/bin/python2 -O
# vim: fileencoding=utf-8

#
# The Qubes OS Project, https://www.qubes-os.org/
#
# Copyright (C) 2015-2016  Joanna Rutkowska <joanna@invisiblethingslab.com>
# Copyright (C) 2015-2016  Wojtek Porczyk <woju@invisiblethingslab.com>
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

'''qvm-create - Create new Qubes OS store'''

# TODO allow to set properties and create domains

import subprocess
import threading

import qubes.ext.gui
import qubes.tools


parser = qubes.tools.QubesArgumentParser(
    description='Send monitor layout to one qube or to all of them',
    want_app=True,
    want_vm=True,
    want_vm_optional=True)


def main(args=None):
    '''Main routine of :program:`qubes-create`.

    :param list args: Optional arguments to override those delivered from \
        command line.
    '''

    args = parser.parse_args(args)
    monitor_layout = qubes.ext.gui.get_monitor_layout()

    # notify only if we've got a non-empty monitor_layout or else we
    # break proper qube resolution set by gui-agent
    if not monitor_layout:
        args.app.log.error('cannot get monitor layout')
        return 1

    subprocess.check_call(['killall', '-HUP', 'qubes-guid'])
    if args.vm:
        args.vm.fire_event('monitor-layout-change', monitor_layout)
    else:
        threads = []

        for vm in args.app.domains:
            thread = threading.Thread(name=vm.name, target=vm.fire_event,
                args=('monitor-layout-change',),
                kwargs={'monitor_layout': monitor_layout})
            threads.append(thread)
            thread.run()

        for thread in threads:
            thread.join()

    return 0
