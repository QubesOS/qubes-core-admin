#!/usr/bin/python2
# -*- encoding: utf8 -*-
#
# The Qubes OS Project, http://www.qubes-os.org
#
# Copyright (C) 2016 Marek Marczykowski-Górecki 
#                               <marmarek@invisiblethingslab.com>
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
import argparse

import qubes.firewall
import qubes.tests
import qubes.tests.firewall
import qubes.tools.qvm_firewall


class TC_00_RuleAction(qubes.tests.QubesTestCase):
    def setUp(self):
        super(TC_00_RuleAction, self).setUp()
        self.action = qubes.tools.qvm_firewall.RuleAction(None, dest='rule')

    def test_000_named_opts(self):
        ns = argparse.Namespace()
        self.action(None, ns, ['dsthost=127.0.0.1', 'action=accept'])
        self.assertEqual(ns.rule,
            qubes.firewall.Rule(None, action='accept', dsthost='127.0.0.1/32'))

    def test_001_unnamed_opts(self):
        ns = argparse.Namespace()
        self.action(None, ns, ['accept', '127.0.0.1', 'tcp', '80'])
        self.assertEqual(ns.rule,
            qubes.firewall.Rule(None, action='accept', dsthost='127.0.0.1/32',
            proto='tcp', dstports=80))

    def test_002_unnamed_opts(self):
        ns = argparse.Namespace()
        self.action(None, ns, ['accept', '127.0.0.1', 'icmp', '8'])
        self.assertEqual(ns.rule,
            qubes.firewall.Rule(None, action='accept', dsthost='127.0.0.1/32',
            proto='icmp', icmptype=8))

    def test_003_mixed_opts(self):
        ns = argparse.Namespace()
        self.action(None, ns, ['dsthost=127.0.0.1', 'accept',
            'dstports=443', 'tcp'])
        self.assertEqual(ns.rule,
            qubes.firewall.Rule(None, action='accept', dsthost='127.0.0.1/32',
            proto='tcp', dstports=443))