# -*- encoding: utf8 -*-
#
# The Qubes OS Project, http://www.qubes-os.org
#
# Copyright (C) 2017 Wojtek Porczyk <woju@invisiblethingslab.com>
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
import importlib

import qubes.api
import qubes.api.internal
import qubes.exc
import qubes.ext
import qubes.vm.adminvm
from qrexec.policy import utils, parser

from qubes.device_protocol import DeviceInterface


class JustEvaluateAskResolution(parser.AskResolution):
    async def execute(self):
        pass


class JustEvaluateAllowResolution(parser.AllowResolution):
    async def execute(self):
        pass


class AdminExtension(qubes.ext.Extension):
    def __init__(self):
        super().__init__()
        # during tests, __init__() of the extension can be called multiple
        # times, because there are multiple Qubes() object instances
        if not hasattr(self, "policy_cache"):
            self.policy_cache = utils.PolicyCache(lazy_load=True)
            self.policy_cache.initialize_watcher()

    # pylint: disable=too-few-public-methods
    @qubes.ext.handler(
        "admin-permission:admin.vm.tag.Set",
        "admin-permission:admin.vm.tag.Remove",
    )
    def on_tag_set_or_remove(self, vm, event, arg, **kwargs):
        """Forbid changing specific tags"""
        # pylint: disable=unused-argument
        if arg.startswith("created-by-") and not isinstance(
            vm, qubes.vm.adminvm.AdminVM
        ):
            raise qubes.exc.PermissionDenied(
                "changing this tag is prohibited by {}.{}".format(
                    __name__, type(self).__name__
                )
            )

    # TODO create that tag here (need to figure out how to pass mgmtvm name)

    @qubes.ext.handler("admin-permission:admin.vm.List")
    def admin_vm_list(self, vm, event, arg, **kwargs):
        """When called with target 'dom0' (aka "get full list"), exclude domains
        that the caller don't have permission to list
        """
        # pylint: disable=unused-argument

        if vm.klass == "AdminVM":
            # dom0 can always list everything
            return None

        if not hasattr(vm, "app"):
            # process cleanup, do not allow listing VMs anymore
            return ((lambda _vm: False),)

        policy = self.policy_cache.get_policy()
        system_info = qubes.api.internal.get_system_info(vm.app)

        def filter_vms(dest_vm):
            request = parser.Request(
                "admin.vm.List",
                "+" + arg,
                vm.name,
                dest_vm.name,
                system_info=system_info,
                ask_resolution_type=JustEvaluateAskResolution,
                allow_resolution_type=JustEvaluateAllowResolution,
            )
            try:
                resolution = policy.evaluate(request)
                # do not consider 'ask' as allow here,
                # this needs to be not interactive
                return isinstance(resolution, parser.AllowResolution)
            except parser.AccessDenied:
                return False

        return (filter_vms,)

    @qubes.ext.handler("admin-permission:admin.Events")
    def admin_events(self, vm, event, arg, **kwargs):
        """When called with target 'dom0' (aka "get all events"),
        exclude domains that the caller don't have permission to receive
        events about
        """
        # pylint: disable=unused-argument

        if vm.klass == "AdminVM":
            # dom0 can always list everything
            return None

        def filter_events(event):
            subject, event, kwargs = event
            try:
                dest = subject.name
            except AttributeError:
                # domain-add and similar events fired on the Qubes() object
                if "vm" in kwargs:
                    dest = kwargs["vm"].name
                else:
                    dest = "@adminvm"

            if not hasattr(vm, "app"):
                # process cleanup, do not send events anymore
                return False

            policy = self.policy_cache.get_policy()
            # TODO: cache system_info (based on last qubes.xml write time?)
            system_info = qubes.api.internal.get_system_info(vm.app)
            request = parser.Request(
                "admin.Events",
                "+" + event.replace(":", "_"),
                vm.name,
                dest,
                system_info=system_info,
                ask_resolution_type=JustEvaluateAskResolution,
                allow_resolution_type=JustEvaluateAllowResolution,
            )
            try:
                resolution = policy.evaluate(request)
                # do not consider 'ask' as allow here,
                # this needs to be not interactive
                return isinstance(resolution, parser.AllowResolution)
            except parser.AccessDenied:
                return False

        return (filter_events,)

    @qubes.ext.handler("qubes-close", system=True)
    def on_qubes_close(self, app, event, **kwargs):
        """Unregister policy file watches on app.close()."""
        # pylint: disable=unused-argument
        if hasattr(self, "policy_cache"):
            self.policy_cache.cleanup()
            del self.policy_cache

    @qubes.ext.handler("domain-tag-add:created-by-*")
    def on_tag_add(self, vm, event, tag, **kwargs):
        """Add extra tags based on creators 'tag-created-vm-with' feature"""
        # pylint: disable=unused-argument
        created_by = vm.app.domains[tag.partition("created-by-")[2]]
        tag_with = created_by.features.get("tag-created-vm-with", "")
        for tag_with_single in tag_with.split():
            vm.tags.add(tag_with_single)

    @qubes.ext.handler(
        *(
            f"admin-permission:admin.vm.device.{ep.name}.Attach"
            for ep in importlib.metadata.entry_points(group="qubes.devices")
        )
    )
    def on_device_attach(self, vm, event, dest, arg, device, mode, **kwargs):
        # pylint: disable=unused-argument,too-many-positional-arguments
        # ignore auto-attachment
        if mode != "manual":
            return

        # check if any presented interface is on denied list
        denied = set(DeviceInterface.from_str_bulk(dest.devices_denied))
        for pattern in denied:
            for devint in device.interfaces:
                if pattern.matches(devint):
                    raise qubes.exc.PermissionDenied(
                        f"Device exposes a banned interface: {devint}"
                    )
