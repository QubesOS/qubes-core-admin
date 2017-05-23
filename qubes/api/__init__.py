# -*- encoding: utf8 -*-
#
# The Qubes OS Project, http://www.qubes-os.org
#
# Copyright (C) 2017  Wojtek Porczyk <woju@invisiblethingslab.com>
# Copyright (C) 2017  Marek Marczykowski-Górecki
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
import functools


class ProtocolError(AssertionError):
    '''Raised when something is wrong with data received'''
    pass


class PermissionDenied(Exception):
    '''Raised deliberately by handlers when we decide not to cooperate'''
    pass


def method(name, *, no_payload=False, endpoints=None):
    '''Decorator factory for methods intended to appear in API.

    The decorated method can be called from public API using a child of
    :py:class:`AbstractQubesMgmt` class. The method becomes "public", and can be
    called using remote management interface.

    :param str name: qrexec rpc method name
    :param bool no_payload: if :py:obj:`True`, will barf on non-empty payload; \
        also will not pass payload at all to the method

    The expected function method should have one argument (other than usual
    *self*), ``untrusted_payload``, which will contain the payload.

    .. warning::
        This argument has to be named such, to remind the programmer that the
        content of this variable is indeed untrusted.

    If *no_payload* is true, then the method is called with no arguments.
    '''

    def decorator(func):
        if no_payload:
            # the following assignment is needed for how closures work in Python
            _func = func
            @functools.wraps(_func)
            def wrapper(self, untrusted_payload, **kwargs):
                if untrusted_payload != b'':
                    raise ProtocolError('unexpected payload')
                return _func(self, **kwargs)
            func = wrapper

        # pylint: disable=protected-access
        if endpoints is None:
            func._rpcname = ((name, None),)
        else:
            func._rpcname = tuple(
                (name.format(endpoint=endpoint), endpoint)
                for endpoint in endpoints)
        return func

    return decorator


def apply_filters(iterable, filters):
    '''Apply filters returned by mgmt-permission:... event'''
    for selector in filters:
        iterable = filter(selector, iterable)
    return iterable


class AbstractQubesAPI(object):
    '''Common code for Qubes Management Protocol handling

    Different interfaces can expose different API call sets, however they share
    common protocol and common implementation framework. This class is the
    latter.

    To implement a new interface, inherit from this class and write at least one
    method and decorate it with :py:func:`api` decorator. It will have access to
    pre-defined attributes: :py:attr:`app`, :py:attr:`src`, :py:attr:`dest`,
    :py:attr:`arg` and :py:attr:`method`.

    There are also two helper functions for firing events associated with API
    calls.
    '''
    def __init__(self, app, src, method_name, dest, arg, send_event=None):
        #: :py:class:`qubes.Qubes` object
        self.app = app

        #: source qube
        self.src = self.app.domains[src.decode('ascii')]

        #: destination qube
        self.dest = self.app.domains[dest.decode('ascii')]

        #: argument
        self.arg = arg.decode('ascii')

        #: name of the method
        self.method = method_name.decode('ascii')

        #: callback for sending events if applicable
        self.send_event = send_event

        #: is this operation cancellable?
        self.cancellable = False

        untrusted_candidates = []
        for attr in dir(self):
            func = getattr(self, attr)

            if not callable(func):
                continue

            try:
                # pylint: disable=protected-access
                for mname, endpoint in func._rpcname:
                    if mname != self.method:
                        continue
                    untrusted_candidates.append((func, endpoint))
            except AttributeError:
                continue

        if not untrusted_candidates:
            raise ProtocolError('no such method: {!r}'.format(self.method))

        assert len(untrusted_candidates) == 1, \
            'multiple candidates for method {!r}'.format(self.method)

        #: the method to execute
        self._handler = untrusted_candidates[0]
        self._running_handler = None
        del untrusted_candidates

    def execute(self, *, untrusted_payload):
        '''Execute management operation.

        This method is a coroutine.
        '''
        handler, endpoint = self._handler
        kwargs = {}
        if endpoint is not None:
            kwargs['endpoint'] = endpoint
        self._running_handler = asyncio.ensure_future(handler(
            untrusted_payload=untrusted_payload, **kwargs))
        return self._running_handler

    def cancel(self):
        '''If operation is cancellable, interrupt it'''
        if self.cancellable and self._running_handler is not None:
            self._running_handler.cancel()


    def fire_event_for_permission(self, **kwargs):
        '''Fire an event on the source qube to check for permission'''
        return self.src.fire_event_pre('mgmt-permission:' + self.method,
            dest=self.dest, arg=self.arg, **kwargs)

    def fire_event_for_filter(self, iterable, **kwargs):
        '''Fire an event on the source qube to filter for permission'''
        return apply_filters(iterable,
            self.fire_event_for_permission(**kwargs))
