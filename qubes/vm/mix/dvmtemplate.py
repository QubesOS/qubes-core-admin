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

    def get_feat_preload(self) -> list[str]:
        feature = "preload-dispvm"
        assert isinstance(self, qubes.vm.BaseVM)
        value = self.features.get(feature, "")
        return value.split(" ") if value else []

    def get_feat_preload_max(self) -> int:
        feature = "preload-dispvm-max"
        assert isinstance(self, qubes.vm.BaseVM)
        value = self.features.get(feature, 0)
        return int(value) if value else 0

    def can_preload(self) -> bool:
        preload_dispvm_max = self.get_feat_preload_max()
        preload_dispvm = self.get_feat_preload()
        if len(preload_dispvm) < preload_dispvm_max:
            return True
        return False

    def remove_preload_from_list(self, disp) -> None:
        assert isinstance(self, qubes.vm.BaseVM)
        preload_dispvm = self.get_feat_preload()
        preload_dispvm.remove(disp)
        self.features["preload-dispvm"] = " ".join(preload_dispvm or [])

    def remove_preload_excess(self, max_preload: Optional[int] = None) -> None:
        """Removes excessive preloaded qubes:

        - Qubes that exceed the maximum
        - Qubes that are in the list but do not exist anymore
        """
        assert isinstance(self, qubes.vm.BaseVM)
        if max_preload is None:
            max_preload = self.get_feat_preload_max()
        old_preload = self.get_feat_preload()
        if not old_preload:
            return
        new_preload = old_preload[:max_preload]
        excess = old_preload[max_preload:]
        if excess:
            self.log.info(
                "Removing excess qube(s) from preloaded list: '%s'",
                ", ".join(excess),
            )
            self.features["preload-dispvm"] = " ".join(new_preload or [])
            for unwanted_disp in excess:
                if unwanted_disp in self.app.domains:
                    dispvm = self.app.domains[unwanted_disp]
                    asyncio.ensure_future(dispvm.cleanup())
        clean_preload = new_preload
        for unwanted_disp in new_preload:
            if unwanted_disp not in self.app.domains:
                clean_preload.remove(unwanted_disp)
        if len(clean_preload) < len(new_preload):
            absent = list(set(new_preload) - set(clean_preload))
            self.log.info(
                "Removing absent qube(s) from preloaded list: '%s'",
                ", ".join(absent),
            )
            self.features["preload-dispvm"] = " ".join(clean_preload or [])

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
        value = value or "0"
        if not value.isdigit():
            raise qubes.exc.QubesValueError(
                "Invalid preload-dispvm-max value: not a digit"
            )

    @qubes.events.handler("domain-feature-set:preload-dispvm-max")
    def on_feature_set_preload_dispvm_max(
        self, event, feature, value, oldvalue=None
    ):  # pylint: disable=unused-argument
        # Preload if there is vacancy, offload if there is excess.
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
        #
        # TODO: ben
        # Marek: Looks like a good idea to check this, but make sure the
        # from_appvm (and maybe other places?) handle this case correctly. From
        # what I see, theoretically it will happen if you reduce preload max
        # while some dispvm is getting preloaded already (the window is quite
        # short, basically you need to hit create_on_disk() call, but still
        # looks possible). In that case it shouldn't left orphaned running (or
        # not even started?) dispvm.
        if new_len > max(preload_dispvm_max, old_len):
            raise qubes.exc.QubesValueError(
                f"\nold_list='{old_list}' new_list='{new_list}'\n"
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
        # TODO: ben: review and cleanup
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
        """When preloaded DispVM is used or after boot, preload another one.

        :param event: event which was fired
        :returns:
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
            return
        max_preload = self.get_feat_preload_max()
        if event == "used":
            want_preload = 1
        else:
            want_preload = max_preload - len(self.get_feat_preload())
        if want_preload <= 0:
            return

        avail_mem_file = qubes.config.qmemman_avail_mem_file
        available_memory = None
        try:
            with open(avail_mem_file, "r", encoding="ascii") as file:
                available_memory = int(file.read())
        except FileNotFoundError:
            can_preload = want_preload
        if available_memory:
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
                # TODO: ben
                #
                # Marek:
                #   Should it retry with some delay? Or maybe only after some
                #   specific event (like closing other dispvm, or requesting
                #   one)?  I'm not sure if a delay is a good idea, but there
                #   should be some way to recover from this situation, not only
                #   by manually setting the feature again (as currently
                #   documented).
                #
                # Ben:
                #   I am still thinking of a way to solve this. If two qubes
                #   are marked as used, there will be a threshold of 2, then
                #   the first used event runs, it currently just tries to
                #   preload 1 substitute, if it tried to preload the threshold,
                #   the 2nd used state would fail, or so it would in the past.
                #   With the many rewrites this function had, I can this this
                #   would not be an issue anymore and used event should not be
                #   limited to 1 because above there is
                #
                #         elif not self.can_preload():
                #             self.remove_preload_excess() return
                #
                #   The used has one flaw in this case, if a preloaded is
                #   marked as used and there are no more preloaded qubes and
                #   also there is not enough memory, it will not try to preload
                #   qubes anymore unless the workaround to re-set the feature
                #   to the same value it is on, so there are different edge
                #   cases that we should look out for.
                return

        self.log.info("Preloading '%d' qube(s)", can_preload)
        async with asyncio.TaskGroup() as task_group:
            for _ in range(can_preload):
                task_group.create_task(
                    qubes.vm.dispvm.DispVM.from_appvm(self, preload=True)
                )

    @property
    def dispvms(self):
        """Returns a generator containing all Disposable VMs based on the
        current AppVM.
        """
        for vm in self.app.domains:
            if getattr(vm, "template", None) == self:
                yield vm
