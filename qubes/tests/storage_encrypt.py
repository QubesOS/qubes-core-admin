#
# The Qubes OS Project, https://www.qubes-os.org/
#
# Copyright (C) 2026 rishi-jat <rishijat098@gmail.com>
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
"""Tests for LUKS2 volume encryption"""

import os
import shutil
import subprocess
import tempfile
import unittest.mock

import qubes.exc
import qubes.storage
import qubes.storage.file
import qubes.storage.lvm
import qubes.storage.reflink
import qubes.storage.zfs
import qubes.tests
import qubes.tests.storage
from qubes.storage import LUKS2_HEADER_SIZE, StoragePoolException

SIZE = 64 << 20
LUKS_MAGIC = b"LUKS\xba\xbe"


class TestApp:
    def __init__(self):
        self.save = unittest.mock.Mock()
        self.domains = []


class TestVM(qubes.tests.storage.TestVM):
    klass = "AppVM"
    template_for_dispvms = False

    def __init__(self, test):
        super().__init__(test)
        self.volumes = {}
        self.fire_event_async = unittest.mock.AsyncMock()

    def is_running(self):
        return False


class EncryptTestCase(qubes.tests.QubesTestCase):
    def setUp(self):
        super().setUp()
        self.app = TestApp()
        self.tmpdir = tempfile.mkdtemp()
        self.pool = qubes.storage.file.FilePool(
            name="test-pool", dir_path=self.tmpdir
        )
        self.pool.setup()
        self.vm = TestVM(self)
        self.storage = qubes.storage.Storage(self.vm)
        # is_empty() needs SEEK_DATA support of the filesystem of tmpdir
        with open(os.path.join(self.tmpdir, "sparse"), "w+b") as sparse:
            sparse.truncate(1 << 20)
            try:
                os.lseek(sparse.fileno(), 0, os.SEEK_DATA)
                self.seek_data = False
            except OSError:
                self.seek_data = True
        self.cryptsetup = unittest.mock.patch(
            "qubes.utils.cryptsetup", new_callable=unittest.mock.AsyncMock
        ).start()
        self.cryptsetup.side_effect = self.cryptsetup_side_effect
        #: passphrases passed to cryptsetup, as they were at call time
        self.passphrases = []
        self.failing = None
        self.addCleanup(unittest.mock.patch.stopall)

    def tearDown(self):
        shutil.rmtree(self.tmpdir)
        super().tearDown()

    def make_volume(self, name="private", **config):
        volume_config = {
            "name": name,
            "rw": True,
            "save_on_stop": True,
            "size": SIZE,
        }
        volume_config.update(config)
        volume = self.pool.init_volume(self.vm, volume_config)
        os.makedirs(os.path.dirname(volume.path), exist_ok=True)
        self.loop.run_until_complete(qubes.utils.coro_maybe(volume.create()))
        self.vm.volumes[name] = volume
        return volume

    def mapping(self, volume):
        return volume.encrypted_volume_path(self.vm.name, volume.name)

    def import_mapping(self, volume):
        return qubes.storage.Volume.encrypted_volume_path(
            volume, self.vm.name, volume.name + "-import"
        )

    @staticmethod
    def mapping_exists(name):
        """Make a LUKS mapping look open"""
        exists = os.path.exists
        return unittest.mock.patch(
            "os.path.exists", lambda path: path == name or exists(path)
        )

    def cryptsetup_calls(self, action):
        return [
            call.args
            for call in self.cryptsetup.call_args_list
            if action in call.args
        ]

    def cryptsetup_side_effect(self, *args, **kwargs):
        if "passphrase" in kwargs:
            self.passphrases.append(bytes(kwargs["passphrase"]))
        if self.failing and self.failing[0] in args:
            raise subprocess.CalledProcessError(self.failing[1], "cryptsetup")

    def fail_cryptsetup(self, action, returncode=1):
        """Make cryptsetup mock fail for the given action"""
        self.failing = (action, returncode)

    @staticmethod
    def write_luks_magic(volume):
        with open(volume.path, "r+b") as image:
            image.write(LUKS_MAGIC)

    @staticmethod
    def fake_resize(volume):
        """resize() of FileVolume needs losetup, replace it"""

        def resize(size):
            with open(volume.path, "r+b") as image:
                image.truncate(size)

        volume.resize = unittest.mock.Mock(side_effect=resize)
        return volume.resize


class TC_00_Encrypted(EncryptTestCase):
    """Volume.encrypted and the passphrase"""

    def test_000_default(self):
        volume = self.make_volume()
        self.assertFalse(volume.encrypted)
        self.assertNotIn("encrypted", volume.config)
        self.assertEqual(volume.data_size, SIZE)

    def test_001_enable(self):
        volume = self.make_volume()
        volume.encrypted = True
        self.assertTrue(volume.encrypted)
        self.assertTrue(volume.config["encrypted"])
        self.assertEqual(volume.__xml__().get("encrypted"), "True")
        self.assertEqual(volume.data_size, SIZE - LUKS2_HEADER_SIZE)

    def test_002_init(self):
        volume = self.make_volume(encrypted=True)
        self.assertTrue(volume.encrypted)

    def test_003_not_encryptable(self):
        volatile = self.make_volume("volatile", save_on_stop=False)
        readonly = self.make_volume("readonly", rw=False)
        for volume in (volatile, readonly):
            self.assertFalse(volume.is_encryptable())
            with self.assertRaises(qubes.exc.QubesValueError):
                volume.encrypted = True
            self.assertFalse(volume.encrypted)

    def test_004_snapshot(self):
        template = qubes.tests.storage.TestTemplateVM(self)
        source = self.pool.init_volume(
            template,
            {"name": "root", "rw": True, "save_on_stop": True, "size": SIZE},
        )
        snapshot_config = {
            "name": "root",
            "rw": True,
            "snap_on_start": True,
            "source": source,
            "size": SIZE,
        }
        snapshot = self.pool.init_volume(self.vm, snapshot_config)
        with self.assertRaises(qubes.exc.QubesValueError):
            snapshot.encrypted = True
        # a snapshot of an encrypted volume loads (qubes.xml may say so), but
        # does not start
        source.encrypted = True
        snapshot = self.pool.init_volume(self.vm, snapshot_config)
        snapshot.start = unittest.mock.AsyncMock()
        self.vm.volumes["root"] = snapshot
        with self.assertRaises(qubes.exc.QubesVMError):
            self.loop.run_until_complete(qubes.storage.Storage(self.vm).start())
        snapshot.start.assert_not_called()

    def test_005_ephemeral(self):
        volatile = self.make_volume("volatile", save_on_stop=False)
        volatile.ephemeral = True
        with self.assertRaises(qubes.exc.QubesValueError):
            volatile.encrypted = True
        private = self.make_volume(encrypted=True)
        with self.assertRaises(qubes.exc.QubesValueError):
            private.ephemeral = True

    def test_006_disable(self):
        volume = self.make_volume(encrypted=True)
        # possible until there is a LUKS header
        volume.encrypted = False
        self.assertFalse(volume.encrypted)
        volume.encrypted = True
        self.write_luks_magic(volume)
        with self.assertRaises(qubes.exc.QubesValueError):
            volume.encrypted = False
        self.assertTrue(volume.encrypted)
        volume = self.make_volume("root")
        volume.encrypted = False
        self.assertFalse(volume.encrypted)

    def test_007_passphrase(self):
        volume = self.make_volume(encrypted=True)
        self.assertFalse(volume.has_passphrase())
        volume.set_passphrase(b"s3cret")
        self.assertTrue(volume.has_passphrase())
        self.assertNotIn(b"s3cret", repr(volume.config).encode())
        self.assertNotIn(b"s3cret", repr(volume.__xml__().items()).encode())
        buffer = volume._passphrase  # pylint: disable=protected-access
        volume.clear_passphrase()
        self.assertFalse(volume.has_passphrase())
        self.assertEqual(buffer, bytearray(len(b"s3cret")))

    def test_008_passphrase_invalid(self):
        volume = self.make_volume(encrypted=True)
        for passphrase in (b"", b"a\nb", b"x" * 513):
            with self.assertRaises(qubes.exc.QubesValueError):
                volume.set_passphrase(passphrase)
            self.assertFalse(volume.has_passphrase())

    def test_009_missing(self):
        volume = self.make_volume(encrypted=True)
        os.unlink(volume.path)
        # not taken for a volume without a header
        with self.assertRaises(StoragePoolException):
            volume.is_luks()
        with self.assertRaises(StoragePoolException):
            volume.encrypted = False
        self.assertTrue(volume.encrypted)

    def test_010_driver_support(self):
        volume = qubes.storage.Volume(
            name="private",
            pool=self.pool,
            vid="test-vm/private",
            rw=True,
            save_on_stop=True,
            size=SIZE,
        )
        self.assertFalse(volume.is_encryptable())
        with self.assertRaises(qubes.exc.QubesValueError):
            volume.encrypted = True


