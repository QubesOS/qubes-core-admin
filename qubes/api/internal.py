# -*- encoding: utf8 -*-
#
# The Qubes OS Project, http://www.qubes-os.org
#
# Copyright (C) 2017 Marek Marczykowski-Górecki
#                               <marmarek@invisiblethingslab.com>
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
# with this program; if not, see <http://www.gnu.org/licenses/>.

''' Internal interface for dom0 components to communicate with qubesd. '''

import asyncio
import json
import subprocess

import qubes.api
import qubes.api.admin
import qubes.vm.adminvm
import qubes.vm.dispvm


class QubesInternalAPI(qubes.api.AbstractQubesAPI):
    ''' Communication interface for dom0 components,
    by design the input here is trusted.'''

    SOCKNAME = '/var/run/qubesd.internal.sock'

    @qubes.api.method('internal.GetSystemInfo', no_payload=True)
    @asyncio.coroutine
    def getsysteminfo(self):
        assert self.dest.name == 'dom0'
        assert not self.arg

        system_info = {'domains': {
            domain.name: {
                'tags': list(domain.tags),
                'type': domain.__class__.__name__,
                'dispvm_allowed': getattr(domain, 'dispvm_allowed', False),
                'default_dispvm': (str(domain.default_dispvm) if
                    getattr(domain, 'default_dispvm', None) else None),
                'icon': str(domain.label.icon),
            } for domain in self.app.domains
        }}

        return json.dumps(system_info)

    @qubes.api.method('internal.vm.Start', no_payload=True)
    @asyncio.coroutine
    def start(self):
        assert not self.arg
        if self.dest.name == 'dom0':
            return

        yield from self.dest.start()

    @qubes.api.method('internal.vm.Create.DispVM', no_payload=True)
    @asyncio.coroutine
    def create_dispvm(self):
        assert not self.arg

        dispvm = yield from qubes.vm.dispvm.DispVM.from_appvm(self.dest)
        return dispvm.name

    @qubes.api.method('internal.vm.CleanupDispVM', no_payload=True)
    @asyncio.coroutine
    def cleanup_dispvm(self):
        assert not self.arg

        yield from self.dest.cleanup()

    @qubes.api.method('internal.vm.volume.ImportEnd')
    @asyncio.coroutine
    def vm_volume_import_end(self, untrusted_payload):
        '''
        This is second half of admin.vm.volume.Import handling. It is called
        when actual import is finished. Response from this method is sent do
        the client (as a response for admin.vm.volume.Import call).
        '''
        assert self.arg in self.dest.volumes.keys()
        success = untrusted_payload == b'ok'

        try:
            self.dest.storage.import_data_end(self.arg, success=success)
        except:
            self.dest.fire_event('domain-volume-import-end', volume=self.arg,
                succeess=False)
            raise

        self.dest.fire_event('domain-volume-import-end', volume=self.arg,
            succeess=success)

        if not success:
            raise qubes.exc.QubesException('Data import failed')

    @qubes.api.method('internal.SuspendPre', no_payload=True)
    @asyncio.coroutine
    def suspend_pre(self):
        '''
        Method called before host system goes to sleep.

        :return:
        '''

        # first notify all VMs
        processes = []
        for vm in self.app.domains:
            if isinstance(vm, qubes.vm.adminvm.AdminVM):
                continue
            if vm.is_running():
                proc = yield from vm.run_service(
                    'qubes.SuspendPreAll', user='root',
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL)
                processes.append(proc)

        # FIXME: some timeout?
        if processes:
            yield from asyncio.wait([p.wait() for p in processes])

        coros = []
        # then suspend/pause VMs
        for vm in self.app.domains:
            if isinstance(vm, qubes.vm.adminvm.AdminVM):
                continue
            if vm.is_running():
                coros.append(vm.suspend())
        if coros:
            yield from asyncio.wait(coros)

    @qubes.api.method('internal.SuspendPost', no_payload=True)
    @asyncio.coroutine
    def suspend_post(self):
        '''
        Method called after host system wake up from sleep.

        :return:
        '''

        coros = []
        # first resume/unpause VMs
        for vm in self.app.domains:
            if isinstance(vm, qubes.vm.adminvm.AdminVM):
                continue
            if vm.get_power_state() in ["Paused", "Suspended"]:
                coros.append(vm.resume())
        if coros:
            yield from asyncio.wait(coros)

        # then notify all VMs
        processes = []
        for vm in self.app.domains:
            if isinstance(vm, qubes.vm.adminvm.AdminVM):
                continue
            if vm.is_running():
                proc = yield from vm.run_service(
                    'qubes.SuspendPostAll', user='root',
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL)
                processes.append(proc)

        # FIXME: some timeout?
        if processes:
            yield from asyncio.wait([p.wait() for p in processes])
