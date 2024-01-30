#
# The Qubes OS Project, https://www.qubes-os.org/
#
# Copyright (C) 2015-2020
#                   Marek Marczykowski-Górecki <marmarek@invisiblethingslab.com>
# Copyright (C) 2015  Wojtek Porczyk <woju@invisiblethingslab.com>
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

import asyncio
import subprocess
import sys
import time
import unittest
from distutils import spawn

import qubes.firewall
import qubes.tests
import qubes.vm
from qubes.tests.integ.network import VmNetworkingMixin


# noinspection PyAttributeOutsideInit,PyPep8Naming
class VmIPv6NetworkingMixin(VmNetworkingMixin):
    test_ip6 = '2000:abcd::1'

    ping6_cmd = 'ping6 -W 1 -n -c 1 {target}'

    def setUp(self):
        super(VmIPv6NetworkingMixin, self).setUp()
        self.ping6_ip = self.ping6_cmd.format(target=self.test_ip6)
        self.ping6_name = self.ping6_cmd.format(target=self.test_name)

    def tearDown(self):
        # collect more info on failure (ipv4 info collected in parent)
        if self._outcome and not self._outcome.success:
            for vm in (self.testnetvm, self.testvm1, getattr(self, 'proxy', None)):
                if vm is None:
                    continue
                self._run_cmd_and_log_output(vm, 'ip -6 r')
                self._run_cmd_and_log_output(vm, 'ip6tables -vnL')
                self._run_cmd_and_log_output(vm, 'ip6tables -vnL -t nat')
                self._run_cmd_and_log_output(vm, 'nft list table ip6 qubes-firewall')

        super().tearDown()

    def configure_netvm(self):
        '''
        :type self: qubes.tests.SystemTestCase | VmIPv6NetworkingMixin
        '''
        self.testnetvm.features['ipv6'] = True
        super(VmIPv6NetworkingMixin, self).configure_netvm()

        def run_netvm_cmd(cmd):
            try:
                self.loop.run_until_complete(
                    self.testnetvm.run_for_stdio(cmd, user='root'))
            except subprocess.CalledProcessError as e:
                self.fail("Command '%s' failed: %s%s" %
                          (cmd, e.stdout.decode(), e.stderr.decode()))

        run_netvm_cmd("ip addr add {}/128 dev test0".format(self.test_ip6))
        run_netvm_cmd(
            "nft add ip6 qubes custom-input ip6 daddr {} accept".format(self.test_ip6))
        # ignore failure
        self.run_cmd(self.testnetvm, "while pkill dnsmasq; do sleep 1; done")
        run_netvm_cmd(
            "dnsmasq -a {ip} -A /{name}/{ip} -A /{name}/{ip6} -i test0 -z".
            format(ip=self.test_ip, ip6=self.test_ip6, name=self.test_name))

    def test_500_ipv6_simple_networking(self):
        '''
        :type self: qubes.tests.SystemTestCase | VmIPv6NetworkingMixin
        '''
        self.loop.run_until_complete(self.start_vm(self.testvm1))
        self.assertEqual(self.run_cmd(self.testvm1, self.ping6_ip), 0)
        self.assertEqual(self.run_cmd(self.testvm1, self.ping6_name), 0)


    def test_510_ipv6_simple_proxyvm(self):
        '''
        :type self: qubes.tests.SystemTestCase | VmIPv6NetworkingMixin
        '''
        self.proxy = self.app.add_new_vm(qubes.vm.appvm.AppVM,
            name=self.make_vm_name('proxy'),
            label='red')
        self.proxy.provides_network = True
        self.proxy.netvm = self.testnetvm
        self.loop.run_until_complete(self.proxy.create_on_disk())
        self.testvm1.netvm = self.proxy
        self.app.save()

        self.loop.run_until_complete(self.start_vm(self.testvm1))
        self.assertTrue(self.proxy.is_running())
        self.assertEqual(self.run_cmd(self.proxy, self.ping6_ip), 0,
                         "Ping by IP from ProxyVM failed")
        self.assertEqual(self.run_cmd(self.proxy, self.ping6_name), 0,
                         "Ping by name from ProxyVM failed")
        self.assertEqual(self.run_cmd(self.testvm1, self.ping6_ip), 0,
                         "Ping by IP from AppVM failed")
        self.assertEqual(self.run_cmd(self.testvm1, self.ping6_name), 0,
                         "Ping by IP from AppVM failed")


    @qubes.tests.expectedFailureIfTemplate('debian-7')
    @unittest.skipUnless(spawn.find_executable('xdotool'),
                         "xdotool not installed")
    def test_520_ipv6_simple_proxyvm_nm(self):
        '''
        :type self: qubes.tests.SystemTestCase | VmIPv6NetworkingMixin
        '''
        self.proxy = self.app.add_new_vm(qubes.vm.appvm.AppVM,
            name=self.make_vm_name('proxy'),
            label='red')
        self.proxy.provides_network = True
        self.loop.run_until_complete(self.proxy.create_on_disk())
        self.proxy.netvm = self.testnetvm
        self.proxy.features['service.network-manager'] = True
        self.testvm1.netvm = self.proxy
        self.app.save()

        self.loop.run_until_complete(self.start_vm(self.testvm1))
        self.assertTrue(self.proxy.is_running())
        self.assertEqual(self.run_cmd(self.testvm1, self.ping6_ip), 0,
                         "Ping by IP failed")
        self.assertEqual(self.run_cmd(self.testvm1, self.ping6_name), 0,
                         "Ping by name failed")

        # reconnect to make sure that device was configured by NM
        self.assertEqual(
            self.run_cmd(self.proxy, "nmcli device disconnect eth0",
                user="user"),
            0, "Failed to disconnect eth0 using nmcli")

        self.assertNotEqual(self.run_cmd(self.testvm1, self.ping6_ip), 0,
            "Network should be disabled, but apparently it isn't")
        self.assertEqual(
            self.run_cmd(self.proxy,
                'nmcli connection up "VM uplink eth0" ifname eth0',
                user="user"),
            0, "Failed to connect eth0 using nmcli")
        self.assertEqual(self.run_cmd(self.proxy, "nm-online",
            user="user"), 0,
                         "Failed to wait for NM connection")

        # wait for duplicate-address-detection to complete - by default it has
        #  1s timeout
        time.sleep(2)

        # check for nm-applet presence
        self.assertEqual(subprocess.call([
            'xdotool', 'search', '--class', '{}:nm-applet'.format(
                self.proxy.name)],
            stdout=subprocess.DEVNULL), 0, "nm-applet window not found")
        self.assertEqual(self.run_cmd(self.testvm1, self.ping6_ip), 0,
                         "Ping by IP failed (after NM reconnection")
        self.assertEqual(self.run_cmd(self.testvm1, self.ping6_name), 0,
                         "Ping by name failed (after NM reconnection)")


    def test_530_ipv6_firewallvm_firewall(self):
        '''
        :type self: qubes.tests.SystemTestCase | VmIPv6NetworkingMixin
        '''
        self.proxy = self.app.add_new_vm(qubes.vm.appvm.AppVM,
            name=self.make_vm_name('proxy'),
            label='red')
        self.proxy.provides_network = True
        self.loop.run_until_complete(self.proxy.create_on_disk())
        self.proxy.netvm = self.testnetvm
        self.testvm1.netvm = self.proxy
        self.app.save()

        # block all for first

        self.testvm1.firewall.rules = [qubes.firewall.Rule(action='drop')]
        self.testvm1.firewall.save()
        self.loop.run_until_complete(self.start_vm(self.testvm1))
        self.assertTrue(self.proxy.is_running())

        server = self.loop.run_until_complete(self.testnetvm.run(
            'socat TCP6-LISTEN:1234,fork EXEC:/bin/uname'))

        try:
            self.assertEqual(self.run_cmd(self.proxy, self.ping6_ip), 0,
                            "Ping by IP from ProxyVM failed")
            self.assertEqual(self.run_cmd(self.proxy, self.ping6_name), 0,
                            "Ping by name from ProxyVM failed")
            self.assertNotEqual(self.run_cmd(self.testvm1, self.ping6_ip), 0,
                            "Ping by IP should be blocked")

            client6_cmd = "socat TCP:[{}]:1234 -".format(self.test_ip6)
            client4_cmd = "socat TCP:{}:1234 -".format(self.test_ip)
            self.assertNotEqual(self.run_cmd(self.testvm1, client6_cmd), 0,
                            "TCP connection should be blocked")

            # block all except ICMP

            self.testvm1.firewall.rules = [(
                qubes.firewall.Rule(None, action='accept', proto='icmp')
            )]
            self.testvm1.firewall.save()
            # Ugly hack b/c there is no feedback when the rules are actually
            # applied
            time.sleep(3)
            self.assertEqual(self.run_cmd(self.testvm1, self.ping6_ip), 0,
                            "Ping by IP failed (should be allowed now)")
            self.assertNotEqual(self.run_cmd(self.testvm1, self.ping6_name), 0,
                            "Ping by name should be blocked")

            # all TCP still blocked

            self.testvm1.firewall.rules = [
                qubes.firewall.Rule(None, action='accept', proto='icmp'),
                qubes.firewall.Rule(None, action='accept', specialtarget='dns'),
            ]
            self.testvm1.firewall.save()

            # Ugly hack b/c there is no feedback when the rules are actually
            # applied
            time.sleep(3)
            self.assertEqual(self.run_cmd(self.testvm1, self.ping6_name), 0,
                            "Ping by name failed (should be allowed now)")
            self.assertNotEqual(self.run_cmd(self.testvm1, client6_cmd), 0,
                            "TCP connection should be blocked")

            # block all except target

            self.testvm1.firewall.rules = [
                qubes.firewall.Rule(None, action='accept',
                    dsthost=self.test_ip6,
                    proto='tcp', dstports=1234),
            ]
            self.testvm1.firewall.save()

            # Ugly hack b/c there is no feedback when the rules are actually
            # applied
            time.sleep(3)
            self.assertEqual(self.run_cmd(self.testvm1, client6_cmd), 0,
                            "TCP connection failed (should be allowed now)")

            # block all except target - by name

            self.testvm1.firewall.rules = [
                qubes.firewall.Rule(None, action='accept',
                    dsthost=self.test_name,
                    proto='tcp', dstports=1234),
            ]
            self.testvm1.firewall.save()

            # Ugly hack b/c there is no feedback when the rules are actually
            # applied
            time.sleep(3)
            self.assertEqual(self.run_cmd(self.testvm1, client6_cmd), 0,
                "TCP (IPv6) connection failed (should be allowed now)")
            self.assertEqual(self.run_cmd(self.testvm1, client4_cmd),
                0,
                "TCP (IPv4) connection failed (should be allowed now)")

            # allow all except target

            self.testvm1.firewall.rules = [
                qubes.firewall.Rule(None, action='drop', dsthost=self.test_ip6,
                    proto='tcp', dstports=1234),
                qubes.firewall.Rule(action='accept'),
            ]
            self.testvm1.firewall.save()

            # Ugly hack b/c there is no feedback when the rules are actually
            # applied
            time.sleep(3)
            self.assertNotEqual(self.run_cmd(self.testvm1, client6_cmd), 0,
                            "TCP connection should be blocked")
        finally:
            server.terminate()
            self.loop.run_until_complete(server.wait())


    def test_540_ipv6_inter_vm(self):
        '''
        :type self: qubes.tests.SystemTestCase | VmIPv6NetworkingMixin
        '''
        self.proxy = self.app.add_new_vm(qubes.vm.appvm.AppVM,
            name=self.make_vm_name('proxy'),
            label='red')
        self.loop.run_until_complete(self.proxy.create_on_disk())
        self.proxy.provides_network = True
        self.proxy.netvm = self.testnetvm
        self.testvm1.netvm = self.proxy

        self.testvm2 = self.app.add_new_vm(qubes.vm.appvm.AppVM,
            name=self.make_vm_name('vm2'),
            label='red')
        self.loop.run_until_complete(self.testvm2.create_on_disk())
        self.testvm2.netvm = self.proxy
        self.app.save()

        self.loop.run_until_complete(asyncio.gather(
            self.start_vm(self.testvm1),
            self.start_vm(self.testvm2)))

        self.assertNotEqual(self.run_cmd(self.testvm1,
            self.ping_cmd.format(target=self.testvm2.ip6)), 0)

        self.testvm2.netvm = self.testnetvm

        self.assertNotEqual(self.run_cmd(self.testvm1,
            self.ping_cmd.format(target=self.testvm2.ip6)), 0)
        self.assertNotEqual(self.run_cmd(self.testvm2,
            self.ping_cmd.format(target=self.testvm1.ip6)), 0)

        self.testvm1.netvm = self.testnetvm

        self.assertNotEqual(self.run_cmd(self.testvm1,
            self.ping_cmd.format(target=self.testvm2.ip6)), 0)
        self.assertNotEqual(self.run_cmd(self.testvm2,
            self.ping_cmd.format(target=self.testvm1.ip6)), 0)



    def test_550_ipv6_spoof_ip(self):
        '''Test if VM IP spoofing is blocked

        :type self: qubes.tests.SystemTestCase | VmIPv6NetworkingMixin
        '''
        self.loop.run_until_complete(self.start_vm(self.testvm1))

        self.assertEqual(self.run_cmd(self.testvm1, self.ping6_ip), 0)
        # add a simple rule counting packets
        iptables = False
        cmd = "nft add ip6 qubes custom-input ip6 saddr {} counter".format(
            self.testvm1.ip6)
        retcode = self.run_cmd(self.testnetvm, cmd)
        if retcode == 127:
            self.assertEqual(self.run_cmd(self.testnetvm,
                'ip6tables -I INPUT -i vif+ ! -s {} -p icmpv6 -j LOG'.format(
                    self.testvm1.ip6)), 0)
            iptables = True
        elif retcode != 0:
            raise AssertionError(
                '{} failed with: {}'.format(cmd, retcode))
        self.loop.run_until_complete(self.testvm1.run_for_stdio(
            'ip -6 addr flush dev eth0 && '
            'ip -6 addr add {}/128 dev eth0 && '
            'ip -6 route replace default via {} dev eth0'.format(
                str(self.testvm1.visible_ip6) + '1',
                str(self.testvm1.visible_gateway6)),
            user='root'))
        self.assertNotEqual(self.run_cmd(self.testvm1, self.ping6_ip), 0,
                         "Spoofed ping should be blocked")
        if iptables:
            try:
                (output, _) = self.loop.run_until_complete(
                    self.testnetvm.run_for_stdio('ip6tables -nxvL INPUT',
                        user='root'))
            except subprocess.CalledProcessError:
                self.fail('ip6tables -nxvL INPUT failed')
            index = 0
            line = 2
        else:
            try:
                (output, _) = self.loop.run_until_complete(
                    self.testnetvm.run_for_stdio('nft list chain ip6 qubes custom-input',
                        user='root'))
            except subprocess.CalledProcessError:
                self.fail('nft list ip6 chain qubes custom-input')
            # ... packets 0 bytes 0
            line = 3
            index = -3
        output = output.decode().splitlines()
        packets = output[line].lstrip().split()[index]
        self.assertEqual(packets, '0', 'Some packet hit the INPUT rule')

    def test_710_ipv6_custom_ip_simple(self):
        '''Custom AppVM IP

        :type self: qubes.tests.SystemTestCase | VmIPv6NetworkingMixin
        '''
        self.testvm1.ip6 = '2000:aaaa:bbbb::1'
        self.app.save()
        self.loop.run_until_complete(self.start_vm(self.testvm1))
        self.assertEqual(self.run_cmd(self.testvm1, self.ping6_ip), 0)
        self.assertEqual(self.run_cmd(self.testvm1, self.ping6_name), 0)

    def test_711_ipv6_custom_ip_proxy(self):
        '''Custom ProxyVM IP

        :type self: qubes.tests.SystemTestCase | VmIPv6NetworkingMixin
        '''
        self.proxy = self.app.add_new_vm(qubes.vm.appvm.AppVM,
            name=self.make_vm_name('proxy'),
            label='red')
        self.loop.run_until_complete(self.proxy.create_on_disk())
        self.proxy.provides_network = True
        self.proxy.netvm = self.testnetvm
        self.testvm1.ip6 = '2000:aaaa:bbbb::1'
        self.testvm1.netvm = self.proxy
        self.app.save()

        self.loop.run_until_complete(self.start_vm(self.testvm1))

        self.assertEqual(self.run_cmd(self.testvm1, self.ping6_ip), 0)
        self.assertEqual(self.run_cmd(self.testvm1, self.ping6_name), 0)

    def test_712_ipv6_custom_ip_firewall(self):
        '''Custom VM IP and firewall

        :type self: qubes.tests.SystemTestCase | VmIPv6NetworkingMixin
        '''
        self.testvm1.ip6 = '2000:aaaa:bbbb::1'

        self.proxy = self.app.add_new_vm(qubes.vm.appvm.AppVM,
            name=self.make_vm_name('proxy'),
            label='red')
        self.proxy.provides_network = True
        self.loop.run_until_complete(self.proxy.create_on_disk())
        self.proxy.netvm = self.testnetvm
        self.testvm1.netvm = self.proxy
        self.app.save()

        # block all but ICMP and DNS

        self.testvm1.firewall.rules = [
            qubes.firewall.Rule(None, action='accept', proto='icmp'),
            qubes.firewall.Rule(None, action='accept', specialtarget='dns'),
        ]
        self.testvm1.firewall.save()
        self.loop.run_until_complete(self.start_vm(self.testvm1))
        self.assertTrue(self.proxy.is_running())

        server = self.loop.run_until_complete(self.testnetvm.run(
            'socat TCP6-LISTEN:1234,fork EXEC:/bin/uname'))

        try:
            self.assertEqual(self.run_cmd(self.proxy, self.ping6_ip), 0,
                            "Ping by IP from ProxyVM failed")
            self.assertEqual(self.run_cmd(self.proxy, self.ping6_name), 0,
                            "Ping by name from ProxyVM failed")
            self.assertEqual(self.run_cmd(self.testvm1, self.ping6_ip), 0,
                            "Ping by IP should be allowed")
            self.assertEqual(self.run_cmd(self.testvm1, self.ping6_name), 0,
                            "Ping by name should be allowed")
            client_cmd = "socat TCP:[{}]:1234 -".format(self.test_ip6)
            self.assertNotEqual(self.run_cmd(self.testvm1, client_cmd), 0,
                            "TCP connection should be blocked")
        finally:
            server.terminate()
            self.loop.run_until_complete(server.wait())

def create_testcases_for_templates():
    yield from qubes.tests.create_testcases_for_templates('VmIPv6Networking',
        VmIPv6NetworkingMixin, qubes.tests.SystemTestCase,
        module=sys.modules[__name__])

def load_tests(loader, tests, pattern):
    tests.addTests(loader.loadTestsFromNames(
        create_testcases_for_templates()))
    return tests

qubes.tests.maybe_create_testcases_on_import(create_testcases_for_templates)
