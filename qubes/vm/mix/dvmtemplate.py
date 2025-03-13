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
        value = self.features.get(feature, "")
        return value.split(" ") if value else []

    def get_feat_preload_max(self) -> int:
        feature = "preload-dispvm-max"
        return int(self.features.get(feature, 0))

    def can_preload(self) -> bool:
        preload_dispvm_max = self.get_feat_preload_max()
        preload_dispvm = self.get_feat_preload()
        if preload_dispvm_max == 0:
            return False
        if preload_dispvm and len(preload_dispvm) >= preload_dispvm_max:
            return False
        return True

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
        if event == "domain-preloaded-dispvm-autostart":
            self.features["preload-dispvm"] = ""
        await asyncio.sleep(delay)
        if not self.can_preload():
            return
        while True:
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
            available_memory = psutil.virtual_memory().available / (
                1024 * 1024
            )
            threshold = 1024 * 5
            if memory >= (available_memory - threshold):
                dispvm = await qubes.vm.dispvm.DispVM.from_appvm(
                    self, preload=True
                )
                await dispvm.start()
                # TODO: how to pass arg?
                # await qubes.api.admin.QubesAdminAPI.create_disposable(
                #    self.app, b"dom0", "admin.vm.CreateDisposable", b"dom0", b"preload"
                # )
                #
                # TODO:
                #  Ben:
                #    What to do if the maximum is never reached on autostart as
                #    there is not enough memory, and then a preloaded DispVM is
                #    used, calling for the creation of another one, while the
                #    autostart will also try to create one. Is this a race
                #    condition?
                # Marek:
                #    async lock, break on any event when max is reached.
                #
                # TODO: fire event after start of all qubes that are set to
                # autostart.
                if event == "domain-preloaded-dispvm-autostart":
                    if self.can_preload():
                        continue
                break
            await asyncio.sleep(delay)

    @property
    def dispvms(self):
        """Returns a generator containing all Disposable VMs based on the
        current AppVM.
        """
        for vm in self.app.domains:
            if getattr(vm, "template", None) == self:
                yield vm
