#!/usr/bin/python2
# pylint: disable=C,R
# -*- encoding: utf8 -*-
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

'''Qubes volume and block device managment'''

from __future__ import print_function

import sys

import qubes
import qubes.exc
import qubes.tools
import qubes.utils


def prepare_table(vd_list, full=False):
    ''' Converts a list of :py:class:`VolumeData` objects to a list of tupples
        for the :py:func:`qubes.tools.print_table`.

        If :program:`qvm-block` is running in a TTY, it will ommit duplicate
        data.

        :param list vd_list: List of :py:class:`VolumeData` objects.
        :param bool full:    If set to true duplicate data is printed even when
                             running from TTY.
        :returns: list of tupples
    '''
    output = []
    if sys.stdout.isatty():
        output += [('POOL:VOLUME', 'VMNAME', 'VOLUME_NAME')]  # NOQA

    for volume in vd_list:
        if volume.domains:
            vmname, volume_name = volume.domains.pop()
            output += [(str(volume), vmname, volume_name, volume.revisions)]
            for tupple in volume.domains:
                vmname, volume_name = tupple
                if full or not sys.stdout.isatty():
                    output += [(str(volume), vmname, volume_name,
                            volume.revisions)]
                else:
                    output += [('', vmname, volume_name, '', volume.revisions)]
        else:
            output += [(str(volume), "")]

    return output


class VolumeData(object):
    ''' Wrapper object around :py:class:`qubes.storage.Volume`, mainly to track
        the domains a volume is attached to.
    '''
    # pylint: disable=too-few-public-methods
    def __init__(self, volume):
        self.name = volume.name
        self.pool = volume.pool
        self.vid = volume.vid
        if volume.revisions != {}:
            self.revisions = 'Yes'
        else:
            self.revisions = 'No'
        self.domains = []

    def __str__(self):
        return "{!s}:{!s}".format(self.pool, self.vid)


def list_volumes(args):
    ''' Called by the parser to execute the qubes-block list subcommand. '''
    app = args.app

    if args.pools:
        pools = args.pools  # only specified pools
    else:
        pools = app.pools.values()  # all pools

    volumes = [v for p in pools for v in p.volumes]

    if not args.internal:  # hide internal volumes
        volumes = [v for v in volumes if not v.internal]

    vd_dict = {}

    for volume in volumes:
        volume_data = VolumeData(volume)
        try:
            vd_dict[volume.pool][volume.vid] = volume_data
        except KeyError:
            vd_dict[volume.pool] = {volume.vid: volume_data}

    if hasattr(args, 'domains') and args.domains:
        domains = args.domains
    else:
        domains = args.app.domains
    for domain in domains:  # gather the domain names
        try:
            for volume in domain.attached_volumes:
                try:
                    volume_data = vd_dict[volume.pool][volume.vid]
                    volume_data.domains += [(domain.name, volume.name)]
                except KeyError:
                    # Skipping volume
                    continue
        except AttributeError:
            # Skipping domain without volumes
            continue

    if hasattr(args, 'domains') and args.domains:
        result = [x  # reduce to only VolumeData with assigned domains
                  for p in vd_dict.itervalues() for x in p.itervalues()
                  if x.domains]
    else:
        result = [x for p in vd_dict.itervalues() for x in p.itervalues()]
    qubes.tools.print_table(prepare_table(result, full=args.full))

def revert_volume(args):
    volume = args.volume
    app = args.app
    try:
        pool = app.pools[volume.pool]
        pool.revert(volume)
    except qubes.storage.StoragePoolException as e:
        print(e.message, file=sys.stderr)
        sys.exit(1)

def attach_volumes(args):
    ''' Called by the parser to execute the :program:`qvm-block attach`
        subcommand.
    '''
    volume = args.volume
    vm = args.domains[0]
    try:
        rw = not args.ro
        vm.storage.attach(volume, rw=rw)
    except qubes.storage.StoragePoolException as e:
        print(e.message, file=sys.stderr)
        sys.exit(1)


