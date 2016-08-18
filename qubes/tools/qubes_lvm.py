#!/usr/bin/python2
#
# The Qubes OS Project, http://www.qubes-os.org
#
# Copyright (C) 2016 Bahtiar `kalkin-` Gadimov <bahtiar@gadimov.de>
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
#
''' Manage pools and volumes managed by the 'lvm_thin' driver. '''

from __future__ import print_function

import logging
import subprocess
import sys
import time
import lvm  # pylint: disable=import-error

import qubes

log = logging.getLogger('qubes.storage.lvm')


def pool_exists(args):
    """ Check if given name is an lvm thin volume. """
    # TODO Implement a faster and proper working version pool_exists
    vg_name, thin_pool_name = args.pool_id.split('/', 1)
    volume_group = lvm.vgOpen(vg_name)
    for p in volume_group.listLVs():
        if p.getAttr()[0] == 't' and p.getName() == thin_pool_name:
            volume_group.close()
            return True

    volume_group.close()
    return False


def volume_exists(volume):
    """ Check if the given volume exists and is a thin volume """
    log.debug("Checking if the %s thin volume exists", volume)
    assert volume is not None
    vg_name, volume_name = volume.split('/', 1)
    volume_group = lvm.vgOpen(vg_name)
    for p in volume_group.listLVs():
        if p.getAttr()[0] == 'V' and p.getName() == volume_name:
            volume_group.close()
            return True

    volume_group.close()
    return False


def remove_volume(args):
    """ Tries to remove the specified logical volume.

        If the removal fails it will try up to 3 times waiting 1, 2 and 3
        seconds between tries. Most of the time this function fails if some
        process still has the volume locked.
    """
    img = args.name
    if not volume_exists(img):
        log.info("Expected to remove %s, but volume does not exist", img)
        return

    tries = 1
    successful = False
    cmd = ['sudo', 'lvremove', '-f', img]

    while tries <= 3 and not successful:
        log.info("Trying to remove LVM %s", img)
        try:
            output = subprocess.check_output(cmd, stderr=subprocess.STDOUT)
            log.debug(output)
            successful = True
        except subprocess.CalledProcessError:
            successful = False

        if successful:
            break
        else:
            time.sleep(tries)
            tries += 1

    if not successful:
        log.error('Could not remove volume ' + img)


def clone_volume(args):
    """ Calls lvcreate and creates new snapshot. """
    old = args.source
    new_name = args.destination
    cmd = ["sudo", "lvcreate", "-kn", "-ay", "-s", old, "-n", new_name]
    return subprocess.call(cmd)


def new_volume(args):
    ''' Creates a new volume in the specified thin pool, formated with ext4 '''

    thin_pool = args.pool_id
    name = args.name
    size = args.size
    log.info('Creating new Thin LVM %s in %s VG %s bytes', name, thin_pool,
             size)
    cmd = ['sudo', 'lvcreate', '-T', thin_pool, '-kn', '-ay', '-n', name, '-V',
           str(size) + 'B']

    return subprocess.call(cmd)


def rename_volume(old_name, new_name):
    ''' Rename volume '''
    log.debug("Renaming LVM  %s to %s ", old_name, new_name)
    retcode = subprocess.call(["sudo", "lvrename", old_name, new_name])
    if retcode != 0:
        raise IOError("Error renaming LVM  %s to %s " % (old_name, new_name))
    return new_name


def init_pool_parser(sub_parsers):
    ''' Initialize pool subparser '''
    pool_parser = sub_parsers.add_parser(
        'pool', aliases=('p', 'pl'),
        help="Exit with exit code 0 if pool exists")
    pool_parser.add_argument('pool_id', metavar='VG/POOL',
                             help="volume_group/pool_name")
    pool_parser.set_defaults(func=pool_exists)


def init_new_parser(sub_parsers):
    ''' Initialize the 'new' subparser '''
    new_parser = sub_parsers.add_parser(
        'new', aliases=('n', 'create'),
        help='Creates a new thin ThinPoolLogicalVolume')
    new_parser.add_argument('pool_id', metavar='VG/POOL',
                            help="volume_group/pool_name")

    new_parser.add_argument('name',
                            help='name of the new ThinPoolLogicalVolume')
    new_parser.add_argument(
        'size', help='size in bytes of the new ThinPoolLogicalVolume')

    new_parser.set_defaults(func=new_volume)


def init_import_parser(sub_parsers):
    ''' Initialize import subparser '''
    import_parser = sub_parsers.add_parser(
        'import', aliases=('imp', 'i'),
        help='sparse copy data from stdin to a thin volume')
    import_parser.add_argument('name', metavar='VG/VID',
                               help='volume_group/volume_name')
    import_parser.set_defaults(func=import_volume)

def init_clone_parser(sub_parsers):
    ''' Initialize clone subparser '''
    clone_parser = sub_parsers.add_parser(
        'clone', aliases=('cln', 'c'),
        help='sparse copy data from stdin to a thin volume')
    clone_parser.add_argument('source', metavar='VG/VID',
                               help='volume_group/volume_name')
    clone_parser.add_argument('destination', metavar='VG/VID',
                               help='volume_group/volume_name')
    clone_parser.set_defaults(func=clone_volume)

def import_volume(args):
    ''' Imports from stdin to a thin volume '''
    name = args.name
    src = sys.stdin
    blk_size = 4096
    zeros = '\x00' * blk_size
    dst_path = '/dev/%s' % name
    with open(dst_path, 'wb') as dst:
        while True:
            tmp = src.read(blk_size)
            if not tmp:
                break
            elif tmp == zeros:
                dst.seek(blk_size, 1)
            else:
                dst.write(tmp)


def list_volumes(args):
    ''' lists volumes '''
    vg_name, _ = args.name.split('/')
    volume_group = lvm.vgOpen(vg_name)
    for p in volume_group.listLVs():
        if p.getAttr()[0] == 'V':
            print(vg_name + "/" + p.getName() + ' ' + p.getAttr())
    volume_group.close()


def init_volumes_parser(sub_parsers):
    ''' Initialize volumes subparser '''
    parser = sub_parsers.add_parser('volumes', aliases=('v', 'vol'),
                                    help='list volumes in a pool')
    parser.add_argument('name', metavar='VG/THIN_POOL',
                        help='volume_group/thin_pool_name')
    parser.set_defaults(func=list_volumes)


def init_remove_parser(sub_parsers):
    ''' Initialize remove subparser '''
    remove_parser = sub_parsers.add_parser('remove', aliases=('rm', 'r'),
                                           help='Removes a LogicalVolume')
    remove_parser.add_argument('name', metavar='VG/VID',
                               help='volume_group/volume_name')
    remove_parser.set_defaults(func=remove_volume)


def get_parser():
    '''Create :py:class:`argparse.ArgumentParser` suitable for
    :program:`qubes-lvm`.
    '''
    parser = qubes.tools.QubesArgumentParser(description=__doc__, want_app=True)
    parser.register('action', 'parsers', qubes.tools.AliasedSubParsersAction)
    sub_parsers = parser.add_subparsers(
        title='commands',
        description="For more information see qubes-lvm command -h",
        dest='command')
    init_pool_parser(sub_parsers)
    init_import_parser(sub_parsers)
    init_new_parser(sub_parsers)
    init_volumes_parser(sub_parsers)
    init_remove_parser(sub_parsers)
    init_clone_parser(sub_parsers)

    return parser


def main(args=None):
    '''Main routine of :program:`qubes-lvm`.'''
    args = get_parser().parse_args(args)
    return args.func(args)


if __name__ == '__main__':
    sys.exit(main())
