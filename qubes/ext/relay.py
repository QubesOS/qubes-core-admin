#
# The Qubes OS Project, https://www.qubes-os.org/
#
# Copyright (C) 2024 Frédéric Pierret <frederic.pierret@qubes-os.org>
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
#

import qubes.ext
import qubes.vm.remotevm


class Relay(qubes.ext.Extension):
    # pylint: disable=unused-argument
    @qubes.ext.handler("domain-init", "domain-load")
    def on_domain_init_load(self, vm, event):
        if (
            getattr(vm, "relayvm", None)
            and "relayvm-" + vm.relayvm.name not in vm.tags
        ):
            self.on_property_set(vm, event, name="relayvm", newvalue=vm.relayvm)

    @qubes.ext.handler("domain-start")
    def on_domain_start(self, vm, event, **kwargs):
        if not vm.untrusted_qdb:
            return
        for domain in vm.app.domains:
            if getattr(domain, "relayvm", None) == vm:
                vm.untrusted_qdb.write(
                    f"/remote/{domain.name}", domain.remote_name or domain.name
                )

    @qubes.ext.handler("property-reset:relayvm", vm=qubes.vm.remotevm.RemoteVM)
    def on_property_reset(self, subject, event, name, oldvalue=None):
        newvalue = getattr(subject, "relayvm", None)
        self.on_property_set(subject, event, name, newvalue, oldvalue)

    @qubes.ext.handler("property-set:relayvm", vm=qubes.vm.remotevm.RemoteVM)
    def on_property_set(self, subject, event, name, newvalue, oldvalue=None):
        # Clean other 'relayvm-XXX' tags.
        # qrexec-client-vm can connect to only one domain
        tags_list = list(subject.tags)
        for tag in tags_list:
            if tag.startswith("relayvm-"):
                subject.tags.remove(tag)

        if newvalue:
            relayvm_tag = "relayvm-" + newvalue.name
            subject.tags.add(relayvm_tag)
            if newvalue.untrusted_qdb:
                remote_name = subject.remote_name or subject.name
                newvalue.untrusted_qdb.write(
                    f"/remote/{subject.name}", remote_name
                )
