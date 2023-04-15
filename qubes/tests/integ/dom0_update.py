#
# The Qubes OS Project, http://www.qubes-os.org
#
# Copyright (C) 2015 Marek Marczykowski-Górecki <marmarek@invisiblethingslab.com>
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
# USA.
#

import asyncio
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest

import qubes
import qubes.tests

VM_PREFIX = "test-"

@unittest.skipUnless(os.path.exists('/usr/bin/rpmsign') and
                     os.path.exists('/usr/bin/rpmbuild'),
                     'rpm-sign and/or rpm-build not installed')
class TC_00_Dom0UpgradeMixin(object):
    """
    Tests for downloading dom0 updates using VMs based on different templates
    """
    pkg_name = 'qubes-test-pkg'
    dom0_update_common_opts = ['--disablerepo=*', '--enablerepo=test']

    @classmethod
    def generate_key(cls, keydir):
        gpg_opts = ['gpg', '--quiet', '--no-default-keyring',
                    '--homedir', keydir]
        p = subprocess.Popen(gpg_opts + ['--gen-key', '--batch'],
                             stdin=subprocess.PIPE,
                             stderr=open(os.devnull, 'w'))
        p.stdin.write('''
Key-Type: RSA
Key-Length: 4096
Key-Usage: sign
Name-Real: Qubes test
Expire-Date: 0
%no-protection
%commit
        '''.format(keydir=keydir).encode())
        p.stdin.close()
        p.wait()

        subprocess.check_call(gpg_opts + ['-a', '--export',
                                          '--output', os.path.join(keydir, 'pubkey.asc')])
        p = subprocess.Popen(gpg_opts + ['--with-colons', '--list-keys'],
                             stdout=subprocess.PIPE)
        for line in p.stdout.readlines():
            fields = line.decode().split(':')
            if fields[0] == 'pub':
                return fields[4][-8:].lower()
        raise RuntimeError

    @classmethod
    def setUpClass(cls):
        super(TC_00_Dom0UpgradeMixin, cls).setUpClass()

        cls.tmpdir = tempfile.mkdtemp()

        cls.keyid = cls.generate_key(cls.tmpdir)

        with open('/etc/yum.repos.d/test.repo', 'w') as repo_file:
            repo_file.write('''
[test]
name = Test
baseurl = http://localhost:8080/
enabled = 1
''')


    @classmethod
    def tearDownClass(cls):
        os.unlink('/etc/yum.repos.d/test.repo')

        shutil.rmtree(cls.tmpdir)

    def setUp(self):
        super(TC_00_Dom0UpgradeMixin, self).setUp()
        if self.template.startswith('whonix-'):
            # Whonix redirect all the traffic through tor, so repository
            # on http://localhost:8080/ is unavailable
            self.skipTest("Test not supported for this template")
        self.init_default_template(self.template)
        self.updatevm = self.app.add_new_vm(
            qubes.vm.appvm.AppVM,
            name=self.make_vm_name("updatevm"),
            label='red'
        )
        self.loop.run_until_complete(self.updatevm.create_on_disk())
        self.app.updatevm = self.updatevm
        self.app.save()
        subprocess.call(['rpm', '-e', self.pkg_name],
                        stderr=subprocess.DEVNULL)
        subprocess.check_call(['rpm', '--import',
                               os.path.join(self.tmpdir, 'pubkey.asc')])
        self.loop.run_until_complete(self.updatevm.start())
        self.repo_running = False
        self.repo_proc = None

    def tearDown(self):
        if self.repo_proc:
            self.repo_proc.terminate()
            self.loop.run_until_complete(self.repo_proc.wait())
            del self.repo_proc
        self.app.updatevm = None
        super(TC_00_Dom0UpgradeMixin, self).tearDown()

        subprocess.call(['rpm', '-e', self.pkg_name],
            stderr=subprocess.DEVNULL)
        subprocess.call(['rpm', '-e', 'gpg-pubkey-{}'.format(
            self.keyid)], stderr=subprocess.DEVNULL)

        for pkg in os.listdir(self.tmpdir):
            if pkg.endswith('.rpm'):
                os.unlink(pkg)

    def create_pkg(self, dir, name, version):
        spec_path = os.path.join(dir, name+'.spec')
        spec = open(spec_path, 'w')
        spec.write(
            '''
Name:       {name}
Summary:    Test Package
Version:    {version}
Release:        1
Vendor:         Invisible Things Lab
License:        GPL
Group:          Qubes
URL:            http://www.qubes-os.org

%description
Test package

%install

%files
            '''.format(name=name, version=version)
        )
        spec.close()
        subprocess.check_call(
            ['rpmbuild', '--quiet', '-bb', '--define', '_rpmdir {}'.format(dir),
             spec_path])
        pkg_path = os.path.join(dir, 'x86_64',
                                '{}-{}-1.x86_64.rpm'.format(name, version))
        subprocess.check_call(['chmod', 'go-rw', '/dev/tty'])
        subprocess.check_call(
            ['rpm', '--quiet', '--define=_gpg_path {}'.format(dir),
             '--define=_gpg_name {}'.format("Qubes test"),
             '--addsign', pkg_path],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT)
        subprocess.check_call(['chmod', 'go+rw', '/dev/tty'])
        return pkg_path

    def send_pkg(self, filename):
        with open(filename, 'rb') as f_pkg:
            self.loop.run_until_complete(self.updatevm.run_for_stdio(
                'mkdir -p /tmp/repo; cat > /tmp/repo/{}'.format(
                    os.path.basename(filename)),
                input=f_pkg.read()))
        try:
            self.loop.run_until_complete(
                self.updatevm.run_for_stdio('cd /tmp/repo; createrepo_c .'))
        except subprocess.CalledProcessError as e:
            if e.returncode == 127:
                self.skipTest('createrepo_c not installed in template {}'.format(
                    self.template))
            else:
                self.skipTest('createrepo_c failed with code {}, '
                    'cannot perform the test'.format(e.returncode))
        self.start_repo()

    def start_repo(self):
        if self.repo_running:
            return
        self.repo_proc = self.loop.run_until_complete(self.updatevm.run(
            'cd /tmp/repo && python3 -m http.server 8080',
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT))
        self.repo_running = True

    def test_000_update(self):
        """Dom0 update tests

        Check if package update is:
         - detected
         - installed
         - "updates pending" flag is cleared
        """
        filename = self.create_pkg(self.tmpdir, self.pkg_name, '1.0')
        subprocess.check_call(['rpm', '-i', filename])
        filename = self.create_pkg(self.tmpdir, self.pkg_name, '2.0')
        self.send_pkg(filename)
        self.app.domains[0].features['updates-available'] = True

        logpath = os.path.join(self.tmpdir, 'dom0-update-output.txt')
        with open(logpath, 'w') as f_log:
            proc = self.loop.run_until_complete(asyncio.create_subprocess_exec(
                'qubes-dom0-update', '-y', *self.dom0_update_common_opts,
                stdout=f_log,
                stderr=subprocess.STDOUT))
        self.loop.run_until_complete(proc.wait())
        if proc.returncode:
            del proc
            with open(logpath) as f_log:
                self.fail("qubes-dom0-update failed: " + f_log.read())
        del proc

        retcode = subprocess.call(['rpm', '-q', '{}-1.0'.format(
            self.pkg_name)], stdout=subprocess.DEVNULL)
        self.assertEqual(retcode, 1, 'Package {}-1.0 still installed after '
                                     'update'.format(self.pkg_name))
        retcode = subprocess.call(['rpm', '-q', '{}-2.0'.format(
            self.pkg_name)], stdout=subprocess.DEVNULL)
        self.assertEqual(retcode, 0, 'Package {}-2.0 not installed after '
                                     'update'.format(self.pkg_name))
        self.assertFalse(
            self.app.domains[0].features.get('updates-available', False),
            "'updates pending' flag not cleared")

    def test_001_update_check(self):
        """ Check if dom0 updates check works
        """
        filename = self.create_pkg(self.tmpdir, self.pkg_name, '1.0')
        subprocess.check_call(['rpm', '-i', filename])
        filename = self.create_pkg(self.tmpdir, self.pkg_name, '2.0')
        self.send_pkg(filename)
        # check if disabling updates check is respected
        self.app.domains[0].features['service.qubes-update-check'] = False
        proc = self.loop.run_until_complete(asyncio.create_subprocess_exec(
            '/etc/cron.daily/qubes-dom0-updates.cron'))
        self.loop.run_until_complete(proc.communicate())
        self.assertFalse(self.app.domains[0].features.get('updates-available', False))

        # re-enable updates check and try again
        del self.app.domains[0].features['service.qubes-update-check']
        proc = self.loop.run_until_complete(asyncio.create_subprocess_exec(
            '/etc/cron.daily/qubes-dom0-updates.cron'))
        self.loop.run_until_complete(proc.communicate())
        self.assertTrue(self.app.domains[0].features.get('updates-available', False))

    def test_005_update_flag_clear(self):
        """Check if 'updates pending' flag is cleared"""

        # create any pkg (but not install it) to initialize repo in the VM
        filename = self.create_pkg(self.tmpdir, self.pkg_name, '1.0')
        self.send_pkg(filename)
        self.app.domains[0].features['updates-available'] = True

        logpath = os.path.join(self.tmpdir, 'dom0-update-output.txt')
        with open(logpath, 'w') as f_log:
            proc = self.loop.run_until_complete(asyncio.create_subprocess_exec(
                'qubes-dom0-update', '-y', *self.dom0_update_common_opts,
                stdout=f_log,
                stderr=subprocess.STDOUT))
        self.loop.run_until_complete(proc.wait())
        if proc.returncode:
            del proc
            with open(logpath) as f_log:
                self.fail("qubes-dom0-update failed: " + f_log.read())
        del proc

        with open(logpath) as f:
            dom0_update_output = f.read()
            self.assertFalse('Errno' in dom0_update_output or
                             'Couldn\'t' in dom0_update_output,
                             "qubes-dom0-update reported an error: {}".
                             format(dom0_update_output))

        self.assertFalse(
            self.app.domains[0].features.get('updates-available', False),
            "'updates pending' flag not cleared")

    def test_006_update_flag_clear(self):
        """Check if 'updates pending' flag is cleared, using --clean"""

        # create any pkg (but not install it) to initialize repo in the VM
        filename = self.create_pkg(self.tmpdir, self.pkg_name, '1.0')
        self.send_pkg(filename)
        self.app.domains[0].features['updates-available'] = True

        # remove also repodata to test #1685
        if os.path.exists('/var/lib/qubes/updates/repodata'):
            shutil.rmtree('/var/lib/qubes/updates/repodata')
        logpath = os.path.join(self.tmpdir, 'dom0-update-output.txt')
        with open(logpath, 'w') as f_log:
            proc = self.loop.run_until_complete(asyncio.create_subprocess_exec(
                'qubes-dom0-update', '-y', '--clean',
                *self.dom0_update_common_opts,
                stdout=f_log,
                stderr=subprocess.STDOUT))
        self.loop.run_until_complete(proc.wait())
        if proc.returncode:
            del proc
            with open(logpath) as f_log:
                self.fail("qubes-dom0-update failed: " + f_log.read())
        del proc

        with open(logpath) as f:
            dom0_update_output = f.read()
            self.assertFalse('Errno' in dom0_update_output or
                             'Couldn\'t' in dom0_update_output,
                             "qubes-dom0-update reported an error: {}".
                             format(dom0_update_output))

        self.assertFalse(
            self.app.domains[0].features.get('updates-available', False),
            "'updates pending' flag not cleared")

    def test_010_instal(self):
        filename = self.create_pkg(self.tmpdir, self.pkg_name, '1.0')
        self.send_pkg(filename)

        logpath = os.path.join(self.tmpdir, 'dom0-update-output.txt')
        with open(logpath, 'w') as f_log:
            proc = self.loop.run_until_complete(asyncio.create_subprocess_exec(
                'qubes-dom0-update', '-y', *self.dom0_update_common_opts,
                self.pkg_name,
                stdout=f_log,
                stderr=subprocess.STDOUT))
        self.loop.run_until_complete(proc.wait())
        if proc.returncode:
            del proc
            with open(logpath) as f_log:
                self.fail("qubes-dom0-update failed: " + f_log.read())
        del proc

        retcode = subprocess.call(['rpm', '-q', '{}-1.0'.format(
            self.pkg_name)], stdout=open('/dev/null', 'w'))
        self.assertEqual(retcode, 0, 'Package {}-1.0 not installed'.format(
            self.pkg_name))

    def test_020_install_wrong_sign(self):
        subprocess.call(['rpm', '-e', 'gpg-pubkey-{}'.format(
            self.keyid)])
        filename = self.create_pkg(self.tmpdir, self.pkg_name, '1.0')
        self.send_pkg(filename)

        logpath = os.path.join(self.tmpdir, 'dom0-update-output.txt')
        with open(logpath, 'w') as f_log:
            proc = self.loop.run_until_complete(asyncio.create_subprocess_exec(
                'qubes-dom0-update', '-y', *self.dom0_update_common_opts,
                self.pkg_name,
                stdout=f_log,
                stderr=subprocess.STDOUT))
        self.loop.run_until_complete(proc.wait())
        if not proc.returncode:
            del proc
            with open(logpath) as f_log:
                self.fail("qubes-dom0-update unexpectedly succeeded: " +
                          f_log.read())
        del proc

        retcode = subprocess.call(['rpm', '-q', '{}-1.0'.format(
            self.pkg_name)], stdout=subprocess.DEVNULL)
        self.assertEqual(retcode, 1,
                         'Package {}-1.0 installed although '
                         'signature is invalid'.format(self.pkg_name))

    def test_030_install_unsigned(self):
        filename = self.create_pkg(self.tmpdir, self.pkg_name, '1.0')
        subprocess.check_call(['rpm', '--delsign', filename],
                              stdout=subprocess.DEVNULL,
                              stderr=subprocess.STDOUT)
        self.send_pkg(filename)

        logpath = os.path.join(self.tmpdir, 'dom0-update-output.txt')
        with open(logpath, 'w') as f_log:
            proc = self.loop.run_until_complete(asyncio.create_subprocess_exec(
                'qubes-dom0-update', '-y', *self.dom0_update_common_opts,
                self.pkg_name,
                stdout=f_log,
                stderr=subprocess.STDOUT))
        self.loop.run_until_complete(proc.wait())
        if not proc.returncode:
            del proc
            with open(logpath) as f_log:
                self.fail("qubes-dom0-update unexpectedly succeeded: " +
                          f_log.read())
        del proc

        retcode = subprocess.call(['rpm', '-q', '{}-1.0'.format(
            self.pkg_name)], stdout=subprocess.DEVNULL)
        self.assertEqual(retcode, 1,
                         'UNSIGNED package {}-1.0 installed'.format(self.pkg_name))

