# coding=utf-8
#
# The Qubes OS Project, https://www.qubes-os.org
#
# Copyright (C) 2023  Piotr Bartman-Szwarc <prbartman@invisiblethingslab.com>
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301,
# USA.
import importlib
import asyncio
import subprocess

import qubes

from typing import Type

from qubes import device_protocol


def device_list_change(
        ext: qubes.ext.Extension, current_devices,
        vm, path, device_class: Type[qubes.device_protocol.DeviceInfo]
):
    devclass = device_class.__name__[:-len('Device')].lower()

    if path is not None:
        vm.fire_event(f'device-list-change:{devclass}')

    added, attached, detached, removed = (
        compare_device_cache(vm, ext.devices_cache, current_devices))

    # send events about devices detached/attached outside by themselves
    for dev_id, front_vm in detached.items():
        dev = device_class(vm, dev_id)
        asyncio.ensure_future(front_vm.fire_event_async(
            f'device-detach:{devclass}', device=dev))
    for dev_id in removed:
        device = device_class(vm, dev_id)
        vm.fire_event(f'device-removed:{devclass}', device=device)
    for dev_id in added:
        device = device_class(vm, dev_id)
        vm.fire_event(f'device-added:{devclass}', device=device)
    for dev_ident, front_vm in attached.items():
        dev = device_class(vm, dev_ident)
        # options are unknown, device already attached
        asyncio.ensure_future(front_vm.fire_event_async(
            f'device-attach:{devclass}', device=dev, options={}))

    ext.devices_cache[vm.name] = current_devices

    to_attach = {}
    for front_vm in vm.app.domains:
        if not front_vm.is_running():
            continue
        for assignment in front_vm.devices[devclass].get_assigned_devices():
            if (assignment.backend_domain == vm
                    and assignment.device_identity
                        == assignment.device.self_identity
                    and assignment.ident in added
                    and assignment.ident not in attached
            ):
                frontends = to_attach.get(assignment.ident, {})
                frontends[front_vm] = assignment
                to_attach[assignment.ident] = frontends

    for ident, frontends in to_attach.items():
        if len(frontends) > 1:
            device = tuple(frontends.values())[0].device
            target_name = confirm_device_attachment(device, frontends)
            for front in frontends:
                if front.name == target_name:
                    target = front
                    assignment = frontends[front]
                    # already asked
                    if assignment.mode.value == "ask-to-attach":
                        assignment.mode = device_protocol.AssignmentMode.AUTO
                    break
            else:
                return
        else:
            target = tuple(frontends.keys())[0]
            assignment = frontends[target]

        asyncio.ensure_future(ext.attach_and_notify(target, assignment))


def compare_device_cache(vm, devices_cache, current_devices):
    # compare cached devices and current devices, collect:
    # - newly appeared devices (ident)
    # - devices attached from a vm to frontend vm (ident: frontend_vm)
    # - devices detached from frontend vm (ident: frontend_vm)
    # - disappeared devices, e.g., plugged out (ident)
    added = set()
    attached = {}
    detached = {}
    removed = set()
    cache = devices_cache[vm.name]
    for dev_id, front_vm in current_devices.items():
        if dev_id not in cache:
            added.add(dev_id)
            if front_vm is not None:
                attached[dev_id] = front_vm
        elif cache[dev_id] != front_vm:
            cached_front = cache[dev_id]
            if front_vm is None:
                detached[dev_id] = cached_front
            elif cached_front is None:
                attached[dev_id] = front_vm
            else:
                # a front changed from one to another, so we signal it as:
                # detach from the first one and attach to the second one.
                detached[dev_id] = cached_front
                attached[dev_id] = front_vm

    for dev_id, cached_front in cache.items():
        if dev_id not in current_devices:
            removed.add(dev_id)
            if cached_front is not None:
                detached[dev_id] = cached_front
    return added, attached, detached, removed


def confirm_device_attachment(device, frontends) -> str:
    guivm = 'dom0'  # TODO
    # TODO: guivm rpc?

    proc = subprocess.Popen(
        ["attach-confirm", guivm,
         device.backend_domain.name, device.ident,
         device.description,
         *[f.name for f in frontends.keys()]],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (target_name, _) = proc.communicate()
    return target_name.decode()
