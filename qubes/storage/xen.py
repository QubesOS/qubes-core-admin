#!/usr/bin/python2 -O
# vim: fileencoding=utf-8

#
# The Qubes OS Project, https://www.qubes-os.org/
#
# Copyright (C) 2015  Joanna Rutkowska <joanna@invisiblethingslab.com>
# Copyright (C) 2013-2015  Marek Marczykowski-Górecki
#                              <marmarek@invisiblethingslab.com>
# Copyright (C) 2015  Wojtek Porczyk <woju@invisiblethingslab.com>
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

from __future__ import absolute_import

import os
import os.path
import subprocess
import sys

import lxml.etree

import qubes
import qubes.config
import qubes.storage
import qubes.vm.templatevm


class XenVMStorage(qubes.storage.VMStorage):
    '''Class for VM storage of Xen VMs.
    '''

    root_dev = 'xvda'
    private_dev = 'xvdb'
    volatile_dev = 'xvdc'
    modules_dev = 'xvdd'


    @staticmethod
    def _format_disk_dev(path, vdev, script=None, rw=True, type='disk',
            domain=None):
        if path is None:
            return ''

        element = lxml.etree.Element('disk')
        element.set('type', 'block')
        element.set('device', type)

        element.append(lxml.etree.Element('driver', name='phy'))
        element.append(lxml.etree.Element('source', dev=path))
        element.append(lxml.etree.Element('target', dev=vdev))

        if not rw:
            element.append(lxml.etree.Element('readonly'))
        if domain is not None:
            # XXX vm.name?
            element.append(lxml.etree.Element('domain', name=domain))
        if script:
            element.append(lxml.etree.Element('script', path=script))

        # TODO return element
        return lxml.etree.tostring(element)


    def _get_rootdev(self):
        if isinstance(self.vm, qubes.vm.templatevm.TemplateVM):
            return self._format_disk_dev(
                '{}:{}'.format(self.root_img, self.rootcow_img),
                self.root_dev,
                script='block-origin')

        elif hasattr(self.vm, 'template'):
            return self._format_disk_dev(
                '{}:{}'.format(self.root_img, self.vm.template.rootcow_img),
                self.root_dev,
                script='block-snapshot')

        else:
            return self._format_disk_dev(self.root_img, self.root_dev)


    def get_config_params(self):
        args = {}
        args['rootdev'] = self._get_rootdev()
        args['privatedev'] = self._format_disk_dev(self.private_img,
            self.private_dev)
        args['volatiledev'] = self._format_disk_dev(self.volatile_img,
            self.volatile_dev)

        if self.modules_img is not None:
            args['otherdevs'] = self._format_disk_dev(self.modules_img,
                self.modules_dev, rw=self.modules_img_rw)
        elif self.drive is not None:
            (drive_type, drive_domain, drive_path) = self.drive.split(":")
            if drive_domain.lower() == "dom0":
                drive_domain = None

            args['otherdevs'] = self._format_disk_dev(drive_path,
                self.modules_dev,
                rw=(drive_type == "disk"),
                type=drive_type,
                domain=drive_domain)

        else:
            args['otherdevs'] = ''

        return args


    def create_on_disk_private_img(self, source_template=None):
        if source_template is None:
            f_private = open(self.private_img, 'a+b')
            f_private.truncate(self.private_img_size)
            f_private.close()

        else:
            self.vm.log.info("Copying the template's private image: {}".format(
                source_template.private_img))
            self._copy_file(source_template.private_img, self.private_img)


    def create_on_disk_root_img(self, source_template=None):
        if source_template is None:
            fd = open(self.root_img, 'a+b')
            fd.truncate(self.root_img_size)
            fd.close()

        elif self.vm.updateable:
            # if not updateable, just use template's disk
            self.vm.log.info("--> Copying the template's root image: {}".format(
                source_template.root_img))
            self._copy_file(source_template.root_img, self.root_img)


    def resize_private_img(self, size):
        fd = open(self.private_img, 'a+b')
        fd.truncate(size)
        fd.close()

        # find loop device if any
        p = subprocess.Popen(
            ['sudo', 'losetup', '--associated', self.private_img],
            stdout=subprocess.PIPE)
        result = p.communicate()

        m = re.match(r'^(/dev/loop\d+):\s', result[0])
        if m is not None:
            loop_dev = m.group(1)

            # resize loop device
            subprocess.check_call(
                ['sudo', 'losetup', '--set-capacity', loop_dev])


    def commit_template_changes(self):
        assert isinstance(self.vm, qubes.vm.templatevm.TemplateVM)

        # TODO: move rootcow_img to this class; the same for vm.is_outdated()
        if os.path.exists(self.vm.rootcow_img):
            os.rename(self.vm.rootcow_img, self.vm.rootcow_img + '.old')

        old_umask = os.umask(002)
        f_cow = open(self.vm.rootcow_img, 'w')
        f_root = open(self.root_img, 'r')
        f_root.seek(0, os.SEEK_END)
        # make empty sparse file of the same size as root.img
        f_cow.truncate(f_root.tell())
        f_cow.close()
        f_root.close()
        os.umask(old_umask)
