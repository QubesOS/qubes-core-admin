#
# The Qubes OS Project, https://www.qubes-os.org/
#
# Copyright (C) 2024 Marek Marczykowski-Górecki
#                           <marmarek@invisiblethingslab.com>
#
# This library is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public
# License as published by the Free Software Foundation; either
# version 2 of the License, or (at your option) any later version.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU General Public
# License along with this library; if not, see <https://www.gnu.org/licenses/>.
import asyncio
import grp
import json
import os
import signal
import subprocess
import sys
import tempfile
import unittest
from distutils import spawn

import numpy as np

import qubes.vm
import qubes.devices
from qubes.tests.integ.vm_qrexec_gui import TC_00_AppVMMixin, in_qemu


@qubes.tests.skipIfTemplate("whonix-g")
class TC_00_AudioMixin(TC_00_AppVMMixin):
    def wait_for_pulseaudio_startup(self, vm):
        self.loop.run_until_complete(self.wait_for_session(self.testvm1))
        try:
            self.loop.run_until_complete(
                vm.run_for_stdio(
                    "timeout 30s sh -c 'while ! pactl info; do sleep 1; done'"
                )
            )
        except subprocess.CalledProcessError as e:
            self.fail(
                "Timeout waiting for pulseaudio start in {}: {}{}".format(
                    vm.name, e.stdout, e.stderr
                )
            )
        # then wait for the stream to appear in dom0
        local_user = grp.getgrnam("qubes").gr_mem[0]
        p = self.loop.run_until_complete(
            asyncio.create_subprocess_shell(
                "sudo -E -u {} timeout 60s sh -c '"
                "while ! pactl list sink-inputs | grep -q :{}; do sleep 1; done'".format(
                    local_user, vm.name
                )
            )
        )
        self.loop.run_until_complete(p.wait())
        # and some more...
        self.loop.run_until_complete(asyncio.sleep(1))

    def prepare_audio_test(self, backend):
        self.loop.run_until_complete(self.testvm1.start())
        pulseaudio_units = "pulseaudio.socket pulseaudio.service"
        pipewire_units = "pipewire.socket wireplumber.service pipewire.service"
        if backend == "pipewire":
            if not self.testvm1.features.check_with_template(
                "supported-service.pipewire", False
            ):
                self.skipTest("PipeWire not supported in VM")
            if "debian-11" in self.template or (
                "whonix" in self.template and "16" in self.template
            ):
                self.skipTest("PipeWire audio not supported in Debian 11")
            self.testvm1.features["service.pipewire"] = True
        elif backend == "pulseaudio":
            # Use PulseAudio if it is installed.  If it is not installed,
            # PipeWire will still run, and its PulseAudio emulation will
            # be tested.
            self.testvm1.features["service.pipewire"] = False
        else:
            self.fail("bad audio backend")
        self.wait_for_pulseaudio_startup(self.testvm1)

    def create_audio_vm(self, backend, start=True):
        self.audiovm = self.app.add_new_vm(
            qubes.vm.appvm.AppVM,
            label="red",
            name=self.make_vm_name("audiovm"),
            template=self.app.domains[self.template],
        )
        self.loop.run_until_complete(self.audiovm.create_on_disk())
        with open("/etc/qubes/policy.d/10-test-audiovm.policy", "w") as f:
            f.write(
                """
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
""".format(
                    vm=self.audiovm.name
                )
            )
        self.addCleanup(os.unlink, "/etc/qubes/policy.d/10-test-audiovm.policy")
        self.audiovm.features["service.audiovm"] = True
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
                self.loop.run_until_complete(
                    audiovm.run_for_stdio(f"kill -0 $(cat {pidfile})")
                )
                running = True
            except subprocess.CalledProcessError:
                running = False
        return running

    def assert_pacat_running(self, audiovm, testvm, expected=True):
        if testvm.features.get("audio-model", None):
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
            self.fail(
                f"pacat for {testvm.name} (xid {xid}) running({running}) "
                f"in {audiovm.name} while expected running({expected})"
            )

    def check_audio_sample(self, sample, sfreq):
        rec = np.fromstring(sample, dtype=np.float32)
        # determine sample size using silence threshold
        threshold = 10**-3
        rec_size = np.count_nonzero((rec > threshold) | (rec < -threshold))
        if not rec_size:
            self.fail("only silence detected, no useful audio data")
        margin = 0.95
        if in_qemu and self.testvm1.features.get("audio-model"):
            # be less strict on HVM tests in nested virt, the test environment
            # has huge overhead already
            margin = 0.80
        if rec_size < margin * 441000:
            fname = f"/tmp/audio-sample-{self.id()}.raw"
            with open(fname, "wb") as f:
                f.write(sample)
            self.fail(
                f"too short audio, expected 10s, got {rec_size / 44100}, saved to {fname}"
            )
        # find zero crossings
        crossings = np.nonzero((rec[1:] > threshold) & (rec[:-1] < -threshold))[
            0
        ]
        np.seterr("raise")
        # compare against sine wave frequency
        rec_freq = 44100 / np.mean(np.diff(crossings))
        if not sfreq * 0.8 < rec_freq < sfreq * 1.2:
            fname = f"/tmp/audio-sample-{self.id()}.raw"
            with open(fname, "wb") as f:
                f.write(sample)
            self.fail(
                "frequency {} not in specified range, saved to {}".format(
                    rec_freq, fname
                )
            )

    def common_audio_playback(self):
        # sine frequency
        sfreq = 4400
        # generate signal
        audio_in = np.sin(2 * np.pi * np.arange(441000) * sfreq / 44100)
        # Need to use .snd extension so that pw-play (really libsndfile)
        # recognizes the file as raw audio.
        self.loop.run_until_complete(
            self.testvm1.run_for_stdio(
                "cat > audio_in.snd",
                input=audio_in.astype(np.float32).tobytes(),
            )
        )
        local_user = grp.getgrnam("qubes").gr_mem[0]
        if self.testvm1.features["service.pipewire"]:
            cmd = "timeout 20s pw-play --format=f32 --rate=44100 --channels=1 - < audio_in.snd"
        else:
            cmd = (
                "timeout 20s paplay --format=float32le --rate=44100 --channels=1 "
                "--raw audio_in.snd"
            )
        with tempfile.NamedTemporaryFile() as recorded_audio:
            os.chmod(recorded_audio.name, 0o666)
            p = subprocess.Popen(
                [
                    "sudo",
                    "-E",
                    "-u",
                    local_user,
                    "parecord",
                    "-d",
                    "@DEFAULT_MONITOR@",
                    "--raw",
                    "--format=float32le",
                    "--rate=44100",
                    "--channels=1",
                    recorded_audio.name,
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            try:
                self.loop.run_until_complete(self.testvm1.run_for_stdio(cmd))
            except subprocess.CalledProcessError as err:
                self.fail("{} stderr: {}".format(str(err), err.stderr))
            # wait for possible parecord buffering
            self.loop.run_until_complete(asyncio.sleep(2))
            if p.returncode is not None:
                self.fail(
                    "Recording process ended prematurely: exit code {}, stderr: {}".format(
                        p.returncode, p.stderr.read()
                    )
                )
            p.send_signal(signal.SIGINT)
            p.wait()
            self.check_audio_sample(recorded_audio.file.read(), sfreq)

    def _call_in_audiovm(self, audiovm, command):
        local_user = grp.getgrnam("qubes").gr_mem[0]
        sudo = ["sudo", "-E", "-u", local_user]
        if audiovm.name != "dom0":
            stdout, _ = self.loop.run_until_complete(
                audiovm.run_for_stdio(" ".join(command))
            )
            return stdout
        else:
            return subprocess.check_output(sudo + command)

    def _find_pactl_entry_for_vm(self, pactl_data, vm_name):
        try:
            return [
                s
                for s in pactl_data
                if s["properties"].get("application.name") == vm_name
            ][0]
        except IndexError:
            self.fail("source-output for VM {} not found".format(vm.name))
            # self.fail never returns
            assert False

    def _configure_audio_recording(self, vm):
        """Connect VM's source-output to sink monitor instead of mic"""
        audiovm = vm.audiovm

        source_outputs = json.loads(
            self._call_in_audiovm(
                audiovm, ["pactl", "-f", "json", "list", "source-outputs"]
            )
        )

        if not source_outputs:
            self.fail("no source-output found in {}".format(audiovm.name))
            assert False

        output_info = self._find_pactl_entry_for_vm(source_outputs, vm.name)
        output_index = output_info["index"]
        current_source = output_info["source"]

        sources = json.loads(
            self._call_in_audiovm(
                audiovm, ["pactl", "-f", "json", "list", "sources"]
            )
        )

        if not sources:
            self.fail("no sources found in {}".format(audiovm.name))
            assert False

        try:
            source_index = [
                s["index"] for s in sources if s["name"].endswith(".monitor")
            ][0]
        except IndexError:
            self.fail("monitor source not found")
            # self.fail never returns
            assert False

        attempts_left = 5
        # pactl seems to fail sometimes, still with exit code 0...
        while current_source != source_index and attempts_left:
            assert isinstance(output_index, int)
            assert isinstance(source_index, int)
            cmd = [
                "pactl",
                "move-source-output",
                str(output_index),
                str(source_index),
            ]
            self._call_in_audiovm(audiovm, cmd)

            source_outputs = json.loads(
                self._call_in_audiovm(
                    audiovm, ["pactl", "-f", "json", "list", "source-outputs"]
                )
            )

            output_info = self._find_pactl_entry_for_vm(source_outputs, vm.name)
            output_index = output_info["index"]
            current_source = output_info["source"]
            attempts_left -= 1

        self.assertGreater(attempts_left, 0, "Failed to move-source-output")

    async def retrieve_audio_input(self, vm, status):
        try:
            await asyncio.wait_for(
                self._check_audio_input_status(vm, status), timeout=2
            )
        except asyncio.TimeoutError:
            self.fail("Failed to get mic attach/detach status!")

    @staticmethod
    async def _check_audio_input_status(vm, status):
        while (
            vm.audiovm.untrusted_qdb.read("/audio-input/{}".format(vm.name))
            != status
        ):
            await asyncio.sleep(0.5)

    def attach_mic(self):
        deva = qubes.device_protocol.DeviceAssignment(
            qubes.device_protocol.VirtualDevice(
                qubes.device_protocol.Port(self.app.domains[0], "mic", "mic")
            )
        )
        self.loop.run_until_complete(self.testvm1.devices["mic"].attach(deva))
        self.loop.run_until_complete(
            self.retrieve_audio_input(self.testvm1, b"1")
        )

    def detach_mic(self):
        deva = qubes.device_protocol.DeviceAssignment(
            qubes.device_protocol.VirtualDevice(
                qubes.device_protocol.Port(self.app.domains[0], "mic", "mic")
            )
        )
        self.loop.run_until_complete(self.testvm1.devices["mic"].detach(deva))
        self.loop.run_until_complete(
            self.retrieve_audio_input(self.testvm1, b"0")
        )

    def common_audio_record_muted(self):
        # connect VM's recording source output monitor (instead of mic)
        self._configure_audio_recording(self.testvm1)

        # generate some "audio" data
        audio_in = b"\x20" * 4 * 44100
        local_user = grp.getgrnam("qubes").gr_mem[0]
        sudo = ["sudo", "-E", "-u", local_user]
        # Need to use .snd extension so that pw-play (really libsndfile)
        # recognizes the file as raw audio.
        if self.testvm1.features["service.pipewire"]:
            cmd = (
                "pw-record --format=f32 --rate=44100 --channels=1 audio_rec.snd"
            )
            kill_cmd = "pkill --signal SIGINT pw-record"
        else:
            cmd = "parecord --raw audio_rec.snd"
            kill_cmd = "pkill --signal SIGINT parecord"
        record = self.loop.run_until_complete(
            self.testvm1.run(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
        )
        # give it time to start recording
        self.loop.run_until_complete(asyncio.sleep(0.5))

        play_cmd = ["paplay", "--raw"]
        if self.testvm1.audiovm.name != "dom0":
            self.loop.run_until_complete(
                self.testvm1.audiovm.run_for_stdio(
                    " ".join(play_cmd), input=audio_in
                )
            )
        else:
            p = subprocess.Popen(sudo + play_cmd, stdin=subprocess.PIPE)
            p.communicate(audio_in)

        # wait for possible parecord buffering
        self.loop.run_until_complete(asyncio.sleep(2))
        if record.returncode is not None:
            self.fail(
                "Recording process ended prematurely: exit code {}, stderr: {}".format(
                    record.returncode,
                    self.loop.run_until_complete(record.stderr.read()),
                )
            )
        try:
            self.loop.run_until_complete(self.testvm1.run_for_stdio(kill_cmd))
        except subprocess.CalledProcessError:
            pass
        self.loop.run_until_complete(record.wait())
        recorded_audio, _ = self.loop.run_until_complete(
            self.testvm1.run_for_stdio("cat audio_rec.snd")
        )
        # should be empty or silence, so check just a little fragment
        if audio_in[:32] in recorded_audio:
            self.fail("VM recorded something, even though mic disabled")

    def common_audio_record_unmuted(self, attach_mic=True, detach_mic=True):
        if attach_mic:
            try:
                self.detach_mic()
            except qubes.devices.DeviceNotAssigned:
                pass
            self.attach_mic()
        # connect VM's recording source output monitor (instead of mic)
        self._configure_audio_recording(self.testvm1)
        sfreq = 4400
        audio_in = np.sin(2 * np.pi * np.arange(441000) * sfreq / 44100)
        local_user = grp.getgrnam("qubes").gr_mem[0]
        sudo = ["sudo", "-E", "-u", local_user]

        # Need to use .snd extension so that pw-play (really libsndfile)
        # recognizes the file as raw audio.
        if self.testvm1.features["service.pipewire"]:
            record_cmd = (
                "pw-record --format=f32 --rate=44100 --channels=1 "
                "audio_rec.snd"
            )
            kill_cmd = "pkill --signal SIGINT pw-record"
        else:
            record_cmd = (
                "parecord --raw --format=float32le --rate=44100 "
                "--channels=1 audio_rec.snd"
            )
            kill_cmd = "pkill --signal SIGINT parecord"
        record = self.loop.run_until_complete(self.testvm1.run(record_cmd))
        # give it time to start recording
        self.loop.run_until_complete(asyncio.sleep(0.5))

        # play sound that will be used as source-output
        play_cmd = [
            "paplay",
            "--raw",
            "--format=float32le",
            "--rate=44100",
            "--channels=1",
        ]
        if self.testvm1.audiovm.name != "dom0":
            self.loop.run_until_complete(
                self.testvm1.audiovm.run_for_stdio(
                    " ".join(play_cmd),
                    input=audio_in.astype(np.float32).tobytes(),
                )
            )
        else:
            p = subprocess.Popen(sudo + play_cmd, stdin=subprocess.PIPE)
            p.communicate(audio_in.astype(np.float32).tobytes())

        # wait for possible parecord buffering
        self.loop.run_until_complete(asyncio.sleep(2))
        if record.returncode is not None:
            self.fail(
                "Recording process ended prematurely: exit code {}, stderr: {}".format(
                    record.returncode,
                    self.loop.run_until_complete(record.stderr.read()),
                )
            )
        try:
            self.loop.run_until_complete(self.testvm1.run_for_stdio(kill_cmd))
        except subprocess.CalledProcessError:
            pass
        _, record_stderr = self.loop.run_until_complete(record.communicate())
        if record_stderr:
            self.fail(
                "parecord printed something on stderr: {}".format(record_stderr)
            )

        recorded_audio, _ = self.loop.run_until_complete(
            self.testvm1.run_for_stdio("cat audio_rec.snd")
        )
        self.check_audio_sample(recorded_audio, sfreq)
        if detach_mic:
            self.detach_mic()


class TC_20_AudioVM_Pulse(TC_00_AudioMixin):
    @unittest.skipUnless(
        spawn.find_executable("parecord"),
        "pulseaudio-utils not installed in dom0",
    )
    def test_220_audio_play_pulseaudio(self):
        self.prepare_audio_test("pulseaudio")
        self.common_audio_playback()

    @unittest.skipUnless(
        spawn.find_executable("parecord"),
        "pulseaudio-utils not installed in dom0",
    )
    def test_221_audio_rec_muted_pulseaudio(self):
        self.prepare_audio_test("pulseaudio")
        self.common_audio_record_muted()

    @unittest.skipUnless(
        spawn.find_executable("parecord"),
        "pulseaudio-utils not installed in dom0",
    )
    def test_222_audio_rec_unmuted_pulseaudio(self):
        self.prepare_audio_test("pulseaudio")
        self.common_audio_record_unmuted()

    @unittest.skipUnless(
        spawn.find_executable("parecord"),
        "pulseaudio-utils not installed in dom0",
    )
    def test_223_audio_play_hvm(self):
        self.testvm1.virt_mode = "hvm"
        self.testvm1.features["audio-model"] = "ich6"
        self.prepare_audio_test("pulseaudio")
        try:
            self.loop.run_until_complete(
                self.testvm1.run_for_stdio(
                    "systemctl --user is-active pipewire-pulse.socket || "
                    "pacmd unload-module module-vchan-sink"
                )
            )
        except subprocess.CalledProcessError:
            self.skipTest("PipeWire modules cannot be unloaded")
        self.common_audio_playback()

    @unittest.skipUnless(
        spawn.find_executable("parecord"),
        "pulseaudio-utils not installed in dom0",
    )
    def test_224_audio_rec_muted_hvm(self):
        self.testvm1.virt_mode = "hvm"
        self.testvm1.features["audio-model"] = "ich6"
        self.prepare_audio_test("pulseaudio")
        try:
            # if pulseaudio is really emulated by pipewire, nothing needs to be
            # done - pipewire-qubes won't register output before connecting to
            # dom0, and with emulated sound active, it won't connect
            self.loop.run_until_complete(
                self.testvm1.run_for_stdio(
                    "systemctl --user is-active pipewire-pulse.socket || "
                    "pacmd unload-module module-vchan-sink"
                )
            )
        except subprocess.CalledProcessError:
            self.skipTest("PipeWire modules cannot be unloaded")
        self.common_audio_record_muted()

    @unittest.skipUnless(
        spawn.find_executable("parecord"),
        "pulseaudio-utils not installed in dom0",
    )
    def test_225_audio_rec_unmuted_hvm(self):
        self.testvm1.virt_mode = "hvm"
        self.testvm1.features["audio-model"] = "ich6"
        self.prepare_audio_test("pulseaudio")
        pa_info = self.loop.run_until_complete(
            self.testvm1.run_for_stdio("pactl info")
        )[0]
        # Server Name: PulseAudio (on PipeWire 0.3.65)
        if b"on PipeWire 0.3." in pa_info:
            self.skipTest("Known-buggy pipewire runs inside VM")
        try:
            sinks = self.loop.run_until_complete(
                self.testvm1.run_for_stdio("pactl -f json list sinks")
            )[0]
            sink_index = json.loads(sinks)[0]["index"]
            self.loop.run_until_complete(
                self.testvm1.run_for_stdio(
                    f"pactl set-sink-volume {sink_index!s} 0x10000"
                )
            )
            self.loop.run_until_complete(
                self.testvm1.run_for_stdio(
                    "systemctl --user is-active pipewire-pulse.socket || "
                    "pacmd unload-module module-vchan-sink"
                )
            )
        except subprocess.CalledProcessError:
            self.skipTest("PipeWire modules cannot be unloaded")
        self.common_audio_record_unmuted()

    @unittest.skipUnless(
        spawn.find_executable("parecord"),
        "pulseaudio-utils not installed in dom0",
    )
    def test_252_audio_playback_audiovm_switch_hvm(self):
        self.create_audio_vm("pulseaudio")
        self.testvm1.audiovm = self.audiovm
        self.testvm1.virt_mode = "hvm"
        self.testvm1.features["audio-model"] = "ich6"
        self.testvm1.features["stubdom-qrexec"] = "1"
        self.prepare_audio_test("pulseaudio")
        self.assert_pacat_running(self.audiovm, self.testvm1, True)
        self.assert_pacat_running(self.app.domains[0], self.testvm1, False)
        self.common_audio_playback()
        self.testvm1.audiovm = "dom0"
        self.assert_pacat_running(self.audiovm, self.testvm1, False)
        self.assert_pacat_running(self.app.domains[0], self.testvm1, True)
        self.common_audio_playback()
        self.testvm1.audiovm = None
        self.assert_pacat_running(self.audiovm, self.testvm1, False)


class TC_20_AudioVM_PipeWire(TC_00_AudioMixin):
    @unittest.skipUnless(
        spawn.find_executable("parecord"),
        "pulseaudio-utils not installed in dom0",
    )
    def test_226_audio_playback_pipewire(self):
        self.prepare_audio_test("pipewire")
        self.common_audio_playback()

    @unittest.skipUnless(
        spawn.find_executable("parecord"),
        "pulseaudio-utils not installed in dom0",
    )
    def test_227_audio_rec_muted_pipewire(self):
        self.prepare_audio_test("pipewire")
        self.common_audio_record_muted()

    @unittest.skipUnless(
        spawn.find_executable("parecord"),
        "pulseaudio-utils not installed in dom0",
    )
    def test_228_audio_rec_unmuted_pipewire(self):
        self.prepare_audio_test("pipewire")
        self.common_audio_record_unmuted()

    @unittest.skipUnless(
        spawn.find_executable("parecord"),
        "pulseaudio-utils not installed in dom0",
    )
    def test_250_audio_playback_audiovm_pipewire(self):
        self.create_audio_vm("pipewire")
        self.testvm1.audiovm = self.audiovm
        self.prepare_audio_test("pipewire")
        self.assert_pacat_running(self.audiovm, self.testvm1, True)
        self.assert_pacat_running(self.app.domains[0], self.testvm1, False)
        self.common_audio_playback()
        self.testvm1.audiovm = None
        self.assert_pacat_running(self.audiovm, self.testvm1, False)

    @unittest.skipUnless(
        spawn.find_executable("parecord"),
        "pulseaudio-utils not installed in dom0",
    )
    def test_251_audio_playback_audiovm_pipewire_late_start(self):
        self.create_audio_vm("pipewire", start=False)
        self.testvm1.audiovm = self.audiovm
        self.prepare_audio_test("pipewire")
        self.loop.run_until_complete(self.audiovm.start())
        self.assert_pacat_running(self.audiovm, self.testvm1, True)
        self.assert_pacat_running(self.app.domains[0], self.testvm1, False)
        self.common_audio_playback()

    @unittest.skipUnless(
        spawn.find_executable("parecord"),
        "pulseaudio-utils not installed in dom0",
    )
    def test_260_audio_mic_enabled_switch_audiovm(self):
        self.create_audio_vm("pipewire", start=False)
        self.testvm1.audiovm = self.audiovm
        self.prepare_audio_test("pipewire")
        self.loop.run_until_complete(self.audiovm.start())

        # check mic is enabled in first audiovm
        self.assert_pacat_running(self.audiovm, self.testvm1, True)
        self.common_audio_record_unmuted(detach_mic=False)

        # check mic is enabled in second audiovm, admin ext will
        # allow mic during switch as it was previously enabled
        self.testvm1.audiovm = self.app.domains[0]
        self.assert_pacat_running(self.testvm1.audiovm, self.testvm1, True)
        self.common_audio_record_unmuted(attach_mic=False, detach_mic=False)

        # detach mic, switch to original audiovm and check there
        # is no sound as we disabled mic
        self.detach_mic()
        self.testvm1.audiovm = self.audiovm
        self.assert_pacat_running(self.audiovm, self.testvm1, True)
        self.common_audio_record_muted()


def create_testcases_for_templates():
    yield from qubes.tests.create_testcases_for_templates(
        "TC_20_AudioVM_Pulse",
        TC_20_AudioVM_Pulse,
        qubes.tests.SystemTestCase,
        module=sys.modules[__name__],
    )
    yield from qubes.tests.create_testcases_for_templates(
        "TC_20_AudioVM_PipeWire",
        TC_20_AudioVM_PipeWire,
        qubes.tests.SystemTestCase,
        module=sys.modules[__name__],
    )


def load_tests(loader, tests, pattern):
    tests.addTests(loader.loadTestsFromNames(create_testcases_for_templates()))
    return tests


qubes.tests.maybe_create_testcases_on_import(create_testcases_for_templates)
