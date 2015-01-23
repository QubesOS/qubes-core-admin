#!/usr/bin/python -O
# vim: fileencoding=utf-8
# pylint: disable=too-few-public-methods

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

'''qvm-ls - List available domains'''


from __future__ import print_function

import __builtin__
import argparse
import collections
import os
import sys
import textwrap

import qubes
import qubes.config
import qubes.utils


#
# columns
#

class Column(object):
    '''A column in qvm-ls output characterised by its head, a width and a way
    to fetch a parameter describing the domain.

    :param str head: Column head (usually uppercase).
    :param int width: Column width.
    :param str attr: Attribute, possibly complex (containing ``.``). This may \
        also be a callable that gets as its only argument the domain.
    :param str fmt: if specified, used as base for :py:meth:`str.format` for \
        column's value
    :param str doc: Description of column (will be visible in --help-columns).
    '''

    #: collection of all columns
    columns = {}

    def __init__(self, head, width=0, attr=None, fmt=None, doc=None):
        self.ls_head = head
        self.ls_width = max(width, len(self.ls_head) + 1)
        self._fmt = fmt
        self.__doc__ = doc if doc is None else qubes.utils.format_doc(doc)

        # intentionally not always do set self._attr,
        # to cause AttributeError in self.format()
        if attr is not None:
            self._attr = attr

        self.__class__.columns[self.ls_head] = self


    def cell(self, vm):
        '''Format one cell.

        .. note::

            This is only for technical formatting (filling with space). If you
            want to subclass the :py:class:`Column` class, you should override
            :py:meth:`Column.format` method instead.

        :param qubes.vm.qubesvm.QubesVM: Domain to get a value from.
        :returns: string that is at least as wide as needed to fill table row.
        :rtype: str
        '''

        value = self.format(vm) or '-'
        return value.ljust(self.ls_width)


    def format(self, vm):
        '''Format one cell value.

        Return value to put in a table cell.

        :param qubes.vm.qubesvm.QubesVM: Domain to get a value from.
        :returns: Value to put, or :py:obj:`None` if no value .
        :rtype: str or None
        '''

        ret = None
        try:
            if isinstance(self._attr, basestring):
                ret = vm
                for attrseg in self._attr.split('.'):
                    ret = getattr(ret, attrseg)
            elif isinstance(self._attr, collections.Callable):
                ret = self._attr(vm)

        except (AttributeError, ZeroDivisionError):
            # division by 0 may be caused by arithmetic in callable attr
            return None

        if ret is None:
            return None

        if self._fmt is not None:
            return self._fmt.format(ret)

        # late import to avoid circular import
        # pylint: disable=redefined-outer-name
        import qubes.vm
        if isinstance(ret, (qubes.vm.BaseVM, qubes.Label)):
            return ret.name

        return ret


    def __repr__(self):
        return '{}(head={!r}, width={!r})'.format(self.__class__.__name__,
            self.ls_head, self.ls_width)


    def __eq__(self, other):
        return self.ls_head == other.ls_head


    def __lt__(self, other):
        return self.ls_head < other.ls_head


def column(width=0, head=None, fmt=None):
    '''Mark function or plain property as valid column in :program:`qvm-ls`.

    By default all instances of :py:class:`qubes.property` are valid.

    :param int width: Column width
    :param str head: Column head (default: take property's name)
    '''

    def decorator(obj):
        # pylint: disable=missing-docstring
        # we keep hints on fget, so the order of decorators does not matter
        holder = obj.fget if isinstance(obj, __builtin__.property) else obj

        try:
            holder.ls_head = head or holder.__name__.replace('_', '-').upper()
        except AttributeError:
            raise TypeError('Cannot find default column name '
                'for a strange object {!r}'.format(obj))

        holder.ls_width = max(width, len(holder.ls_head) + 1)
        holder.ls_fmt = fmt

        return obj

    return decorator


