#
# The Qubes OS Project, https://www.qubes-os.org/
#
# This library is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 2.1 of the License, or (at your option) any later version.
#
"""Tests for persistent per-VM LUKS2 encryption (#1293)."""

import asyncio
import os
import shutil
import subprocess
import tempfile
import unittest.mock

import qubes.exc
import qubes.storage
import qubes.storage.file
import qubes.tests
import qubes.tests.storage
from qubes.config import defaults
from qubes.storage import StoragePoolException


class _DummyApp:
    """Stand-in so TestVM can be constructed without a full Qubes()."""


class _EncryptTestCase(qubes.tests.QubesTestCase):
    def setUp(self):
        try:
            asyncio.get_event_loop()
        except RuntimeError:
            asyncio.set_event_loop(asyncio.new_event_loop())
        super().setUp()
        self.app = _DummyApp()
        self.tmpdir = tempfile.mkdtemp()
        self.pool = qubes.storage.file.FilePool(
            name="test-enc-pool", dir_path=self.tmpdir
        )
        self.pool.setup()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)
        super().tearDown()

    def _private_volume(self, **extra):
        config = {
            "name": "private",
            "rw": True,
            "save_on_stop": True,
            "size": defaults["private_img_size"],
        }
        config.update(extra)
        vm = qubes.tests.storage.TestVM(self)
        return self.pool.init_volume(vm, config)

    def _volatile_volume(self, **extra):
        config = {
            "name": "volatile",
            "rw": True,
            "size": defaults["root_img_size"],
        }
        config.update(extra)
        vm = qubes.tests.storage.TestVM(self)
        return self.pool.init_volume(vm, config)


class TC_00_EncryptedProperty(_EncryptTestCase):
    """Volume.encrypted constraints and serialization."""

    def test_000_default_false(self):
        vol = self._private_volume()
        self.assertFalse(vol.encrypted)
        self.assertNotIn("encrypted", vol.config)

    def test_001_enable_on_private(self):
        vol = self._private_volume()
        vol.encrypted = True
        self.assertTrue(vol.encrypted)
        self.assertTrue(vol.config["encrypted"])

    def test_002_init_with_encrypted(self):
        vol = self._private_volume(encrypted=True)
        self.assertTrue(vol.encrypted)
        self.assertTrue(vol.config["encrypted"])

    def test_003_reject_volatile(self):
        vol = self._volatile_volume()
        with self.assertRaises(qubes.exc.QubesValueError):
            vol.encrypted = True

    def test_004_reject_readonly(self):
        vol = self._private_volume(rw=False)
        with self.assertRaises(qubes.exc.QubesValueError):
            vol.encrypted = True

    def test_005_reject_snap_on_start(self):
        template_vm = qubes.tests.storage.TestTemplateVM(self)
        src_config = {
            "name": "root",
            "rw": True,
            "save_on_stop": True,
            "size": defaults["root_img_size"],
        }
        src = self.pool.init_volume(template_vm, src_config)
        vm = qubes.tests.storage.TestVM(self, template=template_vm)
        snap = self.pool.init_volume(
            vm,
            {
                "name": "root",
                "rw": True,
                "snap_on_start": True,
                "source": src,
                "size": defaults["root_img_size"],
            },
        )
        with self.assertRaises(qubes.exc.QubesValueError):
            snap.encrypted = True

    def test_006_mutex_with_ephemeral(self):
        vol = self._volatile_volume()
        vol.ephemeral = True
        with self.assertRaises(qubes.exc.QubesValueError):
            vol.encrypted = True

        priv = self._private_volume()
        priv.encrypted = True
        with self.assertRaises(qubes.exc.QubesValueError):
            priv.ephemeral = True

    def test_007_cannot_disable(self):
        vol = self._private_volume()
        vol.encrypted = True
        with self.assertRaises(qubes.exc.QubesValueError):
            vol.encrypted = False

    def test_008_config_has_no_passphrase(self):
        vol = self._private_volume(encrypted=True)
        vol.set_passphrase(b"secret-pass")
        self.assertNotIn("passphrase", vol.config)
        xml = vol.__xml__()
        self.assertIsNone(xml.get("passphrase"))
        self.assertEqual(xml.get("encrypted"), "True")


