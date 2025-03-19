# The Qubes OS Project, http://www.qubes-os.org
#
# Copyright (C) 2024 Frédéric Pierret <frederic@invisiblethingslab.com>
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
# with this program. If not, see <https://www.gnu.org/licenses/>.
#
# SPDX-License-Identifier: GPL-3.0-or-later

import qubes
import qubes.exc
import qubes.vm
from qubes.vm import BaseVM


class RemoteVM(BaseVM):

    relayvm = qubes.VMProperty(
        "relayvm",
        load_stage=4,
        allow_none=True,
        default=None,
        doc="Local qube used as relay.",
    )

    transport_rpc = qubes.property(
        "transport_rpc",
        type=str,
        default=None,
        doc="Transport RPC used by the relay.",
    )

    remote_name = qubes.property(
        "remote_name",
        type=str,
        default=None,
        doc="Name on the remote host.",
    )

    def __init__(self, app, xml, **kwargs):
        super().__init__(app, xml, **kwargs)

        if xml is None:
            self.events_enabled = True
        self.fire_event("domain-init")

    def get_mem(self):
        return 0

    def get_mem_static_max(self):
        return 0

    def get_cputime(self):
        return 0

    @staticmethod
    def is_running():
        # fixme: handle power management option
        return True

    @staticmethod
    def is_halted():
        # fixme: handle power management option
        return False

    @staticmethod
    def get_power_state():
        # fixme: handle power management option
        return "Running"

    def start(self, **kwargs):
        raise qubes.exc.QubesVMNotHaltedError(self, "Cannot start a RemoteVM.")

    def suspend(self):
        raise qubes.exc.QubesVMError(self, "Cannot suspend a RemoteVM.")

    def shutdown(self):
        raise qubes.exc.QubesVMError(self, "Cannot shutdown a RemoteVM.")

    def kill(self):
        raise qubes.exc.QubesVMError(self, "Cannot kill a RemoteVM.")