class PropertyColumn(Column):
    '''Column that displays value from property (:py:class:`property` or
    :py:class:`qubes.property`) of domain.

    You shouldn't use this class directly, see :py:func:`column` decorator.

    :param holder: Holder of magic attributes.
    '''

    def __init__(self, holder):
        super(PropertyColumn, self).__init__(
            head=holder.ls_head,
            width=holder.ls_width,
            doc=holder.__doc__)
        self.holder = holder

    def format(self, vm):
        try:
            value = getattr(vm, self.holder.__name__)
        except AttributeError:
            return None

        if not hasattr(self.holder, 'ls_fmt') or self.holder.ls_fmt is None:
            return value

        return self.holder.ls_fmt.format(
            getattr(vm, self.holder.__name__)).ljust(
            self.ls_width)


    def __repr__(self):
        return '{}(head={!r}, width={!r} holder={!r})'.format(
            self.__class__.__name__,
            self.ls_head,
            self.ls_width,
            self.holder)


def process_class(cls):
    '''Process class after definition to find all listable properties.

    It is used in metaclass of the domain.

    :param qubes.vm.BaseVMMeta cls: Class to round up.
    '''

    for prop in cls.__dict__.values():
        holder = prop.fget if isinstance(prop, __builtin__.property) else prop
        if not hasattr(holder, 'ls_head') or holder.ls_head is None:
            continue

        for col in Column.columns.values():
            if not isinstance(col, PropertyColumn):
                continue

            if col.holder.__name__ != holder.__name__:
                continue

            if col.ls_head != holder.ls_head:
                raise TypeError('Found column head mismatch in class {!r} '
                    '({!r} != {!r})'.format(cls.__name__,
                        holder.ls_head, col.ls_head))

            if col.ls_width != holder.ls_width:
                raise TypeError('Found column width mismatch in class {!r} '
                    '({!r} != {!r})'.format(cls.__name__,
                        holder.ls_width, col.ls_width))

        PropertyColumn(holder)


def flag(field):
    '''Mark method as flag field.

    :param int field: Which field to fill (counted from 1)
    '''

    def decorator(obj):
        # pylint: disable=missing-docstring
        obj.field = field
        return obj
    return decorator


def simple_flag(field, letter, attr, doc=None):
    '''Create simple, binary flag.

    :param str attr: Attribute name to check. If result is true, flag is fired.
    :param str letter: The letter to show.
    '''

    def helper(self, vm):
        # pylint: disable=missing-docstring,unused-argument
        try:
            value = getattr(vm, attr)
        except AttributeError:
            value = False

        if value:
            return letter[0]

    helper.__doc__ = doc
    helper.field = field
    return helper


class StatusColumn(Column):
    '''Some fancy flags that describe general status of the domain.'''
    # pylint: disable=no-self-use

    def __init__(self):
        super(StatusColumn, self).__init__(
            head='STATUS',
            width=len(self.get_flags()) + 1,
            doc=self.__class__.__doc__)


    @flag(1)
    def type(self, vm):
        '''Type of domain.

        0   AdminVM (AKA Dom0)
        aA  AppVM
        dD  DisposableVM
        sS  StandaloneVM
        tT  TemplateVM

        When it is HVM (optimised VM), the letter is capital.
        '''

        # late import because of circular dependency
        # pylint: disable=redefined-outer-name
        import qubes.vm
        import qubes.vm.adminvm
        import qubes.vm.appvm
        import qubes.vm.dispvm
        import qubes.vm.hvm
        import qubes.vm.qubesvm
        import qubes.vm.templatevm

        if isinstance(vm, qubes.vm.adminvm.AdminVM):
            return '0'

        ret = None
        # TODO right order, depending on inheritance
        if isinstance(vm, qubes.vm.templatevm.TemplateVM):
            ret = 't'
        if isinstance(vm, qubes.vm.appvm.AppVM):
            ret = 'a'