def detach_volumes(args):
    ''' Called by the parser to execute the :program:`qvm-block detach`
        subcommand.
    '''
    volume = args.volume
    vm = args.domains[0]
    try:
        vm.storage.detach(volume)
    except qubes.storage.StoragePoolException as e:
        print(e.message, file=sys.stderr)
        sys.exit(1)


def extend_volumes(args):
    ''' Called by the parser to execute the :program:`qvm-block extend`
        subcommand
    '''
    volume = args.volume
    app = args.app
    size = qubes.utils.parse_size(args.size)
    pool = app.get_pool(volume.pool)
    pool.resize(volume, volume.size+size)
    app.save()

def init_list_parser(sub_parsers):
    ''' Configures the parser for the :program:`qvm-block list` subcommand '''
    # pylint: disable=protected-access
    list_parser = sub_parsers.add_parser('list', aliases=('ls', 'l'),
                                         help='list block devices')
    list_parser.add_argument('-p', '--pool', dest='pools',
                             action=qubes.tools.PoolsAction)
    list_parser.add_argument('-i', '--internal', action='store_true',
                             help='Show internal volumes')
    list_parser.add_argument(
        '--full', action='store_true',
        help='print full line for each POOL_NAME:VOLUME_ID & vm combination')

    vm_name_group = qubes.tools.VmNameGroup(
        list_parser, required=False, vm_action=qubes.tools.VmNameAction,
        help='list volumes from specified domain(s)')
    list_parser._mutually_exclusive_groups.append(vm_name_group)
    list_parser.set_defaults(func=list_volumes)

def init_revert_parser(sub_parsers):
    revert_parser = sub_parsers.add_parser(
        'revert', aliases=('rv', 'r'),
        help='revert volume to previous revision')
    revert_parser.add_argument(metavar='POOL_NAME:VOLUME_ID', dest='volume',
                               action=qubes.tools.VolumeAction)
    revert_parser.set_defaults(func=revert_volume)

def init_attach_parser(sub_parsers):
    attach_parser = sub_parsers.add_parser(
        'attach', help="Attach volume to domain", aliases=('at', 'a'))
    attach_parser.add_argument('--ro', help='attach device read-only',
                               action='store_true')
    attach_parser.add_argument('VMNAME', action=qubes.tools.RunningVmNameAction)
    attach_parser.add_argument(metavar='POOL_NAME:VOLUME_ID', dest='volume',
                               action=qubes.tools.VolumeAction)
    attach_parser.set_defaults(func=attach_volumes)


def init_dettach_parser(sub_parsers):
    detach_parser = sub_parsers.add_parser(
        "detach", help="Detach volume from domain", aliases=('d', 'dt'))
    detach_parser.add_argument('VMNAME', action=qubes.tools.RunningVmNameAction)
    detach_parser.add_argument(metavar='POOL_NAME:VOLUME_ID', dest='volume',
                               action=qubes.tools.VolumeAction)
    detach_parser.set_defaults(func=detach_volumes)

def init_extend_parser(sub_parsers):
    extend_parser = sub_parsers.add_parser(
        "extend", help="extend volume from domain", aliases=('d', 'dt'))
    extend_parser.add_argument(metavar='POOL_NAME:VOLUME_ID', dest='volume',
                               action=qubes.tools.VolumeAction)
    extend_parser.add_argument(
        'size', help='size in bytes of the new ThinPoolLogicalVolume')
    extend_parser.set_defaults(func=extend_volumes)

def get_parser():
    '''Create :py:class:`argparse.ArgumentParser` suitable for
    :program:`qvm-block`.
    '''
    parser = qubes.tools.QubesArgumentParser(description=__doc__, want_app=True)
    parser.register('action', 'parsers', qubes.tools.AliasedSubParsersAction)
    sub_parsers = parser.add_subparsers(
        title='commands',
        description="For more information see qvm-block command -h",
        dest='command')
    init_attach_parser(sub_parsers)
    init_dettach_parser(sub_parsers)
    init_extend_parser(sub_parsers)
    init_list_parser(sub_parsers)
    init_revert_parser(sub_parsers)

    return parser


def main(args=None):
    '''Main routine of :program:`qvm-block`.'''
    args = get_parser().parse_args(args)
    args.func(args)


if __name__ == '__main__':
    sys.exit(main())