class TC_10_QvmTemplateMixin(object):
    """
    Tests for downloading dom0 updates using VMs based on different templates
    """
    template_name = os.environ.get(
        'QUBES_INSTALL_TEST_TEMPLATE', 'debian-11-minimal')
    common_args = []

    def setUp(self):
        super().setUp()
        if self.template_name in self.app.domains:
            self.skipTest(
                'Template \'{}\' is already installed, '
                'choose a different one with QUBES_INSTALL_TEST_TEMPLATE variable')
        if self.template.startswith('whonix-ws'):
            self.skipTest('Test not supported for this template')
        self.tmpdir = tempfile.mkdtemp()
        self.init_default_template(self.template)
        self.updatevm = self.app.add_new_vm(
            qubes.vm.appvm.AppVM,
            name=self.make_vm_name("updatevm"),
            label='red'
        )
        self.loop.run_until_complete(self.updatevm.create_on_disk())
        self.app.updatevm = self.updatevm
        self.app.save()
        if self.template.startswith('whonix-gw'):
            self.loop.run_until_complete(
                self.whonix_gw_setup_async(self.updatevm))
        else:
            self.loop.run_until_complete(self.updatevm.start())

    def tearDown(self):
        shutil.rmtree(self.tmpdir)
        if self.template_name in self.app.domains:
            tpl = self.app.domains[self.template_name]
            try:
                self.loop.run_until_complete(tpl.kill())
            except qubes.exc.QubesVMNotStartedError:
                pass
            except:
                self.app.log.exception('Failed to kill %s template', tpl.name)
                # but still try to continue
            del self.app.domains[tpl]
            self.loop.run_until_complete(tpl.remove_from_disk())
        super().tearDown()

    def run_qvm_template(self, *args):
        proc = self.loop.run_until_complete(asyncio.create_subprocess_exec(
            *args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE))
        stdout, stderr = self.loop.run_until_complete(proc.communicate())
        return proc.returncode, stdout, stderr

    def test_000_template_list(self):
        retcode, stdout, stderr = self.run_qvm_template('qvm-template',
                *self.common_args,
                '--repoid=qubes-templates-itl-testing',
                'list', '--machine-readable', '--available', self.template_name)
        if retcode != 0:
            self.fail("qvm-template failed: " + stderr.decode())
        self.assertIn('|' + self.template_name + '|', stdout.decode())

    def test_010_template_install(self):
        retcode, stdout, stderr = self.run_qvm_template('qvm-template',
                *self.common_args,
                '--disablerepo=*', '--enablerepo=qubes-templates-itl-testing',
                'install', self.template_name)
        if retcode != 0:
            self.fail("qvm-template failed: " + stderr.decode())
        self.assertIn(self.template_name, self.app.domains)
        # just a basic sanity check - tests whether the template starts
        # and have qrexec working
        tpl = self.app.domains[self.template_name]
        self.loop.run_until_complete(tpl.start())
        got_hostname, _ = self.loop.run_until_complete(tpl.run_for_stdio('uname -n'))
        self.assertEqual(got_hostname.decode().strip(), self.template_name)


