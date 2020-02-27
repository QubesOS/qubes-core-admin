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

import asyncio

import qubes.config
import qubes.ext


class AUDIO(qubes.ext.Extension):
    # pylint: disable=unused-argument,no-self-use
    @staticmethod
    def attached_vms(vm):
        for domain in vm.app.domains:
            if getattr(domain, 'audiovm', None) and domain.audiovm == vm:
                yield domain

    @qubes.ext.handler('domain-pre-shutdown')
    @asyncio.coroutine
    def on_domain_pre_shutdown(self, vm, event, **kwargs):
        attached_vms = [domain for domain in self.attached_vms(vm) if
                        domain.is_running()]
        if attached_vms and not kwargs.get('force', False):
            raise qubes.exc.QubesVMError(
                self, 'There are running VMs using this VM as AudioVM: '
                      '{}'.format(', '.join(vm.name for vm in attached_vms)))

    @qubes.ext.handler('domain-pre-start')
    def on_domain_pre_start(self, vm, event, start_guid, **kwargs):
        if getattr(vm, 'audiovm', None):
            if vm.audiovm.qid != 0:
                if not vm.audiovm.is_running():
                    yield from vm.audiovm.start(start_guid=start_guid,
                                                notify_function=None)

    @qubes.ext.handler('domain-init', 'domain-load')
    def on_domain_init_load(self, vm, event):
        if getattr(vm, 'audiovm', None):
            if 'audiovm-' + vm.audiovm.name not in list(vm.tags):
                vm.fire_event('property-set:audiovm',
                              name='audiovm', newvalue=vm.audiovm)

    # property-del <=> property-reset-to-default
    @qubes.ext.handler('property-del:audiovm')
    def on_property_del(self, subject, event, name, oldvalue=None):
        newvalue = getattr(subject, 'audiovm', None)
        self.on_property_set(subject, event, name, newvalue, oldvalue)

    @qubes.ext.handler('property-set:audiovm')
    def on_property_set(self, subject, event, name, newvalue, oldvalue=None):
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
        # Add AudioVM Xen ID for gui-agent
        if getattr(vm, 'audiovm', None):
            if vm != vm.audiovm:
                vm.untrusted_qdb.write('/qubes-audio-domain-xid',
                                       str(vm.audiovm.xid))

    @qubes.ext.handler('property-set:default_audiovm', system=True)
    def on_property_set_default_audiovm(self, app, event, name, newvalue,
                                        oldvalue=None):
        for vm in app.domains:
            if hasattr(vm, 'audiovm') and vm.property_is_default('audiovm'):
                vm.fire_event('property-set:audiovm',
                              name='audiovm', newvalue=newvalue,
                              oldvalue=oldvalue)
