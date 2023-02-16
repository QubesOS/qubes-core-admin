#
# The Qubes OS Project, http://www.qubes-os.org
#
# Copyright (C) 2014 Marek Marczykowski-Górecki <marmarek@invisiblethingslab.com>
#
# This library is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 2.1 of the License, or (at your option) any later version.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with this library; if not, see <https://www.gnu.org/licenses/>.
#

from multiprocessing import Queue

import asyncio
import os
import shutil
import subprocess

import unittest
import sys
import re

import qubes.tests
import qubes.tests.integ.backup


QUBESXML_R2 = '''
<QubesVmCollection updatevm="3" default_kernel="3.7.6-2" default_netvm="3" default_fw_netvm="2" default_template="1" clockvm="2">
  <QubesTemplateVm installed_by_rpm="True" kernel="3.7.6-2" uses_default_kernelopts="True" qid="1" include_in_backups="True" uses_default_kernel="True" qrexec_timeout="60" internal="False" conf_file="fedora-20-x64.conf" label="black" template_qid="none" kernelopts="" memory="400" default_user="user" netvm_qid="3" uses_default_netvm="True" volatile_img="volatile.img" services="{ 'meminfo-writer': True}" maxmem="1535" pcidevs="[]" name="fedora-20-x64" private_img="private.img" vcpus="2" root_img="root.img" debug="False" dir_path="/var/lib/qubes/vm-templates/fedora-20-x64"/>
  <QubesNetVm installed_by_rpm="False" kernel="3.7.6-2" uses_default_kernelopts="True" qid="2" include_in_backups="True" uses_default_kernel="True" qrexec_timeout="60" internal="False" conf_file="netvm.conf" label="red" template_qid="1" kernelopts="iommu=soft swiotlb=4096" memory="200" default_user="user" volatile_img="volatile.img" services="{'ntpd': False, 'meminfo-writer': False}" maxmem="1535" pcidevs="['02:00.0', '03:00.0']" name="netvm" netid="1" private_img="private.img" vcpus="2" root_img="root.img" debug="False" dir_path="/var/lib/qubes/servicevms/netvm"/>
  <QubesProxyVm installed_by_rpm="False" kernel="3.7.6-2" uses_default_kernelopts="True" qid="3" include_in_backups="True" uses_default_kernel="True" qrexec_timeout="60" internal="False" conf_file="firewallvm.conf" label="green" template_qid="1" kernelopts="" memory="200" default_user="user" netvm_qid="2" volatile_img="volatile.img" services="{'meminfo-writer': True}" maxmem="1535" pcidevs="[]" name="firewallvm" netid="2" private_img="private.img" vcpus="2" root_img="root.img" debug="False" dir_path="/var/lib/qubes/servicevms/firewallvm"/>
  <QubesAppVm installed_by_rpm="False" kernel="3.7.6-2" uses_default_kernelopts="True" qid="4" include_in_backups="True" uses_default_kernel="True" qrexec_timeout="60" internal="True" conf_file="fedora-20-x64-dvm.conf" label="gray" template_qid="1" kernelopts="" memory="400" default_user="user" netvm_qid="3" uses_default_netvm="True" volatile_img="volatile.img" services="{ 'meminfo-writer': True}" maxmem="1535" pcidevs="[]" name="fedora-20-x64-dvm" private_img="private.img" vcpus="1" root_img="root.img" debug="False" dir_path="/var/lib/qubes/appvms/fedora-20-x64-dvm"/>
  <QubesAppVm backup_content="True" backup_path="appvms/test-work" installed_by_rpm="False" kernel="3.7.6-2" uses_default_kernelopts="True" qid="5" include_in_backups="True" uses_default_kernel="True" qrexec_timeout="60" internal="False" conf_file="test-work.conf" label="green" template_qid="1" kernelopts="" memory="400" default_user="user" netvm_qid="3" uses_default_netvm="True" volatile_img="volatile.img" services="{'meminfo-writer': True}" maxmem="1535" pcidevs="[]" name="test-work" private_img="private.img" vcpus="2" root_img="root.img" debug="False" dir_path="/var/lib/qubes/appvms/test-work"/>
  <QubesAppVm installed_by_rpm="False" kernel="3.7.6-2" uses_default_kernelopts="True" qid="6" include_in_backups="True" uses_default_kernel="True" qrexec_timeout="60" internal="False" conf_file="banking.conf" label="green" template_qid="1" kernelopts="" memory="400" default_user="user" netvm_qid="3" uses_default_netvm="True" volatile_img="volatile.img" services="{'meminfo-writer': True}" maxmem="1535" pcidevs="[]" name="banking" private_img="private.img" vcpus="2" root_img="root.img" debug="False" dir_path="/var/lib/qubes/appvms/banking"/>
  <QubesAppVm installed_by_rpm="False" kernel="3.7.6-2" uses_default_kernelopts="True" qid="7" include_in_backups="True" uses_default_kernel="True" qrexec_timeout="60" internal="False" conf_file="personal.conf" label="yellow" template_qid="1" kernelopts="" memory="400" default_user="user" netvm_qid="3" uses_default_netvm="True" volatile_img="volatile.img" services="{'meminfo-writer': True}" maxmem="1535" pcidevs="[]" name="personal" private_img="private.img" vcpus="2" root_img="root.img" debug="False" dir_path="/var/lib/qubes/appvms/personal"/>
  <QubesAppVm installed_by_rpm="False" kernel="3.7.6-2" uses_default_kernelopts="True" qid="8" include_in_backups="True" uses_default_kernel="True" qrexec_timeout="60" internal="False" conf_file="untrusted.conf" label="red" template_qid="1" kernelopts="" memory="400" default_user="user" netvm_qid="12" uses_default_netvm="False" volatile_img="volatile.img" services="{'meminfo-writer': True}" maxmem="1535" pcidevs="[]" name="untrusted" private_img="private.img" vcpus="2" root_img="root.img" debug="False" dir_path="/var/lib/qubes/appvms/untrusted"/>
  <QubesTemplateVm backup_size="104857600" backup_content="True" backup_path="vm-templates/test-template-clone" installed_by_rpm="False" kernel="3.7.6-2" uses_default_kernelopts="True" qid="9" include_in_backups="True" uses_default_kernel="True" qrexec_timeout="60" internal="False" conf_file="test-template-clone.conf" label="green" template_qid="none" kernelopts="" memory="400" default_user="user" netvm_qid="3" uses_default_netvm="True" volatile_img="volatile.img" services="{'meminfo-writer': True}" maxmem="1535" pcidevs="[]" name="test-template-clone" private_img="private.img" vcpus="2" root_img="root.img" debug="False" dir_path="/var/lib/qubes/vm-templates/test-template-clone"/>
  <QubesAppVm backup_size="104857600" backup_content="True" backup_path="appvms/test-custom-template-appvm" installed_by_rpm="False" kernel="3.7.6-2" uses_default_kernelopts="True" qid="10" include_in_backups="True" uses_default_kernel="True" qrexec_timeout="60" internal="False" conf_file="test-custom-template-appvm.conf" label="yellow" template_qid="9" kernelopts="" memory="400" default_user="user" netvm_qid="3" uses_default_netvm="True" volatile_img="volatile.img" services="{'meminfo-writer': True}" maxmem="1535" pcidevs="[]" name="test-custom-template-appvm" private_img="private.img" vcpus="2" root_img="root.img" debug="False" dir_path="/var/lib/qubes/appvms/test-custom-template-appvm"/>
  <QubesAppVm backup_size="104857600" backup_content="True" backup_path="appvms/test-standalonevm" installed_by_rpm="False" kernel="3.7.6-2" uses_default_kernelopts="True" qid="11" include_in_backups="True" uses_default_kernel="True" qrexec_timeout="60" internal="False" conf_file="test-standalonevm.conf" label="blue" template_qid="none" kernelopts="" memory="400" default_user="user" netvm_qid="3" uses_default_netvm="True" volatile_img="volatile.img" services="{'meminfo-writer': True}" maxmem="1535" pcidevs="[]" name="test-standalonevm" private_img="private.img" vcpus="2" root_img="root.img" debug="False" dir_path="/var/lib/qubes/appvms/test-standalonevm"/>
  <QubesProxyVm backup_size="104857600" backup_content="True" backup_path="servicevms/test-testproxy" installed_by_rpm="False" kernel="3.7.6-2" uses_default_kernelopts="True" qid="12" include_in_backups="True" uses_default_kernel="True" qrexec_timeout="60" internal="False" conf_file="test-testproxy.conf" label="red" template_qid="1" kernelopts="" memory="200" default_user="user" netvm_qid="3" volatile_img="volatile.img" services="{'meminfo-writer': True}" maxmem="1535" pcidevs="[]" name="test-testproxy" netid="3" private_img="private.img" vcpus="2" root_img="root.img" debug="False" dir_path="/var/lib/qubes/servicevms/test-testproxy"/>
  <QubesProxyVm installed_by_rpm="False" kernel="3.7.6-2" uses_default_kernelopts="True" qid="13" include_in_backups="True" uses_default_kernel="True" qrexec_timeout="60" internal="False" conf_file="testproxy2.conf" label="red" template_qid="9" kernelopts="" memory="200" default_user="user" netvm_qid="2" volatile_img="volatile.img" services="{'meminfo-writer': True}" maxmem="1535" pcidevs="[]" name="testproxy2" netid="4" private_img="private.img" vcpus="2" root_img="root.img" debug="False" dir_path="/var/lib/qubes/servicevms/testproxy2"/>
  <QubesHVm backup_size="104857600" backup_content="True" backup_path="appvms/test-testhvm" installed_by_rpm="False" netvm_qid="none" qid="14" include_in_backups="True" timezone="localtime" qrexec_timeout="60" conf_file="test-testhvm.conf" label="purple" template_qid="none" internal="False" memory="512" uses_default_netvm="True" services="{'meminfo-writer': False}" default_user="user" pcidevs="[]" name="test-testhvm" qrexec_installed="False" private_img="private.img" drive="None" vcpus="2" root_img="root.img" guiagent_installed="False" debug="False" dir_path="/var/lib/qubes/appvms/test-testhvm"/>
  <QubesDisposableVm dispid="50" firewall_conf="firewall.xml" label="red" name="disp50" netvm_qid="2" qid="15" template_qid="1"/>
</QubesVmCollection>
'''

