# -*- encoding: utf-8 -*-
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

import asyncio
import json
import os
import shutil
import subprocess
import sys
import unittest
import warnings

import qubes.tests

class SaltTestMixin(object):
    def setUp(self):
        super().setUp()
        self.salt_testdir = '/srv/salt/test_salt'
        os.makedirs(self.salt_testdir, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.salt_testdir)
        try:
            tops = '/srv/salt/_tops/base'
            for top_link in os.listdir(tops):
                path = os.path.join(tops, top_link)
                target = os.readlink(path)
                if target.startswith(self.salt_testdir):
                    os.unlink(path)
        except FileNotFoundError:
            pass
        super().tearDown()

    def salt_call(self, cmd):
        full_cmd = ['qubesctl']
        if '--dom0-only' in cmd:
            full_cmd.insert(1, '--dom0-only')
            cmd.remove('--dom0-only')
        full_cmd.extend(cmd)
        full_cmd.append('--out=json')
        p = self.loop.run_until_complete(asyncio.create_subprocess_exec(
            *full_cmd, stdout=subprocess.PIPE))
        output, _ = self.loop.run_until_complete(p.communicate())
        if p.returncode != 0:
            raise AssertionError(
                'Salt command \'{}\' failed with code {}. '
                'Full output: {}'.format(full_cmd, p.returncode, output))
        return output.decode()

    def dom0_salt_call_json(self, cmd):
        return json.loads(self.salt_call(['--dom0-only'] + cmd))


