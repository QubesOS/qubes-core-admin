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
import re
import subprocess

import qubes
import qubes.config
import qubes.vm.templatevm
from qubes.storage import Pool, StoragePoolException, Volume


class XenPool(Pool):

    root_dev = 'xvda'
    private_dev = 'xvdb'
    volatile_dev = 'xvdc'

    def __init__(self, vm=None, name=None, dir_path=None):
        super(XenPool, self).__init__(vm=vm, name=name)
        assert dir_path, "No pool dir_path specified"
        self.dir_path = os.path.normpath(dir_path)

        self.create_dir_if_not_exists(self.dir_path)
        appvms_path = os.path.join(self.dir_path, 'appvms')
        self.create_dir_if_not_exists(appvms_path)
        vm_templates_path = os.path.join(self.dir_path, 'vm-templates')
        self.create_dir_if_not_exists(vm_templates_path)

    @property
    def private_img(self):
        '''Path to the private image'''
        return self.abspath(qubes.config.vm_files['private_img'])

    @property
    def root_img(self):
        '''Path to the root image'''
        return self.vm.template.storage.root_img \
            if hasattr(self.vm, 'template') and self.vm.template \
            else self.abspath(qubes.config.vm_files['root_img'])

    @property
    def rootcow_img(self):
        '''Path to the root COW image'''

        if isinstance(self.vm, qubes.vm.templatevm.TemplateVM):
            return self.abspath(qubes.config.vm_files['rootcow_img'])

        return None

    @property
    def volatile_img(self):
        '''Path to the volatile image'''
        return self.abspath(qubes.config.vm_files['volatile_img'])

    def root_dev_config(self):
        dev_name = 'root'
        if isinstance(self.vm, qubes.vm.templatevm.TemplateVM):
            return self.format_disk_dev(
                '{root}:{rootcow}'.format(
                    root=self.root_img,
                    rootcow=self.rootcow_img),
                dev_name,
                script='block-origin')

        elif self.vm.hvm and hasattr(self.vm, 'template'):
            # HVM template-based VM - only one device-mapper layer, in dom0
            # (root+volatile)
            # HVM detection based on 'kernel' property is massive hack,
            # but taken from assumption that VM needs Qubes-specific kernel
            # (actually initramfs) to assemble the second layer of device-mapper
            return self.format_disk_dev(
                '{root}:{volatile}'.format(
                    root=self.vm.template.storage.root_img,
                    volatile=self.volatile_img),
                dev_name,
                script='block-snapshot')

        elif hasattr(self.vm, 'template'):
            # any other template-based VM - two device-mapper layers: one
            # in dom0 (here) from root+root-cow, and another one from
            # this+volatile.img
            path = '{root}:{template_rootcow}'.format(
                root=self.root_img,
                template_rootcow=self.vm.template.storage.rootcow_img)
            return self.format_disk_dev(path=path,
                                        vdev=self.root_dev,
                                        script='block-snapshot',
                                        rw=False)

        else:
            # standalone qube
            return self.format_disk_dev(self.root_img, dev_name)

    def private_dev_config(self):
        return self.format_disk_dev(self.private_img, 'private')

    def volatile_dev_config(self):
        return self.format_disk_dev(self.volatile_img, 'volatile')

    def create_on_disk_private_img(self, source_template=None):
        if not os.path.exists(self.target_dir):
            os.makedirs(self.target_dir)
        if source_template is None:
            f_private = open(self.private_img, 'a+b')
            f_private.truncate(self.private_img_size)
            f_private.close()

        else:
            self.vm.log.info("Copying the template's private image: {}".format(
                source_template.storage.private_img))
            self._copy_file(source_template.storage.private_img, self.private_img)

    def create_on_disk_root_img(self, source_template=None):
        if not os.path.exists(self.target_dir):
            os.makedirs(self.target_dir)
        if source_template is None:
            fd = open(self.root_img, 'a+b')
            fd.truncate(self.root_img_size)
            fd.close()

        elif self.vm.updateable:
            # if not updateable, just use template's disk
            self.vm.log.info(
                "--> Copying the template's root image: {}".format(
                    source_template.storage.root_img))
            self._copy_file(source_template.storage.root_img, self.root_img)

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
            subprocess.check_call(['sudo', 'losetup', '--set-capacity',
                                   loop_dev])

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

    def reset_volatile_storage(self):
        try:
            # no template set, in any way (Standalone VM, Template VM)
            if self.vm.template is None:
                raise AttributeError

            # template-based HVM with only one device-mapper layer -
            # volatile.img used as upper layer on root.img, no root-cow.img
            # intermediate layer
            if self.vm.hvm:
                if os.path.exists(self.volatile_img):
                    if self.vm.debug:
                        if os.path.getmtime(self.vm.template.storage.root_img) \
                                > os.path.getmtime(self.volatile_img):
                            self.vm.log.warning(
                                'Template have changed, resetting root.img')
                        else:
                            self.vm.log.warning(
                                'Debug mode: not resetting root.img; if you'
                                ' want to force root.img reset, either'
                                ' update template VM, or remove volatile.img'
                                ' file.')
                            return

                    os.remove(self.volatile_img)

                # FIXME stat on f_root; with open() ...
                f_volatile = open(self.volatile_img, "w")
                f_root = open(self.vm.template.storage.root_img, "r")
                # make empty sparse file of the same size as root.img
                f_root.seek(0, os.SEEK_END)
                f_volatile.truncate(f_root.tell())
                f_volatile.close()
                f_root.close()
                return  # XXX why is that? super() does not run
        except AttributeError:  # self.vm.template
            pass

        super(XenPool, self).reset_volatile_storage()

    def prepare_for_vm_startup(self):
        super(XenPool, self).prepare_for_vm_startup()

        if self.drive is not None:
            # pylint: disable=unused-variable
            (drive_type, drive_domain, drive_path) = self.drive.split(":")

            if drive_domain.lower() != "dom0":
                # XXX "VM '{}' holding '{}' does not exists".format(
                drive_vm = self.vm.app.domains[drive_domain]

                if not drive_vm.is_running():
                    raise qubes.exc.QubesVMNotRunningError(
                        drive_vm, 'VM {!r} holding {!r} isn\'t running'.format(
                            drive_domain, drive_path))

        if self.rootcow_img and not os.path.exists(self.rootcow_img):
            self.commit_template_changes()

    # XXX there is also a class attribute on the domain classes which does
    # exactly that -- which one should prevail?
    @property
    def target_dir(self):
        """ Returns the path to vmdir depending on the type of the VM.

            The default QubesOS file storage saves the vm images in three
            different directories depending on the ``QubesVM`` type:

            * ``appvms`` for ``QubesAppVm`` or ``QubesHvm``
            * ``vm-templates`` for ``QubesTemplateVm`` or ``QubesTemplateHvm``

            Args:
                vm: a QubesVM
                pool_dir: the root directory of the pool

            Returns:
                string (str) absolute path to the directory where the vm files
                             are stored
        """
        vm = self.vm
        if vm.is_template():
            subdir = 'vm-templates'
        elif vm.is_disposablevm():
            subdir = 'appvms'
            return os.path.join(self.dir_path, subdir,
                                vm.template.name + '-dvm')
        else:
            subdir = 'appvms'

        return os.path.join(self.dir_path, subdir, vm.name)

    def abspath(self, file_name):
        return os.path.join(self.target_dir, file_name)