class TC_01_VolumeLuks(EncryptTestCase):
    """LUKS operations of a Volume"""

    def test_000_cryptsetup(self):
        volume = self.make_volume(encrypted=True)
        with self.assertRaises(StoragePoolException):
            self.loop.run_until_complete(volume.cryptsetup("--", "x"))
        self.cryptsetup.assert_not_called()
        volume.set_passphrase(b"s3cret")
        self.loop.run_until_complete(volume.cryptsetup("--", "x", "y"))
        self.cryptsetup.assert_called_once()
        self.assertEqual(
            self.cryptsetup.call_args.args,
            ("--batch-mode", "--key-file=-", "--", "x", "y"),
        )
        self.assertEqual(self.passphrases, [b"s3cret"])
        # a copy, wiped afterwards
        self.assertEqual(
            self.cryptsetup.call_args.kwargs["passphrase"], bytearray(6)
        )
        self.assertTrue(volume.has_passphrase())

    def test_001_is_luks(self):
        volume = self.make_volume()
        self.assertEqual(volume.luks_backend_path(), volume.path)
        self.assertFalse(volume.is_luks())
        self.write_luks_magic(volume)
        self.assertTrue(volume.is_luks())
        self.assertFalse(volume.is_partially_encrypted())
        # cryptsetup restores the header from a copy of a LUKS2 one
        for offset in (0x4000, 0x400000):
            with open(volume.path, "r+b") as image:
                image.write(bytes(6))
                image.seek(offset)
                image.write(b"SKUL\xba\xbe")
            self.assertTrue(volume.is_luks())
            self.assertTrue(volume.is_partially_encrypted())
            with open(volume.path, "r+b") as image:
                image.seek(offset)
                image.write(bytes(6))
        self.assertFalse(volume.is_luks())
        self.cryptsetup.assert_not_called()
        if not self.seek_data:
            self.skipTest("no SEEK_DATA support in the temporary directory")
        self.assertFalse(self.loop.run_until_complete(volume.is_empty()))
        volume = self.make_volume("empty")
        self.assertTrue(self.loop.run_until_complete(volume.is_empty()))

    def start_luks_volume(self):
        volume = self.make_volume(encrypted=True)
        volume.set_passphrase(b"s3cret")
        volume.start = unittest.mock.AsyncMock()
        volume.stop = unittest.mock.AsyncMock()
        volume.block_device = unittest.mock.Mock(
            return_value=qubes.storage.BlockDevice(
                "/dev/backend", "private", None, True, None, "disk"
            )
        )
        return volume

    def test_002_start_luks(self):
        volume = self.start_luks_volume()
        name = self.mapping(volume)
        self.loop.run_until_complete(volume.start_luks(name))
        volume.start.assert_awaited_once_with()
        self.cryptsetup.assert_called_once()
        self.assertEqual(
            self.cryptsetup.call_args.args,
            (
                "--batch-mode",
                "--key-file=-",
                "--type=luks2",
                "--allow-discards",
                "--",
                "open",
                "/dev/backend",
                name[12:],
            ),
        )
        self.assertEqual(self.passphrases, [b"s3cret"])
        self.assertFalse(volume.has_passphrase())
        volume.stop.assert_not_called()

    def test_003_start_luks_no_passphrase(self):
        volume = self.start_luks_volume()
        volume.clear_passphrase()
        with self.assertRaises(StoragePoolException):
            self.loop.run_until_complete(
                volume.start_luks(self.mapping(volume))
            )
        volume.start.assert_not_called()
        self.cryptsetup.assert_not_called()

    def test_004_check_passphrase(self):
        volume = self.start_luks_volume()
        # no header: nothing to unlock, do not even try
        with self.assertRaises(StoragePoolException):
            self.loop.run_until_complete(volume.check_passphrase())
        self.cryptsetup.assert_not_called()
        self.write_luks_magic(volume)
        self.loop.run_until_complete(volume.check_passphrase())
        self.cryptsetup.assert_called_once()
        self.assertEqual(
            self.cryptsetup.call_args.args,
            (
                "--batch-mode",
                "--key-file=-",
                "--test-passphrase",
                "--",
                "open",
                volume.path,
            ),
        )
        self.assertEqual(self.passphrases, [b"s3cret"])
        for returncode, reason, kept in (
            (1, "status 1", True),
            # useless for the next attempt
            (2, "wrong passphrase", False),
        ):
            self.fail_cryptsetup("--test-passphrase", returncode=returncode)
            with self.assertRaises(StoragePoolException) as ctx:
                self.loop.run_until_complete(volume.check_passphrase())
            self.assertIn(reason, str(ctx.exception))
            self.assertEqual(volume.has_passphrase(), kept)
        volume.set_passphrase(b"s3cret")
        # an interrupted in-place encryption must be finished first
        self.failing = None
        with open(volume.path, "r+b") as image:
            image.seek(4096)
            image.write(b'"requirements":{"mandatory":["online-reencrypt-v2"]}')
        self.assertTrue(volume.is_partially_encrypted())
        self.cryptsetup.reset_mock()
        with self.assertRaises(StoragePoolException) as ctx:
            self.loop.run_until_complete(volume.check_passphrase())
        self.assertIn("interrupted", str(ctx.exception))
        self.cryptsetup.assert_not_called()
        volume.start.assert_not_called()

    def test_005_start_luks_stale_mapping(self):
        volume = self.start_luks_volume()
        name = self.mapping(volume)
        close = unittest.mock.call("--", "close", name[12:])
        volume.start.side_effect = lambda: self.assertEqual(
            self.cryptsetup.call_args_list, [close]
        )
        with self.mapping_exists(name), self.assertLogs(
            "qubes.storage", "WARNING"
        ):
            self.loop.run_until_complete(volume.start_luks(name))
        volume.start.assert_awaited_once_with()
        self.assertEqual(self.cryptsetup.call_args_list[0], close)
        self.assertEqual(len(self.cryptsetup.call_args_list), 2)

    def test_006_start_luks_open_failed(self):
        volume = self.start_luks_volume()
        self.fail_cryptsetup("open", returncode=5)
        with self.assertRaises(StoragePoolException):
            self.loop.run_until_complete(
                volume.start_luks(self.mapping(volume))
            )
        volume.start.assert_awaited_once_with()
        volume.stop.assert_awaited_once_with()
        # keep it for the next attempt
        self.assertTrue(volume.has_passphrase())

    def test_007_change_passphrase(self):
        volume = self.make_volume(encrypted=True)
        self.write_luks_magic(volume)
        volume.set_passphrase(b"old")
        new_passphrase = []

        def side_effect(*args, **kwargs):
            # the new passphrase is readable from the passed fd
            (read_fd,) = kwargs["pass_fds"]
            new_passphrase.append(os.read(read_fd, 100))
            self.assertIn("/dev/fd/{}".format(read_fd), args)
            self.cryptsetup_side_effect(*args, **kwargs)

        self.cryptsetup.side_effect = side_effect
        self.loop.run_until_complete(volume.change_passphrase(b"old", b"new"))
        self.cryptsetup.assert_called_once()
        self.assertEqual(
            self.cryptsetup.call_args.args[:6],
            (
                "--batch-mode",
                "--key-file=-",
                "--pbkdf-memory=262144",
                "--",
                "luksChangeKey",
                volume.path,
            ),
        )
        self.assertEqual(self.passphrases, [b"old"])
        self.assertEqual(new_passphrase, [b"new"])
        # the one set before may be the old one
        self.assertFalse(volume.has_passphrase())

    def test_008_change_passphrase_failed(self):
        volume = self.make_volume(encrypted=True)
        volume.set_passphrase(b"old")
        for refused in ("is_running", "is_dirty"):
            setattr(volume, refused, lambda: True)
            with self.assertRaises(StoragePoolException):
                self.loop.run_until_complete(
                    volume.change_passphrase(b"old", b"new")
                )
            setattr(volume, refused, lambda: False)
        with self.assertRaises(qubes.exc.QubesValueError):
            self.loop.run_until_complete(
                volume.change_passphrase(b"old", b"new\nline")
            )
        # no header, or the encryption not finished
        for header in (b"", b'"mandatory":["online-reencrypt-v2"]'):
            with open(volume.path, "r+b") as image:
                image.write(LUKS_MAGIC if header else bytes(6))
                image.seek(4096)
                image.write(header)
            with self.assertRaises(StoragePoolException):
                self.loop.run_until_complete(
                    volume.change_passphrase(b"old", b"new")
                )
        self.cryptsetup.assert_not_called()
        with open(volume.path, "r+b") as image:
            image.seek(4096)
            image.write(bytes(64))
        self.fail_cryptsetup("luksChangeKey", returncode=2)
        with self.assertRaises(StoragePoolException) as ctx:
            self.loop.run_until_complete(
                volume.change_passphrase(b"wrong", b"new")
            )
        self.assertIn("wrong passphrase", str(ctx.exception))
        # pylint: disable=protected-access
        self.assertEqual(volume._passphrase, b"old")

    def test_009_cryptsetup_passphrase_changed(self):
        volume = self.make_volume(encrypted=True)
        volume.set_passphrase(b"s3cret")

        async def cryptsetup(*_args, passphrase, **_kwargs):
            # admin.vm.volume.SetPassphrase while cryptsetup starts
            volume.set_passphrase(b"other")
            self.passphrases.append(bytes(passphrase))

        self.cryptsetup.side_effect = cryptsetup
        self.loop.run_until_complete(volume.cryptsetup("--", "x"))
        self.assertEqual(self.passphrases, [b"s3cret"])


