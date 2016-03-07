#!/usr/bin/python2 -O
# vim: fileencoding=utf-8
#
# The Qubes OS Project, https://www.qubes-os.org/
#
# Copyright (C) 2010  Joanna Rutkowska <joanna@invisiblethingslab.com>
# Copyright (C) 2013-2016  Marek Marczykowski-Górecki
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
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
#
import base64
import datetime
import qubes.ext
import qubes.vm.qubesvm
import qubes.vm.appvm
import qubes.vm.templatevm
import qubes.utils

yum_proxy_ip = '10.137.255.254'
yum_proxy_port = '8082'


class R3Compatibility(qubes.ext.Extension):
    '''Maintain VM interface compatibility with R3.0 and R3.1.
    At lease where possible.
    '''
    # noinspection PyUnusedLocal
    @qubes.ext.handler('qdb-created')
    def on_qdb_created(self, vm, event):
        """
        :param vm: VM on which QubesDB entries were just created
        :type vm: qubes.vm.qubesvm.QubesVM
        """
        # /qubes-vm-type: AppVM, NetVM, ProxyVM, TemplateVM
        if isinstance(vm, qubes.vm.templatevm.TemplateVM):
            vmtype = 'TemplateVM'
        elif vm.netvm is not None and vm.provides_network:
            vmtype = 'ProxyVM'
        elif vm.netvm is None and vm.provides_network:
            vmtype = 'NetVM'
        else:
            vmtype = 'AppVM'
        vm.qdb.write('/qubes-vm-type', vmtype)

        # /qubes-vm-updateable
        vm.qdb.write('/qubes-vm-updateable', str(vm.updateable))

        # /qubes-base-template
        try:
            if vm.template:
                vm.qdb.write('/qubes-base-template', str(vm.template))
            else:
                vm.qdb.write('/qubes-base-template', '')
        except AttributeError:
            vm.qdb.write('/qubes-base-template', '')

        # /qubes-debug-mode: 0, 1
        vm.qdb.write('/qubes-debug-mode', str(int(vm.debug)))

        # /qubes-timezone
        timezone = vm.qdb.read('/timezone')
        if timezone:
            vm.qdb.write('/qubes-timezone', timezone)

        # /qubes-vm-persistence
        persistence = vm.qdb.read('/persistence')
        if persistence:
            vm.qdb.write('/qubes-vm-persistence', persistence)

        # /qubes-random-seed
        # write a new one, to make sure it wouldn't be reused/leaked
        vm.qdb.write('/qubes-random-seed',
            base64.b64encode(qubes.utils.urandom(64)))

        # /qubes-keyboard
        # not needed for now - the old one is still present

        # Networking
        if vm.provides_network:
            # '/qubes-netvm-network' value is only checked for being non empty
            vm.qdb.write('/qubes-netvm-network', vm.gateway)
            vm.qdb.write('/qubes-netvm-netmask', vm.netmask)
            vm.qdb.write('/qubes-netvm-gateway', vm.gateway)
            vm.qdb.write('/qubes-netvm-primary-dns', vm.dns[0])
            vm.qdb.write('/qubes-netvm-secondary-dns', vm.dns[1])

        if vm.netvm is not None:
            vm.qdb.write('/qubes-ip', vm.ip)
            vm.qdb.write('/qubes-netmask', vm.netvm.netmask)
            vm.qdb.write('/qubes-gateway', vm.netvm.gateway)
            vm.qdb.write('/qubes-primary-dns', vm.dns[0])
            vm.qdb.write('/qubes-secondary-dns', vm.dns[1])
