#!/usr/bin/python2 -O

import sys
import unittest

import lxml.etree

sys.path.insert(0, '../')
import qubes

class TC_QubesVmLabel(unittest.TestCase):
    def test_000_appvm(self):
        xml = lxml.etree.XML('''
<qubes version="3">
    <labels>
        <label id="label-1" color="#cc0000">red</label>
    </labels>
</qubes>
        ''')

        node = xml.xpath('//label')[0]
        label = qubes.QubesVmLabel.fromxml(node)

        self.assertEqual(label.index, 1)
        self.assertEqual(label.color, '#cc0000')
        self.assertEqual(label.name, 'red')
        self.assertEqual(label.dispvm, False)
        self.assertEqual(label.icon, 'appvm-red')

    def test_001_dispvm(self):
        xml = lxml.etree.XML('''
<qubes version="3">
    <labels>
        <label id="label-2" color="#cc0000" dispvm="True">red</label>
    </labels>
</qubes>
        ''')

        node = xml.xpath('//label')[0]
        label = qubes.QubesVmLabel.fromxml(node)

        self.assertEqual(label.dispvm, True)
        self.assertEqual(label.icon, 'dispvm-red')
