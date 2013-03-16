#!/usr/bin/python2
#
# The Qubes OS Project, http://www.qubes-os.org
#
# Copyright (C) 2010  Joanna Rutkowska <joanna@invisiblethingslab.com>
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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.
#
#

import os

from qubes.qubes import QubesVm,register_qubes_vm_class,xs,dry_run
from qubes.qubes import system_path,defaults

system_path["config_template_hvm"] = '/usr/share/qubes/vm-template-hvm.conf'

defaults["hvm_disk_size"] = 20*1024*1024*1024
defaults["hvm_private_img_size"] = 2*1024*1024*1024
defaults["hvm_memory"] = 512


class QubesHVm(QubesVm):
    """
    A class that represents an HVM. A child of QubesVm.
    """

    # FIXME: logically should inherit after QubesAppVm, but none of its methods
    # are useful for HVM

    def get_attrs_config(self):
        attrs = super(QubesHVm, self).get_attrs_config()
        attrs.pop('kernel')
        attrs.pop('kernels_dir')
        attrs.pop('kernelopts')
        attrs.pop('uses_default_kernel')
        attrs.pop('uses_default_kernelopts')
        attrs['dir_path']['eval'] = 'value if value is not None else os.path.join(system_path["qubes_appvms_dir"], self.name)'
        attrs['volatile_img']['eval'] = 'None'
        attrs['config_file_template']['eval'] = 'system_path["config_template_hvm"]'
        attrs['drive'] = { 'save': 'str(self.drive)' }
        attrs['maxmem'].pop('save')
        attrs['timezone'] = { 'default': 'localtime', 'save': 'str(self.timezone)' }
        attrs['qrexec_installed'] = { 'default': False, 'save': 'str(self.qrexec_installed)' }
        attrs['guiagent_installed'] = { 'default' : False, 'save': 'str(self.guiagent_installed)' }
        attrs['_start_guid_first']['eval'] = 'True'
        attrs['services']['default'] = "{'meminfo-writer': False}"

        # only standalone HVM supported for now
        attrs['template']['eval'] = 'None'
        attrs['memory']['default'] = defaults["hvm_memory"]

        return attrs

    def __init__(self, **kwargs):

        super(QubesHVm, self).__init__(**kwargs)

        # Default for meminfo-writer have changed to (correct) False in the
        # same version as introduction of guiagent_installed, so for older VMs
        # with wrong setting, change is based on 'guiagent_installed' presence
        if "guiagent_installed" not in kwargs and \
            (not 'xml_element' in kwargs or kwargs['xml_element'].get('guiagent_installed') is None):
            self.services['meminfo-writer'] = False

        # HVM normally doesn't support dynamic memory management
        if not ('meminfo-writer' in self.services and self.services['meminfo-writer']):
            self.maxmem = self.memory

        # Disable qemu GUID if the user installed qubes gui agent
        if self.guiagent_installed:
            self._start_guid_first = False

    @property
    def type(self):
        return "HVM"

    def is_appvm(self):
        return True

    def get_clone_attrs(self):
        attrs = super(QubesHVm, self).get_clone_attrs()
        attrs.remove('kernel')
        attrs.remove('uses_default_kernel')
        attrs.remove('kernelopts')
        attrs.remove('uses_default_kernelopts')
        attrs += [ 'timezone' ]
        attrs += [ 'qrexec_installed' ]
        attrs += [ 'guiagent_installed' ]
        return attrs

    def create_on_disk(self, verbose, source_template = None):
        if dry_run:
            return

        if verbose:
            print >> sys.stderr, "--> Creating directory: {0}".format(self.dir_path)
        os.mkdir (self.dir_path)

        if verbose:
            print >> sys.stderr, "--> Creating icon symlink: {0} -> {1}".format(self.icon_path, self.label.icon_path)
        os.symlink (self.label.icon_path, self.icon_path)

        self.create_config_file()

        # create empty disk
        f_root = open(self.root_img, "w")
        f_root.truncate(defaults["hvm_disk_size"])
        f_root.close()

        # create empty private.img
        f_private = open(self.private_img, "w")
        f_private.truncate(defaults["hvm_private_img_size"])
        f_root.close()

        # fire hooks
        for hook in self.hooks_create_on_disk:
            hook(self, verbose, source_template=source_template)

    def get_disk_utilization_private_img(self):
        return 0

    def get_private_img_sz(self):
        return 0

    def resize_private_img(self, size):
        raise NotImplementedError("HVM has no private.img")

    def get_config_params(self, source_template=None):

        params = super(QubesHVm, self).get_config_params(source_template=source_template)

        params['volatiledev'] = ''
        if self.drive:
            type_mode = ":cdrom,r"
            drive_path = self.drive
            # leave empty to use standard syntax in case of dom0
            backend_domain = ""
            if drive_path.startswith("hd:"):
                type_mode = ",w"
                drive_path = drive_path[3:]
            elif drive_path.startswith("cdrom:"):
                type_mode = ":cdrom,r"
                drive_path = drive_path[6:]
            backend_split = re.match(r"^([a-zA-Z0-9-]*):(.*)", drive_path)
            if backend_split:
                backend_domain = "," + backend_split.group(1)
                drive_path = backend_split.group(2)

            # FIXME: os.stat will work only when backend in dom0...
            stat_res = None
            if backend_domain == "":
                stat_res = os.stat(drive_path)
            if stat_res and stat.S_ISBLK(stat_res.st_mode):
                params['otherdevs'] = "'phy:%s,xvdc%s%s'," % (drive_path, type_mode, backend_domain)
            else:
                params['otherdevs'] = "'script:file:%s,xvdc%s%s'," % (drive_path, type_mode, backend_domain)
        else:
             params['otherdevs'] = ''

        # Disable currently unused private.img - to be enabled when TemplateHVm done
        params['privatedev'] = ''

        if self.timezone.lower() == 'localtime':
             params['localtime'] = '1'
             params['timeoffset'] = '0'
        elif self.timezone.isdigit():
            params['localtime'] = '0'
            params['timeoffset'] = self.timezone
        else:
            print >>sys.stderr, "WARNING: invalid 'timezone' value: %s" % self.timezone
            params['localtime'] = '0'
            params['timeoffset'] = '0'
        return params

    def verify_files(self):
        if dry_run:
            return

        if not os.path.exists (self.dir_path):
            raise QubesException (
                    "VM directory doesn't exist: {0}".\
                    format(self.dir_path))

        if self.is_updateable() and not os.path.exists (self.root_img):
            raise QubesException (
                    "VM root image file doesn't exist: {0}".\
                    format(self.root_img))

        if not os.path.exists (self.private_img):
            print >>sys.stderr, "WARNING: Creating empty VM private image file: {0}".\
                format(self.private_img)
            f_private = open(self.private_img, "w")
            f_private.truncate(defaults["hvm_private_img_size"])
            f_private.close()

        # fire hooks
        for hook in self.hooks_verify_files:
            hook(self)

        return True

    def reset_volatile_storage(self, **kwargs):
        pass

    @property
    def vif(self):
        if self.xid < 0:
            return None
        if self.netvm is None:
            return None
        return "vif{0}.+".format(self.stubdom_xid)

    def run(self, command, **kwargs):
        if self.qrexec_installed:
            if 'gui' in kwargs and kwargs['gui']==False:
                command = "nogui:" + command
            return super(QubesHVm, self).run(command, **kwargs)
        else:
            raise QubesException("Needs qrexec agent installed in VM to use this function. See also qvm-prefs.")

    @property
    def stubdom_xid(self):
        if self.xid < 0:
            return -1

        stubdom_xid_str = xs.read('', '/local/domain/%d/image/device-model-domid' % self.xid)
        if stubdom_xid_str is not None:
            return int(stubdom_xid_str)
        else:
            return -1

    def start_guid(self, verbose = True, notify_function = None):
        # If user force the guiagent, start_guid will mimic a standard QubesVM
        if self.guiagent_installed:
            super(QubesHVm, self).start_guid(verbose, notify_function)
        else:
            if verbose:
                print >> sys.stderr, "--> Starting Qubes GUId..."

            retcode = subprocess.call ([system_path["qubes_guid_path"], "-d", str(self.stubdom_xid), "-c", self.label.color, "-i", self.label.icon_path, "-l", str(self.label.index)])
            if (retcode != 0) :
                raise QubesException("Cannot start qubes-guid!")

    def start_qrexec_daemon(self, **kwargs):
        if self.qrexec_installed:
            super(QubesHVm, self).start_qrexec_daemon(**kwargs)

            if self._start_guid_first:
                if kwargs.get('verbose'):
                    print >> sys.stderr, "--> Waiting for user '%s' login..." % self.default_user

                self.wait_for_session(notify_function=kwargs.get('notify_function', None))

    def pause(self):
        if dry_run:
            return

        xc.domain_pause(self.stubdom_xid)
        super(QubesHVm, self).pause()

    def unpause(self):
        if dry_run:
            return

        xc.domain_unpause(self.stubdom_xid)
        super(QubesHVm, self).unpause()

    def is_guid_running(self):
        # If user force the guiagent, is_guid_running will mimic a standard QubesVM
        if self.guiagent_installed:
            return super(QubesHVm, self).is_guid_running()
        else:
            xid = self.stubdom_xid
            if xid < 0:
                return False
            if not os.path.exists('/var/run/qubes/guid-running.%d' % xid):
                return False
            return True


register_qubes_vm_class(QubesHVm)
