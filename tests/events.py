#!/usr/bin/python2 -O

import sys
import unittest

sys.path.insert(0, '..')
import qubes.events

class TC_Emitter(unittest.TestCase):
    def test_000_add_handler(self):
        # need something mutable
        testevent_fired = [False]

        def on_testevent(subject, event):
            if event == 'testevent':
                testevent_fired[0] = True

        emitter = qubes.events.Emitter()
        emitter.add_handler('testevent', on_testevent)
        emitter.fire_event('testevent')
        self.assertTrue(testevent_fired[0])


    def test_001_decorator(self):
        class TestEmitter(qubes.events.Emitter):
            def __init__(self):
                super(TestEmitter, self).__init__()
                self.testevent_fired = False

            @qubes.events.handler('testevent')
            def on_testevent(self, event):
                if event == 'testevent':
                    self.testevent_fired = True

        emitter = TestEmitter()
        emitter.fire_event('testevent')
        self.assertTrue(emitter.testevent_fired)
