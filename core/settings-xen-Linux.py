#!/usr/bin/python2

from __future__ import absolute_import

from qubes.storage.xen import XenStorage, XenPool


def apply(system_path, vm_files, defaults):
    defaults['storage_class'] = XenStorage
    defaults['pool_drivers'] = {'xen': XenPool}
    defaults['pool_config'] = {'dir_path': '/var/lib/qubes/'}
