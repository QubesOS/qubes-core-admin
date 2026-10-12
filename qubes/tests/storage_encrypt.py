#
# The Qubes OS Project, https://www.qubes-os.org/
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


class TC_01_VolumeLuks(EncryptTestCase):
    """LUKS operations of a Volume"""

    def test_000_cryptsetup(self):
        volume = self.make_volume(encrypted=True)
        with self.assertRaises(StoragePoolException):
            self.loop.run_until_complete(volume.cryptsetup("--", "x"))
        self.cryptsetup.assert_not_called()
        volume.set_passphrase(b"s3cret")
        self.loop.run_until_complete(volume.cryptsetup("--", "x", "y"))
        self.cryptsetup.assert_called_once_with(
            "--batch-mode",
            "--key-file=-",
            "--",
            "x",
            "y",
            passphrase=bytearray(b"s3cret"),
        )

    def test_001_is_luks(self):
        volume = self.make_volume()
        self.assertEqual(volume.luks_backend_path(), volume.path)
        self.assertFalse(volume.is_luks())
        self.assertTrue(self.loop.run_until_complete(volume.is_empty()))
        self.write_luks_magic(volume)
        self.assertTrue(volume.is_luks())
        self.assertFalse(self.loop.run_until_complete(volume.is_empty()))
        self.cryptsetup.assert_not_called()

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
        self.loop.run_until_complete(volume.check_passphrase())
        self.cryptsetup.assert_called_once_with(
            "--batch-mode",
            "--key-file=-",
            "--test-passphrase",
            "--",
            "open",
            volume.path,
            passphrase=bytearray(b"s3cret"),
        )
        for returncode in (1, 2):
            self.fail_cryptsetup("--test-passphrase", returncode=returncode)
            with self.assertRaises(StoragePoolException):
                self.loop.run_until_complete(volume.check_passphrase())
        self.assertTrue(volume.has_passphrase())
        volume.start.assert_not_called()

    def test_005_start_luks_stale_mapping(self):
        volume = self.start_luks_volume()
        name = self.mapping(volume)
        exists = os.path.exists
        close = unittest.mock.call("--", "close", name[12:])
        volume.start.side_effect = lambda: self.assertEqual(
            self.cryptsetup.call_args_list, [close]
        )
        with unittest.mock.patch(
            "os.path.exists", lambda path: path == name or exists(path)
        ), self.assertLogs("qubes.storage", "WARNING"):
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
            self.cryptsetup.call_args.args[:5],
            (
                "--batch-mode",
                "--key-file=-",
                "--",
                "luksChangeKey",
                volume.path,
            ),
        )
        self.assertEqual(self.passphrases, [b"old"])
        self.assertEqual(new_passphrase, [b"new"])
        # pylint: disable=protected-access
        self.assertEqual(volume._passphrase, b"new")

    def test_008_change_passphrase_failed(self):
        volume = self.make_volume(encrypted=True)
        volume.set_passphrase(b"old")
        volume.is_dirty = lambda: True
        with self.assertRaises(StoragePoolException):
            self.loop.run_until_complete(
                volume.change_passphrase(b"old", b"new")
            )
        volume.is_dirty = lambda: False
        with self.assertRaises(qubes.exc.QubesValueError):
            self.loop.run_until_complete(
                volume.change_passphrase(b"old", b"new\nline")
            )
        self.cryptsetup.assert_not_called()
        self.fail_cryptsetup("luksChangeKey", returncode=2)
        with self.assertRaises(StoragePoolException):
            self.loop.run_until_complete(
                volume.change_passphrase(b"wrong", b"new")
            )
        # pylint: disable=protected-access
        self.assertEqual(volume._passphrase, b"old")


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

    def test_000_start(self):
        encrypted = self.make_volume("private", encrypted=True)
        encrypted.set_passphrase(b"s3cret")
        encrypted.start_luks = unittest.mock.AsyncMock()
        volatile = self.make_volume("volatile", save_on_stop=False)
        volatile.ephemeral = True
        volatile.start_encrypted = unittest.mock.AsyncMock()
        plain = self.make_volume("root")
        plain.set_passphrase(b"stale")
        plain.start = unittest.mock.AsyncMock()
        encrypted.start_luks.side_effect = lambda _name: self.assertIn(
            "--test-passphrase", self.cryptsetup.call_args.args
        )
        self.loop.run_until_complete(self.storage.start())
        encrypted.start_luks.assert_awaited_once_with(self.mapping(encrypted))
        volatile.start_encrypted.assert_awaited_once_with(
            self.mapping(volatile)
        )
        plain.start.assert_awaited_once_with()
        self.assertFalse(plain.has_passphrase())
        self.vm.fire_event_async.assert_not_called()
        self.assertEqual(self.passphrases, [b"s3cret"])

    def test_000b_start_wrong_passphrase(self):
        first = self.make_volume("private", encrypted=True)
        second = self.make_volume("second", encrypted=True)
        for volume in (first, second):
            volume.set_passphrase(b"s3cret")
            volume.start_luks = unittest.mock.AsyncMock()
        self.fail_cryptsetup(second.path, returncode=2)
        with self.assertRaises(StoragePoolException):
            self.loop.run_until_complete(self.storage.start())
        # nothing started, passphrases kept for the next attempt
        first.start_luks.assert_not_called()
        second.start_luks.assert_not_called()
        self.assertTrue(first.has_passphrase())
        self.assertTrue(second.has_passphrase())

    def test_001_start_passphrase_required(self):
        volume = self.make_volume(encrypted=True)
        volume.start_luks = unittest.mock.AsyncMock()
        with self.assertRaises(StoragePoolException):
            self.loop.run_until_complete(self.storage.start())
        self.vm.fire_event_async.assert_awaited_once_with(
            "domain-passphrase-required", volumes=["private"]
        )
        volume.start_luks.assert_not_called()

    def test_002_start_passphrase_from_event(self):
        volume = self.make_volume(encrypted=True)
        volume.start_luks = unittest.mock.AsyncMock()

        async def handler(_event, volumes):
            self.assertEqual(volumes, ["private"])
            volume.set_passphrase(b"s3cret")

        self.vm.fire_event_async = handler
        self.loop.run_until_complete(self.storage.start())
        volume.start_luks.assert_awaited_once_with(self.mapping(volume))

    def test_003_block_devices(self):
        encrypted = self.make_volume("private", encrypted=True)
        plain = self.make_volume("root")
        paths = {dev.name: dev.path for dev in self.storage.block_devices()}
        self.assertEqual(paths["private"], self.mapping(encrypted))
        self.assertEqual(paths["root"], plain.block_device().path)

    def test_004_resize(self):
        volume = self.make_volume(encrypted=True)
        resize = self.fake_resize(volume)
        self.loop.run_until_complete(self.storage.resize("private", 2 * SIZE))
        resize.assert_called_once_with(2 * SIZE + LUKS2_HEADER_SIZE)
        self.assertEqual(volume.data_size, 2 * SIZE)
        self.cryptsetup.assert_not_called()

    def test_005_resize_started(self):
        volume = self.make_volume(encrypted=True)
        resize = self.fake_resize(volume)
        name = self.mapping(volume)
        exists = os.path.exists
        with unittest.mock.patch(
            "os.path.exists", lambda path: path == name or exists(path)
        ):
            # the passphrase is needed before anything changes
            with self.assertRaises(StoragePoolException):
                self.loop.run_until_complete(
                    self.storage.resize("private", 2 * SIZE)
                )
            resize.assert_not_called()
            self.cryptsetup.assert_not_called()
            volume.set_passphrase(b"s3cret")
            self.loop.run_until_complete(
                self.storage.resize("private", 2 * SIZE)
            )
        resize.assert_called_once_with(2 * SIZE + LUKS2_HEADER_SIZE)
        self.cryptsetup.assert_called_once_with(
            "--batch-mode",
            "--key-file=-",
            "--",
            "resize",
            name[12:],
            passphrase=bytearray(b"s3cret"),
        )

    def test_010_import_data_plain(self):
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

    def test_011_import_data(self):
        volume = self.make_volume(encrypted=True)
        volume.set_passphrase(b"s3cret")
        name = self.mapping(volume)
        path = self.loop.run_until_complete(
            self.storage.import_data("private", None)
        )
        self.assertEqual(path, name)
        self.assertEqual(
            os.path.getsize(volume.path_import),
            SIZE - LUKS2_HEADER_SIZE + LUKS2_HEADER_SIZE,
        )
        self.assertEqual(
            self.cryptsetup.call_args_list,
            [
                unittest.mock.call(
                    "--batch-mode",
                    "--key-file=-",
                    "--type=luks2",
                    "--cipher=aes-xts-plain64",
                    "--offset=65536",
                    "--",
                    "luksFormat",
                    volume.path_import,
                    passphrase=bytearray(b"s3cret"),
                ),
                unittest.mock.call(
                    "--batch-mode",
                    "--key-file=-",
                    "--",
                    "open",
                    volume.path_import,
                    name[12:],
                    passphrase=bytearray(b"s3cret"),
                ),
            ],
        )
        self.run_program.assert_awaited_once_with(
            "dd",
            "if=/dev/zero",
            "of=" + name,
            "bs=1M",
            "count=10",
            "conv=fsync",
            sudo=True,
        )
        exists = os.path.exists
        with unittest.mock.patch(
            "os.path.exists", lambda path: path == name or exists(path)
        ):
            self.loop.run_until_complete(
                self.storage.import_data_end("private", True)
            )
        self.assertEqual(
            self.cryptsetup.call_args,
            unittest.mock.call("--", "close", name[12:]),
        )
        self.assertFalse(os.path.exists(volume.path_import))
        self.assertEqual(volume.size, SIZE)

    def test_012_import_data_size(self):
        volume = self.make_volume(encrypted=True)
        volume.set_passphrase(b"s3cret")
        self.loop.run_until_complete(
            self.storage.import_data("private", 4 << 20)
        )
        self.assertEqual(
            os.path.getsize(volume.path_import), (4 << 20) + LUKS2_HEADER_SIZE
        )
        self.assertIn("count=4", self.run_program.call_args.args)

    def test_013_import_data_in_use(self):
        volume = self.make_volume(encrypted=True)
        volume.set_passphrase(b"s3cret")
        name = self.mapping(volume)
        exists = os.path.exists
        with unittest.mock.patch(
            "os.path.exists", lambda path: path == name or exists(path)
        ), self.assertRaises(StoragePoolException):
            self.loop.run_until_complete(
                self.storage.import_data("private", None)
            )
        self.assertFalse(exists(volume.path_import))
        self.cryptsetup.assert_not_called()

    def test_014_import_data_failed(self):
        volume = self.make_volume(encrypted=True)
        volume.set_passphrase(b"s3cret")
        self.fail_cryptsetup("open")
        with self.assertRaises(subprocess.CalledProcessError):
            self.loop.run_until_complete(
                self.storage.import_data("private", None)
            )
        self.assertFalse(os.path.exists(volume.path_import))
        self.run_program.assert_not_called()

    def test_020_import_volume(self):
        source = self.make_volume("source", encrypted=True)
        destination = self.make_volume("private")
        destination.import_volume = unittest.mock.AsyncMock(
            side_effect=lambda _src: self.assertFalse(destination.encrypted)
        )
        self.loop.run_until_complete(
            self.storage.import_volume(destination, source)
        )
        self.assertTrue(destination.encrypted)
        destination.import_volume.assert_awaited_once_with(source)
        self.vm.fire_event_async.assert_awaited_once_with(
            "domain-import-volume", name="private", source=source
        )

    def test_021_import_volume_refused(self):
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
        with self.assertRaises(StoragePoolException):
            self.loop.run_until_complete(
                self.storage.import_volume(plain, encrypted)
            )
        plain.import_volume.assert_not_called()
        self.assertFalse(plain.encrypted)

    def test_022_clone_volume(self):
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

    def assert_refused(self):
        with self.assertRaises(StoragePoolException):
            self.encrypt()
        self.assertFalse(self.volume.encrypted)
        self.app.save.assert_not_called()
        self.assertEqual(os.path.getsize(self.volume.path), SIZE)

    def test_000_passphrase_required(self):
        self.volume.clear_passphrase()
        self.assert_refused()

    def test_002_dirty(self):
        self.volume.is_dirty = lambda: True
        self.assert_refused()

    def test_003_luks_header(self):
        self.write_luks_magic(self.volume)
        self.assert_refused()

    def test_004_revisions(self):
        with open(self.volume.path_cow + ".old", "wb"):
            pass
        self.assertEqual(self.volume.revisions_to_keep, 1)
        self.assert_refused()
        self.volume.revisions_to_keep = 0
        self.encrypt()
        self.assertFalse(self.volume.revisions)
        self.assertTrue(self.volume.encrypted)

    def test_005_empty(self):
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
                    self.mapping(self.volume)[12:],
                ),
            ],
        )
        self.assertEqual(self.passphrases, [b"s3cret", b"s3cret"])
        self.resize.assert_not_called()
        # the new container replaced the empty volume
        self.assertFalse(os.path.exists(self.volume.path_import))
        self.assertEqual(self.volume.size, SIZE + LUKS2_HEADER_SIZE)
        self.assertEqual(self.volume.data_size, SIZE)

    def test_006_data(self):
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
                    "--encrypt",
                    "--reduce-device-size={}".format(2 * LUKS2_HEADER_SIZE),
                    "--offset=65536",
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

    def test_007_save_first(self):
        with open(self.volume.path, "r+b") as image:
            image.write(b"data")
        self.app.save.side_effect = lambda: self.assertFalse(
            self.cryptsetup_calls("reencrypt") or self.resize.called
        )
        self.encrypt()
        self.app.save.assert_called_once_with()

    def test_008_resume(self):
        # marked encrypted and with a header, but interrupted before finishing
        self.volume.encrypted = True
        self.write_luks_magic(self.volume)
        self.fail_cryptsetup("--resume-only", returncode=1)
        self.encrypt()
        self.app.save.assert_not_called()
        self.assertEqual(
            self.cryptsetup_calls("reencrypt"),
            [
                (
                    "--batch-mode",
                    "--key-file=-",
                    "--resume-only",
                    "--force-offline-reencrypt",
                    "--",
                    "reencrypt",
                    self.volume.path,
                )
            ],
        )
        # nothing to resume, so nothing to shrink either
        self.resize.assert_not_called()
        self.failing = None
        self.encrypt()
        self.resize.assert_called_once_with(SIZE - LUKS2_HEADER_SIZE)
        self.fail_cryptsetup("--resume-only", returncode=2)
        with self.assertRaises(StoragePoolException):
            self.encrypt()

    def test_009_retry(self):
        # marked encrypted, but interrupted before writing the header
        self.volume.encrypted = True
        with open(self.volume.path, "r+b") as image:
            image.write(b"data")
        self.encrypt()
        self.app.save.assert_not_called()
        self.assertEqual(len(self.cryptsetup_calls("--encrypt")), 1)
        self.assertEqual(self.volume.size, SIZE + LUKS2_HEADER_SIZE)

    def test_010_template(self):
        self.vm.klass = "TemplateVM"
        self.assert_refused()
        self.vm.klass = "AppVM"
        self.vm.template_for_dispvms = True
        self.assert_refused()

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
        # the flag was saved first, the volume is back at its size
        self.assertTrue(self.volume.encrypted)
        self.app.save.assert_called_once_with()
        self.assertEqual(
            self.resize.call_args_list,
            [
                unittest.mock.call(SIZE + 2 * LUKS2_HEADER_SIZE),
                unittest.mock.call(SIZE),
            ],
        )
        self.assertEqual(self.volume.size, SIZE)


class TC_04_DiscardRevisions(qubes.tests.QubesTestCase):
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

    def test_001b_lvm_is_empty(self):
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

    def test_001c_zfs_not_encryptable(self):
        volume = object.__new__(qubes.storage.zfs.ZFSVolume)
        self.assertFalse(volume.is_encryptable())

    def test_002_reflink(self):
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