class TC_00_Dom0(SaltTestMixin, qubes.tests.SystemTestCase):
    def test_000_top_enable_disable(self):
        with open(os.path.join(self.salt_testdir, 'something.sls'), 'w') as f:
            f.write('test-top-enable:\n')
            f.write('  test.succeed_without_changes: []\n')
        with open(os.path.join(self.salt_testdir, 'something.top'), 'w') as f:
            f.write('base:\n')
            f.write('  dom0:\n')
            f.write('    - test_salt.something\n')

        cmd_output = self.dom0_salt_call_json(
            ['top.enable', 'test_salt.something'])
        self.assertEqual(cmd_output,
            {'local': {'test_salt.something.top': {'status': 'enabled'}}})

        cmd_output = self.dom0_salt_call_json(['state.show_top'])
        self.assertIn('local', cmd_output)
        self.assertIn('base', cmd_output['local'])
        self.assertIn('test_salt.something', cmd_output['local']['base'])

        cmd_output = self.dom0_salt_call_json(
            ['top.disable', 'test_salt.something'])
        #self.assertEqual(cmd_output,
        #    {'local': {'test_salt.something.top': {'status': 'disabled'}}})

        cmd_output = self.dom0_salt_call_json(['state.show_top'])
        self.assertIn('local', cmd_output)
        self.assertNotIn('test_salt.something', cmd_output['local'].get('base', []))

    def test_001_state_sls(self):
        with open(os.path.join(self.salt_testdir, 'something.sls'), 'w') as f:
            f.write('test-top-enable:\n')
            f.write('  test.succeed_without_changes: []\n')

        cmd_output = self.dom0_salt_call_json(
            ['state.sls', 'test_salt.something'])
        state_id = 'test_|-test-top-enable_|-test-top-enable_|-succeed_without_changes'
        self.assertIn('local', cmd_output)
        self.assertIn(state_id, cmd_output['local'])
        self.assertIn('start_time', cmd_output['local'][state_id])
        del cmd_output['local'][state_id]['start_time']
        self.assertIn('duration', cmd_output['local'][state_id])
        del cmd_output['local'][state_id]['duration']
        self.assertEqual(cmd_output,
            {'local': {state_id: {
                'name': 'test-top-enable',
                'comment': 'Success!',
                'result': True,
                '__run_num__': 0,
                '__sls__': 'test_salt.something',
                'changes': {},
                '__id__': 'test-top-enable'
            }}})

    def test_010_create_vm(self):
        vmname = self.make_vm_name('appvm')
        with open(os.path.join(self.salt_testdir, 'create_vm.sls'), 'w') as f:
            f.write(vmname + ':\n')
            f.write('  qvm.vm:\n')
            f.write('    - present:\n')
            f.write('      - label: orange\n')
            f.write('    - prefs:\n')
            f.write('      - vcpus: 1\n')
        cmd_output = self.dom0_salt_call_json(
            ['state.sls', 'test_salt.create_vm'])
        state_out = list(cmd_output['local'].values())[0]
        del state_out['start_time']
        del state_out['duration']
        self.assertEqual(state_out, {
            'comment': '====== [\'present\'] ======\n'
                       '/usr/bin/qvm-create {} --class=AppVM --label=orange \n'
                       '\n'
                       '====== [\'prefs\'] ======\n'.format(vmname),
            'name': vmname,
            'result': True,
            'changes': {
                'qvm.prefs': {'qvm.create': {
                        'vcpus': {'new': 1, 'old': '*default*'}
                    }
                },
            },
            '__sls__': 'test_salt.create_vm',
            '__run_num__': 0,
            '__id__': vmname,
        })

        self.assertIn(vmname, self.app.domains)
        vm = self.app.domains[vmname]
        self.assertEqual(str(vm.label), 'orange')
        self.assertEqual(vm.vcpus, 1)

    def test_011_set_prefs(self):
        vmname = self.make_vm_name('appvm')

        vm = self.app.add_new_vm('AppVM', label='red',
            name=vmname)
        self.loop.run_until_complete(vm.create_on_disk())

        with open(os.path.join(self.salt_testdir, 'create_vm.sls'), 'w') as f:
            f.write(vmname + ':\n')
            f.write('  qvm.vm:\n')
            f.write('    - present:\n')
            f.write('      - label: orange\n')
            f.write('    - prefs:\n')
            f.write('      - vcpus: 1\n')
        cmd_output = self.dom0_salt_call_json(
            ['state.sls', 'test_salt.create_vm'])
        state_out = list(cmd_output['local'].values())[0]
        del state_out['start_time']
        del state_out['duration']
        self.assertEqual(state_out, {
            'comment': '====== [\'present\'] ======\n'
                       '[SKIP] A VM with the name \'{}\' already exists.\n'
                       '\n'
                       '====== [\'prefs\'] ======\n'.format(vmname),
            'name': vmname,
            'result': True,
            'changes': {
                'qvm.prefs': {'qvm.create': {
                        'vcpus': {'new': 1, 'old': '*default*'}
                    }
                },
            },
            '__sls__': 'test_salt.create_vm',
            '__run_num__': 0,
            '__id__': vmname,
        })

        self.assertIn(vmname, self.app.domains)
        vm = self.app.domains[vmname]
        self.assertEqual(str(vm.label), 'red')
        self.assertEqual(vm.vcpus, 1)

    def test_012_tags(self):
        vmname = self.make_vm_name('appvm')

        vm = self.app.add_new_vm('AppVM', label='red',
            name=vmname)
        self.loop.run_until_complete(vm.create_on_disk())
        new_tags = list(sorted(list(vm.tags) + ['tag1', 'tag2']))
        vm.tags.add('tag1')
        vm.tags.add('tag3')
        old_tags = list(sorted(vm.tags))

        with open(os.path.join(self.salt_testdir, 'test_state.sls'), 'w') as f:
            f.write(vmname + ':\n')
            f.write('  qvm.vm:\n')
            f.write('    - tags:\n')
            f.write('      - present:\n')
            f.write('        - tag1\n')
            f.write('        - tag2\n')
            f.write('      - absent:\n')
            f.write('        - tag3\n')
            f.write('        - tag4\n')
        cmd_output = self.dom0_salt_call_json(
            ['state.sls', 'test_salt.test_state'])
        state_out = list(cmd_output['local'].values())[0]
        del state_out['start_time']
        del state_out['duration']
        self.maxDiff = None
        self.assertEqual(state_out, {
            'comment': '====== [\'tags\'] ======\n',
            'name': vmname,
            'result': True,
            'changes': {
                'qvm.tags': {'qvm.tags': {
                        'new': new_tags, 'old': old_tags,
                    }
                },
            },
            '__sls__': 'test_salt.test_state',
            '__run_num__': 0,
            '__id__': vmname,
        })

        self.assertIn(vmname, self.app.domains)
        vm = self.app.domains[vmname]
        self.assertEqual(set(vm.tags), set(new_tags))

    def test_020_qubes_pillar(self):
        vmname = self.make_vm_name('appvm')

        vm = self.app.add_new_vm('AppVM', label='red',
            name=vmname)
        self.loop.run_until_complete(vm.create_on_disk())
        vm.features['vm-config.test'] = 'value'
        # this should not be included in pillar
        vm.features['internal'] = '1'

        cmd_output = self.dom0_salt_call_json(
            ['pillar.items', '--id=' + vmname])
        self.assertIn('local', cmd_output)
        self.assertIn('qubes', cmd_output['local'])
        qubes_pillar = cmd_output['local']['qubes']
        self.assertEqual(qubes_pillar, {
            'type': 'app',
            'netvm': str(vm.netvm),
            'template': str(vm.template),
            'features': {'vm-config.test': 'value'},
            'tags': ['audiovm-dom0', 'guivm-dom0'],
        })

