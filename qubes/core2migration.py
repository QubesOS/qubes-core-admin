#!/usr/bin/python
# -*- coding: utf-8 -*-
#
# The Qubes OS Project, http://www.qubes-os.org
#
# Copyright (C) 2016  Marek Marczykowski-Górecki
#                                   <marmarek@invisiblethingslab.com>
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
# along with this program. If not, see <http://www.gnu.org/licenses/>
#

import ast
import xml.parsers.expat

import lxml.etree

import qubes
import qubes.vm.appvm
import qubes.vm.standalonevm
import qubes.vm.templatevm
import qubes.vm.adminvm
import qubes.ext.r3compatibility


class AppVM(qubes.vm.appvm.AppVM):  # pylint: disable=too-many-ancestors
    """core2 compatibility AppVM class, with variable dir_path"""
    dir_path = qubes.property('dir_path',
        # pylint: disable=undefined-variable
        default=(lambda self: super(AppVM, self).dir_path),
        saver=qubes.property.dontsave,
        doc="VM storage directory",
    )

    def is_running(self):
        return False

class StandaloneVM(qubes.vm.standalonevm.StandaloneVM):
    """core2 compatibility StandaloneVM class, with variable dir_path
    """  # pylint: disable=too-many-ancestors
    dir_path = qubes.property('dir_path',
        # pylint: disable=undefined-variable
        default=(lambda self: super(StandaloneVM, self).dir_path),
        saver=qubes.property.dontsave,
        doc="VM storage directory")

    def is_running(self):
        return False