#       if isinstance(vm, qubes.vm.standalonevm.StandaloneVM):
#           ret = 's'
        if isinstance(vm, qubes.vm.dispvm.DispVM):
            ret = 'd'

        if ret is not None:
            if isinstance(vm, qubes.vm.hvm.HVM):
                return ret.upper()
            else:
                return ret


    @flag(2)
    def power(self, vm):
        '''Current power state.

        r   running
        t   transient
        p   paused
        s   suspended
        h   halting
        d   dying
        c   crashed
        ?   unknown
        '''

        state = vm.get_power_state().lower()
        if state == 'unknown':
            return '?'
        elif state in ('running', 'transient', 'paused', 'suspended',
                'halting', 'dying', 'crashed'):
            return state[0]


    updateable = simple_flag(3, 'U', 'updateable',
        doc='If the domain is updateable.')

    provides_network = simple_flag(4, 'N', 'provides_network',
        doc='If the domain provides network.')

    installed_by_rpm = simple_flag(5, 'R', 'installed_by_rpm',
        doc='If the domain is installed by RPM.')

    internal = simple_flag(6, 'i', 'internal',
        doc='If the domain is internal (not normally shown, no appmenus).')

    debug = simple_flag(7, 'D', 'debug',
        doc='If the domain is being debugged.')

    autostart = simple_flag(8, 'A', 'autostart',
        doc='If the domain is marked for autostart.')

    # TODO (not sure if really):
    # include in backups
    # uses_custom_config

    def _no_flag(self, vm):
        '''Reserved for future use.'''


    @classmethod
    def get_flags(cls):
        '''Get all flags as list.

        Holes between flags are filled with :py:meth:`_no_flag`.

        :rtype: list
        '''

        flags = {}
        for mycls in cls.__mro__:
            for attr in mycls.__dict__.values():
                if not hasattr(attr, 'field'):
                    continue
                if attr.field in flags:
                    continue
                flags[attr.field] = attr

        return [(flags[i] if i in flags else cls._no_flag)
            for i in range(1, max(flags) + 1)]


    def format(self, vm):
        return ''.join((flag(self, vm) or '-') for flag in self.get_flags())


# todo maxmem

Column('GATEWAY', width=15,
    attr='netvm.gateway',
    doc='Network gateway.')

Column('MEMORY', width=5,
    attr=(lambda vm: vm.get_mem()/1024 if vm.is_running() else None),
    doc='Memory currently used by VM')

Column('DISK', width=5,
    attr=(lambda vm: vm.get_disk_utilization()/1024/1024),
    doc='Total disk utilisation.')


Column('PRIV-CURR', width=5,
    attr=(lambda vm: vm.get_disk_utilization_private_img()/1024/1024),
    fmt='{:.0f}',
    doc='Disk utilisation by private image (/home, /usr/local).')

Column('PRIV-MAX', width=5,
    attr=(lambda vm: vm.get_private_img_sz()/1024/1024),
    fmt='{:.0f}',
    doc='Maximum available space for private image.')

Column('PRIV-USED', width=5,
    attr=(lambda vm: vm.get_disk_utilization_private_img() * 100
        / vm.get_private_img_sz()),
    fmt='{:.0f}',
    doc='Disk utilisation by private image as a percentage of available space.')


Column('ROOT-CURR', width=5,
    attr=(lambda vm: vm.get_disk_utilization_private_img()/1024/1024),
    fmt='{:.0f}',
    doc='Disk utilisation by root image (/usr, /lib, /etc, ...).')

Column('ROOT-MAX', width=5,
    attr=(lambda vm: vm.get_private_img_sz()/1024/1024),
    fmt='{:.0f}',
    doc='Maximum available space for root image.')

Column('ROOT-USED', width=5,
    attr=(lambda vm: vm.get_disk_utilization_private_img() * 100
        / vm.get_private_img_sz()),
    fmt='{:.0f}',
    doc='Disk utilisation by root image as a percentage of available space.')


StatusColumn()


class Table(object):
    '''Table that is displayed to the user.

    :param qubes.Qubes app: Qubes application object.
    :param list colnames: Names of the columns (need not to be uppercase).
    '''
    def __init__(self, app, colnames):
        self.app = app
        self.columns = tuple(Column.columns[col.upper()] for col in colnames)


    def format_head(self):
        '''Format table head (all column heads).'''
        return ''.join('{head:{width}s}'.format(
                head=col.ls_head, width=col.ls_width)
            for col in self.columns[:-1]) + \
            self.columns[-1].ls_head


    def format_row(self, vm):
        '''Format single table row (all columns for one domain).'''
        return ''.join(col.cell(vm) for col in self.columns)


    def write_table(self, stream=sys.stdout):
        '''Write whole table to file-like object.

        :param file stream: Stream to write the table to.
        '''

        stream.write(self.format_head() + '\n')
        for vm in self.app.domains:
            stream.write(self.format_row(vm) + '\n')


#: Available formats. Feel free to plug your own one.
formats = {
    'simple': ('name', 'status', 'label', 'template', 'netvm'),
    'network': ('name', 'status', 'netvm', 'ip', 'ipback', 'gateway'),
    'full': ('name', 'status', 'label', 'qid', 'xid', 'uuid'),
#   'perf': ('name', 'status', 'cpu', 'memory'),
    'disk': ('name', 'status', 'disk',
        'priv-curr', 'priv-max', 'priv-used',
        'root-curr', 'root-max', 'root-used'),
}


