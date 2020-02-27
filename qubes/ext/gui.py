#
# The Qubes OS Project, https://www.qubes-os.org/
#
# Copyright (C) 2010-2016  Joanna Rutkowska <joanna@invisiblethingslab.com>
# Copyright (C) 2013-2016  Marek Marczykowski-Górecki
#                              <marmarek@invisiblethingslab.com>
# Copyright (C) 2014-2018  Wojtek Porczyk <woju@invisiblethingslab.com>
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


class GUI(qubes.ext.Extension):
    # pylint: disable=too-few-public-methods,unused-argument,no-self-use
    @staticmethod
    def attached_vms(vm):
        for domain in vm.app.domains:
            if getattr(domain, 'guivm', None) and domain.guivm == vm:
                yield domain

    @qubes.ext.handler('domain-pre-shutdown')
    def on_domain_pre_shutdown(self, vm, event, **kwargs):
        attached_vms = [domain for domain in self.attached_vms(vm) if
                        domain.is_running()]
        if attached_vms and not kwargs.get('force', False):
            raise qubes.exc.QubesVMError(
                self, 'There are running VMs using this VM as GuiVM: '
                      '{}'.format(', '.join(vm.name for vm in attached_vms)))

    @staticmethod
    def send_gui_mode(vm):
        vm.run_service('qubes.SetGuiMode',
                       input=('SEAMLESS'
                              if vm.features.get('gui-seamless', False)
                              else 'FULLSCREEN'))

    @qubes.ext.handler('domain-init', 'domain-load')
    def on_domain_init_load(self, vm, event):
        if getattr(vm, 'guivm', None):
            if 'guivm-' + vm.guivm.name not in list(vm.tags):
                self.on_property_set(vm, event, name='guivm', newvalue=vm.guivm)

    # property-del <=> property-reset-to-default
    @qubes.ext.handler('property-del:guivm')
    def on_property_del(self, subject, event, name, oldvalue=None):
        newvalue = getattr(subject, 'guivm', None)
        self.on_property_set(subject, event, name, newvalue, oldvalue)

    @qubes.ext.handler('property-set:guivm')
    def on_property_set(self, subject, event, name, newvalue, oldvalue=None):
        # Clean other 'guivm-XXX' tags.
        # gui-daemon can connect to only one domain
        tags_list = list(subject.tags)
        for tag in tags_list:
            if tag.startswith('guivm-'):
                subject.tags.remove(tag)

        if newvalue:
            guivm = 'guivm-' + newvalue.name
            subject.tags.add(guivm)

    @qubes.ext.handler('domain-qdb-create')
    def on_domain_qdb_create(self, vm, event):
        for feature in ('gui-videoram-overhead', 'gui-videoram-min'):
            try:
                vm.untrusted_qdb.write(
                    '/qubes-{}'.format(feature),
                    vm.features.check_with_template_and_adminvm(
                        feature))
            except KeyError:
                pass

        # Add GuiVM Xen ID for gui-daemon
        if getattr(vm, 'guivm', None):
            if vm != vm.guivm and vm.guivm.is_running():
                vm.untrusted_qdb.write('/qubes-gui-domain-xid',
                                       str(vm.guivm.xid))

            # Add keyboard layout from that of GuiVM
            kbd_layout = vm.guivm.features.get('keyboard-layout', None)
            if kbd_layout:
                vm.untrusted_qdb.write('/keyboard-layout', kbd_layout)

                # Legacy value for setting keyboard layout
                xkb_keymap = \
                    'xkb_keymap {\x0a\x09xkb_keycodes  { include ' \
                    '"evdev"\x09};\x0a\x09xkb_types     { include ' \
                    '"complete"\x09};\x0a\x09xkb_compat    { include ' \
                    '"complete"\x09};\x0a\x09xkb_symbols   { include ' \
                    '"pc+%s+inet(evdev)"\x09};\x0a\x09xkb_geometry  ' \
                    '{ include "pc(pc105)"\x09};\x0a};' % kbd_layout
                vm.untrusted_qdb.write('/qubes-keyboard', xkb_keymap)

        # Set GuiVM prefix
        guivm_windows_prefix = vm.features.get('guivm-windows-prefix', 'GuiVM')
        if vm.features.get('service.guivm-gui-agent', None):
            vm.untrusted_qdb.write('/guivm-windows-prefix',
                                   guivm_windows_prefix)

    @qubes.ext.handler('property-set:default_guivm', system=True)
    def on_property_set_default_guivm(self, app, event, name, newvalue,
                                      oldvalue=None):
        for vm in app.domains:
            if hasattr(vm, 'guivm') and vm.property_is_default('guivm'):
                vm.fire_event('property-set:guivm',
                              name='guivm', newvalue=newvalue,
                              oldvalue=oldvalue)

    @qubes.ext.handler('domain-start')
    def on_domain_start(self, vm, event, **kwargs):
        attached_vms = [domain for domain in self.attached_vms(vm) if
                        domain.is_running()]
        for attached_vm in attached_vms:
            attached_vm.untrusted_qdb.write('/qubes-gui-domain-xid',
                                            str(vm.xid))
