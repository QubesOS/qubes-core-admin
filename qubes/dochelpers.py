#!/usr/bin/python2 -O
# vim: fileencoding=utf-8

#
# The Qubes OS Project, https://www.qubes-os.org/
#
# Copyright (C) 2010-2015  Joanna Rutkowska <joanna@invisiblethingslab.com>
# Copyright (C) 2014-2015  Wojtek Porczyk <woju@invisiblethingslab.com>
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

'''Documentation helpers.

This module contains classes and functions which help to maintain documentation,
particularly our custom Sphinx extension.
'''

import csv
import os
import posixpath
import re
import StringIO
import urllib2

import docutils
import docutils.nodes
import docutils.parsers.rst
import docutils.parsers.rst.roles
import docutils.statemachine
import sphinx
import sphinx.errors
import sphinx.locale
import sphinx.util.docfields

import qubes.tools


def fetch_ticket_info(uri):
    '''Fetch info about particular trac ticket given

    :param str uri: URI at which ticket resides
    :rtype: mapping
    :raises: urllib2.HTTPError
    '''

    data = urllib2.urlopen(uri + '?format=csv').read()
    reader = csv.reader((line + '\n' for line in data.split('\r\n')),
        quoting=csv.QUOTE_MINIMAL, quotechar='"')

    return dict(zip(*((cell.decode('utf-8') for cell in row)
        for row in list(reader)[:2])))


def ticket(name, rawtext, text, lineno, inliner, options=None, content=None):
    '''Link to qubes ticket

    :param str name: The role name used in the document
    :param str rawtext: The entire markup snippet, with role
    :param str text: The text marked with the role
    :param int lineno: The line number where rawtext appears in the input
    :param docutils.parsers.rst.states.Inliner inliner: The inliner instance \
        that called this function
    :param options: Directive options for customisation
    :param content: The directive content for customisation
    ''' # pylint: disable=unused-argument

    if options is None:
        options = {}

    ticketno = text.lstrip('#')
    if not ticketno.isdigit():
        msg = inliner.reporter.error(
            'Invalid ticket identificator: {!r}'.format(text), line=lineno)
        prb = inliner.problematic(rawtext, rawtext, msg)
        return [prb], [msg]

    app = inliner.document.settings.env.app
    uri = posixpath.join(app.config.ticket_base_uri, ticketno)
    try:
        info = fetch_ticket_info(uri)
    except urllib2.HTTPError, e:
        msg = inliner.reporter.error(
            'Error while fetching ticket info: {!s}'.format(e), line=lineno)
        prb = inliner.problematic(rawtext, rawtext, msg)
        return [prb], [msg]

    docutils.parsers.rst.roles.set_classes(options)

    node = docutils.nodes.reference(
        rawtext,
        '#{} ({})'.format(ticketno, info['summary']),
        refuri=uri,
        **options)

    return [node], []


class versioncheck(docutils.nodes.warning):
    # pylint: disable=invalid-name
    pass

def visit(self, node):
    self.visit_admonition(node, 'version')

def depart(self, node):
    self.depart_admonition(node)

sphinx.locale.admonitionlabels['version'] = 'Version mismatch'


class VersionCheck(docutils.parsers.rst.Directive):
    '''Directive versioncheck

    Check if current version (from ``conf.py``) equals version specified as
    argument. If not, generate warning.'''

    has_content = True
    required_arguments = 1
    optional_arguments = 0
    final_argument_whitespace = True
    option_spec = {}

    def run(self):
        current = self.state.document.settings.env.app.config.version
        version = self.arguments[0]

        if current == version:
            return []

        text = ' '.join('''This manual page was written for version **{}**, but
            current version at the time when this page was generated is **{}**.
            This may or may not mean that page is outdated or has
            inconsistencies.'''.format(version, current).split())

        node = versioncheck(text)
        node['classes'] = ['admonition', 'warning']

        self.state.nested_parse(docutils.statemachine.StringList([text]),
            self.content_offset, node)
        return [node]


def make_rst_section(heading, char):
    return '{}\n{}\n\n'.format(heading, char[0] * len(heading))


