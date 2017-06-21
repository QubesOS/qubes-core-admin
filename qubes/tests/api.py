# -*- encoding: utf8 -*-
#
# The Qubes OS Project, http://www.qubes-os.org
#
# Copyright (C) 2017 Marek Marczykowski-Górecki
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
# with this program; if not, see <http://www.gnu.org/licenses/>.

import asyncio
import socket
import unittest.mock

import qubes.api
import qubes.tests


class TestMgmt(object):
    def __init__(self, app, src, method, dest, arg, send_event=None):
        self.app = app
        self.src = src
        self.method = method
        self.dest = dest
        self.arg = arg
        self.send_event = send_event
        try:
            self.function = {
                'mgmt.success': self.success,
                'mgmt.success_none': self.success_none,
                'mgmt.qubesexception': self.qubesexception,
                'mgmt.exception': self.exception,
                'mgmt.event': self.event,
            }[self.method.decode()]
        except KeyError:
            raise qubes.api.ProtocolError('Invalid method')

    def execute(self, untrusted_payload):
        self.task = asyncio.Task(self.function(
            untrusted_payload=untrusted_payload))
        return self.task

    def cancel(self):
        self.task.cancel()

    @asyncio.coroutine
    def success(self, untrusted_payload):
        return 'src: {!r}, dest: {!r}, arg: {!r}, payload: {!r}'.format(
            self.src, self.dest, self.arg, untrusted_payload
        )

    @asyncio.coroutine
    def success_none(self, untrusted_payload):
        pass

    @asyncio.coroutine
    def qubesexception(self, untrusted_payload):
        raise qubes.exc.QubesException('qubes-exception')

    @asyncio.coroutine
    def exception(self, untrusted_payload):
        raise Exception('exception')

    @asyncio.coroutine
    def event(self, untrusted_payload):
        future = asyncio.get_event_loop().create_future()

        class Subject:
            name = 'subject'
        self.send_event(Subject, 'event', payload=untrusted_payload.decode())
        try:
            # give some time to close the other end
            yield from asyncio.sleep(0.1)
            # should be canceled
            self.send_event(Subject, 'event2',
                payload=untrusted_payload.decode())
            yield from future
        except asyncio.CancelledError:
            pass

class TC_00_QubesDaemonProtocol(qubes.tests.QubesTestCase):
    def setUp(self):
        super(TC_00_QubesDaemonProtocol, self).setUp()
        self.app = unittest.mock.Mock()
        self.app.log = self.log
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.sock_client, self.sock_server = socket.socketpair()
        self.reader, self.writer = self.loop.run_until_complete(
            asyncio.open_connection(sock=self.sock_client))

        connect_coro = self.loop.create_connection(
            lambda: qubes.api.QubesDaemonProtocol(
                TestMgmt, app=self.app),
            sock=self.sock_server)
        self.transport, self.protocol = self.loop.run_until_complete(
            connect_coro)

    def tearDown(self):
        self.sock_server.close()
        self.sock_client.close()
        self.loop.stop()
        self.loop.run_forever()
        self.loop.close()
        super(TC_00_QubesDaemonProtocol, self).tearDown()

    def test_000_message_ok(self):
        self.writer.write(b'dom0\0mgmt.success\0dom0\0arg\0payload')
        self.writer.write_eof()
        with self.assertNotRaises(asyncio.TimeoutError):
            response = self.loop.run_until_complete(
                asyncio.wait_for(self.reader.read(), 1))
        self.assertEqual(response,
            b"0\0src: b'dom0', dest: b'dom0', arg: b'arg', payload: b'payload'")

    def test_001_message_ok_in_parts(self):
        self.writer.write(b'dom0\0mgmt.')
        self.loop.run_until_complete(self.writer.drain())
        self.writer.write(b'success\0dom0\0arg\0payload')
        self.writer.write_eof()
        with self.assertNotRaises(asyncio.TimeoutError):
            response = self.loop.run_until_complete(
                asyncio.wait_for(self.reader.read(), 1))
        self.assertEqual(response,
            b"0\0src: b'dom0', dest: b'dom0', arg: b'arg', payload: b'payload'")

    def test_002_message_ok_empty(self):
        self.writer.write(b'dom0\0mgmt.success_none\0dom0\0arg\0payload')
        self.writer.write_eof()
        with self.assertNotRaises(asyncio.TimeoutError):
            response = self.loop.run_until_complete(
                asyncio.wait_for(self.reader.read(), 1))
        self.assertEqual(response, b"0\0")

    def test_003_exception_qubes(self):
        self.writer.write(b'dom0\0mgmt.qubesexception\0dom0\0arg\0payload')
        self.writer.write_eof()
        with self.assertNotRaises(asyncio.TimeoutError):
            response = self.loop.run_until_complete(
                asyncio.wait_for(self.reader.read(), 1))
        self.assertEqual(response, b"2\0QubesException\0\0qubes-exception\0")

    def test_004_exception_generic(self):
        self.writer.write(b'dom0\0mgmt.exception\0dom0\0arg\0payload')
        self.writer.write_eof()
        with self.assertNotRaises(asyncio.TimeoutError):
            response = self.loop.run_until_complete(
                asyncio.wait_for(self.reader.read(), 1))
        self.assertEqual(response, b"")

    def test_005_event(self):
        self.writer.write(b'dom0\0mgmt.event\0dom0\0arg\0payload')
        self.writer.write_eof()
        with self.assertNotRaises(asyncio.TimeoutError):
            response = self.loop.run_until_complete(
                asyncio.wait_for(self.reader.readuntil(b'\0\0'), 1))
        self.assertEqual(response, b"1\0subject\0event\0payload\0payload\0\0")
        # this will trigger connection_lost, but only when next event is sent
        self.sock_client.shutdown(socket.SHUT_RD)
        # check if event-producing method is interrupted
        with self.assertNotRaises(asyncio.TimeoutError):
            self.loop.run_until_complete(
                asyncio.wait_for(self.protocol.mgmt.task, 1))
