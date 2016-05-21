#!/usr/bin/python2 -O
# vim: fileencoding=utf-8

import warnings

import qubes
import qubes.config
import qubes.vm.qubesvm
from qubes.config import defaults
from qubes.vm.qubesvm import QubesVM


class TemplateVM(QubesVM):
    '''Template for AppVM'''

    dir_path_prefix = qubes.config.system_path['qubes_templates_dir']

    @property
    def rootcow_img(self):
        '''COW image'''
        warnings.warn("rootcow_img is deprecated, use "
                      "volumes['root'].path_origin", DeprecationWarning)
        return self.volumes['root'].path_cow

    @property
    def appvms(self):
        for vm in self.app.domains:
            if hasattr(vm, 'template') and vm.template is self:
                yield vm

    def __init__(self, *args, **kwargs):
        assert 'template' not in kwargs, "A TemplateVM can not have a template"
        self.volume_config = {
            'root': {
                'name': 'root',
                'pool': 'default',
                'volume_type': 'origin',
                'size': defaults['root_img_size'],
            },
            'private': {
                'name': 'private',
                'pool': 'default',
                'volume_type': 'read-write',
                'size': defaults['private_img_size'],
            },
            'volatile': {
                'name': 'volatile',
                'pool': 'default',
                'size': defaults['root_img_size'],
                'volume_type': 'volatile',
            },
            'kernel': {
                'name': 'kernel',
                'pool': 'linux-kernel',
                'volume_type': 'read-only',
            }
        }
        super(TemplateVM, self).__init__(*args, **kwargs)

    def clone_disk_files(self, src):
        super(TemplateVM, self).clone_disk_files(src)

        # Create root-cow.img
        self.commit_changes()

    def commit_changes(self):
        '''Commit changes to template'''
        self.log.debug('commit_changes()')

        if not self.app.vmm.offline_mode:
            assert not self.is_running(), \
                'Attempt to commit changes on running Template VM!'

        self.storage.commit_template_changes()
