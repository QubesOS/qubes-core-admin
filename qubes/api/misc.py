# -*- encoding: utf8 -*-
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

"""Interface for methods not being part of Admin API, but still handled by
qubesd."""

import string
from datetime import datetime

import qubes.api
import qubes.api.admin
import qubes.vm.dispvm


class QubesMiscAPI(qubes.api.AbstractQubesAPI):
    SOCKNAME = "/var/run/qubesd.misc.sock"

    @qubes.api.method("qubes.FeaturesRequest", no_payload=True)
    async def qubes_features_request(self):
        """qubes.FeaturesRequest handler

        VM (mostly templates) can request some features from dom0 for itself.
        Then dom0 (qubesd extension) may respect this request or ignore it.

        Technically, VM first write requested features into QubesDB in
        `/features-request/` subtree, then call this method. The method will
        dispatch 'features-request' event, which may be handled by
        appropriate extensions. Requests not explicitly handled by some
        extension are ignored.
        """
        self.enforce(self.dest.name == "dom0")
        self.enforce(not self.arg)

        prefix = "/features-request/"

        keys = self.src.untrusted_qdb.list(prefix)
        untrusted_features = {
            key[len(prefix) :]: self.src.untrusted_qdb.read(key).decode(
                "ascii", errors="strict"
            )
            for key in keys
        }

        safe_set = string.ascii_letters + string.digits + "-.,_= "
        for untrusted_key in untrusted_features:
            untrusted_value = untrusted_features[untrusted_key]
            self.enforce(all((c in safe_set) for c in untrusted_value))

        await self.src.fire_event_async(
            "features-request", untrusted_features=untrusted_features
        )
        self.app.save()

    @qubes.api.method("qubes.NotifyTools", no_payload=True)
    async def qubes_notify_tools(self):
        """
        Legacy version of qubes.FeaturesRequest, used by Qubes Windows Tools
        """
        self.enforce(self.dest.name == "dom0")
        self.enforce(not self.arg)

        untrusted_features = {}
        safe_set = string.ascii_letters + string.digits
        expected_features = (
            "qrexec",
            "gui",
            "gui-emulated",
            "default-user",
            "os",
        )
        for feature in expected_features:
            untrusted_value = self.src.untrusted_qdb.read(
                "/qubes-tools/" + feature
            )
            if untrusted_value:
                untrusted_value = untrusted_value.decode(
                    "ascii", errors="strict"
                )
                self.enforce(all((c in safe_set) for c in untrusted_value))
                untrusted_features[feature] = untrusted_value
            del untrusted_value

        await self.src.fire_event_async(
            "features-request", untrusted_features=untrusted_features
        )
        self.app.save()

    @qubes.api.method("qubes.NotifyUpdates")
    async def qubes_notify_updates(self, untrusted_payload):
        """
        Receive VM notification about updates availability

        Payload contains a single integer - either 0 (no updates) or some
        positive value (some updates).
        """

        untrusted_update_count = untrusted_payload.strip()
        self.enforce(untrusted_update_count.isdigit())
        # now sanitized
        update_count = int(untrusted_update_count)
        del untrusted_update_count

        # look for the nearest updateable VM up in the template chain
        updateable_template = getattr(self.src, "template", None)
        while (
            updateable_template is not None
            and not updateable_template.updateable
        ):
            updateable_template = getattr(updateable_template, "template", None)

        if self.src.updateable:
            # Just trust information from VM itself
            self._feature_of_update(self.src, bool(update_count))
            self.app.save()
        elif updateable_template is not None:
            # Hint about updates availability in template
            # If template is running - it will notify about updates itself
            if updateable_template.is_running():
                return
            # Ignore no-updates info
            if update_count > 0:
                # If VM is outdated, updates were probably already installed
                # in the template - ignore info
                if self.src.storage.outdated_volumes:
                    return
                self._feature_of_update(updateable_template, bool(update_count))
                self.app.save()

    @staticmethod
    def _feature_of_update(qube, new_updates_available):
        current_date = datetime.today().strftime("%Y-%m-%d %H:%M:%S")
        old_updates_available = qube.features.get("updates-available", False)
        if old_updates_available and not new_updates_available:
            qube.features["last-update"] = current_date
        qube.features["updates-available"] = new_updates_available
        qube.features["last-updates-check"] = current_date
