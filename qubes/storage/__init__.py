#!/usr/bin/python2 -O
# vim: fileencoding=utf-8

#
# The Qubes OS Project, https://www.qubes-os.org/
#
# Copyright (C) 2013-2015  Joanna Rutkowska <joanna@invisiblethingslab.com>
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

import importlib
import os
import os.path
import re
import shutil
import subprocess
import sys

import qubes
import qubes.exc
import qubes.utils

BLKSIZE = 512

class VMStorage(object):
    '''Class for handling VM virtual disks.

    This is base class for all other implementations, mostly with Xen on Linux
    in mind.
    ''' # pylint: disable=abstract-class-little-used

    def __init__(self, vm, private_img_size=None, root_img_size=None):

        #: Domain for which we manage storage
        self.vm = vm

        #: Size of the private image
        self.private_img_size = private_img_size \
            if private_img_size is not None \
            else qubes.config.defaults['private_img_size']

        #: Size of the root image
        self.root_img_size = root_img_size \
            if root_img_size is not None \
            else qubes.config.defaults['root_img_size']

        #: Additional drive (currently used only by HVM)
        self.drive = None


    @property
    def private_img(self):
        '''Path to the private image'''
        return self.abspath(qubes.config.vm_files['private_img'])


    @property
    def root_img(self):
        '''Path to the root image'''
        return self.vm.template.root_img if hasattr(self.vm, 'template') \
            else self.abspath(qubes.config.vm_files['root_img'])


    @property
    def volatile_img(self):
        '''Path to the volatile image'''
        return self.abspath(qubes.config.vm_files['volatile_img'])


    @property
    def kernels_dir(self):
        '''Directory where kernel resides.

        If :py:attr:`self.vm.kernel` is :py:obj:`None`, the this points inside
        :py:attr:`self.vm.dir_path`
        '''
        return os.path.join(qubes.config.system_path['qubes_base_dir'],
            qubes.config.system_path['qubes_kernels_base_dir'], self.vm.kernel)\
            if self.vm.kernel is not None \
        else os.path.join(self.vm.dir_path,
            qubes.config.vm_files['kernels_subdir'])


    @property
    def modules_img(self):
        '''Path to image with modules.

        Depending on domain, this may be global or inside domain's dir.
        '''
        return os.path.join(self.kernels_dir, 'modules.img')


    @property
    def modules_img_rw(self):
        ''':py:obj:`True` if module image should be mounted RW, :py:obj:`False`
        otherwise.'''
        return self.vm.kernel is None


    def abspath(self, path, rel=None):
        '''Make absolute path.

        If given path is relative, it is interpreted as relative to
        :py:attr:`self.vm.dir_path` or given *rel*.
        '''
        return path if os.path.isabs(path) \
            else os.path.join(rel or self.vm.dir_path, path)


    def get_config_params(self):
        raise NotImplementedError()

    @staticmethod
    def _copy_file(source, destination):
        '''Effective file copy, preserving sparse files etc.
        '''
        # TODO: Windows support

        # We prefer to use Linux's cp, because it nicely handles sparse files
        try:
            subprocess.check_call(['cp', source, destination])
        except subprocess.CalledProcessError:
            raise IOError('Error while copying {!r} to {!r}'.format(
                source, destination))

    def get_disk_utilization(self):
        return get_disk_usage(self.vm.dir_path)

    def get_disk_utilization_private_img(self):
        # pylint: disable=invalid-name
        return get_disk_usage(self.private_img)

    def get_private_img_sz(self):
        if not os.path.exists(self.private_img):
            return 0

        return os.path.getsize(self.private_img)

    def resize_private_img(self, size):
        raise NotImplementedError()

    def create_on_disk_private_img(self, source_template=None):
        raise NotImplementedError()

    def create_on_disk_root_img(self, source_template=None):
        raise NotImplementedError()

    def create_on_disk(self, source_template=None):
        if source_template is None:
            source_template = self.vm.template

        old_umask = os.umask(002)

        self.vm.log.info('Creating directory: {0}'.format(self.vm.dir_path))
        os.mkdir(self.vm.dir_path)
        self.create_on_disk_private_img(source_template)
        self.create_on_disk_root_img(source_template)
        self.reset_volatile_storage(source_template)

        os.umask(old_umask)

    def clone_disk_files(self, src_vm):
        self.vm.log.info('Creating directory: {0}'.format(self.vm.dir_path))
        os.mkdir(self.vm.dir_path)

        if hasattr(src_vm, 'private_img'):
            self.vm.log.info('Copying the private image: {} -> {}'.format(
                src_vm.private_img, self.vm.private_img))
            self._copy_file(src_vm.private_img, self.vm.private_img)

        if src_vm.updateable and hasattr(src_vm, 'root_img'):
            self.vm.log.info('Copying the root image: {} -> {}'.format(
                src_vm.root_img, self.root_img))
            self._copy_file(src_vm.root_img, self.root_img)

            # TODO: modules?
            # XXX which modules? -woju


    @staticmethod
    def rename(newpath, oldpath):
        '''Move storage directory, most likely during domain's rename.

        .. note::
            The arguments are in different order than in :program:`cp` utility.

        .. versionchange:: 3.0
            This is now dummy method that just passes everything to
            :py:func:`os.rename`.

        :param str newpath: New path
        :param str oldpath: Old path
        '''

        os.rename(oldpath, newpath)


    def verify_files(self):
        if not os.path.exists(self.vm.dir_path):
            raise qubes.exc.QubesVMError(self.vm,
                'VM directory does not exist: {}'.format(self.vm.dir_path))

        if hasattr(self.vm, 'root_img') and not os.path.exists(self.root_img):
            raise qubes.exc.QubesVMError(self.vm,
                'VM root image file does not exist: {}'.format(self.root_img))

        if hasattr(self.vm, 'private_img') \
                and not os.path.exists(self.private_img):
            raise qubes.exc.QubesVMError(self.vm,
                'VM private image file does not exist: {}'.format(
                    self.private_img))

        if self.modules_img is not None \
                and not os.path.exists(self.modules_img):
            raise qubes.exc.QubesVMError(self.vm,
                'VM kernel modules image does not exists: {}'.format(
                    self.modules_img))


    def remove_from_disk(self):
        shutil.rmtree(self.vm.dir_path)


    def reset_volatile_storage(self, source_template=None):
        if source_template is None:
            source_template = self.vm.template

        # Re-create only for template based VMs
        if source_template is not None and self.volatile_img:
            if os.path.exists(self.volatile_img):
                os.remove(self.volatile_img)

        # For StandaloneVM create it only if not already exists
        # (eg after backup-restore)
        if hasattr(self.vm, 'volatile_img') \
                and not os.path.exists(self.vm.volatile_img):
            self.vm.log.info(
                'Creating volatile image: {0}'.format(self.volatile_img))
            subprocess.check_call(
                [qubes.config.system_path["prepare_volatile_img_cmd"],
                    self.volatile_img,
                    str(self.root_img_size / 1024 / 1024)])


    def prepare_for_vm_startup(self):
        self.reset_volatile_storage()

        if hasattr(self.vm, 'private_img') \
                and not os.path.exists(self.private_img):
            self.vm.log.info('Creating empty VM private image file: {0}'.format(
                self.private_img))
            self.create_on_disk_private_img()


