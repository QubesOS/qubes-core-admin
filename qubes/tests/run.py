#!/usr/bin/python -O

import curses
import importlib
import sys
import unittest

test_order = [
    'qubes.tests.events',
    'qubes.tests.vm.init',
    'qubes.tests.vm.qubesvm',
    'qubes.tests.init'
]

sys.path.insert(0, '../../')

class ANSIColor(dict):
    def __init__(self):
        super(ANSIColor, self).__init__()
        try:
            curses.setupterm()
        except curses.error:
            return

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
        self.showAll = verbosity > 1
        self.dots = verbosity == 1
        self.descriptions = descriptions

        self.color = ANSIColor()

    def _fmtexc(self, err):
        s = str(err[1])
        if s:
            return '{bold}{}:{normal} {!s}'.format(
                err[0].__name__, err[1], **self.color)
        else:
            return '{bold}{}{normal}'.format(err[0].__name__, **self.color)

    def getDescription(self, test):
        teststr = str(test).split('/')
        teststr[-1] = '{bold}{}{normal}'.format(teststr[-1], **self.color)
        teststr = '/'.join(teststr)

        doc_first_line = test.shortDescription()
        if self.descriptions and doc_first_line:
            return '\n'.join((teststr, '  {}'.format(
                doc_first_line, **self.color)))
        else:
            return teststr

    def startTest(self, test):
        super(ANSITestResult, self).startTest(test)
        if self.showAll:
            self.stream.write(self.getDescription(test))
            self.stream.write(' ... ')
            self.stream.flush()

    def addSuccess(self, test):
        super(ANSITestResult, self).addSuccess(test)
        if self.showAll:
            self.stream.writeln('{green}ok{normal}'.format(**self.color))
        elif self.dots:
            self.stream.write('.')
            self.stream.flush()

    def addError(self, test, err):
        super(ANSITestResult, self).addError(test, err)
        if self.showAll:
            self.stream.writeln('{red}{bold}ERROR{normal} ({})'.format(
                self._fmtexc(err), **self.color))
        elif self.dots:
            self.stream.write('{red}{bold}E{normal}'.format(**self.color))
            self.stream.flush()

    def addFailure(self, test, err):
        super(ANSITestResult, self).addFailure(test, err)
        if self.showAll:
            self.stream.writeln('{red}FAIL{normal}'.format(**self.color))
        elif self.dots:
            self.stream.write('{red}F{normal}'.format(**self.color))
            self.stream.flush()

    def addSkip(self, test, reason):
        super(ANSITestResult, self).addSkip(test, reason)
        if self.showAll:
            self.stream.writeln('{cyan}skipped{normal} ({})'.format(
                reason, **self.color))
        elif self.dots:
            self.stream.write('{cyan}s{normal}'.format(**self.color))
            self.stream.flush()

    def addExpectedFailure(self, test, err):
        super(ANSITestResult, self).addExpectedFailure(test, err)
        if self.showAll:
            self.stream.writeln('{yellow}expected failure{normal}'.format(
                **self.color))
        elif self.dots:
            self.stream.write('{yellow}x{normal}'.format(**self.color))
            self.stream.flush()

    def addUnexpectedSuccess(self, test):
        super(ANSITestResult, self).addUnexpectedSuccess(test)
        if self.showAll:
            self.stream.writeln(
                '{yellow}{bold}unexpected success{normal}'.format(**self.color))
        elif self.dots:
            self.stream.write('{yellow}{bold}u{normal}'.format(**self.color))
            self.stream.flush()

    def printErrors(self):
        if self.dots or self.showAll:
            self.stream.writeln()
        self.printErrorList(
            '{red}{bold}ERROR{normal}'.format(**self.color), self.errors)
        self.printErrorList(
            '{red}FAIL{normal}'.format(**self.color), self.failures)

    def printErrorList(self, flavour, errors):
        for test, err in errors:
            self.stream.writeln(self.separator1)
            self.stream.writeln('%s: %s' % (flavour,self.getDescription(test)))
            self.stream.writeln(self.separator2)
            self.stream.writeln('%s' % err)


def demo(verbosity=2):
    import qubes.tests
    class TC_Demo(qubes.tests.QubesTestCase):
        '''Demo class'''
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

    suite = unittest.TestLoader().loadTestsFromTestCase(TC_Demo)
    runner = unittest.TextTestRunner(stream=sys.stdout, verbosity=verbosity)
    runner.resultclass = ANSITestResult
    return runner.run(suite).wasSuccessful()


def main():
    suite = unittest.TestSuite()
    loader = unittest.TestLoader()
    for modname in test_order:
        module = importlib.import_module(modname)
        suite.addTests(loader.loadTestsFromModule(module))

    runner = unittest.TextTestRunner(stream=sys.stdout, verbosity=2)
    runner.resultclass = ANSITestResult
    return runner.run(suite).wasSuccessful()

if __name__ == '__main__':
    sys.exit(not main())
