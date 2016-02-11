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

import ConfigParser
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
CONFIG_FILE = '/etc/qubes/storage.conf'


class StoragePoolException(qubes.exc.QubesException):
    pass


class Storage(object):
    '''Class for handling VM virtual disks.

    This is base class for all other implementations, mostly with Xen on Linux
    in mind.
    '''

    root_img = None
    private_img = None
    volatile_img = None

    modules_dev = None

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


    def get_config_params(self):
        args = {}
        args['rootdev'] = self.root_dev_config()
        args['privatedev'] = self.private_dev_config()
        args['volatiledev'] = self.volatile_dev_config()
        args['otherdevs'] = self.other_dev_config()

        args['kerneldir'] = self.kernels_dir

        return args


    def root_dev_config(self):
        raise NotImplementedError()

    def private_dev_config(self):
        raise NotImplementedError()

    def volatile_dev_config(self):
        raise NotImplementedError()

    def other_dev_config(self):
        if self.modules_img is not None:
            return self.format_disk_dev(self.modules_img, self.modules_dev,
                rw=self.modules_img_rw)
        elif self.drive is not None:
            (drive_type, drive_domain, drive_path) = self.drive.split(":")
            if drive_type == 'hd':
                drive_type = 'disk'

            rw = (drive_type == 'disk')

            if drive_domain.lower() == "dom0":
                drive_domain = None

            return self.format_disk_dev(drive_path,
                self.modules_dev,
                rw=rw,
                devtype=drive_type,
                domain=drive_domain)

        else:
            return ''

    def format_disk_dev(self, path, vdev, script=None, rw=True, devtype='disk',
            domain=None):
        raise NotImplementedError()


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

        modules_path = os.path.join(self.kernels_dir, 'modules.img')

        if os.path.exists(modules_path):
            return modules_path
        else:
            return None


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


    @staticmethod
    def _copy_file(source, destination):
        '''Effective file copy, preserving sparse files etc.
        '''
        # TODO: Windows support

        # We prefer to use Linux's cp, because it nicely handles sparse files
        try:
            subprocess.check_call(['cp', '--reflink=auto', source, destination])
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
        if source_template is None and hasattr(self.vm, 'template'):
            source_template = self.vm.template

        old_umask = os.umask(002)

        self.vm.log.info('Creating directory: {0}'.format(self.vm.dir_path))
        os.mkdir(self.vm.dir_path)
        self.create_on_disk_private_img(source_template)
        self.create_on_disk_root_img(source_template)
        self.reset_volatile_storage()

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

        .. versionchange:: 4.0
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


    def reset_volatile_storage(self):
        # Re-create only for template based VMs
        try:
            if self.vm.template is not None and self.volatile_img:
                if os.path.exists(self.volatile_img):
                    os.remove(self.volatile_img)
        except AttributeError: # self.vm.template
            pass

        # For StandaloneVM create it only if not already exists
        # (eg after backup-restore)
        if hasattr(self, 'volatile_img') \
                and not os.path.exists(self.volatile_img):
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


def load(clsname):
    '''Given a dotted full module string representation of a class it loads it

        Args:
            string (str) i.e. 'qubes.storage.xen.QubesXenVmStorage'

        Returns:
            type

        See also:
            :func:`qubes.storage.dump`

    :raises ImportError: when storage class specified in config cannot be found
    :raises KeyError: when storage class specified in config cannot be found
    '''

    if not isinstance(clsname, basestring):
        return clsname
    pkg, cls = clsname.strip().rsplit('.', 1)

    # this may raise ImportError or KeyError, that's okay
    return importlib.import_module(pkg).__dict__[cls]


def dump(o):
    """ Returns a string represention of the given object

        Args:
            o (object): anything that response to `__module__` and `__class__`

        Given the class :class:`qubes.storage.QubesVmStorage` it returns
        'qubes.storage.QubesVmStorage' as string
    """
    return o.__module__ + '.' + o.__class__.__name__


def get_pool(name, vm):
    """ Instantiates the storage for the specified vm """
    config = _get_storage_config_parser()

    klass = _get_pool_klass(name, config)

    keys = [k for k in config.options(name) if k != 'driver' and k != 'class']
    values = [config.get(name, o) for o in keys]
    config_kwargs = dict(zip(keys, values))

    if name == 'default':
        kwargs = qubes.config.defaults['pool_config'].copy()
        kwargs.update(keys)
    else:
        kwargs = config_kwargs

    return klass(vm, **kwargs)


def pool_exists(name):
    """ Check if the specified pool exists """
    try:
        _get_pool_klass(name)
        return True
    except StoragePoolException:
        return False

def add_pool(name, **kwargs):
    """ Add a storage pool to config."""
    config = _get_storage_config_parser()
    config.add_section(name)
    for key, value in kwargs.iteritems():
        config.set(name, key, value)
    _write_config(config)

def remove_pool(name):
    """ Remove a storage pool from config file.  """
    config = _get_storage_config_parser()
    config.remove_section(name)
    _write_config(config)

def _write_config(config):
    with open(CONFIG_FILE, 'w') as configfile:
        config.write(configfile)

def _get_storage_config_parser():
    """ Instantiates a `ConfigParaser` for specified storage config file.

        Returns:
            RawConfigParser
    """
    config = ConfigParser.RawConfigParser()
    config.read(CONFIG_FILE)
    return config


def _get_pool_klass(name, config=None):
    """ Returns the storage klass for the specified pool.

        Args:
            name: The pool name.
            config: If ``config`` is not specified
                    `_get_storage_config_parser()` is called.

        Returns:
            type: A class inheriting from `QubesVmStorage`
    """
    if config is None:
        config = _get_storage_config_parser()

    if not config.has_section(name):
        raise StoragePoolException('Uknown storage pool ' + name)

    if config.has_option(name, 'class'):
        klass = load(config.get(name, 'class'))
    elif config.has_option(name, 'driver'):
        pool_driver = config.get(name, 'driver')
        klass = load(qubes.config.defaults['pool_drivers'][pool_driver])
    else:
        raise StoragePoolException('Uknown storage pool driver ' + name)
    return klass


class Pool(object):
    def __init__(self, vm, dir_path):
        assert vm is not None
        assert dir_path is not None

        self.vm = vm
        self.dir_path = dir_path

        self.create_dir_if_not_exists(self.dir_path)

        self.vmdir = self.vmdir_path(vm, self.dir_path)

        appvms_path = os.path.join(self.dir_path, 'appvms')
        self.create_dir_if_not_exists(appvms_path)

        servicevms_path = os.path.join(self.dir_path, 'servicevms')
        self.create_dir_if_not_exists(servicevms_path)

        vm_templates_path = os.path.join(self.dir_path, 'vm-templates')
        self.create_dir_if_not_exists(vm_templates_path)

    # XXX there is also a class attribute on the domain classes which does
    # exactly that -- which one should prevail?
    def vmdir_path(self, vm, pool_dir):
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
        if vm.is_template():
            subdir = 'vm-templates'
        elif vm.is_disposablevm():
            subdir = 'appvms'
            return os.path.join(pool_dir, subdir, vm.template.name + '-dvm')
        else:
            subdir = 'appvms'

        return os.path.join(pool_dir, subdir, vm.name)

    def create_dir_if_not_exists(self, path):
        """ Check if a directory exists in if not create it.

            This method does not create any parent directories.
        """
        if not os.path.exists(path):
            os.mkdir(path)
