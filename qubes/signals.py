#!/usr/bin/env python2
# -*- encoding: utf8 -*-
#
# The Qubes OS Project, https://www.qubes-os.org/
#
# Copyright (C) 2016 Bahtiar `kalkin-` Gadimov <bahtiar@gadimov.de>
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
''' Signals are events which need to propagate to the "outer system" like D-Bus,
    GuiDomain & Co.

    When forwarding qubes.events to the "outer system" we have to differentiate
    between different kinds of events:

    - All the events send before/after/including domain-init and domain-load,
      are only useful for core-admin.
    - All the 'property-*' after the domain is loaded need to be buffered as an
      array of events until app.save() is called and only then be send to the
      event_receiver.
    - Events which should be propagated to the event_receiver as soon as
       possible, like domain-add/delete/is-fully-usable
'''

from __future__ import print_function

import sys

import pkg_resources

RECEIVERS_ENTRY_POINT = 'qubes.signals.receivers'


class SignalEmitter(object):
    ''' SignalEmitter implements helper functions to buffer some signals,
        which will be send out once the `_flush_signals()` function is called.

        This is used to buffer property change signals until app.save() is
        called.
    '''

    def __init__(self, *args, **kwargs):
        super(SignalEmitter, self).__init__(*args, **kwargs)
        self.signal_receivers = []
        for entry in pkg_resources.iter_entry_points(RECEIVERS_ENTRY_POINT):
            receiver = entry.load()
            self.signal_receivers.append(receiver())
        self.changes = []
        self._is_loaded = None

    def _buffer(self, name, args, kwargs):
        ''' Adds a signal to the signal buffer, to be flushed out later '''
        if self._is_loaded:
            self.changes.append((name, args, kwargs))

    def _flush_signals(self):
        ''' Send out all the buffered signals '''
        for event_tupple in self.changes:
            self._fire_signal(*event_tupple)
        self.changes = []

    def fire_signal(self, event, *args, **kwargs):
        ''' This function has a hardcoded logic, which decides if an event
            should be send out as a signal immediately or buffered and send out
            when an '*-save' event is fired.

            Keep in mind that the '*-save' event it self is dropped, because it
            doesn't carry any new information for the signal receiver.
        '''
        if not self._is_loaded:
            return
        if event.startswith('property-') \
        or event.startswith('device-attach') \
        or event.startswith('domain-feature-') \
        or event in ['domain-add', 'domain-delete']:
            self._buffer(event, args, kwargs)
        else:
            if len(event.split('-', 1)) == 2:
                _, name = event.split('-', 1)

            if name.startswith('save'):
                self._flush_signals()
            else:
                self._fire_signal(event, *args, **kwargs)

    def _fire_signal(self, name, *args, **kwargs):
        ''' Sends out a signal to each signal receiver '''
        for receiver in self.signal_receivers:
            try:
                receiver.fire_signal(self, name, args, kwargs)
            except Exception as exc:  # pylint: disable=broad-except
                msg = "Can not send event {!r} to the receiver {!r}".format(
                    name, receiver)
                try:
                    # pylint: disable=no-member
                    self.log.warn(msg)
                    self.log.exception(exc)
                except:  # pylint: disable=bare-except
                    print(msg, file=sys.stderr)

    def start_forwarding_signals(self):
        ''' This method needs to be called to start forwarding signals. It
            should be called by the implementing object once it stops
            receiving meaningless preload events like 'domain-load' &
            'domain-init'
        '''
        self._is_loaded = True
