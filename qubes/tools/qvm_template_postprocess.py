#!/usr/bin/python2 -O
# vim: fileencoding=utf-8

#
# The Qubes OS Project, https://www.qubes-os.org/
#
# Copyright (C) 2016  Marek Marczykowski-Górecki
#                                       <marmarek@invisiblethingslab.com>
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

import argparse
import glob
import os

import shutil
import subprocess

import sys

import grp

import qubes
import qubes.tools

parser = qubes.tools.QubesArgumentParser(
    description='Postprocess template package, for internal use only')
parser.add_argument('--really', action='store_true', default=False,
    help=argparse.SUPPRESS)
parser.add_argument('action', choices=['post-install', 'pre-remove'],
    help='Action to perform')
parser.add_argument('name', action='store',
    help='Template name')
parser.add_argument('dir', action='store',
    help='Template directory')


def move_if_exists(source, dest_dir):
    if os.path.exists(source):
        shutil.move(source, os.path.join(dest_dir, os.path.basename(source)))


def import_data(source_dir, vm):
    # FIXME: this abuses volume export() for importing purposes
    root_path = os.path.join(source_dir, 'root.img')
    target_path = vm.storage.export('root')
    if os.path.exists(root_path + '.part.00'):
        input_files = glob.glob(root_path + '.*')
        cat = subprocess.Popen(['cat'] + sorted(input_files),
            stdout=subprocess.PIPE)
        tar = subprocess.Popen(['tar', 'xSOf', '-'],
            stdin=cat.stdout,
            stdout=open(target_path, 'w'))
        if tar.wait() != 0:
            raise qubes.exc.QubesException('root.img extraction failed')
        if cat.wait() != 0:
            raise qubes.exc.QubesException('root.img extraction failed')
    elif os.path.exists(root_path):
        subprocess.check_call(
            ['dd', 'if='+root_path, 'of='+target_path, 'conv=sparse']
        )

    move_if_exists(os.path.join(source_dir, 'whitelisted-appmenus.list'),
        vm.dir_path)
    move_if_exists(os.path.join(source_dir, 'vm-whitelisted-appmenus.list'),
        vm.dir_path)
    move_if_exists(os.path.join(source_dir, 'netvm-whitelisted-appmenus.list'),
        vm.dir_path)

    shutil.rmtree(source_dir)


def post_install(args):
    root_path = os.path.join(args.dir, 'root.img')
    if os.path.exists(root_path + '.part.00'):
        # get just file root_size from the tar header
        p = subprocess.Popen(['tar', 'tvf', root_path + '.part.00'],
            stdout=subprocess.PIPE, stderr=open(os.devnull, 'w'))
        (stdout, _) = p.communicate()
        # -rw-r--r-- 0/0      1073741824 1970-01-01 01:00 root.img
        root_size = int(stdout.split()[2])
    elif os.path.exists(root_path):
        root_size = os.path.getsize(root_path)
    else:
        raise qubes.exc.QubesException('root.img not found')
    volume_config = {'root': {'size': root_size}}

    # TODO: add lock=True
    app = args.app
    reinstall = False
    try:
        # reinstall
        vm = app.domains[args.name]
        reinstall = True
    except KeyError:
        vm = app.add_new_vm(qubes.vm.templatevm.TemplateVM,
            name=args.name,
            label=qubes.config.defaults['template_label'],
            volume_config=volume_config)

    # vm.create_on_disk() need to create the directory on its own, move it
    # away for from its way
    if vm.dir_path == args.dir:
        shutil.move(args.dir,
            os.path.join(qubes.config.qubes_base_dir, 'tmp-' + args.name))
        args.dir = os.path.join(qubes.config.qubes_base_dir, 'tmp-' + args.name)
    if reinstall:
        vm.remove_from_disk()
    vm.create_on_disk()
    vm.log.info('Importing data')
    import_data(args.dir, vm)
    app.save()
    if os.getuid() == 0:
        # fix permissions, do it only here (not after starting the VM),
        # because we're running as root only at early installation phase,
        # when offline mode is enabled anyway - otherwise main() would switch
        # to non-root user
        try:
            qubes_group = grp.getgrnam('qubes')
            for dirpath, _, filenames in os.walk(vm.dir_path):
                os.chown(dirpath, -1, qubes_group.gr_gid)
                os.chmod(dirpath, 0o2775)
                for name in filenames:
                    filename = os.path.join(dirpath, name)
                    os.chown(filename, -1, qubes_group.gr_gid)
                    os.chmod(filename, 0o664)
        except KeyError:
            raise qubes.exc.QubesException('\'qubes\' group missing')

    if not app.vmm.offline_mode:
        # just created, so no need to save previous value - we know what it was
        vm.netvm = None
        vm.start(start_guid=False)
        vm.fire_event('template-postinstall')
        vm.shutdown(wait=True)
        vm.netvm = qubes.property.DEFAULT
    return 0


def pre_remove(args):
    # TODO: add lock=True
    app = args.app
    try:
        tpl = app.domains[args.name]
    except KeyError:
        parser.error('Qube with this name do not exist')
        return 1
    for appvm in app.domains:
        if hasattr(appvm, 'template') and appvm.template == tpl:
            parser.error('Qube {} use this template'.format(appvm.name))
            return 1

    del app.domains[args.name]
    tpl.remove_from_disk()
    app.save()
    return 0


def main(args=None):
    if os.getuid() == 0:
        try:
            qubes_group = grp.getgrnam('qubes')
            prefix_cmd = ['runuser', '-u', qubes_group.gr_mem[0], '--']
            os.execvp('runuser', prefix_cmd + sys.argv)
        except (KeyError, IndexError):
            # When group or user do not exist yet, continue as root. This
            # probably also means we're still in installer, so some actions
            # will not be taken anyway (because of running in chroot ->
            # offline mode).
            pass
    args = parser.parse_args(args)
    if not args.really:
        parser.error('Do not call this tool directly.')
        return 1
    if args.action == 'post-install':
        return post_install(args)
    elif args.action == 'pre-remove':
        pre_remove(args)
    else:
        parser.error('Unknown action')
        return 1
    return 0

if __name__ == '__main__':
    sys.exit(main())
