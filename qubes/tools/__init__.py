#!/usr/bin/python2 -O
# vim: fileencoding=utf-8

#
# The Qubes OS Project, https://www.qubes-os.org/
#
# Copyright (C) 2015  Joanna Rutkowska <joanna@invisiblethingslab.com>
# Copyright (C) 2015  Wojtek Porczyk <woju@invisiblethingslab.com>
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

'''Qubes' command line tools
'''

import argparse
import importlib
import os


# TODO --verbose, logger setup
def get_parser_base(want_force_root=False, **kwargs):
    '''Get base parser with options common to all Qubes OS tools.

    :param bool want_force_root: add ``--force-root`` option
    *kwargs* are passed to :py:class:`argparser.ArgumentParser`.

    Currently supported options: ``--force-root`` (optional), ``--xml``.
    '''
    parser = argparse.ArgumentParser(**kwargs)

    parser.add_argument('--xml', metavar='XMLFILE',
        action='store',
        help='Qubes OS store file')

    if want_force_root:
        parser.add_argument('--force-root',
            action='store_true', default=False,
            help='Force to run as root.')

    return parser


def get_parser_for_command(command):
    '''Get parser for given qvm-tool.

    :param str command: command name
    :rtype: argparse.ArgumentParser
    :raises ImportError: when command's module is not found
    :raises AttributeError: when parser was not found
    '''

    module = importlib.import_module(
        '.' + command.replace('-', '_'), 'qubes.tools')

    try:
        parser = module.parser
    except AttributeError:
        try:
            parser = module.get_parser()
        except AttributeError:
            raise AttributeError('cannot find parser in module')

    return parser


def dont_run_as_root(parser, args):
    '''Prevent running as root.

    :param argparse.ArgumentParser parser: parser on which we invoke error
    :param argparse.Namespace args: if there is ``.force_root`` attribute set \
        to true, run anyway
    :return: If we should back off
    :rtype bool:
    '''
    try:
        euid = os.geteuid()
    except AttributeError: # no geteuid(), probably NT
        return

    if euid == 0 and not args.force_root:
        parser.error('refusing to run as root; add --force-root to override')
