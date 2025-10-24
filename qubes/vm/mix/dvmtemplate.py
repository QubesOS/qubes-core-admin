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
from typing import Optional, Union, Iterator

import qubes.config
import qubes.events
import qubes.vm.dispvm


class DVMTemplateMixin(qubes.events.Emitter):
    """
    VM class capable of being disposable template.
    """

    # pylint doesn't see event handlers being registered via decorator
    # pylint: disable=unused-private-member

    template_for_dispvms = qubes.property(
        "template_for_dispvms",
        type=bool,
        default=False,
        doc="Should this VM be allowed to start as Disposable VM",
    )

    @property
    def dispvms(self) -> Iterator["qubes.vm.dispvm.DispVM"]:
        """
        Get all disposables based on the current disposable template.

        :rtype: Iterator[qubes.vm.dispvm.DispVM]
        """
        assert isinstance(self, qubes.vm.BaseVM)
        for vm in self.app.domains:
            if getattr(vm, "template", None) == self:
                yield vm

    @qubes.events.handler("domain-load")
    def on_domain_loaded(self, event) -> None:
        """
        Cleanup invalid preloaded qubes when domain is loaded.

        :param str event: Event which was fired.
        """
        # pylint: disable=unused-argument
        assert isinstance(self, qubes.vm.BaseVM)
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
        #
        # Or qubesd stopped and the qube was destroyed/killed in the meantime,
        # shutdown was not called by qubesd so the qube is still present. The
        # "preload-dispvm-completed" is used to check if this was a preloaded
        # qube instead of "is_preload()" because it might not be in the
        # "preload-dispvm" list anymore if the following happened: "removed
        # from list -> scheduled cleanup -> stopped qubesd".
        preload_in_progress = [
            qube
            for qube in self.dispvms
            if (
                not qube.is_running()
                and qube.features.get("preload-dispvm-completed", False)
            )
            or qube.features.get("preload-dispvm-in-progress", False)
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

    @qubes.events.handler("domain-pre-start")
    def __on_domain_pre_start(self, event, **kwargs) -> None:
        """
        Prevents startup for domain having a volume with disabled snapshots
        and a disposable based on this volume started.

        :param str event: Event which was fired.
        """
        # pylint: disable=unused-argument
        assert isinstance(self, qubes.vm.qubesvm.QubesVM)
        volume_with_disabled_snapshots = False
        for vol in self.volumes.values():
            volume_with_disabled_snapshots |= vol.snapshots_disabled

        if not volume_with_disabled_snapshots:
            return

        for vm in self.dispvms:
            if vm.is_running():
                raise qubes.exc.QubesVMNotHaltedError(vm)

    @qubes.events.handler("domain-shutdown")
    async def on_dvmtemplate_domain_shutdown(self, _event, **_kwargs) -> None:
        """
        Refresh preloaded disposables on shutdown.
        """
        await self.refresh_preload()

    @qubes.events.handler("domain-feature-delete:preload-dispvm-max")
    def on_feature_delete_preload_dispvm_max(self, event, feature) -> None:
        """
        On deletion of the ``preload-dispvm-max`` feature, remove all preloaded
        disposables if the global preload is not set.

        :param str event: Event which was fired.
        :param str feature: Feature name.
        """
        # pylint: disable=unused-argument
        if self.is_global_preload_set():
            return
        self.remove_preload_excess(0)

    @qubes.events.handler("domain-feature-pre-set:preload-dispvm-max")
    def on_feature_pre_set_preload_dispvm_max(
        self, event, feature, value, oldvalue=None
    ):
        """
        Before accepting the ``preload-dispvm-max`` feature, validate it.

        :param str event: Event which was fired.
        :param str feature: Feature name.
        :param int value: New value of the feature.
        :param int oldvalue: Old value of the feature.
        """
        # pylint: disable=unused-argument
        if not self.features.check_with_template("qrexec", None):
            raise qubes.exc.QubesValueError("Qube does not support qrexec")

        service = "qubes.WaitForRunningSystem"
        if not self.supports_preload():
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
    ):
        """
        After setting the ``preload-dispvm-max`` feature, attempt to preload.

        :param str event: Event which was fired.
        :param str feature: Feature name.
        :param int value: New value of the feature.
        :param int oldvalue: Old value of the feature.
        """
        # pylint: disable=unused-argument
        if value == oldvalue:
            return
        if self.is_global_preload_set():
            return
        reason = "local feature was set to " + repr(value)
        asyncio.ensure_future(
            self.fire_event_async("domain-preload-dispvm-start", reason=reason)
        )

    @qubes.events.handler("domain-feature-pre-set:preload-dispvm")
    def on_feature_pre_set_preload_dispvm(
        self, event, feature, value, oldvalue=None
    ):
        """
        Before accepting the ``preload-dispvm`` feature, validate it.

        :param str event: Event which was fired.
        :param str feature: Feature name.
        :param str value: New value of the feature.
        :param str oldvalue: Old value of the feature.
        """
        # pylint: disable=unused-argument
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
    ):
        """
        After setting the ``preload-dispvm`` feature, reset the ``is_preload``
        property.

        :param str event: Event which was fired.
        :param str feature: Feature name.
        :param str value: New value of the feature.
        :param str oldvalue: Old value of the feature.
        """
        # pylint: disable=unused-argument
        value = value.split(" ") if value else []
        oldvalue = oldvalue.split(" ") if oldvalue else []
        exclusive = list(set(oldvalue).symmetric_difference(value))
        for qube in exclusive:
            if qube in self.app.domains:
                qube = self.app.domains[qube]
                qube.fire_event("property-reset:is_preload", name="is_preload")

    @qubes.events.handler("property-pre-set:template_for_dispvms")
    def __on_pre_set_dvmtemplate(
        self, event, name, newvalue, oldvalue=None
    ) -> None:
        """
        Forbid disabling ``template_for_dispvms`` while there are disposables
        running.

        :param str event: Event which was fired.
        :param str name: Property name.
        :param bool newvalue: New value of the property.
        :param bool oldvalue: Old value of the property.
        """
        # pylint: disable=unused-argument
        if newvalue:
            return
        if any(self.dispvms):
            raise qubes.exc.QubesVMInUseError(
                self,
                "Cannot change template_for_dispvms to False while there are "
                "some disposables based on this disposable template",
            )

    @qubes.events.handler("property-pre-del:template_for_dispvms")
    def __on_pre_del_dvmtemplate(self, event, name, oldvalue=None) -> None:
        """
        Forbid disabling ``template_for_dispvms`` while there are disposables
        running.

        :param str event: Event which was fired.
        :param str name: Property name.
        :param bool oldvalue: Old value of the property.
        """
        self.__on_pre_set_dvmtemplate(event, name, False, oldvalue)

    @qubes.events.handler("property-pre-set:template")
    def __on_pre_property_set_template(
        self, event, name, newvalue, oldvalue=None
    ):
        """
        Forbid changing ``template`` while there are disposables running.

        :param str event: Event which was fired.
        :param str name: Property name.
        :param qubes.vm.templatevm.TemplateVM newvalue: New value of the \
                property.
        :param qubes.vm.templatevm.TemplateVM oldvalue: Old value of the \
                property.
        """
        # pylint: disable=unused-argument
        for vm in self.dispvms:
            if vm.is_running():
                raise qubes.exc.QubesVMNotHaltedError(
                    self,
                    "Cannot change template while there are running disposables"
                    " based on this disposable template",
                )

    @qubes.events.handler("property-set:template")
    def __on_property_set_template(
        self, event, name, newvalue, oldvalue=None
    ) -> None:
        # pylint: disable=unused-argument
        pass

    @qubes.events.handler(
        "domain-preload-dispvm-used",
        "domain-preload-dispvm-autostart",
        "domain-preload-dispvm-start",
    )
    async def on_domain_preload_dispvm_used(
        self,
        event: str,
        dispvm: Optional["qubes.vm.dispvm.DispVM"] = None,
        reason: Optional[str] = None,
        delay: Union[int, float] = 0,
        **kwargs,  # pylint: disable=unused-argument
    ) -> None:
        """
        Offloads on excess and preload on vacancy. On ``autostart``, the
        preloaded list is emptied before preloading.

        :param str event: Event which was fired. Events have the prefix \
            ``domain-preload-dispvm-``. If the suffix is ``autostart``, the \
            preload list is emptied before attempting to preload. If the \
            suffix is ``used`` or ``start``, tries to preload until it fills \
            gaps.
        :param qubes.vm.dispvm.DispVM dispvm: Disposable that was used
        :param str reason: Why the event was fired
        :param float delay: Proceed only after sleeping that many seconds
        """
        assert isinstance(self, qubes.vm.BaseVM)
        event = event.removeprefix("domain-preload-dispvm-")
        event_log = "Received preload event '%s'" % str(event)
        if event == "used" and dispvm:
            event_log += " for dispvm '%s'" % str(dispvm)
        if reason:
            event_log += " because %s" % str(reason)
        if delay:
            event_log += " with a delay of %s second(s)" % f"{delay:.1f}"
        self.log.info(event_log)
        service = "qubes.WaitForRunningSystem"
        if not self.supports_preload():
            raise qubes.exc.QubesValueError(
                "Qube does not support the RPC '%s' but tried to preload, "
                "check if template is outdated" % service
            )
        if delay:
            await asyncio.sleep(delay)

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
                available_memory = max(
                    0, int(file.read()) - self.get_feat_preload_threshold()
                )
        except FileNotFoundError:
            can_preload = want_preload
            self.log.warning("File containing available memory was not found")
        if available_memory is not None:
            memory = getattr(self, "memory", 0) * 1024**2
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
                # requesting a non-preloaded disposable.
                return

        self.log.info("Preloading '%d' qube(s)", can_preload)
        async with asyncio.TaskGroup() as task_group:
            for _ in range(can_preload):
                task_group.create_task(
                    qubes.vm.dispvm.DispVM.from_appvm(self, preload=True)
                )

    def get_feat_preload_threshold(self) -> int:
        """
        Get the ``preload-dispvm-threshold`` feature as int (bytes unit).

        :rtype: int
        """
        assert isinstance(self, qubes.vm.BaseVM)
        feature = "preload-dispvm-threshold"
        global_features = self.app.domains["dom0"].features
        value = int(global_features.get(feature) or 0)
        return value * 1024**2

    def get_feat_preload(self) -> list[str]:
        """
        Get the ``preload-dispvm`` feature as a list.

        :rtype: list[str]
        """
        assert isinstance(self, qubes.vm.BaseVM)
        feature = "preload-dispvm"
        value = self.features.get(feature, "")
        return value.split(" ") if value else []

    def get_feat_global_preload_max(self) -> Optional[int]:
        """
        Get the global ``preload-dispvm-max`` feature as an integer if it is
        set, None otherwise.

        :rtype: Optional[int]
        """
        assert isinstance(self, qubes.vm.BaseVM)
        feature = "preload-dispvm-max"
        value = None
        global_features = self.app.domains["dom0"].features
        if feature in global_features:
            value = int(global_features.get(feature) or 0)
        return value

    def get_feat_preload_max(self, force_local=False) -> int:
        """
        Get the ``preload-dispvm-max`` feature as an integer.

        :param bool force_local: ignore global setting.
        :rtype: Optional[int]
        """
        assert isinstance(self, qubes.vm.BaseVM)
        feature = "preload-dispvm-max"
        value = None
        if not force_local and self == getattr(
            self.app, "default_dispvm", None
        ):
            value = self.get_feat_global_preload_max()
        if value is None:
            value = self.features.get(feature)
        return int(value or 0)

    def is_global_preload_set(self) -> bool:
        """
        Check if this qube is the global default_dispvm and the global preload
        feature is set.

        :rtype: bool
        """
        assert isinstance(self, qubes.vm.BaseVM)
        if (
            self == getattr(self.app, "default_dispvm", None)
            and "preload-dispvm-max" in self.app.domains["dom0"].features
        ):
            return True
        return False

    def is_global_preload_distinct(self) -> bool:
        """
        Check if global preload feature is distinct compared to local one.

        :rtype: bool
        """
        if (
            self.get_feat_global_preload_max() or 0
        ) != self.get_feat_preload_max(force_local=True):
            return True
        return False

    def can_preload(self) -> bool:
        """
        Check if there is preload vacancy.

        :rtype: bool
        """
        preload_dispvm_max = self.get_feat_preload_max()
        preload_dispvm = self.get_feat_preload()
        if len(preload_dispvm) < preload_dispvm_max:
            return True
        return False

    async def refresh_preload(self) -> None:
        """
        Refresh disposables which have outdated volumes.
        """
        assert isinstance(self, qubes.vm.BaseVM)
        outdated = []
        for qube in self.dispvms:
            if not qube.is_preload or not any(
                vol.is_outdated() for vol in qube.volumes.values()
            ):
                continue
            outdated.append(qube)
            self.remove_preload_from_list([qube.name])
        if outdated:
            tasks = [self.app.domains[qube].cleanup() for qube in outdated]
            asyncio.ensure_future(asyncio.gather(*tasks))
            # Delay to not overload the system with cleanup+preload.
            asyncio.ensure_future(
                self.fire_event_async(
                    "domain-preload-dispvm-start",
                    reason="of outdated volume(s)",
                    delay=4,
                )
            )

    def remove_preload_from_list(self, disposables: list[str]) -> None:
        """
        Removes list of preload qubes from the list.

        :param list[str] disposables: disposable names to remove from list.
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
        """
        Removes preloaded qubes that exceeds the maximum specified.

        :param Optional[int] max_preload: Maximum number of preloaded that \
                should exist.
        """
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

    def supports_preload(self) -> bool:
        """
        Check if the necessary RPC is supported.

        :rtype: bool
        """
        assert isinstance(self, qubes.vm.BaseVM)
        service = "qubes.WaitForRunningSystem"
        supported_service = "supported-rpc." + service
        if self.features.check_with_template(supported_service, False):
            return True
        return False