class SaltVMTestMixin(SaltTestMixin):
    template = None

    def setUp(self):
        if self.template.startswith('whonix'):
            self.skipTest('Whonix not supported as salt VM')
        super(SaltVMTestMixin, self).setUp()
        self.init_default_template(self.template)

        dispvm_tpl_name = self.make_vm_name('disp-tpl')
        dispvm_tpl = self.app.add_new_vm('AppVM', label='red',
            template_for_dispvms=True, name=dispvm_tpl_name)
        self.loop.run_until_complete(dispvm_tpl.create_on_disk())
        self.app.default_dispvm = dispvm_tpl
        self.app.management_dispvm = dispvm_tpl
        if self.id().endswith('user_sls'):
            if os.path.exists('/srv/user_salt'):
                shutil.copy('/srv/user_salt/top.sls', '/srv/user_salt/top.sls.test-bak')
                self.user_salt_exists = True
            else:
                self.salt_call(["--dom0-only", "state.sls", "qubes.user-dirs"])
                self.user_salt_exists = False

    def tearDown(self):
        if hasattr(self, "user_salt_exists"):
            if self.user_salt_exists:
                os.unlink("/srv/user_salt/top.sls")
                os.rename("/srv/user_salt/top.sls.test-bak", "/srv/user_salt/top.sls")
            else:
                shutil.rmtree("/srv/user_salt")
                shutil.rmtree("/srv/user_pillar")
                shutil.rmtree("/srv/user_formulas")

        self.app.default_dispvm = None
        super(SaltVMTestMixin, self).tearDown()

    def test_000_simple_sls(self):
        vmname = self.make_vm_name('target')
        self.vm = self.app.add_new_vm('AppVM', name=vmname, label='red')
        self.loop.run_until_complete(self.vm.create_on_disk())
        # start the VM manually, so it stays running after applying salt state
        self.loop.run_until_complete(self.vm.start())
        with open(os.path.join(self.salt_testdir, 'something.sls'), 'w') as f:
            f.write('/home/user/testfile:\n')
            f.write('  file.managed:\n')
            f.write('    - contents: |\n')
            f.write('        this is test\n')
        with open(os.path.join(self.salt_testdir, 'something.top'), 'w') as f:
            f.write('base:\n')
            f.write('  {}:\n'.format(vmname))
            f.write('    - test_salt.something\n')

        # enable so state.show_top will not be empty, otherwise qubesctl will
        #  skip the VM; but we don't use state.highstate
        self.dom0_salt_call_json(['top.enable', 'test_salt.something'])
        state_output = self.salt_call(
            ['--skip-dom0', '--show-output', '--targets=' + vmname,
             'state.sls', 'test_salt.something'])
        expected_output = vmname + ':\n'
        self.assertTrue(state_output.startswith(expected_output),
            'Full output: ' + state_output)
        state_id = 'file_|-/home/user/testfile_|-/home/user/testfile_|-managed'
        # drop the header
        json_data = state_output[len(expected_output):].strip()
        # skip trailing junk to workaround
        # https://github.com/saltstack/salt/issues/65604 and similar
        try:
            decoder = json.JSONDecoder()
            state_output_json, end = decoder.raw_decode(json_data)
            if end != len(json_data):
                warnings.warn(f"Trailing junk in json output: {json_data[end:]}")
        except json.decoder.JSONDecodeError as e:
            self.fail("JSON output decoding error: {}\n{}".format(
                e, json_data
            ))
        state_output_json = state_output_json[vmname][state_id]
        try:
            del state_output_json['duration']
            del state_output_json['start_time']
        except KeyError:
            pass

        try:
            del state_output_json['pchanges']
        except KeyError:
            pass

        try:
            # older salt do not report this
            self.assertEqual(state_output_json['__id__'], '/home/user/testfile')
            del state_output_json['__id__']
        except KeyError:
            pass

        try:
            # or sls file
            self.assertEqual(state_output_json['__sls__'],
                'test_salt.something')
            del state_output_json['__sls__']
        except KeyError:
            pass
        # different output depending on salt version
        expected_output = {
            '__run_num__': 0,
            'changes': {
                'diff': 'New file',
            },
            'name': '/home/user/testfile',
            'comment': 'File /home/user/testfile updated',
            'result': True,
        }
        self.assertEqual(state_output_json, expected_output)
        stdout, stderr = self.loop.run_until_complete(self.vm.run_for_stdio(
            'cat /home/user/testfile'))
        self.assertEqual(stdout, b'this is test\n')
        self.assertEqual(stderr, b'')

    def test_001_multi_state_highstate(self):
        vmname = self.make_vm_name('target')
        self.vm = self.app.add_new_vm('AppVM', name=vmname, label='red')
        self.loop.run_until_complete(self.vm.create_on_disk())
        # start the VM manually, so it stays running after applying salt state
        self.loop.run_until_complete(self.vm.start())
        states = ('something', 'something2')
        for state in states:
            with open(os.path.join(self.salt_testdir, state + '.sls'), 'w') as f:
                f.write('/home/user/{}:\n'.format(state))
                f.write('  file.managed:\n')
                f.write('    - contents: |\n')
                f.write('        this is test\n')
            with open(os.path.join(self.salt_testdir, state + '.top'), 'w') as f:
                f.write('base:\n')
                f.write('  {}:\n'.format(vmname))
                f.write('    - test_salt.{}\n'.format(state))
        # test with some jinja templating
        state = 'jinja'
        with open(os.path.join(self.salt_testdir, state + '.sls'), 'w') as f:
            f.write("{% set ex = salt['cmd.shell']('echo what') %}\n")
            f.write("{% if ex.startswith('what') %}\n")
            f.write("/home/user/{}:\n".format(state))
            f.write("  file.managed:\n")
            f.write("    - contents: |\n")
            f.write("        this is test\n")
            f.write("{% endif %}\n")
            f.write("/home/user/test2:\n")
            f.write("  file.managed:\n")
            f.write("    - contents: |\n")
            f.write("        {{ grains['id'] }}\n")
        with open(os.path.join(self.salt_testdir, state + '.top'), 'w') as f:
            f.write('base:\n')
            f.write('  {}:\n'.format(vmname))
            f.write('    - test_salt.{}\n'.format(state))

        self.dom0_salt_call_json(['top.enable', 'test_salt.something'])
        self.dom0_salt_call_json(['top.enable', 'test_salt.something2'])
        self.dom0_salt_call_json(['top.enable', 'test_salt.jinja'])
        state_output = self.salt_call(
            ['--skip-dom0', '--show-output', '--targets=' + vmname,
             'state.highstate'])
        expected_output = vmname + ':\n'
        self.assertTrue(state_output.startswith(expected_output),
            'Full output: ' + state_output)
        json_data = state_output[len(expected_output):].strip()
        # skip trailing junk to workaround
        # https://github.com/saltstack/salt/issues/65604 and similar
        try:
            decoder = json.JSONDecoder()
            state_output_json, end = decoder.raw_decode(json_data)
            if end != len(json_data):
                warnings.warn(f"Trailing junk in json output: {json_data[end:]}")
        except json.decoder.JSONDecodeError as e:
            self.fail("JSON output decoding error: {}\n{}".format(
                e, json_data
            ))
        states = states + ('jinja',)
        for state in states:
            state_id = \
                'file_|-/home/user/{0}_|-/home/user/{0}_|-managed'.format(state)
            # drop the header
            self.assertIn(state_id, state_output_json[vmname])
            state_output_single = state_output_json[vmname][state_id]

            self.assertTrue(state_output_single['result'])
            self.assertNotEqual(state_output_single['changes'], {})

            stdout, stderr = self.loop.run_until_complete(self.vm.run_for_stdio(
                'cat /home/user/' + state))
            self.assertEqual(stdout, b'this is test\n')
            self.assertEqual(stderr, b'')

            stdout, stderr = self.loop.run_until_complete(self.vm.run_for_stdio(
                'cat /home/user/' + state))
            self.assertEqual(stdout, b'this is test\n')
            self.assertEqual(stderr, b'')

        # and finally verify if grain id is correct
        stdout, stderr = self.loop.run_until_complete(self.vm.run_for_stdio(
            'cat /home/user/test2'))
        self.assertEqual(stdout, '{}\n'.format(self.vm.name).encode())
        self.assertEqual(stderr, b'')

    @unittest.expectedFailure
    def test_002_grains_id(self):
        vmname = self.make_vm_name('target')
        tplname = self.make_vm_name('tpl')
        self.test_template = self.app.add_new_vm('TemplateVM',
            name=tplname, label='red')
        self.test_template.features.update(
            self.app.domains[self.template].features)
        self.loop.run_until_complete(
            self.test_template.clone_disk_files(self.app.domains[self.template]))
        self.vm = self.app.add_new_vm('AppVM', name=vmname, label='red',
                                      template=self.test_template)
        self.loop.run_until_complete(self.vm.create_on_disk())
        # test with some jinja templating
        with open(os.path.join(self.salt_testdir, 'jinja.sls'), 'w') as f:
            f.write("/home/user/test2-{{ grains['id'] }}:\n")
            f.write("  file.managed:\n")
            f.write("    - contents: |\n")
            f.write("        {{ grains['id'] }}\n")
        with open(os.path.join(self.salt_testdir, 'jinja.top'), 'w') as f:
            f.write('base:\n')
            f.write('  {}:\n'.format(vmname))
            f.write('    - test_salt.jinja\n')
            f.write('  {}:\n'.format(tplname))
            f.write('    - test_salt.jinja\n')

        self.dom0_salt_call_json(['top.enable', 'test_salt.jinja'])
        state_output = self.salt_call(
            ['--skip-dom0', '--show-output',
             '--targets={},{}'.format(tplname, vmname),
             'state.highstate'])
        self.assertIn(tplname + ':\n', state_output)
        self.assertIn(vmname + ':\n', state_output)
        tpl_output, _, appvm_output = state_output.partition(vmname + ':\n')
        self.assertTrue(tpl_output.startswith(tplname + ':\n'),
            'Full output: ' + state_output)
        tpl_output = tpl_output[len(tplname + ':\n'):].strip()
        appvm_output = appvm_output.strip()

        for name, output in ((tplname, tpl_output), (vmname, appvm_output)):
            # skip trailing junk to workaround
            # https://github.com/saltstack/salt/issues/65604 and similar
            try:
                decoder = json.JSONDecoder()
                state_output_json, end = decoder.raw_decode(output)
                if end != len(output):
                    warnings.warn(f"Trailing junk in json output: {output[end:]}")
            except json.decoder.JSONDecodeError as e:
                self.fail("JSON output decoding error: {}\n{}".format(
                    e, output
                ))
            state_id = \
                'file_|-/home/user/test2-{0}_|-/home/user/test2-{0}_|-managed'.format(name)
            # drop the header
            self.assertIn(state_id, state_output_json[name])
            state_output_single = state_output_json[name][state_id]

            self.assertTrue(state_output_single['result'])
            self.assertNotEqual(state_output_single['changes'], {})

    def test_003_update(self):
        vmname = self.make_vm_name('target')
        self.vm = self.app.add_new_vm('AppVM', name=vmname, label='red')
        self.loop.run_until_complete(self.vm.create_on_disk())
        # start the VM manually, so it stays running after applying salt state
        self.loop.run_until_complete(self.vm.start())
        state_output = self.salt_call(
            ['--skip-dom0', '--show-output', '--targets=' + vmname,
             'state.sls', 'update.qubes-vm'])
        expected_output = vmname + ':\n'
        self.assertTrue(state_output.startswith(expected_output),
            'Full output: ' + state_output)
        json_data = state_output[len(expected_output):].strip()
        # skip trailing junk to workaround
        # https://github.com/saltstack/salt/issues/65604 and similar
        try:
            decoder = json.JSONDecoder()
            state_output_json, end = decoder.raw_decode(json_data)
            if end != len(json_data):
                warnings.warn(f"Trailing junk in json output: {json_data[end:]}")
        except json.decoder.JSONDecodeError as e:
            self.fail("JSON output decoding error: {}\n{}".format(
                e, json_data
            ))
        self.assertIn(vmname, state_output_json)
        self.assertNotEqual(state_output_json[vmname], {})
        for state, result in state_output_json[vmname].items():
            self.assertTrue(
                result['result'],
                "State {} failed: {!r}".format(state, result))

    def test_004_user_sls(self):
        vmname = self.make_vm_name('target')
        self.vm = self.app.add_new_vm('AppVM', name=vmname, label='red')
        self.loop.run_until_complete(self.vm.create_on_disk())
        # start the VM manually, so it stays running after applying salt state
        self.loop.run_until_complete(self.vm.start())
        os.makedirs("/srv/user_salt/test_salt", exist_ok=True)
        with open("/srv/user_salt/test_salt/something.sls", "w") as f:
            f.write('/home/user/testfile:\n')
            f.write('  file.managed:\n')
            f.write('    - contents: |\n')
            f.write('        this is test\n')
        with open('/srv/user_salt/top.sls', 'a') as f:
            f.write('user:\n')
            f.write('  {}:\n'.format(vmname))
            f.write('    - test_salt.something\n')

        state_output = self.salt_call(
            ['--skip-dom0', '--show-output', '--targets=' + vmname,
             'state.highstate'])
        expected_output = vmname + ':\n'
        self.assertTrue(state_output.startswith(expected_output),
            'Full output: ' + state_output)
        state_id = 'file_|-/home/user/testfile_|-/home/user/testfile_|-managed'
        # drop the header
        json_data = state_output[len(expected_output):].strip()
        # skip trailing junk to workaround
        # https://github.com/saltstack/salt/issues/65604 and similar
        try:
            decoder = json.JSONDecoder()
            state_output_json, end = decoder.raw_decode(json_data)
            if end != len(json_data):
                warnings.warn(f"Trailing junk in json output: {json_data[end:]}")
        except json.decoder.JSONDecodeError as e:
            self.fail("JSON output decoding error: {}\n{}".format(
                e, json_data
            ))
        state_output_json = state_output_json[vmname][state_id]
        try:
            del state_output_json['duration']
            del state_output_json['start_time']
        except KeyError:
            pass

        try:
            del state_output_json['pchanges']
        except KeyError:
            pass

        try:
            # older salt do not report this
            self.assertEqual(state_output_json['__id__'], '/home/user/testfile')
            del state_output_json['__id__']
        except KeyError:
            pass

        try:
            # or sls file
            self.assertEqual(state_output_json['__sls__'],
                'test_salt.something')
            del state_output_json['__sls__']
        except KeyError:
            pass
        # different output depending on salt version
        expected_output = {
            '__run_num__': 0,
            'changes': {
                'diff': 'New file',
            },
            'name': '/home/user/testfile',
            'comment': 'File /home/user/testfile updated',
            'result': True,
        }
        self.assertEqual(state_output_json, expected_output)
        stdout, stderr = self.loop.run_until_complete(self.vm.run_for_stdio(
            'cat /home/user/testfile'))
        self.assertEqual(stdout, b'this is test\n')
        self.assertEqual(stderr, b'')


def create_testcases_for_templates():
    return qubes.tests.create_testcases_for_templates('TC_10_VMSalt',
        SaltVMTestMixin, qubes.tests.SystemTestCase,
        module=sys.modules[__name__])


def load_tests(loader, tests, pattern):
    tests.addTests(loader.loadTestsFromNames(
        create_testcases_for_templates()))
    return tests

qubes.tests.maybe_create_testcases_on_import(create_testcases_for_templates)
