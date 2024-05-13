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
import asyncio

import qubes


def device_list_change(
        ext: qubes.ext.Extension, current_devices,
        vm, path, device_class: qubes.device_protocol.DeviceInfo
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

    for front_vm in vm.app.domains:
        if not front_vm.is_running():
            continue
        for assignment in front_vm.devices[devclass].get_assigned_devices():
            if (assignment.backend_domain == vm
                    and assignment.ident in added
                    and assignment.ident not in attached
            ):
                ext.notify_auto_attached(
                    front_vm, assignment.device, assignment.options)


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
