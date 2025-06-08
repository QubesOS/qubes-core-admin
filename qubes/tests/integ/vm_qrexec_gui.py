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
import sys
import unittest

from distutils import spawn

import qubes.config
import qubes.devices
import qubes.tests
import qubes.vm.appvm
import qubes.vm.templatevm

in_qemu = os.path.exists("/sys/firmware/qemu_fw_cfg")


class TC_00_AppVMMixin(object):
    def setUp(self):
        super(TC_00_AppVMMixin, self).setUp()
        self.init_default_template(self.template)
        if self._testMethodName == "test_210_time_sync":
            self.init_networking()
        self.testvm1 = self.app.add_new_vm(
            qubes.vm.appvm.AppVM,
            label="red",
            name=self.make_vm_name("vm1"),
            template=self.app.domains[self.template],
        )
        self.loop.run_until_complete(self.testvm1.create_on_disk())
        self.testvm2 = self.app.add_new_vm(
            qubes.vm.appvm.AppVM,
            label="red",
            name=self.make_vm_name("vm2"),
            template=self.app.domains[self.template],
        )
        self.loop.run_until_complete(self.testvm2.create_on_disk())
        if self.template.startswith("whonix-g"):
            # Whonix Gateway loudly complains if the VM doesn't provide network,
            # which spams the screen with error messages that interfere with
            # other tests
            self.testvm1.provides_network = True
            self.testvm2.provides_network = True
        self.app.save()


