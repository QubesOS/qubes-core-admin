# -*- encoding: utf-8 -*-
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

import qubes.events

class DVMTemplateMixin(qubes.events.Emitter):
    '''VM class capable of being DVM template'''

    template_for_dispvms = qubes.property('template_for_dispvms',
        type=bool,
        default=False,
        doc='Should this VM be allowed to start as Disposable VM')

    @qubes.events.handler('property-pre-set:template_for_dispvms')
    def __on_pre_set_dvmtemplate(self, event, name,
            newvalue, oldvalue=None):
        # pylint: disable=unused-argument
        if newvalue:
            return
        if any(self.dispvms):
            raise qubes.exc.QubesVMInUseError(self,
                'Cannot change template_for_dispvms to False while there are '
                'some DispVMs based on this DVM template')

    @qubes.events.handler('property-pre-del:template_for_dispvms')
    def __on_pre_del_dvmtemplate(self, event, name,
            oldvalue=None):
        self.__on_pre_set_dvmtemplate(
            event, name, False, oldvalue)

    @qubes.events.handler('property-pre-set:template')
    def __on_pre_property_set_template(self, event, name, newvalue,
            oldvalue=None):
        # pylint: disable=unused-argument
        for vm in self.dispvms:
            running = vm.is_running()
            assert type(running) is bool
            if running:
                raise qubes.exc.QubesVMNotHaltedError(self,
                    'Cannot change template while there are running DispVMs '
                    'based on this DVM template')

    @qubes.events.handler('property-set:template')
    def __on_property_set_template(self, event, name, newvalue,
            oldvalue=None):
        # pylint: disable=unused-argument
        pass

    @property
    def dispvms(self):
        ''' Returns a generator containing all Disposable VMs based on the
        current AppVM.
        '''
        for vm in self.app.domains:
            if getattr(vm, 'template', None) == self:
                yield vm
