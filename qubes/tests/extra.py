#
# The Qubes OS Project, https://www.qubes-os.org/
#
# Copyright (C) 2016
#                   Marek Marczykowski-Górecki <marmarek@invisiblethingslab.com>
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

import asyncio
import subprocess
import sys

import pkg_resources

import qubes.tests
import qubes.vm.appvm

class ProcessWrapper(object):
    def __init__(self, proc, loop=None):
        self._proc = proc
        self._loop = loop or asyncio.get_event_loop()

    def __getattr__(self, item):
        return getattr(self._proc, item)

    def __setattr__(self, key, value):
        if key.startswith('_'):
            return super(ProcessWrapper, self).__setattr__(key, value)
        return setattr(self._proc, key, value)

    def communicate(self, input=None):
        return self._loop.run_until_complete(self._proc.communicate(input))

class VMWrapper(object):
    '''Wrap VM object to provide stable API for basic operations'''
    def __init__(self, vm, loop=None):
        self._vm = vm
        self._loop = loop or asyncio.get_event_loop()

    def __getattr__(self, item):
        return getattr(self._vm, item)

    def __setattr__(self, key, value):
        if key.startswith('_'):
            return super(VMWrapper, self).__setattr__(key, value)
        return setattr(self._vm, key, value)

    def __str__(self):
        return str(self._vm)

    def __eq__(self, other):
        return self._vm == other

    def __hash__(self):
        return hash(self._vm)

    def start(self, start_guid=True):
        return self._loop.run_until_complete(
            self._vm.start(start_guid=start_guid))

    def shutdown(self):
        return self._loop.run_until_complete(self._vm.shutdown())

    def run(self, command, wait=False, user=None, passio_popen=False,
            passio_stderr=False, **kwargs):
        if wait:
            try:
                self._loop.run_until_complete(
                    self._vm.run_for_stdio(command, user=user))
            except subprocess.CalledProcessError as err:
                return err.returncode
            return 0
        elif passio_popen:
            p = self._loop.run_until_complete(self._vm.run(command, user=user,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE if passio_stderr else None))
            return ProcessWrapper(p, self._loop)
        else:
            asyncio.ensure_future(self._vm.run_for_stdio(command, user=user),
                loop=self._loop)

    def run_service(self, service, wait=True, input=None, user=None,
            passio_popen=False,
            passio_stderr=False, **kwargs):
        if wait:
            try:
                if isinstance(input, str):
                    input = input.encode()
                self._loop.run_until_complete(
                    self._vm.run_service_for_stdio(service,
                        input=input, user=user))
            except subprocess.CalledProcessError as err:
                return err.returncode
            return 0
        elif passio_popen:
            p = self._loop.run_until_complete(self._vm.run_service(service,
                user=user,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE if passio_stderr else None))
            return ProcessWrapper(p, self._loop)


class ExtraTestCase(qubes.tests.SystemTestCase):

    template = None

    def setUp(self):
        super(ExtraTestCase, self).setUp()
        self.init_default_template(self.template)
        if self.template is not None:
            # also use this template for DispVMs
            dispvm_base = self.app.add_new_vm('AppVM',
                name=self.make_vm_name('dvm'),
                template=self.template, label='red', template_for_dispvms=True)
            self.loop.run_until_complete(dispvm_base.create_on_disk())
            self.app.default_dispvm = dispvm_base

    def tearDown(self):
        self.app.default_dispvm = None
        super(ExtraTestCase, self).tearDown()

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
            self.loop.run_until_complete(vm.create_on_disk())
        self.app.save()

        # get objects after reload
        vms = []
        for vmname in names:
            vms.append(VMWrapper(self.app.domains[self.make_vm_name(vmname)],
                loop=self.loop))
        return vms

    def enable_network(self):
        """
        Enable access to the network. Must be called before creating VMs.
        """
        self.init_networking()

    def qrexec_policy(self, service, source, destination, allow=True):
        """
        Allow qrexec calls for duration of the test
        :param service: service name
        :param source: source VM name
        :param destination: destination VM name
        :return:
        """

        def add_remove_rule(add=True):
            with open('/etc/qubes-rpc/policy/{}'.format(service), 'r+') as policy:
                policy_rules = policy.readlines()
                rule = "{} {} {}\n".format(source, destination,
                                              'allow' if allow else 'deny')
                if add:
                    policy_rules.insert(0, rule)
                else:
                    policy_rules.remove(rule)
                policy.truncate(0)
                policy.seek(0)
                policy.write(''.join(policy_rules))
        add_remove_rule(add=True)
        self.addCleanup(add_remove_rule, add=False)


def load_tests(loader, tests, pattern):
    for entry in pkg_resources.iter_entry_points('qubes.tests.extra'):
        try:
            for test_case in entry.load()():
                tests.addTests(loader.loadTestsFromNames([
                    '{}.{}'.format(test_case.__module__, test_case.__name__)]))
        except Exception as err:  # pylint: disable=broad-except
            def runTest(self):
                raise err
            ExtraLoadFailure = type('ExtraLoadFailure',
                (qubes.tests.QubesTestCase,),
                {entry.name: runTest})
            tests.addTest(ExtraLoadFailure(entry.name))

    for entry in pkg_resources.iter_entry_points(
            'qubes.tests.extra.for_template'):
        try:
            for test_case in entry.load()():
                tests.addTests(loader.loadTestsFromNames(
                    qubes.tests.create_testcases_for_templates(
                        test_case.__name__, test_case,
                        module=sys.modules[test_case.__module__])))
        except Exception as err:  # pylint: disable=broad-except
            def runTest(self):
                raise err
            ExtraForTemplateLoadFailure = type('ExtraForTemplateLoadFailure',
                (qubes.tests.QubesTestCase,),
                {entry.name: runTest})
            tests.addTest(ExtraForTemplateLoadFailure(entry.name))

    return tests
