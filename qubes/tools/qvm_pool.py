#!/usr/bin/python2
# -*- encoding: utf8 -*-
# :pylint: disable=too-few-public-methods
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
'''Manages Qubes pools and their options'''

from __future__ import print_function

import argparse
import sys

import qubes
import qubes.ext
import qubes.storage
import qubes.tools

drivers = qubes.storage.pool_drivers()


class _HelpDrivers(argparse.Action):
    ''' Action for argument parser that displays all drivers and their options
        and exits.
    '''

    def __init__(self,
                 option_strings,
                 dest=argparse.SUPPRESS,
                 default=argparse.SUPPRESS):
        super(_HelpDrivers, self).__init__(
            option_strings=option_strings,
            dest=dest,
            default=default,
            nargs=0,
            help='list all drivers with their options and exit')

    def __call__(self, parser, namespace, values, option_string=None):
        result = []
        for driver in drivers:
            params = driver_parameters(driver)
            driver_options = ', '.join(params)
            result += [(driver, 'driver options', driver_options)]
        qubes.tools.print_table(result)
        parser.exit(0)


class _Info(qubes.tools.PoolsAction):
    ''' Action for argument parser that displays pool info and exits. '''

    def __init__(self, option_strings, help='print pool info and exit',
                 **kwargs):
        super(_Info, self).__init__(option_strings, help=help, **kwargs)

    def __call__(self, parser, namespace, values, option_string=None):
        setattr(namespace, 'command', 'info')
        super(_Info, self).__call__(parser, namespace, values, option_string)


def pool_info(pool):
    ''' Prints out pool name and config '''
    data = [("name", pool.name)]
    data += [i for i in pool.config.items() if i[0] != 'name']
    qubes.tools.print_table(data)


def list_pools(app):
    ''' Prints out all known pools and their drivers '''
    result = [('NAME', 'DRIVER')]
    for pool in app.pools.values():
        result += [(pool.name, pool.driver)]
    qubes.tools.print_table(result)


class _Remove(argparse.Action):
    ''' Action for argument parser that removes a pool '''

    def __init__(self, option_strings, dest=None, default=None, metavar=None):
        super(_Remove, self).__init__(option_strings=option_strings,
                                      dest=dest,
                                      metavar=metavar,
                                      default=default,
                                      help='remove pool')

    def __call__(self, parser, namespace, name, option_string=None):
        app = qubes.Qubes(namespace.app)
        if name in app.pools.keys():
            setattr(namespace, 'command', 'remove')
            setattr(namespace, 'name', name)
        else:
            parser.error('no such pool %s\n' % name)


class _Add(argparse.Action):
    ''' Action for argument parser that adds a pool. '''

    def __init__(self, option_strings, dest=None, default=None, metavar=None):
        super(_Add, self).__init__(option_strings=option_strings,
                                   dest=dest,
                                   metavar=metavar,
                                   default=default,
                                   nargs=2,
                                   help='add pool')

    def __call__(self, parser, namespace, values, option_string=None):
        app = qubes.Qubes(namespace.app)
        name, driver = values

        if name in app.pools.keys():
            parser.error('pool named %s already exists \n' % name)
        elif driver not in drivers:
            parser.error('driver %s is unknown \n' % driver)
        else:
            setattr(namespace, 'command', 'add')
            setattr(namespace, 'name', name)
            setattr(namespace, 'driver', driver)


class _Options(argparse.Action):
    ''' Action for argument parser that parsers options. '''

    def __init__(self, option_strings, dest, default, metavar='options'):
        super(_Options, self).__init__(
            option_strings=option_strings,
            dest=dest,
            metavar=metavar,
            default=default,
            help='comma-separated list of driver options')

    def __call__(self, parser, namespace, options, option_string=None):
        result = {}
        for option in options.split(','):
            if option.count('=') != 1:
                parser.error('option %s should have form option=value' %
                             option)
            name, value = option.split('=')
            result[name] = value
        setattr(namespace, 'options', result)


def get_parser():
    ''' Parses the provided args '''
    epilog = 'available pool drivers: ' \
        + ', '.join(drivers)
    parser = qubes.tools.QubesArgumentParser(description=__doc__,
                                             epilog=epilog)
    parser.add_argument('--help-drivers', action=_HelpDrivers)
    parser.add_argument('-o', action=_Options, dest='options', default={})
    group = parser.add_mutually_exclusive_group()
    group.add_argument('-l',
                       '--list',
                       dest='command',
                       const='list',
                       action='store_const',
                       help='list all pools and exit (default action)')
    group.add_argument('-i', '--info', metavar='POOLNAME', dest='pools',
                       action=_Info, default=[])
    group.add_argument('-a',
                       '--add',
                       action=_Add,
                       dest='command',
                       metavar=('NAME', 'DRIVER'))
    group.add_argument('-r', '--remove', metavar='NAME', action=_Remove)
    return parser


def driver_parameters(name):
    ''' Get __init__ parameters from a driver with out `self` & `name`. '''
    init_function = qubes.utils.get_entry_point_one(
        qubes.storage.STORAGE_ENTRY_POINT, name).__init__
    params = init_function.func_code.co_varnames
    ignored_params = ['self', 'name']
    return [p for p in params if p not in ignored_params]


def main(args=None):
    '''Main routine of :program:`qvm-pools`.

    :param list args: Optional arguments to override those delivered from \
        command line.
    '''
    args = get_parser().parse_args(args)
    if args.command is None or args.command == 'list':
        list_pools(args.app)
    elif args.command == 'add':
        args.app.add_pool(name=args.name, driver=args.driver, **args.options)
        args.app.save()
    elif args.command == 'remove':
        args.app.remove_pool(args.name)
        args.app.save()
    elif args.command == 'info':
        pool_info(args.pools)
    return 0


if __name__ == '__main__':
    sys.exit(main())
