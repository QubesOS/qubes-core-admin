#
# The Qubes OS Project, https://www.qubes-os.org/
#
# Copyright (C) 2026 Divina Commedia <fishtheclock@gmail.com>
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
import shutil
import tempfile
import unittest.mock

import qubes.backup
import qubes.exc
import qubes.tests


class TC_00_BackupHeader(qubes.tests.QubesTestCase):
    """Tests for qubes.backup.BackupHeader serialization."""

    def setUp(self):
        super().setUp()
        self.tmpdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmpdir)

    def read_header(self, header):
        path = os.path.join(self.tmpdir, "backup-header")
        header.save(path)
        with open(path, "r", encoding="ascii") as header_f:
            return header_f.read()

    def test_000_version_only(self):
        header = qubes.backup.BackupHeader(version="4")
        self.assertEqual(self.read_header(header), "version=4\n")

    def test_010_all_options(self):
        header = qubes.backup.BackupHeader(
            version="4",
            encrypted=True,
            compressed=False,
            compression_filter="gzip",
            hmac_algorithm="scrypt",
            crypto_algorithm="aes-256-cbc",
            backup_id="backup-id",
        )
        self.assertEqual(
            self.read_header(header),
            "version=4\n"
            "encrypted=True\n"
            "compressed=False\n"
            "compression-filter=gzip\n"
            "crypto-algorithm=aes-256-cbc\n"
            "hmac-algorithm=scrypt\n"
            "backup-id=backup-id\n",
        )

    def test_020_none_options_skipped(self):
        header = qubes.backup.BackupHeader(
            version="4",
            encrypted=True,
            compressed=None,
            compression_filter=None,
            hmac_algorithm="scrypt",
            crypto_algorithm=None,
            backup_id=None,
        )
        self.assertEqual(
            self.read_header(header),
            "version=4\n" "encrypted=True\n" "hmac-algorithm=scrypt\n",
        )

    def test_030_version_always_first(self):
        header = qubes.backup.BackupHeader(
            version="4",
            encrypted=True,
            compressed=True,
        )
        content = self.read_header(header)
        self.assertEqual(content.splitlines()[0], "version=4")

    def test_040_header_keys_cover_init_params(self):
        """Every __init__ parameter must be serialized via header_keys."""
        for attr in (
            "version",
            "encrypted",
            "compressed",
            "compression_filter",
            "hmac_algorithm",
            "crypto_algorithm",
            "backup_id",
        ):
            self.assertIn(
                attr,
                qubes.backup.BackupHeader.header_keys.values(),
                "init parameter {!r} missing from header_keys".format(attr),
            )


class TC_10_BackupSplitAndSend(qubes.tests.QubesTestCase):
    """Tests for qubes.backup.Backup._split_and_send."""

    def setUp(self):
        super().setUp()
        self.tmpdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmpdir)
        self.backup = qubes.backup.Backup(
            unittest.mock.Mock(), [], passphrase=b"test"
        )
        self.backup.tmpdir = self.tmpdir

    def test_000_scrypt_failure(self):
        """A chunk scrypt failed to write must not be sent."""
        scrypt = unittest.mock.Mock()
        scrypt.returncode = 1
        scrypt.wait = unittest.mock.AsyncMock(return_value=1)
        scrypt.stderr.read = unittest.mock.AsyncMock(
            return_value=b"scrypt: No space left on device\n"
        )
        input_stream = asyncio.StreamReader()
        input_stream.feed_data(b"data")
        input_stream.feed_eof()
        output_queue = asyncio.Queue()
        with unittest.mock.patch(
            "qubes.backup.launch_scrypt",
            unittest.mock.AsyncMock(return_value=scrypt),
        ):
            with self.assertRaisesRegex(
                qubes.exc.QubesException, "No space left on device"
            ):
                self.loop.run_until_complete(
                    self.backup._split_and_send(
                        input_stream,
                        os.path.join(self.tmpdir, "vm1", "private.img"),
                        output_queue,
                    )
                )
        self.assertTrue(output_queue.empty())


class TC_20_BackupTarget(qubes.tests.QubesTestCase):
    """Tests for the local backup file on success and failure."""

    def setUp(self):
        super().setUp()
        self.tmpdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmpdir)
        self.target_dir = os.path.join(self.tmpdir, "target")
        os.mkdir(self.target_dir)
        store = os.path.join(self.tmpdir, "qubes.xml")
        open(store, "w", encoding="ascii").close()
        app = unittest.mock.Mock(store=store, domains=[])
        self.backup = qubes.backup.Backup(
            app, vms_list=[], passphrase="pass", target_dir=self.target_dir
        )
        for patcher in (
            unittest.mock.patch("qubes.Qubes"),
            unittest.mock.patch.object(
                self.backup, "_prepare_backup_header", self.no_header
            ),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    @staticmethod
    async def no_header():
        return ()

    def run_backup(self, send_files):
        with unittest.mock.patch.object(
            self.backup, "_wrap_and_send_files", send_files
        ):
            self.loop.run_until_complete(self.backup.backup_do())

    def test_000_success_keeps_file(self):
        """A finished backup keeps the backup file it created."""

        async def send_files(_files, queue):
            await queue.put(qubes.backup.QUEUE_FINISHED)

        self.run_backup(send_files)
        self.assertEqual(len(os.listdir(self.target_dir)), 1)

    def test_010_error_removes_file(self):
        """A failed backup removes the file it created."""

        async def send_files(_files, _queue):
            raise qubes.exc.QubesException("failed")

        with self.assertRaises(qubes.exc.QubesException):
            self.run_backup(send_files)
        self.assertEqual(os.listdir(self.target_dir), [])

    def test_011_cancel_removes_file(self):
        """A cancelled backup removes the file it created."""

        async def send_files(_files, _queue):
            await asyncio.sleep(10)

        with unittest.mock.patch.object(
            self.backup, "_wrap_and_send_files", send_files
        ):
            task = asyncio.ensure_future(self.backup.backup_do())
            self.loop.run_until_complete(asyncio.sleep(0.1))
            self.assertEqual(len(os.listdir(self.target_dir)), 1)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                self.loop.run_until_complete(task)
        self.assertEqual(os.listdir(self.target_dir), [])

    def test_012_error_keeps_existing_file(self):
        """A failed backup keeps a target file that existed before."""
        target = os.path.join(self.target_dir, "existing")
        open(target, "w", encoding="ascii").close()
        self.backup.target_dir = target

        async def send_files(_files, _queue):
            raise qubes.exc.QubesException("failed")

        with self.assertRaises(qubes.exc.QubesException):
            self.run_backup(send_files)
        self.assertTrue(os.path.exists(target))