class _HelpColumnsAction(argparse.Action):
    '''Action for argument parser that displays all columns and exits.'''
    # pylint: disable=redefined-builtin
    def __init__(self,
            option_strings,
            dest=argparse.SUPPRESS,
            default=argparse.SUPPRESS,
            help='list all available columns with short descriptions and exit'):
        super(_HelpColumnsAction, self).__init__(
            option_strings=option_strings,
            dest=dest,
            default=default,
            nargs=0,
            help=help)

    def __call__(self, parser, namespace, values, option_string=None):
        width = max(len(column.ls_head) for column in Column.columns.values())
        wrapper = textwrap.TextWrapper(width=80,
            initial_indent='  ', subsequent_indent=' ' * (width + 6))

        text = 'Available columns:\n' + '\n'.join(
            wrapper.fill('{head:{width}s}  {doc}'.format(
                head=column.ls_head,
                doc=column.__doc__ or '',
                width=width))
            for column in sorted(Column.columns.values()))
        parser.exit(message=text + '\n')

class _HelpFormatsAction(argparse.Action):
    '''Action for argument parser that displays all formats and exits.'''
    # pylint: disable=redefined-builtin
    def __init__(self,
            option_strings,
            dest=argparse.SUPPRESS,
            default=argparse.SUPPRESS,
            help='list all available formats with their definitions and exit'):
        super(_HelpFormatsAction, self).__init__(
            option_strings=option_strings,
            dest=dest,
            default=default,
            nargs=0,
            help=help)

    def __call__(self, parser, namespace, values, option_string=None):
        width = max(len(fmt) for fmt in formats)
        text = 'Available formats:\n' + ''.join(
            '  {fmt:{width}s}  {columns}\n'.format(
                fmt=fmt, columns=','.join(formats[fmt]).upper(), width=width)
            for fmt in sorted(formats))
        parser.exit(message=text)


def get_parser():
    '''Create :py:class:`argparse.ArgumentParser` suitable for
    :program:`qvm-ls`.
    '''
    # parser creation is delayed to get all the columns that are scattered
    # thorough the modules

    wrapper = textwrap.TextWrapper(width=80, break_on_hyphens=False,
        initial_indent='  ', subsequent_indent='  ')

    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawTextHelpFormatter,
        description='List Qubes domains and their parametres.',
        epilog='available formats (see --help-formats):\n{}\n\n'
               'available columns (see --help-columns):\n{}'.format(
                wrapper.fill(', '.join(sorted(formats.keys()))),
                wrapper.fill(', '.join(sorted(sorted(Column.columns.keys()))))))

    parser.add_argument('--help-columns', action=_HelpColumnsAction)
    parser.add_argument('--help-formats', action=_HelpFormatsAction)


    parser_formats = parser.add_mutually_exclusive_group()

    parser_formats.add_argument('--format', '-o', metavar='FORMAT',
        action='store', choices=formats.keys(),
        help='preset format')

    parser_formats.add_argument('--fields', '-O', metavar='FIELD,...',
        action='store',
        help='user specified format (see available columns below)')


#   parser.add_argument('--conf', '-c',
#       action='store', metavar='CFGFILE',
#       help='Qubes config file')

    parser.add_argument('--xml', metavar='XMLFILE',
        action='store',
        help='Qubes store file')

    parser.set_defaults(
        qubesxml=os.path.join(qubes.config.system_path['qubes_base_dir'],
            qubes.config.system_path['qubes_store_filename']),
        format='simple')

    return parser


def main(args=None):
    '''Main routine of :program:`qvm-ls`.

    :param list args: Optional arguments to override those delivered from \
        command line.
    '''

    parser = get_parser()
    args = parser.parse_args(args)
    app = qubes.Qubes(args.xml)

    if args.fields:
        columns = [col.strip() for col in args.fields.split(',')]
        for col in columns:
            if col.upper() not in Column.columns:
                parser.error('no such column: {!r}'.format(col))
    else:
        columns = formats[args.format]

    table = Table(app, columns)
    table.write_table(sys.stdout)

    return True


if __name__ == '__main__':
    sys.exit(not main())