class TC_20_NonAudio(TC_00_AppVMMixin):
    def test_000_start_shutdown(self):
        # TODO: wait_for, timeout
        self.loop.run_until_complete(self.testvm1.start())
        self.assertEqual(self.testvm1.get_power_state(), "Running")
        self.loop.run_until_complete(self.wait_for_session(self.testvm1))
        self.loop.run_until_complete(self.testvm1.shutdown(wait=True))
        self.assertEqual(self.testvm1.get_power_state(), "Halted")

    @unittest.skipUnless(
        spawn.find_executable("xdotool"), "xdotool not installed"
    )
    def test_010_run_xterm(self):
        self.loop.run_until_complete(self.testvm1.start())
        self.assertEqual(self.testvm1.get_power_state(), "Running")

        self.loop.run_until_complete(self.wait_for_session(self.testvm1))
        p = self.loop.run_until_complete(self.testvm1.run("xterm"))
        try:
            title = "user@{}".format(self.testvm1.name)
            if self.template.count("whonix"):
                title = "user@host"
            self.wait_for_window(title)

            self.loop.run_until_complete(asyncio.sleep(0.5))
            subprocess.check_call(
                [
                    "xdotool",
                    "search",
                    "--name",
                    title,
                    "windowactivate",
                    "type",
                    "exit\n",
                ]
            )

            self.wait_for_window(title, show=False)
        finally:
            try:
                p.terminate()
                self.loop.run_until_complete(p.wait())
            except ProcessLookupError:  # already dead
                pass

    @unittest.skipUnless(
        spawn.find_executable("xdotool"), "xdotool not installed"
    )
    def test_011_run_gnome_terminal(self):
        if "minimal" in self.template:
            self.skipTest("Minimal template doesn't have 'gnome-terminal'")
        if "whonix" in self.template:
            self.skipTest("Whonix template doesn't have 'gnome-terminal'")
        if "xfce" in self.template:
            self.skipTest("Xfce template doesn't have 'gnome-terminal'")
        if "archlinux" in self.template:
            self.skipTest("Arch template doesn't have 'gnome-terminal'")
        self.loop.run_until_complete(self.testvm1.start())
        self.assertEqual(self.testvm1.get_power_state(), "Running")
        self.loop.run_until_complete(self.wait_for_session(self.testvm1))
        p = self.loop.run_until_complete(
            self.testvm1.run("gnome-terminal || ptyxis")
        )
        try:
            title = "user@{}".format(self.testvm1.name)
            if self.template.count("whonix"):
                title = "user@host"
            self.wait_for_window(title)

            self.loop.run_until_complete(asyncio.sleep(0.5))
            subprocess.check_call(
                [
                    "xdotool",
                    "search",
                    "--name",
                    title,
                    "windowactivate",
                    "--sync",
                    "type",
                    "exit\n",
                ]
            )

            wait_count = 0
            while (
                subprocess.call(
                    ["xdotool", "search", "--name", title],
                    stdout=open(os.path.devnull, "w"),
                    stderr=subprocess.STDOUT,
                )
                == 0
            ):
                wait_count += 1
                if wait_count > 100:
                    self.fail(
                        "Timeout while waiting for gnome-terminal/ptyxis "
                        "termination"
                    )
                self.loop.run_until_complete(asyncio.sleep(0.1))
        finally:
            try:
                p.terminate()
                self.loop.run_until_complete(p.wait())
            except ProcessLookupError:  # already dead
                pass

    @unittest.skipUnless(
        spawn.find_executable("xdotool"), "xdotool not installed"
    )
    def test_012_qubes_desktop_run(self):
        self.loop.run_until_complete(self.testvm1.start())
        self.assertEqual(self.testvm1.get_power_state(), "Running")
        xterm_desktop_path = "/usr/share/applications/xterm.desktop"
        # Debian has it different...
        xterm_desktop_path_debian = (
            "/usr/share/applications/debian-xterm.desktop"
        )
        try:
            self.loop.run_until_complete(
                self.testvm1.run_for_stdio(
                    "test -r {}".format(xterm_desktop_path_debian)
                )
            )
        except subprocess.CalledProcessError:
            pass
        else:
            xterm_desktop_path = xterm_desktop_path_debian
        self.loop.run_until_complete(self.wait_for_session(self.testvm1))
        p = self.loop.run_until_complete(
            self.testvm1.run("qubes-desktop-run {}".format(xterm_desktop_path))
        )
        title = "user@{}".format(self.testvm1.name)
        if self.template.count("whonix"):
            title = "user@host"
        self.wait_for_window(title)

        self.loop.run_until_complete(asyncio.sleep(0.5))
        subprocess.check_call(
            [
                "xdotool",
                "search",
                "--name",
                title,
                "windowactivate",
                "--sync",
                "type",
                "exit\n",
            ]
        )

        self.wait_for_window(title, show=False)
        try:
            self.loop.run_until_complete(asyncio.wait_for(p.wait(), 5))
        except asyncio.TimeoutError:
            p.terminate()
            self.loop.run_until_complete(p.wait())

    def test_100_qrexec_filecopy(self):
        self.loop.run_until_complete(
            asyncio.gather(self.testvm1.start(), self.testvm2.start())
        )

        self.loop.run_until_complete(
            self.testvm1.run_for_stdio("cp /etc/passwd /tmp/passwd")
        )
        with self.qrexec_policy("qubes.Filecopy", self.testvm1, self.testvm2):
            try:
                self.loop.run_until_complete(
                    self.testvm1.run_for_stdio(
                        "qvm-copy-to-vm {} /tmp/passwd".format(
                            self.testvm2.name
                        )
                    )
                )
            except subprocess.CalledProcessError as e:
                self.fail("qvm-copy-to-vm failed: {}".format(e.stderr))

        try:
            self.loop.run_until_complete(
                self.testvm2.run_for_stdio(
                    "diff /etc/passwd /home/user/QubesIncoming/{}/passwd".format(
                        self.testvm1.name
                    )
                )
            )
        except subprocess.CalledProcessError:
            self.fail("file differs")

        try:
            self.loop.run_until_complete(
                self.testvm1.run_for_stdio("test -f /tmp/passwd")
            )
        except subprocess.CalledProcessError:
            self.fail("source file got removed")

    def test_105_qrexec_filemove(self):
        self.loop.run_until_complete(
            asyncio.gather(self.testvm1.start(), self.testvm2.start())
        )

        self.loop.run_until_complete(
            self.testvm1.run_for_stdio("cp /etc/passwd /tmp/passwd")
        )
        with self.qrexec_policy("qubes.Filecopy", self.testvm1, self.testvm2):
            try:
                self.loop.run_until_complete(
                    self.testvm1.run_for_stdio(
                        "qvm-move-to-vm {} /tmp/passwd".format(
                            self.testvm2.name
                        )
                    )
                )
            except subprocess.CalledProcessError as e:
                self.fail("qvm-move-to-vm failed: {}".format(e.stderr))

        try:
            self.loop.run_until_complete(
                self.testvm2.run_for_stdio(
                    "diff /etc/passwd /home/user/QubesIncoming/{}/passwd".format(
                        self.testvm1.name
                    )
                )
            )
        except subprocess.CalledProcessError:
            self.fail("file differs")

        with self.assertRaises(subprocess.CalledProcessError):
            self.loop.run_until_complete(
                self.testvm1.run_for_stdio("test -f /tmp/passwd")
            )

    def test_101_qrexec_filecopy_with_autostart(self):
        self.loop.run_until_complete(self.testvm1.start())

        with self.qrexec_policy("qubes.Filecopy", self.testvm1, self.testvm2):
            try:
                self.loop.run_until_complete(
                    self.testvm1.run_for_stdio(
                        "qvm-copy-to-vm {} /etc/passwd".format(
                            self.testvm2.name
                        )
                    )
                )
            except subprocess.CalledProcessError as e:
                self.fail("qvm-copy-to-vm failed: {}".format(e.stderr))

        # workaround for libvirt bug (domain ID isn't updated when is started
        #  from other application) - details in
        # QubesOS/qubes-core-libvirt@63ede4dfb4485c4161dd6a2cc809e8fb45ca664f
        # XXX is it still true with qubesd? --woju 20170523
        self.testvm2._libvirt_domain = None
        self.assertTrue(self.testvm2.is_running())

        try:
            self.loop.run_until_complete(
                self.testvm2.run_for_stdio(
                    "diff /etc/passwd /home/user/QubesIncoming/{}/passwd".format(
                        self.testvm1.name
                    )
                )
            )
        except subprocess.CalledProcessError:
            self.fail("file differs")

        try:
            self.loop.run_until_complete(
                self.testvm1.run_for_stdio("test -f /etc/passwd")
            )
        except subprocess.CalledProcessError:
            self.fail("source file got removed")

    def test_110_qrexec_filecopy_deny(self):
        self.loop.run_until_complete(
            asyncio.gather(self.testvm1.start(), self.testvm2.start())
        )

        with self.qrexec_policy(
            "qubes.Filecopy", self.testvm1, self.testvm2, allow=False
        ):
            with self.assertRaises(subprocess.CalledProcessError):
                self.loop.run_until_complete(
                    self.testvm1.run_for_stdio(
                        "qvm-copy-to-vm {} /etc/passwd".format(
                            self.testvm2.name
                        )
                    )
                )

        with self.assertRaises(subprocess.CalledProcessError):
            self.loop.run_until_complete(
                self.testvm1.run_for_stdio(
                    "test -d /home/user/QubesIncoming/{}".format(
                        self.testvm1.name
                    )
                )
            )

    def test_115_qrexec_filecopy_no_agent(self):
        # The operation should not hang when qrexec-agent is down on target
        # machine, see QubesOS/qubes-issues#5347.

        self.loop.run_until_complete(
            asyncio.gather(self.testvm1.start(), self.testvm2.start())
        )

        with self.qrexec_policy("qubes.Filecopy", self.testvm1, self.testvm2):
            try:
                self.loop.run_until_complete(
                    self.testvm2.run_for_stdio(
                        "systemctl stop qubes-qrexec-agent.service", user="root"
                    )
                )
            except subprocess.CalledProcessError:
                # A failure is normal here, because we're killing the qrexec
                # process that is handling the command.
                pass

            with self.assertRaises(subprocess.CalledProcessError):
                self.loop.run_until_complete(
                    asyncio.wait_for(
                        self.testvm1.run_for_stdio(
                            "qvm-copy-to-vm {} /etc/passwd".format(
                                self.testvm2.name
                            )
                        ),
                        timeout=30,
                    )
                )

    @unittest.skip(
        "Xen gntalloc driver crashes when page is mapped in the " "same domain"
    )
    def test_120_qrexec_filecopy_self(self):
        self.testvm1.start()
        self.qrexec_policy(
            "qubes.Filecopy", self.testvm1.name, self.testvm1.name
        )
        p = self.testvm1.run(
            "qvm-copy-to-vm %s /etc/passwd" % self.testvm1.name,
            passio_popen=True,
            passio_stderr=True,
        )
        p.wait()
        self.assertEqual(
            p.returncode, 0, "qvm-copy-to-vm failed: %s" % p.stderr.read()
        )
        retcode = self.testvm1.run(
            "diff /etc/passwd /home/user/QubesIncoming/{}/passwd".format(
                self.testvm1.name
            ),
            wait=True,
        )
        self.assertEqual(retcode, 0, "file differs")

    @unittest.skipUnless(
        spawn.find_executable("xdotool"), "xdotool not installed"
    )
    def test_130_qrexec_filemove_disk_full(self):
        self.loop.run_until_complete(
            asyncio.gather(self.testvm1.start(), self.testvm2.start())
        )

        self.loop.run_until_complete(self.wait_for_session(self.testvm1))

        # Prepare test file
        self.loop.run_until_complete(
            self.testvm1.run_for_stdio(
                "yes teststring | dd of=/tmp/testfile bs=1M count=50 "
                "iflag=fullblock"
            )
        )

        # Prepare target directory with limited size
        self.loop.run_until_complete(
            self.testvm2.run_for_stdio(
                "mkdir -p /home/user/QubesIncoming && "
                "chown user /home/user/QubesIncoming && "
                "mount -t tmpfs none /home/user/QubesIncoming -o size=48M",
                user="root",
            )
        )

        with self.qrexec_policy("qubes.Filecopy", self.testvm1, self.testvm2):
            p = self.loop.run_until_complete(
                self.testvm1.run(
                    "qvm-move-to-vm {} /tmp/testfile".format(self.testvm2.name)
                )
            )

            self.loop.run_until_complete(p.wait())
            self.assertNotEqual(p.returncode, 0)

        # the file shouldn't be removed in source vm
        self.loop.run_until_complete(
            self.testvm1.run_for_stdio("test -f /tmp/testfile")
        )

    def test_140_qrexec_filecopy_unsafe_name(self):
        self.loop.run_until_complete(
            asyncio.gather(self.testvm1.start(), self.testvm2.start())
        )

        # emoji are "unsafe"
        name = "test-\U0001f605"
        self.loop.run_until_complete(
            self.testvm1.run_for_stdio(f"cp /etc/passwd /tmp/{name}")
        )
        with self.qrexec_policy(
            "qubes.Filecopy+", self.testvm1, self.testvm2
        ), self.qrexec_policy(
            "qubes.Filecopy+allow-all-names",
            self.testvm1,
            self.testvm2,
            allow=False,
        ):
            with self.assertRaises(subprocess.CalledProcessError):
                self.loop.run_until_complete(
                    self.testvm1.run_for_stdio(
                        f"qvm-copy-to-vm {self.testvm2!s} /tmp/{name}"
                    )
                )

        try:
            self.loop.run_until_complete(
                self.testvm2.run_for_stdio(
                    f"! test -e /home/user/QubesIncoming/{self.testvm1!s}/{name}"
                )
            )
        except subprocess.CalledProcessError:
            self.fail('file with "unsafe" name was copied')

        # try again with changed policy
        with self.qrexec_policy("qubes.Filecopy", self.testvm1, self.testvm2):
            try:
                self.loop.run_until_complete(
                    self.testvm1.run_for_stdio(
                        f"qvm-copy-to-vm {self.testvm2!s} /tmp/{name}"
                    )
                )
            except subprocess.CalledProcessError as e:
                self.fail(f"qvm-copy-to-vm failed: {e.stderr}")

        try:
            self.loop.run_until_complete(
                self.testvm2.run_for_stdio(
                    f"diff /etc/passwd /home/user/QubesIncoming/{self.testvm1!s}/{name}"
                )
            )
        except subprocess.CalledProcessError:
            self.fail("file differs")

        try:
            self.loop.run_until_complete(
                self.testvm1.run_for_stdio(f"test -f /tmp/{name}")
            )
        except subprocess.CalledProcessError:
            self.fail("source file got removed")

    def test_141_qrexec_filecopy_unsafe_symlink(self):
        self.loop.run_until_complete(
            asyncio.gather(self.testvm1.start(), self.testvm2.start())
        )

        # symlinks are not allowed in either mode
        name = "test"
        self.loop.run_until_complete(
            self.testvm1.run_for_stdio(f"ln -s /etc/passwd /tmp/{name}")
        )
        self.loop.run_until_complete(
            self.testvm1.run_for_stdio(f"ln -s ../etc/passwd /tmp/{name}2")
        )
        with self.qrexec_policy("qubes.Filecopy", self.testvm1, self.testvm2):
            with self.assertRaises(subprocess.CalledProcessError):
                self.loop.run_until_complete(
                    self.testvm1.run_for_stdio(
                        f"qvm-copy-to-vm {self.testvm2!s} /tmp/{name}"
                    )
                )
            with self.assertRaises(subprocess.CalledProcessError):
                self.loop.run_until_complete(
                    self.testvm1.run_for_stdio(
                        f"qvm-copy-to-vm {self.testvm2!s} /tmp/{name}2"
                    )
                )

        try:
            self.loop.run_until_complete(
                self.testvm2.run_for_stdio(
                    f"! test -e /home/user/QubesIncoming/{self.testvm1!s}/{name}"
                )
            )
            self.loop.run_until_complete(
                self.testvm2.run_for_stdio(
                    f"! test -e /home/user/QubesIncoming/{self.testvm1!s}/{name}2"
                )
            )
        except subprocess.CalledProcessError:
            self.fail('file with "unsafe" symlink was copied')

    def test_200_timezone(self):
        """Test whether timezone setting is properly propagated to the VM"""
        if "whonix" in self.template:
            self.skipTest("Timezone propagation disabled on Whonix templates")

        self.loop.run_until_complete(self.testvm1.start())
        vm_tz, _ = self.loop.run_until_complete(
            self.testvm1.run_for_stdio("date +%Z")
        )
        dom0_tz = subprocess.check_output(["date", "+%Z"])
        self.assertEqual(vm_tz.strip(), dom0_tz.strip())

        # Check if reverting back to UTC works
        vm_tz, _ = self.loop.run_until_complete(
            self.testvm1.run_for_stdio("TZ=UTC date +%Z")
        )
        self.assertEqual(vm_tz.strip(), b"UTC")

    def test_210_time_sync(self):
        """Test time synchronization mechanism"""
        if self.template.startswith("whonix-"):
            self.skipTest("qvm-sync-clock disabled for Whonix VMs")
        self.loop.run_until_complete(
            asyncio.gather(self.testvm1.start(), self.testvm2.start())
        )
        start_time = subprocess.check_output(["date", "-u", "+%s"])

        try:
            self.app.clockvm = self.testvm1
            self.app.save()
            # break vm and dom0 time, to check if qvm-sync-clock would fix it
            subprocess.check_call(
                ["sudo", "date", "-s", "2001-01-01T12:34:56"],
                stdout=subprocess.DEVNULL,
            )
            self.loop.run_until_complete(
                self.testvm2.run_for_stdio(
                    "date -s 2001-01-01T12:34:56", user="root"
                )
            )

            self.loop.run_until_complete(
                self.testvm2.run_for_stdio("qvm-sync-clock", user="root")
            )

            p = self.loop.run_until_complete(
                asyncio.create_subprocess_exec(
                    "sudo", "qvm-sync-clock", stdout=asyncio.subprocess.DEVNULL
                )
            )
            self.loop.run_until_complete(p.wait())
            self.assertEqual(p.returncode, 0)
            vm_time, _ = self.loop.run_until_complete(
                self.testvm2.run_for_stdio("date -u +%s")
            )
            # get current time
            current_time, _ = self.loop.run_until_complete(
                self.testvm1.run_for_stdio("date -u +%s")
            )
            self.assertAlmostEqual(int(vm_time), int(current_time), delta=30)

            dom0_time = subprocess.check_output(["date", "-u", "+%s"])
            self.assertAlmostEqual(int(dom0_time), int(current_time), delta=30)

        except:
            # reset time to some approximation of the real time
            subprocess.Popen(
                ["sudo", "date", "-u", "-s", "@" + start_time.decode()]
            )
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
            self.testvm1.storage.resize("private", 4 * 1024**3)
        )
        self.loop.run_until_complete(self.testvm1.start())
        df_cmd = (
            "( df --output=size /rw || df /rw | awk '{print $2}' )|" "tail -n 1"
        )
        # new_size in 1k-blocks
        new_size, _ = self.loop.run_until_complete(
            self.testvm1.run_for_stdio(df_cmd)
        )
        # some safety margin for FS metadata
        self.assertGreater(int(new_size.strip()), 3.8 * 1024**2)
        # Then online test
        self.loop.run_until_complete(
            self.testvm1.storage.resize("private", 6 * 1024**3)
        )
        # new_size in 1k-blocks
        new_size, _ = self.loop.run_until_complete(
            self.testvm1.run_for_stdio(df_cmd)
        )
        # some safety margin for FS metadata
        self.assertGreater(int(new_size.strip()), 5.7 * 1024**2)

    @unittest.skipUnless(
        spawn.find_executable("xdotool"), "xdotool not installed"
    )
    def test_300_bug_1028_gui_memory_pinning(self):
        """
        If VM window composition buffers are relocated in memory, GUI will
        still use old pointers and will display old pages
        :return:
        """

        # this test does too much asynchronous operations,
        # so let's rewrite it as a coroutine and call it as such
        return self.loop.run_until_complete(
            self._test_300_bug_1028_gui_memory_pinning()
        )

    async def _test_300_bug_1028_gui_memory_pinning(self):
        self.testvm1.memory = 800
        self.testvm1.maxmem = 800

        # exclude from memory balancing
        self.testvm1.features["service.meminfo-writer"] = False
        # prevent Whonix startup notifications from interfering
        self.testvm1.features["service.whonix-tor-disable"] = True
        await self.testvm1.start()
        # avoid whonix wizard showing up
        if "whonix" in self.template:
            await self.testvm1.run_for_stdio(
                "touch /var/lib/whonix/do_once/whonixsetup.done",
                user="root",
            )
        await self.wait_for_session(self.testvm1)

        # and allow large map count
        await self.testvm1.run(
            "echo 256000 > /proc/sys/vm/max_map_count", user="root"
        )

        allocator_c = """
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
"""

        await self.testvm1.run_for_stdio(
            "cat > allocator.c", input=allocator_c.encode()
        )

        try:
            await self.testvm1.run_for_stdio("gcc allocator.c -o allocator")
        except subprocess.CalledProcessError as e:
            self.skipTest("allocator compile failed: {}".format(e.stderr))

        # drop caches to have even more memory pressure
        await self.testvm1.run_for_stdio(
            "echo 3 > /proc/sys/vm/drop_caches", user="root"
        )

        # now fragment all free memory
        stdout, _ = await self.testvm1.run_for_stdio(
            "grep ^MemFree: /proc/meminfo|awk '{print $2}'"
        )
        memory_pages = int(stdout) // 4  # 4k pages

        alloc1 = await self.testvm1.run(
            "ulimit -l unlimited; exec /home/user/allocator {}".format(
                memory_pages
            ),
            user="root",
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        # wait for memory being allocated; can't use just .read(), because EOF
        # passing is unreliable while the process is still running
        alloc1.stdin.write(b"\n")
        await alloc1.stdin.drain()
        try:
            alloc_out = await alloc1.stdout.readexactly(
                len("Stage1\nStage2\nStage3\n")
            )
        except asyncio.IncompleteReadError as e:
            alloc_out = e.partial

        if b"Stage3" not in alloc_out:
            # read stderr only in case of failed assert (), but still have nice
            # failure message (don't use self.fail() directly)
            #
            # stderr isn't always read, because on not-failed run, the process
            # is still running, so stderr.read() will wait (indefinitely).
            self.assertIn(b"Stage3", alloc_out, (await alloc1.stderr.read()))

        # now, launch some window - it should get fragmented composition buffer
        # it is important to have some changing content there, to generate
        # content update events (aka damage notify)
        proc = await self.testvm1.run("xterm -maximized -e top -d 5")

        if proc.returncode is not None:
            self.fail("xterm failed to start")
        # get window ID
        winid = await self.wait_for_window_coro(
            self.testvm1.name + ":xterm", search_class=True
        )
        xprop = await asyncio.get_event_loop().run_in_executor(
            None,
            subprocess.check_output,
            ["xprop", "-notype", "-id", winid, "_QUBES_VMWINDOWID"],
        )
        vm_winid = xprop.decode().strip().split(" ")[4]

        # now free the fragmented memory and trigger compaction
        alloc1.stdin.write(b"\n")
        await alloc1.stdin.drain()
        await alloc1.wait()
        await self.testvm1.run_for_stdio(
            "echo 1 > /proc/sys/vm/compact_memory", user="root"
        )

        # now window may be already "broken"; to be sure, allocate (=zero)
        # some memory
        alloc2 = await self.testvm1.run(
            "ulimit -l unlimited; /home/user/allocator {}".format(memory_pages),
            user="root",
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
        )
        await alloc2.stdout.read(len("Stage1\n"))

        # wait for damage notify - top updates every 5 sec
        await asyncio.sleep(6)

        # stop changing the window content
        subprocess.check_call(["xdotool", "key", "--window", winid, "d"])

        # now take screenshot of the window, from dom0 and VM
        # choose pnm format, as it doesn't have any useless metadata - easy
        # to compare
        vm_image, _ = await self.testvm1.run_for_stdio(
            "gm import -window {} rgba:-".format(vm_winid)
        )

        dom0_image = await asyncio.get_event_loop().run_in_executor(
            None,
            subprocess.check_output,
            ["gm", "import", "-window", winid, "rgba:-"],
        )

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
            self.fail(
                f"Dom0 window doesn't match VM window content, saved to {file_basename}*"
            )

    @unittest.skipUnless(
        spawn.find_executable("xdotool"), "xdotool not installed"
    )
    def test_400_long_window_title(self):
        self.loop.run_until_complete(self._test_400_long_window_title(False))

    def test_401_long_window_title_utf8(self):
        self.loop.run_until_complete(self._test_400_long_window_title(True))

    async def get_full_title(self, title):
        title_part = title[:32]
        await self.wait_for_window_coro(title_part)
        await asyncio.sleep(0.5)
        title = subprocess.check_output(
            [
                "xdotool",
                "search",
                "--name",
                title_part,
                "getwindowname",
            ]
        )
        return title.decode().strip()

    async def _test_400_long_window_title(self, utf8=False):
        if utf8:
            self.testvm1.features["gui-allow-utf8-titles"] = "1"
        else:
            # don't rely on global default
            self.testvm1.features["gui-allow-utf8-titles"] = ""
        await self.testvm1.start()
        await self.wait_for_session(self.testvm1)
        title = "B" * 120
        p = await self.testvm1.run(f"zenity --title={title} --info")
        try:
            dom0_title = await self.get_full_title(title)
            self.assertEqual(dom0_title, title)
        finally:
            try:
                p.terminate()
                await p.wait()
            except ProcessLookupError:  # already dead
                pass

        title = "A" * 128
        if utf8:
            truncated_title = title[:124] + "\u2026"
        else:
            truncated_title = title[:124] + "..."
        p = await self.testvm1.run(f"zenity --title={title} --info")
        try:
            dom0_title = await self.get_full_title(title)
            self.assertEqual(dom0_title, truncated_title)
        finally:
            try:
                p.terminate()
                await p.wait()
            except ProcessLookupError:  # already dead
                pass


class TC_10_Generic(qubes.tests.SystemTestCase):
    def setUp(self):
        super(TC_10_Generic, self).setUp()
        self.init_default_template()
        self.vm = self.app.add_new_vm(
            qubes.vm.appvm.AppVM,
            name=self.make_vm_name("vm"),
            label="red",
            template=self.app.default_template,
        )
        self.loop.run_until_complete(self.vm.create_on_disk())
        self.app.save()
        self.vm = self.app.domains[self.vm.qid]

    def test_000_anyvm_deny_dom0(self):
        """$anyvm in policy should not match dom0"""
        policy = open("/etc/qubes-rpc/policy/test.AnyvmDeny", "w")
        policy.write("%s $anyvm allow" % (self.vm.name,))
        policy.close()
        self.addCleanup(os.unlink, "/etc/qubes-rpc/policy/test.AnyvmDeny")

        flagfile = "/tmp/test-anyvmdeny-flag"
        if os.path.exists(flagfile):
            os.remove(flagfile)

        self.create_local_file(
            "/etc/qubes-rpc/test.AnyvmDeny",
            "touch {}\necho service output\n".format(flagfile),
        )

        self.loop.run_until_complete(self.vm.start())
        with self.qrexec_policy("test.AnyvmDeny", self.vm, "$anyvm"):
            with self.assertRaises(
                subprocess.CalledProcessError, msg="$anyvm matched dom0"
            ) as e:
                self.loop.run_until_complete(
                    self.vm.run_for_stdio(
                        "/usr/lib/qubes/qrexec-client-vm dom0 test.AnyvmDeny"
                    )
                )
            stdout = e.exception.output
            stderr = e.exception.stderr
        self.assertFalse(
            os.path.exists(flagfile),
            "Flag file created (service was run) even though should be denied,"
            " qrexec-client-vm output: {} {}".format(stdout, stderr),
        )


def create_testcases_for_templates():
    yield from qubes.tests.create_testcases_for_templates(
        "TC_20_NonAudio",
        TC_20_NonAudio,
        qubes.tests.SystemTestCase,
        module=sys.modules[__name__],
    )


def load_tests(loader, tests, pattern):
    tests.addTests(loader.loadTestsFromNames(create_testcases_for_templates()))
    return tests


qubes.tests.maybe_create_testcases_on_import(create_testcases_for_templates)
