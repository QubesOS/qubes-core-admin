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
import sys

import qubes.backup
import qubes.tools
import qubes.utils

parser = qubes.tools.QubesArgumentParser(want_force_root=True)

parser.add_argument("--verify-only", action="store_true",
    dest="verify_only", default=False,
    help="Verify backup integrity without restoring any "
         "data")

parser.add_argument("--skip-broken", action="store_true", dest="skip_broken",
    default=False,
    help="Do not restore VMs that have missing TemplateVMs "
         "or NetVMs")

parser.add_argument("--ignore-missing", action="store_true",
    dest="ignore_missing", default=False,
    help="Restore VMs even if their associated TemplateVMs "
         "and NetVMs are missing")

parser.add_argument("--skip-conflicting", action="store_true",
    dest="skip_conflicting", default=False,
    help="Do not restore VMs that are already present on "
         "the host")

parser.add_argument("--rename-conflicting", action="store_true",
    dest="rename_conflicting", default=False,
    help="Restore VMs that are already present on the host "
         "under different names")

parser.add_argument("--replace-template", action="append",
    dest="replace_template", default=[],
    help="Restore VMs using another TemplateVM; syntax: "
         "old-template-name:new-template-name (may be "
         "repeated)")

parser.add_argument("-x", "--exclude", action="append", dest="exclude",
    default=[],
    help="Skip restore of specified VM (may be repeated)")

parser.add_argument("--skip-dom0-home", action="store_false", dest="dom0_home",
    default=True,
    help="Do not restore dom0 user home directory")

parser.add_argument("--ignore-username-mismatch", action="store_true",
    dest="ignore_username_mismatch", default=False,
    help="Ignore dom0 username mismatch when restoring home "
         "directory")

parser.add_argument("-d", "--dest-vm", action="store", dest="appvm",
    help="Specify VM containing the backup to be restored")

parser.add_argument("-p", "--passphrase-file", action="store",
    dest="pass_file", default=None,
    help="Read passphrase from file, or use '-' to read from stdin")

parser.add_argument('backup_location', action='store',
    help="Backup directory name, or command to pipe from")

parser.add_argument('vms', nargs='*', action='store', default='[]',
    help='Restore only those VMs')


