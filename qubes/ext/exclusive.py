# -*- encoding: utf-8 -*-
#
# The Qubes OS Project, http://www.qubes-os.org
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
Keep some qubes from running at the same time.

A qube with the ``exclusive-with`` feature set to a space-separated list of
tags cannot run together with any qube that has one of those tags. The check
works both ways and is done when a qube starts:

 - a qube with ``exclusive-with`` does not start while a qube with one of
   the listed tags is running;
 - a qube with one of the tags does not start while a qube that lists that
   tag in its ``exclusive-with`` is running.

A qube counts as running in every state except "Halted" (so also while it
is starting, paused, suspended or shutting down). The qube itself and dom0
are never counted.
"""

import qubes.exc
import qubes.ext
import qubes.vm.adminvm

FEATURE = "exclusive-with"


def _excluded_tags(vm):
    return set(str(vm.features.get(FEATURE, "") or "").split())


def _is_active(vm):
    return vm.get_power_state() not in ("Halted", "NA")


class ExclusiveExtension(qubes.ext.Extension):
    # pylint: disable=too-few-public-methods
    @qubes.ext.handler("domain-pre-start")
    def on_domain_pre_start(self, vm, event, **kwargs):
        """Refuse to start a qube that conflicts with a running one"""
        # pylint: disable=unused-argument
        own_excluded = _excluded_tags(vm)
        conflicts = []
        for other in vm.app.domains:
            if other is vm or isinstance(other, qubes.vm.adminvm.AdminVM):
                continue
            # check tags first, the power state needs a libvirt call
            if (
                own_excluded.intersection(other.tags)
                or _excluded_tags(other).intersection(vm.tags)
            ) and _is_active(other):
                conflicts.append(other.name)
        if conflicts:
            raise qubes.exc.QubesVMError(
                vm,
                "Qube {} cannot run at the same time as: {} "
                "(see the '{}' feature)".format(
                    vm.name, ", ".join(sorted(conflicts)), FEATURE
                ),
            )
