#!/usr/bin/python2 -O
# vim: fileencoding=utf-8

#
# The Qubes OS Project, https://www.qubes-os.org/
#
# Copyright (C) 2014-2015  Joanna Rutkowska <joanna@invisiblethingslab.com>
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

import curses
import importlib
import socket
import sys
import unittest

test_order = [
    'qubes.tests.events',
    'qubes.tests.vm.init',
    'qubes.tests.vm.qubesvm',
    'qubes.tests.vm.adminvm',
    'qubes.tests.init',

    'qubes.tests.tools',
]

sys.path.insert(1, '../../')

import qubes.tests

class ANSIColor(dict):
    def __init__(self):
        super(ANSIColor, self).__init__()
        try:
            curses.setupterm()
        except curses.error:
            return

        # pylint: disable=bad-whitespace
        self['black']   = curses.tparm(curses.tigetstr('setaf'), 0)
        self['red']     = curses.tparm(curses.tigetstr('setaf'), 1)
        self['green']   = curses.tparm(curses.tigetstr('setaf'), 2)
        self['yellow']  = curses.tparm(curses.tigetstr('setaf'), 3)
        self['blue']    = curses.tparm(curses.tigetstr('setaf'), 4)
        self['magenta'] = curses.tparm(curses.tigetstr('setaf'), 5)
        self['cyan']    = curses.tparm(curses.tigetstr('setaf'), 6)
        self['white']   = curses.tparm(curses.tigetstr('setaf'), 7)

        self['bold']    = curses.tigetstr('bold')
        self['normal']  = curses.tigetstr('sgr0')

    def __missing__(self, key):
        # pylint: disable=unused-argument,no-self-use
        return ''