class TC_02_Storage(EncryptTestCase):
    """Encrypted volumes in Storage"""

    def setUp(self):
        super().setUp()
        self.run_program = unittest.mock.patch(
            "qubes.utils.run_program", new_callable=unittest.mock.AsyncMock
        ).start()
        state_dir = os.path.join(self.tmpdir, "run")
        os.mkdir(state_dir)
        unittest.mock.patch("qubes.storage.VOLUME_STATE_DIR", state_dir).start()

    def test_000_check_passphrases(self):
        encrypted = self.make_volume("private", encrypted=True)
        self.write_luks_magic(encrypted)
        encrypted.set_passphrase(b"s3cret")
        plain = self.make_volume("root")
        plain.set_passphrase(b"stale")
        self.loop.run_until_complete(self.storage.check_passphrases())
        self.assertEqual(
            self.cryptsetup_calls("--test-passphrase"),
            [
                (
                    "--batch-mode",
                    "--key-file=-",
                    "--test-passphrase",
                    "--",
                    "open",
                    encrypted.path,
                )
            ],
        )
        self.assertEqual(self.passphrases, [b"s3cret"])
        # kept for the start
        self.assertTrue(encrypted.has_passphrase())
        self.assertFalse(plain.has_passphrase())
        self.vm.fire_event_async.assert_not_called()

    def test_001_check_passphrases_wrong(self):
        first = self.make_volume("private", encrypted=True)
        second = self.make_volume("second", encrypted=True)
        for volume in (first, second):
            self.write_luks_magic(volume)
            volume.set_passphrase(b"s3cret")
        self.fail_cryptsetup(second.path, returncode=2)
        with self.assertRaises(StoragePoolException):
            self.loop.run_until_complete(self.storage.check_passphrases())
        # only the wrong passphrase is cleared
        self.assertTrue(first.has_passphrase())
        self.assertFalse(second.has_passphrase())

    def test_002_check_passphrases_missing(self):
        volume = self.make_volume(encrypted=True)
        with self.assertRaises(StoragePoolException):
            self.loop.run_until_complete(self.storage.check_passphrases())
        self.vm.fire_event_async.assert_awaited_once_with(
            "domain-passphrase-required", volumes=["private"]
        )
        self.cryptsetup.assert_not_called()
        self.assertFalse(volume.has_passphrase())

    def test_003_check_passphrases_from_event(self):
        volume = self.make_volume(encrypted=True)
        self.write_luks_magic(volume)

        async def handler(_event, volumes):
            self.assertEqual(volumes, ["private"])
            volume.set_passphrase(b"s3cret")

        self.vm.fire_event_async = handler
        self.loop.run_until_complete(self.storage.check_passphrases())
        self.assertEqual(self.passphrases, [b"s3cret"])

    def test_004_start(self):
        encrypted = self.make_volume("private", encrypted=True)
        encrypted.start_luks = unittest.mock.AsyncMock()
        volatile = self.make_volume("volatile", save_on_stop=False)
        volatile.ephemeral = True
        volatile.start_encrypted = unittest.mock.AsyncMock()
        plain = self.make_volume("root")
        plain.start = unittest.mock.AsyncMock()
        self.loop.run_until_complete(self.storage.start())
        encrypted.start_luks.assert_awaited_once_with(self.mapping(encrypted))
        volatile.start_encrypted.assert_awaited_once_with(
            self.mapping(volatile)
        )
        plain.start.assert_awaited_once_with()
        # checked before, see check_passphrases()
        self.cryptsetup.assert_not_called()
        self.vm.fire_event_async.assert_not_called()

    def test_005_start_sequential(self):
        first = self.make_volume("private", encrypted=True)
        second = self.make_volume("second", encrypted=True)
        plain = self.make_volume("root")
        plain.start = unittest.mock.AsyncMock()
        # the encrypted volumes are unlocked one by one, before the others
        first.start_luks = unittest.mock.AsyncMock(
            side_effect=lambda _name: self.assertFalse(
                second.start_luks.called or plain.start.called
            )
        )
        second.start_luks = unittest.mock.AsyncMock(
            side_effect=lambda _name: self.assertFalse(plain.start.called)
        )
        self.loop.run_until_complete(self.storage.start())
        first.start_luks.assert_awaited_once()
        second.start_luks.assert_awaited_once()
        plain.start.assert_awaited_once()

    def test_006_start_failed(self):
        first = self.make_volume("private", encrypted=True)
        second = self.make_volume("second", encrypted=True)
        plain = self.make_volume("root")
        for volume in (first, second):
            volume.start_luks = unittest.mock.AsyncMock()
            volume.stop_encrypted = unittest.mock.AsyncMock()
        plain.start = unittest.mock.AsyncMock(
            side_effect=StoragePoolException("start failed")
        )
        with self.assertRaises(StoragePoolException):
            self.loop.run_until_complete(self.storage.start())
        for volume in (first, second):
            volume.stop_encrypted.assert_awaited_once_with(self.mapping(volume))
        # an unlock failing: only the volumes unlocked before are stopped
        first.stop_encrypted.reset_mock()
        second.stop_encrypted.reset_mock()
        second.start_luks.side_effect = StoragePoolException("open failed")
        plain.start.reset_mock()
        with self.assertRaises(StoragePoolException):
            self.loop.run_until_complete(self.storage.start())
        first.stop_encrypted.assert_awaited_once_with(self.mapping(first))
        second.stop_encrypted.assert_not_called()
        plain.start.assert_not_called()

    def test_007_block_devices(self):
        encrypted = self.make_volume("private", encrypted=True)
        plain = self.make_volume("root")
        paths = {dev.name: dev.path for dev in self.storage.block_devices()}
        self.assertEqual(paths["private"], self.mapping(encrypted))
        self.assertEqual(paths["root"], plain.block_device().path)

    def test_008_resize(self):
        volume = self.make_volume(encrypted=True)
        resize = self.fake_resize(volume)
        # no header yet, or the encryption is not finished: the end of the
        # volume may hold data cryptsetup has to move
        for header in (b"", b'"mandatory":["online-reencrypt-v2"]'):
            with open(volume.path, "r+b") as image:
                image.write(LUKS_MAGIC if header else bytes(6))
                image.seek(4096)
                image.write(header)
            with self.assertRaises(StoragePoolException):
                self.loop.run_until_complete(
                    self.storage.resize("private", SIZE)
                )
        resize.assert_not_called()
        with open(volume.path, "r+b") as image:
            image.seek(4096)
            image.write(bytes(64))
        self.loop.run_until_complete(self.storage.resize("private", 2 * SIZE))
        resize.assert_called_once_with(2 * SIZE + LUKS2_HEADER_SIZE)
        self.assertEqual(volume.data_size, 2 * SIZE)
        self.cryptsetup.assert_not_called()

    def test_009_resize_started(self):
        volume = self.make_volume(encrypted=True)
        self.write_luks_magic(volume)
        resize = self.fake_resize(volume)
        name = self.mapping(volume)
        with self.mapping_exists(name):
            # the passphrase is needed before anything changes
            with self.assertRaises(StoragePoolException):
                self.loop.run_until_complete(
                    self.storage.resize("private", 2 * SIZE)
                )
            resize.assert_not_called()
            self.cryptsetup.assert_not_called()
            # a wrong one too
            volume.set_passphrase(b"wrong")
            self.fail_cryptsetup("--test-passphrase", returncode=2)
            with self.assertRaises(StoragePoolException):
                self.loop.run_until_complete(
                    self.storage.resize("private", 2 * SIZE)
                )
            resize.assert_not_called()
            self.failing = None
            self.cryptsetup.reset_mock()
            self.passphrases.clear()
            volume.set_passphrase(b"s3cret")
            self.loop.run_until_complete(
                self.storage.resize("private", 2 * SIZE)
            )
        resize.assert_called_once_with(2 * SIZE + LUKS2_HEADER_SIZE)
        self.assertEqual(
            self.cryptsetup_calls("--test-passphrase"),
            [
                (
                    "--batch-mode",
                    "--key-file=-",
                    "--test-passphrase",
                    "--",
                    "open",
                    volume.path,
                )
            ],
        )
        self.assertEqual(
            self.cryptsetup.call_args.args,
            ("--batch-mode", "--key-file=-", "--", "resize", name[12:]),
        )
        self.assertEqual(self.passphrases, [b"s3cret", b"s3cret"])
        # used up, like on start
        self.assertFalse(volume.has_passphrase())

    def test_010_resize_started_failed(self):
        volume = self.make_volume(encrypted=True)
        self.write_luks_magic(volume)
        volume.set_passphrase(b"s3cret")
        self.fake_resize(volume)
        self.fail_cryptsetup("resize")
        with self.mapping_exists(self.mapping(volume)), self.assertRaises(
            StoragePoolException
        ):
            self.loop.run_until_complete(
                self.storage.resize("private", 2 * SIZE)
            )
        # the qube sees the new size after a restart
        self.assertEqual(volume.data_size, 2 * SIZE)
        self.assertTrue(volume.has_passphrase())

    def test_020_import_data_plain(self):
        volume = self.make_volume()
        path = self.loop.run_until_complete(
            self.storage.import_data("private", None)
        )
        self.assertEqual(path, volume.path_import)
        self.assertEqual(os.path.getsize(path), SIZE)
        self.loop.run_until_complete(
            self.storage.import_data_end("private", True)
        )
        self.cryptsetup.assert_not_called()

    def test_021_import_data(self):
        volume = self.make_volume(encrypted=True)
        volume.set_passphrase(b"s3cret")
        name = self.import_mapping(volume)
        # not touched when starting the volume, but ignored by udev like it
        self.assertNotEqual(name, self.mapping(volume))
        self.assertTrue(name.startswith("/dev/mapper/vm-volatile-"))
        path = self.loop.run_until_complete(
            self.storage.import_data("private", None)
        )
        self.assertEqual(path, name)
        self.assertEqual(os.path.getsize(volume.path_import), SIZE)
        self.assertEqual(
            [call.args for call in self.cryptsetup.call_args_list],
            [
                (
                    "--batch-mode",
                    "--key-file=-",
                    "--type=luks2",
                    "--cipher=aes-xts-plain64",
                    "--sector-size=512",
                    "--pbkdf-memory=262144",
                    "--offset=65536",
                    "--",
                    "luksFormat",
                    volume.path_import,
                ),
                (
                    "--batch-mode",
                    "--key-file=-",
                    "--",
                    "open",
                    volume.path_import,
                    name[12:],
                ),
            ],
        )
        self.assertEqual(self.passphrases, [b"s3cret", b"s3cret"])
        self.run_program.assert_awaited_once_with(
            "dd",
            "if=/dev/zero",
            "of=" + name,
            "bs=1M",
            "count=10",
            "conv=nocreat,fsync",
            "status=none",
            sudo=True,
        )
        with self.mapping_exists(name):
            self.loop.run_until_complete(
                self.storage.import_data_end("private", True)
            )
        self.assertEqual(
            self.cryptsetup.call_args,
            unittest.mock.call("--", "close", name[12:]),
        )
        self.assertFalse(os.path.exists(volume.path_import))
        self.assertEqual(volume.size, SIZE)

    def test_022_import_data_size(self):
        volume = self.make_volume(encrypted=True)
        volume.set_passphrase(b"s3cret")
        self.loop.run_until_complete(
            self.storage.import_data("private", 4 << 20)
        )
        self.assertEqual(
            os.path.getsize(volume.path_import), (4 << 20) + LUKS2_HEADER_SIZE
        )
        self.assertIn("count=4", self.run_program.call_args.args)

    def test_023_import_data_in_use(self):
        volume = self.make_volume(encrypted=True)
        volume.set_passphrase(b"s3cret")
        with self.mapping_exists(
            self.import_mapping(volume)
        ), self.assertRaises(StoragePoolException):
            self.loop.run_until_complete(
                self.storage.import_data("private", None)
            )
        self.assertFalse(os.path.exists(volume.path_import))
        self.cryptsetup.assert_not_called()

    def test_024_import_data_running(self):
        volume = self.make_volume(encrypted=True)
        volume.set_passphrase(b"s3cret")
        volume.is_running = lambda: True
        with self.assertRaises(StoragePoolException):
            self.loop.run_until_complete(
                self.storage.import_data("private", None)
            )
        self.assertFalse(os.path.exists(volume.path_import))
        self.cryptsetup.assert_not_called()

    def test_025_import_data_failed(self):
        volume = self.make_volume(encrypted=True)
        volume.set_passphrase(b"s3cret")
        self.fail_cryptsetup("open")
        with self.assertRaises(StoragePoolException):
            self.loop.run_until_complete(
                self.storage.import_data("private", None)
            )
        self.assertFalse(os.path.exists(volume.path_import))
        self.run_program.assert_not_called()

    def test_026_import_data_passphrase(self):
        # replacing a container: its passphrase is required
        volume = self.make_volume(encrypted=True)
        self.write_luks_magic(volume)
        volume.set_passphrase(b"wrong")
        self.fail_cryptsetup("--test-passphrase", returncode=2)
        with self.assertRaises(StoragePoolException):
            self.loop.run_until_complete(
                self.storage.import_data("private", None)
            )
        self.assertFalse(self.cryptsetup_calls("luksFormat"))
        self.assertFalse(os.path.exists(volume.path_import))
        self.failing = None
        volume.set_passphrase(b"s3cret")
        self.loop.run_until_complete(self.storage.import_data("private", None))
        self.assertEqual(len(self.cryptsetup_calls("--test-passphrase")), 2)
        self.assertEqual(len(self.cryptsetup_calls("luksFormat")), 1)

    def test_030_import_volume(self):
        source = self.make_volume("source", encrypted=True)
        destination = self.make_volume("private")
        # saved before the copy
        self.app.save.side_effect = lambda: self.assertTrue(
            destination.encrypted
        )
        destination.import_volume = unittest.mock.AsyncMock(
            side_effect=lambda _src: self.app.save.assert_called_once_with()
        )
        self.loop.run_until_complete(
            self.storage.import_volume(destination, source)
        )
        self.assertTrue(destination.encrypted)
        destination.import_volume.assert_awaited_once_with(source)
        self.vm.fire_event_async.assert_awaited_once_with(
            "domain-import-volume", name="private", source=source
        )

    def test_031_import_volume_failed(self):
        source = self.make_volume("source", encrypted=True)
        destination = self.make_volume("private")
        destination.import_volume = unittest.mock.AsyncMock(
            side_effect=StoragePoolException("copy failed")
        )
        with self.assertRaises(StoragePoolException):
            self.loop.run_until_complete(
                self.storage.import_volume(destination, source)
            )
        # nothing copied
        self.assertFalse(destination.encrypted)
        self.assertEqual(self.app.save.call_count, 2)

    def test_032_import_volume_refused(self):
        encrypted = self.make_volume("source", encrypted=True)
        plain = self.make_volume("plain")
        volatile = self.make_volume("volatile", save_on_stop=False)
        for destination, source in ((encrypted, plain), (volatile, encrypted)):
            destination.import_volume = unittest.mock.AsyncMock()
            with self.assertRaises(qubes.exc.QubesException):
                self.loop.run_until_complete(
                    self.storage.import_volume(destination, source)
                )
            destination.import_volume.assert_not_called()
        self.assertFalse(volatile.encrypted)
        # nor into a volume of a template
        self.vm.klass = "TemplateVM"
        plain.import_volume = unittest.mock.AsyncMock()
        with self.assertRaises(qubes.exc.QubesValueError):
            self.loop.run_until_complete(
                self.storage.import_volume(plain, encrypted)
            )
        plain.import_volume.assert_not_called()
        self.assertFalse(plain.encrypted)
        # nor into a running qube, whose data would replace the copy
        self.vm.klass = "AppVM"
        plain.is_running = lambda: True
        with self.assertRaises(StoragePoolException):
            self.loop.run_until_complete(
                self.storage.import_volume(plain, encrypted)
            )
        plain.is_running = lambda: False
        # nor onto a header the qube wrote, kept if the copy failed
        self.write_luks_magic(plain)
        with self.assertRaises(StoragePoolException):
            self.loop.run_until_complete(
                self.storage.import_volume(plain, encrypted)
            )
        plain.import_volume.assert_not_called()
        self.assertFalse(plain.encrypted)
        self.app.save.assert_not_called()

    def test_033_clone_volume(self):
        source_vm = TestVM(self)
        source = self.pool.init_volume(
            source_vm,
            {
                "name": "private",
                "rw": True,
                "save_on_stop": True,
                "size": SIZE,
                "encrypted": True,
            },
        )
        source_vm.volumes["private"] = source
        self.vm.volume_config = {
            "private": {
                "name": "private",
                "pool": "test-pool",
                "rw": True,
                "save_on_stop": True,
                "size": SIZE,
            }
        }
        self.app.get_pool = lambda name: self.pool
        with unittest.mock.patch.object(
            qubes.storage.file.FileVolume,
            "import_volume",
            new_callable=unittest.mock.AsyncMock,
        ) as import_volume:
            volume = self.loop.run_until_complete(
                self.storage.clone_volume(source_vm, "private")
            )
        self.assertTrue(volume.encrypted)
        import_volume.assert_awaited_once_with(source)


