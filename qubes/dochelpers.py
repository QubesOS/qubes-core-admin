#!/usr/bin/python2 -O
# -*- coding: utf-8 -*-

'''Documentation helpers

This module contains classes and functions which help to maintain documentation,
particularly our custom Sphinx extension.

'''

import csv
import posixpath
import re
import sys
import urllib2

import docutils
import docutils.nodes
import docutils.parsers.rst
import docutils.parsers.rst.roles
import docutils.statemachine
import sphinx
import sphinx.locale
import sphinx.util.docfields

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


def ticket(name, rawtext, text, lineno, inliner, options={}, content=[]):
    '''Link to qubes ticket

    :param str name: The role name used in the document
    :param str rawtext: The entire markup snippet, with role
    :param str text: The text marked with the role
    :param int lineno: The line number where rawtext appears in the input
    :param docutils.parsers.rst.states.Inliner inliner: The inliner instance \
        that called this function
    :param options: Directive options for customisation
    :param content: The directive content for customisation
    '''

    ticket = text.lstrip('#')
    if not ticket.isdigit():
        msg = inliner.reporter.error(
            'Invalid ticket identificator: {!r}'.format(text), line=lineno)
        prb = inliner.problematic(rawtext, rawtext, msg)
        return [prb], [msg]

    app = inliner.document.settings.env.app
    uri = posixpath.join(app.config.ticket_base_uri, ticket)
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
        '#{} ({})'.format(ticket, info['summary']),
        refuri=uri,
        **options)

    return [node], []


class versioncheck(docutils.nodes.warning):
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


#
# this is lifted from sphinx' own conf.py
#

event_sig_re = re.compile(r'([a-zA-Z-:<>]+)\s*\((.*)\)')

def parse_event(env, sig, signode):
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

def setup(app):
    app.add_role('ticket', ticket)
    app.add_config_value('ticket_base_uri',
        'https://wiki.qubes-os.org/ticket/', 'env')
    app.add_node(versioncheck,
        html=(visit, depart),
        man=(visit, depart))
    app.add_directive('versioncheck', VersionCheck)

    fdesc = sphinx.util.docfields.GroupedField('parameter', label='Parameters',
                         names=['param'], can_collapse=True)
    app.add_object_type('event', 'event', 'pair: %s; event', parse_event,
                        doc_field_types=[fdesc])


# vim: ts=4 sw=4 et
