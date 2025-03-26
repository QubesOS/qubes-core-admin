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
import psutil

import qubes.vm.dispvm
import qubes.events


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

    def get_feat_preload(self) -> list:
        feature = "preload-dispvm"
        # TODO: fix, mypy throws:
        # error: "DVMTemplateMixin" has no attribute "features"  [attr-defined]
        value = self.features.get(feature, "")  # type: ignore
        return value.split(" ") if value else []

    def get_feat_preload_max(self) -> int:
        feature = "preload-dispvm-max"
        # TODO: fix, mypy throws:
        # error: "DVMTemplateMixin" has no attribute "features"  [attr-defined]
        value = self.features.get(feature, 0)  # type: ignore
        return int(value) if value else 0

    def can_preload(self) -> bool:
        preload_dispvm_max = self.get_feat_preload_max()
        preload_dispvm = self.get_feat_preload()
        if len(preload_dispvm) < preload_dispvm_max:
            return True
        return False

    @qubes.events.handler("domain-feature-pre-set:preload-dispvm-max")
    def on_feature_pre_set_preload_dispvm_max(
        self, event, feature, value, oldvalue=None
    ):  # pylint: disable=unused-argument
        if not value.isdigit():
            raise qubes.exc.QubesValueError(
                "Invalid preload-dispvm-max value: not a digit"
            )
        ## TODO: preload disposables in case the limit increases.
        # if not oldvalue or int(newvalue) > int(oldvalue):

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
                f"{error_prefix} can't increment: qube count ({new_len}) "
                f"is bigger than old count ({old_len}) and also bigger than "
                f"preload-dispvm-max ({preload_dispvm_max})"
            )

        if new_len != len(set(new_list)):
            duplicates = [
                qube for qube in set(new_list) if new_list.count(qube) > 1
            ]
            raise qubes.exc.QubesValueError(
                f"{error_prefix} contain duplicates: '{', '.join(duplicates)}'"
            )

        nonqube = [qube for qube in new_list if qube not in self.app.domains]
        if nonqube:
            raise qubes.exc.QubesValueError(
                f"{error_prefix} non qube(s): '{', '.join(nonqube)}'"
            )

        # self.dispvms is outdated at this point.
        nonderived = [
            qube
            for qube in new_list
            if getattr(self.app.domains[qube], "template") != self
        ]
        if nonderived:
            raise qubes.exc.QubesValueError(
                f"{error_prefix} qube(s) not based on {self.name}: "
                f"'{', '.join(nonderived)}'"
            )

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
        "domain-preloaded-dispvm-used", "domain-preloaded-dispvm-autostart"
    )
    async def on_domain_preloaded_dispvm_used(
        self, event, delay=5, **kwargs
    ):  # pylint: disable=unused-argument
        """When preloaded DispVM is used or after boot, preload another one.

        :param event: event which was fired
        :param delay: seconds between trials
        :returns:
        """
        # TODO: add a refill event in case the limit is increased?
        if event == "domain-preloaded-dispvm-autostart":
            self.features["preload-dispvm"] = ""
        if not self.can_preload():
            return
        while True:
            await asyncio.sleep(delay)
            # TODO:
            # Ben:
            #   Is there existing Qubes code that checks available memory
            #   before starting a qube?
            # Marek:
            #   I get what you mean, but this will not work. This looks only at
            #   free memory in dom0, not the whole system. And even if it would
            #   look more globally, qmemman tries to allocate available memory
            #   as much as possible. Only qmemman knows how much "free" memory
            #   you really have, and currently there is no API to query that...
            # Ben:
            #   For last...
            memory = getattr(self, "memory", 0)
            available_memory = psutil.virtual_memory().available / (1024 * 1024)
            threshold = 1024 * 5
            if memory >= (available_memory - threshold):
                await qubes.vm.dispvm.DispVM.from_appvm(self, preload=True)
                # TODO:
                #  Ben:
                #    What to do if the maximum is never reached on autostart as
                #    there is not enough memory, and then a preloaded DispVM is
                #    used, calling for the creation of another one, while the
                #    autostart will also try to create one. Is this a race
                #    condition?
                # Marek:
                #    async lock, break on any event when max is reached.
                # Ben:
                #    Leaving this comment for future implementation of a new
                #    event, one that can refill preloaded DispVMs up to the
                #    maximum.
                if (
                    event == "domain-preloaded-dispvm-autostart"
                    and self.can_preload()
                ):
                    continue
                break

    @property
    def dispvms(self):
        """Returns a generator containing all Disposable VMs based on the
        current AppVM.
        """
        for vm in self.app.domains:
            if getattr(vm, "template", None) == self:
                yield vm