class TC_03_StorageEncrypt(EncryptTestCase):
    """Storage.encrypt"""

    def setUp(self):
        super().setUp()
        self.run_program = unittest.mock.patch(
            "qubes.utils.run_program", new_callable=unittest.mock.AsyncMock
        ).start()
        self.volume = self.make_volume()
        self.volume.set_passphrase(b"s3cret")
        self.resize = self.fake_resize(self.volume)

    def encrypt(self):
        self.loop.run_until_complete(self.storage.encrypt("private"))

    def assert_refused(self, exception=StoragePoolException):
        with self.assertRaises(exception):
            self.encrypt()
        self.assertFalse(self.volume.encrypted)
        self.app.save.assert_not_called()
        self.assertEqual(os.path.getsize(self.volume.path), SIZE)

    def test_000_passphrase_required(self):
        self.volume.clear_passphrase()
        self.assert_refused()

    def test_001_dirty(self):
        self.volume.is_dirty = lambda: True
        self.assert_refused()

    def test_002_luks_header(self):
        self.write_luks_magic(self.volume)
        self.assert_refused()
        # written by the qube, cryptsetup would restore the header from it
        with open(self.volume.path, "r+b") as image:
            image.write(bytes(6))
            image.seek(0x4000)
            image.write(b"SKUL\xba\xbe")
        self.assert_refused()
        self.cryptsetup.assert_not_called()

    def test_003_revisions(self):
        with open(self.volume.path_cow + ".old", "wb"):
            pass
        self.assertEqual(self.volume.revisions_to_keep, 1)
        self.assert_refused()
        self.volume.revisions_to_keep = 0
        self.encrypt()
        self.assertFalse(self.volume.revisions)
        self.assertTrue(self.volume.encrypted)

    def test_004_empty(self):
        if not self.seek_data:
            self.skipTest("no SEEK_DATA support in the temporary directory")
        self.encrypt()
        self.assertTrue(self.volume.encrypted)
        self.app.save.assert_called_once_with()
        self.assertEqual(
            [call.args for call in self.cryptsetup.call_args_list],
            [
                (
                    "--batch-mode",
                    "--key-file=-",
                    "--type=luks2",
                    "--cipher=aes-xts-plain64",
                    "--sector-size=512",
                    "--pbkdf-memory=262144",
                    "--offset=65536",
                    "--",
                    "luksFormat",
                    self.volume.path_import,
                ),
                (
                    "--batch-mode",
                    "--key-file=-",
                    "--",
                    "open",
                    self.volume.path_import,
                    self.import_mapping(self.volume)[12:],
                ),
            ],
        )
        self.assertEqual(self.passphrases, [b"s3cret", b"s3cret"])
        self.resize.assert_not_called()
        # the new container replaced the empty volume
        self.assertFalse(os.path.exists(self.volume.path_import))
        self.assertEqual(self.volume.size, SIZE + LUKS2_HEADER_SIZE)
        self.assertEqual(self.volume.data_size, SIZE)

    def test_005_data(self):
        with open(self.volume.path, "r+b") as image:
            image.write(b"data")
        self.encrypt()
        self.assertTrue(self.volume.encrypted)
        self.app.save.assert_called_once_with()
        self.assertEqual(
            self.cryptsetup_calls("reencrypt"),
            [
                (
                    "--batch-mode",
                    "--key-file=-",
                    "--type=luks2",
                    "--cipher=aes-xts-plain64",
                    "--sector-size=512",
                    "--pbkdf-memory=262144",
                    "--offset=65536",
                    "--disable-blkid",
                    "--encrypt",
                    "--reduce-device-size={}".format(2 * LUKS2_HEADER_SIZE),
                    "--force-offline-reencrypt",
                    "--",
                    "reencrypt",
                    self.volume.path,
                )
            ],
        )
        self.assertEqual(
            self.resize.call_args_list,
            [
                unittest.mock.call(SIZE + 2 * LUKS2_HEADER_SIZE),
                unittest.mock.call(SIZE + LUKS2_HEADER_SIZE),
            ],
        )
        self.assertEqual(self.volume.size, SIZE + LUKS2_HEADER_SIZE)
        self.assertEqual(self.volume.data_size, SIZE)
        self.assertFalse(os.path.exists(self.volume.path_import))

    def test_006_save_first(self):
        with open(self.volume.path, "r+b") as image:
            image.write(b"data")
        # after growing it, before anything gets encrypted
        self.app.save.side_effect = lambda: self.assertEqual(
            (self.resize.call_count, self.cryptsetup_calls("reencrypt")),
            (1, []),
        )
        self.encrypt()
        self.app.save.assert_called_once_with()

    def write_interrupted_header(self):
        with open(self.volume.path, "r+b") as image:
            image.write(LUKS_MAGIC)
            image.seek(4096)
            image.write(b'"mandatory":["online-reencrypt-v2"]')

    def finish_reencrypt(self, *args, **kwargs):
        """cryptsetup mock finishing an interrupted encryption"""
        self.cryptsetup_side_effect(*args, **kwargs)
        if "--resume-only" in args:
            self.write_luks_magic(self.volume)
            with open(self.volume.path, "r+b") as image:
                image.seek(4096)
                image.write(bytes(64))

    def test_007_resume(self):
        # marked encrypted and with a header, but interrupted before finishing
        self.volume.encrypted = True
        self.write_interrupted_header()
        self.cryptsetup.side_effect = self.finish_reencrypt
        self.encrypt()
        self.app.save.assert_not_called()
        self.assertEqual(
            [call.args for call in self.cryptsetup.call_args_list],
            [
                (
                    "--batch-mode",
                    "--key-file=-",
                    "--",
                    "repair",
                    self.volume.path,
                ),
                (
                    "--batch-mode",
                    "--key-file=-",
                    "--resume-only",
                    "--force-offline-reencrypt",
                    "--",
                    "reencrypt",
                    self.volume.path,
                ),
            ],
        )
        self.resize.assert_called_once_with(SIZE - LUKS2_HEADER_SIZE)
        self.assertTrue(self.volume.encrypted)
        # finished: nothing to do, not even with a passphrase
        self.cryptsetup.reset_mock()
        self.resize.reset_mock()
        self.volume.clear_passphrase()
        self.encrypt()
        self.cryptsetup.assert_not_called()
        self.resize.assert_not_called()

    def test_008_resume_failed(self):
        self.volume.encrypted = True
        self.write_interrupted_header()
        # wrong passphrase, or resuming exits 0 without finishing
        for failing in (("repair", 2), ("--resume-only", 2), None):
            self.failing = failing
            with self.assertRaises(StoragePoolException):
                self.encrypt()
            self.resize.assert_not_called()
            self.assertTrue(self.volume.encrypted)
            self.assertTrue(self.volume.is_partially_encrypted())

    def test_009_retry(self):
        # marked encrypted, interrupted before writing the header (and before
        # moving any data), the volume grown or not
        for grown in (2 * LUKS2_HEADER_SIZE, 0):
            self.volume.encrypted = True
            with open(self.volume.path, "r+b") as image:
                image.write(b"data")
                image.truncate(SIZE + grown)
            self.resize.reset_mock()
            self.encrypt()
            self.app.save.assert_not_called()
            # grown (again): the qube may see 64 MiB more, but loses nothing
            self.assertEqual(
                self.resize.call_args_list,
                [
                    unittest.mock.call(SIZE + grown + 2 * LUKS2_HEADER_SIZE),
                    unittest.mock.call(SIZE + grown + LUKS2_HEADER_SIZE),
                ],
            )
            self.volume.encrypted = False
        self.assertEqual(len(self.cryptsetup_calls("--encrypt")), 2)

    def test_010_template(self):
        self.vm.klass = "TemplateVM"
        self.assert_refused(qubes.exc.QubesValueError)
        self.vm.klass = "AppVM"
        self.vm.template_for_dispvms = True
        self.assert_refused(qubes.exc.QubesValueError)

    def test_011_not_encryptable(self):
        volatile = self.make_volume("volatile", save_on_stop=False)
        volatile.set_passphrase(b"s3cret")
        with self.assertRaises(qubes.exc.QubesValueError):
            self.loop.run_until_complete(self.storage.encrypt("volatile"))
        self.assertFalse(volatile.encrypted)
        self.cryptsetup.assert_not_called()

    def test_012_reencrypt_failed(self):
        with open(self.volume.path, "r+b") as image:
            image.write(b"data")
        self.fail_cryptsetup("--encrypt", returncode=1)
        with self.assertRaises(StoragePoolException):
            self.encrypt()
        # nothing was encrypted: the flag saved first is dropped again and
        # the volume is back at its size
        self.assertFalse(self.volume.encrypted)
        self.app.save.assert_called_once_with()
        self.assertEqual(
            self.resize.call_args_list,
            [
                unittest.mock.call(SIZE + 2 * LUKS2_HEADER_SIZE),
                unittest.mock.call(SIZE),
            ],
        )
        self.assertEqual(self.volume.size, SIZE)

    def test_013_grow_failed(self):
        with open(self.volume.path, "r+b") as image:
            image.write(b"data")
        # the driver resized something else (a stale import volume on LVM)
        self.volume.resize = unittest.mock.Mock()
        with self.assertRaises(StoragePoolException):
            self.encrypt()
        self.assertFalse(self.cryptsetup_calls("reencrypt"))
        self.assertFalse(self.volume.encrypted)
        self.assertEqual(self.volume.size, SIZE)

    def test_014_reencrypt_failed_after_header(self):
        with open(self.volume.path, "r+b") as image:
            image.write(b"data")

        def interrupted(*args, **kwargs):
            self.cryptsetup_side_effect(*args, **kwargs)
            self.write_interrupted_header()
            raise subprocess.CalledProcessError(1, "cryptsetup")

        self.cryptsetup.side_effect = interrupted
        with self.assertRaises(StoragePoolException):
            self.encrypt()
        # to be finished by encrypting again: keep the flag and the size
        self.assertTrue(self.volume.encrypted)
        self.resize.assert_called_once_with(SIZE + 2 * LUKS2_HEADER_SIZE)
        self.assertEqual(self.volume.size, SIZE + 2 * LUKS2_HEADER_SIZE)

    def test_015_shrink_failed(self):
        with open(self.volume.path, "r+b") as image:
            image.write(b"data")

        def resize(size):
            if size < self.volume.size:
                raise StoragePoolException("lvresize failed")
            with open(self.volume.path, "r+b") as image:
                image.truncate(size)

        self.resize.side_effect = resize
        self.cryptsetup.side_effect = lambda *args, **kwargs: (
            self.write_luks_magic(self.volume)
        )
        with self.assertRaises(StoragePoolException):
            self.encrypt()
        # encrypted, the qube just sees a bigger volume
        self.assertTrue(self.volume.encrypted)
        self.assertEqual(self.volume.size, SIZE + 2 * LUKS2_HEADER_SIZE)

    def test_016_import_failed(self):
        if not self.seek_data:
            self.skipTest("no SEEK_DATA support in the temporary directory")
        self.fail_cryptsetup("luksFormat")
        with self.assertRaises(StoragePoolException):
            self.encrypt()
        self.assertFalse(self.volume.encrypted)
        self.assertFalse(os.path.exists(self.volume.path_import))
        self.assertEqual(self.volume.size, SIZE)

    def test_017_running(self):
        # halted, but the storage is not stopped yet
        self.volume.is_running = lambda: True
        self.assert_refused()
        self.cryptsetup.assert_not_called()

    def test_018_no_space(self):
        with open(self.volume.path, "r+b") as image:
            image.write(b"data")
        needed = SIZE + 2 * LUKS2_HEADER_SIZE
        # blocks already allocated may be shared (reflink, snapshots)
        with unittest.mock.patch.object(
            qubes.storage.file.FilePool,
            "usage",
            new_callable=unittest.mock.PropertyMock,
            return_value=self.pool.size - needed + 1,
        ):
            with self.assertRaises(StoragePoolException):
                self.encrypt()
        self.resize.assert_not_called()
        self.cryptsetup.assert_not_called()
        self.assertFalse(self.volume.encrypted)
        with unittest.mock.patch.object(
            qubes.storage.file.FilePool,
            "usage",
            new_callable=unittest.mock.PropertyMock,
            return_value=self.pool.size - needed,
        ):
            self.encrypt()
        self.assertTrue(self.volume.encrypted)

    def test_019_missing(self):
        os.unlink(self.volume.path)
        with self.assertRaises(StoragePoolException):
            self.encrypt()
        self.assertFalse(self.volume.encrypted)
        # nor resumed
        self.volume.encrypted = True
        with self.assertRaises(StoragePoolException):
            self.encrypt()
        self.assertTrue(self.volume.encrypted)
        self.cryptsetup.assert_not_called()
        self.app.save.assert_not_called()

    def test_020_resume_header_copy(self):
        # power loss while cryptsetup wrote the header: only its copy is left
        self.volume.encrypted = True
        with open(self.volume.path, "r+b") as image:
            image.seek(0x4000)
            image.write(b"SKUL\xba\xbe")

        def repair(*args, **kwargs):
            self.finish_reencrypt(*args, **kwargs)
            if "repair" in args:
                self.write_interrupted_header()

        self.cryptsetup.side_effect = repair
        self.encrypt()
        self.assertEqual(
            [call.args[-2] for call in self.cryptsetup.call_args_list],
            ["repair", "reencrypt"],
        )
        self.assertEqual(self.cryptsetup.call_args.args[2], "--resume-only")
        # finished only the header: nothing to shrink
        self.resize.reset_mock()
        self.cryptsetup.reset_mock()
        with open(self.volume.path, "r+b") as image:
            image.write(bytes(6))
        self.cryptsetup.side_effect = lambda *args, **kwargs: (
            self.write_luks_magic(self.volume)
        )
        self.encrypt()
        self.assertEqual(len(self.cryptsetup.call_args_list), 1)
        self.resize.assert_not_called()

    def test_021_retry_data_moved(self):
        # marked encrypted, and cryptsetup moved the start of the data to the
        # end, but the power got lost before the header was written (or it
        # was not grown, and the qube used the end of the volume)
        self.volume.encrypted = True
        with open(self.volume.path, "r+b") as image:
            image.write(b"data")
            image.seek(SIZE - LUKS2_HEADER_SIZE)
            image.write(b"data")
        with self.assertRaises(StoragePoolException) as ctx:
            self.encrypt()
        self.assertIn("manual recovery", str(ctx.exception))
        self.assertFalse(self.cryptsetup_calls("reencrypt"))
        self.resize.assert_not_called()
        self.assertTrue(self.volume.encrypted)

    def test_022_reencrypt_failed_data_moved(self):
        with open(self.volume.path, "r+b") as image:
            image.write(b"data")

        def failed(*args, **kwargs):
            self.cryptsetup_side_effect(*args, **kwargs)
            # moved the start of the data, then failed writing the header
            with open(self.volume.path, "r+b") as image:
                image.seek(SIZE + LUKS2_HEADER_SIZE)
                image.write(b"data")
            raise subprocess.CalledProcessError(1, "cryptsetup")

        self.cryptsetup.side_effect = failed
        with self.assertRaises(StoragePoolException):
            self.encrypt()
        # the end of the volume holds data: do not shrink it away
        self.assertTrue(self.volume.encrypted)
        self.resize.assert_called_once_with(SIZE + 2 * LUKS2_HEADER_SIZE)


