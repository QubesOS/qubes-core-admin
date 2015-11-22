#!/usr/bin/python2
#
# The Qubes OS Project, http://www.qubes-os.org
#
# Copyright (C) 2013  Marek Marczykowski <marmarek@invisiblethingslab.com>
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301,
# USA.
#

from __future__ import absolute_import

import ConfigParser
import os
import os.path
import shutil
import subprocess
import sys

import qubes.qubesutils
from qubes.qubes import QubesException, defaults, system_path

CONFIG_FILE = '/etc/qubes/storage.conf'


class QubesVmStorage(object):
    """
    Class for handling VM virtual disks. This is base class for all other
    implementations, mostly with Xen on Linux in mind.
    """

    def __init__(self, vm,
            private_img_size = None,
            root_img_size = None,
            modules_img = None,
            modules_img_rw = False):
        self.vm = vm
        self.vmdir = vm.dir_path
        if private_img_size:
            self.private_img_size = private_img_size
        else:
            self.private_img_size = defaults['private_img_size']
        if root_img_size:
            self.root_img_size = root_img_size
        else:
            self.root_img_size = defaults['root_img_size']

        self.root_dev = "xvda"
        self.private_dev = "xvdb"
        self.volatile_dev = "xvdc"
        self.modules_dev = "xvdd"

        # For now compute this path still in QubesVm
        self.modules_img = modules_img
        self.modules_img_rw = modules_img_rw

        # Additional drive (currently used only by HVM)
        self.drive = None

    def format_disk_dev(self, path, script, vdev, rw=True, type="disk",
                        domain=None):
        if path is None:
            return ''
        template = "    <disk type='block' device='{type}'>\n" \
                   "      <driver name='phy'/>\n" \
                   "      <source dev='{path}'/>\n" \
                   "      <target dev='{vdev}' bus='xen'/>\n" \
                   "{params}" \
                   "    </disk>\n"
        params = ""
        if not rw:
            params += "      <readonly/>\n"
        if domain:
            params += "      <backenddomain name='%s'/>\n" % domain
        if script:
            params += "      <script path='%s'/>\n" % script
        return template.format(path=path, vdev=vdev, type=type, params=params)

    def get_config_params(self):
        args = {}
        args['rootdev'] = self.root_dev_config()
        args['privatedev'] = self.private_dev_config()
        args['volatiledev'] = self.volatile_dev_config()
        args['otherdevs'] = self.other_dev_config()

        return args

    def root_dev_config(self):
        raise NotImplementedError

    def private_dev_config(self):
        raise NotImplementedError

    def volatile_dev_config(self):
        raise NotImplementedError

    def other_dev_config(self):
        if self.modules_img is not None:
            return self.format_disk_dev(self.modules_img,
                                        None,
                                        self.modules_dev,
                                        self.modules_img_rw)
        elif self.drive is not None:
            (drive_type, drive_domain, drive_path) = self.drive.split(":")
            if drive_type == "hd":
                drive_type = "disk"

            writable = False
            if drive_type == "disk":
                writable = True

            if drive_domain.lower() == "dom0":
                drive_domain = None

            return self.format_disk_dev(drive_path, None,
                                        self.modules_dev,
                                        rw=writable,
                                        type=drive_type,
                                        domain=drive_domain)
        else:
            return ''

    def _copy_file(self, source, destination):
        """
        Effective file copy, preserving sparse files etc.
        """
        # TODO: Windows support

        # We prefer to use Linux's cp, because it nicely handles sparse files
        retcode = subprocess.call (["cp", "--reflink=auto", source, destination])
        if retcode != 0:
            raise IOError ("Error while copying {0} to {1}".\
                           format(source, destination))

    def get_disk_utilization(self):
        return qubes.qubesutils.get_disk_usage(self.vmdir)

    def get_disk_utilization_private_img(self):
        return qubes.qubesutils.get_disk_usage(self.private_img)

    def get_private_img_sz(self):
        if not os.path.exists(self.private_img):
            return 0

        return os.path.getsize(self.private_img)

    def resize_private_img(self, size):
        raise NotImplementedError

    def create_on_disk_private_img(self, verbose, source_template = None):
        raise NotImplementedError

    def create_on_disk_root_img(self, verbose, source_template = None):
        raise NotImplementedError

    def create_on_disk(self, verbose, source_template = None):
        if source_template is None:
            source_template = self.vm.template

        old_umask = os.umask(002)
        if verbose:
            print >> sys.stderr, "--> Creating directory: {0}".format(self.vmdir)
        os.mkdir (self.vmdir)

        self.create_on_disk_private_img(verbose, source_template)
        self.create_on_disk_root_img(verbose, source_template)
        self.reset_volatile_storage(verbose, source_template)

        os.umask(old_umask)

    def clone_disk_files(self, src_vm, verbose):
        if verbose:
            print >> sys.stderr, "--> Creating directory: {0}".format(self.vmdir)
        os.mkdir (self.vmdir)

        if src_vm.private_img is not None and self.private_img is not None:
            if verbose:
                print >> sys.stderr, "--> Copying the private image:\n{0} ==>\n{1}".\
                        format(src_vm.private_img, self.private_img)
            self._copy_file(src_vm.private_img, self.private_img)

        if src_vm.updateable and src_vm.root_img is not None and self.root_img is not None:
            if verbose:
                print >> sys.stderr, "--> Copying the root image:\n{0} ==>\n{1}".\
                        format(src_vm.root_img, self.root_img)
            self._copy_file(src_vm.root_img, self.root_img)

            # TODO: modules?

    def rename(self, old_name, new_name):
        old_vmdir = self.vmdir
        new_vmdir = os.path.join(os.path.dirname(self.vmdir), new_name)
        os.rename(self.vmdir, new_vmdir)
        self.vmdir = new_vmdir
        if self.private_img:
            self.private_img = self.private_img.replace(old_vmdir, new_vmdir)
        if self.root_img:
            self.root_img = self.root_img.replace(old_vmdir, new_vmdir)
        if self.volatile_img:
            self.volatile_img = self.volatile_img.replace(old_vmdir, new_vmdir)

    def verify_files(self):
        if not os.path.exists (self.vmdir):
            raise QubesException (
                "VM directory doesn't exist: {0}".\
                format(self.vmdir))

        if self.root_img and not os.path.exists (self.root_img):
            raise QubesException (
                "VM root image file doesn't exist: {0}".\
                format(self.root_img))

        if self.private_img and not os.path.exists (self.private_img):
            raise QubesException (
                "VM private image file doesn't exist: {0}".\
                format(self.private_img))
        if self.modules_img is not None:
            if not os.path.exists(self.modules_img):
                raise QubesException (
                        "VM kernel modules image does not exists: {0}".\
                                format(self.modules_img))

    def remove_from_disk(self):
        shutil.rmtree (self.vmdir)

    def reset_volatile_storage(self, verbose = False, source_template = None):
        if source_template is None:
            source_template = self.vm.template

        # Re-create only for template based VMs
        if source_template is not None and self.volatile_img:
            if os.path.exists(self.volatile_img):
                os.remove(self.volatile_img)

        # For StandaloneVM create it only if not already exists (eg after backup-restore)
        if self.volatile_img and not os.path.exists(self.volatile_img):
            if verbose:
                print >> sys.stderr, "--> Creating volatile image: {0}...".\
                        format(self.volatile_img)
            subprocess.check_call([system_path["prepare_volatile_img_cmd"],
                self.volatile_img, str(self.root_img_size / 1024 / 1024)])

    def prepare_for_vm_startup(self, verbose):
        self.reset_volatile_storage(verbose=verbose)

        if self.private_img and not os.path.exists (self.private_img):
            print >>sys.stderr, "WARNING: Creating empty VM private image file: {0}".\
                format(self.private_img)
            self.create_on_disk_private_img(verbose=False)


