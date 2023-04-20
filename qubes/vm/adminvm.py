#
# The Qubes OS Project, https://www.qubes-os.org/
#
# Copyright (C) 2010-2015  Joanna Rutkowska <joanna@invisiblethingslab.com>
# Copyright (C) 2013-2015  Marek Marczykowski-Górecki
#                              <marmarek@invisiblethingslab.com>
# Copyright (C) 2014-2015  Wojtek Porczyk <woju@invisiblethingslab.com>
#
# This library is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 2.1 of the License, or (at your option) any later version.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with this library; if not, see <https://www.gnu.org/licenses/>.
#

''' This module contains the AdminVM implementation '''
import asyncio
import subprocess
import libvirt

import qubes
import qubes.exc
import qubes.vm
from qubes.vm.qubesvm import _setter_kbd_layout
from qubes.vm import BaseVM


class AdminVM(BaseVM):
    '''Dom0'''

    dir_path = None

    name = qubes.property('name',
        default='dom0', setter=qubes.property.forbidden)

    qid = qubes.property('qid',
        default=0, type=int, setter=qubes.property.forbidden)

    uuid = qubes.property('uuid',
        default='00000000-0000-0000-0000-000000000000',
        setter=qubes.property.forbidden)

    default_dispvm = qubes.VMProperty('default_dispvm',
        load_stage=4,
        allow_none=True,
        default=(lambda self: self.app.default_dispvm),
        doc='Default VM to be used as Disposable VM for service calls.')

    include_in_backups = qubes.property('include_in_backups',
        default=True, type=bool,
        doc='If this domain is to be included in default backup.')

    updateable = qubes.property('updateable',
        default=True,
        type=bool,
        setter=qubes.property.forbidden,
        doc='True if this machine may be updated on its own.')

    # for changes in keyboard_layout, see also the same property in QubesVM
    keyboard_layout = qubes.property(
        'keyboard_layout',
        type=str,
        setter=_setter_kbd_layout,
        default='us++',
        doc='Keyboard layout for this VM')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._qdb_connection = None
        self._libvirt_domain = None

        if not self.app.vmm.offline_mode:
            self.start_qdb_watch()

    def __str__(self):
        return self.name

    def __lt__(self, other: object):
        if not isinstance(other, BaseVM):
            return NotImplemented
        # order dom0 before anything
        if not isinstance(other, AdminVM):
            return True
        assert self is other, "multiple instances of AdminVM?"
        return False

    @property
    def attached_volumes(self):
        return []

    @property
    def xid(self) -> int:
        '''Always ``0``.

        .. seealso:
           :py:attr:`qubes.vm.qubesvm.QubesVM.xid`
        '''
        return 0

    @qubes.stateless_property
    def icon(self):
        """freedesktop icon name, suitable for use in
        :py:meth:`PyQt4.QtGui.QIcon.fromTheme`"""
        return 'adminvm-black'

    @property
    def libvirt_domain(self):
        '''Libvirt object for dom0.

        .. seealso:
           :py:attr:`qubes.vm.qubesvm.QubesVM.libvirt_domain`
        '''
        if self._libvirt_domain is None:
            self._libvirt_domain = self.app.vmm.libvirt_conn.lookupByID(0)
        return self._libvirt_domain

    @staticmethod
    def is_running():
        '''Always :py:obj:`True`.

        .. seealso:
           :py:meth:`qubes.vm.qubesvm.QubesVM.is_running`
        '''
        return True

    @staticmethod
    def is_halted():
        '''Always :py:obj:`False`.

        .. seealso:
           :py:meth:`qubes.vm.qubesvm.QubesVM.is_halted`
        '''
        return False

    @staticmethod
    def get_power_state():
        '''Always ``'Running'``.

        .. seealso:
           :py:meth:`qubes.vm.qubesvm.QubesVM.get_power_state`
        '''
        return 'Running'

    @staticmethod
    def get_mem():
        '''Get current memory usage of Dom0.

        Unit is KiB.

        .. seealso:
           :py:meth:`qubes.vm.qubesvm.QubesVM.get_mem`
        '''

        # return psutil.virtual_memory().total/1024
        with open('/proc/meminfo', encoding='ascii') as file:
            for line in file:
                if line.startswith('MemTotal:'):
                    return int(line.split(':')[1].strip().split()[0])
        raise NotImplementedError()

    def get_mem_static_max(self):
        '''Get maximum memory available to Dom0.

        .. seealso:
           :py:meth:`qubes.vm.qubesvm.QubesVM.get_mem_static_max`
        '''
        if self.app.vmm.offline_mode:
            # default value passed on xen cmdline
            return 4096
        try:
            return self.app.vmm.libvirt_conn.getInfo()[1]
        except libvirt.libvirtError as e:
            self.log.warning('Failed to get memory limit for dom0: %s', e)
            return 4096

    def get_cputime(self):
        '''Get total CPU time burned by Dom0 since start.

        .. seealso:
           :py:meth:`qubes.vm.qubesvm.QubesVM.get_cputime`
        '''
        try:
            return self.libvirt_domain.info()[4]
        except libvirt.libvirtError as e:
            self.log.warning('Failed to get CPU time for dom0: %s', e)
            return 0

    def verify_files(self):
        '''Always :py:obj:`True`

        .. seealso:
           :py:meth:`qubes.vm.qubesvm.QubesVM.verify_files`
        '''
        return True

    def start(self, start_guid=True, notify_function=None,
            mem_required=None):
        '''Always raises an exception.

        .. seealso:
           :py:meth:`qubes.vm.qubesvm.QubesVM.start`
        '''  # pylint: disable=unused-argument,arguments-differ
        raise qubes.exc.QubesVMNotHaltedError(
            self, 'Cannot start Dom0 fake domain!')

    def suspend(self):
        '''Does nothing.

        .. seealso:
           :py:meth:`qubes.vm.qubesvm.QubesVM.suspend`
        '''
        raise qubes.exc.QubesVMError(self, 'Cannot suspend Dom0 fake domain!')

    def shutdown(self):
        '''Does nothing.

        .. seealso:
           :py:meth:`qubes.vm.qubesvm.QubesVM.shutdown`
        '''
        raise qubes.exc.QubesVMError(self, 'Cannot shutdown Dom0 fake domain!')

    def kill(self):
        '''Does nothing.

        .. seealso:
           :py:meth:`qubes.vm.qubesvm.QubesVM.kill`
        '''
        raise qubes.exc.QubesVMError(self, 'Cannot kill Dom0 fake domain!')

    @property
    def untrusted_qdb(self):
        '''QubesDB handle for this domain.'''
        if self._qdb_connection is None:
            import qubesdb  # pylint: disable=import-error
            self._qdb_connection = qubesdb.QubesDB(self.name)
        return self._qdb_connection

    async def run_service(self, service, source=None, user=None,
            filter_esc=False, autostart=False, gui=False, **kwargs):
        '''Run service on this VM

        :param str service: service name
        :param qubes.vm.qubesvm.QubesVM source: source domain as presented to
            this VM
        :param str user: username to run service as
        :param bool filter_esc: filter escape sequences to protect terminal \
            emulator
        :param bool autostart: if :py:obj:`True`, machine will be started if \
            it is not running
        :param bool gui: when autostarting, also start gui daemon
        :rtype: asyncio.subprocess.Process

        .. note::
            User ``root`` is redefined to ``SYSTEM`` in the Windows agent code
        '''
        # pylint: disable=unused-argument

        source = 'dom0' if source is None else self.app.domains[source].name

        if filter_esc:
            raise NotImplementedError(
                'filter_esc=True not supported on calls to dom0')

        if user is None:
            user = 'root'

        await self.fire_event_async('domain-cmd-pre-run', pre_event=True,
            start_guid=gui)

        if user != 'root':
            cmd = ['runuser', '-u', user, '--']
        else:
            cmd = []
        cmd.extend([
            qubes.config.system_path['qrexec_rpc_multiplexer'],
            service,
            source,
            'name',
            self.name,
            ])
        return await asyncio.create_subprocess_exec(*cmd, **kwargs)

    async def run_service_for_stdio(self, *args, input=None, **kwargs):
        '''Run a service, pass an optional input and return (stdout, stderr).

        Raises an exception if return code != 0.

        *args* and *kwargs* are passed verbatim to :py:meth:`run_service`.

        .. warning::
            There are some combinations if stdio-related *kwargs*, which are
            not filtered for problems originating between the keyboard and the
            chair.
        '''  # pylint: disable=redefined-builtin

        kwargs.setdefault('stdin', subprocess.PIPE)
        kwargs.setdefault('stdout', subprocess.PIPE)
        kwargs.setdefault('stderr', subprocess.PIPE)
        p = await self.run_service(*args, **kwargs)

        # this one is actually a tuple, but there is no need to unpack it
        stdouterr = await p.communicate(input=input)

        if p.returncode:
            raise subprocess.CalledProcessError(p.returncode,
                args[0], *stdouterr)

        return stdouterr