def get_disk_usage_one(st):
    '''Extract disk usage of one inode from its stat_result struct.

    If known, get real disk usage, as written to device by filesystem, not
    logical file size. Those values may be different for sparse files.

    :param os.stat_result st: stat result
    :returns: disk usage
    '''
    try:
        return st.st_blocks * BLKSIZE
    except AttributeError:
        return st.st_size


def get_disk_usage(path):
    '''Get real disk usage of given path (file or directory).

    When *path* points to directory, then it is evaluated recursively.

    This function tries estiate real disk usage. See documentation of
    :py:func:`get_disk_usage_one`.

    :param str path: path to evaluate
    :returns: disk usage
    '''
    try:
        st = os.lstat(path)
    except OSError:
        return 0

    ret = get_disk_usage_one(st)

    # if path is not a directory, this is skipped
    for dirpath, dirnames, filenames in os.walk(path):
        for name in dirnames + filenames:
            ret += get_disk_usage_one(os.lstat(os.path.join(dirpath, name)))

    return ret


def get_storage(vm):
    '''Factory yielding storage class instances for domains.

    :raises ImportError: when storage class specified in config cannot be found
    :raises KeyError: when storage class specified in config cannot be found
    '''
    pkg, cls = qubes.config.defaults['storage_class'].strip().rsplit('.', 1)

    # this may raise ImportError or KeyError, that's okay
    return importlib.import_module(pkg).__dict__[cls](vm)
