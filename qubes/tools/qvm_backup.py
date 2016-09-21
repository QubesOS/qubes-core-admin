#!/usr/bin/python2
# -*- encoding: utf8 -*-
#
# The Qubes OS Project, http://www.qubes-os.org
#
# Copyright (C) 2016 Marek Marczykowski-Górecki
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
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.

from __future__ import print_function
import getpass
import locale
import os

import sys

import qubes.backup
import qubes.tools
import qubes.utils

parser = qubes.tools.QubesArgumentParser(want_force_root=True)

parser.add_argument("--exclude", "-x", action="append",
    dest="exclude_list", default=[],
    help="Exclude the specified VM from the backup (may be "
         "repeated)")
parser.add_argument("--dest-vm", "-d", action="store",
    dest="appvm", default=None,
    help="Specify the destination VM to which the backup "
         "will be sent (implies -e)")
parser.add_argument("--encrypt", "-e", action="store_true", dest="encrypted",
    default=False,
    help="Encrypt the backup")
parser.add_argument("--no-encrypt", action="store_true",
    dest="no_encrypt", default=False,
    help="Skip encryption even if sending the backup to a "
         "VM")
parser.add_argument("--passphrase-file", "-p", action="store",
    dest="pass_file", default=None,
    help="Read passphrase from a file, or use '-' to read "
         "from stdin")
parser.add_argument("--enc-algo", "-E", action="store",
    dest="crypto_algorithm", default=None,
    help="Specify a non-default encryption algorithm. For a "
         "list of supported algorithms, execute 'openssl "
         "list-cipher-algorithms' (implies -e)")
parser.add_argument("--hmac-algo", "-H", action="store",
    dest="hmac_algorithm", default=None,
    help="Specify a non-default HMAC algorithm. For a list "
         "of supported algorithms, execute 'openssl "
         "list-message-digest-algorithms'")
parser.add_argument("--compress", "-z", action="store_true", dest="compressed",
    default=False,
    help="Compress the backup")
parser.add_argument("--compress-filter", "-Z", action="store",
    dest="compression_filter", default=False,
    help="Specify a non-default compression filter program "
         "(default: gzip)")
parser.add_argument("--tmpdir", action="store", dest="tmpdir", default=None,
    help="Specify a temporary directory (if you have at least "
         "1GB free RAM in dom0, use of /tmp is advised) ("
         "default: /var/tmp)")

parser.add_argument("backup_location", action="store",
    help="Backup location (directory path, or command to pipe backup to)")

parser.add_argument("vms", nargs="*", action=qubes.tools.VmNameAction,
    help="Backup only those VMs")


def main(args=None):
    args = parser.parse_args(args)

    appvm = None
    if args.appvm:
        try:
            appvm = args.app.domains[args.appvm]
        except KeyError:
            parser.error('no such domain: {!r}'.format(args.appvm))
        args.app.log.info(("NOTE: VM {} will be excluded because it is "
               "the backup destination.").format(args.appvm),
            file=sys.stderr)

    if appvm:
        args.exclude_list.append(appvm.name)
    if args.appvm or args.crypto_algorithm:
        args.encrypted = True
    if args.no_encrypt:
        args.encrypted = False

    try:
        backup = qubes.backup.Backup(args.app,
            args.domains if args.domains else None,
            exclude_list=args.exclude_list)
    except qubes.exc.QubesException as e:
        parser.error_runtime(str(e))
        # unreachable - error_runtime will raise SystemExit
        return 1

    backup.target_dir = args.backup_location

    if not appvm:
        if os.path.isdir(args.backup_location):
            stat = os.statvfs(args.backup_location)
        else:
            stat = os.statvfs(os.path.dirname(args.backup_location))
        backup_fs_free_sz = stat.f_bsize * stat.f_bavail
        print()
        if backup.total_backup_bytes > backup_fs_free_sz:
            parser.error_runtime("Not enough space available on the "
                                 "backup filesystem!")

        args.app.log.info("Available space: {0}".format(
            qubes.utils.size_to_human(backup_fs_free_sz)))
    else:
        stat = os.statvfs('/var/tmp')
        backup_fs_free_sz = stat.f_bsize * stat.f_bavail
        print()
        if backup_fs_free_sz < 1000000000:
            parser.error_runtime("Not enough space available "
                "on the local filesystem (1GB required for temporary files)!")

        if not appvm.is_running():
            appvm.start()

    if not args.encrypted:
        args.app.log.info("WARNING: The backup will NOT be encrypted!", file=sys.stderr)

    if args.pass_file is not None:
        pass_f = open(args.pass_file) if args.pass_file != "-" else sys.stdin
        passphrase = pass_f.readline().rstrip()
        if pass_f is not sys.stdin:
            pass_f.close()

    else:
        if raw_input("Do you want to proceed? [y/N] ").upper() != "Y":
            return 0

        prompt = ("Please enter the passphrase that will be used to {}verify "
             "the backup: ").format('encrypt and ' if args.encrypted else '')
        passphrase = getpass.getpass(prompt)

        if getpass.getpass("Enter again for verification: ") != passphrase:
            parser.error_runtime("Passphrase mismatch!")

    backup.encrypted = args.encrypted
    backup.compressed = args.compressed
    if args.compression_filter:
        backup.compression_filter = args.compression_filter

    encoding = sys.stdin.encoding or locale.getpreferredencoding()
    backup.passphrase = passphrase.decode(encoding)

    if args.hmac_algorithm:
        backup.hmac_algorithm = args.hmac_algorithm
    if args.crypto_algorithm:
        backup.crypto_algorithm = args.crypto_algorithm
    if args.tmpdir:
        backup.tmpdir = args.tmpdir
    if appvm:
        backup.target_vm = appvm

    try:
        backup.backup_do()
    except qubes.exc.QubesException as e:
        parser.error_runtime(str(e))

    print()
    args.app.log.info("Backup completed.")
    return 0

if __name__ == '__main__':
    main()