class TC_01_Passphrase(_EncryptTestCase):
    """In-memory passphrase handling."""

    def test_000_set_and_clear(self):
        vol = self._private_volume()
        self.assertFalse(vol.has_passphrase())
        vol.set_passphrase(b"s3cret")
        self.assertTrue(vol.has_passphrase())
        self.assertEqual(bytes(vol._passphrase), b"s3cret")
        vol.clear_passphrase()
        self.assertFalse(vol.has_passphrase())
        self.assertIsNone(vol._passphrase)

    def test_001_clear_overwrites_buffer(self):
        vol = self._private_volume()
        vol.set_passphrase(b"s3cret")
        buf = vol._passphrase
        vol.clear_passphrase()
        self.assertEqual(buf, bytearray(len(buf)))

    def test_002_reject_empty(self):
        vol = self._private_volume()
        with self.assertRaises(qubes.exc.QubesValueError):
            vol.set_passphrase(b"")

    def test_003_reject_newline(self):
        vol = self._private_volume()
        with self.assertRaises(qubes.exc.QubesValueError):
            vol.set_passphrase(b"foo\nbar")

    def test_004_accept_str(self):
        vol = self._private_volume()
        vol.set_passphrase("s3cret")
        self.assertEqual(bytes(vol._passphrase), b"s3cret")

    def test_005_reject_too_long(self):
        vol = self._private_volume()
        with self.assertRaises(qubes.exc.QubesValueError):
            vol.set_passphrase(b"x" * (qubes.storage.LUKS_PASSPHRASE_MAX + 1))