class TC_11_QvmTemplateMgmtVMMixin(TC_10_QvmTemplateMixin):
    common_args = TC_10_QvmTemplateMixin.common_args + ['--updatevm=']
    def run_qvm_template(self, *args):
        try:
            stdout, stderr = self.loop.run_until_complete(
                self.updatevm.run_for_stdio(shlex.join(args)))
        except subprocess.CalledProcessError as e:
            if e.returncode == 127:
                self.skipTest('Package qubes-core-admin-client '
                              '(including qvm-template) not installed')
            return e.returncode, e.stdout, e.stderr
        return 0, stdout, stderr

    def setUp(self):
        super(TC_11_QvmTemplateMgmtVMMixin, self).setUp()
        self.policy_path = '/etc/qubes/policy.d/50-test-inst.policy'
        if os.path.exists(self.policy_path):
            # do not automatically remove any policy file that wasn't _for sure_
            # created by the very same test
            self.fail(
                '{} already exists, cleanup after previous test failed?'.format(
                    self.policy_path))
        with open(self.policy_path, 'w') as policy:
            policy.write('''### Qrexec policy used by tests in {file}
admin.vm.Create.TemplateVM * {vm} @adminvm allow target=dom0
admin.vm.feature.Get * {vm} @tag:created-by-{vm} allow target=dom0
admin.vm.feature.Set * {vm} @tag:created-by-{vm} allow target=dom0
admin.vm.property.Get * {vm} @tag:created-by-{vm} allow target=dom0
admin.vm.property.Set * {vm} @tag:created-by-{vm} allow target=dom0
admin.vm.property.Reset * {vm} @tag:created-by-{vm} allow target=dom0
admin.vm.CurrentState * {vm} @tag:created-by-{vm} allow target=dom0
admin.vm.Start * {vm} @tag:created-by-{vm} allow target=dom0
admin.vm.Shutdown * {vm} @tag:created-by-{vm} allow target=dom0
admin.vm.Kill * {vm} @tag:created-by-{vm} allow target=dom0
admin.vm.volume.List + {vm} @tag:created-by-{vm} allow target=dom0
admin.vm.volume.Info +root {vm} @tag:created-by-{vm} allow target=dom0
admin.vm.volume.ImportWithSize +root {vm} @tag:created-by-{vm} allow target=dom0
admin.vm.volume.Resize +root {vm} @tag:created-by-{vm} allow target=dom0
admin.vm.volume.Clear +private {vm} @tag:created-by-{vm} allow target=dom0
admin.vm.List + {vm} @adminvm allow
admin.vm.List + {vm} @tag:created-by-{vm} allow target=dom0
admin.Events * {vm} @adminvm allow target=dom0
admin.Events * {vm} @tag:created-by-{vm} allow target=dom0
qubes.PostInstall + {vm} @tag:created-by-{vm} allow
'''.format(file=__file__, vm=self.updatevm.name))

    def tearDown(self):
        os.unlink(self.policy_path)
        super(TC_11_QvmTemplateMgmtVMMixin, self).tearDown()


def create_testcases_for_templates():
    yield from qubes.tests.create_testcases_for_templates('TC_00_Dom0Upgrade',
        TC_00_Dom0UpgradeMixin, qubes.tests.SystemTestCase,
        module=sys.modules[__name__])
    yield from qubes.tests.create_testcases_for_templates('TC_10_QvmTemplate',
        TC_10_QvmTemplateMixin, qubes.tests.SystemTestCase,
        module=sys.modules[__name__])
    yield from qubes.tests.create_testcases_for_templates('TC_11_QvmTemplateMgmtVM',
        TC_11_QvmTemplateMgmtVMMixin, qubes.tests.SystemTestCase,
        module=sys.modules[__name__])

def load_tests(loader, tests, pattern):
    tests.addTests(loader.loadTestsFromNames(
        create_testcases_for_templates()))
    return tests

qubes.tests.maybe_create_testcases_on_import(create_testcases_for_templates)
