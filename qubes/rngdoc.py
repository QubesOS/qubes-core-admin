#!/usr/bin/env python3
#
# The Qubes OS Project, https://www.qubes-os.org/
#
# Copyright (C) 2014-2015  Joanna Rutkowska <joanna@invisiblethingslab.com>
# Copyright (C) 2014-2015  Wojtek Porczyk <woju@invisiblethingslab.com>
#
# This library is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 2.1 of the License, or (at your option) any later version.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with this library; if not, see <https://www.gnu.org/licenses/>.
#

import sys
import textwrap

import lxml.etree

class Element:
    def __init__(self, schema, xml):
        self.schema = schema
        self.xml = xml


    @property
    def nsmap(self):
        return self.schema.nsmap


    @property
    def name(self):
        return self.xml.get('name')


    def get_description(self, xml=None, wrap=True):
        if xml is None:
            xml = self.xml

        xml = xml.xpath('./doc:description', namespaces=self.nsmap)
        if not xml:
            return ''
        xml = xml[0]

        if wrap:
            return ''.join(self.schema.wrapper.fill(p) + '\n\n'
                for p in textwrap.dedent(xml.text.strip('\n')).split('\n\n'))

        return ' '.join(xml.text.strip().split())


    def get_data_type(self, xml=None):
        if xml is None:
            xml = self.xml

        value = xml.xpath('./rng:value', namespaces=self.nsmap)
        if value:
            value = '``{}``'.format(value[0].text.strip())
        else:
            metavar = xml.xpath('./doc:metavar', namespaces=self.nsmap)
            if metavar:
                value = '``{}``'.format(metavar[0].text.strip())
            else:
                value = ''

        xml = xml.xpath('./rng:data', namespaces=self.nsmap)
        if not xml:
            return ('', value)

        xml = xml[0]
        type_ = xml.get('type', '')

        if not value:
            pattern = xml.xpath('./rng:param[@name="pattern"]',
                namespaces=self.nsmap)
            if pattern:
                value = '``{}``'.format(pattern[0].text.strip())

        return type_, value


    def get_attributes(self):
        for xml in self.xml.xpath('''./rng:attribute |
                ./rng:optional/rng:attribute |
                ./rng:choice/rng:attribute''', namespaces=self.nsmap):
            required = 'yes' if xml.getparent() == self.xml else 'no'
            yield (xml, required)


    def resolve_ref(self, ref):
        refs = self.xml.xpath(
            '//rng:define[name="{}"]/rng:element'.format(ref['name']))
        return refs[0] if refs else None


    def get_child_elements(self):
        for xml in self.xml.xpath('''./rng:element | ./rng:ref |
                ./rng:optional/rng:element | ./rng:optional/rng:ref |
                ./rng:zeroOrMore/rng:element | ./rng:zeroOrMore/rng:ref |
                ./rng:oneOrMore/rng:element | ./rng:oneOrMore/rng:ref''',
                namespaces=self.nsmap):
            parent = xml.getparent()
            qname = lxml.etree.QName(parent)
            if parent == self.xml:
                number = '1'
            elif qname.localname == 'optional':
                number = '?'
            elif qname.localname == 'zeroOrMore':
                number = '\\*'
            elif qname.localname == 'oneOrMore':
                number = '\\+'
            else:
                print(parent.tag)
                raise Exception(f"Cannot choose number format for tag {parent.tag}")

            if xml.tag == 'ref':
                xml = self.resolve_ref(xml)
                if xml is None:
                    continue

            yield (self.schema.elements[xml.get('name')], number)


    def write_rst(self, stream):
        stream.write('.. _qubesxml-element-{}:\n\n'.format(self.name))
        stream.write(make_rst_section('Element: **{}**'.format(self.name), '-'))
        stream.write(self.get_description())

        attrtable = []
        for attr, required in self.get_attributes():
            type_, value = self.get_data_type(attr)
            attrtable.append((
                attr.get('name'),
                required,
                type_,
                value,
                self.get_description(attr, wrap=False)))

        if attrtable:
            stream.write(make_rst_section('Attributes', '^'))
            write_rst_table(stream, attrtable,
                ('attribute', 'req.', 'type', 'value', 'description'))

        childtable = [(':ref:`{0} <qubesxml-element-{0}>`'.format(
                child.xml.get('name')), n)
            for child, n in self.get_child_elements()]
        if childtable:
            stream.write(make_rst_section('Child elements', '^'))
            write_rst_table(stream, childtable, ('element', 'number'))


class Schema:
    # pylint: disable=too-few-public-methods
    nsmap = {
        'rng': 'http://relaxng.org/ns/structure/1.0',
        'q': 'http://qubes-os.org/qubes/3',
        'doc': 'http://qubes-os.org/qubes-doc/1'}

    def __init__(self, xml):
        self.xml = xml

        self.wrapper = textwrap.TextWrapper(width=80,
            break_long_words=False, break_on_hyphens=False)

        self.elements = {}
        for node in self.xml.xpath('//rng:element', namespaces=self.nsmap):
            element = Element(self, node)
            self.elements[element.name] = element


def make_rst_section(heading, char):
    return '{}\n{}\n\n'.format(heading, char[0] * len(heading))


def write_rst_table(stream, itr, heads):
    stream.write('.. csv-table::\n')
    stream.write('   :header: {}\n'.format(', '.join('"{}"'.format(c)
        for c in heads)))
    stream.write('   :widths: {}\n\n'.format(', '.join('1'
        for c in heads)))

    for row in itr:
        stream.write('   {}\n'.format(', '.join('"{}"'.format(i) for i in row)))

    stream.write('\n')


def main(filename, example):
    with open(filename, 'rb') as schema_f:
        schema = Schema(lxml.etree.parse(schema_f))

    sys.stdout.write(make_rst_section('Qubes XML specification', '='))
    sys.stdout.write('''
This is the documentation of qubes.xml autogenerated from RelaxNG source.

Quick example, worth thousands lines of specification:
.. literalinclude:: {}
   :language: xml

'''[1:].format(example))

    for name in sorted(schema.elements):
        schema.elements[name].write_rst(sys.stdout)


if __name__ == '__main__':
    # pylint: disable=no-value-for-parameter
    main(*sys.argv[1:])

# vim: ts=4 sw=4 et