def main(args=None):
    args = parser.parse_args(args)

    appvm = None
    if args.appvm:
        try:
            appvm = args.app.domains[args.appvm]
        except KeyError:
            parser.error('no such domain: {!r}'.format(args.appvm))

    if args.pass_file is not None:
        pass_f = open(args.pass_file) if args.pass_file != "-" else sys.stdin
        passphrase = pass_f.readline().rstrip()
        if pass_f is not sys.stdin:
            pass_f.close()
    else:
        passphrase = getpass.getpass("Please enter the passphrase to verify "
                                     "and (if encrypted) decrypt the backup: ")

    encoding = sys.stdin.encoding or locale.getpreferredencoding()
    passphrase = passphrase.decode(encoding)

    args.app.log.info("Checking backup content...")

    try:
        backup = qubes.backup.BackupRestore(args.app, args.backup_location,
            appvm, passphrase)
    except qubes.exc.QubesException as e:
        parser.error_runtime(str(e))
        # unreachable - error_runtime will raise SystemExit
        return 1

    if args.ignore_missing:
        backup.options.use_default_template = True
        backup.options.use_default_netvm = True
    if args.replace_template:
        backup.options.replace_template = args.replace_template
    if args.rename_conflicting:
        backup.options.rename_conflicting = True
    if not args.dom0_home:
        backup.options.dom0_home = False
    if args.ignore_username_mismatch:
        backup.options.ignore_username_mismatch = True
    if args.exclude:
        backup.options.exclude = args.exclude
    if args.verify_only:
        backup.options.verify_only = True

    restore_info = None
    try:
        restore_info = backup.get_restore_info()
    except qubes.exc.QubesException as e:
        parser.error_runtime(str(e))

    print(backup.get_restore_summary(restore_info))

    there_are_conflicting_vms = False
    there_are_missing_templates = False
    there_are_missing_netvms = False
    dom0_username_mismatch = False

    for vm_info in restore_info.values():
        assert isinstance(vm_info, qubes.backup.BackupRestore.VMToRestore)
        if qubes.backup.BackupRestore.VMToRestore.EXCLUDED in vm_info.problems:
            continue
        if qubes.backup.BackupRestore.VMToRestore.MISSING_TEMPLATE in \
                vm_info.problems:
            there_are_missing_templates = True
        if qubes.backup.BackupRestore.VMToRestore.MISSING_NETVM in \
                vm_info.problems:
            there_are_missing_netvms = True
        if qubes.backup.BackupRestore.VMToRestore.ALREADY_EXISTS in \
                vm_info.problems:
            there_are_conflicting_vms = True
        if qubes.backup.BackupRestore.Dom0ToRestore.USERNAME_MISMATCH in \
                vm_info.problems:
            dom0_username_mismatch = True


    if there_are_conflicting_vms:
        args.app.log.error(
            "*** There are VMs with conflicting names on the host! ***")
        if args.skip_conflicting:
            args.app.log.error(
                "Those VMs will not be restored. "
                "The host VMs will NOT be overwritten.")
        else:
            args.app.log.error(
                "Remove VMs with conflicting names from the host "
                "before proceeding.")
            args.app.log.error(
                "Or use --skip-conflicting to restore only those VMs that "
                "do not exist on the host.")
            args.app.log.error(
                "Or use --rename-conflicting to restore those VMs under "
                "modified names (with numbers at the end).")
            return 1

    args.app.log.info("The above VMs will be copied and added to your system.")
    args.app.log.info("Exisiting VMs will NOT be removed.")

    if there_are_missing_templates:
        args.app.log.error("*** One or more TemplateVMs are missing on the "
                           "host! ***")
        if not (args.skip_broken or args.ignore_missing):
            args.app.log.error("Install them before proceeding with the "
                                 "restore.")
            args.app.log.error("Or pass: --skip-broken or --ignore-missing.")
            return 1
        elif args.skip_broken:
            args.app.log.error("Skipping broken entries: VMs that depend on "
                                 "missing TemplateVMs will NOT be restored.")
        elif args.ignore_missing:
            args.app.log.error("Ignoring missing entries: VMs that depend "
                               "on missing TemplateVMs will NOT be restored.")
        else:
            args.app.log.error("INTERNAL ERROR! Please report this to the "
                               "Qubes OS team!")
            return 1

    if there_are_missing_netvms:
        args.app.log.error("*** One or more NetVMs are missing on the "
                           "host! ***")
        if not (args.skip_broken or args.ignore_missing):
            args.app.log.error("Install them before proceeding with the "
                               "restore.")
            args.app.log.error("Or pass: --skip-broken or --ignore-missing.")
            return 1
        elif args.skip_broken:
            args.app.log.error("Skipping broken entries: VMs that depend on "
                               "missing NetVMs will NOT be restored.")
        elif args.ignore_missing:
            args.app.log.error("Ignoring missing entries: VMs that depend "
                               "on missing NetVMs will NOT be restored.")
        else:
            args.app.log.error("INTERNAL ERROR! Please report this to the "
                               "Qubes OS team!")
            return 1

    if 'dom0' in restore_info.keys() and args.dom0_home:
        if dom0_username_mismatch:
            args.app.log.error("*** Dom0 username mismatch! This can break "
                               "some settings! ***")
            if not args.ignore_username_mismatch:
                args.app.log.error("Skip restoring the dom0 home directory "
                                   "(--skip-dom0-home), or pass "
                                   "--ignore-username-mismatch to continue "
                                   "anyway.")
                return 1
            else:
                args.app.log.error("Continuing as directed.")
        args.app.log.error("NOTE: Before restoring the dom0 home directory, "
            "a new directory named "
            "'home-pre-restore-<current-time>' will be "
            "created inside the dom0 home directory. If any "
            "restored files conflict with existing files, "
            "the existing files will be moved to this new "
            "directory.")

    if args.pass_file is None:
        if raw_input("Do you want to proceed? [y/N] ").upper() != "Y":
            exit(0)

    try:
        backup.restore_do(restore_info)
    except qubes.exc.QubesException as e:
        parser.error_runtime(str(e))

if __name__ == '__main__':
    main()