MANGLED_SUBDIRS_R2 = {
    "test-work": "vm5",
    "test-template-clone": "vm9",
    "test-custom-template-appvm": "vm10",
    "test-standalonevm": "vm11",
    "test-testproxy": "vm12",
    "test-testhvm": "vm14",
}

APPTEMPLATE_R2B2 = '''
[Desktop Entry]
Name=%VMNAME%: {name}
GenericName=%VMNAME%: {name}
GenericName[ca]=%VMNAME%: Navegador web
GenericName[cs]=%VMNAME%: Webový prohlížeč
GenericName[es]=%VMNAME%: Navegador web
GenericName[fa]=%VMNAME%: مرورر اینترنتی
GenericName[fi]=%VMNAME%: WWW-selain
GenericName[fr]=%VMNAME%: Navigateur Web
GenericName[hu]=%VMNAME%: Webböngésző
GenericName[it]=%VMNAME%: Browser Web
GenericName[ja]=%VMNAME%: ウェブ・ブラウザ
GenericName[ko]=%VMNAME%: 웹 브라우저
GenericName[nb]=%VMNAME%: Nettleser
GenericName[nl]=%VMNAME%: Webbrowser
GenericName[nn]=%VMNAME%: Nettlesar
GenericName[no]=%VMNAME%: Nettleser
GenericName[pl]=%VMNAME%: Przeglądarka WWW
GenericName[pt]=%VMNAME%: Navegador Web
GenericName[pt_BR]=%VMNAME%: Navegador Web
GenericName[sk]=%VMNAME%: Internetový prehliadač
GenericName[sv]=%VMNAME%: Webbläsare
Comment={comment}
Comment[ca]=Navegueu per el web
Comment[cs]=Prohlížení stránek World Wide Webu
Comment[de]=Im Internet surfen
Comment[es]=Navegue por la web
Comment[fa]=صفحات شبه جهانی اینترنت را مرور نمایید
Comment[fi]=Selaa Internetin WWW-sivuja
Comment[fr]=Navigue sur Internet
Comment[hu]=A világháló böngészése
Comment[it]=Esplora il web
Comment[ja]=ウェブを閲覧します
Comment[ko]=웹을 돌아 다닙니다
Comment[nb]=Surf på nettet
Comment[nl]=Verken het internet
Comment[nn]=Surf på nettet
Comment[no]=Surf på nettet
Comment[pl]=Przeglądanie stron WWW
Comment[pt]=Navegue na Internet
Comment[pt_BR]=Navegue na Internet
Comment[sk]=Prehliadanie internetu
Comment[sv]=Surfa på webben
Exec=qvm-run -q --tray -a %VMNAME% '{command} %u'
Categories=Network;WebBrowser;
X-Qubes-VmName=%VMNAME%
Icon=%VMDIR%/icon.png
'''

