#!/usr/bin/python
# -*- coding: utf-8 -*-
#
# The Qubes OS Project, http://www.qubes-os.org
#
# Copyright (C) 2014 Marek Marczykowski-Górecki <marmarek@invisiblethingslab.com>
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
from multiprocessing import Queue

import os
import shutil
import subprocess

import unittest
import sys
import re
from qubes.qubes import QubesVmCollection, QubesException
from qubes import backup

import qubes.tests

QUBESXML_R32 = '''
<QubesVmCollection clockvm="5" default_fw_netvm="5" default_kernel="4.4.14-11" default_netvm="6" default_template="1" updatevm="6">
  <QubesAdminVm autostart="False" backup_content="True" backup_path="dom0-home/user" backup_size="9770090496" conf_file="dom0.conf" debug="False" default_user="user" dir_path="/var/lib/qubes/servicevms/dom0" dispvm_netvm="none" firewall_conf="firewall.xml" include_in_backups="True" installed_by_rpm="False" internal="False" label="black" maxmem="0" memory="300" name="dom0" netid="0" pci_e820_host="True" pci_strictreset="True" pcidevs="[]" pool_name="default" qid="0" qrexec_timeout="60" services="{'meminfo-writer': True}" template_qid="none" uses_default_dispvm_netvm="True" vcpus="0"/>
  <QubesTemplateVm autostart="False" backup_content="False" backup_path="" backup_size="0" conf_file="fedora-23.conf" debug="False" default_user="user" dir_path="/var/lib/qubes/vm-templates/fedora-23" dispvm_netvm="6" firewall_conf="firewall.xml" include_in_backups="False" installed_by_rpm="True" internal="False" kernel="4.4.14-11" kernelopts="nopat" label="black" maxmem="2006" memory="400" name="fedora-23" netvm_qid="6" pci_e820_host="True" pci_strictreset="True" pcidevs="[]" pool_name="default" qid="1" qrexec_timeout="60" services="{'meminfo-writer': True}" template_qid="none" uses_default_dispvm_netvm="True" uses_default_kernel="True" uses_default_kernelopts="True" uses_default_netvm="True" uuid="778f8b4a-6847-476b-8892-14d5b61b69da" vcpus="2"/>
  <QubesTemplateVm autostart="False" backup_content="False" backup_path="" backup_size="0" conf_file="debian-8.conf" debug="False" default_user="user" dir_path="/var/lib/qubes/vm-templates/debian-8" dispvm_netvm="6" firewall_conf="firewall.xml" include_in_backups="False" installed_by_rpm="True" internal="False" kernel="4.4.14-11" kernelopts="nopat" label="black" maxmem="2006" memory="400" name="debian-8" netvm_qid="6" pci_e820_host="True" pci_strictreset="True" pcidevs="[]" pool_name="default" qid="2" qrexec_timeout="60" services="{'meminfo-writer': True}" template_qid="none" uses_default_dispvm_netvm="True" uses_default_kernel="True" uses_default_kernelopts="True" uses_default_netvm="True" vcpus="2"/>
  <QubesTemplateVm autostart="False" backup_content="False" backup_path="" backup_size="0" conf_file="whonix-ws.conf" debug="False" default_user="user" dir_path="/var/lib/qubes/vm-templates/whonix-ws" dispvm_netvm="8" firewall_conf="firewall.xml" include_in_backups="False" installed_by_rpm="True" internal="False" kernel="4.4.14-11" kernelopts="nopat" label="black" maxmem="2006" memory="400" name="whonix-ws" netvm_qid="8" pci_e820_host="True" pci_strictreset="True" pcidevs="[]" pool_name="default" qid="3" qrexec_timeout="60" services="{'meminfo-writer': True}" template_qid="none" uses_default_dispvm_netvm="True" uses_default_kernel="True" uses_default_kernelopts="True" uses_default_netvm="False" uuid="020b6cc9-4e2e-436a-a67f-7dbb8d6c1ec7" vcpus="2"/>
  <QubesTemplateVm autostart="False" backup_content="False" backup_path="" backup_size="0" conf_file="whonix-gw.conf" debug="False" default_user="user" dir_path="/var/lib/qubes/vm-templates/whonix-gw" dispvm_netvm="8" firewall_conf="firewall.xml" include_in_backups="False" installed_by_rpm="True" internal="False" kernel="4.4.14-11" kernelopts="nopat" label="black" maxmem="2006" memory="400" name="whonix-gw" netvm_qid="8" pci_e820_host="True" pci_strictreset="True" pcidevs="[]" pool_name="default" qid="4" qrexec_timeout="60" services="{'meminfo-writer': True}" template_qid="none" uses_default_dispvm_netvm="True" uses_default_kernel="True" uses_default_kernelopts="True" uses_default_netvm="False" uuid="56c39ac4-7090-4fba-83b7-291bb43fe3ab" vcpus="2"/>
  <QubesNetVm autostart="True" backup_content="False" backup_path="" backup_size="0" conf_file="sys-net.conf" debug="False" default_user="user" dir_path="/var/lib/qubes/servicevms/sys-net" dispvm_netvm="none" firewall_conf="firewall.xml" include_in_backups="True" installed_by_rpm="False" internal="False" kernel="4.4.14-11" kernelopts="nopat iommu=soft swiotlb=8192" label="red" maxmem="2006" memory="300" name="sys-net" netid="1" pci_e820_host="True" pci_strictreset="True" pcidevs="['02:00.0']" pool_name="default" qid="5" qrexec_timeout="60" services="{'ntpd': False, 'meminfo-writer': False}" template_qid="1" uses_default_dispvm_netvm="True" uses_default_kernel="True" uses_default_kernelopts="True" uuid="d629b4c8-39fc-4e76-ad02-ec42bc2b4166" vcpus="2"/>
  <QubesProxyVm autostart="True" backup_content="False" backup_path="" backup_size="0" conf_file="sys-firewall.conf" debug="False" default_user="user" dir_path="/var/lib/qubes/servicevms/sys-firewall" dispvm_netvm="5" firewall_conf="firewall.xml" include_in_backups="True" installed_by_rpm="False" internal="False" kernel="4.4.14-11" kernelopts="nopat" label="green" maxmem="2006" memory="500" name="sys-firewall" netid="2" netvm_qid="5" pci_e820_host="True" pci_strictreset="True" pcidevs="[]" pool_name="default" qid="6" qrexec_timeout="60" services="{'meminfo-writer': True}" template_qid="1" uses_default_dispvm_netvm="True" uses_default_kernel="True" uses_default_kernelopts="True" uuid="8f3d442f-b37b-449e-8209-1dd413d942c2" vcpus="2"/>
  <QubesAppVm autostart="False" backup_content="False" backup_path="" backup_size="0" conf_file="untrusted.conf" debug="False" default_user="user" dir_path="/var/lib/qubes/appvms/untrusted" dispvm_netvm="6" firewall_conf="firewall.xml" include_in_backups="True" installed_by_rpm="False" internal="False" kernel="4.4.14-11" kernelopts="nopat" label="red" maxmem="2006" memory="400" name="untrusted" netvm_qid="6" pci_e820_host="True" pci_strictreset="True" pcidevs="[]" pool_name="default" qid="7" qrexec_timeout="60" services="{'meminfo-writer': True}" template_qid="1" uses_default_dispvm_netvm="True" uses_default_kernel="True" uses_default_kernelopts="True" uses_default_netvm="True" uuid="43fb3f4d-f139-4ab4-b262-a3573ae9b0c8" vcpus="2"/>
  <QubesProxyVm autostart="True" backup_content="False" backup_path="" backup_size="0" conf_file="sys-whonix.conf" debug="False" default_user="user" dir_path="/var/lib/qubes/servicevms/sys-whonix" dispvm_netvm="6" firewall_conf="firewall.xml" include_in_backups="True" installed_by_rpm="False" internal="False" kernel="4.4.14-11" kernelopts="nopat" label="black" maxmem="2006" memory="500" name="sys-whonix" netid="3" netvm_qid="6" pci_e820_host="True" pci_strictreset="True" pcidevs="[]" pool_name="default" qid="8" qrexec_timeout="60" services="{'meminfo-writer': True}" template_qid="4" uses_default_dispvm_netvm="True" uses_default_kernel="True" uses_default_kernelopts="True" uuid="f7b7b41f-840c-4761-a988-3993d3ea73db" vcpus="2"/>
  <QubesAppVm autostart="False" backup_content="False" backup_path="" backup_size="0" conf_file="anon-whonix.conf" debug="False" default_user="user" dir_path="/var/lib/qubes/appvms/anon-whonix" dispvm_netvm="8" firewall_conf="firewall.xml" include_in_backups="True" installed_by_rpm="False" internal="False" kernel="4.4.14-11" kernelopts="nopat" label="red" maxmem="2006" memory="400" name="anon-whonix" netvm_qid="8" pci_e820_host="True" pci_strictreset="True" pcidevs="[]" pool_name="default" qid="9" qrexec_timeout="60" services="{'meminfo-writer': True}" template_qid="3" uses_default_dispvm_netvm="True" uses_default_kernel="True" uses_default_kernelopts="True" uses_default_netvm="False" uuid="d095f34f-26dc-48c1-89f7-c8ffba852452" vcpus="2"/>
  <QubesAppVm autostart="False" backup_content="False" backup_path="" backup_size="0" conf_file="vault.conf" debug="False" default_user="user" dir_path="/var/lib/qubes/appvms/vault" dispvm_netvm="none" firewall_conf="firewall.xml" include_in_backups="True" installed_by_rpm="False" internal="False" kernel="4.4.14-11" kernelopts="nopat" label="black" maxmem="2006" memory="400" name="vault" netvm_qid="none" pci_e820_host="True" pci_strictreset="True" pcidevs="[]" pool_name="default" qid="10" qrexec_timeout="60" services="{'meminfo-writer': True}" template_qid="1" uses_default_dispvm_netvm="True" uses_default_kernel="True" uses_default_kernelopts="True" uses_default_netvm="False" uuid="4627217c-f6c9-4365-a264-3d118fab91a1" vcpus="2"/>
  <QubesAppVm autostart="False" backup_content="False" backup_path="" backup_size="0" conf_file="personal.conf" debug="False" default_user="user" dir_path="/var/lib/qubes/appvms/personal" dispvm_netvm="6" firewall_conf="firewall.xml" include_in_backups="True" installed_by_rpm="False" internal="False" kernel="4.4.14-11" kernelopts="nopat" label="yellow" maxmem="2006" memory="400" name="personal" netvm_qid="6" pci_e820_host="True" pci_strictreset="True" pcidevs="[]" pool_name="default" qid="11" qrexec_timeout="60" services="{'meminfo-writer': True}" template_qid="1" uses_default_dispvm_netvm="True" uses_default_kernel="True" uses_default_kernelopts="True" uses_default_netvm="True" uuid="b076f81f-32dc-448c-a755-07cdaf9af009" vcpus="2"/>
  <QubesAppVm autostart="False" backup_content="False" backup_path="" backup_size="0" conf_file="work.conf" debug="False" default_user="user" dir_path="/var/lib/qubes/appvms/work" dispvm_netvm="6" firewall_conf="firewall.xml" include_in_backups="True" installed_by_rpm="False" internal="False" kernel="4.4.14-11" kernelopts="nopat" label="blue" maxmem="2006" memory="400" name="work" netvm_qid="6" pci_e820_host="True" pci_strictreset="True" pcidevs="[]" pool_name="default" qid="12" qrexec_timeout="60" services="{'meminfo-writer': True}" template_qid="1" uses_default_dispvm_netvm="True" uses_default_kernel="True" uses_default_kernelopts="True" uses_default_netvm="True" uuid="71cf8f3d-51bc-45ef-808c-b7d4e3320e37" vcpus="2"/>
  <QubesAppVm autostart="False" backup_content="False" backup_path="" backup_size="0" conf_file="fedora-23-dvm.conf" debug="False" default_user="user" dir_path="/var/lib/qubes/appvms/fedora-23-dvm" dispvm_netvm="6" firewall_conf="firewall.xml" include_in_backups="True" installed_by_rpm="False" internal="True" kernel="4.4.14-11" kernelopts="nopat" label="gray" maxmem="2006" memory="400" name="fedora-23-dvm" netvm_qid="6" pci_e820_host="True" pci_strictreset="True" pcidevs="[]" pool_name="default" qid="13" qrexec_timeout="60" services="{'meminfo-writer': True}" template_qid="1" uses_default_dispvm_netvm="True" uses_default_kernel="True" uses_default_kernelopts="True" uses_default_netvm="True" uuid="54b498c6-1112-4c5e-861d-bfffa86db4ec" vcpus="1"/>
  <QubesHVm autostart="False" backup_content="False" backup_path="" backup_size="0" conf_file="stubdomtest.conf" debug="False" default_user="user" dir_path="/var/lib/qubes/appvms/stubdomtest" dispvm_netvm="6" drive="None" firewall_conf="firewall.xml" guiagent_installed="False" include_in_backups="True" installed_by_rpm="False" internal="False" label="red" memory="1536" name="stubdomtest" netvm_qid="6" pci_e820_host="True" pci_strictreset="False" pcidevs="[]" pool_name="default" qid="14" qrexec_installed="False" qrexec_timeout="60" seamless_gui_mode="False" services="{'meminfo-writer': False}" template_qid="none" timezone="localtime" uses_default_dispvm_netvm="True" uses_default_netvm="True" uuid="490f5562-660d-401d-bb7f-33c6d7bf2128" vcpus="1"/>
  <QubesAppVm autostart="False" backup_content="True" backup_path="appvms/test-work" backup_size="68145152" conf_file="test-work.conf" debug="False" default_user="user" dir_path="/var/lib/qubes/appvms/test-work" dispvm_netvm="19" firewall_conf="firewall.xml" include_in_backups="True" installed_by_rpm="False" internal="False" kernel="4.4.14-11" kernelopts="nopat" label="green" maxmem="2006" memory="400" name="test-work" netvm_qid="23" pci_e820_host="True" pci_strictreset="True" pcidevs="[]" pool_name="default" qid="15" qrexec_timeout="60" services="{'meminfo-writer': True}" template_qid="1" uses_default_dispvm_netvm="False" uses_default_kernel="True" uses_default_kernelopts="True" uses_default_netvm="False" uuid="9717539c-a3ce-4c3e-b95a-1238d195f78f" vcpus="2"/>
  <QubesAppVm autostart="False" backup_content="True" backup_path="appvms/test-standalonevm" backup_size="4446990336" conf_file="test-standalonevm.conf" debug="False" default_user="user" dir_path="/var/lib/qubes/appvms/test-standalonevm" dispvm_netvm="6" firewall_conf="firewall.xml" include_in_backups="True" installed_by_rpm="False" internal="False" kernel="4.4.14-11" kernelopts="nopat" label="blue" maxmem="2006" memory="400" name="test-standalonevm" netvm_qid="6" pci_e820_host="True" pci_strictreset="True" pcidevs="[]" pool_name="default" qid="16" qrexec_timeout="60" services="{'meminfo-writer': True}" template_qid="none" uses_default_dispvm_netvm="True" uses_default_kernel="True" uses_default_kernelopts="True" uses_default_netvm="True" uuid="b8a56982-200a-4349-9cfa-3407a919c861" vcpus="2"/>
  <QubesTemplateVm autostart="False" backup_content="True" backup_path="vm-templates/test-template-clone" backup_size="4016513024" conf_file="test-template-clone.conf" debug="False" default_user="user" dir_path="/var/lib/qubes/vm-templates/test-template-clone" dispvm_netvm="6" firewall_conf="firewall.xml" include_in_backups="False" installed_by_rpm="False" internal="False" kernel="4.4.14-11" kernelopts="nopat" label="black" maxmem="2006" memory="400" name="test-template-clone" netvm_qid="6" pci_e820_host="True" pci_strictreset="True" pcidevs="[]" pool_name="default" qid="17" qrexec_timeout="60" services="{'meminfo-writer': True}" template_qid="none" uses_default_dispvm_netvm="True" uses_default_kernel="True" uses_default_kernelopts="True" uses_default_netvm="True" uuid="068a34f5-23eb-462c-b8c3-5b4e3a2d2bfe" vcpus="2"/>
  <QubesAppVm autostart="False" backup_content="True" backup_path="appvms/test-custom-template-appvm" backup_size="68145152" conf_file="test-custom-template-appvm.conf" debug="False" default_user="user" dir_path="/var/lib/qubes/appvms/test-custom-template-appvm" dispvm_netvm="6" firewall_conf="firewall.xml" include_in_backups="True" installed_by_rpm="False" internal="False" kernel="4.4.14-11" kernelopts="nopat" label="green" maxmem="2006" memory="400" name="test-custom-template-appvm" netvm_qid="6" pci_e820_host="True" pci_strictreset="True" pcidevs="[]" pool_name="default" qid="18" qrexec_timeout="60" services="{'meminfo-writer': True}" template_qid="17" uses_default_dispvm_netvm="True" uses_default_kernel="True" uses_default_kernelopts="True" uses_default_netvm="True" uuid="eea549b7-cc81-4191-a229-4866489f3d8e" vcpus="2"/>
  <QubesProxyVm autostart="False" backup_content="True" backup_path="servicevms/test-testproxy" backup_size="68063232" conf_file="test-testproxy.conf" debug="False" default_user="user" dir_path="/var/lib/qubes/servicevms/test-testproxy" dispvm_netvm="none" firewall_conf="firewall.xml" include_in_backups="True" installed_by_rpm="False" internal="False" kernel="4.4.14-11" kernelopts="nopat" label="yellow" maxmem="2006" memory="300" name="test-testproxy" netid="4" netvm_qid="none" pci_e820_host="True" pci_strictreset="True" pcidevs="[]" pool_name="default" qid="19" qrexec_timeout="60" services="{'meminfo-writer': True}" template_qid="1" uses_default_dispvm_netvm="True" uses_default_kernel="True" uses_default_kernelopts="True" uuid="c9951f79-ae68-45d4-864d-b60381169cd3" vcpus="2"/>
  <QubesHVm autostart="False" backup_content="True" backup_path="appvms/test-testhvm" backup_size="32768" conf_file="test-testhvm.conf" debug="False" default_user="user" dir_path="/var/lib/qubes/appvms/test-testhvm" dispvm_netvm="6" drive="None" firewall_conf="firewall.xml" guiagent_installed="False" include_in_backups="True" installed_by_rpm="False" internal="False" label="orange" memory="512" name="test-testhvm" netvm_qid="6" pci_e820_host="True" pci_strictreset="True" pcidevs="[]" pool_name="default" qid="20" qrexec_installed="False" qrexec_timeout="60" seamless_gui_mode="False" services="{'meminfo-writer': False}" template_qid="none" timezone="localtime" uses_default_dispvm_netvm="True" uses_default_netvm="True" uuid="14055677-44bd-4a11-99e2-595d5e17d2ee" vcpus="2"/>
  <QubesTemplateHVm autostart="False" backup_content="True" backup_path="vm-templates/test-hvmtemplate" backup_size="32768" conf_file="test-hvmtemplate.conf" debug="False" default_user="user" dir_path="/var/lib/qubes/vm-templates/test-hvmtemplate" dispvm_netvm="6" drive="None" firewall_conf="firewall.xml" guiagent_installed="False" include_in_backups="True" installed_by_rpm="False" internal="False" label="green" memory="512" name="test-hvmtemplate" netvm_qid="6" pci_e820_host="True" pci_strictreset="True" pcidevs="[]" pool_name="default" qid="21" qrexec_installed="False" qrexec_timeout="60" seamless_gui_mode="False" services="{'meminfo-writer': False}" template_qid="none" timezone="localtime" uses_default_dispvm_netvm="True" uses_default_netvm="True" uuid="bcba2650-1854-4c84-b1b3-082a48d93366" vcpus="2"/>
  <QubesHVm autostart="False" backup_content="True" backup_path="appvms/test-template-based-hvm" backup_size="24576" conf_file="test-template-based-hvm.conf" debug="False" default_user="user" dir_path="/var/lib/qubes/appvms/test-template-based-hvm" dispvm_netvm="6" drive="None" firewall_conf="firewall.xml" guiagent_installed="False" include_in_backups="True" installed_by_rpm="False" internal="False" label="red" memory="512" name="test-template-based-hvm" netvm_qid="6" pci_e820_host="True" pci_strictreset="True" pcidevs="[]" pool_name="default" qid="22" qrexec_installed="False" qrexec_timeout="60" seamless_gui_mode="False" services="{'meminfo-writer': False}" template_qid="21" timezone="localtime" uses_default_dispvm_netvm="True" uses_default_netvm="True" uuid="39c5f6bf-ab27-4d75-8b3f-d436833cff26" vcpus="2"/>
  <QubesNetVm autostart="False" backup_content="True" backup_path="servicevms/test-net" backup_size="68059136" conf_file="test-net.conf" debug="False" default_user="user" dir_path="/var/lib/qubes/servicevms/test-net" dispvm_netvm="none" firewall_conf="firewall.xml" include_in_backups="True" installed_by_rpm="False" internal="False" kernel="4.4.14-11" kernelopts="nopat" label="red" maxmem="2006" memory="300" name="test-net" netid="5" pci_e820_host="True" pci_strictreset="False" pcidevs="[]" pool_name="default" qid="23" qrexec_timeout="60" services="{'meminfo-writer': True}" template_qid="1" uses_default_dispvm_netvm="True" uses_default_kernel="True" uses_default_kernelopts="True" uuid="30865f52-5574-42c6-b3e1-500dc1d320ac" vcpus="2"/>
</QubesVmCollection>
'''

