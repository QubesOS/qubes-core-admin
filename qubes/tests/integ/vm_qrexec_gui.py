#
# The Qubes OS Project, https://www.qubes-os.org/
#
# Copyright (C) 2014-2015
#                   Marek Marczykowski-Górecki <marmarek@invisiblethingslab.com>
# Copyright (C) 2015  Wojtek Porczyk <woju@invisiblethingslab.com>
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
import os
import subprocess
import signal
import sys
import tempfile
import json
import unittest

from distutils import spawn

import grp

import qubes.config
import qubes.devices
import qubes.tests
import qubes.vm.appvm
import qubes.vm.templatevm

import numpy as np

in_qemu = os.path.exists("/sys/firmware/qemu_fw_cfg")

class TC_00_AppVMMixin(object):
    def setUp(self):
        super(TC_00_AppVMMixin, self).setUp()
        self.init_default_template(self.template)
        if self._testMethodName == 'test_210_time_sync':
            self.init_networking()
        self.testvm1 = self.app.add_new_vm(
            qubes.vm.appvm.AppVM,
            label='red',
            name=self.make_vm_name('vm1'),
            template=self.app.domains[self.template])
        self.loop.run_until_complete(self.testvm1.create_on_disk())
        self.testvm2 = self.app.add_new_vm(
            qubes.vm.appvm.AppVM,
            label='red',
            name=self.make_vm_name('vm2'),
            template=self.app.domains[self.template])
        self.loop.run_until_complete(self.testvm2.create_on_disk())
        if self.template.startswith('whonix-g'):
            # Whonix Gateway loudly complains if the VM doesn't provide network,
            # which spams the screen with error messages that interfere with
            # other tests
            self.testvm1.provides_network = True
            self.testvm2.provides_network = True
        self.app.save()

