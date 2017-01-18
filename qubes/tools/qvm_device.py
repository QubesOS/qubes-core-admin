#!/usr/bin/python2
# coding=utf-8
# pylint: disable=C,R
#
# The Qubes OS Project, http://www.qubes-os.org
#
# Copyright (C) 2016 Bahtiar `kalkin-` Gadimov <bahtiar@gadimov.de>
# Copyright (C) 2016 Marek Marczykowski-Górecki
#                              <marmarek@invisiblethingslab.com>
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

import argparse
import os
import sys

import pkg_resources
import qubes
import qubes.devices
import qubes.exc
import qubes.tools


def prepare_table(dev_list):
    ''' Converts a list of :py:class:`qubes.devices.DeviceInfo` objects to a
    list of tupples for the :py:func:`qubes.tools.print_table`.

        If :program:`qvm-devices` is running in a TTY, it will ommit duplicate
        data.

        :param list dev_list: List of :py:class:`qubes.devices.DeviceInfo`
        objects.
        :returns: list of tupples
    '''
    output = []
    header = []
    if sys.stdout.isatty():
        header += [('BACKEND:DEVID', 'DESCRIPTION', 'USED BY')]  # NOQA

    for dev in dev_list:
        output += [("{!s}:{!s}".format(dev.backend_domain, dev.ident),
                    str(dev.description),
                    str(dev.frontend_domain) if dev.frontend_domain else "", )]

    return header + sorted(output)


def list_devices(args):
    ''' Called by the parser to execute the qubes-devices list
    subcommand. '''
    app = args.app

    result = []
    if hasattr(args, 'domains') and args.domains:
        for domain in args.domains:
            result.extend(domain.devices[args.devclass].attached())
    else:
        for backend in app.domains:
            result.extend(backend.devices[args.devclass])

    qubes.tools.print_table(prepare_table(result))


def attach_device(args):
    ''' Called by the parser to execute the :program:`qvm-devices attach`
        subcommand.
    '''
    device = args.device
    vm = args.domains[0]
    persistent = args.persistent
    vm.devices[args.devclass].attach(device, persistent=persistent)
    if persistent:
        args.app.save()


def detach_device(args):
    ''' Called by the parser to execute the :program:`qvm-devices detach`
        subcommand.
    '''
    device = args.device
    vm = args.domains[0]
    was_persistent = False
    if device in vm.devices[args.devclass].attached(persistent=True):
        was_persistent = True
    vm.devices[args.devclass].detach(device, persistent=args.only_once)
    if was_persistent:
        args.app.save()


def init_list_parser(sub_parsers):
    ''' Configures the parser for the :program:`qvm-devices list` subcommand '''
    # pylint: disable=protected-access
    list_parser = sub_parsers.add_parser('list', aliases=('ls', 'l'),
                                         help='list devices')

    vm_name_group = qubes.tools.VmNameGroup(
        list_parser, required=False, vm_action=qubes.tools.VmNameAction,
        help='list devices assigned to specific domain(s)')
    list_parser._mutually_exclusive_groups.append(vm_name_group)
    list_parser.set_defaults(func=list_devices)


class DeviceAction(qubes.tools.QubesAction):
    ''' Validates the device string and sets the corresponding
        `qubes.devices.DeviceInfo` object.
    ''' # pylint: disable=too-few-public-methods
    def __init__(self, help='A domain & device id combination',
                 required=True, allow_unknown=False, **kwargs):
        # pylint: disable=redefined-builtin
        super(DeviceAction, self).__init__(help=help, required=required,
                                           **kwargs)
        self.allow_unknown = allow_unknown

    def __call__(self, parser, namespace, values, option_string=None):
        ''' Set ``namespace.device`` to ``values`` '''
        setattr(namespace, self.dest, values)

    def parse_qubes_app(self, parser, namespace):
        ''' Acquire the :py:class:``qubes.devices.DeviceInfo`` object from
            ``namespace.app``.
        '''
        assert hasattr(namespace, 'app')
        assert hasattr(namespace, 'devclass')
        app = namespace.app
        devclass = namespace.devclass

        try:
            backend_name, devid = getattr(namespace, self.dest).split(':', 1)
            try:
                backend = app.domains[backend_name]
                dev = backend.devices[devclass][devid]
                if not self.allow_unknown and isinstance(dev,
                        qubes.devices.UnknownDevice):
                    parser.error_runtime('no device {!r} in qube {!r}'.format(
                        backend_name, devid))
                setattr(namespace, self.dest, dev)
            except KeyError:
                parser.error_runtime('no domain {!r}'.format(backend_name))
        except ValueError:
            parser.error('expected a domain & device id combination like '
                         'foo:bar')


def get_parser(device_class=None):
    '''Create :py:class:`argparse.ArgumentParser` suitable for
    :program:`qvm-block`.
    '''
    parser = qubes.tools.QubesArgumentParser(description=__doc__, want_app=True)
    parser.register('action', 'parsers', qubes.tools.AliasedSubParsersAction)
    all_classes = [entry.name
               # pylint: disable=no-member
               for entry in pkg_resources.iter_entry_points('qubes.devices')]
    if device_class:
        parser.add_argument('devclass', const=device_class,
            action='store_const', help=argparse.SUPPRESS)
    else:
        parser.add_argument('devclass', metavar='DEVICE_CLASS', action='store',
            choices=all_classes, help="Device class to manage (%s)" %
            ', '.join(all_classes))
    sub_parsers = parser.add_subparsers(
        title='commands',
        description="For more information see qvm-device command -h",
        dest='command')
    init_list_parser(sub_parsers)
    attach_parser = sub_parsers.add_parser(
        'attach', help="Attach device to domain", aliases=('at', 'a'))
    attach_parser.add_argument('VMNAME', action=qubes.tools.RunningVmNameAction)
    attach_parser.add_argument(metavar='BACKEND:DEVICE_ID', dest='device',
                               action=DeviceAction)
    attach_parser.add_argument('-p', '--persistent', action='store_true',
        help='attach on startup', default=False, required=False)
    attach_parser.set_defaults(func=attach_device)
    detach_parser = sub_parsers.add_parser(
        "detach", help="Detach device from domain", aliases=('d', 'dt'))
    detach_parser.add_argument('VMNAME', action=qubes.tools.RunningVmNameAction)
    detach_parser.add_argument(metavar='BACKEND:DEVICE_ID', dest='device',
                               action=DeviceAction)
    detach_parser.add_argument('-o', '--only-once', action='store_false',
        help='device will still be attached on next startup', default=False, required=False)
    detach_parser.set_defaults(func=detach_device)

    return parser


def main(args=None):
    '''Main routine of :program:`qvm-block`.'''
    basename = os.path.basename(sys.argv[0])
    devclass = None
    if basename.startswith('qvm-') and basename != 'qvm-device':
        devclass = basename[4:]
    args = get_parser(devclass).parse_args(args)
    try:
        args.func(args)
    except qubes.exc.QubesException as e:
        print(e.message, file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