def dump(o):
    """ Returns a string represention of the given object

        Args:
            o (object): anything that response to `__module__` and `__class__`

        Given the class :class:`qubes.storage.QubesVmStorage` it returns
        'qubes.storage.QubesVmStorage' as string
    """
    return o.__module__ + '.' + o.__class__.__name__


def load(string):
    """ Given a dotted full module string representation of a class it loads it

        Args:
            string (str) i.e. 'qubes.storage.xen.QubesXenVmStorage'

        Returns:
            type

        See also:
            :func:`qubes.storage.dump`
    """
    if not type(string) is str:
        # This is a hack which allows giving a real class to a vm instead of a
        # string as string_class parameter.
        return string

    components = string.split(".")
    module_path = ".".join(components[:-1])
    klass = components[-1:][0]
    module = __import__(module_path, fromlist=[klass])
    return getattr(module, klass)


def get_pool(name, vm):
    """ Instantiates the storage for the specified vm """
    config = _get_storage_config_parser()

    klass = _get_pool_klass(name, config)

    keys = [k for k in config.options(name) if k != 'driver' and k != 'class']
    values = [config.get(name, o) for o in keys]
    config_kwargs = dict(zip(keys, values))

    if name == 'default':
        kwargs = defaults['pool_config'].copy()
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
        klass = defaults['pool_drivers'][pool_driver]
    else:
        raise StoragePoolException('Uknown storage pool driver ' + name)
    return klass


class StoragePoolException(QubesException):
    pass


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

    def vmdir_path(self, vm, pool_dir):
        """ Returns the path to vmdir depending on the type of the VM.

            The default QubesOS file storage saves the vm images in three
            different directories depending on the ``QubesVM`` type:

            * ``appvms`` for ``QubesAppVm`` or ``QubesHvm``
            * ``vm-templates`` for ``QubesTemplateVm`` or ``QubesTemplateHvm``
            * ``servicevms`` for any subclass of  ``QubesNetVm``

            Args:
                vm: a QubesVM
                pool_dir: the root directory of the pool

            Returns:
                string (str) absolute path to the directory where the vm files
                             are stored
        """
        if vm.is_appvm():
            subdir = 'appvms'
        elif vm.is_template():
            subdir = 'vm-templates'
        elif vm.is_netvm():
            subdir = 'servicevms'
        elif vm.is_disposablevm():
            subdir = 'appvms'
            return os.path.join(pool_dir, subdir, vm.template.name + '-dvm')
        else:
            raise QubesException(vm.type() + ' unknown vm type')

        return os.path.join(pool_dir, subdir, vm.name)

    def create_dir_if_not_exists(self, path):
        """ Check if a directory exists in if not create it.

            This method does not create any parent directories.
        """
        if not os.path.exists(path):
            os.mkdir(path)