QUBESXML_R2B2 = '''
<QubesVmCollection updatevm="3" default_kernel="3.7.6-2" default_netvm="3" default_fw_netvm="2" default_template="1" clockvm="2">
  <QubesTemplateVm installed_by_rpm="True" kernel="3.7.6-2" uses_default_kernelopts="True" qid="1" include_in_backups="True" uses_default_kernel="True" qrexec_timeout="60" internal="False" conf_file="fedora-18-x64.conf" label="black" template_qid="none" kernelopts="" memory="400" default_user="user" netvm_qid="3" uses_default_netvm="True" volatile_img="volatile.img" services="{'meminfo-writer': True}" maxmem="1535" pcidevs="[]" name="fedora-18-x64" private_img="private.img" vcpus="2" root_img="root.img" debug="False" dir_path="/var/lib/qubes/vm-templates/fedora-18-x64"/>
  <QubesNetVm installed_by_rpm="False" kernel="3.7.6-2" uses_default_kernelopts="True" qid="2" include_in_backups="True" uses_default_kernel="True" qrexec_timeout="60" internal="False" conf_file="netvm.conf" label="red" template_qid="1" kernelopts="iommu=soft swiotlb=4096" memory="200" default_user="user" volatile_img="volatile.img" services="{'ntpd': False, 'meminfo-writer': False}" maxmem="1535" pcidevs="['02:00.0', '03:00.0']" name="netvm" netid="1" private_img="private.img" vcpus="2" root_img="root.img" debug="False" dir_path="/var/lib/qubes/servicevms/netvm"/>
  <QubesProxyVm installed_by_rpm="False" kernel="3.7.6-2" uses_default_kernelopts="True" qid="3" include_in_backups="True" uses_default_kernel="True" qrexec_timeout="60" internal="False" conf_file="firewallvm.conf" label="green" template_qid="1" kernelopts="" memory="200" default_user="user" netvm_qid="2" volatile_img="volatile.img" services="{'meminfo-writer': True}" maxmem="1535" pcidevs="[]" name="firewallvm" netid="2" private_img="private.img" vcpus="2" root_img="root.img" debug="False" dir_path="/var/lib/qubes/servicevms/firewallvm"/>
  <QubesAppVm installed_by_rpm="False" kernel="3.7.6-2" uses_default_kernelopts="True" qid="4" include_in_backups="True" uses_default_kernel="True" qrexec_timeout="60" internal="True" conf_file="fedora-18-x64-dvm.conf" label="gray" template_qid="1" kernelopts="" memory="400" default_user="user" netvm_qid="3" uses_default_netvm="True" volatile_img="volatile.img" services="{'meminfo-writer': True}" maxmem="1535" pcidevs="[]" name="fedora-18-x64-dvm" private_img="private.img" vcpus="1" root_img="root.img" debug="False" dir_path="/var/lib/qubes/appvms/fedora-18-x64-dvm"/>
  <QubesAppVm installed_by_rpm="False" kernel="3.7.6-2" uses_default_kernelopts="True" qid="5" include_in_backups="True" uses_default_kernel="True" qrexec_timeout="60" internal="False" conf_file="test-work.conf" label="green" template_qid="1" kernelopts="" memory="400" default_user="user" netvm_qid="3" uses_default_netvm="True" volatile_img="volatile.img" services="{'meminfo-writer': True}" maxmem="1535" pcidevs="[]" name="test-work" private_img="private.img" vcpus="2" root_img="root.img" debug="False" dir_path="/var/lib/qubes/appvms/test-work"/>
  <QubesAppVm installed_by_rpm="False" kernel="3.7.6-2" uses_default_kernelopts="True" qid="6" include_in_backups="True" uses_default_kernel="True" qrexec_timeout="60" internal="False" conf_file="banking.conf" label="green" template_qid="1" kernelopts="" memory="400" default_user="user" netvm_qid="3" uses_default_netvm="True" volatile_img="volatile.img" services="{'meminfo-writer': True}" maxmem="1535" pcidevs="[]" name="banking" private_img="private.img" vcpus="2" root_img="root.img" debug="False" dir_path="/var/lib/qubes/appvms/banking"/>
  <QubesAppVm installed_by_rpm="False" kernel="3.7.6-2" uses_default_kernelopts="True" qid="7" include_in_backups="True" uses_default_kernel="True" qrexec_timeout="60" internal="False" conf_file="personal.conf" label="yellow" template_qid="1" kernelopts="" memory="400" default_user="user" netvm_qid="3" uses_default_netvm="True" volatile_img="volatile.img" services="{'meminfo-writer': True}" maxmem="1535" pcidevs="[]" name="personal" private_img="private.img" vcpus="2" root_img="root.img" debug="False" dir_path="/var/lib/qubes/appvms/personal"/>
  <QubesAppVm installed_by_rpm="False" kernel="3.7.6-2" uses_default_kernelopts="True" qid="8" include_in_backups="True" uses_default_kernel="True" qrexec_timeout="60" internal="False" conf_file="untrusted.conf" label="red" template_qid="1" kernelopts="" memory="400" default_user="user" netvm_qid="12" uses_default_netvm="False" volatile_img="volatile.img" services="{'meminfo-writer': True}" maxmem="1535" pcidevs="[]" name="untrusted" private_img="private.img" vcpus="2" root_img="root.img" debug="False" dir_path="/var/lib/qubes/appvms/untrusted"/>
  <QubesTemplateVm installed_by_rpm="False" kernel="3.7.6-2" uses_default_kernelopts="True" qid="9" include_in_backups="True" uses_default_kernel="True" qrexec_timeout="60" internal="False" conf_file="test-template-clone.conf" label="green" template_qid="none" kernelopts="" memory="400" default_user="user" netvm_qid="3" uses_default_netvm="True" volatile_img="volatile.img" services="{'meminfo-writer': True}" maxmem="1535" pcidevs="[]" name="test-template-clone" private_img="private.img" vcpus="2" root_img="root.img" debug="False" dir_path="/var/lib/qubes/vm-templates/test-template-clone"/>
  <QubesAppVm installed_by_rpm="False" kernel="3.7.6-2" uses_default_kernelopts="True" qid="10" include_in_backups="True" uses_default_kernel="True" qrexec_timeout="60" internal="False" conf_file="test-custom-template-appvm.conf" label="yellow" template_qid="9" kernelopts="" memory="400" default_user="user" netvm_qid="3" uses_default_netvm="True" volatile_img="volatile.img" services="{'meminfo-writer': True}" maxmem="1535" pcidevs="[]" name="test-custom-template-appvm" private_img="private.img" vcpus="2" root_img="root.img" debug="False" dir_path="/var/lib/qubes/appvms/test-custom-template-appvm"/>
  <QubesAppVm installed_by_rpm="False" kernel="3.7.6-2" uses_default_kernelopts="True" qid="11" include_in_backups="True" uses_default_kernel="True" qrexec_timeout="60" internal="False" conf_file="test-standalonevm.conf" label="blue" template_qid="none" kernelopts="" memory="400" default_user="user" netvm_qid="3" uses_default_netvm="True" volatile_img="volatile.img" services="{'meminfo-writer': True}" maxmem="1535" pcidevs="[]" name="test-standalonevm" private_img="private.img" vcpus="2" root_img="root.img" debug="False" dir_path="/var/lib/qubes/appvms/test-standalonevm"/>
  <QubesProxyVm installed_by_rpm="False" kernel="3.7.6-2" uses_default_kernelopts="True" qid="12" include_in_backups="True" uses_default_kernel="True" qrexec_timeout="60" internal="False" conf_file="test-testproxy.conf" label="red" template_qid="1" kernelopts="" memory="200" default_user="user" netvm_qid="3" volatile_img="volatile.img" services="{'meminfo-writer': True}" maxmem="1535" pcidevs="[]" name="test-testproxy" netid="3" private_img="private.img" vcpus="2" root_img="root.img" debug="False" dir_path="/var/lib/qubes/servicevms/test-testproxy"/>
  <QubesProxyVm installed_by_rpm="False" kernel="3.7.6-2" uses_default_kernelopts="True" qid="13" include_in_backups="True" uses_default_kernel="True" qrexec_timeout="60" internal="False" conf_file="testproxy2.conf" label="red" template_qid="9" kernelopts="" memory="200" default_user="user" netvm_qid="2" volatile_img="volatile.img" services="{'meminfo-writer': True}" maxmem="1535" pcidevs="[]" name="testproxy2" netid="4" private_img="private.img" vcpus="2" root_img="root.img" debug="False" dir_path="/var/lib/qubes/servicevms/testproxy2"/>
  <QubesHVm installed_by_rpm="False" netvm_qid="none" qid="14" include_in_backups="True" timezone="localtime" qrexec_timeout="60" conf_file="test-testhvm.conf" label="purple" template_qid="none" internal="False" memory="512" uses_default_netvm="True" services="{'meminfo-writer': False}" default_user="user" pcidevs="[]" name="test-testhvm" qrexec_installed="False" private_img="private.img" drive="None" vcpus="2" root_img="root.img" guiagent_installed="False" debug="False" dir_path="/var/lib/qubes/appvms/test-testhvm"/>
  <QubesDisposableVm dispid="50" firewall_conf="firewall.xml" label="red" name="disp50" netvm_qid="2" qid="15" template_qid="1"/>
</QubesVmCollection>
'''

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