class TC_02_LuksMethods(_EncryptTestCase):
    """setup_luks / start_luks / stop_luks / change_passphrase."""

    def setUp(self):
        super().setUp()
        self.cryptsetup_patch = unittest.mock.patch(
            "qubes.utils.cryptsetup", new_callable=unittest.mock.AsyncMock
        )
        self.mock_cryptsetup = self.cryptsetup_patch.start()

    def tearDown(self):
        self.cryptsetup_patch.stop()
        super().tearDown()

    def _created_volume(self):
        vol = self._private_volume()
        os.makedirs(os.path.dirname(vol.path), exist_ok=True)
        self.loop.run_until_complete(qubes.utils.coro_maybe(vol.create()))
        return vol

    def test_000_setup_luks_formats_empty(self):
        vol = self._created_volume()
        vol.set_passphrase(b"s3cret")
        self.mock_cryptsetup.side_effect = [
            subprocess.CalledProcessError(1, "isLuks"),
            None,
        ]
        self.loop.run_until_complete(vol.setup_luks())
        self.assertGreaterEqual(self.mock_cryptsetup.call_count, 2)
        args = self.mock_cryptsetup.call_args_list[-1][0]
        self.assertIn("luksFormat", args)
        self.assertIn("--type=luks2", args)
        self.assertIn("--key-file=-", args)
        self.assertEqual(
            self.mock_cryptsetup.call_args_list[-1][1]["passphrase"],
            vol._passphrase,
        )

    def test_001_setup_luks_requires_passphrase(self):
        vol = self._created_volume()
        with self.assertRaises(StoragePoolException) as ctx:
            self.loop.run_until_complete(vol.setup_luks())
        self.assertIn("Passphrase required", str(ctx.exception))
        self.mock_cryptsetup.assert_not_called()

    def test_002_setup_luks_skips_if_already_luks(self):
        vol = self._created_volume()
        vol.set_passphrase(b"s3cret")
        self.mock_cryptsetup.return_value = None  # isLuks succeeds
        self.loop.run_until_complete(vol.setup_luks())
        # only isLuks, no luksFormat
        self.assertEqual(self.mock_cryptsetup.call_count, 1)
        self.assertIn("isLuks", self.mock_cryptsetup.call_args[0])

    def test_003_setup_luks_reencrypts_existing_data(self):
        vol = self._created_volume()
        # write some non-zero data so _volume_has_data() is True
        with open(vol.path, "r+b") as fh:
            fh.write(b"filesystem-superblock")
        vol.set_passphrase(b"s3cret")
        orig_size = vol.size

        def fake_resize(size):
            vol._size = size
            with open(vol.path, "r+b") as fh:
                fh.truncate(size)

        vol.resize = fake_resize

        async def cryptsetup_side(*args, **kwargs):
            if "isLuks" in args:
                raise subprocess.CalledProcessError(1, "isLuks")
            return None

        self.mock_cryptsetup.side_effect = cryptsetup_side
        self.loop.run_until_complete(vol.setup_luks())
        called = [c[0] for c in self.mock_cryptsetup.call_args_list]
        self.assertTrue(any("reencrypt" in c for c in called))
        self.assertTrue(any("--encrypt" in c for c in called))
        self.assertTrue(any("--reduce-device-size=32M" in c for c in called))
        self.assertEqual(vol.size, orig_size + qubes.storage.LUKS2_HEADER_SIZE)

    def test_004_start_luks_opens_and_wipes_passphrase(self):
        vol = self._created_volume()
        vol.set_passphrase(b"s3cret")
        vol.start = unittest.mock.AsyncMock()
        vol.block_device = unittest.mock.Mock(
            return_value=qubes.storage.BlockDevice(
                vol.path, vol.name, None, True, None, "disk"
            )
        )
        mapper = vol.encrypted_volume_path("test-vm", "private")

        async def cryptsetup_side(*args, **kwargs):
            if "isLuks" in args:
                return None
            return None

        self.mock_cryptsetup.side_effect = cryptsetup_side
        self.loop.run_until_complete(vol.start_luks(mapper))
        vol.start.assert_called_once_with()
        opened = [
            c for c in self.mock_cryptsetup.call_args_list if "open" in c[0]
        ]
        self.assertTrue(opened)
        self.assertIn("--type=luks2", opened[0][0])
        resized = [
            c for c in self.mock_cryptsetup.call_args_list if "resize" in c[0]
        ]
        self.assertTrue(resized, "start_luks must cryptsetup resize after open")
        self.assertFalse(vol.has_passphrase())

    def test_005_start_luks_requires_passphrase(self):
        vol = self._created_volume()
        mapper = vol.encrypted_volume_path("test-vm", "private")
        with self.assertRaises(StoragePoolException) as ctx:
            self.loop.run_until_complete(vol.start_luks(mapper))
        self.assertIn("Passphrase required", str(ctx.exception))

    def test_006_stop_luks_closes(self):
        vol = self._created_volume()
        vol.stop = unittest.mock.AsyncMock()
        mapper = "/dev/mapper/vm-test-luks@private"
        with unittest.mock.patch("os.path.exists", return_value=True):
            self.loop.run_until_complete(vol.stop_luks(mapper))
        self.mock_cryptsetup.assert_called()
        self.assertIn("close", self.mock_cryptsetup.call_args[0])
        vol.stop.assert_called_once_with()

    def test_007_change_passphrase(self):
        vol = self._created_volume()
        vol.set_passphrase(b"oldpass")
        change = unittest.mock.AsyncMock()
        with unittest.mock.patch(
            "qubes.utils.cryptsetup_change_key", change
        ), unittest.mock.patch.object(
            vol, "is_luks", new=unittest.mock.AsyncMock(return_value=True)
        ):
            self.loop.run_until_complete(
                vol.change_passphrase(b"oldpass", b"newpass")
            )
        change.assert_called_once()
        self.assertEqual(bytes(vol._passphrase), b"newpass")

    def test_008_setup_luks_refuses_dirty(self):
        vol = self._created_volume()
        vol.set_passphrase(b"s3cret")
        vol.is_dirty = lambda: True

        async def cryptsetup_side(*args, **kwargs):
            if "isLuks" in args:
                raise subprocess.CalledProcessError(1, "isLuks")
            return None

        self.mock_cryptsetup.side_effect = cryptsetup_side
        with self.assertRaises(StoragePoolException) as ctx:
            self.loop.run_until_complete(vol.setup_luks())
        self.assertIn("dirty", str(ctx.exception).lower())
        called = [c[0] for c in self.mock_cryptsetup.call_args_list]
        self.assertFalse(
            any("luksFormat" in c or "reencrypt" in c for c in called)
        )

    def test_009_setup_luks_refuses_revisions(self):
        vol = self._created_volume()
        vol.set_passphrase(b"s3cret")
        os.makedirs(os.path.dirname(vol.path_cow), exist_ok=True)
        with open(vol.path_cow + ".old", "wb") as fh:
            fh.write(b"previous-revision")

        async def cryptsetup_side(*args, **kwargs):
            if "isLuks" in args:
                raise subprocess.CalledProcessError(1, "isLuks")
            return None

        self.mock_cryptsetup.side_effect = cryptsetup_side
        with self.assertRaises(StoragePoolException) as ctx:
            self.loop.run_until_complete(vol.setup_luks())
        self.assertIn("revision", str(ctx.exception).lower())
        called = [c[0] for c in self.mock_cryptsetup.call_args_list]
        self.assertFalse(
            any("luksFormat" in c or "reencrypt" in c for c in called)
        )

    def test_010_setup_luks_discards_clean_cow(self):
        vol = self._created_volume()
        with open(vol.path, "r+b") as fh:
            fh.write(b"filesystem-superblock")
        os.makedirs(os.path.dirname(vol.path_cow), exist_ok=True)
        with open(vol.path_cow, "wb"):
            pass
        vol.is_dirty = lambda: False
        vol.set_passphrase(b"s3cret")

        def fake_resize(size):
            vol._size = size
            with open(vol.path, "r+b") as fh:
                fh.truncate(size)

        vol.resize = fake_resize

        async def cryptsetup_side(*args, **kwargs):
            if "isLuks" in args:
                raise subprocess.CalledProcessError(1, "isLuks")
            return None

        self.mock_cryptsetup.side_effect = cryptsetup_side
        self.loop.run_until_complete(vol.setup_luks())
        self.assertFalse(os.path.exists(vol.path_cow))

    def test_011_start_luks_does_not_format(self):
        vol = self._created_volume()
        vol.set_passphrase(b"s3cret")
        vol.start = unittest.mock.AsyncMock()
        mapper = vol.encrypted_volume_path("test-vm", "private")

        async def cryptsetup_side(*args, **kwargs):
            if "isLuks" in args:
                raise subprocess.CalledProcessError(1, "isLuks")
            return None

        self.mock_cryptsetup.side_effect = cryptsetup_side
        with self.assertRaises(StoragePoolException) as ctx:
            self.loop.run_until_complete(vol.start_luks(mapper))
        self.assertIn("not LUKS formatted", str(ctx.exception))
        vol.start.assert_not_called()
        called = [c[0] for c in self.mock_cryptsetup.call_args_list]
        self.assertFalse(
            any("luksFormat" in c or "reencrypt" in c for c in called)
        )

    def test_013_start_luks_open_failure_rolls_back_and_retries(self):
        vol = self._created_volume()
        vol.set_passphrase(b"s3cret")
        vol.start = unittest.mock.AsyncMock()
        vol.stop = unittest.mock.AsyncMock()
        vol.block_device = unittest.mock.Mock(
            return_value=qubes.storage.BlockDevice(
                vol.path, vol.name, None, True, None, "disk"
            )
        )
        mapper = vol.encrypted_volume_path("test-vm", "private")
        opens = {"n": 0}

        async def cryptsetup_side(*args, **kwargs):
            if "isLuks" in args:
                return None
            if "open" in args:
                opens["n"] += 1
                if opens["n"] == 1:
                    raise subprocess.CalledProcessError(1, "open")
            return None

        self.mock_cryptsetup.side_effect = cryptsetup_side
        with self.assertRaises(StoragePoolException) as ctx:
            self.loop.run_until_complete(vol.start_luks(mapper))
        self.assertIn("Failed to unlock", str(ctx.exception))
        vol.start.assert_called_once_with()
        vol.stop.assert_called_once_with()
        self.assertTrue(vol.has_passphrase())
        self.assertEqual(bytes(vol._passphrase), b"s3cret")

        self.loop.run_until_complete(vol.start_luks(mapper))
        self.assertEqual(vol.start.call_count, 2)
        self.assertEqual(vol.stop.call_count, 1)
        self.assertFalse(vol.has_passphrase())

    def test_012_failed_reencrypt_keeps_encrypted_flag(self):
        vol = self._created_volume()
        with open(vol.path, "r+b") as fh:
            fh.write(b"filesystem-superblock")
        vol.set_passphrase(b"s3cret")
        self.assertFalse(vol.encrypted)

        def fake_resize(size):
            vol._size = size

        vol.resize = fake_resize

        async def cryptsetup_side(*args, **kwargs):
            if "isLuks" in args:
                raise subprocess.CalledProcessError(1, "isLuks")
            if "reencrypt" in args:
                raise subprocess.CalledProcessError(1, "reencrypt")
            return None

        self.mock_cryptsetup.side_effect = cryptsetup_side
        with self.assertRaises(subprocess.CalledProcessError):
            self.loop.run_until_complete(vol.setup_luks())
        self.assertTrue(vol.encrypted)
        self.assertTrue(vol._luks_device_mutated)

    def test_014_header_size_constant(self):
        self.assertEqual(qubes.storage.LUKS2_HEADER_SIZE, 32 << 20)
        self.assertEqual(
            "--reduce-device-size={}M".format(
                qubes.storage.LUKS2_HEADER_SIZE >> 20
            ),
            "--reduce-device-size=32M",
        )

    def test_015_start_luks_warns_on_stale_mapper(self):
        vol = self._created_volume()
        vol.set_passphrase(b"s3cret")
        vol.start = unittest.mock.AsyncMock()
        vol.block_device = unittest.mock.Mock(
            return_value=qubes.storage.BlockDevice(
                vol.path, vol.name, None, True, None, "disk"
            )
        )
        mapper = vol.encrypted_volume_path("test-vm", "private")
        seen = {"first": True}
        real_exists = os.path.exists

        def exists(path):
            if path == mapper and seen["first"]:
                seen["first"] = False
                return True
            return real_exists(path)

        async def cryptsetup_side(*args, **kwargs):
            if "isLuks" in args:
                return None
            return None

        self.mock_cryptsetup.side_effect = cryptsetup_side
        with unittest.mock.patch("os.path.exists", side_effect=exists):
            with self.assertLogs("qubes.storage", level="WARNING") as log:
                self.loop.run_until_complete(vol.start_luks(mapper))
        self.assertTrue(
            any("leftover LUKS mapping" in line for line in log.output)
        )
        closed = [
            c for c in self.mock_cryptsetup.call_args_list if "close" in c[0]
        ]
        self.assertTrue(closed)


