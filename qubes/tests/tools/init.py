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

import argparse

import qubes
import qubes.tools

import qubes.tests

class TC_00_PropertyAction(qubes.tests.QubesTestCase):
    def test_000_default(self):
        parser = argparse.ArgumentParser()
        parser.add_argument('--property', '-p',
            action=qubes.tools.PropertyAction)
        parser.set_defaults(properties={'defaultprop': 'defaultvalue'})

        args = parser.parse_args([])
        self.assertDictContainsSubset(
            {'defaultprop': 'defaultvalue'}, args.properties)

    def test_001_set_prop(self):
        parser = argparse.ArgumentParser()
        parser.add_argument('--property', '-p',
            action=qubes.tools.PropertyAction)

        args = parser.parse_args(['-p', 'testprop=testvalue'])
        self.assertDictContainsSubset(
            {'testprop': 'testvalue'}, args.properties)

    def test_002_set_prop_2(self):
        parser = argparse.ArgumentParser()
        parser.add_argument('--property', '-p',
            action=qubes.tools.PropertyAction)
        parser.set_defaults(properties={'defaultprop': 'defaultvalue'})

        args = parser.parse_args(
            ['-p', 'testprop=testvalue', '-p', 'testprop2=testvalue2'])
        self.assertDictContainsSubset(
            {'testprop': 'testvalue', 'testprop2': 'testvalue2'},
            args.properties)

    def test_003_set_prop_with_default(self):
        parser = argparse.ArgumentParser()
        parser.add_argument('--property', '-p',
            action=qubes.tools.PropertyAction)
        parser.set_defaults(properties={'defaultprop': 'defaultvalue'})

        args = parser.parse_args(['-p', 'testprop=testvalue'])
        self.assertDictContainsSubset(
            {'testprop': 'testvalue', 'defaultprop': 'defaultvalue'},
            args.properties)

    def test_003_set_prop_override_default(self):
        parser = argparse.ArgumentParser()
        parser.add_argument('--property', '-p',
            action=qubes.tools.PropertyAction)
        parser.set_defaults(properties={'testprop': 'defaultvalue'})

        args = parser.parse_args(['-p', 'testprop=testvalue'])
        self.assertDictContainsSubset(
            {'testprop': 'testvalue'},
            args.properties)


class TC_01_SinglePropertyAction(qubes.tests.QubesTestCase):
    def test_000_help(self):
        parser = argparse.ArgumentParser()
        action = parser.add_argument('--testprop', '-T',
            action=qubes.tools.SinglePropertyAction)
        self.assertIn('testprop', action.help)

    def test_001_help_const(self):
        parser = argparse.ArgumentParser()
        action = parser.add_argument('--testprop', '-T',
            action=qubes.tools.SinglePropertyAction,
            const='testvalue')
        self.assertIn('testvalue', action.help)

    def test_100_default(self):
        parser = argparse.ArgumentParser()
        parser.add_argument('--testprop', '-T',
            action=qubes.tools.SinglePropertyAction)
        parser.set_defaults(properties={'testprop': 'defaultvalue'})

        args = parser.parse_args([])
        self.assertDictContainsSubset(
            {'testprop': 'defaultvalue'}, args.properties)

    def test_101_set_prop(self):
        parser = argparse.ArgumentParser()
        parser.add_argument('--testprop', '-T',
            action=qubes.tools.SinglePropertyAction)
        args = parser.parse_args(['-T', 'testvalue'])
        self.assertDictContainsSubset(
            {'testprop': 'testvalue'}, args.properties)

    def test_102_set_prop_dest(self):
        parser = argparse.ArgumentParser()
        parser.add_argument('--testprop', '-T', dest='otherprop',
            action=qubes.tools.SinglePropertyAction)
        args = parser.parse_args(['-T', 'testvalue'])
        self.assertDictContainsSubset(
            {'otherprop': 'testvalue'}, args.properties)

    def test_103_set_prop_const(self):
        parser = argparse.ArgumentParser()
        parser.add_argument('--testprop', '-T',
            action=qubes.tools.SinglePropertyAction,
            const='testvalue')
        args = parser.parse_args(['-T'])
        self.assertDictContainsSubset(
            {'testprop': 'testvalue'}, args.properties)

    def test_104_set_prop_positional(self):
        parser = argparse.ArgumentParser()
        parser.add_argument('testprop',
            action=qubes.tools.SinglePropertyAction)
        args = parser.parse_args(['testvalue'])
        self.assertDictContainsSubset(
            {'testprop': 'testvalue'}, args.properties)