class Core2Qubes(qubes.Qubes):

    def __init__(self, store=None, load=True, **kwargs):
        if store is None:
            raise ValueError("store path required")
        super(Core2Qubes, self).__init__(store, load, **kwargs)

    def load_default_template(self, element):
        default_template = element.get("default_template")
        self.default_template = int(default_template) \
            if default_template.lower() != "none" else None

    def load_globals(self, element):
        default_netvm = element.get("default_netvm")
        if default_netvm is not None:
            self.default_netvm = int(default_netvm) \
                if default_netvm != "None" else None

        default_fw_netvm = element.get("default_fw_netvm")
        if default_fw_netvm is not None:
            self.default_fw_netvm = int(default_fw_netvm) \
                if default_fw_netvm != "None" else None

        updatevm = element.get("updatevm")
        if updatevm is not None:
            self.updatevm = int(updatevm) \
                if updatevm != "None" else None

        clockvm = element.get("clockvm")
        if clockvm is not None:
            self.clockvm = int(clockvm) \
                if clockvm != "None" else None


    def set_netvm_dependency(self, element):
        kwargs = {}
        attr_list = ("qid", "uses_default_netvm", "netvm_qid")

        for attribute in attr_list:
            kwargs[attribute] = element.get(attribute)

        vm = self.domains[int(kwargs["qid"])]

        if element.get("uses_default_netvm") is None:
            uses_default_netvm = True
        else:
            uses_default_netvm = (
                True if element.get("uses_default_netvm") == "True" else False)
        if not uses_default_netvm:
            netvm_qid = element.get("netvm_qid")
            if netvm_qid is None or netvm_qid == "none":
                vm.netvm = None
            else:
                vm.netvm = int(netvm_qid)

    def set_dispvm_netvm_dependency(self, element):
        kwargs = {}
        attr_list = ("qid", "uses_default_netvm", "netvm_qid")

        for attribute in attr_list:
            kwargs[attribute] = element.get(attribute)

        vm = self.domains[int(kwargs["qid"])]

        if element.get("uses_default_dispvm_netvm") is None:
            uses_default_dispvm_netvm = True
        else:
            uses_default_dispvm_netvm = (
                True if element.get("uses_default_dispvm_netvm") == "True"
                else False)
        if not uses_default_dispvm_netvm:
            dispvm_netvm_qid = element.get("dispvm_netvm_qid")
            if dispvm_netvm_qid is None or dispvm_netvm_qid == "none":
                dispvm_netvm = None
            else:
                dispvm_netvm = self.domains[int(dispvm_netvm_qid)]
        else:
            dispvm_netvm = vm.netvm

        if dispvm_netvm:
            dispvm_tpl_name = 'disp-{}'.format(dispvm_netvm.name)
        else:
            dispvm_tpl_name = 'disp-no-netvm'

        if dispvm_tpl_name not in self.domains:
            vm = self.add_new_vm(qubes.vm.appvm.AppVM,
                name=dispvm_tpl_name)
            # TODO: add support for #2075
        # TODO: set qrexec policy based on dispvm_netvm value

    def import_core2_vm(self, element):
        vm_class_name = element.tag
        try:
            kwargs = {}
            if vm_class_name in ["QubesTemplateVm", "QubesTemplateHVm"]:
                vm_class = qubes.vm.templatevm.TemplateVM
            elif element.get('template_qid').lower() == "none":
                kwargs['dir_path'] = element.get('dir_path')
                vm_class = StandaloneVM
            else:
                kwargs['dir_path'] = element.get('dir_path')
                kwargs['template'] = self.domains[int(element.get(
                    'template_qid'))]
                vm_class = AppVM
            # simple attributes
            for attr in ['installed_by_rpm', 'include_in_backups',
                    'qrexec_timeout', 'internal', 'label', 'name',
                    'vcpus', 'memory', 'maxmem', 'default_user',
                    'debug', 'pci_strictreset', 'mac', 'autostart']:
                value = element.get(attr)
                if value:
                    kwargs[attr] = value
            # attributes with default value
            for attr in ["kernel", "kernelopts"]:
                value = element.get(attr)
                if value and value.lower() == "none":
                    value = None
                value_is_default = element.get(
                    "uses_default_{}".format(attr))
                if value_is_default and value_is_default.lower() != \
                        "true":
                    kwargs[attr] = value
            kwargs['hvm'] = "HVm" in vm_class_name
            vm = self.add_new_vm(vm_class,
                qid=int(element.get('qid')), **kwargs)
            services = element.get('services')
            if services:
                services = ast.literal_eval(services)
            else:
                services = {}
            for service, value in services.iteritems():
                feature = service
                for repl_feature, repl_service in \
                        qubes.ext.r3compatibility.\
                        R3Compatibility.features_to_services.\
                        iteritems():
                    if repl_service == service:
                        feature = repl_feature
                vm.features[feature] = value
            for attr in ['backup_content', 'backup_path',
                'backup_size']:
                value = element.get(attr)
                vm.features[attr.replace('_', '-')] = value
            pcidevs = element.get('pcidevs')
            if pcidevs:
                pcidevs = ast.literal_eval(pcidevs)
            for pcidev in pcidevs:
                try:
                    vm.devices["pci"].attach(pcidev)
                except qubes.exc.QubesException as e:
                    self.log.error("VM {}: {}".format(vm.name, str(e)))
        except (ValueError, LookupError) as err:
            self.log.error("import error ({1}): {2}".format(
                vm_class_name, err))
            if 'vm' in locals():
                del self.domains[vm]

    def load(self):
        qubes_store_file = open(self._store, 'r')

        try:
            qubes_store_file.seek(0)
            tree = lxml.etree.parse(qubes_store_file)
        except (EnvironmentError,  # pylint: disable=broad-except
                xml.parsers.expat.ExpatError) as err:
            self.log.error(err)
            return False

        self.load_initial_values()

        self.default_kernel = tree.getroot().get("default_kernel")

        vm_classes = ["TemplateVm", "TemplateHVm",
            "AppVm", "HVm", "NetVm", "ProxyVm"]
        # First load templates
        for vm_class_name in ["TemplateVm", "TemplateHVm"]:
            vms_of_class = tree.findall("Qubes" + vm_class_name)
            for element in vms_of_class:
                self.import_core2_vm(element)

        # Then set default template ...
        self.load_default_template(tree.getroot())

        # ... and load other VMs
        for vm_class_name in ["AppVm", "HVm", "NetVm", "ProxyVm"]:
            vms_of_class = tree.findall("Qubes" + vm_class_name)
            # first non-template based, then template based
            sorted_vms_of_class = sorted(vms_of_class,
                key=lambda x: str(x.get('template_qid')).lower() != "none")
            for element in sorted_vms_of_class:
                self.import_core2_vm(element)

        # After importing all VMs, set netvm references, in the same order
        for vm_class_name in vm_classes:
            for element in tree.findall("Qubes" + vm_class_name):
                try:
                    self.set_netvm_dependency(element)
                except (ValueError, LookupError) as err:
                    self.log.error("VM {}: failed to set netvm dependency: {}".
                        format(element.get('name'), err))

        # and load other defaults (default netvm, updatevm etc)
        self.load_globals(tree.getroot())

    def save(self):
        raise NotImplementedError("Saving old qubes.xml not supported")
