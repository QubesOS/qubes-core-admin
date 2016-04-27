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
import re
import subprocess

import qubes.config
import qubes.ext


# "LVDS connected 1024x768+0+0 (normal left inverted right) 304mm x 228mm"
REGEX_OUTPUT = re.compile(r'''
        (?x)                           # ignore whitespace
        ^                              # start of string
        (?P<output>[A-Za-z0-9\-]*)[ ]  # LVDS VGA etc
        (?P<connect>(dis)?connected)[ ]# dis/connected
        (?P<primary>(primary)?)[ ]?
        ((                             # a group
           (?P<width>\d+)x             # either 1024x768+0+0
           (?P<height>\d+)[+]
           (?P<x>\d+)[+]
           (?P<y>\d+)
         )|[\D])                       # or not a digit
        .*                             # ignore rest of line
        ''')


def get_monitor_layout():
    outputs = []

    for line in subprocess.Popen(
            ['xrandr', '-q'], stdout=subprocess.PIPE).stdout:
        if not line.startswith("Screen") and not line.startswith(" "):
            output_params = REGEX_OUTPUT.match(line).groupdict()
            if output_params['width']:
                outputs.append("%s %s %s %s\n" % (
                            output_params['width'],
                            output_params['height'],
                            output_params['x'],
                            output_params['y']))
    return outputs


class GUI(qubes.ext.Extension):
    @qubes.ext.handler('domain-start', 'domain-cmd-pre-run')
    def start_guid(self, vm, event, preparing_dvm=False, start_guid=True,
            extra_guid_args=None, **kwargs):
        '''Launch gui daemon.

        GUI daemon securely displays windows from domain.
        ''' # pylint: disable=no-self-use,unused-argument

        if not start_guid or preparing_dvm \
                or not os.path.exists('/var/run/shm.id'):
            return

        if self.is_guid_running(vm):
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

        if vm.hvm:
            guid_cmd += ['-Q', '-n']

            stubdom_guid_pidfile = \
                '/var/run/qubes/guid-running.{}'.format(self.get_stubdom_xid(vm))
            if not vm.debug and os.path.exists(stubdom_guid_pidfile):
                # Terminate stubdom guid once "real" gui agent connects
                stubdom_guid_pid = open(stubdom_guid_pidfile, 'r').read().strip()
                guid_cmd += ['-K', stubdom_guid_pid]

        try:
            subprocess.check_call(guid_cmd)
        except subprocess.CalledProcessError:
            raise qubes.exc.QubesVMError(vm,
                'Cannot start qubes-guid for domain {!r}'.format(vm.name))

        vm.fire_event('monitor-layout-change')
        vm.wait_for_session()


    @staticmethod
    def get_stubdom_xid(vm):
        if vm.xid < 0:
            return -1

        if vm.app.vmm.xs is None:
            return -1

        stubdom_xid_str = vm.app.vmm.xs.read('',
            '/local/domain/{}/image/device-model-domid'.format(vm.xid))
        if stubdom_xid_str is None or not stubdom_xid_str.isdigit():
            return -1

        return int(stubdom_xid_str)


    @staticmethod
    def send_gui_mode(vm):
        vm.run_service('qubes.SetGuiMode',
            input=('SEAMLESS'
            if vm.features.get('gui-seamless', False)
            else 'FULLSCREEN'))


    @qubes.ext.handler('domain-spawn')
    def on_domain_spawn(self, vm, event, start_guid=True, **kwargs):
        if not start_guid:
            return

        if not vm.hvm:
            return

        if not os.getenv('DISPLAY'):
            vm.log.error('Not starting gui daemon, no DISPLAY set')
            return

        guid_cmd = [qubes.config.system_path['qubes_guid_path'],
            '-d', str(self.get_stubdom_xid(vm)),
            '-t', str(vm.xid),
            '-N', vm.name,
            '-c', vm.label.color,
            '-i', vm.label.icon_path,
            '-l', str(vm.label.index),
            ]

        if vm.debug:
            guid_cmd += ['-v', '-v']
        else:
            guid_cmd += ['-q']

        try:
            subprocess.check_call(guid_cmd)
        except subprocess.CalledProcesException:
            raise qubes.exc.QubesVMError(vm, 'Cannot start gui daemon')


    @qubes.ext.handler('monitor-layout-change')
    def on_monitor_layout_change(self, vm, event, monitor_layout=None):
        # pylint: disable=no-self-use
        if vm.features.check_with_template('no-monitor-layout', False) \
                or not vm.is_running():
            return

        if monitor_layout is None:
            monitor_layout = get_monitor_layout()
            if not monitor_layout:
                return

        pipe = vm.run('QUBESRPC qubes.SetMonitorLayout dom0',
            passio_popen=True, wait=True)

        pipe.stdin.write(''.join(monitor_layout))
        pipe.stdin.close()
        pipe.wait()


    @staticmethod
    def is_guid_running(vm):
        '''Check whether gui daemon for this domain is available.

        :returns: :py:obj:`True` if guid is running, \
            :py:obj:`False` otherwise.
        :rtype: bool
        '''
        xid = vm.xid
        if xid < 0:
            return False
        if not os.path.exists('/var/run/qubes/guid-running.{}'.format(xid)):
            return False
        return True


    @qubes.ext.handler('domain-is-fully-usable')
    def on_domain_is_fully_usable(self, vm, event):
        if not self.is_guid_running(vm):
            yield False