class TC_03_StorageStartStop(_EncryptTestCase):
    """Storage.start / stop / create / block_devices for encrypted volumes."""

    def _storage_with(self, vol):
        vm = vol.pool  # unused; rebuild a TestVM
        vm = qubes.tests.storage.TestVM(self)
        vm.volumes = {vol.name: vol}
        # Storage.import_volume fires domain-import-volume on the VM.
        vm.fire_event_async = unittest.mock.AsyncMock()
        return qubes.storage.Storage(vm), vm

    def test_000_start_calls_start_luks(self):
        vol = self._private_volume(encrypted=True)
        vol.set_passphrase(b"s3cret")
        vol.start_luks = unittest.mock.AsyncMock()
        vol.start_encrypted = unittest.mock.AsyncMock()
        vol.start = unittest.mock.AsyncMock()
        storage, vm = self._storage_with(vol)
        state_dir = os.path.join(self.tmpdir, "run")
        os.makedirs(state_dir)
        with unittest.mock.patch("qubes.storage.VOLUME_STATE_DIR", state_dir):
            self.loop.run_until_complete(storage.start())
        vol.start_luks.assert_called_once()
        vol.start.assert_not_called()
        vol.start_encrypted.assert_not_called()

    def test_001_start_raises_without_passphrase(self):
        vol = self._private_volume(encrypted=True)
        storage, _vm = self._storage_with(vol)
        with self.assertRaises(StoragePoolException) as ctx:
            self.loop.run_until_complete(storage.start())
        self.assertIn("Passphrase required", str(ctx.exception))

    def test_002_stop_calls_stop_luks(self):
        vol = self._private_volume(encrypted=True)
        vol.stop_luks = unittest.mock.AsyncMock()
        vol.stop = unittest.mock.AsyncMock()
        storage, _vm = self._storage_with(vol)
        state_dir = os.path.join(self.tmpdir, "run")
        os.makedirs(state_dir)
        with unittest.mock.patch("qubes.storage.VOLUME_STATE_DIR", state_dir):
            self.loop.run_until_complete(storage.stop())
        vol.stop_luks.assert_called_once()
        vol.stop.assert_not_called()

    def test_003_start_plain_still_works(self):
        vol = self._private_volume()
        vol.start = unittest.mock.AsyncMock()
        vol.start_luks = unittest.mock.AsyncMock()
        storage, _vm = self._storage_with(vol)
        state_dir = os.path.join(self.tmpdir, "run")
        os.makedirs(state_dir)
        with unittest.mock.patch("qubes.storage.VOLUME_STATE_DIR", state_dir):
            self.loop.run_until_complete(storage.start())
        vol.start.assert_called_once()
        vol.start_luks.assert_not_called()

    def test_004_start_ephemeral_still_works(self):
        vol = self._volatile_volume()
        vol.ephemeral = True
        vol.start_encrypted = unittest.mock.AsyncMock()
        vol.start_luks = unittest.mock.AsyncMock()
        storage, _vm = self._storage_with(vol)
        state_dir = os.path.join(self.tmpdir, "run")
        os.makedirs(state_dir)
        with unittest.mock.patch("qubes.storage.VOLUME_STATE_DIR", state_dir):
            self.loop.run_until_complete(storage.start())
        vol.start_encrypted.assert_called_once()
        vol.start_luks.assert_not_called()

    def test_005_create_calls_setup_luks(self):
        vol = self._private_volume(encrypted=True)
        vol.set_passphrase(b"s3cret")
        vol.create = unittest.mock.AsyncMock()
        vol.setup_luks = unittest.mock.AsyncMock()
        storage, _vm = self._storage_with(vol)
        self.loop.run_until_complete(storage.create())
        vol.create.assert_called_once()
        vol.setup_luks.assert_called_once()

    def test_006_block_devices_uses_mapper(self):
        vol = self._private_volume(encrypted=True)
        os.makedirs(os.path.dirname(vol.path), exist_ok=True)
        self.loop.run_until_complete(qubes.utils.coro_maybe(vol.create()))
        storage, vm = self._storage_with(vol)
        devices = list(storage.block_devices())
        self.assertEqual(len(devices), 1)
        self.assertTrue(devices[0].path.startswith("/dev/mapper/"))

    def test_007_passphrase_event_then_retry(self):
        vol = self._private_volume(encrypted=True)
        vol.start_luks = unittest.mock.AsyncMock()
        storage, vm = self._storage_with(vol)

        async def provide_passphrase(event, **kwargs):
            self.assertEqual(event, "domain-passphrase-required")
            self.assertEqual(kwargs["volumes"], ["private"])
            vol.set_passphrase(b"s3cret")

        vm.fire_event_async = provide_passphrase
        state_dir = os.path.join(self.tmpdir, "run")
        os.makedirs(state_dir)
        with unittest.mock.patch("qubes.storage.VOLUME_STATE_DIR", state_dir):
            self.loop.run_until_complete(storage.start())
        vol.start_luks.assert_called_once()