class TC_00_AudioMixin(TC_00_AppVMMixin):
    def wait_for_pulseaudio_startup(self, vm):
        self.loop.run_until_complete(
            self.wait_for_session(self.testvm1))
        try:
            self.loop.run_until_complete(vm.run_for_stdio(
                "timeout 30s sh -c 'while ! pactl info; do sleep 1; done'"
            ))
        except subprocess.CalledProcessError as e:
            self.fail('Timeout waiting for pulseaudio start in {}: {}{}'.format(
                vm.name, e.stdout, e.stderr))
        # then wait for the stream to appear in dom0
        local_user = grp.getgrnam('qubes').gr_mem[0]
        p = self.loop.run_until_complete(asyncio.create_subprocess_shell(
            "sudo -E -u {} timeout 60s sh -c '"
            "while ! pactl list sink-inputs | grep -q :{}; do sleep 1; done'"
            .format(local_user, vm.name)))
        self.loop.run_until_complete(p.wait())
        # and some more...
        self.loop.run_until_complete(asyncio.sleep(1))

    def prepare_audio_test(self, backend):
        if 'whonix-g' in self.template:
            self.skipTest('whonix gateway have no audio')
        self.loop.run_until_complete(self.testvm1.start())
        pulseaudio_units = 'pulseaudio.socket pulseaudio.service'
        pipewire_units = 'pipewire.socket wireplumber.service pipewire.service'
        if backend == 'pipewire':
            if not self.testvm1.features.check_with_template('supported-service.pipewire', False):
                self.skipTest('PipeWire not supported in VM')
            if 'debian-11' in self.template or 'whonix' in self.template:
                self.skipTest('PipeWire audio not supported in Debian 11')
            self.testvm1.features['service.pipewire'] = True
        elif backend == 'pulseaudio':
            # Use PulseAudio if it is installed.  If it is not installed,
            # PipeWire will still run, and its PulseAudio emulation will
            # be tested.
            self.testvm1.features['service.pipewire'] = False
        else:
            self.fail('bad audio backend')
        self.wait_for_pulseaudio_startup(self.testvm1)

    def create_audio_vm(self, backend, start=True):
        self.audiovm = self.app.add_new_vm(
            qubes.vm.appvm.AppVM,
            label='red',
            name=self.make_vm_name('audiovm'),
            template=self.app.domains[self.template])
        self.loop.run_until_complete(self.audiovm.create_on_disk())
        with open("/etc/qubes/policy.d/10-test-audiovm.policy", "w") as f:
            f.write("""
admin.Events          *   {vm}     {vm}               allow   target=dom0
admin.Events          *   {vm}     @adminvm                allow   target=dom0
admin.Events          *   {vm}     @tag:audiovm-{vm}  allow   target=dom0
admin.vm.CurrentState *   {vm}     {vm}               allow   target=dom0
admin.vm.CurrentState *   {vm}     @adminvm                allow   target=dom0
admin.vm.CurrentState *   {vm}     @tag:audiovm-{vm}  allow   target=dom0
admin.vm.List         *   {vm}     {vm}               allow   target=dom0
admin.vm.List         *   {vm}     @adminvm                allow   target=dom0
admin.vm.List         *   {vm}     @tag:audiovm-{vm}  allow   target=dom0
admin.vm.property.Get               +audiovm {vm}     @tag:audiovm-{vm}  allow   target=dom0
admin.vm.property.Get               +xid     {vm}     @tag:audiovm-{vm}  allow   target=dom0
admin.vm.property.Get               +stubdom_xid     {vm}     @tag:audiovm-{vm}  allow   target=dom0
admin.vm.property.Get               +virt_mode     {vm}     @tag:audiovm-{vm}  allow   target=dom0
admin.vm.feature.CheckWithTemplate  +audio   {vm}     @tag:audiovm-{vm}  allow   target=dom0
admin.vm.feature.CheckWithTemplate  +audio-model   {vm}     @tag:audiovm-{vm}  allow   target=dom0
""".format(vm=self.audiovm.name))
        self.addCleanup(os.unlink, "/etc/qubes/policy.d/10-test-audiovm.policy")
        self.audiovm.features['service.audiovm'] = True
        if start:
            self.loop.run_until_complete(self.audiovm.start())

    def check_pacat_running(self, audiovm, xid):
        pidfile = f"/run/qubes/pacat.{xid}"
        if audiovm.qid == 0:
            try:
                with open(pidfile) as f:
                    pid = int(f.readline())
                os.kill(pid, 0)
                running = True
            except (FileNotFoundError, ProcessLookupError, ValueError):
                running = False
        else:
            try:
                self.loop.run_until_complete(audiovm.run_for_stdio(f"kill -0 $(cat {pidfile})"))
                running = True
            except subprocess.CalledProcessError:
                running = False
        return running

    def assert_pacat_running(self, audiovm, testvm, expected=True):
        if testvm.features.get('audio-model', None):
            xid = testvm.stubdom_xid
        else:
            xid = testvm.xid
        running = None
        for attempt in range(10):
            running = self.check_pacat_running(audiovm, xid)
            if running == expected:
                break
            self.loop.run_until_complete(asyncio.sleep(1))
        if expected != running:
            self.fail(f"pacat for {testvm.name} (xid {xid}) running({running}) "
                      f"in {audiovm.name} while expected running({expected})")

    def check_audio_sample(self, sample, sfreq):
        rec = np.fromstring(sample, dtype=np.float32)
        # determine sample size using silence threshold
        threshold = 10**-3
        rec_size = np.count_nonzero((rec > threshold) | (rec < -threshold))
        if not rec_size:
            self.fail('only silence detected, no useful audio data')
        margin = 0.95
        if in_qemu and self.testvm1.features.get('audio-model'):
            # be less strict on HVM tests in nested virt, the test environment
            # has huge overhead already
            margin = 0.80
        if rec_size < margin*441000:
            fname = f"/tmp/audio-sample-{self.id()}.raw"
            with open(fname, "wb") as f:
                f.write(sample)
            self.fail(f'too short audio, expected 10s, got {rec_size/44100}, saved to {fname}')
        # find zero crossings
        crossings = np.nonzero((rec[1:] > threshold) &
                            (rec[:-1] < -threshold))[0]
        np.seterr('raise')
        # compare against sine wave frequency
        rec_freq = 44100/np.mean(np.diff(crossings))
        if not sfreq*0.8 < rec_freq < sfreq*1.2:
            fname = f"/tmp/audio-sample-{self.id()}.raw"
            with open(fname, "wb") as f:
                f.write(sample)
            self.fail('frequency {} not in specified range, saved to {}'
                    .format(rec_freq, fname))

    def common_audio_playback(self):
        # sine frequency
        sfreq = 4400
        # generate signal
        audio_in = np.sin(2*np.pi*np.arange(441000)*sfreq/44100)
        # Need to use .snd extension so that pw-play (really libsndfile)
        # recognizes the file as raw audio.
        self.loop.run_until_complete(
            self.testvm1.run_for_stdio('cat > audio_in.snd',
            input=audio_in.astype(np.float32).tobytes()))
        local_user = grp.getgrnam('qubes').gr_mem[0]
        if self.testvm1.features['service.pipewire']:
            cmd = 'timeout 20s pw-play --format=f32 --rate=44100 --channels=1 - < audio_in.snd'
        else:
            cmd = ('timeout 20s paplay --format=float32le --rate=44100 --channels=1 '
                   '--raw audio_in.snd')
        with tempfile.NamedTemporaryFile() as recorded_audio:
            os.chmod(recorded_audio.name, 0o666)
            p = subprocess.Popen(['sudo', '-E', '-u', local_user,
                'parecord', '-d', '@DEFAULT_MONITOR@', '--raw',
                '--format=float32le', '--rate=44100', '--channels=1',
                recorded_audio.name], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                self.loop.run_until_complete(self.testvm1.run_for_stdio(cmd))
            except subprocess.CalledProcessError as err:
                self.fail('{} stderr: {}'.format(str(err), err.stderr))
            # wait for possible parecord buffering
            self.loop.run_until_complete(asyncio.sleep(2))
            if p.returncode is not None:
                self.fail("Recording process ended prematurely: exit code {}, stderr: {}".format(
                          p.returncode, p.stderr.read()))
            p.send_signal(signal.SIGINT)
            p.wait()
            self.check_audio_sample(recorded_audio.file.read(), sfreq)

    def _configure_audio_recording(self, vm):
        """Connect VM's output-source to sink monitor instead of mic"""
        local_user = grp.getgrnam("qubes").gr_mem[0]
        sudo = ["sudo", "-E", "-u", local_user]
        source_outputs = json.loads(subprocess.check_output(
            sudo + ["pactl", "-f", "json", "list", "source-outputs"]))

        try:
            output_index = [s["index"] for s in source_outputs
                            if s["properties"].get("application.name")
                            == vm.name][0]
        except IndexError:
            self.fail("source-output for VM {} not found".format(vm.name))
            # self.fail never returns
            assert False

        sources = json.loads(subprocess.check_output(
            sudo + ["pactl", "-f", "json", "list", "sources"]))
        try:
            source_index = [s["index"] for s in sources
                            if s["name"].endswith(".monitor")][0]
        except IndexError:
            self.fail("monitor source not found")
            # self.fail never returns
            assert False

        subprocess.check_call(sudo +
            ["pactl", "move-source-output", str(output_index), str(source_index)])

    def common_audio_record_muted(self):
        # connect VM's recording source output monitor (instead of mic)
        self._configure_audio_recording(self.testvm1)

        # generate some "audio" data
        audio_in = b'\x20' * 4 * 44100
        local_user = grp.getgrnam('qubes').gr_mem[0]
        # Need to use .snd extension so that pw-play (really libsndfile)
        # recognizes the file as raw audio.
        if self.testvm1.features['service.pipewire']:
            cmd = 'pw-record --format=f32 --rate=44100 --channels=1 audio_rec.snd'
            kill_cmd = 'pkill --signal SIGINT pw-record'
        else:
            cmd = 'parecord --raw audio_rec.snd'
            kill_cmd = 'pkill --signal SIGINT parecord'
        record = self.loop.run_until_complete(self.testvm1.run(cmd,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE))
        # give it time to start recording
        self.loop.run_until_complete(asyncio.sleep(0.5))
        p = subprocess.Popen(['sudo', '-E', '-u', local_user,
            'paplay', '--raw'],
            stdin=subprocess.PIPE)
        p.communicate(audio_in)
        # wait for possible parecord buffering
        self.loop.run_until_complete(asyncio.sleep(2))
        if record.returncode is not None:
            self.fail("Recording process ended prematurely: exit code {}, stderr: {}".format(
                      record.returncode, self.loop.run_until_complete(record.stderr.read())))
        try:
            self.loop.run_until_complete(
                self.testvm1.run_for_stdio(kill_cmd))
        except subprocess.CalledProcessError:
            pass
        self.loop.run_until_complete(record.wait())
        recorded_audio, _ = self.loop.run_until_complete(
            self.testvm1.run_for_stdio('cat audio_rec.snd'))
        # should be empty or silence, so check just a little fragment
        if audio_in[:32] in recorded_audio:
            self.fail('VM recorded something, even though mic disabled')

    def common_audio_record_unmuted(self):
        deva = qubes.devices.DeviceAssignment(self.app.domains[0], 'mic')
        self.loop.run_until_complete(
            self.testvm1.devices['mic'].attach(deva))
        # connect VM's recording source output monitor (instead of mic)
        self._configure_audio_recording(self.testvm1)
        sfreq = 4400
        audio_in = np.sin(2*np.pi*np.arange(441000)*sfreq/44100)
        local_user = grp.getgrnam('qubes').gr_mem[0]
        # Need to use .snd extension so that pw-play (really libsndfile)
        # recognizes the file as raw audio.
        if self.testvm1.features['service.pipewire']:
            record_cmd = ('pw-record --format=f32 --rate=44100 --channels=1 '
                          'audio_rec.snd')
            kill_cmd = 'pkill --signal SIGINT pw-record'
        else:
            record_cmd = ('parecord --raw --format=float32le --rate=44100 '
                          '--channels=1 audio_rec.snd')
            kill_cmd = 'pkill --signal SIGINT parecord'
        record = self.loop.run_until_complete(self.testvm1.run(record_cmd))
        # give it time to start recording
        self.loop.run_until_complete(asyncio.sleep(0.5))
        p = subprocess.Popen(['sudo', '-E', '-u', local_user,
            'paplay', '--raw', '--format=float32le',
                    '--rate=44100', '--channels=1'],
            stdin=subprocess.PIPE)
        p.communicate(audio_in.astype(np.float32).tobytes())
        # wait for possible parecord buffering
        self.loop.run_until_complete(asyncio.sleep(2))
        if record.returncode is not None:
            self.fail("Recording process ended prematurely: exit code {}, stderr: {}".format(
                      record.returncode, self.loop.run_until_complete(record.stderr.read())))
        try:
            self.loop.run_until_complete(self.testvm1.run_for_stdio(kill_cmd))
        except subprocess.CalledProcessError:
            pass
        _, record_stderr = self.loop.run_until_complete(record.communicate())
        if record_stderr:
            self.fail('parecord printed something on stderr: {}'.format(
                record_stderr))

        recorded_audio, _ = self.loop.run_until_complete(
            self.testvm1.run_for_stdio('cat audio_rec.snd'))
        self.check_audio_sample(recorded_audio, sfreq)

class TC_20_AudioVM_Pulse(TC_00_AudioMixin):
    @unittest.skipUnless(spawn.find_executable('parecord'),
                         "pulseaudio-utils not installed in dom0")
    def test_220_audio_play_pulseaudio(self):
        self.prepare_audio_test('pulseaudio')
        self.common_audio_playback()

    @unittest.skipUnless(spawn.find_executable('parecord'),
                         "pulseaudio-utils not installed in dom0")
    def test_221_audio_rec_muted_pulseaudio(self):
        self.prepare_audio_test('pulseaudio')
        self.common_audio_record_muted()

    @unittest.skipUnless(spawn.find_executable('parecord'),
                         "pulseaudio-utils not installed in dom0")
    def test_222_audio_rec_unmuted_pulseaudio(self):
        self.prepare_audio_test('pulseaudio')
        self.common_audio_record_unmuted()

    @unittest.skipUnless(spawn.find_executable('parecord'),
                         "pulseaudio-utils not installed in dom0")
    def test_223_audio_play_hvm(self):
        self.testvm1.virt_mode = 'hvm'
        self.testvm1.features['audio-model'] = 'ich6'
        self.prepare_audio_test('pulseaudio')
        try:
            self.loop.run_until_complete(
                self.testvm1.run_for_stdio(
                    'systemctl --user is-active pipewire-pulse.socket || '
                    'pacmd unload-module module-vchan-sink'))
        except subprocess.CalledProcessError:
            self.skipTest('PipeWire modules cannot be unloaded')
        self.common_audio_playback()

    @unittest.skipUnless(spawn.find_executable('parecord'),
                         "pulseaudio-utils not installed in dom0")
    def test_224_audio_rec_muted_hvm(self):
        self.testvm1.virt_mode = 'hvm'
        self.testvm1.features['audio-model'] = 'ich6'
        self.prepare_audio_test('pulseaudio')
        try:
            # if pulseaudio is really emulated by pipewire, nothing needs to be
            # done - pipewire-qubes won't register output before connecting to
            # dom0, and with emulated sound active, it won't connect
            self.loop.run_until_complete(
                self.testvm1.run_for_stdio(
                    'systemctl --user is-active pipewire-pulse.socket || '
                    'pacmd unload-module module-vchan-sink'))
        except subprocess.CalledProcessError:
            self.skipTest('PipeWire modules cannot be unloaded')
        self.common_audio_record_muted()

    @unittest.skipUnless(spawn.find_executable('parecord'),
                         "pulseaudio-utils not installed in dom0")
    def test_225_audio_rec_unmuted_hvm(self):
        self.testvm1.virt_mode = 'hvm'
        self.testvm1.features['audio-model'] = 'ich6'
        self.prepare_audio_test('pulseaudio')
        pa_info = self.loop.run_until_complete(
            self.testvm1.run_for_stdio("pactl info"))[0]
        # Server Name: PulseAudio (on PipeWire 0.3.65)
        if b"on PipeWire 0.3." in pa_info:
            self.skipTest("Known-buggy pipewire runs inside VM")
        try:
            sinks = self.loop.run_until_complete(
                self.testvm1.run_for_stdio("pactl -f json list sinks"))[0]
            sink_index = json.loads(sinks)[0]["index"]
            self.loop.run_until_complete(
                self.testvm1.run_for_stdio(
                    f"pactl set-sink-volume {sink_index!s} 0x10000"))
            self.loop.run_until_complete(
                self.testvm1.run_for_stdio(
                    'systemctl --user is-active pipewire-pulse.socket || '
                    'pacmd unload-module module-vchan-sink'))
        except subprocess.CalledProcessError:
            self.skipTest('PipeWire modules cannot be unloaded')
        self.common_audio_record_unmuted()

    @unittest.skipUnless(spawn.find_executable('parecord'),
                         "pulseaudio-utils not installed in dom0")
    def test_252_audio_playback_audiovm_switch_hvm(self):
        self.create_audio_vm('pulseaudio')
        self.testvm1.audiovm = self.audiovm
        self.testvm1.virt_mode = 'hvm'
        self.testvm1.features['audio-model'] = 'ich6'
        self.testvm1.features['stubdom-qrexec'] = '1'
        self.prepare_audio_test('pulseaudio')
        self.assert_pacat_running(self.audiovm, self.testvm1, True)
        self.assert_pacat_running(self.app.domains[0], self.testvm1, False)
        self.common_audio_playback()
        self.testvm1.audiovm = 'dom0'
        self.assert_pacat_running(self.audiovm, self.testvm1, False)
        self.assert_pacat_running(self.app.domains[0], self.testvm1, True)
        self.common_audio_playback()
        self.testvm1.audiovm = None
        self.assert_pacat_running(self.audiovm, self.testvm1, False)


class TC_20_AudioVM_PipeWire(TC_00_AudioMixin):
    @unittest.skipUnless(spawn.find_executable('parecord'),
                         "pulseaudio-utils not installed in dom0")
    def test_226_audio_playback_pipewire(self):
        self.prepare_audio_test('pipewire')
        self.common_audio_playback()

    @unittest.skipUnless(spawn.find_executable('parecord'),
                         "pulseaudio-utils not installed in dom0")
    def test_227_audio_rec_muted_pipewire(self):
        self.prepare_audio_test('pipewire')
        self.common_audio_record_muted()

    @unittest.skipUnless(spawn.find_executable('parecord'),
                         "pulseaudio-utils not installed in dom0")
    def test_228_audio_rec_unmuted_pipewire(self):
        self.prepare_audio_test('pipewire')
        self.common_audio_record_unmuted()

    @unittest.skipUnless(spawn.find_executable('parecord'),
                         "pulseaudio-utils not installed in dom0")
    def test_250_audio_playback_audiovm_pipewire(self):
        self.create_audio_vm('pipewire')
        self.testvm1.audiovm = self.audiovm
        self.prepare_audio_test('pipewire')
        self.assert_pacat_running(self.audiovm, self.testvm1, True)
        self.assert_pacat_running(self.app.domains[0], self.testvm1, False)
        self.common_audio_playback()
        self.testvm1.audiovm = None
        self.assert_pacat_running(self.audiovm, self.testvm1, False)

    @unittest.skipUnless(spawn.find_executable('parecord'),
                         "pulseaudio-utils not installed in dom0")
    def test_251_audio_playback_audiovm_pipewire_late_start(self):
        self.create_audio_vm('pipewire', start=False)
        self.testvm1.audiovm = self.audiovm
        self.prepare_audio_test('pipewire')
        self.loop.run_until_complete(self.audiovm.start())
        self.assert_pacat_running(self.audiovm, self.testvm1, True)
        self.assert_pacat_running(self.app.domains[0], self.testvm1, False)
        self.common_audio_playback()


class TC_20_NonAudio(TC_00_AppVMMixin):
    def test_000_start_shutdown(self):
        # TODO: wait_for, timeout
        self.loop.run_until_complete(self.testvm1.start())
        self.assertEqual(self.testvm1.get_power_state(), "Running")
        self.loop.run_until_complete(self.wait_for_session(self.testvm1))
        self.loop.run_until_complete(self.testvm1.shutdown(wait=True))
        self.assertEqual(self.testvm1.get_power_state(), "Halted")

    @unittest.skipUnless(spawn.find_executable('xdotool'),
                         "xdotool not installed")
    def test_010_run_xterm(self):
        self.loop.run_until_complete(self.testvm1.start())
        self.assertEqual(self.testvm1.get_power_state(), "Running")

        self.loop.run_until_complete(self.wait_for_session(self.testvm1))
        p = self.loop.run_until_complete(self.testvm1.run('xterm'))
        try:
            title = 'user@{}'.format(self.testvm1.name)
            if self.template.count("whonix"):
                title = 'user@host'
            self.wait_for_window(title)

            self.loop.run_until_complete(asyncio.sleep(0.5))
            subprocess.check_call(
                ['xdotool', 'search', '--name', title,
                'windowactivate', 'type', 'exit\n'])

            self.wait_for_window(title, show=False)
        finally:
            try:
                p.terminate()
                self.loop.run_until_complete(p.wait())
            except ProcessLookupError:  # already dead
                pass

    @unittest.skipUnless(spawn.find_executable('xdotool'),
                         "xdotool not installed")
    def test_011_run_gnome_terminal(self):
        if "minimal" in self.template:
            self.skipTest("Minimal template doesn't have 'gnome-terminal'")
        if 'whonix' in self.template:
            self.skipTest("Whonix template doesn't have 'gnome-terminal'")
        if 'xfce' in self.template:
            self.skipTest("Xfce template doesn't have 'gnome-terminal'")
        self.loop.run_until_complete(self.testvm1.start())
        self.assertEqual(self.testvm1.get_power_state(), "Running")
        self.loop.run_until_complete(self.wait_for_session(self.testvm1))
        p = self.loop.run_until_complete(self.testvm1.run('gnome-terminal'))
        try:
            title = 'user@{}'.format(self.testvm1.name)
            if self.template.count("whonix"):
                title = 'user@host'
            self.wait_for_window(title)

            self.loop.run_until_complete(asyncio.sleep(0.5))
            subprocess.check_call(
                ['xdotool', 'search', '--name', title,
                'windowactivate', '--sync', 'type', 'exit\n'])

            wait_count = 0
            while subprocess.call(['xdotool', 'search', '--name', title],
                                stdout=open(os.path.devnull, 'w'),
                                stderr=subprocess.STDOUT) == 0:
                wait_count += 1
                if wait_count > 100:
                    self.fail("Timeout while waiting for gnome-terminal "
                            "termination")
                self.loop.run_until_complete(asyncio.sleep(0.1))
        finally:
            try:
                p.terminate()
                self.loop.run_until_complete(p.wait())
            except ProcessLookupError:  # already dead
                pass

    @unittest.skipUnless(spawn.find_executable('xdotool'),
                         "xdotool not installed")
    def test_012_qubes_desktop_run(self):
        self.loop.run_until_complete(self.testvm1.start())
        self.assertEqual(self.testvm1.get_power_state(), "Running")
        xterm_desktop_path = "/usr/share/applications/xterm.desktop"
        # Debian has it different...
        xterm_desktop_path_debian = \
            "/usr/share/applications/debian-xterm.desktop"
        try:
            self.loop.run_until_complete(self.testvm1.run_for_stdio(
                'test -r {}'.format(xterm_desktop_path_debian)))
        except subprocess.CalledProcessError:
            pass
        else:
            xterm_desktop_path = xterm_desktop_path_debian
        self.loop.run_until_complete(self.wait_for_session(self.testvm1))
        self.loop.run_until_complete(
            self.testvm1.run('qubes-desktop-run {}'.format(xterm_desktop_path)))
        title = 'user@{}'.format(self.testvm1.name)
        if self.template.count("whonix"):
            title = 'user@host'
        self.wait_for_window(title)

        self.loop.run_until_complete(asyncio.sleep(0.5))
        subprocess.check_call(
            ['xdotool', 'search', '--name', title,
             'windowactivate', '--sync', 'type', 'exit\n'])

        self.wait_for_window(title, show=False)

    def test_100_qrexec_filecopy(self):
        self.loop.run_until_complete(asyncio.gather(
            self.testvm1.start(),
            self.testvm2.start()))

        self.loop.run_until_complete(self.testvm1.run_for_stdio(
            'cp /etc/passwd /tmp/passwd'))
        with self.qrexec_policy('qubes.Filecopy', self.testvm1, self.testvm2):
            try:
                self.loop.run_until_complete(
                    self.testvm1.run_for_stdio(
                        'qvm-copy-to-vm {} /tmp/passwd'.format(
                            self.testvm2.name)))
            except subprocess.CalledProcessError as e:
                self.fail('qvm-copy-to-vm failed: {}'.format(e.stderr))

        try:
            self.loop.run_until_complete(self.testvm2.run_for_stdio(
                'diff /etc/passwd /home/user/QubesIncoming/{}/passwd'.format(
                    self.testvm1.name)))
        except subprocess.CalledProcessError:
            self.fail('file differs')

        try:
            self.loop.run_until_complete(self.testvm1.run_for_stdio(
                'test -f /tmp/passwd'))
        except subprocess.CalledProcessError:
            self.fail('source file got removed')

    def test_105_qrexec_filemove(self):
        self.loop.run_until_complete(asyncio.gather(
            self.testvm1.start(),
            self.testvm2.start()))

        self.loop.run_until_complete(self.testvm1.run_for_stdio(
            'cp /etc/passwd /tmp/passwd'))
        with self.qrexec_policy('qubes.Filecopy', self.testvm1, self.testvm2):
            try:
                self.loop.run_until_complete(
                    self.testvm1.run_for_stdio(
                        'qvm-move-to-vm {} /tmp/passwd'.format(
                            self.testvm2.name)))
            except subprocess.CalledProcessError as e:
                self.fail('qvm-move-to-vm failed: {}'.format(e.stderr))

        try:
            self.loop.run_until_complete(self.testvm2.run_for_stdio(
                'diff /etc/passwd /home/user/QubesIncoming/{}/passwd'.format(
                    self.testvm1.name)))
        except subprocess.CalledProcessError:
            self.fail('file differs')

        with self.assertRaises(subprocess.CalledProcessError):
            self.loop.run_until_complete(self.testvm1.run_for_stdio(
                'test -f /tmp/passwd'))

    def test_101_qrexec_filecopy_with_autostart(self):
        self.loop.run_until_complete(self.testvm1.start())

        with self.qrexec_policy('qubes.Filecopy', self.testvm1, self.testvm2):
            try:
                self.loop.run_until_complete(
                    self.testvm1.run_for_stdio(
                        'qvm-copy-to-vm {} /etc/passwd'.format(
                            self.testvm2.name)))
            except subprocess.CalledProcessError as e:
                self.fail('qvm-copy-to-vm failed: {}'.format(e.stderr))

        # workaround for libvirt bug (domain ID isn't updated when is started
        #  from other application) - details in
        # QubesOS/qubes-core-libvirt@63ede4dfb4485c4161dd6a2cc809e8fb45ca664f
        # XXX is it still true with qubesd? --woju 20170523
        self.testvm2._libvirt_domain = None
        self.assertTrue(self.testvm2.is_running())

        try:
            self.loop.run_until_complete(self.testvm2.run_for_stdio(
                'diff /etc/passwd /home/user/QubesIncoming/{}/passwd'.format(
                    self.testvm1.name)))
        except subprocess.CalledProcessError:
            self.fail('file differs')

        try:
            self.loop.run_until_complete(self.testvm1.run_for_stdio(
                'test -f /etc/passwd'))
        except subprocess.CalledProcessError:
            self.fail('source file got removed')

    def test_110_qrexec_filecopy_deny(self):
        self.loop.run_until_complete(asyncio.gather(
            self.testvm1.start(),
            self.testvm2.start()))

        with self.qrexec_policy('qubes.Filecopy', self.testvm1, self.testvm2,
                allow=False):
            with self.assertRaises(subprocess.CalledProcessError):
                self.loop.run_until_complete(
                    self.testvm1.run_for_stdio(
                        'qvm-copy-to-vm {} /etc/passwd'.format(
                            self.testvm2.name)))

        with self.assertRaises(subprocess.CalledProcessError):
            self.loop.run_until_complete(self.testvm1.run_for_stdio(
                'test -d /home/user/QubesIncoming/{}'.format(
                    self.testvm1.name)))

    def test_115_qrexec_filecopy_no_agent(self):
        # The operation should not hang when qrexec-agent is down on target
        # machine, see QubesOS/qubes-issues#5347.

        self.loop.run_until_complete(asyncio.gather(
            self.testvm1.start(),
            self.testvm2.start()))

        with self.qrexec_policy('qubes.Filecopy', self.testvm1, self.testvm2):
            try:
                self.loop.run_until_complete(
                    self.testvm2.run_for_stdio(
                        'systemctl stop qubes-qrexec-agent.service', user='root'))
            except subprocess.CalledProcessError:
                # A failure is normal here, because we're killing the qrexec
                # process that is handling the command.
                pass

            with self.assertRaises(subprocess.CalledProcessError):
                self.loop.run_until_complete(
                    asyncio.wait_for(
                        self.testvm1.run_for_stdio(
                            'qvm-copy-to-vm {} /etc/passwd'.format(
                                self.testvm2.name)),
                        timeout=30))

    @unittest.skip("Xen gntalloc driver crashes when page is mapped in the "
                   "same domain")
    def test_120_qrexec_filecopy_self(self):
        self.testvm1.start()
        self.qrexec_policy('qubes.Filecopy', self.testvm1.name,
            self.testvm1.name)
        p = self.testvm1.run("qvm-copy-to-vm %s /etc/passwd" %
                             self.testvm1.name, passio_popen=True,
                             passio_stderr=True)
        p.wait()
        self.assertEqual(p.returncode, 0, "qvm-copy-to-vm failed: %s" %
                         p.stderr.read())
        retcode = self.testvm1.run(
            "diff /etc/passwd /home/user/QubesIncoming/{}/passwd".format(
                self.testvm1.name),
            wait=True)
        self.assertEqual(retcode, 0, "file differs")

    @unittest.skipUnless(spawn.find_executable('xdotool'),
                         "xdotool not installed")
    def test_130_qrexec_filemove_disk_full(self):
        self.loop.run_until_complete(asyncio.gather(
            self.testvm1.start(),
            self.testvm2.start()))

        self.loop.run_until_complete(self.wait_for_session(self.testvm1))

        # Prepare test file
        self.loop.run_until_complete(self.testvm1.run_for_stdio(
            'yes teststring | dd of=/tmp/testfile bs=1M count=50 '
            'iflag=fullblock'))

        # Prepare target directory with limited size
        self.loop.run_until_complete(self.testvm2.run_for_stdio(
            'mkdir -p /home/user/QubesIncoming && '
            'chown user /home/user/QubesIncoming && '
            'mount -t tmpfs none /home/user/QubesIncoming -o size=48M',
            user='root'))

        with self.qrexec_policy('qubes.Filecopy', self.testvm1, self.testvm2):
            p = self.loop.run_until_complete(self.testvm1.run(
                'qvm-move-to-vm {} /tmp/testfile'.format(
                    self.testvm2.name)))

            self.loop.run_until_complete(p.wait())
            self.assertNotEqual(p.returncode, 0)

        # the file shouldn't be removed in source vm
        self.loop.run_until_complete(self.testvm1.run_for_stdio(
            'test -f /tmp/testfile'))

    def test_200_timezone(self):
        """Test whether timezone setting is properly propagated to the VM"""
        if "whonix" in self.template:
            self.skipTest("Timezone propagation disabled on Whonix templates")

        self.loop.run_until_complete(self.testvm1.start())
        vm_tz, _ = self.loop.run_until_complete(self.testvm1.run_for_stdio(
            'date +%Z'))
        dom0_tz = subprocess.check_output(['date', '+%Z'])
        self.assertEqual(vm_tz.strip(), dom0_tz.strip())

        # Check if reverting back to UTC works
        vm_tz, _ = self.loop.run_until_complete(self.testvm1.run_for_stdio(
            'TZ=UTC date +%Z'))
        self.assertEqual(vm_tz.strip(), b'UTC')

    def test_210_time_sync(self):
        """Test time synchronization mechanism"""
        if self.template.startswith('whonix-'):
            self.skipTest('qvm-sync-clock disabled for Whonix VMs')
        self.loop.run_until_complete(asyncio.gather(
            self.testvm1.start(),
            self.testvm2.start()))
        start_time = subprocess.check_output(['date', '-u', '+%s'])

        try:
            self.app.clockvm = self.testvm1
            self.app.save()
            # break vm and dom0 time, to check if qvm-sync-clock would fix it
            subprocess.check_call(['sudo', 'date', '-s', '2001-01-01T12:34:56'],
                stdout=subprocess.DEVNULL)
            self.loop.run_until_complete(
                self.testvm2.run_for_stdio('date -s 2001-01-01T12:34:56',
                    user='root'))

            self.loop.run_until_complete(
                self.testvm2.run_for_stdio('qvm-sync-clock',
                    user='root'))

            p = self.loop.run_until_complete(
                asyncio.create_subprocess_exec('sudo', 'qvm-sync-clock',
                    stdout=asyncio.subprocess.DEVNULL))
            self.loop.run_until_complete(p.wait())
            self.assertEqual(p.returncode, 0)
            vm_time, _ = self.loop.run_until_complete(
                self.testvm2.run_for_stdio('date -u +%s'))
            # get current time
            current_time, _ = self.loop.run_until_complete(
                self.testvm1.run_for_stdio('date -u +%s'))
            self.assertAlmostEquals(int(vm_time), int(current_time), delta=30)

            dom0_time = subprocess.check_output(['date', '-u', '+%s'])
            self.assertAlmostEquals(int(dom0_time), int(current_time), delta=30)

        except:
            # reset time to some approximation of the real time
            subprocess.Popen(
                ["sudo", "date", "-u", "-s", "@" + start_time.decode()])
            raise
        finally:
            self.app.clockvm = None

    def test_250_resize_private_img(self):
        """
        Test private.img resize, both offline and online
        :return:
        """
        # First offline test
        self.loop.run_until_complete(
            self.testvm1.storage.resize('private', 4*1024**3))
        self.loop.run_until_complete(self.testvm1.start())
        df_cmd = '( df --output=size /rw || df /rw | awk \'{print $2}\' )|' \
                 'tail -n 1'
        # new_size in 1k-blocks
        new_size, _ = self.loop.run_until_complete(
            self.testvm1.run_for_stdio(df_cmd))
        # some safety margin for FS metadata
        self.assertGreater(int(new_size.strip()), 3.8*1024**2)
        # Then online test
        self.loop.run_until_complete(
            self.testvm1.storage.resize('private', 6*1024**3))
        # new_size in 1k-blocks
        new_size, _ = self.loop.run_until_complete(
            self.testvm1.run_for_stdio(df_cmd))
        # some safety margin for FS metadata
        self.assertGreater(int(new_size.strip()), 5.7*1024**2)

    @unittest.skipUnless(spawn.find_executable('xdotool'),
                         "xdotool not installed")
    def test_300_bug_1028_gui_memory_pinning(self):
        """
        If VM window composition buffers are relocated in memory, GUI will
        still use old pointers and will display old pages
        :return:
        """

        # this test does too much asynchronous operations,
        # so let's rewrite it as a coroutine and call it as such
        return self.loop.run_until_complete(
            self._test_300_bug_1028_gui_memory_pinning())

    async def _test_300_bug_1028_gui_memory_pinning(self):
        self.testvm1.memory = 800
        self.testvm1.maxmem = 800

        # exclude from memory balancing
        self.testvm1.features['service.meminfo-writer'] = False
        await self.testvm1.start()
        await self.wait_for_session(self.testvm1)

        # and allow large map count
        await self.testvm1.run('echo 256000 > /proc/sys/vm/max_map_count',
            user="root")

        allocator_c = '''
#include <sys/mman.h>
#include <stdlib.h>
#include <stdio.h>

int main(int argc, char **argv) {
    int total_pages;
    char *addr, *iter;

    total_pages = atoi(argv[1]);
    addr = mmap(NULL, total_pages * 0x1000, PROT_READ | PROT_WRITE,
        MAP_ANONYMOUS | MAP_PRIVATE | MAP_POPULATE, -1, 0);
    if (addr == MAP_FAILED) {
        perror("mmap");
        exit(1);
    }

    printf("Stage1\\n");
    fflush(stdout);
    getchar();
    for (iter = addr; iter < addr + total_pages*0x1000; iter += 0x2000) {
        if (mlock(iter, 0x1000) == -1) {
            perror("mlock");
            fprintf(stderr, "%d of %d\\n", (iter-addr)/0x1000, total_pages);
            exit(1);
        }
    }

    printf("Stage2\\n");
    fflush(stdout);
    for (iter = addr+0x1000; iter < addr + total_pages*0x1000; iter += 0x2000) {
        if (munmap(iter, 0x1000) == -1) {
            perror(\"munmap\");
            exit(1);
        }
    }

    printf("Stage3\\n");
    fflush(stdout);
    fclose(stdout);
    getchar();

    return 0;
}
'''

        await self.testvm1.run_for_stdio('cat > allocator.c',
            input=allocator_c.encode())

        try:
            await self.testvm1.run_for_stdio(
                'gcc allocator.c -o allocator')
        except subprocess.CalledProcessError as e:
            self.skipTest('allocator compile failed: {}'.format(e.stderr))

        # drop caches to have even more memory pressure
        await self.testvm1.run_for_stdio(
            'echo 3 > /proc/sys/vm/drop_caches', user='root')

        # now fragment all free memory
        stdout, _ = await self.testvm1.run_for_stdio(
            "grep ^MemFree: /proc/meminfo|awk '{print $2}'")
        memory_pages = int(stdout) // 4  # 4k pages

        alloc1 = await self.testvm1.run(
            'ulimit -l unlimited; exec /home/user/allocator {}'.format(
                memory_pages),
            user="root",
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE)

        # wait for memory being allocated; can't use just .read(), because EOF
        # passing is unreliable while the process is still running
        alloc1.stdin.write(b'\n')
        await alloc1.stdin.drain()
        try:
            alloc_out = await alloc1.stdout.readexactly(
                len('Stage1\nStage2\nStage3\n'))
        except asyncio.IncompleteReadError as e:
            alloc_out = e.partial

        if b'Stage3' not in alloc_out:
            # read stderr only in case of failed assert (), but still have nice
            # failure message (don't use self.fail() directly)
            #
            # stderr isn't always read, because on not-failed run, the process
            # is still running, so stderr.read() will wait (indefinitely).
            self.assertIn(b'Stage3', alloc_out,
                (await alloc1.stderr.read()))

        # now, launch some window - it should get fragmented composition buffer
        # it is important to have some changing content there, to generate
        # content update events (aka damage notify)
        proc = await self.testvm1.run(
            'xterm -maximized -e top -d 5')

        if proc.returncode is not None:
            self.fail('xterm failed to start')
        # get window ID
        winid = await self.wait_for_window_coro(
            self.testvm1.name + ':xterm',
            search_class=True)
        xprop = await asyncio.get_event_loop().run_in_executor(None,
            subprocess.check_output,
            ['xprop', '-notype', '-id', winid, '_QUBES_VMWINDOWID'])
        vm_winid = xprop.decode().strip().split(' ')[4]

        # now free the fragmented memory and trigger compaction
        alloc1.stdin.write(b'\n')
        await alloc1.stdin.drain()
        await alloc1.wait()
        await self.testvm1.run_for_stdio(
            'echo 1 > /proc/sys/vm/compact_memory', user='root')

        # now window may be already "broken"; to be sure, allocate (=zero)
        # some memory
        alloc2 = await self.testvm1.run(
            'ulimit -l unlimited; /home/user/allocator {}'.format(memory_pages),
            user='root', stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        await alloc2.stdout.read(len('Stage1\n'))

        # wait for damage notify - top updates every 5 sec
        await asyncio.sleep(6)

        # stop changing the window content
        subprocess.check_call(['xdotool', 'key', '--window', winid, 'd'])

        # now take screenshot of the window, from dom0 and VM
        # choose pnm format, as it doesn't have any useless metadata - easy
        # to compare
        vm_image, _ = await self.testvm1.run_for_stdio(
            'gm import -window {} rgba:-'.format(vm_winid))

        dom0_image = await asyncio.get_event_loop().run_in_executor(None,
            subprocess.check_output, ['gm', 'import', '-window', winid, 'rgba:-'])

        alloc2.terminate()
        await alloc2.wait()
        proc.terminate()
        await proc.wait()

        if vm_image != dom0_image:
            file_basename = f"/tmp/window-dump-{self.id()}-"
            with open(file_basename + "vm", "wb") as f:
                f.write(vm_image)
            with open(file_basename + "dom0", "wb") as f:
                f.write(dom0_image)
            self.fail(f"Dom0 window doesn't match VM window content, saved to {file_basename}*")

class TC_10_Generic(qubes.tests.SystemTestCase):
    def setUp(self):
        super(TC_10_Generic, self).setUp()
        self.init_default_template()
        self.vm = self.app.add_new_vm(
            qubes.vm.appvm.AppVM,
            name=self.make_vm_name('vm'),
            label='red',
            template=self.app.default_template)
        self.loop.run_until_complete(self.vm.create_on_disk())
        self.app.save()
        self.vm = self.app.domains[self.vm.qid]

    def test_000_anyvm_deny_dom0(self):
        '''$anyvm in policy should not match dom0'''
        policy = open("/etc/qubes-rpc/policy/test.AnyvmDeny", "w")
        policy.write("%s $anyvm allow" % (self.vm.name,))
        policy.close()
        self.addCleanup(os.unlink, "/etc/qubes-rpc/policy/test.AnyvmDeny")

        flagfile = '/tmp/test-anyvmdeny-flag'
        if os.path.exists(flagfile):
            os.remove(flagfile)

        self.create_local_file('/etc/qubes-rpc/test.AnyvmDeny',
            'touch {}\necho service output\n'.format(flagfile))

        self.loop.run_until_complete(self.vm.start())
        with self.qrexec_policy('test.AnyvmDeny', self.vm, '$anyvm'):
            with self.assertRaises(subprocess.CalledProcessError,
                    msg='$anyvm matched dom0') as e:
                self.loop.run_until_complete(
                    self.vm.run_for_stdio(
                        '/usr/lib/qubes/qrexec-client-vm dom0 test.AnyvmDeny'))
            stdout = e.exception.output
            stderr = e.exception.stderr
        self.assertFalse(os.path.exists(flagfile),
            'Flag file created (service was run) even though should be denied,'
            ' qrexec-client-vm output: {} {}'.format(stdout, stderr))

def create_testcases_for_templates():
    yield from qubes.tests.create_testcases_for_templates(
        'TC_20_AudioVM_Pulse', TC_20_AudioVM_Pulse,
        qubes.tests.SystemTestCase, module=sys.modules[__name__])
    yield from qubes.tests.create_testcases_for_templates(
        'TC_20_AudioVM_PipeWire', TC_20_AudioVM_PipeWire,
        qubes.tests.SystemTestCase, module=sys.modules[__name__])
    yield from qubes.tests.create_testcases_for_templates(
        'TC_20_NonAudio', TC_20_NonAudio,
        qubes.tests.SystemTestCase, module=sys.modules[__name__])

def load_tests(loader, tests, pattern):
    tests.addTests(loader.loadTestsFromNames(
        create_testcases_for_templates()))
    return tests

qubes.tests.maybe_create_testcases_on_import(create_testcases_for_templates)
