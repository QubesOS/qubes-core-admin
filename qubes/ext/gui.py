#
# The Qubes OS Project, https://www.qubes-os.org/
#
# Copyright (C) 2010-2016  Joanna Rutkowska <joanna@invisiblethingslab.com>
# Copyright (C) 2013-2016  Marek Marczykowski-Górecki
#                              <marmarek@invisiblethingslab.com>
# Copyright (C) 2014-2018  Wojtek Porczyk <woju@invisiblethingslab.com>
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


class GUI(qubes.ext.Extension):
    # pylint: disable=too-few-public-methods
    # TODO put this somewhere...
    @staticmethod
    def send_gui_mode(vm):
        vm.run_service('qubes.SetGuiMode',
                       input=('SEAMLESS'
                              if vm.features.get('gui-seamless', False)
                              else 'FULLSCREEN'))

    @qubes.ext.handler('property-set:guivm')
    def on_property_set(self, subject, event, name, newvalue, oldvalue=None):
        # pylint: disable=unused-argument,no-self-use

        # Clean other 'guivm-XXX' tags.
        # gui-daemon can connect to only one domain
        tags_list = list(subject.tags)
        for tag in tags_list:
            if 'guivm-' in tag:
                subject.tags.remove(tag)

        guivm = 'guivm-' + newvalue.name
        subject.tags.add(guivm)

    @qubes.ext.handler('domain-qdb-create')
    def on_domain_qdb_create(self, vm, event):
        # pylint: disable=unused-argument,no-self-use
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
            if vm != vm.guivm:
                vm.untrusted_qdb.write('/qubes-gui-domain-xid',
                                       str(vm.guivm.xid))

            # Add keyboard layout from that of GuiVM
            kbd_layout = vm.guivm.features.get('keyboard-layout', None)
            if kbd_layout:
                vm.untrusted_qdb.write('/keyboard-layout', kbd_layout)

        # Set GuiVM prefix
        guivm_windows_prefix = vm.features.get('guivm-windows-prefix', 'GuiVM')
        if vm.features.get('service.guivm-gui-agent', None):
            vm.untrusted_qdb.write('/guivm-windows-prefix',
                                   guivm_windows_prefix)
