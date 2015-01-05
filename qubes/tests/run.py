#!/usr/bin/python -O

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

def main():
    suite = unittest.TestSuite()
    loader = unittest.TestLoader()
    for modname in test_order:
        module = importlib.import_module(modname)
        suite.addTests(loader.loadTestsFromModule(module))

    unittest.TextTestRunner(stream=sys.stdout, verbosity=2).run(suite)

if __name__ == '__main__':
    main()
