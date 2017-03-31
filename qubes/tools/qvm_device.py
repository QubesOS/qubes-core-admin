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
        output += [(
            "{!s}:{!s}".format(dev.backend_domain, dev.ident),
            dev.description,
            str(dev.frontend_domain) if dev.frontend_domain else "",
        )]

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
    vm.devices[args.devclass].attach(device)


def detach_device(args):
    ''' Called by the parser to execute the :program:`qvm-devices detach`
        subcommand.
    '''
    device = args.device
    vm = args.domains[0]
    vm.devices[args.devclass].detach(device)


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
    ''' Action for argument parser that gets the
        :py:class:``qubes.device.DeviceInfo`` from a BACKEND:DEVICE_ID string.
    '''  # pylint: disable=too-few-public-methods

    def __init__(self, help='A pool & volume id combination',
                 required=True, **kwargs):
        # pylint: disable=redefined-builtin
        super(DeviceAction, self).__init__(help=help, required=required,
                                           **kwargs)

    def __call__(self, parser, namespace, values, option_string=None):
        ''' Set ``namespace.vmname`` to ``values`` '''
        setattr(namespace, self.dest, values)

    def parse_qubes_app(self, parser, namespace):
        assert hasattr(namespace, 'app')
        app = namespace.app

        assert hasattr(namespace, 'device')
        backend_device_id = getattr(namespace, self.dest)

        assert hasattr(namespace, 'devclass')
        devclass = namespace.devclass

        try:
            vmname, device_id = backend_device_id.split(':', 1)
            try:
                vm = app.domains[vmname]
            except KeyError:
                parser.error_runtime("no backend vm {!r}".format(vmname))

            try:
                device = vm.devices[devclass][device_id]
            except KeyError:
                parser.error_runtime(
                    "backend vm {!r} doesn't expose device {!r}"
                    .format(vmname, device_id))
            device_assignment = qubes.devices.DeviceAssignment(vm, device_id,)
            setattr(namespace, 'device_assignment', device_assignment)
        except ValueError:
            parser.error('expected a backend vm & device id combination ' \
                         'like foo:bar got %s' % backend_device_id)


def get_parser(device_class=None):
    '''Create :py:class:`argparse.ArgumentParser` suitable for
    :program:`qvm-block`.
    '''
    parser = qubes.tools.QubesArgumentParser(description=__doc__, want_app=True)
    parser.register('action', 'parsers', qubes.tools.AliasedSubParsersAction)
    if device_class:
        parser.add_argument('devclass', const=device_class,
            action='store_const',
            help=argparse.SUPPRESS)
    else:
        parser.add_argument('devclass', metavar='DEVICE_CLASS', action='store',
            help="Device class to manage ('pci', 'usb', etc)")
    sub_parsers = parser.add_subparsers(
        title='commands',
        description="For more information see qvm-device command -h",
        dest='command')
    init_list_parser(sub_parsers)
    attach_parser = sub_parsers.add_parser(
        'attach', help="Attach device to domain", aliases=('at', 'a'))
    detach_parser = sub_parsers.add_parser(
        "detach", help="Detach device from domain", aliases=('d', 'dt'))

    attach_parser.add_argument('VMNAME', action=qubes.tools.RunningVmNameAction)
    detach_parser.add_argument('VMNAME', action=qubes.tools.RunningVmNameAction)

    if device_class == 'block':
        attach_parser.add_argument(metavar='BACKEND:DEVICE_ID', dest='device',
                                action=qubes.tools.VolumeAction)
        detach_parser.add_argument(metavar='BACKEND:DEVICE_ID', dest='device',
                                    action=qubes.tools.VolumeAction)
    else:
        attach_parser.add_argument(metavar='BACKEND:DEVICE_ID',
                                   dest='device',
                                   action=DeviceAction)
        detach_parser.add_argument(metavar='BACKEND:DEVICE_ID',
                                   dest='device',
                                   action=DeviceAction)

    attach_parser.set_defaults(func=attach_device)
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
        print(str(e), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
