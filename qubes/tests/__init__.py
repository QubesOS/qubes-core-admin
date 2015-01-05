#!/usr/bin/python -O

import unittest

class QubesTestCase(unittest.TestCase):
    def __str__(self):
        return '{}/{}/{}'.format(
            '.'.join(self.__class__.__module__.split('.')[2:]),
            self.__class__.__name__,
            self._testMethodName)