class TC_04_Drivers(qubes.tests.QubesTestCase):
    """What pool drivers implement for encrypted volumes"""

    def setUp(self):
        super().setUp()
        self.tmpdir = tempfile.mkdtemp()
        self.app = TestApp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)
        super().tearDown()

    def test_000_file(self):
        pool = qubes.storage.file.FilePool(name="test", dir_path=self.tmpdir)
        pool.setup()
        volume = pool.init_volume(
            TestVM(self),
            {"name": "private", "rw": True, "save_on_stop": True, "size": SIZE},
        )
        os.makedirs(os.path.dirname(volume.path))
        self.loop.run_until_complete(qubes.utils.coro_maybe(volume.create()))
        with open(volume.path_cow + ".old", "wb"):
            pass
        self.assertTrue(volume.revisions)
        self.loop.run_until_complete(volume.discard_revisions())
        self.assertFalse(volume.revisions)
        self.assertTrue(os.path.exists(volume.path))

    def test_001_lvm(self):
        pool = qubes.storage.Pool(name="test")
        volume = qubes.storage.lvm.ThinVolume(
            volume_group="qubes_dom0",
            name="private",
            pool=pool,
            vid="qubes_dom0/vm-test-private",
            rw=True,
            save_on_stop=True,
            size=SIZE,
        )
        revisions = {"1-back": "2020-01-01T00:00:00", "2-back": "2020-01-02"}
        with unittest.mock.patch.object(
            qubes.storage.lvm.ThinVolume,
            "revisions",
            new_callable=unittest.mock.PropertyMock,
            return_value=revisions,
        ), unittest.mock.patch(
            "qubes.storage.lvm.qubes_lvm_coro",
            new_callable=unittest.mock.AsyncMock,
        ) as lvm, unittest.mock.patch(
            "qubes.storage.lvm.reset_cache_coro",
            new_callable=unittest.mock.AsyncMock,
        ) as reset_cache:
            self.loop.run_until_complete(volume.discard_revisions())
            self.assertEqual(
                [call.args[0] for call in lvm.call_args_list],
                [
                    ["remove", "qubes_dom0/vm-test-private-1-back"],
                    ["remove", "qubes_dom0/vm-test-private-2-back"],
                ],
            )
            reset_cache.assert_awaited_once_with()
            lvm.side_effect = StoragePoolException("lvremove failed")
            with self.assertRaises(StoragePoolException):
                self.loop.run_until_complete(volume.discard_revisions())

    def test_002_lvm_is_empty(self):
        pool = qubes.storage.Pool(name="test")
        volume = qubes.storage.lvm.ThinVolume(
            volume_group="qubes_dom0",
            name="private",
            pool=pool,
            vid="qubes_dom0/vm-test-private",
            rw=True,
            save_on_stop=True,
            size=SIZE,
        )
        proc = unittest.mock.Mock(returncode=0)
        proc.communicate = unittest.mock.AsyncMock(
            return_value=(b"0 131072 thin 0 -\n", b"")
        )
        with unittest.mock.patch(
            "asyncio.create_subprocess_exec",
            new_callable=unittest.mock.AsyncMock,
            return_value=proc,
        ) as exec_mock:
            self.assertTrue(self.loop.run_until_complete(volume.is_empty()))
            self.assertEqual(
                exec_mock.call_args.args[-3:],
                ("status", "--", volume.path),
            )
            proc.communicate.return_value = (b"0 131072 thin 128 2047\n", b"")
            self.assertFalse(self.loop.run_until_complete(volume.is_empty()))
            # only the zeroed first chunk is mapped
            proc.communicate.return_value = (b"0 131072 thin 128 127\n", b"")
            for data, empty in ((bytes(65536), True), (b"x" * 65536, False)):
                with unittest.mock.patch(
                    "builtins.open", unittest.mock.mock_open(read_data=data)
                ):
                    self.assertEqual(
                        self.loop.run_until_complete(volume.is_empty()), empty
                    )

    def test_003_lvm_resize(self):
        volume = qubes.storage.lvm.ThinVolume(
            volume_group="qubes_dom0",
            name="private",
            pool=qubes.storage.Pool(name="test"),
            vid="qubes_dom0/vm-test-private",
            rw=True,
            save_on_stop=True,
            size=SIZE,
        )
        with unittest.mock.patch(
            "qubes.storage.lvm.qubes_lvm_coro",
            new_callable=unittest.mock.AsyncMock,
        ) as lvm, unittest.mock.patch(
            "qubes.storage.lvm.reset_cache_coro",
            new_callable=unittest.mock.AsyncMock,
        ):
            self.loop.run_until_complete(volume.resize(2 * SIZE))
            volume.encrypted = True
            self.loop.run_until_complete(volume.resize(SIZE))
        self.assertEqual(
            [call.args[0] for call in lvm.call_args_list],
            [
                ["resize", volume.vid, str(2 * SIZE)],
                ["resize_luks", volume.vid, str(SIZE)],
            ],
        )
        # lvresize refuses to cut a filesystem it sees, but needs to be
        # forced to shrink an encrypted volume
        # pylint: disable=protected-access
        resize = qubes.storage.lvm._get_lvm_cmdline(["resize", "vg/lv", "1"])
        self.assertNotIn("--yes", resize)
        self.assertNotIn("--fs=ignore", resize)
        resize = qubes.storage.lvm._get_lvm_cmdline(
            ["resize_luks", "vg/lv", "1"]
        )
        self.assertIn("--yes", resize)
        self.assertIn("--fs=ignore", resize)

    def test_004_zfs_not_encryptable(self):
        self.assertFalse(qubes.storage.zfs.ZFSVolume.encryption_supported)

    def test_005_reflink(self):
        pool = qubes.storage.reflink.ReflinkPool(
            name="test", dir_path=self.tmpdir, setup_check=False
        )
        volume = pool.init_volume(
            TestVM(self),
            {"name": "private", "rw": True, "save_on_stop": True, "size": SIZE},
        )
        # pylint: disable=protected-access
        os.makedirs(os.path.dirname(volume._path_clean))
        self.assertEqual(volume.luks_backend_path(), volume._path_clean)
        for revision in ("1@2020-01-01T00:00:00Z", "2@2020-01-02T00:00:00Z"):
            with open(volume._path_clean + "." + revision, "wb"):
                pass
        self.assertEqual(len(volume.revisions), 2)
        self.loop.run_until_complete(volume.discard_revisions())
        self.assertFalse(volume.revisions)

    def test_006_reflink_change_passphrase(self):
        pool = qubes.storage.reflink.ReflinkPool(
            name="test", dir_path=self.tmpdir, setup_check=False
        )
        volume = pool.init_volume(
            TestVM(self),
            {
                "name": "private",
                "rw": True,
                "save_on_stop": True,
                "size": SIZE,
                "encrypted": True,
            },
        )
        # pylint: disable=protected-access
        os.makedirs(os.path.dirname(volume._path_clean))
        for path in (volume._path_clean, volume._path_precache):
            with open(path, "wb") as image:
                image.write(LUKS_MAGIC)
        with unittest.mock.patch(
            "qubes.utils.cryptsetup", new_callable=unittest.mock.AsyncMock
        ) as cryptsetup:
            self.loop.run_until_complete(
                volume.change_passphrase(b"old", b"new")
            )
        self.assertEqual(
            cryptsetup.call_args.args[4:6],
            ("luksChangeKey", volume._path_clean),
        )
        # it would keep the old keyslot
        self.assertFalse(os.path.exists(volume._path_precache))
