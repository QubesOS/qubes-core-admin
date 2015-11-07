#!/usr/bin/python2

from __future__ import absolute_import

from qubes.storage.xen import XenStorage, XenPool


def apply(system_path, vm_files, defaults):
    defaults['storage_class'] = XenStorage
    defaults['pool_types'] = {'xen': XenPool}
    defaults['pool_config'] = {'dir': '/var/lib/qubes/'}
