#!/usr/bin/python2 -O
# vim: fileencoding=utf-8

#
# The Qubes OS Project, https://www.qubes-os.org/
#
# Copyright (C) 2016
#                   Marek Marczykowski-Górecki <marmarek@invisiblethingslab.com>
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
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
#

import pkg_resources
import qubes.tests
import qubes.qubes


class ExtraTestCase(qubes.tests.SystemTestsMixin, qubes.tests.QubesTestCase):

    template = None

    def setUp(self):
        super(ExtraTestCase, self).setUp()
        self.qc.unlock_db()
        self.default_netvm = None

    def create_vms(self, names):
        """
        Create AppVMs for the duration of the test. Will be automatically
        removed after completing the test.
        :param names: list of VM names to create (each of them will be
        prefixed with some test specific string)
        :return: list of created VM objects
        """
        self.qc.lock_db_for_writing()
        self.qc.load()
        if self.template:
            template = self.qc.get_vm_by_name(self.template)
        else:
            template = self.qc.get_default_template()
        for vmname in names:
            vm = self.qc.add_new_vm("QubesAppVm",
                                    name=self.make_vm_name(vmname),
                                    template=template,
                                    uses_default_netvm=False,
                                    netvm=self.default_netvm)
            vm.create_on_disk(verbose=False)
        self.save_and_reload_db()
        self.qc.unlock_db()

        # get objects after reload
        vms = []
        for vmname in names:
            vms.append(self.qc.get_vm_by_name(self.make_vm_name(vmname)))
        return vms

    def enable_network(self):
        """
        Enable access to the network. Must be called before creating VMs.
        """
        self.default_netvm = self.qc.get_default_netvm()
        if self.template.startswith('whonix-ws'):
            whonix_netvm = self.qc.get_vm_by_name('sys-whonix')
            if whonix_netvm:
                self.default_netvm = whonix_netvm

def load_tests(loader, tests, pattern):
    for entry in pkg_resources.iter_entry_points('qubes.tests.extra'):
        for test_case in entry.load()():
            tests.addTests(loader.loadTestsFromTestCase(test_case))

    try:
        qc = qubes.qubes.QubesVmCollection()
        qc.lock_db_for_reading()
        qc.load()
        qc.unlock_db()
        templates = [vm.name for vm in qc.values() if
                     isinstance(vm, qubes.qubes.QubesTemplateVm)]
    except OSError:
        templates = []

    for entry in pkg_resources.iter_entry_points(
            'qubes.tests.extra.for_template'):
        for test_case in entry.load()():
            for template in templates:
                tests.addTests(loader.loadTestsFromTestCase(
                    type(
                        '{}_{}_{}'.format(
                            entry.name, test_case.__name__, template),
                        (test_case,),
                        {'template': template}
                    )
                ))

    return tests
