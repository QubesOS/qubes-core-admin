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

import sys
import pkg_resources
import qubes.tests
import qubes.vm.appvm
import qubes.vm.templatevm


class ExtraTestCase(qubes.tests.SystemTestsMixin, qubes.tests.QubesTestCase):

    template = None

    def setUp(self):
        super(ExtraTestCase, self).setUp()
        self.init_default_template(self.template)

    def create_vms(self, names):
        """
        Create AppVMs for the duration of the test. Will be automatically
        removed after completing the test.
        :param names: list of VM names to create (each of them will be
        prefixed with some test specific string)
        :return: list of created VM objects
        """
        if self.template:
            template = self.app.domains[self.template]
        else:
            template = self.app.default_template
        for vmname in names:
            vm = self.app.add_new_vm(qubes.vm.appvm.AppVM,
                                    name=self.make_vm_name(vmname),
                                    template=template,
                                    label='red')
            vm.create_on_disk()
        self.app.save()

        # get objects after reload
        vms = []
        for vmname in names:
            vms.append(self.app.domains[self.make_vm_name(vmname)])
        return vms

    def enable_network(self):
        """
        Enable access to the network. Must be called before creating VMs.
        """
        self.init_networking()


def load_tests(loader, tests, pattern):
    for entry in pkg_resources.iter_entry_points('qubes.tests.extra'):
        try:
            for test_case in entry.load()():
                tests.addTests(loader.loadTestsFromTestCase(test_case))
        except Exception as err:  # pylint: disable=broad-except
            def runTest(self):
                raise err
            ExtraLoadFailure = type('ExtraLoadFailure',
                (qubes.tests.QubesTestCase,),
                {entry.name: runTest})
            tests.addTest(ExtraLoadFailure(entry.name))

    try:
        app = qubes.Qubes()
        templates = [vm.name for vm in app.domains if
                     isinstance(vm, qubes.vm.templatevm.TemplateVM)]
    except OSError:
        templates = []

    for entry in pkg_resources.iter_entry_points(
            'qubes.tests.extra.for_template'):
        try:
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
        except Exception as err:  # pylint: disable=broad-except
            def runTest(self):
                raise err
            ExtraForTemplateLoadFailure = type('ExtraForTemplateLoadFailure',
                (qubes.tests.QubesTestCase,),
                {entry.name: runTest})
            tests.addTest(ExtraLoadFailure(entry.name))

    return tests
