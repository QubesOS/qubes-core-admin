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

import qubes.log


class PropertyAction(argparse.Action):
    '''Action for argument parser that stores a property.'''
    # pylint: disable=redefined-builtin
    def __init__(self,
            option_strings,
            dest,
            metavar='NAME=VALUE',
            required=False,
            help='set property to a value'):
        super(PropertyAction, self).__init__(option_strings, 'properties',
            metavar=metavar, default={}, help=help)

    def __call__(self, parser, namespace, values, option_string=None):
        try:
            prop, value = values.split('=', 1)
        except ValueError:
            parser.error('invalid property token: {!r}'.format(token))

        getattr(namespace, self.dest)[prop] = value


class SinglePropertyAction(argparse.Action):
    '''Action for argument parser that stores a property.'''

    # pylint: disable=redefined-builtin
    def __init__(self,
            option_strings,
            dest,
            metavar='VALUE',
            const=None,
            nargs=None,
            required=False,
            help=None):
        if help is None:
            help = 'set {!r} property to a value'.format(dest)
            if const is not None:
                help += ' {!r}'.format(const)

        if const is not None:
            nargs = 0

        super(SinglePropertyAction, self).__init__(option_strings, 'properties',
            metavar=metavar, help=help, default={}, const=const,
            nargs=nargs)

        self.name = dest


    def __call__(self, parser, namespace, values, option_string=None):
        getattr(namespace, self.dest)[self.name] = values \
            if self.const is None else self.const


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
        help=argparse.SUPPRESS)

    parser.add_argument('--verbose', '-v',
        action='count',
        help='increase verbosity')

    parser.add_argument('--quiet', '-q',
        action='count',
        help='decrease verbosity')

    if want_force_root:
        parser.add_argument('--force-root',
            action='store_true', default=False,
            help='Force to run as root.')

    parser.set_defaults(verbose=1, quiet=0)

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


def set_verbosity(parser, args):
    '''Apply a verbosity setting.

    This is done by configuring global logging.
    :param argparse.ArgumentParser parser: command parser
    :param argparse.Namespace args: args as parsed by parser
    '''

    verbose = args.verbose - args.quiet

    if verbose >= 2:
        qubes.log.enable_debug()
    elif verbose >= 1:
        qubes.log.enable()
