# -*- encoding: utf-8 -*-
#
# The Qubes OS Project, http://www.qubes-os.org
#
# Copyright (C) 2017 Marek Marczykowski-Górecki
#                               <marmarek@invisiblethingslab.com>
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

"""Internal interface for dom0 components to communicate with qubesd."""

import asyncio
import json
import os
import subprocess

import qubes.api
import qubes.api.admin
import qubes.vm.adminvm
import qubes.vm.dispvm


PREVIOUSLY_PAUSED = "/run/qubes/previously-paused.list"


class SystemInfoCache:
    cache = None
    cache_for_app = None

    # list of VM events that may affect the content of system_info
    vm_events = (
        "domain-spawn",
        "domain-start",
        "domain-shutdown",
        "domain-tag-add:*",
        "domain-tag-delete:*",
        "domain-feature-set:internal",
        "domain-feature-delete:internal",
        "property-set:template_for_dispvms",
        "property-reset:template_for_dispvms",
        "property-set:default_dispvm",
        "property-reset:default_dispvm",
        "property-set:icon",
        "property-reset:icon",
        "property-set:guivm",
        "property-reset:guivm",
        "property-set:relayvm",
        "property-reset:relayvm",
        "property-set:transport_rpc",
        "property-reset:transport_rpc",
        # technically not changeable, but keep for consistency
        "property-set:uuid",
        "property-reset:uuid",
    )

    @classmethod
    def event_handler(cls, subject, event, **kwargs):
        """Invalidate cache on specific events"""
        # pylint: disable=unused-argument
        cls.cache = None

    @classmethod
    def on_domain_add(cls, subject, event, vm):
        # pylint: disable=unused-argument
        cls.register_events_vm(vm)

    @classmethod
    def on_domain_delete(cls, subject, event, vm):
        # pylint: disable=unused-argument
        cls.unregister_events_vm(vm)

    @classmethod
    def register_events_vm(cls, vm):
        for event in cls.vm_events:
            vm.add_handler(event, cls.event_handler)

    @classmethod
    def unregister_events_vm(cls, vm):
        for event in cls.vm_events:
            vm.remove_handler(event, cls.event_handler)

    @classmethod
    def unregister_events(cls, app):
        app.remove_handler("domain-add", cls.on_domain_add)
        app.remove_handler("domain-delete", cls.on_domain_delete)
        for vm in app.domains:
            cls.unregister_events_vm(vm)

    @classmethod
    def register_events(cls, app):
        app.add_handler("domain-add", cls.on_domain_add)
        app.add_handler("domain-delete", cls.on_domain_delete)
        for vm in app.domains:
            cls.register_events_vm(vm)

    @classmethod
    def get_system_info(cls, app):
        if cls.cache_for_app is not app:
            # new Qubes() instance created, invalidate the cache
            # this is relevant mostly for tests, otherwise Qubes() object is
            # never re-created
            cls.cache = None
            if cls.cache_for_app is not None:
                cls.unregister_events(cls.cache_for_app)
            cls.register_events(app)
        if cls.cache is not None:
            return cls.cache
        system_info = {
            "domains": {
                domain.name: {
                    "internal": domain.features.get("internal", None),
                    "tags": list(domain.tags),
                    "type": domain.__class__.__name__,
                    "template_for_dispvms": getattr(
                        domain, "template_for_dispvms", False
                    ),
                    "default_dispvm": (
                        domain.default_dispvm.name
                        if getattr(domain, "default_dispvm", None)
                        else None
                    ),
                    "icon": str(domain.label.icon),
                    "guivm": (
                        domain.guivm.name
                        if getattr(domain, "guivm", None)
                        else None
                    ),
                    "relayvm": (
                        domain.relayvm.name
                        if getattr(domain, "relayvm", None)
                        else None
                    ),
                    "transport_rpc": (
                        domain.transport_rpc
                        if getattr(domain, "transport_rpc", None)
                        else None
                    ),
                    "power_state": domain.get_power_state(),
                    "uuid": str(domain.uuid),
                }
                for domain in app.domains
            }
        }
        cls.cache_for_app = app
        cls.cache = system_info
        return system_info