class TC_04_PassphraseBytes(_EncryptTestCase):
    def test_000_no_extra_newline(self):
        self.assertEqual(qubes.utils._passphrase_bytes(b"s3cret"), b"s3cret")
        self.assertEqual(qubes.utils._passphrase_bytes("s3cret"), b"s3cret")
        self.assertEqual(
            qubes.utils._passphrase_bytes(bytearray(b"s3cret")), b"s3cret"
        )


class TC_05_SnapshotSource(_EncryptTestCase):
    def test_000_init_rejects_encrypted_source(self):
        src = self._private_volume(encrypted=True)
        vm = qubes.tests.storage.TestVM(self)
        with self.assertRaises(StoragePoolException) as ctx:
            self.pool.init_volume(
                vm,
                {
                    "name": "root",
                    "rw": True,
                    "snap_on_start": True,
                    "source": src,
                    "size": defaults["root_img_size"],
                },
            )
        self.assertIn("encrypted source", str(ctx.exception))

    def test_001_consumers_use_equality_not_identity(self):
        src = self._private_volume()
        other_vm = qubes.tests.storage.TestVM(self)
        src_alias = self.pool.init_volume(
            other_vm,
            {
                "name": "private",
                "rw": True,
                "save_on_stop": True,
                "vid": src.vid,
                "size": defaults["private_img_size"],
            },
        )
        self.assertEqual(src, src_alias)
        self.assertIsNot(src, src_alias)

        child_vm = qubes.tests.storage.TestVM(self)
        child = self.pool.init_volume(
            child_vm,
            {
                "name": "root",
                "rw": True,
                "snap_on_start": True,
                "source": src_alias,
                "size": defaults["private_img_size"],
            },
        )
        child_vm.volumes = {"root": child}

        class _App:
            domains = [child_vm]

        found = list(qubes.storage.snapshot_consumers(_App(), src))
        self.assertEqual(len(found), 1)
        self.assertIs(found[0][1], child)


