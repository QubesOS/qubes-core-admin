#!/usr/bin/python2 -O
# -*- coding: utf-8 -*-

'''Documentation helpers

This module contains classes and functions which help to mainain documentation,
particulary our custom Sphinx extension.

'''

import csv
import posixpath
import sys
import urllib2

import docutils
import docutils.parsers.rst.roles

def fetch_ticket_info(uri):
    '''Fetch info about particular trac ticket given

    :param str uri: URI at which ticket resides
    :rtype: mapping
    :raises: urllib2.HTTPError
    '''

    data = urllib2.urlopen(uri + '?format=csv').read()
    reader = csv.reader((line + '\n' for line in data.split('\r\n')),
        quoting=csv.QUOTE_MINIMAL, quotechar='"')

    return dict(zip(*((cell.decode('utf-8') for cell in row) for row in list(reader)[:2])))


def ticket(name, rawtext, text, lineno, inliner, options={}, content=[]):
    '''Link to qubes ticket

    :param str name: The role name used in the document
    :param str rawtext: The entire markup snippet, with role
    :param str text: The text marked with the role
    :param int lineno: The line noumber where rawtext appearn in the input
    :param docutils.parsers.rst.states.Inliner inliner: The inliner instance that called this function
    :param options: Directive options for customisation
    :param content: The directive content for customisation
    '''

    ticket = text.lstrip('#')
    if not ticket.isdigit():
        msg = inliner.reporter.error('Invalid ticket identificator: {!r}'.format(text), line=lineno)
        prb = inliner.problematic(rawtext, rawtext, msg)
        return [prb], [msg]

    app = inliner.document.settings.env.app
    uri = posixpath.join(app.config.ticket_base_uri, ticket)
    try:
        info = fetch_ticket_info(uri)
    except urllib2.HTTPError, e:
        msg = inliner.reporter.error('Error while fetching ticket info: {!s}'.format(e), line=lineno)
        prb = inliner.problematic(rawtext, rawtext, msg)
        return [prb], [msg]

    docutils.parsers.rst.roles.set_classes(options)

    node = docutils.nodes.reference(
        rawtext,
        '#{} ({})'.format(ticket, info['summary']),
        refuri=uri,
        **options)

    return [node], []


def setup(app):
    app.add_role('ticket', ticket)
    app.add_config_value('ticket_base_uri', 'https://wiki.qubes-os.org/ticket/', 'env')

# vim: ts=4 sw=4 et