class QubesInternalAPI(qubes.api.AbstractQubesAPI):
    """Communication interface for dom0 components,
    by design the input here is trusted."""

    SOCKNAME = "/var/run/qubesd.internal.sock"

    @qubes.api.method("internal.GetSystemInfo", no_payload=True)
    async def getsysteminfo(self):
        self.enforce(self.dest.name == "dom0")
        self.enforce(not self.arg)

        system_info = SystemInfoCache.get_system_info(self.app)

        return json.dumps(system_info)

    @qubes.api.method(
        "internal.vm.volume.ImportBegin", scope="local", write=True
    )
    async def vm_volume_import(self, untrusted_payload):
        """Begin importing volume data. Payload is either size of new data
        in bytes, or empty. If empty, the current volume's size will be used.
        Returns size and path to where data should be written.

        Triggered by scripts in /etc/qubes-rpc:
        admin.vm.volume.Import, admin.vm.volume.ImportWithSize.

        When the script finish importing, it will trigger
        internal.vm.volume.ImportEnd (with either b'ok' or b'fail' as a
        payload) and response from that call will be actually send to the
        caller.
        """
        self.enforce(self.arg in self.dest.volumes.keys())

        if untrusted_payload:
            original_method = "admin.vm.volume.ImportWithSize"
        else:
            original_method = "admin.vm.volume.Import"
        self.src.fire_event(
            "admin-permission:" + original_method,
            pre_event=True,
            dest=self.dest,
            arg=self.arg,
        )

        if not self.dest.is_halted():
            raise qubes.exc.QubesVMNotHaltedError(self.dest)

        requested_size = (
            self.validate_size(untrusted_payload) if untrusted_payload else None
        )
        del untrusted_payload

        path = await self.dest.storage.import_data(self.arg, requested_size)
        self.enforce(" " not in path)
        if requested_size is None:
            size = self.dest.volumes[self.arg].size
        else:
            size = requested_size

        # when we know the action is allowed, inform extensions that it will
        # be performed
        self.dest.fire_event(
            "domain-volume-import-begin", volume=self.arg, size=size
        )

        return "{} {}".format(size, path)

    @qubes.api.method("internal.vm.volume.ImportEnd")
    async def vm_volume_import_end(self, untrusted_payload):
        """
        This is second half of admin.vm.volume.Import handling. It is called
        when actual import is finished. Response from this method is sent do
        the client (as a response for admin.vm.volume.Import call).

        The payload is either 'ok', or 'fail\n<error message>'.
        """
        self.enforce(self.arg in self.dest.volumes.keys())
        success = untrusted_payload == b"ok"

        try:
            await self.dest.storage.import_data_end(self.arg, success=success)
        except:
            self.dest.fire_event(
                "domain-volume-import-end", volume=self.arg, success=False
            )
            raise

        self.dest.fire_event(
            "domain-volume-import-end", volume=self.arg, success=success
        )

        if not success:
            error = ""
            parts = untrusted_payload.decode("ascii").split("\n", 1)
            if len(parts) > 1:
                error = parts[1]
            raise qubes.exc.QubesException(
                "Data import failed: {}".format(error)
            )

    @qubes.api.method("internal.SuspendPre", no_payload=True)
    async def suspend_pre(self):
        """
        Method called before host system goes to sleep.

        :return:
        """

        preload_templates = qubes.vm.dispvm.get_preload_templates(self.app)
        for qube in preload_templates:
            qube.remove_preload_excess(0)

        # first keep track of VMs which were paused before suspending
        previously_paused = [
            vm.name
            for vm in self.app.domains
            if vm.get_power_state() in ["Paused", "Suspended"]
        ]
        with open(PREVIOUSLY_PAUSED, "w", encoding="ascii") as file:
            file.write("\n".join(previously_paused))

        # then notify all VMs (except paused ones)
        processes = []
        for vm in self.app.domains:
            if isinstance(vm, qubes.vm.adminvm.AdminVM):
                continue
            if not vm.is_running():
                continue
            if vm.name in previously_paused:
                continue
            if not vm.features.check_with_template("qrexec", False):
                continue
            try:
                proc = await vm.run_service(
                    "qubes.SuspendPreAll",
                    user="root",
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                processes.append(proc)
            except qubes.exc.QubesException as e:
                vm.log.warning("Failed to run qubes.SuspendPreAll: %s", str(e))

        if processes:
            done, _ = await asyncio.wait(
                [
                    asyncio.create_task(
                        asyncio.wait_for(p.wait(), qubes.config.suspend_timeout)
                    )
                    for p in processes
                ]
            )
            for task in done:
                try:
                    task.result()
                except asyncio.TimeoutError:
                    self.app.log.warning(
                        "some qube timed out after %d seconds on %s call",
                        qubes.config.suspend_timeout,
                        "qubes.SuspendPreAll",
                    )

        coros = []
        # then suspend/pause VMs
        for vm in self.app.domains:
            if isinstance(vm, qubes.vm.adminvm.AdminVM):
                continue
            if vm.name in previously_paused:
                continue
            if vm.is_running():
                coros.append(asyncio.create_task(vm.suspend()))
        if coros:
            done, _ = await asyncio.wait(coros)
            failed = ""
            for coro in done:
                try:
                    coro.result()
                except Exception as e:  # pylint: disable=broad-except
                    failed += f"\n{e!s}"
            if failed:
                raise qubes.exc.QubesException(
                    "Failed to suspend some qubes: {}".format(failed)
                )

    @qubes.api.method("internal.SuspendPost", no_payload=True)
    async def suspend_post(self):
        """
        Method called after host system wake up from sleep.

        :return:
        """

        # Reload list of previously paused qubes before suspending
        previously_paused = []
        try:
            if os.path.isfile(PREVIOUSLY_PAUSED):
                with open(PREVIOUSLY_PAUSED, encoding="ascii") as file:
                    previously_paused = file.read().split("\n")
                os.unlink(PREVIOUSLY_PAUSED)
        except OSError:
            previously_paused = []

        coros = []
        # first resume/unpause VMs
        for vm in self.app.domains:
            if isinstance(vm, qubes.vm.adminvm.AdminVM):
                continue
            if vm.name in previously_paused:
                continue
            if vm.get_power_state() in ["Paused", "Suspended"]:
                coros.append(asyncio.create_task(vm.resume()))
        if coros:
            await asyncio.wait(coros)

        # then notify all VMs (except previously paused ones)
        processes = []
        for vm in self.app.domains:
            if isinstance(vm, qubes.vm.adminvm.AdminVM):
                continue
            if not vm.is_running():
                continue
            if vm.name in previously_paused:
                continue
            if not vm.features.check_with_template("qrexec", False):
                continue
            try:
                proc = await vm.run_service(
                    "qubes.SuspendPostAll",
                    user="root",
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                processes.append(proc)
            except qubes.exc.QubesException as e:
                vm.log.warning("Failed to run qubes.SuspendPostAll: %s", str(e))

        if processes:
            done, _ = await asyncio.wait(
                [
                    asyncio.create_task(
                        asyncio.wait_for(p.wait(), qubes.config.suspend_timeout)
                    )
                    for p in processes
                ]
            )
            for task in done:
                try:
                    task.result()
                except asyncio.TimeoutError:
                    self.app.log.warning(
                        "some qube timed out after %d seconds on %s call",
                        qubes.config.suspend_timeout,
                        "qubes.SuspendPostAll",
                    )

        preload_templates = qubes.vm.dispvm.get_preload_templates(self.app)
        for qube in preload_templates:
            asyncio.ensure_future(
                qube.fire_event_async("domain-preload-dispvm-autostart")
            )