class TC_06_ImportAndCreate(_EncryptTestCase):
    def test_000_import_encrypted_marks_dest(self):
        src = self._private_volume(encrypted=True)
        dst = self._private_volume()
        self.assertFalse(dst.encrypted)
        dst.import_volume = unittest.mock.AsyncMock(return_value=dst)
        src.is_running = lambda: False
        storage, vm = TC_03_StorageStartStop._storage_with(self, dst)
        self.loop.run_until_complete(storage.import_volume(dst, src))
        self.assertTrue(dst.encrypted)
        dst.import_volume.assert_called_once_with(src)
        vm.fire_event_async.assert_awaited_once_with(
            "domain-import-volume", name=dst.name, source=src
        )

    def test_001_import_plaintext_into_encrypted_refused(self):
        src = self._private_volume()
        dst = self._private_volume(encrypted=True)
        dst.import_volume = unittest.mock.AsyncMock()
        src.is_running = lambda: False
        storage, _vm = TC_03_StorageStartStop._storage_with(self, dst)
        with self.assertRaises(StoragePoolException) as ctx:
            self.loop.run_until_complete(storage.import_volume(dst, src))
        self.assertIn("unencrypted", str(ctx.exception))
        dst.import_volume.assert_not_called()

    def test_002_import_encrypted_into_ineligible_dest_refused(self):
        src = self._private_volume(encrypted=True)
        dst = self._volatile_volume()
        dst.import_volume = unittest.mock.AsyncMock()
        src.is_running = lambda: False
        storage, _vm = TC_03_StorageStartStop._storage_with(self, dst)
        with self.assertRaises(qubes.exc.QubesValueError):
            self.loop.run_until_complete(storage.import_volume(dst, src))
        dst.import_volume.assert_not_called()

    def test_003_create_requires_passphrase_before_create(self):
        vol = self._private_volume(encrypted=True)
        vol.create = unittest.mock.AsyncMock()
        vol.setup_luks = unittest.mock.AsyncMock()
        storage, _vm = TC_03_StorageStartStop._storage_with(self, vol)
        with self.assertRaises(StoragePoolException) as ctx:
            self.loop.run_until_complete(storage.create())
        self.assertIn("Passphrase required", str(ctx.exception))
        vol.create.assert_not_called()
        vol.setup_luks.assert_not_called()

    def test_004_import_data_end_reformats_encrypted(self):
        vol = self._private_volume(encrypted=True)
        vol.set_passphrase(b"s3cret")
        vol.import_data_end = unittest.mock.AsyncMock(return_value=vol)
        vol.setup_luks = unittest.mock.AsyncMock()
        storage, _vm = TC_03_StorageStartStop._storage_with(self, vol)
        self.loop.run_until_complete(storage.import_data_end(vol, True))
        vol.setup_luks.assert_called_once_with()

    def test_005_import_data_end_requires_passphrase(self):
        vol = self._private_volume(encrypted=True)
        vol.import_data_end = unittest.mock.AsyncMock(return_value=vol)
        vol.setup_luks = unittest.mock.AsyncMock()
        storage, _vm = TC_03_StorageStartStop._storage_with(self, vol)
        with self.assertRaises(StoragePoolException):
            self.loop.run_until_complete(storage.import_data_end(vol, True))
        vol.setup_luks.assert_not_called()

    def test_006_zfs_like_path_uses_block_device(self):
        class ZLike(qubes.storage.Volume):
            path = None

            def block_device(self):
                return qubes.storage.BlockDevice(
                    "/dev/zvol/tank/vm-private",
                    "private",
                    None,
                    True,
                    None,
                    "disk",
                )

        vol = ZLike(
            "private",
            self.pool,
            "zvol-vid",
            rw=True,
            save_on_stop=True,
            size=1024,
        )
        self.assertEqual(vol._luks_backend_path(), "/dev/zvol/tank/vm-private")
