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

''' Interface for methods not being part of Admin API, but still handled by
qubesd. '''

import asyncio
import string

import qubes.api
import qubes.api.admin
import qubes.vm.dispvm


class QubesMiscAPI(qubes.api.AbstractQubesAPI):
    @qubes.api.method('qubes.FeaturesRequest', no_payload=True)
    @asyncio.coroutine
    def qubes_features_request(self):
        ''' qubes.FeaturesRequest handler

        VM (mostly templates) can request some features from dom0 for itself.
        Then dom0 (qubesd extension) may respect this request or ignore it.

        Technically, VM first write requested features into QubesDB in
        `/features-request/` subtree, then call this method. The method will
        dispatch 'features-request' event, which may be handled by
        appropriate extensions. Requests not explicitly handled by some
        extension are ignored.
        '''
        assert self.dest.name == 'dom0'
        assert not self.arg

        prefix = '/features-request/'

        untrusted_features = {key[len(prefix):]:
            self.src.qdb.read(key).decode('ascii', errors='strict')
                for key in self.src.qdb.list(prefix)}

        safe_set = string.ascii_letters + string.digits
        for untrusted_key in untrusted_features:
            untrusted_value = untrusted_features[untrusted_key]
            assert all((c in safe_set) for c in untrusted_value)

        self.src.fire_event('features-request',
            untrusted_features=untrusted_features)
        self.app.save()

    @qubes.api.method('qubes.NotifyTools', no_payload=True)
    @asyncio.coroutine
    def qubes_notify_tools(self):
        '''
        Legacy version of qubes.FeaturesRequest, used by Qubes Windows Tools
        '''
        assert self.dest.name == 'dom0'
        assert not self.arg

        if getattr(self.src, 'template', None):
            self.src.log.warning(
                'Ignoring qubes.NotifyTools for template-based VM')
            return

        # for now used only to check for the tools presence
        untrusted_version = self.src.qdb.read('/qubes-tools/version')

        # reserved for future use
        #untrusted_os = self.src.qdb.read('/qubes-tools/os')

        # qrexec agent presence (0 or 1)
        untrusted_qrexec = self.src.qdb.read('/qubes-tools/qrexec')

        # gui agent presence (0 or 1)
        untrusted_gui = self.src.qdb.read('/qubes-tools/gui')

        # default user for qvm-run etc
        # starting with Qubes 4.x ignored
        #untrusted_user = self.src.qdb.read('/qubes-tools/default-user')

        if untrusted_version is None:
            # tools didn't advertised its features; it's strange that this
            # service is called, but ignore it
            return

        # any suspicious string will raise exception here
        int(untrusted_version)
        del untrusted_version

        # untrusted_os - ignore for now

        if untrusted_qrexec is None:
            qrexec = False
        else:
            qrexec = bool(int(untrusted_qrexec))
        del untrusted_qrexec

        if untrusted_gui is None:
            gui = False
        else:
            gui = bool(int(untrusted_gui))
        del untrusted_gui

        # ignore default_user

        prev_qrexec = self.src.features.get('qrexec', False)
        # Let the tools to be able to enable *or disable*
        # each particular component
        self.src.features['qrexec'] = qrexec
        self.src.features['gui'] = gui
        self.app.save()

        if not prev_qrexec and qrexec:
            # if this is the first time qrexec was advertised, now can finish
            #  template setup
            self.src.fire_event('template-postinstall')

    @qubes.api.method('qubes.NotifyUpdates')
    @asyncio.coroutine
    def qubes_notify_updates(self, untrusted_payload):
        '''
        Receive VM notification about updates availability

        Payload contains a single integer - either 0 (no updates) or some
        positive value (some updates).
        '''

        untrusted_update_count = untrusted_payload.strip()
        assert untrusted_update_count.isdigit()
        # now sanitized
        update_count = int(untrusted_update_count)
        del untrusted_update_count

        if self.src.updateable:
            # Just trust information from VM itself
            self.src.updates_available = bool(update_count)
            self.app.save()
        elif getattr(self.src, 'template', None) is not None:
            # Hint about updates availability in template
            # If template is running - it will notify about updates itself
            if self.src.template.is_running():
                return
            # Ignore no-updates info
            if update_count > 0:
                # If VM is outdated, updates were probably already installed
                # in the template - ignore info
                if self.src.storage.outdated_volumes:
                    return
                self.src.template.updates_available = bool(update_count)
                self.app.save()
