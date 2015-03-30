#!/usr/bin/python
# vim: fileencoding=utf-8

#
# The Qubes OS Project, https://www.qubes-os.org/
#
# Copyright (C) 2015
#                   Marek Marczykowski-Górecki <marmarek@invisiblethingslab.com>
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
from distutils import spawn

import multiprocessing
import os
import subprocess
import unittest
import time

from qubes.qubes import QubesVmCollection, defaults

import qubes.tests


class VmNetworkingMixin(qubes.tests.SystemTestsMixin):
    test_ip = '192.168.123.45'
    test_name = 'test.example.com'

    ping_cmd = 'ping -W 1 -n -c 1 {target}'
    ping_ip = ping_cmd.format(target=test_ip)
    ping_name = ping_cmd.format(target=test_name)

    def run_cmd(self, vm, cmd, user="root"):
        p = vm.run(cmd, user=user, passio_popen=True, ignore_stderr=True)
        p.stdin.close()
        p.stdout.read()
        return p.wait()

    def setUp(self):
        super(VmNetworkingMixin, self).setUp()
        self.testnetvm = self.qc.add_new_vm("QubesNetVm",
            name=self.make_vm_name('netvm1'),
            template=self.qc.get_vm_by_name(self.template))
        self.testnetvm.create_on_disk(verbose=False)
        self.testvm1 = self.qc.add_new_vm("QubesAppVm",
            name=self.make_vm_name('vm2'),
            template=self.qc.get_vm_by_name(self.template))
        self.testvm1.create_on_disk(verbose=False)
        self.testvm1.netvm = self.testnetvm
        self.qc.save()

        self.configure_netvm()


    def configure_netvm(self):
        def run_netvm_cmd(cmd):
            if self.run_cmd(self.testnetvm, cmd) != 0:
                self.fail("Command '%s' failed" % cmd)

        if not self.testnetvm.is_running():
            self.testnetvm.start()
        # Ensure that dnsmasq is installed:
        p = self.testnetvm.run("dnsmasq --version", user="root",
                               passio_popen=True)
        if p.wait() != 0:
            self.skipTest("dnsmasq not installed")

        run_netvm_cmd("ip link add test0 type dummy")
        run_netvm_cmd("ip link set test0 up")
        run_netvm_cmd("ip addr add {}/24 dev test0".format(self.test_ip))
        run_netvm_cmd("iptables -I INPUT -d {} -j ACCEPT".format(self.test_ip))
        run_netvm_cmd("dnsmasq -a {ip} -A /{name}/{ip} -i test0 -z".format(
            ip=self.test_ip, name=self.test_name))
        run_netvm_cmd("echo nameserver {} > /etc/resolv.conf".format(
            self.test_ip))
        run_netvm_cmd("/usr/lib/qubes/qubes-setup-dnat-to-ns")


    def test_000_simple_networking(self):
        self.qc.unlock_db()
        self.testvm1.start()
        self.assertEqual(self.run_cmd(self.testvm1, self.ping_ip), 0)
        self.assertEqual(self.run_cmd(self.testvm1, self.ping_name), 0)


    def test_010_simple_proxyvm(self):
        self.proxy = self.qc.add_new_vm("QubesProxyVm",
            name=self.make_vm_name('proxy'),
            template=self.qc.get_vm_by_name(self.template))
        self.proxy.create_on_disk(verbose=False)
        self.proxy.netvm = self.testnetvm
        self.testvm1.netvm = self.proxy
        self.qc.save()
        self.qc.unlock_db()

        self.testvm1.start()
        self.assertTrue(self.proxy.is_running())
        self.assertEqual(self.run_cmd(self.proxy, self.ping_ip), 0,
                         "Ping by IP from ProxyVM failed")
        self.assertEqual(self.run_cmd(self.proxy, self.ping_name), 0,
                         "Ping by name from ProxyVM failed")
        self.assertEqual(self.run_cmd(self.testvm1, self.ping_ip), 0,
                         "Ping by IP from AppVM failed")
        self.assertEqual(self.run_cmd(self.testvm1, self.ping_name), 0,
                         "Ping by IP from AppVM failed")


    @unittest.skipUnless(spawn.find_executable('xdotool'),
                         "xdotool not installed")
    def test_020_simple_proxyvm_nm(self):
        self.proxy = self.qc.add_new_vm("QubesProxyVm",
            name=self.make_vm_name('proxy'),
            template=self.qc.get_vm_by_name(self.template))
        self.proxy.create_on_disk(verbose=False)
        self.proxy.netvm = self.testnetvm
        self.proxy.services['network-manager'] = True
        self.testvm1.netvm = self.proxy
        self.qc.save()
        self.qc.unlock_db()

        self.testvm1.start()
        self.assertTrue(self.proxy.is_running())
        self.assertEqual(self.run_cmd(self.testvm1, self.ping_ip), 0,
                         "Ping by IP failed")
        self.assertEqual(self.run_cmd(self.testvm1, self.ping_name), 0,
                         "Ping by name failed")

        # reconnect to make sure that device was configured by NM
        self.assertEqual(
            self.run_cmd(self.proxy, "nmcli device disconnect eth0",
                user="user"),
            0, "Failed to disconnect eth0 using nmcli")

        self.assertNotEqual(self.run_cmd(self.testvm1, self.ping_ip), 0,
            "Network should be disabled, but apparently it isn't")
        self.assertEqual(
            self.run_cmd(self.proxy,
                'nmcli connection up "VM uplink eth0" ifname eth0',
                user="user"),
            0, "Failed to connect eth0 using nmcli")
        self.assertEqual(self.run_cmd(self.proxy, "nm-online", user="user"), 0,
                         "Failed to wait for NM connection")

        # check for nm-applet presence
        self.assertEqual(subprocess.call([
            'xdotool', 'search', '--all', '--name',
            '--class', '^(NetworkManager Applet|{})$'.format(self.proxy.name)],
            stdout=open('/dev/null', 'w')), 0, "nm-applet window not found")
        self.assertEqual(self.run_cmd(self.testvm1, self.ping_ip), 0,
                         "Ping by IP failed (after NM reconnection")
        self.assertEqual(self.run_cmd(self.testvm1, self.ping_name), 0,
                         "Ping by name failed (after NM reconnection)")


    def test_030_firewallvm_firewall(self):
        self.proxy = self.qc.add_new_vm("QubesProxyVm",
            name=self.make_vm_name('proxy'),
            template=self.qc.get_vm_by_name(self.template))
        self.proxy.create_on_disk(verbose=False)
        self.proxy.netvm = self.testnetvm
        self.testvm1.netvm = self.proxy
        self.qc.save()
        self.qc.unlock_db()

        # block all for first

        self.testvm1.write_firewall_conf({
            'allow': False,
            'allowDns': False,
            'allowIcmp': False,
        })
        self.testvm1.start()
        self.assertTrue(self.proxy.is_running())

        self.testnetvm.run("nc -l --send-only -e /bin/hostname -k 1234")

        self.assertEqual(self.run_cmd(self.proxy, self.ping_ip), 0,
                         "Ping by IP from ProxyVM failed")
        self.assertEqual(self.run_cmd(self.proxy, self.ping_name), 0,
                         "Ping by name from ProxyVM failed")
        self.assertNotEqual(self.run_cmd(self.testvm1, self.ping_ip), 0,
                         "Ping by IP should be blocked")
        nc_cmd = "nc -w 1 --recv-only {} 1234".format(self.test_ip)
        self.assertNotEqual(self.run_cmd(self.testvm1, nc_cmd), 0,
                         "TCP connection should be blocked")

        # block all except ICMP

        self.testvm1.write_firewall_conf({
            'allow': False,
            'allowDns': False,
            'allowIcmp': True,
        })
        self.proxy.write_iptables_qubesdb_entry()
        # Ugly hack b/c there is no feedback when the rules are actually applied
        time.sleep(3)
        self.assertEqual(self.run_cmd(self.testvm1, self.ping_ip), 0,
                         "Ping by IP failed (should be allowed now)")
        self.assertNotEqual(self.run_cmd(self.testvm1, self.ping_name), 0,
                         "Ping by name should be blocked")

        # all TCP still blocked

        self.testvm1.write_firewall_conf({
            'allow': False,
            'allowDns': True,
            'allowIcmp': True,
        })
        self.proxy.write_iptables_qubesdb_entry()
        # Ugly hack b/c there is no feedback when the rules are actually applied
        time.sleep(3)
        self.assertEqual(self.run_cmd(self.testvm1, self.ping_name), 0,
                         "Ping by name failed (should be allowed now)")
        self.assertNotEqual(self.run_cmd(self.testvm1, nc_cmd), 0,
                         "TCP connection should be blocked")

        # block all except target

        self.testvm1.write_firewall_conf({
            'allow': False,
            'allowDns': True,
            'allowIcmp': True,
            'rules': [{'address': self.test_ip,
                       'netmask': 32,
                       'proto': 'tcp',
                       'portBegin': 1234
                      }] })
        self.proxy.write_iptables_qubesdb_entry()
        # Ugly hack b/c there is no feedback when the rules are actually applied
        time.sleep(3)
        self.assertEqual(self.run_cmd(self.testvm1, nc_cmd), 0,
                         "TCP connection failed (should be allowed now)")

        # allow all except target

        self.testvm1.write_firewall_conf({
            'allow': True,
            'allowDns': True,
            'allowIcmp': True,
            'rules': [{'address': self.test_ip,
                       'netmask': 32,
                       'proto': 'tcp',
                       'portBegin': 1234
                      }]
        })
        self.proxy.write_iptables_qubesdb_entry()
        # Ugly hack b/c there is no feedback when the rules are actually applied
        time.sleep(3)
        self.assertNotEqual(self.run_cmd(self.testvm1, nc_cmd), 0,
                         "TCP connection should be blocked")


    def test_040_inter_vm(self):
        self.proxy = self.qc.add_new_vm("QubesProxyVm",
            name=self.make_vm_name('proxy'),
            template=self.qc.get_vm_by_name(self.template))
        self.proxy.create_on_disk(verbose=False)
        self.proxy.netvm = self.testnetvm
        self.testvm1.netvm = self.proxy

        self.testvm2 = self.qc.add_new_vm("QubesAppVm",
            name=self.make_vm_name('vm3'),
            template=self.qc.get_vm_by_name(self.template))
        self.testvm2.create_on_disk(verbose=False)
        self.testvm2.netvm = self.proxy
        self.qc.save()
        self.qc.unlock_db()

        self.testvm1.start()
        self.testvm2.start()

        self.assertNotEqual(self.run_cmd(self.testvm1,
            self.ping_cmd.format(target=self.testvm2.ip)), 0)

        self.testvm2.netvm = self.testnetvm

        self.assertNotEqual(self.run_cmd(self.testvm1,
            self.ping_cmd.format(target=self.testvm2.ip)), 0)
        self.assertNotEqual(self.run_cmd(self.testvm2,
            self.ping_cmd.format(target=self.testvm1.ip)), 0)

        self.testvm1.netvm = self.testnetvm

        self.assertNotEqual(self.run_cmd(self.testvm1,
            self.ping_cmd.format(target=self.testvm2.ip)), 0)
        self.assertNotEqual(self.run_cmd(self.testvm2,
            self.ping_cmd.format(target=self.testvm1.ip)), 0)



def load_tests(loader, tests, pattern):
    try:
        qc = qubes.qubes.QubesVmCollection()
        qc.lock_db_for_reading()
        qc.load()
        qc.unlock_db()
        templates = [vm.name for vm in qc.values() if
                     isinstance(vm, qubes.qubes.QubesTemplateVm)]
    except OSError:
        templates = []
    for template in templates:
        tests.addTests(loader.loadTestsFromTestCase(
            type(
                'VmNetworking_' + template,
                (VmNetworkingMixin, qubes.tests.QubesTestCase),
                {'template': template})))
    return tests