MANGLED_SUBDIRS_R32 = {
    "test-work": "vm15",
    "test-template-clone": "vm17",
    "test-custom-template-appvm": "vm18",
    "test-standalonevm": "vm16",
    "test-testproxy": "vm19",
    "test-testhvm": "vm20",
    "test-hvmtemplate": "vm21",
    "test-template-based-hvm": "vm22",
    "test-net": "vm23",
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

APPTEMPLATE_HVM_START_R32 = '''[Desktop Entry]
Version=1.0
Type=Application
Exec=qvm-start --quiet --tray %VMNAME%
Icon=%XDGICON%
Terminal=false
Name=%VMNAME%: Start
GenericName=%VMNAME%: Start
StartupNotify=false
Categories=System;X-Qubes-VM;
'''

APPTEMPLATE_APPMENU_SELECT_R32 = '''[Desktop Entry]
Version=1.0
Type=Application
Exec=qubes-vm-settings %VMNAME% applications
Icon=qubes-appmenu-select
Terminal=false
Name=%VMNAME%: Add more shortcuts...
GenericName=%VMNAME%: Add more shortcuts...
StartupNotify=false
Categories=System;X-Qubes-VM;
'''

APPTEMPLATE_DIR_R32 = '''[Desktop Entry]
Encoding=UTF-8
Type=Directory
Icon=%XDGICON%
Name=%VMTYPE%: %VMNAME%
'''

QUBESXML_R1 = '''<?xml version='1.0' encoding='UTF-8'?>
<QubesVmCollection clockvm="2" default_fw_netvm="2" default_kernel="3.2.7-10" default_netvm="3" default_template="1" updatevm="3"><QubesTemplateVm conf_file="fedora-17-x64.conf" debug="False" default_user="user" dir_path="/var/lib/qubes/vm-templates/fedora-17-x64" include_in_backups="True" installed_by_rpm="True" internal="False" kernel="3.2.7-10" kernelopts="" label="gray" maxmem="4063" memory="400" name="fedora-17-x64" netvm_qid="3" pcidevs="[]" private_img="private.img" qid="1" root_img="root.img" services="{&apos;meminfo-writer&apos;: True}" template_qid="none" uses_default_kernel="True" uses_default_kernelopts="True" uses_default_netvm="True" vcpus="2" volatile_img="volatile.img" /><QubesNetVm conf_file="netvm.conf" debug="False" default_user="user" dir_path="/var/lib/qubes/servicevms/netvm" include_in_backups="True" installed_by_rpm="False" internal="False" kernel="3.2.7-10" kernelopts="iommu=soft swiotlb=2048" label="red" maxmem="4063" memory="200" name="netvm" netid="1" pcidevs="[&apos;00:19.0&apos;, &apos;03:00.0&apos;]" private_img="private.img" qid="2" root_img="root.img" services="{&apos;ntpd&apos;: False, &apos;meminfo-writer&apos;: False}" template_qid="1" uses_default_kernel="True" uses_default_kernelopts="True" vcpus="2" volatile_img="volatile.img" /><QubesProxyVm conf_file="firewallvm.conf" debug="False" default_user="user" dir_path="/var/lib/qubes/servicevms/firewallvm" include_in_backups="True" installed_by_rpm="False" internal="False" kernel="3.2.7-10" kernelopts="" label="green" maxmem="4063" memory="200" name="firewallvm" netid="2" netvm_qid="2" pcidevs="[]" private_img="private.img" qid="3" root_img="root.img" services="{&apos;meminfo-writer&apos;: True}" template_qid="1" uses_default_kernel="True" uses_default_kernelopts="True" vcpus="2" volatile_img="volatile.img" /><QubesAppVm conf_file="fedora-17-x64-dvm.conf" debug="False" default_user="user" dir_path="/var/lib/qubes/appvms/fedora-17-x64-dvm" include_in_backups="True" installed_by_rpm="False" internal="True" kernel="3.2.7-10" kernelopts="" label="gray" maxmem="4063" memory="400" name="fedora-17-x64-dvm" netvm_qid="3" pcidevs="[]" private_img="private.img" qid="4" root_img="root.img" services="{&apos;meminfo-writer&apos;: True}" template_qid="1" uses_default_kernel="True" uses_default_kernelopts="True" uses_default_netvm="True" vcpus="1" volatile_img="volatile.img" /><QubesAppVm conf_file="test-work.conf" debug="False" default_user="user" dir_path="/var/lib/qubes/appvms/test-work" include_in_backups="True" installed_by_rpm="False" internal="False" kernel="3.2.7-10" kernelopts="" label="green" maxmem="4063" memory="400" name="test-work" netvm_qid="3" pcidevs="[]" private_img="private.img" qid="5" root_img="root.img" services="{&apos;meminfo-writer&apos;: True}" template_qid="1" uses_default_kernel="True" uses_default_kernelopts="True" uses_default_netvm="True" vcpus="2" volatile_img="volatile.img" /><QubesAppVm conf_file="personal.conf" debug="False" default_user="user" dir_path="/var/lib/qubes/appvms/personal" include_in_backups="True" installed_by_rpm="False" internal="False" kernel="3.2.7-10" kernelopts="" label="yellow" maxmem="4063" memory="400" name="personal" netvm_qid="3" pcidevs="[]" private_img="private.img" qid="6" root_img="root.img" services="{&apos;meminfo-writer&apos;: True}" template_qid="1" uses_default_kernel="True" uses_default_kernelopts="True" uses_default_netvm="True" vcpus="2" volatile_img="volatile.img" /><QubesAppVm conf_file="banking.conf" debug="False" default_user="user" dir_path="/var/lib/qubes/appvms/banking" include_in_backups="True" installed_by_rpm="False" internal="False" kernel="3.2.7-10" kernelopts="" label="green" maxmem="4063" memory="400" name="banking" netvm_qid="3" pcidevs="[]" private_img="private.img" qid="7" root_img="root.img" services="{&apos;meminfo-writer&apos;: True}" template_qid="1" uses_default_kernel="True" uses_default_kernelopts="True" uses_default_netvm="True" vcpus="2" volatile_img="volatile.img" /><QubesAppVm conf_file="untrusted.conf" debug="False" default_user="user" dir_path="/var/lib/qubes/appvms/untrusted" include_in_backups="True" installed_by_rpm="False" internal="False" kernel="3.2.7-10" kernelopts="" label="red" maxmem="4063" memory="400" name="untrusted" netvm_qid="3" pcidevs="[]" private_img="private.img" qid="8" root_img="root.img" services="{&apos;meminfo-writer&apos;: True}" template_qid="1" uses_default_kernel="True" uses_default_kernelopts="True" uses_default_netvm="True" vcpus="2" volatile_img="volatile.img" /><QubesAppVm conf_file="test-standalonevm.conf" debug="False" default_user="user" dir_path="/var/lib/qubes/appvms/test-standalonevm" include_in_backups="True" installed_by_rpm="False" internal="False" kernel="None" kernelopts="" label="red" maxmem="4063" memory="400" name="test-standalonevm" netvm_qid="3" pcidevs="[]" private_img="private.img" qid="9" root_img="root.img" services="{&apos;meminfo-writer&apos;: True}" template_qid="none" uses_default_kernel="False" uses_default_kernelopts="True" uses_default_netvm="True" vcpus="2" volatile_img="volatile.img" /><QubesAppVm conf_file="test-testvm.conf" debug="False" default_user="user" dir_path="/var/lib/qubes/appvms/test-testvm" include_in_backups="True" installed_by_rpm="False" internal="False" kernel="3.2.7-10" kernelopts="" label="red" mac="00:16:3E:5E:6C:55" maxmem="4063" memory="400" name="test-testvm" netvm_qid="3" pcidevs="[]" private_img="private.img" qid="10" root_img="root.img" services="{&apos;meminfo-writer&apos;: True}" template_qid="1" uses_default_kernel="True" uses_default_kernelopts="True" uses_default_netvm="True" vcpus="2" volatile_img="volatile.img" /><QubesTemplateVm conf_file="test-template-clone.conf" debug="False" default_user="user" dir_path="/var/lib/qubes/vm-templates/test-template-clone" include_in_backups="True" installed_by_rpm="False" internal="False" kernel="3.2.7-10" kernelopts="" label="gray" maxmem="4063" memory="400" name="test-template-clone" netvm_qid="3" pcidevs="[]" private_img="private.img" qid="11" root_img="root.img" services="{&apos;meminfo-writer&apos;: True}" template_qid="none" uses_default_kernel="True" uses_default_kernelopts="True" uses_default_netvm="True" vcpus="2" volatile_img="volatile.img" /><QubesAppVm conf_file="test-custom-template-appvm.conf" debug="False" default_user="user" dir_path="/var/lib/qubes/appvms/test-custom-template-appvm" include_in_backups="True" installed_by_rpm="False" internal="False" kernel="3.2.7-10" kernelopts="" label="yellow" maxmem="4063" memory="400" name="test-custom-template-appvm" netvm_qid="3" pcidevs="[]" private_img="private.img" qid="12" root_img="root.img" services="{&apos;meminfo-writer&apos;: True}" template_qid="11" uses_default_kernel="True" uses_default_kernelopts="True" uses_default_netvm="True" vcpus="2" volatile_img="volatile.img" /><QubesProxyVm conf_file="test-testproxy.conf" debug="False" default_user="user" dir_path="/var/lib/qubes/servicevms/test-testproxy" include_in_backups="True" installed_by_rpm="False" internal="False" kernel="3.2.7-10" kernelopts="" label="yellow" maxmem="4063" memory="200" name="test-testproxy" netid="3" netvm_qid="2" pcidevs="[]" private_img="private.img" qid="13" root_img="root.img" services="{&apos;meminfo-writer&apos;: True}" template_qid="1" uses_default_kernel="True" uses_default_kernelopts="True" vcpus="2" volatile_img="volatile.img" /></QubesVmCollection>
'''

BACKUP_HEADER_R2 = '''version=3
hmac-algorithm=SHA512
crypto-algorithm=aes-256-cbc
encrypted={encrypted}
compressed={compressed}
compression-filter=gzip
'''

BACKUP_HEADER_R32 = '''version=3
hmac-algorithm=SHA512
crypto-algorithm=aes-256-cbc
encrypted={encrypted}
compressed={compressed}
{compression_filter}'''


class TC_00_BackupCompatibility(qubes.tests.BackupTestsMixin, qubes.tests.QubesTestCase):
    def tearDown(self):
        self.qc.unlock_db()
        self.qc.lock_db_for_writing()
        self.qc.load()

        # Remove here as we use 'test-' prefix, instead of 'test-inst-'
        self._remove_test_vms(self.qc, self.conn, prefix="test-")

        self.qc.save()
        self.qc.unlock_db()

        super(TC_00_BackupCompatibility, self).tearDown()

    def create_whitelisted_appmenus(self, filename, appmenus_list=None):
        if appmenus_list is None:
            appmenus_list = ['gnome-terminal', 'nautilus', 'firefox'
                'mozilla-thunderbird', 'libreoffice-startcenter']
        with open(filename, "w") as f:
            for app in appmenus_list:
                f.write(app + '.desktop\n')

    def create_appmenus(self, dir, template, list, fname_prefix=''):
        for name in list:
            f = open(os.path.join(dir, fname_prefix + name + ".desktop"), "w")
            f.write(template.format(name=name, comment=name, command=name))
            f.close()

    def create_private_img(self, filename):
        self.create_sparse(filename, 2*2**30)
        subprocess.check_call(["/usr/sbin/mkfs.ext4", "-q", "-F", filename])

    def create_volatile_img(self, filename):
        self.create_sparse(filename, 11.5*2**30)
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

    def create_files(self, version=1):
        '''Create files for a backup. Versions:
         - 1: Qubes R1 (backup format v1)
         - 2: Qubes R2 (backup format v3)
         - 3: Qubes R3.2 (backup format v3)
         '''

        appmenus_list = [
            "firefox", "gnome-terminal", "evince", "evolution",
            "mozilla-thunderbird", "libreoffice-startcenter", "nautilus",
            "gedit", "gpk-update-viewer", "gpk-application"
        ]
        appmenus_whitelist_template = appmenus_list
        if version >= 3:
            appmenus_list.remove('libreoffice-startcenter')
            appmenus_list.remove('gnome-terminal')
            appmenus_list.remove('nautilus')
            appmenus_list.remove('gedit')
            appmenus_list.remove('gpk-application')
            appmenus_list.extend([
                'org.gnome.Terminal',
                'org.gnome.Nautilus',
                'org.gnome.gedit',
                'org.gnome.Software',
                'gnome-control-center'])
            appmenus_whitelist_template = [
                'org.gnome.Software',
                'org.gnome.Terminal',
                'gnome-control-center',
                'gpk-update-viewer']

        os.mkdir(self.fullpath("appvms"))
        os.mkdir(self.fullpath("servicevms"))
        os.mkdir(self.fullpath("vm-templates"))

        # normal AppVM
        os.mkdir(self.fullpath("appvms/test-work"))
        self.create_whitelisted_appmenus(self.fullpath(
            "appvms/test-work/whitelisted-appmenus.list"))
        if version >= 3:
            shutil.copy("/usr/share/qubes/icons/green.png",
                   self.fullpath("appvms/test-work/icon.png"))
        else:
            os.symlink("/usr/share/qubes/icons/green.png",
                       self.fullpath("appvms/test-work/icon.png"))
        self.create_private_img(self.fullpath("appvms/test-work/private.img"))

        # StandaloneVM
        os.mkdir(self.fullpath("appvms/test-standalonevm"))
        self.create_whitelisted_appmenus(self.fullpath(
            "appvms/test-standalonevm/whitelisted-appmenus.list"))
        if version >= 3:
            shutil.copy("/usr/share/qubes/icons/blue.png",
                       self.fullpath("appvms/test-standalonevm/icon.png"))
        else:
            os.symlink("/usr/share/qubes/icons/blue.png",
                       self.fullpath("appvms/test-standalonevm/icon.png"))
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
        if version >= 2:
            os.mkdir(self.fullpath("appvms/test-testhvm"))
            for filedir in ['icon.png', 'apps.templates', 'private.img',
                    'root.img']:
                subprocess.check_call(
                    ["/bin/cp", "-a",
                        self.fullpath("appvms/test-standalonevm/" + filedir),
                        self.fullpath("appvms/test-testhvm/" + filedir)])

        # HVM based on a template
        if version >= 3:
            os.mkdir(self.fullpath("appvms/test-template-based-hvm"))
            self.create_private_img(
                self.fullpath("appvms/test-template-based-hvm/private.img"))
            shutil.copy("/usr/share/qubes/icons/red.png",
                self.fullpath("appvms/test-template-based-hvm/icon.png"))

        # ProxyVM
        os.mkdir(self.fullpath("servicevms/test-testproxy"))
        self.create_whitelisted_appmenus(self.fullpath(
            "servicevms/test-testproxy/whitelisted-appmenus.list"))
        self.create_private_img(
            self.fullpath("servicevms/test-testproxy/private.img"))

        if version >= 3:
            subprocess.check_call(
                ["/bin/cp", "-a", self.fullpath("servicevms/test-testproxy"),
                    self.fullpath("servicevms/test-net")])

        # Custom template
        os.mkdir(self.fullpath("vm-templates/test-template-clone"))
        self.create_private_img(
            self.fullpath("vm-templates/test-template-clone/private.img"))
        self.create_sparse(self.fullpath(
            "vm-templates/test-template-clone/root-cow.img"), 10*2**30)
        self.create_sparse(self.fullpath(
            "vm-templates/test-template-clone/root.img"), 10*2**30)
        self.fill_image(self.fullpath(
            "vm-templates/test-template-clone/root.img"), 1*2**30, True)
        self.create_volatile_img(self.fullpath(
            "vm-templates/test-template-clone/volatile.img"))
        subprocess.check_call([
            "/bin/tar", "cS",
            "-f", self.fullpath(
                "vm-templates/test-template-clone/clean-volatile.img.tar"),
            "-C", self.fullpath("vm-templates/test-template-clone"),
            "volatile.img"])
        self.create_whitelisted_appmenus(self.fullpath(
            "vm-templates/test-template-clone/whitelisted-appmenus.list"),
            appmenus_whitelist_template)
        self.create_whitelisted_appmenus(self.fullpath(
            "vm-templates/test-template-clone/vm-whitelisted-appmenus.list"))
        if version >= 2:
            self.create_whitelisted_appmenus(self.fullpath(
                "vm-templates/test-template-clone/netvm-whitelisted-appmenus"
                ".list"))
        if version >= 3:
            shutil.copy("/usr/share/qubes/icons/green.png",
                       self.fullpath("vm-templates/test-template-clone/icon.png"))
        else:
            os.symlink("/usr/share/qubes/icons/green.png",
                       self.fullpath("vm-templates/test-template-clone/icon.png"))
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
            appmenus_whitelist_template,
            'test-template-clone-')
        with open(self.fullpath(
                "vm-templates/test-template-clone/apps/test-template-clone"
                "-vm.directory"), 'w') as f:
            f.write(APPTEMPLATE_DIR_R32.
                replace('%VMNAME', 'test-template-clone').
                replace('%XDGICON%', 'appvm-black').
                replace('%VMTYPE%', 'Template'))
        with open(self.fullpath(
                "vm-templates/test-template-clone/apps/test-template-clone"
                "-qubes-appmenu-select.destop"), 'w') as f:
            f.write(APPTEMPLATE_APPMENU_SELECT_R32.
                replace('%VMNAME', 'test-template-clone').
                replace('%XDGICON%', 'appvm-black').
                replace('%VMTYPE%', 'Template'))
        open(self.fullpath(
                "vm-templates/test-template-clone/test-template-clone.conf"),
            'w').close()

        if version >= 3:
            os.mkdir(self.fullpath(
                "vm-templates/test-template-clone/apps.tempicons"))
            for icon in appmenus_list:
                shutil.copy("/usr/share/icons/hicolor/48x48/apps/qubes.png",
                    self.fullpath(
                        "vm-templates/test-template-clone/apps.tempicons/"
                        "{}.png".format(icon)))

            os.mkdir(self.fullpath(
                "vm-templates/test-template-clone/apps.icons"))
            for icon in ['org.gnome.Software', 'org.gnome.Terminal',
                    'gpk-update-viewer']:
                shutil.copy("/usr/share/icons/hicolor/48x48/apps/qubes.png",
                    self.fullpath(
                        "vm-templates/test-template-clone/apps.tempicons/"
                        "{}.png".format(icon)))



        # HVM template
        if version >= 3:
            os.mkdir(self.fullpath('vm-templates/test-hvmtemplate'))
            shutil.copy("/usr/share/qubes/icons/green.png",
                       self.fullpath("vm-templates/test-hvmtemplate/icon.png"))
            self.create_private_img(
                self.fullpath("vm-templates/test-hvmtemplate/private.img"))
            self.create_sparse(self.fullpath(
                "vm-templates/test-hvmtemplate/root-cow.img"), 10 * 2 ** 30)
            self.create_sparse(self.fullpath(
                "vm-templates/test-hvmtemplate/root.img"), 10 * 2 ** 30)
            self.fill_image(self.fullpath(
                "vm-templates/test-hvmtemplate/root.img"), 1 * 2 ** 30, True)
            self.create_volatile_img(self.fullpath(
                "vm-templates/test-hvmtemplate/volatile.img"))
            open(self.fullpath(
                    "vm-templates/test-hvmtemplate/test-hvmtemplate.conf"),
                'w').close()  # TODO
            os.mkdir(self.fullpath(
                    "vm-templates/test-hvmtemplate/apps.templates"))
            with open(self.fullpath(
                    "vm-templates/test-hvmtemplate/apps.templates/qubes-start"
                    ".desktop"), 'w') as f:
                f.write(APPTEMPLATE_HVM_START_R32)
            os.mkdir(
                self.fullpath("vm-templates/test-hvmtemplate/apps"))
            with open(self.fullpath(
                    "vm-templates/test-hvmtemplate/apps/test-hvmtemplate"
                    "-vm.directory"), 'w') as f:
                f.write(APPTEMPLATE_DIR_R32.
                    replace('%VMNAME', 'test-hvmtemplate').
                    replace('%XDGICON%', 'appvm-green').
                    replace('%VMTYPE%', 'Template'))
            with open(self.fullpath(
                    "vm-templates/test-hvmtemplate/apps/test-hvmtemplate"
                    "-qubes-appmenu-select.destop"), 'w') as f:
                f.write(APPTEMPLATE_APPMENU_SELECT_R32.
                    replace('%VMNAME', 'test-hvmtemplate').
                    replace('%XDGICON%', 'appvm-green').
                    replace('%VMTYPE%', 'Template'))
            with open(self.fullpath(
                    "vm-templates/test-hvmtemplate/apps/test-hvmtemplate"
                    "-qubes-start.destop"), 'w') as f:
                f.write(APPTEMPLATE_HVM_START_R32.
                    replace('%VMNAME', 'test-hvmtemplate').
                    replace('%XDGICON%', 'appvm-green').
                    replace('%VMTYPE%', 'Template'))

        if version >= 3:
            os.mkdir(self.fullpath('dom0-home'))
            os.mkdir(self.fullpath('dom0-home/user'))
            os.mkdir(self.fullpath('dom0-home/user/Desktop'))
            with open(self.fullpath('dom0-home/user/Desktop/some-file.txt'),
                    'w') as f:
                f.write('This is test\n')
            os.mkdir(self.fullpath('dom0-home/user/Documents'))
            with open(self.fullpath(
                    'dom0-home/user/Documents/another-file.txt'),
                    'w') as f:
                f.write('This is test\n')

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
                ["openssl", "enc", "-e", "-aes-256-cbc", "-pass", "pass:qubes"],
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

    def create_v3_backup(self, encrypted=True, compressed=True,
            custom_header=None, custom_qubes_xml=None):
        """
        Create "backup format 3" backup - used in R2 and R3.0

        :param encrypt: Should the backup be encrypted
        :return:
        """
        output = open(self.fullpath("backup.bin"), "w")
        with open(self.fullpath("backup-header"), "w") as f:
            if custom_header is not None:
                f.write(custom_header)
            else:
                f.write(BACKUP_HEADER_R2.format(
                    encrypted=str(encrypted),
                    compressed=str(compressed)
                ))
        self.calculate_hmac("backup-header")
        self.append_backup_stream("backup-header", output)
        self.append_backup_stream("backup-header.hmac", output)
        with open(self.fullpath("qubes.xml"), "w") as f:
            if custom_qubes_xml is not None:
                f.write(custom_qubes_xml)
            else:
                if encrypted:
                    qubesxml = QUBESXML_R2
                    for vmname, subdir in MANGLED_SUBDIRS_R2.items():
                        qubesxml = re.sub(r"[a-z-]*/{}".format(vmname),
                                          subdir, qubesxml)
                    f.write(qubesxml)
                else:
                    f.write(QUBESXML_R2)

        self.handle_v3_file("qubes.xml", "", output, encrypted=encrypted,
                            compressed=compressed)

        self.create_files(version=2)
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
                        subdir+'/', output, encrypted=encrypted,
                        compressed=compressed)

        for vm_name in os.listdir(self.fullpath("vm-templates")):
            vm_dir = os.path.join("vm-templates", vm_name)
            if encrypted:
                subdir = MANGLED_SUBDIRS_R2[vm_name]
            else:
                subdir = vm_dir
            self.handle_v3_file(
                os.path.join(vm_dir, "."),
                subdir+'/', output, encrypted=encrypted, compressed=compressed)

        output.close()

    def create_v3_backup_r32(self, compressed=False, encrypted=False,
            custom_header=None, custom_qubes_xml=None):
        # this is intentionally mostly duplicate of create_v3_backup

        output = open(self.fullpath("backup.bin"), "w")
        with open(self.fullpath("backup-header"), "w") as f:
            if custom_header is not None:
                f.write(custom_header)
            else:
                f.write(BACKUP_HEADER_R32.format(
                    encrypted=str(encrypted),
                    compressed=str(compressed),
                    compression_filter=(
                        'compression-filter=gzip\n' if compressed else '')
                ))
        self.calculate_hmac("backup-header")
        self.append_backup_stream("backup-header", output)
        self.append_backup_stream("backup-header.hmac", output)

        with open(self.fullpath("qubes.xml"), "w") as f:
            if custom_qubes_xml is not None:
                f.write(custom_qubes_xml)
            else:
                if encrypted:
                    qubesxml = QUBESXML_R32
                    for vmname, subdir in MANGLED_SUBDIRS_R32.items():
                        qubesxml = re.sub(r"[a-z-]*/{}".format(vmname),
                                          subdir, qubesxml)
                    f.write(qubesxml)
                else:
                    f.write(QUBESXML_R32)

        self.handle_v3_file("qubes.xml", "", output, encrypted=encrypted,
                            compressed=compressed)

        self.create_files(version=3)
        for vm_type in ["appvms", "servicevms"]:
            for vm_name in os.listdir(self.fullpath(vm_type)):
                vm_dir = os.path.join(vm_type, vm_name)
                for f_name in os.listdir(self.fullpath(vm_dir)):
                    if encrypted:
                        subdir = MANGLED_SUBDIRS_R32[vm_name]
                    else:
                        subdir = vm_dir
                    self.handle_v3_file(
                        os.path.join(vm_dir, f_name),
                        subdir+'/', output, encrypted=encrypted,
                        compressed=compressed)

        for vm_name in os.listdir(self.fullpath("vm-templates")):
            vm_dir = os.path.join("vm-templates", vm_name)
            if encrypted:
                subdir = MANGLED_SUBDIRS_R32[vm_name]
            else:
                subdir = vm_dir
            self.handle_v3_file(
                os.path.join(vm_dir, "."),
                subdir+'/', output, encrypted=encrypted, compressed=compressed)

        self.handle_v3_file(
            os.path.join('dom0-home', 'user', "."),
            'dom0-home/', output, encrypted=encrypted, compressed=compressed)



    def test_100_r1(self):
        self.create_files(version=1)

        f = open(self.fullpath("qubes.xml"), "w")
        f.write(QUBESXML_R1)
        f.close()

        self.restore_backup(self.backupdir, options={
            'use-default-template': True,
            'use-default-netvm': True,
        })
        self.assertIsNotNone(self.qc.get_vm_by_name("test-template-clone"))
        self.assertIsNotNone(self.qc.get_vm_by_name("test-testproxy"))
        self.assertIsNotNone(self.qc.get_vm_by_name("test-work"))
        self.assertIsNotNone(self.qc.get_vm_by_name("test-standalonevm"))
        self.assertIsNotNone(self.qc.get_vm_by_name(
            "test-custom-template-appvm"))
        self.assertEqual(self.qc.get_vm_by_name("test-custom-template-appvm")
                         .template,
                         self.qc.get_vm_by_name("test-template-clone"))

    def test_200_r2b2(self):
        self.create_files(version=2)

        f = open(self.fullpath("qubes.xml"), "w")
        f.write(QUBESXML_R2B2)
        f.close()

        self.restore_backup(self.backupdir, options={
            'use-default-template': True,
            'use-default-netvm': True,
        })
        self.assertIsNotNone(self.qc.get_vm_by_name("test-template-clone"))
        self.assertIsNotNone(self.qc.get_vm_by_name("test-testproxy"))
        self.assertIsNotNone(self.qc.get_vm_by_name("test-work"))
        self.assertIsNotNone(self.qc.get_vm_by_name("test-testhvm"))
        self.assertIsNotNone(self.qc.get_vm_by_name("test-standalonevm"))
        self.assertIsNotNone(self.qc.get_vm_by_name(
            "test-custom-template-appvm"))
        self.assertEqual(self.qc.get_vm_by_name("test-custom-template-appvm")
                         .template,
                         self.qc.get_vm_by_name("test-template-clone"))

    def test_210_r2(self):
        self.create_v3_backup(False)

        self.restore_backup(self.fullpath("backup.bin"), options={
            'use-default-template': True,
            'use-default-netvm': True,
        })
        self.assertIsNotNone(self.qc.get_vm_by_name("test-template-clone"))
        self.assertIsNotNone(self.qc.get_vm_by_name("test-testproxy"))
        self.assertIsNotNone(self.qc.get_vm_by_name("test-work"))
        self.assertIsNotNone(self.qc.get_vm_by_name("test-testhvm"))
        self.assertIsNotNone(self.qc.get_vm_by_name("test-standalonevm"))
        self.assertIsNotNone(self.qc.get_vm_by_name(
            "test-custom-template-appvm"))
        self.assertEqual(self.qc.get_vm_by_name("test-custom-template-appvm")
                         .template,
                         self.qc.get_vm_by_name("test-template-clone"))

    def test_220_r2_encrypted(self):
        self.create_v3_backup(True)

        self.restore_backup(self.fullpath("backup.bin"), options={
            'use-default-template': True,
            'use-default-netvm': True,
        })
        self.assertIsNotNone(self.qc.get_vm_by_name("test-template-clone"))
        self.assertIsNotNone(self.qc.get_vm_by_name("test-testproxy"))
        self.assertIsNotNone(self.qc.get_vm_by_name("test-work"))
        self.assertIsNotNone(self.qc.get_vm_by_name("test-testhvm"))
        self.assertIsNotNone(self.qc.get_vm_by_name("test-standalonevm"))
        self.assertIsNotNone(self.qc.get_vm_by_name(
            "test-custom-template-appvm"))
        self.assertEqual(self.qc.get_vm_by_name("test-custom-template-appvm")
                         .template,
                         self.qc.get_vm_by_name("test-template-clone"))

    def assertCorrectlyRestoredR32(self):
        self.assertIsNotNone(self.qc.get_vm_by_name("test-template-clone"))
        self.assertIsNotNone(self.qc.get_vm_by_name("test-testproxy"))
        self.assertIsNotNone(self.qc.get_vm_by_name("test-net"))
        self.assertIsNotNone(self.qc.get_vm_by_name("test-work"))
        self.assertIsNotNone(self.qc.get_vm_by_name("test-testhvm"))
        self.assertIsNotNone(self.qc.get_vm_by_name("test-hvmtemplate"))
        self.assertIsNotNone(self.qc.get_vm_by_name("test-template-based-hvm"))
        self.assertIsNotNone(self.qc.get_vm_by_name("test-standalonevm"))
        self.assertIsNotNone(self.qc.get_vm_by_name(
            "test-custom-template-appvm"))
        self.assertEqual(self.qc.get_vm_by_name("test-custom-template-appvm")
                         .template,
                         self.qc.get_vm_by_name("test-template-clone"))
        self.assertEqual(self.qc.get_vm_by_name("test-template-based-hvm")
                         .template,
                         self.qc.get_vm_by_name("test-hvmtemplate"))
        self.assertEqual(self.qc.get_vm_by_name("test-work").netvm,
            self.qc.get_vm_by_name("test-net"))
        self.assertEqual(self.qc.get_vm_by_name("test-work").dispvm_netvm,
            self.qc.get_vm_by_name("test-testproxy"))

    def test_300_r32(self):
        self.create_v3_backup_r32(compressed=False, encrypted=False)

        self.restore_backup(self.fullpath("backup.bin"), options={
            'use-default-template': True,
            'use-default-netvm': True,
            'dom0-home': False,  # TODO
        })
        self.assertCorrectlyRestoredR32()

    def test_301_r32_compressed(self):
        self.create_v3_backup_r32(compressed=True, encrypted=False)

        self.restore_backup(self.fullpath("backup.bin"), options={
            'use-default-template': True,
            'use-default-netvm': True,
            'dom0-home': False,  # TODO
        })
        self.assertCorrectlyRestoredR32()

    def test_302_r32_encrypted_compressed(self):
        self.create_v3_backup_r32(compressed=True, encrypted=True)

        self.restore_backup(self.fullpath("backup.bin"), options={
            'use-default-template': True,
            'use-default-netvm': True,
            'dom0-home': False,  # TODO
        })
        self.assertCorrectlyRestoredR32()
