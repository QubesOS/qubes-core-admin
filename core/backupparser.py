# -*- encoding: utf8 -*-
#
# The Qubes OS Project, http://www.qubes-os.org
#
# Copyright (C) 2017 Marek Marczykowski-Górecki
#                               <marmarek@invisiblethingslab.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, see <http://www.gnu.org/licenses/>.

'''Standalone qubes.xml parser for safer parsing - without interfering with
all QubesVM code'''
import ast
import string

import lxml.etree
import xml.parsers.expat
import os
import sys

import re
from qubes import QubesVmCollection, QubesException, QubesVmClasses, \
    QubesVm, system_path, QubesVmLabels


class SafeQubesVmCollection(QubesVmCollection):

    def save(self):
        raise NotImplementedError('This class is only for reading qubes.xml')

    def add_new_vm(self, vm_type, **kwargs):
        raise NotImplementedError('This class is only for reading qubes.xml')

    def load_vm(self, vm_type, element):
        kwargs = {}

        untrusted_name = element.get('name')
        if untrusted_name is None:
            raise ValueError('missing VM name')
        if '..' in untrusted_name or '/' in untrusted_name or \
                not QubesVm.verify_name(untrusted_name):
            raise ValueError('rejecting VM name {!r}'.format(untrusted_name))
        if any((vm.name == untrusted_name) for vm in self.values()):
            raise ValueError('Duplicated name: {}'.format(untrusted_name))
        name = untrusted_name
        kwargs['name'] = name

        qid = int(element.get('qid'))
        if qid in self:
            raise ValueError('Duplicated qid: {}, name: {}'.format(qid, name))
        kwargs['qid'] = qid

        # load() enforce load order so templates are loader before
        # template-based VMs

        untrusted_template_qid = element.get('template_qid')
        if untrusted_template_qid is not None:
            if untrusted_template_qid == 'none':
                template = None
            else:
                template_qid = int(untrusted_template_qid)
                template = self[template_qid]
            kwargs['template'] = template

        backup_content = (element.get('backup_content') == 'True')
        kwargs['backup_content'] = backup_content

        if backup_content:
            untrusted_backup_path = element.get('backup_path')
            if untrusted_backup_path not in [
                        'appvms/' + name, 'vm-templates/' + name,
                        'servicevms/' + name, 'vm' + str(qid)]:
                raise ValueError('rejecting backup path')
            backup_path = untrusted_backup_path
            kwargs['backup_path'] = backup_path

            untrusted_backup_size = element.get('backup_size')
            if untrusted_backup_size:
                backup_size = int(element.get('backup_size'))
                kwargs['backup_size'] = backup_size

        uses_default_kernel = (element.get('uses_default_kernel') == 'True')
        kwargs['uses_default_kernel'] = uses_default_kernel

        if not uses_default_kernel:
            untrusted_kernel = element.get('kernel')
            if untrusted_kernel is not None:
                if '..' or '/' in untrusted_kernel:
                    raise ValueError(
                        'invalid kernel: {!r}'.format(untrusted_kernel))
                # missing kernel is handled by restore logic, depending on
                # restore options
                kernel = untrusted_kernel
                kwargs['kernel'] = kernel

        memory = int(element.get('memory'))
        kwargs['memory'] = memory

        untrusted_maxmem = element.get('maxmem')
        if untrusted_maxmem is not None:
            maxmem = int(untrusted_maxmem)
            kwargs['maxmem'] = maxmem

        untrusted_uses_default_kernelopts = \
            element.get('uses_default_kernelopts')
        if untrusted_uses_default_kernelopts is not None:
            uses_default_kernelopts = (untrusted_uses_default_kernelopts ==
                                       'True')
            kwargs['uses_default_kernelopts'] = uses_default_kernelopts
        else:
            uses_default_kernelopts = True

        untrusted_kernelopts = element.get('kernelopts')
        if not uses_default_kernelopts and untrusted_kernelopts is not None:
            if any((c in untrusted_kernelopts) for c in '<>\'"&'):
                raise ValueError('Invalid characters in kernelopts')
            kernelopts = untrusted_kernelopts
            kwargs['kernelopts'] = kernelopts

        untrusted_services = element.get('services')
        if untrusted_services is not None:
            services = {}
            for untrusted_key, untrusted_value in ast.literal_eval(
                    untrusted_services).items():
                if all((c in string.ascii_letters + '-_') for c in
                        untrusted_key) and isinstance(untrusted_value, bool):
                    services[untrusted_key] = untrusted_value
            kwargs['services'] = services

        vcpus = int(element.get('vcpus'))
        kwargs['vcpus'] = vcpus

        internal = (element.get('internal') == 'True')
        kwargs['internal'] = internal

        untrusted_mac = element.get('mac')
        if untrusted_mac is not None:
            if re.match(r'^([0-9a-f][0-9a-f]:){5}[0-9a-f][0-9a-f]$', untrusted_mac,
                    re.IGNORECASE) is None:
                raise ValueError('invalid mac value')
            mac = untrusted_mac
            kwargs['mac'] = mac

        include_in_backups = (element.get('include_in_backups') == 'True')
        kwargs['include_in_backups'] = include_in_backups

        untrusted_label = element.get('label')
        if untrusted_label is None:
            raise ValueError('missing label')

        label = QubesVmLabels[untrusted_label]
        kwargs['label'] = label

        untrusted_timezone = element.get('timezone')
        if untrusted_timezone is not None:
            if untrusted_timezone != 'localtime' and not \
                    untrusted_timezone.isdigit():
                raise ValueError('invalid timezone value')
            timezone = untrusted_timezone
            kwargs['timezone'] = timezone

        untrusted_qrexec_timeout = element.get('qrexec_timeout')
        if untrusted_qrexec_timeout is not None:
            qrexec_timeout = int(untrusted_qrexec_timeout)
            kwargs['qrexec_timeout'] = qrexec_timeout

        untrusted_qrexec_installed = element.get('qrexec_installed')
        if untrusted_qrexec_installed is not None:
            qrexec_installed = (untrusted_qrexec_installed == 'True')
            kwargs['qrexec_installed'] = qrexec_installed

        untrusted_guiagent_installed = element.get('guiagent_installed')
        if untrusted_guiagent_installed is not None:
            guiagent_installed = (untrusted_guiagent_installed == 'True')
            kwargs['guiagent_installed'] = guiagent_installed

        # ignore default_user
        # ignore pcidevs
        # ignore drive

        vm_cls = QubesVmClasses[vm_type]
        vm = vm_cls(collection=self, **kwargs)
        if not self.verify_new_vm(vm):
            raise QubesException("Wrong VM description!")

        self[vm.qid] = vm

        return vm

    def load_vm_deps(self, vm, element):
        uses_default_netvm = element.get('uses_default_netvm') == 'True'
        vm.uses_default_netvm = uses_default_netvm

        if not uses_default_netvm:
            untrusted_netvm_qid = element.get('netvm_qid')
            if untrusted_netvm_qid is not None and untrusted_netvm_qid != \
                    'none':
                netvm = self[int(untrusted_netvm_qid)]
            else:
                netvm = None
        else:
            if vm.is_proxyvm():
                netvm = self.get_default_fw_netvm()
            else:
                netvm = self.get_default_netvm()

        # directly set internal attr to not call setters...
        vm._netvm = netvm
        if netvm:
            netvm.connected_vms[vm.qid] = vm

        uses_default_dispvm_netvm = \
            element.get('uses_default_dispvm_netvm') == 'True'
        vm.uses_default_dispvm_netvm = uses_default_dispvm_netvm

        if not uses_default_dispvm_netvm:
            untrusted_dispvm_netvm_qid = element.get('dispvm_netvm')
            if untrusted_dispvm_netvm_qid is not None:
                dispvm_netvm = self[int(untrusted_dispvm_netvm_qid)]
                vm.dispvm_netvm = dispvm_netvm

    def load(self):
        self.log.debug('load()')
        self.clear()

        try:
            self.qubes_store_file.seek(0)
            tree = lxml.etree.parse(self.qubes_store_file)
        except (EnvironmentError,
        xml.parsers.expat.ExpatError) as err:
            raise QubesException("error loading qubes.xml: {}".format(err))

        self.load_globals(tree.getroot())

        loaded_vms = []
        for (vm_class_name, vm_class) in sorted(QubesVmClasses.items(),
                key=lambda _x: _x[1].load_order):
            if vm_class_name == 'QubesAdminVm':
                # skip dom0
                continue
            vms_of_class = tree.findall(vm_class_name)
            # first non-template based, then template based
            sorted_vms_of_class = sorted(vms_of_class,
                key=lambda x: str(x.get('template_qid')).lower() != "none")
            for element in sorted_vms_of_class:
                try:
                    vm = self.load_vm(vm_class_name, element)
                    loaded_vms.append((vm, element))
                except (ValueError, LookupError) as err:
                    raise QubesException(
                        "paranoid-mode: error loading VM from qubes.xml "
                        "({}): {}".format(
                            vm_class_name, err))

        self.check_globals()

        # then set dependencies
        for vm, element in loaded_vms:
            try:
                self.load_vm_deps(vm, element)
            except (ValueError, LookupError) as err:
                raise QubesException(
                    "error setting dependencies for VM {}: {}".format(
                        vm.name, err))
