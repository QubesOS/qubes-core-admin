#!/usr/bin/env python
# vim: fileencoding=utf-8

#
# The Qubes OS Project, https://www.qubes-os.org/
#
# Copyright (C) 2010-2016  Joanna Rutkowska <joanna@invisiblethingslab.com>
# Copyright (C) 2013-2016  Marek Marczykowski-Górecki
#                              <marmarek@invisiblethingslab.com>
# Copyright (C) 2014-2016  Wojtek Porczyk <woju@invisiblethingslab.com>
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

import os
import subprocess

import qubes.config
import qubes.ext

class GUI(qubes.ext.Extension):
    @qubes.ext.handler('domain-start', 'domain-cmd-pre-start')
    def start_guid(self, vm, start_guid, preparing_dvm=False,
            extra_guid_args=None, **kwargs):
        '''Launch gui daemon.

        GUI daemon securely displays windows from domain.
        ''' # pylint: disable=no-self-use,unused-argument

        if not start_guid or preparing_dvm \
                or not os.path.exists('/var/run/shm.id'):
            return

        if not vm.features.check_with_template('gui', not vm.hvm):
            vm.log.debug('Not starting gui daemon, disabled by features')
            return

        if not os.getenv('DISPLAY'):
            vm.log.error('Not starting gui daemon, no DISPLAY set')
            return

        vm.log.info('Starting gui daemon')

        guid_cmd = [qubes.config.system_path['qubes_guid_path'],
            '-d', str(vm.xid), '-N', vm.name,
            '-c', vm.label.color,
            '-i', vm.label.icon_path,
            '-l', str(vm.label.index)]
        if extra_guid_args is not None:
            guid_cmd += extra_guid_args

        if vm.debug:
            guid_cmd += ['-v', '-v']

#       elif not verbose:
        else:
            guid_cmd += ['-q']

        retcode = subprocess.call(guid_cmd)
        if retcode != 0:
            raise qubes.exc.QubesVMError(vm,
                'Cannot start qubes-guid for domain {!r}'.format(vm.name))

        vm.notify_monitor_layout()
        vm.wait_for_session()


    @qubes.ext.handler('monitor-layout-change')
    def on_monitor_layout_change(self, vm, monitor_layout):
        # pylint: disable=no-self-use
        if vm.features.check_with_template('no-monitor-layout', False) \
                or not vm.is_running():
            return

        pipe = vm.run('QUBESRPC qubes.SetMonitorLayout dom0',
            passio_popen=True, wait=True)

        pipe.stdin.write(''.join(monitor_layout))
        pipe.stdin.close()
        pipe.wait()
