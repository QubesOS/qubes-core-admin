# pylint: skip-file

import importlib

import qubes.plugins
import qubes.tests

__all__ = qubes.plugins.load(__file__)

def load_tests(loader, tests, pattern):
    for name in __all__:
        mod = importlib.import_module('.' + name, __name__)
        tests.addTests(loader.loadTestsFromModule(mod))
    return tests
