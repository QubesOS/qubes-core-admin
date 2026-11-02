#
# The Qubes OS Project, https://www.qubes-os.org/
#
# Copyright (C) 2010  Joanna Rutkowska <joanna@invisiblethingslab.com>
# Copyright (C) 2013-2016  Marek Marczykowski-Górecki
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
#

import qubes.ext
import qubes.vm.qubesvm
import qubes.vm.appvm
import qubes.vm.templatevm
import qubes.utils

yum_proxy_ip = "10.137.255.254"
yum_proxy_port = "8082"


class R3Compatibility(qubes.ext.Extension):
    """Maintain VM interface compatibility with R3.0 and R3.1.
    At least where possible.
    """

    features_to_services = {
        "service.ntpd": "ntpd",
        "check-updates": "qubes-update-check",
        "dvm": "qubes-dvm",
    }

    # noinspection PyUnusedLocal
    @qubes.ext.handler("domain-qdb-create")
    def on_domain_qdb_create(self, vm, event):
        """
        :param qubes.vm.qubesvm.QubesVM vm: \
            VM on which QubesDB entries were just created
        """  # pylint: disable=unused-argument
        # /qubes-vm-type: AppVM, NetVM, ProxyVM, TemplateVM
        if isinstance(vm, qubes.vm.templatevm.TemplateVM):
            vmtype = "TemplateVM"
        elif vm.netvm is not None and vm.provides_network:
            vmtype = "ProxyVM"
        elif vm.netvm is None and vm.provides_network:
            vmtype = "NetVM"
        else:
            vmtype = "AppVM"
        vm.untrusted_qdb.write("/qubes-vm-type", vmtype)

        self.write_services(vm)

    def write_services(self, vm):
        for feature, value in vm.features.items():
            service = self.features_to_services.get(feature, None)
            if service is None:
                continue
            # forcefully convert to '0' or '1'
            vm.untrusted_qdb.write(
                "/qubes-service/{}".format(service), str(int(bool(value)))
            )
        if "updates-proxy-setup" in vm.features.keys():
            vm.untrusted_qdb.write(
                "/qubes-service/{}".format("yum-proxy-setup"),
                str(int(bool(vm.features["updates-proxy-setup"]))),
            )