def prepare_manpage(command):
    parser = qubes.tools.get_parser_for_command(command)
    stream = StringIO.StringIO()
    stream.write('.. program:: {}\n\n'.format(command))
    stream.write(make_rst_section(
        ':program:`{}` -- {}'.format(command, parser.description), '='))
    stream.write('''.. warning::

   This page was autogenerated from command-line parser. It shouldn't be 1:1
   conversion, because it would add little value. Please revise it and add
   more descriptive help, which normally won't fit in standard ``--help``
   option.

   After rewrite, please remove this admonition.\n\n''')

    stream.write(make_rst_section('Synopsis', '-'))
    usage = ' '.join(parser.format_usage().strip().split())
    if usage.startswith('usage: '):
        usage = usage[len('usage: '):]

    # replace METAVARS with *METAVARS*
    usage = re.sub(r'\b([A-Z]{2,})\b', r'*\1*', usage)

    stream.write(':command:`{}` {}\n\n'.format(command, usage))

    stream.write(make_rst_section('Options', '-'))

    for action in parser._actions: # pylint: disable=protected-access
        stream.write('.. option:: ')
        if action.metavar:
            stream.write(', '.join('{}{}{}'.format(
                    option,
                    '=' if option.startswith('--') else ' ',
                    action.metavar)
                for option in sorted(action.option_strings)))
        else:
            stream.write(', '.join(sorted(action.option_strings)))
        stream.write('\n\n   {}\n\n'.format(action.help))

    stream.write(make_rst_section('Authors', '-'))
    stream.write('''\
| Joanna Rutkowska <joanna at invisiblethingslab dot com>
| Rafal Wojtczuk <rafal at invisiblethingslab dot com>
| Marek Marczykowski <marmarek at invisiblethingslab dot com>
| Wojtek Porczyk <woju at invisiblethingslab dot com>

.. vim: ts=3 sw=3 et tw=80
''')

    return stream.getvalue()


class ArgumentCheckVisitor(docutils.nodes.SparseNodeVisitor):
    def __init__(self, app, command, document):
        docutils.nodes.SparseNodeVisitor.__init__(self, document)

        self.app = app
        self.command = command
        self.args = set()

        try:
            parser = qubes.tools.get_parser_for_command(command)
        except ImportError:
            self.app.warn('cannot import module for command')
            self.command = None
            return
        except AttributeError:
            raise sphinx.errors.SphinxError('cannot find parser in module')

        # pylint: disable=protected-access
        for action in parser._actions:
            self.args.update(action.option_strings)


    # pylint: disable=no-self-use,unused-argument

    def visit_desc(self, node):
        if not node.get('desctype', None) == 'option':
            raise docutils.nodes.SkipChildren


    def visit_desc_name(self, node):
        if self.command is None:
            return

        if not isinstance(node[0], docutils.nodes.Text):
            raise sphinx.errors.SphinxError('first child should be Text')

        arg = str(node[0])
        try:
            self.args.remove(arg)
        except KeyError:
            raise sphinx.errors.SphinxError(
                'No such argument for {!r}: {!r}'.format(self.command, arg))


    def depart_document(self, node):
        if self.args:
            raise sphinx.errors.SphinxError(
                'Undocumented arguments: {!r}'.format(
                    ', '.join(sorted(self.args))))


def check_man_args(app, doctree, docname):
    command = os.path.split(docname)[1]
    app.info('Checking arguments for {!r}'.format(command))
    doctree.walk(ArgumentCheckVisitor(app, command, doctree))


#
# this is lifted from sphinx' own conf.py
#

event_sig_re = re.compile(r'([a-zA-Z-:<>]+)\s*\((.*)\)')

def parse_event(env, sig, signode):
    # pylint: disable=unused-argument
    m = event_sig_re.match(sig)
    if not m:
        signode += sphinx.addnodes.desc_name(sig, sig)
        return sig
    name, args = m.groups()
    signode += sphinx.addnodes.desc_name(name, name)
    plist = sphinx.addnodes.desc_parameterlist()
    for arg in args.split(','):
        arg = arg.strip()
        plist += sphinx.addnodes.desc_parameter(arg, arg)
    signode += plist
    return name

#
# end of codelifting
#


def break_to_pdb(app, *dummy):
    if not app.config.break_to_pdb:
        return
    import pdb
    pdb.set_trace()


def setup(app):
    app.add_role('ticket', ticket)
    app.add_config_value('ticket_base_uri',
        'https://wiki.qubes-os.org/ticket/', 'env')
    app.add_config_value('break_to_pdb', False, 'env')
    app.add_node(versioncheck,
        html=(visit, depart),
        man=(visit, depart))
    app.add_directive('versioncheck', VersionCheck)

    fdesc = sphinx.util.docfields.GroupedField('parameter', label='Parameters',
                         names=['param'], can_collapse=True)
    app.add_object_type('event', 'event', 'pair: %s; event', parse_event,
                        doc_field_types=[fdesc])

    app.connect('doctree-resolved', break_to_pdb)
    app.connect('doctree-resolved', check_man_args)


# vim: ts=4 sw=4 et
