# -*- encoding: utf8 -*-
#
# The Qubes OS Project, http://www.qubes-os.org
#
# Copyright (C) 2019 Marek Marczykowski-Górecki
#   <marmarek@invisiblethingslab.com>
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

"""
Backup restore related functionality. Specifically:
 - prevent starting a domain currently being restored
"""

import qubes.api
import qubes.ext
import qubes.vm.adminvm


class BackupRestoreExtension(qubes.ext.Extension):
    # pylint: disable=too-few-public-methods
    @qubes.ext.handler("domain-pre-start")
    def on_domain_pre_start(self, vm, event, **kwargs):
        """Prevent starting a VM during restore"""
        # pylint: disable=unused-argument
        if "backup-restore-in-progress" in vm.tags:
            raise qubes.exc.QubesVMError(
                vm, "Restore of this domain in progress, cannot start"
            )
