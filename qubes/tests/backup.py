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