BACKUP_HEADER_R2 = '''version=3
hmac-algorithm=SHA512
crypto-algorithm=aes-256-cbc
encrypted={encrypted}
compressed={compressed}
compression-filter=gzip
'''

class TC_00_BackupCompatibility(
        qubes.tests.integ.backup.BackupTestsMixin, qubes.tests.SystemTestCase):

    def tearDown(self):
        prefixes = ["test-", "disp-test-"]
        if 'disp-no-netvm' not in self.host_app.domains:
            prefixes.append('disp-no-netvm')
        self.remove_test_vms(prefix=prefixes)
        super(TC_00_BackupCompatibility, self).tearDown()

    def create_whitelisted_appmenus(self, filename):
        f = open(filename, "w")
        f.write("gnome-terminal.desktop\n")
        f.write("nautilus.desktop\n")
        f.write("firefox.desktop\n")
        f.write("mozilla-thunderbird.desktop\n")
        f.write("libreoffice-startcenter.desktop\n")
        f.close()

    def create_appmenus(self, dir, template, list):
        for name in list:
            f = open(os.path.join(dir, name + ".desktop"), "w")
            f.write(template.format(name=name, comment=name, command=name))
            f.close()

    def create_private_img(self, filename):
        self.create_sparse(filename, 2*2**30)
        subprocess.check_call(["/usr/sbin/mkfs.ext4", "-q", "-F", filename])

    def create_volatile_img(self, filename):
        self.create_sparse(filename, int(11.5*2**30))
        # here used to be sfdisk call with "0,1024,S\n,10240,L\n" input,
        # but since sfdisk folks like to change command arguments in
        # incompatible way, have an partition table verbatim here
        ptable = (
            '\x00\x00\x00\x00\x00\x00\x00\x00\xab\x39\xd5\xd4\x00\x00\x20\x00'
            '\x00\x21\xaa\x82\x82\x28\x08\x00\x00\x00\x00\x00\x00\x20\xaa\x00'
            '\x82\x29\x15\x83\x9c\x79\x08\x00\x00\x20\x00\x00\x01\x40\x00\x00'
            '\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'
            '\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xaa\x55'
        )
        with open(filename, 'r+') as f:
            f.seek(0x1b0)
            f.write(ptable)

        # TODO: mkswap

    def fullpath(self, name):
        return os.path.join(self.backupdir, name)

    def create_v1_files(self, r2b2=False):
        appmenus_list = [
            "firefox", "gnome-terminal", "evince", "evolution",
            "mozilla-thunderbird", "libreoffice-startcenter", "nautilus",
            "gedit", "gpk-update-viewer", "gpk-application"
        ]

        os.mkdir(self.fullpath("appvms"))
        os.mkdir(self.fullpath("servicevms"))
        os.mkdir(self.fullpath("vm-templates"))

        # normal AppVM
        os.mkdir(self.fullpath("appvms/test-work"))
        self.create_whitelisted_appmenus(self.fullpath(
            "appvms/test-work/whitelisted-appmenus.list"))
        self.create_private_img(self.fullpath("appvms/test-work/private.img"))

        # StandaloneVM
        os.mkdir(self.fullpath("appvms/test-standalonevm"))
        self.create_whitelisted_appmenus(self.fullpath(
            "appvms/test-standalonevm/whitelisted-appmenus.list"))
        self.create_private_img(self.fullpath(
            "appvms/test-standalonevm/private.img"))
        self.create_sparse(
            self.fullpath("appvms/test-standalonevm/root.img"), 10*2**30)
        self.fill_image(self.fullpath("appvms/test-standalonevm/root.img"),
                        100*1024*1024, True)
        os.mkdir(self.fullpath("appvms/test-standalonevm/apps.templates"))
        self.create_appmenus(self.fullpath("appvms/test-standalonevm/apps"
                                           ".templates"),
                             APPTEMPLATE_R2B2,
                             appmenus_list)
        os.mkdir(self.fullpath("appvms/test-standalonevm/kernels"))
        for k_file in ["initramfs", "vmlinuz", "modules.img"]:
            self.fill_image(self.fullpath("appvms/test-standalonevm/kernels/"
            + k_file), 10*1024*1024)

        # VM based on custom template
        subprocess.check_call(
            ["/bin/cp", "-a", self.fullpath("appvms/test-work"),
                        self.fullpath("appvms/test-custom-template-appvm")])

        # HVM
        if r2b2:
            subprocess.check_call(
                ["/bin/cp", "-a", self.fullpath("appvms/test-standalonevm"),
                            self.fullpath("appvms/test-testhvm")])

        # ProxyVM
        os.mkdir(self.fullpath("servicevms/test-testproxy"))
        self.create_whitelisted_appmenus(self.fullpath(
            "servicevms/test-testproxy/whitelisted-appmenus.list"))
        self.create_private_img(
            self.fullpath("servicevms/test-testproxy/private.img"))

        # Custom template
        os.mkdir(self.fullpath("vm-templates/test-template-clone"))
        self.create_private_img(
            self.fullpath("vm-templates/test-template-clone/private.img"))
        self.create_sparse(self.fullpath(
            "vm-templates/test-template-clone/root-cow.img"), 10*2**30)
        self.create_sparse(self.fullpath(
            "vm-templates/test-template-clone/root.img"), 10*2**30)
        self.fill_image(self.fullpath(
            "vm-templates/test-template-clone/root.img"), 100*2**20, True)
        self.create_volatile_img(self.fullpath(
            "vm-templates/test-template-clone/volatile.img"))
        subprocess.check_call([
            "/bin/tar", "cS",
            "-f", self.fullpath(
                "vm-templates/test-template-clone/clean-volatile.img.tar"),
            "-C", self.fullpath("vm-templates/test-template-clone"),
            "volatile.img"])
        self.create_whitelisted_appmenus(self.fullpath(
            "vm-templates/test-template-clone/whitelisted-appmenus.list"))
        self.create_whitelisted_appmenus(self.fullpath(
            "vm-templates/test-template-clone/vm-whitelisted-appmenus.list"))
        if r2b2:
            self.create_whitelisted_appmenus(self.fullpath(
                "vm-templates/test-template-clone/netvm-whitelisted-appmenus"
                ".list"))
        os.mkdir(
            self.fullpath("vm-templates/test-template-clone/apps.templates"))
        self.create_appmenus(
            self.fullpath("vm-templates/test-template-clone/apps.templates"),
            APPTEMPLATE_R2B2,
            appmenus_list)
        os.mkdir(self.fullpath("vm-templates/test-template-clone/apps"))
        self.create_appmenus(
            self.fullpath("vm-templates/test-template-clone/apps"),
            APPTEMPLATE_R2B2.replace("%VMNAME%", "test-template-clone")
            .replace("%VMDIR%", self.fullpath(
                "vm-templates/test-template-clone")),
            appmenus_list)

    def calculate_hmac(self, f_name, algorithm="sha512", password="qubes"):
        subprocess.check_call(["openssl", "dgst", "-"+algorithm, "-hmac",
                               password],
                              stdin=open(self.fullpath(f_name), "r"),
                              stdout=open(self.fullpath(f_name+".hmac"), "w"))

    def append_backup_stream(self, f_name, stream, basedir=None):
        if not basedir:
            basedir = self.backupdir
        subprocess.check_call(["tar", "-cO", "--posix", "-C", basedir,
                               f_name],
                              stdout=stream)

    def handle_v3_file(self, f_name, subdir, stream, compressed=True,
                       encrypted=True):
        # create inner archive
        tar_cmdline = ["tar", "-Pc", '--sparse',
               '-C', self.fullpath(os.path.dirname(f_name)),
               '--xform', 's:^%s:%s\\0:' % (
                   os.path.basename(f_name),
                   subdir),
               os.path.basename(f_name)
               ]
        if compressed:
            tar_cmdline.insert(-1, "--use-compress-program=%s" % "gzip")
        tar = subprocess.Popen(tar_cmdline, stdout=subprocess.PIPE)
        if encrypted:
            encryptor = subprocess.Popen(
                ["openssl", "enc", "-e", "-aes-256-cbc",
                 "-md", "MD5", "-pass", "pass:qubes"],
                stdin=tar.stdout,
                stdout=subprocess.PIPE)
            data = encryptor.stdout
        else:
            data = tar.stdout

        stage1_dir = self.fullpath(os.path.join("stage1", subdir))
        if not os.path.exists(stage1_dir):
            os.makedirs(stage1_dir)
        subprocess.check_call(["split", "--numeric-suffixes",
                               "--suffix-length=3",
                               "--bytes="+str(100*1024*1024), "-",
                               os.path.join(stage1_dir,
                                            os.path.basename(f_name+"."))],
                              stdin=data)

        for part in sorted(os.listdir(stage1_dir)):
            if not re.match(
                    r"^{}.[0-9][0-9][0-9]$".format(os.path.basename(f_name)),
                    part):
                continue
            part_with_dir = os.path.join(subdir, part)
            self.calculate_hmac(os.path.join("stage1", part_with_dir))
            self.append_backup_stream(part_with_dir, stream,
                                      basedir=self.fullpath("stage1"))
            self.append_backup_stream(part_with_dir+".hmac", stream,
                                      basedir=self.fullpath("stage1"))

    def create_v3_backup(self, encrypted=True, compressed=True):
        """
        Create "backup format 3" backup - used in R2 and R3.0

        :param encrypt: Should the backup be encrypted
        :return:
        """
        output = open(self.fullpath("backup.bin"), "w")
        f = open(self.fullpath("backup-header"), "w")
        f.write(BACKUP_HEADER_R2.format(
            encrypted=str(encrypted),
            compressed=str(compressed)
        ))
        f.close()
        self.calculate_hmac("backup-header")
        self.append_backup_stream("backup-header", output)
        self.append_backup_stream("backup-header.hmac", output)
        f = open(self.fullpath("qubes.xml"), "w")
        if encrypted:
            qubesxml = QUBESXML_R2
            for vmname, subdir in MANGLED_SUBDIRS_R2.items():
                qubesxml = re.sub(r"[a-z-]*/{}".format(vmname),
                                  subdir, qubesxml)
            f.write(qubesxml)
        else:
            f.write(QUBESXML_R2)
        f.close()

        self.handle_v3_file("qubes.xml", "", output, encrypted=encrypted,
                            compressed=compressed)

        self.create_v1_files(r2b2=True)
        for vm_type in ["appvms", "servicevms"]:
            for vm_name in os.listdir(self.fullpath(vm_type)):
                vm_dir = os.path.join(vm_type, vm_name)
                for f_name in os.listdir(self.fullpath(vm_dir)):
                    if encrypted:
                        subdir = MANGLED_SUBDIRS_R2[vm_name]
                    else:
                        subdir = vm_dir
                    self.handle_v3_file(
                        os.path.join(vm_dir, f_name),
                        subdir+'/', output, encrypted=encrypted)

        for vm_name in os.listdir(self.fullpath("vm-templates")):
            vm_dir = os.path.join("vm-templates", vm_name)
            if encrypted:
                subdir = MANGLED_SUBDIRS_R2[vm_name]
            else:
                subdir = vm_dir
            self.handle_v3_file(
                os.path.join(vm_dir, "."),
                subdir+'/', output, encrypted=encrypted)

        output.close()

    def assertRestored(self, name, **kwargs):
        # ignore automatically added features
        ignore_features = ['servicevm']

        with self.assertNotRaises((KeyError, qubes.exc.QubesException)):
            vm = self.app.domains[name]
            asyncio.get_event_loop().run_until_complete(vm.storage.verify())
            for prop, value in kwargs.items():
                if prop == 'klass':
                    self.assertIsInstance(vm, value)
                elif prop == 'features':
                    self.assertEqual(
                        dict((k, v) for k, v in vm.features.items()
                             if k not in ignore_features),
                        value,
                        'VM {} - features mismatch'.format(vm.name))
                elif value is qubes.property.DEFAULT:
                    self.assertTrue(vm.property_is_default(prop),
                        'VM {} - property {} not default'.format(vm.name, prop))
                else:
                    actual_value = getattr(vm, prop)
                    if isinstance(actual_value, qubes.vm.BaseVM):
                        self.assertEqual(value, actual_value.name,
                            'VM {} - property {}'.format(vm.name, prop))
                    elif isinstance(actual_value, qubes.Label):
                        self.assertEqual(value, actual_value.name,
                            'VM {} - property {}'.format(vm.name, prop))
                    else:
                        self.assertEqual(value, actual_value,
                            'VM {} - property {}'.format(vm.name, prop))

    def test_210_r2(self):
        self.create_v3_backup(False)

        self.restore_backup(self.fullpath("backup.bin"), options={
            'use-default-template': True,
            'use-default-netvm': True,
        })
        common_props = {
            'installed_by_rpm': False,
            'kernel': qubes.property.DEFAULT,
            'kernelopts': qubes.property.DEFAULT,
            'qrexec_timeout': qubes.property.DEFAULT,
            'netvm': qubes.property.DEFAULT,
            'default_user': qubes.property.DEFAULT,
            'include_in_backups': True,
            'debug': False,
            'maxmem': min(int(self.app.host.memory_total / 1024 / 2), 4000),
            'memory': 400,
            'features': {
                'menu-items': 'gnome-terminal.desktop nautilus.desktop '
                              'firefox.desktop mozilla-thunderbird.desktop '
                              'libreoffice-startcenter.desktop',
            },
        }
        template_standalone_props = common_props.copy()
        template_standalone_props['features'] = {
            'qrexec': '1',
            'gui': '1',
            'menu-items': common_props['features']['menu-items'],
        }
        self.assertRestored("test-template-clone",
            klass=qubes.vm.templatevm.TemplateVM,
            label='green',
            provides_network=False,
            **template_standalone_props)
        testproxy_props = common_props.copy()
        testproxy_props.update(
            label='red',
            provides_network=True,
            memory=200,
            template=self.app.default_template.name,
        )
        self.assertRestored("test-testproxy",
            klass=qubes.vm.appvm.AppVM,
            **testproxy_props)
        self.assertRestored("test-work",
            klass=qubes.vm.appvm.AppVM,
            template=self.app.default_template.name,
            label='green',
            **common_props)
        self.assertRestored("test-standalonevm",
            klass=qubes.vm.standalonevm.StandaloneVM,
            label='blue',
            **template_standalone_props)
        self.assertRestored("test-custom-template-appvm",
            klass=qubes.vm.appvm.AppVM,
            template='test-template-clone',
            label='yellow',
            **common_props)

    def test_220_r2_encrypted(self):
        self.create_v3_backup(True)

        self.restore_backup(self.fullpath("backup.bin"), options={
            'use-default-template': True,
            'use-default-netvm': True,
        })
        common_props = {
            'installed_by_rpm': False,
            'kernel': qubes.property.DEFAULT,
            'kernelopts': qubes.property.DEFAULT,
            'qrexec_timeout': qubes.property.DEFAULT,
            'netvm': qubes.property.DEFAULT,
            'default_user': qubes.property.DEFAULT,
            'include_in_backups': True,
            'debug': False,
            'maxmem': min(int(self.app.host.memory_total / 1024 / 2), 4000),
            'memory': 400,
            'features': {
                'menu-items': 'gnome-terminal.desktop nautilus.desktop '
                              'firefox.desktop mozilla-thunderbird.desktop '
                              'libreoffice-startcenter.desktop',
            },
        }
        template_standalone_props = common_props.copy()
        template_standalone_props['features'] = {
            'qrexec': '1',
            'gui': '1',
            'menu-items': common_props['features']['menu-items'],
        }
        self.assertRestored("test-template-clone",
            klass=qubes.vm.templatevm.TemplateVM,
            label='green',
            provides_network=False,
            **template_standalone_props)
        testproxy_props = common_props.copy()
        testproxy_props.update(
            label='red',
            provides_network=True,
            memory=200,
            template=self.app.default_template.name,
        )
        self.assertRestored("test-testproxy",
            klass=qubes.vm.appvm.AppVM,
            **testproxy_props)
        self.assertRestored("test-work",
            klass=qubes.vm.appvm.AppVM,
            template=self.app.default_template.name,
            label='green',
            **common_props)
        self.assertRestored("test-standalonevm",
            klass=qubes.vm.standalonevm.StandaloneVM,
            label='blue',
            **template_standalone_props)
        self.assertRestored("test-custom-template-appvm",
            klass=qubes.vm.appvm.AppVM,
            template='test-template-clone',
            label='yellow',
            **common_props)


class TC_01_BackupCompatibilityIntoLVM(TC_00_BackupCompatibility):
    def setUp(self):
        super(TC_01_BackupCompatibilityIntoLVM, self).setUp()
        self.init_lvm_pool()

    def restore_backup(self, source=None, appvm=None, options=None,
            **kwargs):
        if options is None:
            options = {}
        options['override_pool'] = self.pool.name
        super(TC_01_BackupCompatibilityIntoLVM, self).restore_backup(source,
            appvm, options, **kwargs)
