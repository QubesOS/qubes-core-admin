#
# The Qubes OS Project, http://www.qubes-os.org
#
# Copyright (C) 2015 Marek Marczykowski-Górecki <marmarek@invisiblethingslab.com>
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
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301,
# USA.
#

import os
import shutil
import subprocess
import tempfile
import unittest

import asyncio

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
    update_flag_path = '/var/lib/qubes/updates/dom0-updates-available'

    @classmethod
    def generate_key(cls, keydir):
        gpg_opts = ['gpg', '--quiet', '--no-default-keyring',
                    '--homedir', keydir]
        p = subprocess.Popen(gpg_opts + ['--gen-key', '--batch'],
                             stdin=subprocess.PIPE,
                             stderr=open(os.devnull, 'w'))
        p.stdin.write('''
Key-Type: RSA
Key-Length: 1024
Key-Usage: sign
Name-Real: Qubes test
Expire-Date: 0
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

        p = subprocess.Popen(['sudo', 'dd',
                              'status=none', 'of=/etc/yum.repos.d/test.repo'],
                             stdin=subprocess.PIPE)
        p.stdin.write(b'''
[test]
name = Test
baseurl = http://localhost:8080/
enabled = 1
''')
        p.stdin.close()
        p.wait()


    @classmethod
    def tearDownClass(cls):
        subprocess.check_call(['sudo', 'rm', '-f',
                               '/etc/yum.repos.d/test.repo'])

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
        subprocess.call(['sudo', 'rpm', '-e', self.pkg_name],
                        stderr=subprocess.DEVNULL)
        subprocess.check_call(['sudo', 'rpm', '--import',
                               os.path.join(self.tmpdir, 'pubkey.asc')])
        self.loop.run_until_complete(self.updatevm.start())
        self.repo_running = False
        self.repo_proc = None

    def tearDown(self):
        if self.repo_proc:
            self.repo_proc.terminate()
            self.loop.run_until_complete(self.repo_proc.wait())
            del self.repo_proc
        super(TC_00_Dom0UpgradeMixin, self).tearDown()

        subprocess.call(['sudo', 'rpm', '-e', self.pkg_name],
            stderr=subprocess.DEVNULL)
        subprocess.call(['sudo', 'rpm', '-e', 'gpg-pubkey-{}'.format(
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
        subprocess.check_call(['sudo', 'chmod', 'go-rw', '/dev/tty'])
        subprocess.check_call(
            ['rpm', '--quiet', '--define=_gpg_path {}'.format(dir),
             '--define=_gpg_name {}'.format("Qubes test"),
             '--addsign', pkg_path],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT)
        subprocess.check_call(['sudo', 'chmod', 'go+rw', '/dev/tty'])
        return pkg_path

    def send_pkg(self, filename):
        with open(filename, 'rb') as f_pkg:
            self.loop.run_until_complete(self.updatevm.run_for_stdio(
                'mkdir -p /tmp/repo; cat > /tmp/repo/{}'.format(
                    os.path.basename(filename)),
                input=f_pkg.read()))
        try:
            self.loop.run_until_complete(
                self.updatevm.run_for_stdio('cd /tmp/repo; createrepo .'))
        except subprocess.CalledProcessError as e:
            if e.returncode == 127:
                self.skipTest('createrepo not installed in template {}'.format(
                    self.template))
            else:
                self.skipTest('createrepo failed with code {}, '
                    'cannot perform the test'.format(e.returncode))
        self.start_repo()

    def start_repo(self):
        if self.repo_running:
            return
        self.repo_proc = self.loop.run_until_complete(self.updatevm.run(
            'cd /tmp/repo && python -m SimpleHTTPServer 8080'))
        self.repo_running = True

    def test_000_update(self):
        """Dom0 update tests

        Check if package update is:
         - detected
         - installed
         - "updates pending" flag is cleared
        """
        filename = self.create_pkg(self.tmpdir, self.pkg_name, '1.0')
        subprocess.check_call(['sudo', 'rpm', '-i', filename])
        filename = self.create_pkg(self.tmpdir, self.pkg_name, '2.0')
        self.send_pkg(filename)
        open(self.update_flag_path, 'a').close()

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
        self.assertFalse(os.path.exists(self.update_flag_path),
                         "'updates pending' flag not cleared")

    def test_005_update_flag_clear(self):
        """Check if 'updates pending' flag is creared"""

        # create any pkg (but not install it) to initialize repo in the VM
        filename = self.create_pkg(self.tmpdir, self.pkg_name, '1.0')
        self.send_pkg(filename)
        open(self.update_flag_path, 'a').close()

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

        self.assertFalse(os.path.exists(self.update_flag_path),
                         "'updates pending' flag not cleared")

    def test_006_update_flag_clear(self):
        """Check if 'updates pending' flag is creared, using --clean"""

        # create any pkg (but not install it) to initialize repo in the VM
        filename = self.create_pkg(self.tmpdir, self.pkg_name, '1.0')
        self.send_pkg(filename)
        open(self.update_flag_path, 'a').close()

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

        self.assertFalse(os.path.exists(self.update_flag_path),
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
        subprocess.call(['sudo', 'rpm', '-e', 'gpg-pubkey-{}'.format(
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


def load_tests(loader, tests, pattern):
    for template in qubes.tests.list_templates():
        tests.addTests(loader.loadTestsFromTestCase(
            type(
                'TC_00_Dom0Upgrade_' + template,
                (TC_00_Dom0UpgradeMixin, qubes.tests.SystemTestCase),
                {'template': template})))

    return tests
