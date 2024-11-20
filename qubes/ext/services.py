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

"""Extension responsible for qvm-service framework"""

import os
import qubes.ext
import qubes.config


class ServicesExtension(qubes.ext.Extension):
    """This extension export features with 'service.' prefix to QubesDB in
    /qubes-service/ tree.
    """

    @staticmethod
    def add_dom0_service(vm, service):
        try:
            os.makedirs(
                qubes.config.system_path["dom0_services_dir"], exist_ok=True
            )
            service = "{}/{}".format(
                qubes.config.system_path["dom0_services_dir"], service
            )
            if not os.path.exists(service):
                os.mknod(service)
        except PermissionError:
            vm.log.warning(
                "Cannot write to {}".format(
                    qubes.config.system_path["dom0_services_dir"]
                )
            )

    @staticmethod
    def remove_dom0_service(vm, service):
        try:
            service = "{}/{}".format(
                qubes.config.system_path["dom0_services_dir"], service
            )
            if os.path.exists(service):
                os.remove(service)
        except PermissionError:
            vm.log.warning(
                "Cannot write to {}".format(
                    qubes.config.system_path["dom0_services_dir"]
                )
            )

    @qubes.ext.handler("domain-qdb-create")
    def on_domain_qdb_create(self, vm, event):
        """Actually export features"""
        # pylint: disable=unused-argument
        for feature, value in vm.features.items():
            if not feature.startswith("service."):
                continue
            service = feature[len("service.") :]
            if not service:
                vm.log.warning("Empty service name, ignoring: " + service)
                continue
            if len(service) > 48:
                vm.log.warning("Too long service name, ignoring: " + service)
                continue
            # forcefully convert to '0' or '1'
            vm.untrusted_qdb.write(
                "/qubes-service/{}".format(service), str(int(bool(value)))
            )

        # always set meminfo-writer according to maxmem
        vm.untrusted_qdb.write(
            "/qubes-service/meminfo-writer", "1" if vm.maxmem > 0 else "0"
        )

    @qubes.ext.handler("domain-feature-pre-set:*")
    def on_domain_feature_pre_set(
        self, vm, event, feature, value, oldvalue=None
    ):
        """Check if service name is compatible with QubesDB"""
        # pylint: disable=unused-argument
        if not feature.startswith("service."):
            return
        service = feature[len("service.") :]
        if not service:
            raise qubes.exc.QubesValueError("Service name cannot be empty")

        if "/" in service:
            raise qubes.exc.QubesValueError(
                "Service name cannot contain a slash"
            )

        if service in (".", ".."):
            raise qubes.exc.QubesValueError(
                'Service name cannot be "." or ".."'
            )

        if len(service) > 48:
            raise qubes.exc.QubesValueError(
                "Service name must not exceed 48 bytes"
            )

    @qubes.ext.handler("domain-feature-set:*")
    def on_domain_feature_set(self, vm, event, feature, value, oldvalue=None):
        """Update /qubes-service/ QubesDB tree in runtime"""
        # pylint: disable=unused-argument

        # TODO: remove this compatibility hack in Qubes 4.1
        if feature == "service.meminfo-writer":
            # if someone try to enable meminfo-writer ...
            if value:
                # ... reset maxmem to default
                vm.maxmem = qubes.property.DEFAULT
            else:
                # otherwise, set to 0
                vm.maxmem = 0
            # in any case, remove the entry, as it does not indicate memory
            # balancing state anymore
            del vm.features["service.meminfo-writer"]

        if not vm.is_running():
            return
        if not feature.startswith("service."):
            return
        service = feature[len("service.") :]
        # forcefully convert to '0' or '1'
        vm.untrusted_qdb.write(
            "/qubes-service/{}".format(service), str(int(bool(value)))
        )

        if vm.name == "dom0":
            if str(int(bool(value))) == "1":
                self.add_dom0_service(vm, service)
            else:
                self.remove_dom0_service(vm, service)

    @qubes.ext.handler("domain-feature-delete:*")
    def on_domain_feature_delete(self, vm, event, feature):
        """Update /qubes-service/ QubesDB tree in runtime"""
        # pylint: disable=unused-argument
        if not vm.is_running():
            return
        if not feature.startswith("service."):
            return
        service = feature[len("service.") :]
        # this one is excluded from user control
        if service == "meminfo-writer":
            return
        vm.untrusted_qdb.rm("/qubes-service/{}".format(service))

        if vm.name == "dom0":
            self.remove_dom0_service(vm, service)

    @qubes.ext.handler("domain-load")
    def on_domain_load(self, vm, event):
        """Migrate meminfo-writer service into maxmem"""
        # pylint: disable=unused-argument
        if "service.meminfo-writer" in vm.features:
            # if was set to false, force maxmem=0
            # otherwise, simply ignore as the default is fine
            if not vm.features["service.meminfo-writer"]:
                vm.maxmem = 0
            del vm.features["service.meminfo-writer"]

        if vm.name == "dom0":
            for feature, value in vm.features.items():
                if not feature.startswith("service."):
                    continue
                service = feature[len("service.") :]
                if str(int(bool(value))) == "1":
                    self.add_dom0_service(vm, service)
                else:
                    self.remove_dom0_service(vm, service)

    @qubes.ext.handler("features-request")
    def supported_services(self, vm, event, untrusted_features):
        """Handle advertisement of supported services"""
        # pylint: disable=unused-argument

        if getattr(vm, "template", None):
            vm.log.warning(
                "Ignoring qubes.FeaturesRequest from template-based VM"
            )
            return

        new_supported_services = set()
        for requested_service in untrusted_features:
            if not requested_service.startswith("supported-service."):
                continue
            if untrusted_features[requested_service] == "1":
                # only allow to advertise service as supported, lack of entry
                #  means service is not supported
                new_supported_services.add(requested_service)
        del untrusted_features

        # if no service is supported, ignore the whole thing - do not clear
        # all services in case of empty request (manual or such)
        if not new_supported_services:
            return

        old_supported_services = set(
            feat
            for feat in vm.features
            if feat.startswith("supported-service.") and vm.features[feat]
        )

        for feature in new_supported_services.difference(
            old_supported_services
        ):
            vm.features[feature] = True
            if (
                feature == "supported-service.apparmor"
                and not "apparmor" in vm.features
            ):
                vm.features["apparmor"] = True

        for feature in old_supported_services.difference(
            new_supported_services
        ):
            del vm.features[feature]
            if (
                feature == "supported-service.apparmor"
                and "apparmor" in vm.features
                and vm.features["apparmor"] == "1"
            ):
                del vm.features["apparmor"]
