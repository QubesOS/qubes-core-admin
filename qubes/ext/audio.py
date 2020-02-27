#
# The Qubes OS Project, https://www.qubes-os.org/
#
# Copyright (C) 2019 Frédéric Pierret <frederic.pierret@qubes-os.org>
#
# This library is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 2.1 of the License, or (at your option) any later version.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with this library; if not, see <https://www.gnu.org/licenses/>.
#

import qubes.config
import qubes.ext


class AUDIO(qubes.ext.Extension):
    # pylint: disable=unused-argument,no-self-use
    @qubes.ext.handler('domain-init', 'domain-load')
    def on_domain_init_load(self, vm, event):
        if getattr(vm, 'audiovm', None):
            if 'audiovm-' + vm.audiovm not in list(vm.tags):
                vm.fire_event('property-set:audiovm',
                              name='audiovm', newvalue=vm.audiovm)

    # property-del <=> property-reset-to-default
    @qubes.ext.handler('property-del:audiovm')
    def on_property_del(self, subject, event, name, oldvalue=None):
        newvalue = getattr(subject, 'audiovm', None)
        self.on_property_set(subject, event, name, newvalue, oldvalue)

    @qubes.ext.handler('property-set:audiovm')
    def on_property_set(self, subject, event, name, newvalue, oldvalue=None):
        # pylint: disable=unused-argument,no-self-use

        # Clean other 'audiovm-XXX' tags.
        # pulseaudio agent (module-vchan-sink) can connect to only one domain
        tags_list = list(subject.tags)
        for tag in tags_list:
            if 'audiovm-' in tag:
                subject.tags.remove(tag)

        if newvalue:
            audiovm = 'audiovm-' + newvalue.name
            subject.tags.add(audiovm)

    @qubes.ext.handler('domain-qdb-create')
    def on_domain_qdb_create(self, vm, event):
        # pylint: disable=unused-argument,no-self-use
        # Add AudioVM Xen ID for gui-agent
        if getattr(vm, 'audiovm', None):
            if vm != vm.audiovm:
                vm.untrusted_qdb.write('/qubes-audio-domain-xid',
                                       str(vm.audiovm.xid))

    @qubes.ext.handler('property-set:default_audiovm', system=True)
    def on_property_set_default_audiovm(self, app, event, name, newvalue,
                                      oldvalue=None):
        # pylint: disable=unused-argument,no-self-use
        for vm in app.domains:
            if hasattr(vm, 'audiovm') and vm.property_is_default('audiovm'):
                vm.fire_event('property-set:audiovm',
                              name='audiovm', newvalue=newvalue,
                              oldvalue=oldvalue)
