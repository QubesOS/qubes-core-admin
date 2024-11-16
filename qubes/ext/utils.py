# coding=utf-8
#
# The Qubes OS Project, https://www.qubes-os.org
#
# Copyright (C) 2024  Piotr Bartman-Szwarc <prbartman@invisiblethingslab.com>
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
import sys
from typing import Type, Dict

import qubes.ext
from qrexec.server import call_socket_service
from qubes import device_protocol
from qubes.device_protocol import VirtualDevice, Port

SOCKET_PATH = "/var/run/qubes"


def device_list_change(
    ext: qubes.ext.Extension,
    current_devices,
    vm,
    path,
    device_class: Type[qubes.device_protocol.DeviceInfo],
):
    devclass = device_class.__name__[: -len("Device")].lower()

    if path is not None:
        vm.fire_event(f"device-list-change:{devclass}")

    added, attached, detached, removed = compare_device_cache(
        vm, ext.devices_cache, current_devices
    )

    # send events about devices detached/attached outside by themselves
    for port_id, front_vm in detached.items():
        device = device_class(
            Port(backend_domain=vm, port_id=port_id, devclass=devclass)
        )
        ext.ensure_detach(front_vm, device.port)
        asyncio.ensure_future(
            front_vm.fire_event_async(
                f"device-detach:{devclass}", port=device.port
            )
        )
    for port_id in removed:
        device = device_class(
            Port(backend_domain=vm, port_id=port_id, devclass=devclass)
        )
        vm.fire_event(f"device-removed:{devclass}", port=device.port)
    for port_id in added:
        device = device_class(
            Port(backend_domain=vm, port_id=port_id, devclass=devclass)
        )
        vm.fire_event(f"device-added:{devclass}", device=device)
    for port_id, front_vm in attached.items():
        device = device_class(
            Port(backend_domain=vm, port_id=port_id, devclass=devclass)
        )
        # options are unknown, device already attached
        asyncio.ensure_future(
            front_vm.fire_event_async(
                f"device-attach:{devclass}", device=device, options={}
            )
        )

    ext.devices_cache[vm.name] = current_devices

    to_attach: Dict[str, Dict] = {}
    for front_vm in vm.app.domains:
        if not front_vm.is_running():
            continue
        for assignment in reversed(
            sorted(front_vm.devices[devclass].get_assigned_devices())
        ):
            for device in assignment.devices:
                if (
                    assignment.matches(device)
                    and device.port_id in added
                    and device.port_id not in attached
                ):
                    frontends = to_attach.get(device.port_id, {})
                    # make it unique
                    ass = assignment.clone(
                        device=VirtualDevice(device.port, device.device_id)
                    )
                    curr = frontends.get(front_vm, None)
                    if curr is None or curr < ass:
                        # chose the most specific assignment
                        frontends[front_vm] = ass
                    to_attach[device.port_id] = frontends

    asyncio.ensure_future(resolve_conflicts_and_attach(ext, to_attach))


async def resolve_conflicts_and_attach(ext, to_attach):
    for _, frontends in to_attach.items():
        if len(frontends) > 1:
            # unique
            device = tuple(frontends.values())[0].device
            target_name = await confirm_device_attachment(device, frontends)
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

        await ext.attach_and_notify(target, assignment)


def compare_device_cache(vm, devices_cache, current_devices):
    # compare cached devices and current devices, collect:
    # - newly appeared devices (port_id)
    # - devices attached from a vm to frontend vm (port_id: frontend_vm)
    # - devices detached from frontend vm (port_id: frontend_vm)
    # - disappeared devices, e.g., plugged out (port_id)
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


async def confirm_device_attachment(device, frontends) -> str:
    try:
        return await _do_confirm_device_attachment(device, frontends)
    except Exception as exc:
        print(str(exc.__class__.__name__) + ":", str(exc), file=sys.stderr)
        return ""


async def _do_confirm_device_attachment(device, frontends):
    socket = "device-agent.GUI"

    app = tuple(frontends.keys())[0].app
    doms = app.domains

    front_names = [f.name for f in frontends.keys()]

    try:
        guivm = doms["dom0"].guivm.name
    except AttributeError:
        guivm = "dom0"

    number_of_targets = len(front_names)

    params = {
        "source": device.backend_domain.name,
        "device_name": device.description,
        "argument": device.port_id,
        "targets": front_names,
        "default_target": front_names[0] if number_of_targets == 1 else "",
        "icons": {
            (
                dom.name if dom.klass != "DispVM" else f"@dispvm:{dom.name}"
            ): dom.icon
            for dom in doms.values()
        },
    }

    socked_call = asyncio.create_task(
        call_socket_service(guivm, socket, "dom0", params, SOCKET_PATH)
    )

    while not socked_call.done():
        await asyncio.sleep(0.1)

    ask_response = await socked_call

    if ask_response.startswith("allow:"):
        chosen = ask_response[len("allow:") :]
        if chosen in front_names:
            return chosen
    return ""
