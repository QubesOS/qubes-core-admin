# -*- encoding: utf-8 -*-
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

import asyncio
from typing import Optional

import qubes.config
import qubes.events
import qubes.vm.dispvm


class DVMTemplateMixin(qubes.events.Emitter):
    """VM class capable of being DVM template"""

    # pylint doesn't see event handlers being registered via decorator
    # pylint: disable=unused-private-member

    template_for_dispvms = qubes.property(
        "template_for_dispvms",
        type=bool,
        default=False,
        doc="Should this VM be allowed to start as Disposable VM",
    )

    @property
    def dispvms(self):
        """Returns a generator containing all Disposable VMs based on the
        current AppVM.
        """
        for vm in self.app.domains:
            if getattr(vm, "template", None) == self:
                yield vm

    @qubes.events.handler("domain-load")
    def on_domain_loaded(self, event):  # pylint: disable=unused-argument
        """Cleanup invalid preloaded qubes when domain is loaded."""
        changes = False
        # Preloading began and host rebooted and autostart event didn't run yet.
        old_preload = self.get_feat_preload()
        clean_preload = old_preload.copy()
        for unwanted_disp in old_preload:
            if unwanted_disp not in self.app.domains:
                clean_preload.remove(unwanted_disp)
        if absent := list(set(old_preload) - set(clean_preload)):
            changes = True
            self.log.info(
                "Removing absent preloaded qube(s): '%s'",
                ", ".join(absent),
            )
            self.features["preload-dispvm"] = " ".join(clean_preload or [])

        # Preloading was in progress (either preloading but not completed or
        # requested but not delivered) and qubesd stopped.
        preload_in_progress = [
            qube
            for qube in self.dispvms
            if qube.features.get("preload-dispvm-in-progress", False)
        ]
        if preload_in_progress:
            changes = True
            self.log.info(
                "Removing in progress preloaded qube(s): '%s'",
                ", ".join(map(str, preload_in_progress)),
            )
            self.remove_preload_from_list(
                [qube.name for qube in preload_in_progress]
            )
            for dispvm in preload_in_progress:
                asyncio.ensure_future(dispvm.cleanup())
        if changes:
            self.app.save()

    @qubes.events.handler("domain-feature-delete:preload-dispvm-max")
    def on_feature_delete_preload_dispvm_max(
        self, event, feature
    ):  # pylint: disable=unused-argument
        self.remove_preload_excess(0)

    @qubes.events.handler("domain-feature-pre-set:preload-dispvm-max")
    def on_feature_pre_set_preload_dispvm_max(
        self, event, feature, value, oldvalue=None
    ):  # pylint: disable=unused-argument
        if not self.features.check_with_template("qrexec", None):
            raise qubes.exc.QubesValueError("Qube does not support qrexec")

        service = "qubes.WaitForRunningSystem"
        supported_service = "supported-rpc." + service
        if not self.features.check_with_template(supported_service, False):
            raise qubes.exc.QubesValueError(
                "Qube does not support the RPC '%s'" % service
            )

        value = value or "0"
        if not value.isdigit():
            raise qubes.exc.QubesValueError(
                "Invalid preload-dispvm-max value: not a digit"
            )

    @qubes.events.handler("domain-feature-set:preload-dispvm-max")
    def on_feature_set_preload_dispvm_max(
        self, event, feature, value, oldvalue=None
    ):  # pylint: disable=unused-argument
        asyncio.ensure_future(
            self.fire_event_async("domain-preload-dispvm-start")
        )

    @qubes.events.handler("domain-feature-pre-set:preload-dispvm")
    def on_feature_pre_set_preload_dispvm(
        self, event, feature, value, oldvalue=None
    ):  # pylint: disable=unused-argument
        preload_dispvm_max = self.get_feat_preload_max()
        old_list = oldvalue.split(" ") if oldvalue else []
        new_list = value.split(" ") if value else []
        old_len, new_len = len(old_list), len(new_list)
        error_prefix = "Invalid preload-dispvm value:"

        if sorted(new_list) == sorted(old_list):
            return
        if not new_list:
            return

        # New value can be bigger than maximum permitted as long as it is
        # smaller than its old value.
        if new_len > max(preload_dispvm_max, old_len):
            raise qubes.exc.QubesValueError(
                f"{error_prefix} can't increment: qube count ({new_len}) is "
                f"either bigger than old count ({old_len}) or "
                f"preload-dispvm-max ({preload_dispvm_max})"
            )

        if new_len != len(set(new_list)):
            duplicates = [
                qube for qube in set(new_list) if new_list.count(qube) > 1
            ]
            raise qubes.exc.QubesValueError(
                f"{error_prefix} contain duplicates: '{', '.join(duplicates)}'"
            )

        new_list_diff = list(set(new_list) - set(old_list))
        nonqube = [
            qube for qube in new_list_diff if qube not in self.app.domains
        ]
        if nonqube:
            raise qubes.exc.QubesValueError(
                f"{error_prefix} non qube(s): '{', '.join(nonqube)}'"
            )

        nonderived = [
            qube
            for qube in new_list_diff
            if getattr(self.app.domains[qube], "template") != self
        ]
        if nonderived:
            raise qubes.exc.QubesValueError(
                f"{error_prefix} qube(s) not based on {self.name}: "
                f"'{', '.join(nonderived)}'"
            )

    @qubes.events.handler("domain-feature-set:preload-dispvm")
    def on_feature_set_preload_dispvm(
        self, event, feature, value, oldvalue=None
    ):  # pylint: disable=unused-argument
        value = value.split(" ") if value else []
        oldvalue = oldvalue.split(" ") if oldvalue else []
        exclusive = list(set(oldvalue).symmetric_difference(value))
        for qube in exclusive:
            if qube in self.app.domains:
                qube = self.app.domains[qube]
                qube.fire_event("property-reset:is_preload", name="is_preload")

    @qubes.events.handler("property-pre-set:template_for_dispvms")
    def __on_pre_set_dvmtemplate(self, event, name, newvalue, oldvalue=None):
        # pylint: disable=unused-argument
        if newvalue:
            return
        if any(self.dispvms):
            raise qubes.exc.QubesVMInUseError(
                self,
                "Cannot change template_for_dispvms to False while there are "
                "some DispVMs based on this DVM template",
            )

    @qubes.events.handler("property-pre-del:template_for_dispvms")
    def __on_pre_del_dvmtemplate(self, event, name, oldvalue=None):
        self.__on_pre_set_dvmtemplate(event, name, False, oldvalue)

    @qubes.events.handler("property-pre-set:template")
    def __on_pre_property_set_template(
        self, event, name, newvalue, oldvalue=None
    ):
        # pylint: disable=unused-argument
        for vm in self.dispvms:
            if vm.is_running():
                raise qubes.exc.QubesVMNotHaltedError(
                    self,
                    "Cannot change template while there are running DispVMs "
                    "based on this DVM template",
                )

    @qubes.events.handler("property-set:template")
    def __on_property_set_template(self, event, name, newvalue, oldvalue=None):
        # pylint: disable=unused-argument
        pass

    @qubes.events.handler(
        "domain-preload-dispvm-used",
        "domain-preload-dispvm-autostart",
        "domain-preload-dispvm-start",
    )
    async def on_domain_preload_dispvm_used(
        self, event, **kwargs
    ):  # pylint: disable=unused-argument
        """
        Preloads on vacancy and offloads on excess. If the event suffix is
        ``autostart``, the preloaded list is emptied before preloading.

        :param event: event which was fired
        """
        event = event.removeprefix("domain-preload-dispvm-")
        event_log = "Received preload event '%s'" % str(event)
        if event == "used":
            event_log += " for dispvm '%s'" % str(kwargs.get("dispvm"))
        self.log.info(event_log)

        if event == "autostart":
            self.remove_preload_excess(0)
        elif not self.can_preload():
            self.remove_preload_excess()
            # Absent qubes might be removed above.
            if not self.can_preload():
                return
        max_preload = self.get_feat_preload_max()
        want_preload = max_preload - len(self.get_feat_preload())
        if want_preload <= 0:
            self.log.info("Not preloading due to limit hit")
            return

        avail_mem_file = qubes.config.qmemman_avail_mem_file
        available_memory = None
        try:
            with open(avail_mem_file, "r", encoding="ascii") as file:
                available_memory = int(file.read())
        except FileNotFoundError:
            can_preload = want_preload
        if available_memory is not None:
            memory = getattr(self, "memory", 0) * 1024 * 1024
            unrestricted_preload = int(available_memory / memory)
            can_preload = min(unrestricted_preload, want_preload)
            if skip_preload := want_preload - can_preload:
                self.log.warning(
                    "Not preloading '%d' disposable(s) due to insufficient "
                    "memory",
                    skip_preload,
                )
            if can_preload == 0:
                # The gap is filled when consuming a preloaded qube or
                # requesting a disposable.
                return

        self.log.info("Preloading '%d' qube(s)", can_preload)
        async with asyncio.TaskGroup() as task_group:
            for _ in range(can_preload):
                task_group.create_task(
                    qubes.vm.dispvm.DispVM.from_appvm(self, preload=True)
                )

    def get_feat_preload(self) -> list[str]:
        """Get the ``preload-dispvm`` feature as a list."""
        feature = "preload-dispvm"
        assert isinstance(self, qubes.vm.BaseVM)
        value = self.features.get(feature, "")
        return value.split(" ") if value else []

    def get_feat_preload_max(self) -> int:
        """Get the ``preload-dispvm-max`` feature as an integer."""
        feature = "preload-dispvm-max"
        assert isinstance(self, qubes.vm.BaseVM)
        value = self.features.get(feature, 0)
        return int(value) if value else 0

    def can_preload(self) -> bool:
        """Returns ``True`` if there is preload vacancy."""
        preload_dispvm_max = self.get_feat_preload_max()
        preload_dispvm = self.get_feat_preload()
        if len(preload_dispvm) < preload_dispvm_max:
            return True
        return False

    def remove_preload_from_list(self, disposables: list[str]) -> None:
        """Removes list of preload qubes from the list.

        :param disposables: disposable names to remove from the preloaded list.
        """
        assert isinstance(self, qubes.vm.BaseVM)
        old_preload = self.get_feat_preload()
        preload_dispvm = [
            qube for qube in old_preload if qube not in disposables
        ]
        if dispose := list(set(old_preload) - set(preload_dispvm)):
            self.log.info(
                "Removing qube(s) from preloaded list: '%s'",
                ", ".join(dispose),
            )
            self.features["preload-dispvm"] = " ".join(preload_dispvm or [])

    def remove_preload_excess(self, max_preload: Optional[int] = None) -> None:
        """Removes preloaded qubes that exceeds the maximum."""
        assert isinstance(self, qubes.vm.BaseVM)
        if max_preload is None:
            max_preload = self.get_feat_preload_max()
        old_preload = self.get_feat_preload()
        if not old_preload:
            return
        new_preload = old_preload[:max_preload]
        if excess := old_preload[max_preload:]:
            self.log.info(
                "Removing excess qube(s) from preloaded list: '%s'",
                ", ".join(excess),
            )
            self.features["preload-dispvm"] = " ".join(new_preload or [])
            for unwanted_disp in excess:
                if unwanted_disp in self.app.domains:
                    dispvm = self.app.domains[unwanted_disp]
                    asyncio.ensure_future(dispvm.cleanup())