class ANSITestResult(unittest.TestResult):
    '''A test result class that can print colourful text results to a stream.

    Used by TextTestRunner. This is a lightly rewritten unittest.TextTestResult.
    '''

    separator1 = unittest.TextTestResult.separator1
    separator2 = unittest.TextTestResult.separator2

    def __init__(self, stream, descriptions, verbosity):
        super(ANSITestResult, self).__init__(stream, descriptions, verbosity)
        self.stream = stream
        self.showAll = verbosity > 1 # pylint: disable=invalid-name
        self.dots = verbosity == 1
        self.descriptions = descriptions

        self.color = ANSIColor()
        self.hostname = socket.gethostname()

    def _fmtexc(self, err):
        if str(err[1]):
            return '{color[bold]}{}:{color[normal]} {!s}'.format(
                err[0].__name__, err[1], color=self.color)
        else:
            return '{color[bold]}{}{color[normal]}'.format(
                err[0].__name__, color=self.color)

    def getDescription(self, test): # pylint: disable=invalid-name
        teststr = str(test).split('/')
        for i in range(-2, 0):
            try:
                fullname = teststr[i].split('_', 2)
            except IndexError:
                continue
            fullname[-1] = '{color[bold]}{}{color[normal]}'.format(
                fullname[-1], color=self.color)
            teststr[i] = '_'.join(fullname)
        teststr = '/'.join(teststr)

        doc_first_line = test.shortDescription()
        if self.descriptions and doc_first_line:
            return '\n'.join((teststr, '  {}'.format(
                doc_first_line, color=self.color)))
        else:
            return teststr

    def startTest(self, test): # pylint: disable=invalid-name
        super(ANSITestResult, self).startTest(test)
        if self.showAll:
            if not qubes.tests.in_git:
                self.stream.write('{}: '.format(self.hostname))
            self.stream.write(self.getDescription(test))
            self.stream.write(' ... ')
            self.stream.flush()

    def addSuccess(self, test): # pylint: disable=invalid-name
        super(ANSITestResult, self).addSuccess(test)
        if self.showAll:
            self.stream.writeln('{color[green]}ok{color[normal]}'.format(
                color=self.color))
        elif self.dots:
            self.stream.write('.')
            self.stream.flush()

    def addError(self, test, err): # pylint: disable=invalid-name
        super(ANSITestResult, self).addError(test, err)
        if self.showAll:
            self.stream.writeln(
                '{color[red]}{color[bold]}ERROR{color[normal]} ({})'.format(
                    self._fmtexc(err), color=self.color))
        elif self.dots:
            self.stream.write(
                '{color[red]}{color[bold]}E{color[normal]}'.format(
                    color=self.color))
            self.stream.flush()

    def addFailure(self, test, err): # pylint: disable=invalid-name
        super(ANSITestResult, self).addFailure(test, err)
        if self.showAll:
            self.stream.writeln('{color[red]}FAIL{color[normal]}'.format(
                color=self.color))
        elif self.dots:
            self.stream.write('{color[red]}F{color[normal]}'.format(
                color=self.color))
            self.stream.flush()

    def addSkip(self, test, reason): # pylint: disable=invalid-name
        super(ANSITestResult, self).addSkip(test, reason)
        if self.showAll:
            self.stream.writeln(
                '{color[cyan]}skipped{color[normal]} ({})'.format(
                    reason, color=self.color))
        elif self.dots:
            self.stream.write('{color[cyan]}s{color[normal]}'.format(
                color=self.color))
            self.stream.flush()

    def addExpectedFailure(self, test, err): # pylint: disable=invalid-name
        super(ANSITestResult, self).addExpectedFailure(test, err)
        if self.showAll:
            self.stream.writeln(
                '{color[yellow]}expected failure{color[normal]}'.format(
                    color=self.color))
        elif self.dots:
            self.stream.write('{color[yellow]}x{color[normal]}'.format(
                color=self.color))
            self.stream.flush()

    def addUnexpectedSuccess(self, test): # pylint: disable=invalid-name
        super(ANSITestResult, self).addUnexpectedSuccess(test)
        if self.showAll:
            self.stream.writeln(
                '{color[yellow]}{color[bold]}unexpected success'
                    '{color[normal]}'.format(color=self.color))
        elif self.dots:
            self.stream.write(
                '{color[yellow]}{color[bold]}u{color[normal]}'.format(
                    color=self.color))
            self.stream.flush()

    def printErrors(self): # pylint: disable=invalid-name
        if self.dots or self.showAll:
            self.stream.writeln()
        self.printErrorList(
            '{color[red]}{color[bold]}ERROR{color[normal]}'.format(
                color=self.color),
            self.errors)
        self.printErrorList(
            '{color[red]}FAIL{color[normal]}'.format(color=self.color),
            self.failures)

    def printErrorList(self, flavour, errors): # pylint: disable=invalid-name
        for test, err in errors:
            self.stream.writeln(self.separator1)
            self.stream.writeln('%s: %s' % (flavour, self.getDescription(test)))
            self.stream.writeln(self.separator2)
            self.stream.writeln('%s' % err)


def demo(verbosity=2):
    class TC_00_Demo(qubes.tests.QubesTestCase):
        '''Demo class'''
        # pylint: disable=no-self-use
        def test_0_success(self):
            '''Demo test (success)'''
            pass
        def test_1_error(self):
            '''Demo test (error)'''
            raise Exception()
        def test_2_failure(self):
            '''Demo test (failure)'''
            self.fail('boo')
        def test_3_skip(self):
            '''Demo test (skipped by call to self.skipTest())'''
            self.skipTest('skip')
        @unittest.skip(None)
        def test_4_skip_decorator(self):
            '''Demo test (skipped by decorator)'''
            pass
        @unittest.expectedFailure
        def test_5_expected_failure(self):
            '''Demo test (expected failure)'''
            self.fail()
        @unittest.expectedFailure
        def test_6_unexpected_success(self):
            '''Demo test (unexpected success)'''
            pass

    suite = unittest.TestLoader().loadTestsFromTestCase(TC_00_Demo)
    runner = unittest.TextTestRunner(stream=sys.stdout, verbosity=verbosity)
    runner.resultclass = ANSITestResult
    return runner.run(suite).wasSuccessful()


def main():
    suite = unittest.TestSuite()
    loader = unittest.TestLoader()
    for modname in test_order:
        suite.addTests(loader.loadTestsFromName(modname))

    runner = unittest.TextTestRunner(stream=sys.stdout, verbosity=2)
    runner.resultclass = ANSITestResult
    return runner.run(suite).wasSuccessful()

if __name__ == '__main__':
    sys.exit(not main())
