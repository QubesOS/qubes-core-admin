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
import qubes.storage.callback
import qubes.storage.file
import qubes.storage.zfs
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
        self.assertNotIn("luks_needs_zero", vol.config)

    def test_009_config_persists_needs_zero(self):
        vol = self._private_volume(encrypted=True, luks_needs_zero=True)
        self.assertTrue(vol._luks_needs_zero)
        self.assertTrue(vol.config["luks_needs_zero"])
        xml = vol.__xml__()
        self.assertEqual(xml.get("luks_needs_zero"), "True")
        vol._luks_needs_zero = False
        self.assertNotIn("luks_needs_zero", vol.config)

    def test_010_config_persists_guest_size(self):
        orig = 2 << 20
        backing = orig + qubes.storage.LUKS2_HEADER_SIZE
        vol = self._private_volume(
            size=backing,
            encrypted=True,
            luks_needs_zero=True,
            luks_guest_size=orig,
        )
        self.assertEqual(vol._luks_guest_size(), orig)
        self.assertEqual(vol.config["luks_guest_size"], orig)
        xml = vol.__xml__()
        self.assertEqual(int(xml.get("luks_guest_size")), orig)
        reloaded = self._private_volume(**vol.config)
        self.assertEqual(reloaded._luks_guest_size(), orig)
        self.assertTrue(reloaded._luks_needs_zero)


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

    def _patch_zero_mapper(self, leftover=False, appear=True):
        """Control when the temp zero mapper node is visible.

        *leftover*: node exists before ``cryptsetup open`` (stale mapping).
        *appear*: node exists after ``open`` so ``_wait_for_mapper`` succeeds.
        """
        real_exists = os.path.exists

        def fake_exists(path):
            if isinstance(path, str) and "luks-zero-" in path:
                called = self.mock_cryptsetup.call_args_list
                opened = any("open" in c[0] for c in called)
                closed_n = sum(1 for c in called if "close" in c[0])
                if leftover and closed_n == 0:
                    return True
                if not appear:
                    return False
                return opened
            return real_exists(path)

        return unittest.mock.patch(
            "os.path.exists", side_effect=fake_exists
        ), unittest.mock.patch(
            "qubes.utils.run_program", new_callable=unittest.mock.AsyncMock
        )

    def _assert_zero_write(self, vol, mock_dd, orig_size):
        mapper = vol._luks_zero_mapper_name()
        mapper_path = "/dev/mapper/" + mapper
        dd_calls = [
            c for c in mock_dd.call_args_list if c[0] and c[0][0] == "dd"
        ]
        self.assertEqual(len(dd_calls), 1)
        dd_args = dd_calls[0][0]
        self.assertIn("if=/dev/zero", dd_args)
        self.assertIn("of=" + mapper_path, dd_args)
        self.assertIn("count=1", dd_args)
        self.assertIn("status=none", dd_args)
        self.assertIn("conv=fsync,notrunc", dd_args)
        zero_len = min(orig_size, qubes.storage.LUKS2_ZERO_PAYLOAD)
        self.assertIn("bs=" + str(zero_len), dd_args)
        self.assertTrue(dd_calls[0][1].get("sudo"))
        open_calls = [
            c
            for c in self.mock_cryptsetup.call_args_list
            if c[0] and "open" in c[0]
        ]
        self.assertTrue(open_calls)
        opened = open_calls[0][0]
        self.assertIn("--batch-mode", opened)
        self.assertIn("--type=luks2", opened)
        self.assertIn("--key-file=-", opened)
        self.assertIn(mapper, opened)
        self.assertIn(vol.luks_backend_path(), opened)
        self.assertIsNotNone(open_calls[0][1].get("passphrase"))
        if vol.has_passphrase():
            self.assertEqual(open_calls[0][1]["passphrase"], vol._passphrase)
        called = [c[0] for c in self.mock_cryptsetup.call_args_list]
        closed = [c for c in called if "close" in c]
        self.assertTrue(closed)
        self.assertIn("--batch-mode", closed[-1])
        self.assertIn(mapper, closed[-1])

    def test_000_setup_luks_formats_empty(self):
        vol = self._created_volume()
        vol.set_passphrase(b"s3cret")
        orig_size = vol.size
        resized = []

        def fake_resize(size):
            resized.append(size)
            vol._size = size
            with open(vol.path, "r+b") as fh:
                fh.truncate(size)

        vol.resize = fake_resize
        self.mock_cryptsetup.side_effect = [
            subprocess.CalledProcessError(1, "isLuks"),
            None,
            None,
            None,
            None,
        ]
        exists_p, dd_p = self._patch_zero_mapper()
        with exists_p, dd_p as mock_dd:
            self.loop.run_until_complete(vol.setup_luks())
        called = [c[0] for c in self.mock_cryptsetup.call_args_list]
        formatted = [c for c in called if "luksFormat" in c]
        self.assertTrue(formatted)
        args = formatted[0]
        self.assertIn("--type=luks2", args)
        self.assertIn("--key-file=-", args)
        self.assertIn(
            "--offset={}".format(qubes.storage.LUKS2_DATA_OFFSET_SECTORS),
            args,
        )
        self.assertNotIn("reencrypt", args)
        self._assert_zero_write(vol, mock_dd, orig_size)
        self.assertFalse(vol._luks_needs_zero)
        self.assertEqual(resized, [orig_size + qubes.storage.LUKS2_HEADER_SIZE])
        self.assertEqual(vol.size, orig_size + qubes.storage.LUKS2_HEADER_SIZE)
        fmt_call = next(
            c
            for c in self.mock_cryptsetup.call_args_list
            if "luksFormat" in c[0]
        )
        self.assertEqual(fmt_call[1]["passphrase"], vol._passphrase)

    def test_000c_setup_luks_keeps_needs_zero_if_close_fails(self):
        vol = self._created_volume()
        vol.set_passphrase(b"s3cret")

        def fake_resize(size):
            vol._size = size
            with open(vol.path, "r+b") as fh:
                fh.truncate(size)

        vol.resize = fake_resize

        closes = {"n": 0}

        async def cryptsetup_side(*args, **kwargs):
            if "isLuks" in args:
                raise subprocess.CalledProcessError(1, "isLuks")
            if "close" in args:
                closes["n"] += 1
                if closes["n"] > 1:
                    raise subprocess.CalledProcessError(1, "close")
            return None

        self.mock_cryptsetup.side_effect = cryptsetup_side
        exists_p, dd_p = self._patch_zero_mapper(leftover=True)
        with exists_p, dd_p as mock_dd, unittest.mock.patch(
            "asyncio.sleep", new_callable=unittest.mock.AsyncMock
        ), self.assertRaises(subprocess.CalledProcessError):
            self.loop.run_until_complete(vol.setup_luks())
        called = [c[0] for c in self.mock_cryptsetup.call_args_list]
        close_i = next(i for i, c in enumerate(called) if "close" in c)
        open_i = next(i for i, c in enumerate(called) if "open" in c)
        self.assertLess(close_i, open_i)
        dd_calls = [
            c for c in mock_dd.call_args_list if c[0] and c[0][0] == "dd"
        ]
        self.assertEqual(len(dd_calls), 1)
        self.assertGreater(closes["n"], 1)
        self.assertTrue(vol._luks_needs_zero)

    def test_000b_setup_luks_raises_if_zero_mapper_missing(self):
        vol = self._created_volume()
        vol.set_passphrase(b"s3cret")

        def fake_resize(size):
            vol._size = size
            with open(vol.path, "r+b") as fh:
                fh.truncate(size)

        vol.resize = fake_resize
        self.mock_cryptsetup.side_effect = [
            subprocess.CalledProcessError(1, "isLuks"),
            None,
            None,
            None,
        ]
        exists_p, dd_p = self._patch_zero_mapper(appear=False)
        with exists_p, dd_p as mock_dd, unittest.mock.patch(
            "asyncio.sleep", new_callable=unittest.mock.AsyncMock
        ), self.assertRaises(StoragePoolException) as ctx:
            self.loop.run_until_complete(vol.setup_luks())
        self.assertIn("did not appear", str(ctx.exception))
        self.assertTrue(vol._luks_needs_zero)
        mock_dd.assert_not_called()
        called = [c[0] for c in self.mock_cryptsetup.call_args_list]
        opened = [c for c in called if "open" in c]
        closed = [c for c in called if "close" in c]
        self.assertTrue(opened)
        self.assertTrue(closed)
        self.assertIn(vol._luks_zero_mapper_name(), opened[0])
        self.assertIn("--batch-mode", closed[-1])
        self.assertIn(vol._luks_zero_mapper_name(), closed[-1])
        open_i = next(i for i, c in enumerate(called) if "open" in c)
        close_i = next(i for i, c in enumerate(called) if "close" in c)
        self.assertLess(open_i, close_i)

    def test_000d_setup_luks_zeros_as_root(self):
        vol = self._created_volume()
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
        mapper_path = "/dev/mapper/" + vol._luks_zero_mapper_name()
        real_open = open
        mock_fh = unittest.mock.MagicMock()
        mock_fh.__enter__.return_value = mock_fh
        mock_fh.__exit__.return_value = False
        mock_fh.fileno.return_value = 3

        def selective_open(path, mode="r", *args, **kwargs):
            if path == mapper_path:
                self.assertEqual(mode, "r+b")
                return mock_fh
            return real_open(path, mode, *args, **kwargs)

        exists_p, dd_p = self._patch_zero_mapper()
        with exists_p, dd_p as mock_dd, unittest.mock.patch(
            "qubes.storage._am_root", True
        ), unittest.mock.patch(
            "builtins.open", side_effect=selective_open
        ), unittest.mock.patch(
            "os.fsync"
        ) as mock_fsync:
            self.loop.run_until_complete(vol.setup_luks())
        mock_dd.assert_not_called()
        mock_fh.write.assert_called()
        mock_fh.flush.assert_called()
        mock_fsync.assert_called()
        zero_len = min(orig_size, qubes.storage.LUKS2_ZERO_PAYLOAD)
        written = sum(len(c[0][0]) for c in mock_fh.write.call_args_list)
        self.assertEqual(written, zero_len)
        self.assertFalse(vol._luks_needs_zero)

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

    def test_002b_setup_luks_retries_zero_if_needed(self):
        vol = self._created_volume()
        vol.set_passphrase(b"s3cret")
        vol._luks_needs_zero = True
        self.mock_cryptsetup.return_value = None
        exists_p, dd_p = self._patch_zero_mapper()
        with exists_p, dd_p as mock_dd:
            self.loop.run_until_complete(vol.setup_luks())
        called = [c[0] for c in self.mock_cryptsetup.call_args_list]
        self.assertFalse(any("luksFormat" in c for c in called))
        self.assertIn("isLuks", called[0])
        self._assert_zero_write(vol, mock_dd, vol._configured_size)
        self.assertFalse(vol._luks_needs_zero)

    def test_003_setup_luks_reencrypts_existing_data(self):
        vol = self._created_volume()
        # write some non-zero data so _volume_has_data() is True
        with open(vol.path, "r+b") as fh:
            fh.write(b"filesystem-superblock")
        vol.set_passphrase(b"s3cret")
        orig_size = vol.size
        resized = []

        def fake_resize(size):
            resized.append(size)
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
        self.assertTrue(any("--reduce-device-size=64M" in c for c in called))
        self.assertTrue(
            any(
                "--offset={}".format(qubes.storage.LUKS2_DATA_OFFSET_SECTORS)
                in c
                for c in called
            )
        )
        self.assertTrue(any("--force-offline-reencrypt" in c for c in called))
        self.assertFalse(any("--reduce-device-size=32M" in c for c in called))
        self.assertEqual(
            resized,
            [
                orig_size + qubes.storage.LUKS2_REENCRYPT_WORKSPACE,
                orig_size + qubes.storage.LUKS2_HEADER_SIZE,
            ],
        )
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
        self.assertIn("--allow-discards", opened[0][0])
        resized = [
            c for c in self.mock_cryptsetup.call_args_list if "resize" in c[0]
        ]
        self.assertFalse(
            resized,
            "start_luks must not cryptsetup resize after open",
        )
        self.assertFalse(vol.has_passphrase())

    def _reload_from_config(self, vol):
        return self._private_volume(**vol.config)

    def test_004b_start_luks_zeros_if_needed(self):
        orig = 3 << 20
        backing = orig + qubes.storage.LUKS2_HEADER_SIZE
        vol = self._private_volume(
            size=backing,
            encrypted=True,
            luks_needs_zero=True,
            luks_guest_size=orig,
        )
        os.makedirs(os.path.dirname(vol.path), exist_ok=True)
        self.loop.run_until_complete(qubes.utils.coro_maybe(vol.create()))
        self.assertTrue(vol.config["luks_needs_zero"])
        vol = self._reload_from_config(vol)
        vol.set_passphrase(b"s3cret")
        sentinel = os.path.join(self.tmpdir, "luks-origin-sentinel")
        with open(sentinel, "wb"):
            pass
        vol.luks_backend_path = lambda: sentinel
        order = []
        vol.block_device = unittest.mock.Mock(
            return_value=qubes.storage.BlockDevice(
                vol.path, vol.name, None, True, None, "disk"
            )
        )
        mapper = vol.encrypted_volume_path("test-vm", "private")
        self.mock_cryptsetup.return_value = None
        exists_p, dd_p = self._patch_zero_mapper()
        with exists_p, dd_p as mock_dd:

            async def start_side():
                self.assertTrue(mock_dd.call_count)
                order.append("start")

            vol.start = unittest.mock.AsyncMock(side_effect=start_side)
            self.loop.run_until_complete(vol.start_luks(mapper))
        self._assert_zero_write(vol, mock_dd, orig)
        open_calls = [
            c
            for c in self.mock_cryptsetup.call_args_list
            if c[0] and "open" in c[0]
        ]
        self.assertIn(sentinel, open_calls[0][0])
        self.assertNotEqual(sentinel, vol.path)
        self.assertGreaterEqual(len(open_calls), 2)
        vol.start.assert_called_once_with()
        self.assertEqual(order, ["start"])
        self.assertFalse(vol._luks_needs_zero)
        self.assertNotIn("luks_needs_zero", vol.config)
        reloaded = self._reload_from_config(vol)
        self.assertFalse(reloaded._luks_needs_zero)

    def test_004c_start_luks_zeros_persisted_guest_size(self):
        orig = 2 << 20
        backing = orig + qubes.storage.LUKS2_HEADER_SIZE
        vol = self._private_volume(
            size=backing,
            encrypted=True,
            luks_needs_zero=True,
            luks_guest_size=orig,
        )
        os.makedirs(os.path.dirname(vol.path), exist_ok=True)
        self.loop.run_until_complete(qubes.utils.coro_maybe(vol.create()))
        vol = self._reload_from_config(vol)
        self.assertEqual(vol._luks_guest_size(), orig)
        vol.set_passphrase(b"s3cret")
        vol.start = unittest.mock.AsyncMock()
        vol.block_device = unittest.mock.Mock(
            return_value=qubes.storage.BlockDevice(
                vol.path, vol.name, None, True, None, "disk"
            )
        )
        mapper = vol.encrypted_volume_path("test-vm", "private")
        self.mock_cryptsetup.return_value = None
        exists_p, dd_p = self._patch_zero_mapper()
        with exists_p, dd_p as mock_dd:
            self.loop.run_until_complete(vol.start_luks(mapper))
        self._assert_zero_write(vol, mock_dd, orig)
        self.assertFalse(vol._luks_needs_zero)
        self.assertEqual(vol._luks_guest_size(), orig)

    def test_004d_reload_does_not_stack_header(self):
        orig = 2 << 20
        backing = orig + qubes.storage.LUKS2_HEADER_SIZE
        vol = self._private_volume(
            size=backing,
            encrypted=True,
            luks_needs_zero=True,
            luks_guest_size=orig,
        )
        os.makedirs(os.path.dirname(vol.path), exist_ok=True)
        self.loop.run_until_complete(qubes.utils.coro_maybe(vol.create()))
        vol = self._reload_from_config(vol)
        vol.set_passphrase(b"s3cret")
        resized = []

        def fake_resize(size):
            resized.append(size)
            vol._size = size
            with open(vol.path, "r+b") as fh:
                fh.truncate(size)

        vol.resize = fake_resize
        self.mock_cryptsetup.side_effect = [
            subprocess.CalledProcessError(1, "isLuks"),
            None,
            None,
            None,
            None,
        ]
        exists_p, dd_p = self._patch_zero_mapper()
        with exists_p, dd_p as mock_dd:
            self.loop.run_until_complete(vol.setup_luks())
        self.assertEqual(resized, [])
        self._assert_zero_write(vol, mock_dd, orig)
        self.assertEqual(vol.size, backing)
        self.assertFalse(vol._luks_needs_zero)

    def test_004e_drop_tail_does_not_shrink_resized(self):
        orig = 2 << 20
        grown = 2 << 30
        vol = self._private_volume(
            size=grown,
            encrypted=True,
            luks_guest_size=orig,
        )
        os.makedirs(os.path.dirname(vol.path), exist_ok=True)
        self.loop.run_until_complete(qubes.utils.coro_maybe(vol.create()))
        vol = self._reload_from_config(vol)
        self.assertEqual(vol._luks_guest_size(), orig)
        self.assertEqual(vol.config["luks_guest_size"], orig)
        vol.set_passphrase(b"s3cret")
        resized = []

        def fake_resize(size):
            resized.append(size)
            vol._size = size

        vol.resize = fake_resize
        self.mock_cryptsetup.return_value = None
        self.loop.run_until_complete(vol.setup_luks())
        self.assertEqual(resized, [])
        self.assertEqual(vol.size, grown)
        self.assertEqual(vol._luks_guest_size(), orig)

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

    def test_009b_setup_luks_discards_revisions_when_keep_zero(self):
        vol = self._created_volume()
        vol.revisions_to_keep = 0
        vol.set_passphrase(b"s3cret")
        os.makedirs(os.path.dirname(vol.path_cow), exist_ok=True)
        with open(vol.path_cow + ".old", "wb") as fh:
            fh.write(b"previous-revision")
        self.assertTrue(vol.revisions)

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
        exists_p, dd_p = self._patch_zero_mapper()
        with exists_p, dd_p:
            self.loop.run_until_complete(vol.setup_luks())
        self.assertFalse(vol.revisions)
        self.assertFalse(os.path.exists(vol.path_cow + ".old"))
        called = [c[0] for c in self.mock_cryptsetup.call_args_list]
        self.assertTrue(any("luksFormat" in c for c in called))

    def test_009d_setup_luks_aborts_if_revisions_remain(self):
        vol = self._created_volume()
        vol.revisions_to_keep = 0
        vol.set_passphrase(b"s3cret")
        os.makedirs(os.path.dirname(vol.path_cow), exist_ok=True)
        with open(vol.path_cow + ".old", "wb") as fh:
            fh.write(b"previous-revision")
        vol.discard_revisions = lambda: None

        async def cryptsetup_side(*args, **kwargs):
            if "isLuks" in args:
                raise subprocess.CalledProcessError(1, "isLuks")
            return None

        self.mock_cryptsetup.side_effect = cryptsetup_side
        with self.assertRaises(StoragePoolException) as ctx:
            self.loop.run_until_complete(vol.setup_luks())
        self.assertIn("leftover revisions", str(ctx.exception).lower())
        called = [c[0] for c in self.mock_cryptsetup.call_args_list]
        self.assertFalse(
            any("luksFormat" in c or "reencrypt" in c for c in called)
        )

    def test_009e_setup_luks_discards_revisions_when_keep_minus_one(self):
        vol = self._created_volume()
        vol.revisions_to_keep = -1
        vol.set_passphrase(b"s3cret")
        os.makedirs(os.path.dirname(vol.path_cow), exist_ok=True)
        with open(vol.path_cow + ".old", "wb") as fh:
            fh.write(b"previous-revision")

        def fake_resize(size):
            vol._size = size
            with open(vol.path, "r+b") as fh:
                fh.truncate(size)

        vol.resize = fake_resize

        async def cryptsetup_side(*args, **kwargs):
            if "isLuks" in args:
                raise subprocess.CalledProcessError(1, "isLuks")
            return None

        self.assertTrue(vol.revisions)
        self.mock_cryptsetup.side_effect = cryptsetup_side
        exists_p, dd_p = self._patch_zero_mapper()
        with exists_p, dd_p:
            self.loop.run_until_complete(vol.setup_luks())
        self.assertFalse(vol.revisions)
        self.assertFalse(os.path.exists(vol.path_cow + ".old"))
        called = [c[0] for c in self.mock_cryptsetup.call_args_list]
        self.assertTrue(any("luksFormat" in c for c in called))

    def test_009c_discard_revisions_refuses_dirty(self):
        vol = self._created_volume()
        os.makedirs(os.path.dirname(vol.path_cow), exist_ok=True)
        with open(vol.path_cow + ".old", "wb") as fh:
            fh.write(b"previous-revision")
        vol.is_dirty = lambda: True
        with self.assertRaises(StoragePoolException) as ctx:
            self.loop.run_until_complete(
                qubes.utils.coro_maybe(vol.discard_revisions())
            )
        self.assertIn("dirty", str(ctx.exception).lower())
        self.assertTrue(os.path.exists(vol.path_cow + ".old"))

    def test_009f_discard_revisions_refuses_running(self):
        vol = self._created_volume()
        os.makedirs(os.path.dirname(vol.path_cow), exist_ok=True)
        with open(vol.path_cow + ".old", "wb") as fh:
            fh.write(b"previous-revision")
        vol._export_lock = qubes.storage.file.FileVolume._marker_running
        with self.assertRaises(StoragePoolException) as ctx:
            self.loop.run_until_complete(
                qubes.utils.coro_maybe(vol.discard_revisions())
            )
        self.assertIn("running or exported", str(ctx.exception).lower())
        self.assertTrue(os.path.exists(vol.path_cow + ".old"))

    def test_009g_discard_revisions_refuses_exported(self):
        vol = self._created_volume()
        os.makedirs(os.path.dirname(vol.path_cow), exist_ok=True)
        with open(vol.path_cow + ".old", "wb") as fh:
            fh.write(b"previous-revision")
        vol._export_lock = qubes.storage.file.FileVolume._marker_exported
        with self.assertRaises(StoragePoolException) as ctx:
            self.loop.run_until_complete(
                qubes.utils.coro_maybe(vol.discard_revisions())
            )
        self.assertIn("running or exported", str(ctx.exception).lower())
        self.assertTrue(os.path.exists(vol.path_cow + ".old"))

    def test_009h_file_commit_unlinks_when_keep_minus_one(self):
        vol = self._created_volume()
        vol.revisions_to_keep = -1
        os.makedirs(os.path.dirname(vol.path_cow), exist_ok=True)
        with open(vol.path_cow, "wb") as fh:
            fh.write(b"cow")
        vol.commit()
        self.assertFalse(os.path.exists(vol.path_cow + ".old"))
        self.assertTrue(os.path.exists(vol.path_cow))

    def test_009i_lvm_discard_revisions_does_not_ignore_errors(self):
        # qubes.storage.lvm runs `lvs` at import time.
        lvm_json = b'{"report":[{"lv":[]}]}'
        proc = unittest.mock.Mock()
        proc.communicate.return_value = (lvm_json, b"")
        proc.returncode = 0
        proc.__enter__ = lambda s: s
        proc.__exit__ = lambda *a: False
        with unittest.mock.patch("subprocess.Popen", return_value=proc):
            import qubes.storage.lvm as lvm

        pool = qubes.storage.Pool(name="test-lvm")
        vol = lvm.ThinVolume(
            volume_group="qubes_dom0",
            name="private",
            pool=pool,
            vid="qubes_dom0/vm-test-private",
            rw=True,
            save_on_stop=True,
            size=1024,
        )
        vol.is_dirty = lambda: False
        with unittest.mock.patch.object(
            lvm.ThinVolume,
            "revisions",
            new_callable=unittest.mock.PropertyMock,
            return_value={"123-back": "2020-01-01T00:00:00"},
        ), unittest.mock.patch(
            "qubes.storage.lvm.qubes_lvm_coro",
            new_callable=unittest.mock.AsyncMock,
            side_effect=qubes.exc.StoragePoolException("lvremove failed"),
        ) as mock_lvm, unittest.mock.patch(
            "qubes.storage.lvm.reset_cache_coro",
            new_callable=unittest.mock.AsyncMock,
        ) as mock_reset:
            with self.assertRaises(StoragePoolException):
                self.loop.run_until_complete(vol.discard_revisions())
            mock_lvm.assert_awaited()
            self.assertEqual(mock_lvm.call_args[0][0][0], "remove")
            mock_reset.assert_not_called()

    def test_009j_zfs_discard_revisions_blocks_on_any_snapshot(self):
        vol = object.__new__(qubes.storage.zfs.ZFSVolume)
        vol.vid = "tank/vm-test-private"
        vol.log = unittest.mock.Mock()
        vol._lock = asyncio.Lock()
        vol.is_dirty = lambda: False
        vol._purge_old_revisions = unittest.mock.AsyncMock()
        snap = unittest.mock.Mock()
        snap.name = "tank/vm-test-private@qubes-clean-abc"
        accessor = unittest.mock.Mock()
        accessor.get_volume_snapshots_async = unittest.mock.AsyncMock(
            side_effect=[[snap], [snap]]
        )
        accessor.remove_volume_async = unittest.mock.AsyncMock()
        vol.pool = unittest.mock.Mock()
        vol.pool.accessor = accessor
        with self.assertRaises(StoragePoolException) as ctx:
            self.loop.run_until_complete(vol.discard_revisions())
        self.assertIn("still in use", str(ctx.exception).lower())
        vol._purge_old_revisions.assert_awaited_once_with(keep=0)
        accessor.remove_volume_async.assert_awaited()

    def test_009k_callback_discard_revisions_delegates(self):
        impl = self._private_volume()
        impl.discard_revisions = unittest.mock.AsyncMock(return_value=impl)
        pool = object.__new__(qubes.storage.callback.CallbackPool)
        vol = qubes.storage.callback.CallbackVolume(pool, impl)
        with unittest.mock.patch.object(
            qubes.storage.callback.CallbackVolume,
            "_assert_initialized",
            new_callable=unittest.mock.AsyncMock,
        ):
            self.loop.run_until_complete(vol.discard_revisions())
        impl.discard_revisions.assert_called_once_with()

    def test_009l_discard_if_unused_runs_when_revisions_empty(self):
        vol = self._created_volume()
        vol.revisions_to_keep = 0
        self.assertFalse(vol.revisions)
        called = []

        async def discard():
            called.append(True)

        vol.discard_revisions = discard
        self.loop.run_until_complete(vol._discard_revisions_if_unused())
        self.assertTrue(called)

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

    def test_013b_failed_reencrypt_retry_does_not_stack_grow(self):
        vol = self._created_volume()
        with open(vol.path, "r+b") as fh:
            fh.write(b"filesystem-superblock")
        vol.set_passphrase(b"s3cret")
        orig_size = vol.size
        resized = []

        def fake_resize(size):
            resized.append(size)
            vol._size = size
            with open(vol.path, "r+b") as fh:
                fh.truncate(size)

        vol.resize = fake_resize
        fail_reencrypt = {"n": True}

        async def cryptsetup_side(*args, **kwargs):
            if "isLuks" in args:
                if vol.size == orig_size + qubes.storage.LUKS2_HEADER_SIZE:
                    return None
                raise subprocess.CalledProcessError(1, "isLuks")
            if "reencrypt" in args and fail_reencrypt["n"]:
                fail_reencrypt["n"] = False
                raise subprocess.CalledProcessError(1, "reencrypt")
            return None

        self.mock_cryptsetup.side_effect = cryptsetup_side
        with self.assertRaises(subprocess.CalledProcessError):
            self.loop.run_until_complete(vol.setup_luks())
        self.loop.run_until_complete(vol.setup_luks())
        self.assertEqual(
            resized,
            [
                orig_size + qubes.storage.LUKS2_REENCRYPT_WORKSPACE,
                orig_size + qubes.storage.LUKS2_HEADER_SIZE,
            ],
        )
        self.assertEqual(vol.size, orig_size + qubes.storage.LUKS2_HEADER_SIZE)

    def test_014_header_size_constant(self):
        self.assertEqual(qubes.storage.LUKS2_HEADER_SIZE, 32 << 20)
        self.assertEqual(qubes.storage.LUKS2_REENCRYPT_WORKSPACE, 64 << 20)
        self.assertEqual(qubes.storage.LUKS2_DATA_OFFSET_SECTORS, 65536)
        self.assertEqual(qubes.storage.LUKS2_ZERO_PAYLOAD, 10 << 20)
        self.assertEqual(
            "--reduce-device-size={}M".format(
                qubes.storage.LUKS2_REENCRYPT_WORKSPACE >> 20
            ),
            "--reduce-device-size=64M",
        )
        self.assertEqual(
            "--offset={}".format(qubes.storage.LUKS2_DATA_OFFSET_SECTORS),
            "--offset=65536",
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

    def test_016_luks_backend_uses_volume_path(self):
        vol = self._created_volume()
        self.assertTrue(os.path.exists(vol.path))
        self.assertEqual(vol.luks_backend_path(), vol.path)


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

    def test_008_refuses_unencrypted_start_with_passphrase(self):
        vol = self._private_volume()
        vol.set_passphrase(b"s3cret")
        vol.start = unittest.mock.AsyncMock()
        storage, _vm = self._storage_with(vol)
        state_dir = os.path.join(self.tmpdir, "run")
        os.makedirs(state_dir)
        with unittest.mock.patch("qubes.storage.VOLUME_STATE_DIR", state_dir):
            with self.assertRaises(StoragePoolException) as ctx:
                self.loop.run_until_complete(storage.start())
        self.assertIn("enable encryption", str(ctx.exception).lower())
        self.assertTrue(vol.has_passphrase())
        vol.start.assert_not_called()

    def test_009_clears_passphrase_on_unencrypted_stop(self):
        vol = self._private_volume()
        vol.set_passphrase(b"s3cret")
        vol.stop = unittest.mock.AsyncMock()
        storage, _vm = self._storage_with(vol)
        state_dir = os.path.join(self.tmpdir, "run")
        os.makedirs(state_dir)
        with unittest.mock.patch("qubes.storage.VOLUME_STATE_DIR", state_dir):
            self.loop.run_until_complete(storage.stop())
        self.assertFalse(vol.has_passphrase())
        vol.stop.assert_called_once()

    def test_010_keeps_passphrase_on_encrypted_start_until_luks(self):
        vol = self._private_volume(encrypted=True)
        vol.set_passphrase(b"s3cret")
        vol.start_luks = unittest.mock.AsyncMock()
        storage, _vm = self._storage_with(vol)
        state_dir = os.path.join(self.tmpdir, "run")
        os.makedirs(state_dir)
        with unittest.mock.patch("qubes.storage.VOLUME_STATE_DIR", state_dir):
            self.loop.run_until_complete(storage.start())
        self.assertTrue(vol.has_passphrase())
        vol.start_luks.assert_called_once()

    def test_011_refuses_start_before_any_volume_starts(self):
        root = self._private_volume()
        root.start = unittest.mock.AsyncMock()
        priv = self._private_volume()
        priv.set_passphrase(b"s3cret")
        priv.start = unittest.mock.AsyncMock()
        vm = qubes.tests.storage.TestVM(self)
        vm.volumes = {"root": root, "private": priv}
        vm.fire_event_async = unittest.mock.AsyncMock()
        storage = qubes.storage.Storage(vm)
        state_dir = os.path.join(self.tmpdir, "run")
        os.makedirs(state_dir)
        with unittest.mock.patch("qubes.storage.VOLUME_STATE_DIR", state_dir):
            with self.assertRaises(StoragePoolException) as ctx:
                self.loop.run_until_complete(storage.start())
        self.assertIn("unencrypted volume", str(ctx.exception).lower())
        root.start.assert_not_called()
        priv.start.assert_not_called()
        self.assertTrue(priv.has_passphrase())

    def test_012_start_saves_after_zero(self):
        vol = self._private_volume(encrypted=True, luks_needs_zero=True)
        vol.set_passphrase(b"s3cret")

        async def start_luks(_name):
            vol._luks_needs_zero = False

        vol.start_luks = unittest.mock.AsyncMock(side_effect=start_luks)
        storage, vm = self._storage_with(vol)
        saved_flag = []

        def on_save():
            saved_flag.append(vol._luks_needs_zero)

        vm.app.save = unittest.mock.Mock(side_effect=on_save)
        state_dir = os.path.join(self.tmpdir, "run")
        os.makedirs(state_dir)
        with unittest.mock.patch("qubes.storage.VOLUME_STATE_DIR", state_dir):
            self.loop.run_until_complete(storage.start())
        vm.app.save.assert_called_once_with()
        vol.start_luks.assert_awaited()
        self.assertEqual(saved_flag, [False])
        self.assertFalse(vol._luks_needs_zero)

    def test_013_start_skips_save_when_zero_not_needed(self):
        vol = self._private_volume(encrypted=True)
        vol.set_passphrase(b"s3cret")
        vol.start_luks = unittest.mock.AsyncMock()
        storage, vm = self._storage_with(vol)
        vm.app.save = unittest.mock.Mock()
        state_dir = os.path.join(self.tmpdir, "run")
        os.makedirs(state_dir)
        with unittest.mock.patch("qubes.storage.VOLUME_STATE_DIR", state_dir):
            self.loop.run_until_complete(storage.start())
        vm.app.save.assert_not_called()

    def test_014_start_saves_zero_clear_on_unlock_failure(self):
        vol = self._private_volume(encrypted=True, luks_needs_zero=True)
        vol.set_passphrase(b"s3cret")

        async def start_luks(_name):
            vol._luks_needs_zero = False
            raise StoragePoolException("unlock failed")

        vol.start_luks = unittest.mock.AsyncMock(side_effect=start_luks)
        storage, vm = self._storage_with(vol)
        saved_flag = []

        def on_save():
            saved_flag.append(vol._luks_needs_zero)

        vm.app.save = unittest.mock.Mock(side_effect=on_save)
        state_dir = os.path.join(self.tmpdir, "run")
        os.makedirs(state_dir)
        with unittest.mock.patch("qubes.storage.VOLUME_STATE_DIR", state_dir):
            with self.assertRaises(StoragePoolException):
                self.loop.run_until_complete(storage.start())
        vm.app.save.assert_called_once_with()
        vol.start_luks.assert_awaited()
        self.assertEqual(saved_flag, [False])
        self.assertFalse(vol._luks_needs_zero)


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
        orig = 2 << 20
        src = self._private_volume(
            encrypted=True, luks_guest_size=orig, luks_needs_zero=True
        )
        dst = self._private_volume()
        self.assertFalse(dst.encrypted)
        dst.import_volume = unittest.mock.AsyncMock(return_value=dst)
        src.is_running = lambda: False
        storage, vm = TC_03_StorageStartStop._storage_with(self, dst)
        self.loop.run_until_complete(storage.import_volume(dst, src))
        self.assertTrue(dst.encrypted)
        self.assertEqual(dst._luks_setup_guest_size, orig)
        self.assertTrue(dst._luks_needs_zero)
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

    def test_007_import_plaintext_pins_live_guest_and_skips_zero(self):
        orig = 2 << 20
        imported = 8 << 20
        vol = self._private_volume(
            size=imported,
            encrypted=True,
            luks_needs_zero=True,
            luks_guest_size=orig,
        )
        os.makedirs(os.path.dirname(vol.path), exist_ok=True)
        self.loop.run_until_complete(qubes.utils.coro_maybe(vol.create()))
        with open(vol.path, "r+b") as fh:
            fh.write(b"imported-filesystem")
        vol.set_passphrase(b"s3cret")
        vol.import_data_end = unittest.mock.AsyncMock(return_value=vol)
        vol.is_luks = unittest.mock.AsyncMock(return_value=False)
        captured = {}

        async def setup():
            captured["guest"] = vol._luks_setup_guest_size
            captured["zero"] = vol._luks_needs_zero

        vol.setup_luks = unittest.mock.AsyncMock(side_effect=setup)
        storage, _vm = TC_03_StorageStartStop._storage_with(self, vol)
        self.loop.run_until_complete(storage.import_data_end(vol, True))
        self.assertEqual(captured["guest"], imported)
        self.assertFalse(captured["zero"])

    def test_008_import_already_luks_pins_payload_and_skips_zero(self):
        orig = 2 << 20
        backing = orig + qubes.storage.LUKS2_HEADER_SIZE
        imported = 64 << 20
        vol = self._private_volume(
            size=imported,
            encrypted=True,
            luks_needs_zero=True,
            luks_guest_size=orig,
        )
        os.makedirs(os.path.dirname(vol.path), exist_ok=True)
        self.loop.run_until_complete(qubes.utils.coro_maybe(vol.create()))
        vol.set_passphrase(b"s3cret")
        vol.import_data_end = unittest.mock.AsyncMock(return_value=vol)
        vol.is_luks = unittest.mock.AsyncMock(return_value=True)
        captured = {}

        async def setup():
            captured["guest"] = vol._luks_setup_guest_size
            captured["zero"] = vol._luks_needs_zero

        vol.setup_luks = unittest.mock.AsyncMock(side_effect=setup)
        storage, _vm = TC_03_StorageStartStop._storage_with(self, vol)
        self.loop.run_until_complete(storage.import_data_end(vol, True))
        self.assertEqual(
            captured["guest"], imported - qubes.storage.LUKS2_HEADER_SIZE
        )
        self.assertFalse(captured["zero"])
        self.assertNotEqual(captured["guest"], orig)
        self.assertNotEqual(captured["guest"], backing)

    def test_009_import_data_end_saves_luks_pin(self):
        vol = self._private_volume(encrypted=True, luks_needs_zero=True)
        vol.set_passphrase(b"s3cret")
        vol.import_data_end = unittest.mock.AsyncMock(return_value=vol)
        vol.is_luks = unittest.mock.AsyncMock(return_value=False)
        vol.setup_luks = unittest.mock.AsyncMock()
        storage, vm = TC_03_StorageStartStop._storage_with(self, vol)
        vm.app.save = unittest.mock.Mock()
        self.loop.run_until_complete(storage.import_data_end(vol, True))
        vm.app.save.assert_called_once_with()

    def test_010_import_data_end_saves_pin_if_setup_fails(self):
        vol = self._private_volume(encrypted=True, luks_needs_zero=True)
        vol.set_passphrase(b"s3cret")
        vol.import_data_end = unittest.mock.AsyncMock(return_value=vol)
        vol.is_luks = unittest.mock.AsyncMock(return_value=False)
        vol.setup_luks = unittest.mock.AsyncMock(
            side_effect=StoragePoolException("setup failed")
        )
        storage, vm = TC_03_StorageStartStop._storage_with(self, vol)
        vm.app.save = unittest.mock.Mock()
        with self.assertRaises(StoragePoolException):
            self.loop.run_until_complete(storage.import_data_end(vol, True))
        vm.app.save.assert_called_once_with()

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
        self.assertEqual(vol.luks_backend_path(), "/dev/zvol/tank/vm-private")
