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
import contextlib
from distutils import spawn

import asyncio
import subprocess
import sys
import time
import unittest

import qubes.tests
import qubes.firewall
import qubes.vm.qubesvm
import qubes.vm.appvm


# noinspection PyAttributeOutsideInit,PyPep8Naming
class VmNetworkingMixin(object):
    test_ip = '192.168.123.45'
    test_name = 'test.example.com'

    ping_cmd = 'ping -W 1 -n -c 1 {target}'
    ping_ip = ping_cmd.format(target=test_ip)
    ping_name = ping_cmd.format(target=test_name)

    # filled by load_tests
    template = None

    def run_cmd(self, vm, cmd, user="root"):
        '''Run a command *cmd* in a *vm* as *user*. Return its exit code.
        :type self: qubes.tests.SystemTestCase | VmNetworkingMixin
        :param qubes.vm.qubesvm.QubesVM vm: VM object to run command in
        :param str cmd: command to execute
        :param std user: user to execute command as
        :return int: command exit code
        '''
        try:
            self.loop.run_until_complete(vm.run_for_stdio(cmd, user=user))
        except subprocess.CalledProcessError as e:
            return e.returncode
        return 0

    def setUp(self):
        '''
        :type self: qubes.tests.SystemTestCase | VMNetworkingMixin
        '''
        super(VmNetworkingMixin, self).setUp()
        if self.template.startswith('whonix-'):
            self.skipTest("Test not supported here - Whonix uses its own "
                          "firewall settings")
        if self.template.endswith('-minimal'):
            self.skipTest(
                "Test not supported here - minimal template don't have "
                "networking packages by default")
        self.init_default_template(self.template)
        self.testnetvm = self.app.add_new_vm(qubes.vm.appvm.AppVM,
            name=self.make_vm_name('netvm1'),
            label='red')
        self.loop.run_until_complete(self.testnetvm.create_on_disk())
        self.testnetvm.provides_network = True
        self.testnetvm.netvm = None
        # avoid races with NetworkManager, self.configure_netvm() configures
        # everything directly
        self.testnetvm.features['service.network-manager'] = False
        self.testvm1 = self.app.add_new_vm(qubes.vm.appvm.AppVM,
            name=self.make_vm_name('vm1'),
            label='red')
        self.loop.run_until_complete(self.testvm1.create_on_disk())
        self.testvm1.netvm = self.testnetvm
        self.app.save()

        self.configure_netvm()

    def _run_cmd_and_log_output(self, vm, cmd):
        """Used in tearDown to collect more info"""
        if not vm.is_running():
            return
        with contextlib.suppress(subprocess.CalledProcessError):
            output, _ = self.loop.run_until_complete(
                vm.run_for_stdio(cmd, user='root', stderr=subprocess.STDOUT))
            self.log.critical('{}: {}: {}'.format(vm.name, cmd, output))

    def tearDown(self):
        # collect more info on failure
        if not self.success():
            for vm in (self.testnetvm, self.testvm1, getattr(self, 'proxy', None)):
                if vm is None:
                    continue
                self._run_cmd_and_log_output(vm, 'ip a')
                self._run_cmd_and_log_output(vm, 'ip r')
                self._run_cmd_and_log_output(vm, 'iptables -vnL')
                self._run_cmd_and_log_output(vm, 'iptables -vnL -t nat')
                self._run_cmd_and_log_output(vm, 'nft list table qubes-firewall')
                self._run_cmd_and_log_output(vm, 'systemctl --no-pager status qubes-firewall')
                self._run_cmd_and_log_output(vm, 'systemctl --no-pager status qubes-iptables')
                self._run_cmd_and_log_output(vm, 'systemctl --no-pager status xendriverdomain')
                self._run_cmd_and_log_output(vm, 'cat /var/log/xen/xen-hotplug.log')

        super(VmNetworkingMixin, self).tearDown()


    def configure_netvm(self):
        '''
        :type self: qubes.tests.SystemTestCase | VMNetworkingMixin
        '''
        def run_netvm_cmd(cmd):
            try:
                self.loop.run_until_complete(
                    self.testnetvm.run_for_stdio(cmd, user='root'))
            except subprocess.CalledProcessError as e:
                self.fail("Command '%s' failed: %s%s" %
                          (cmd, e.stdout.decode(), e.stderr.decode()))

        if not self.testnetvm.is_running():
            self.loop.run_until_complete(self.testnetvm.start())
        # Ensure that dnsmasq is installed:
        try:
            self.loop.run_until_complete(self.testnetvm.run_for_stdio(
                'dnsmasq --version', user='root'))
        except subprocess.CalledProcessError:
            self.skipTest("dnsmasq not installed")

        run_netvm_cmd("ip link add test0 type dummy")
        run_netvm_cmd("ip link set test0 up")
        run_netvm_cmd("ip addr add {}/24 dev test0".format(self.test_ip))
        run_netvm_cmd("iptables -I INPUT -d {} -j ACCEPT --wait".format(
            self.test_ip))
        # ignore failure
        self.run_cmd(self.testnetvm, "while pkill dnsmasq; do sleep 1; done")
        run_netvm_cmd("dnsmasq -a {ip} -A /{name}/{ip} -i test0 -z".format(
            ip=self.test_ip, name=self.test_name))
        run_netvm_cmd("rm -f /etc/resolv.conf && echo nameserver {} > /etc/resolv.conf".format(
            self.test_ip))
        run_netvm_cmd("systemctl try-restart systemd-resolved || :")
        run_netvm_cmd("/usr/lib/qubes/qubes-setup-dnat-to-ns")


    def test_000_simple_networking(self):
        '''
        :type self: qubes.tests.SystemTestCase | VMNetworkingMixin
        '''
        self.loop.run_until_complete(self.start_vm(self.testvm1))
        self.assertEqual(self.run_cmd(self.testvm1, self.ping_ip), 0)
        self.assertEqual(self.run_cmd(self.testvm1, self.ping_name), 0)


    def test_010_simple_proxyvm(self):
        '''
        :type self: qubes.tests.SystemTestCase | VMNetworkingMixin
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
        self.assertEqual(self.run_cmd(self.proxy, self.ping_ip), 0,
                         "Ping by IP from ProxyVM failed")
        self.assertEqual(self.run_cmd(self.proxy, self.ping_name), 0,
                         "Ping by name from ProxyVM failed")
        self.assertEqual(self.run_cmd(self.testvm1, self.ping_ip), 0,
                         "Ping by IP from AppVM failed")
        self.assertEqual(self.run_cmd(self.testvm1, self.ping_name), 0,
                         "Ping by IP from AppVM failed")


    @qubes.tests.expectedFailureIfTemplate('debian-7')
    @unittest.skipUnless(spawn.find_executable('xdotool'),
                         "xdotool not installed")
    def test_020_simple_proxyvm_nm(self):
        '''
        :type self: qubes.tests.SystemTestCase | VMNetworkingMixin
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
            'xdotool', 'search', '--class', '{}:nm-applet'.format(
                self.proxy.name)],
            stdout=subprocess.DEVNULL), 0, "nm-applet window not found")
        self.assertEqual(self.run_cmd(self.testvm1, self.ping_ip), 0,
                         "Ping by IP failed (after NM reconnection")
        self.assertEqual(self.run_cmd(self.testvm1, self.ping_name), 0,
                         "Ping by name failed (after NM reconnection)")


    def test_030_firewallvm_firewall(self):
        '''
        :type self: qubes.tests.SystemTestCase | VMNetworkingMixin
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
            'socat TCP-LISTEN:1234,fork EXEC:/bin/uname'))

        try:
            self.assertEqual(self.run_cmd(self.proxy, self.ping_ip), 0,
                            "Ping by IP from ProxyVM failed")
            self.assertEqual(self.run_cmd(self.proxy, self.ping_name), 0,
                            "Ping by name from ProxyVM failed")
            self.assertNotEqual(self.run_cmd(self.testvm1, self.ping_ip), 0,
                            "Ping by IP should be blocked")

            client_cmd = "socat TCP:{}:1234 -".format(self.test_ip)
            self.assertNotEqual(self.run_cmd(self.testvm1, client_cmd), 0,
                            "TCP connection should be blocked")

            # block all except ICMP

            self.testvm1.firewall.rules = [(
                qubes.firewall.Rule(None, action='accept', proto='icmp')
            )]
            self.testvm1.firewall.save()
            # Ugly hack b/c there is no feedback when the rules are actually
            # applied
            time.sleep(3)
            self.assertEqual(self.run_cmd(self.testvm1, self.ping_ip), 0,
                            "Ping by IP failed (should be allowed now)")
            self.assertNotEqual(self.run_cmd(self.testvm1, self.ping_name), 0,
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
            self.assertEqual(self.run_cmd(self.testvm1, self.ping_name), 0,
                            "Ping by name failed (should be allowed now)")
            self.assertNotEqual(self.run_cmd(self.testvm1, client_cmd), 0,
                            "TCP connection should be blocked")

            # block all except target

            self.testvm1.firewall.rules = [
                qubes.firewall.Rule(None, action='accept', dsthost=self.test_ip,
                    proto='tcp', dstports=1234),
            ]
            self.testvm1.firewall.save()

            # Ugly hack b/c there is no feedback when the rules are actually
            # applied
            time.sleep(3)
            self.assertEqual(self.run_cmd(self.testvm1, client_cmd), 0,
                            "TCP connection failed (should be allowed now)")

            # allow all except target

            self.testvm1.firewall.rules = [
                qubes.firewall.Rule(None, action='drop', dsthost=self.test_ip,
                    proto='tcp', dstports=1234),
                qubes.firewall.Rule(action='accept'),
            ]
            self.testvm1.firewall.save()

            # Ugly hack b/c there is no feedback when the rules are actually
            # applied
            time.sleep(3)
            self.assertNotEqual(self.run_cmd(self.testvm1, client_cmd), 0,
                            "TCP connection should be blocked")
        finally:
            server.terminate()
            self.loop.run_until_complete(server.wait())


    def test_040_inter_vm(self):
        '''
        :type self: qubes.tests.SystemTestCase | VMNetworkingMixin
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

    def test_050_spoof_ip(self):
        '''Test if VM IP spoofing is blocked

        :type self: qubes.tests.SystemTestCase | VMNetworkingMixin
        '''
        self.loop.run_until_complete(self.start_vm(self.testvm1))

        self.assertEqual(self.run_cmd(self.testvm1, self.ping_ip), 0)
        self.assertEqual(self.run_cmd(self.testnetvm,
            'iptables -I INPUT -i vif+ ! -s {} -p icmp -j LOG'.format(
                self.testvm1.ip)), 0)
        self.loop.run_until_complete(self.testvm1.run_for_stdio(
            'ip addr flush dev eth0 && '
            'ip addr add 10.137.1.128/24 dev eth0 && '
            'ip route add default dev eth0',
            user='root'))
        self.assertNotEqual(self.run_cmd(self.testvm1, self.ping_ip), 0,
                         "Spoofed ping should be blocked")
        try:
            (output, _) = self.loop.run_until_complete(
                self.testnetvm.run_for_stdio('iptables -nxvL INPUT',
                    user='root'))
        except subprocess.CalledProcessError:
            self.fail('iptables -nxvL INPUT failed')

        output = output.decode().splitlines()
        packets = output[2].lstrip().split()[0]
        self.assertEquals(packets, '0', 'Some packet hit the INPUT rule')

    def test_100_late_xldevd_startup(self):
        '''Regression test for #1990

        :type self: qubes.tests.SystemTestCase | VMNetworkingMixin
        '''
        # Simulater late xl devd startup
        cmd = "systemctl stop xendriverdomain"
        if self.run_cmd(self.testnetvm, cmd) != 0:
            self.fail("Command '%s' failed" % cmd)
        self.loop.run_until_complete(self.start_vm(self.testvm1))

        cmd = "systemctl start xendriverdomain"
        if self.run_cmd(self.testnetvm, cmd) != 0:
            self.fail("Command '%s' failed" % cmd)

        # let it initialize the interface(s)
        time.sleep(1)

        self.assertEqual(self.run_cmd(self.testvm1, self.ping_ip), 0)

    def test_110_dynamic_attach(self):
        self.testvm1.netvm = None
        self.loop.run_until_complete(self.start_vm(self.testvm1))
        self.testvm1.netvm = self.testnetvm
        # wait for it to settle down
        self.loop.run_until_complete(self.testvm1.run_for_stdio(
            'udevadm settle'))
        self.assertEqual(self.run_cmd(self.testvm1, self.ping_ip), 0)

    def test_111_dynamic_detach_attach(self):
        self.loop.run_until_complete(self.start_vm(self.testvm1))
        self.testvm1.netvm = None
        # wait for it to settle down
        self.loop.run_until_complete(self.testvm1.run_for_stdio(
            'udevadm settle'))
        self.testvm1.netvm = self.testnetvm
        # wait for it to settle down
        self.loop.run_until_complete(self.testvm1.run_for_stdio(
            'udevadm settle'))
        self.assertEqual(self.run_cmd(self.testvm1, self.ping_ip), 0)

    def test_112_reattach_after_provider_shutdown(self):
        self.proxy = self.app.add_new_vm(qubes.vm.appvm.AppVM,
            name=self.make_vm_name('proxy'),
            label='red')
        self.proxy.provides_network = True
        self.proxy.netvm = self.testnetvm
        self.loop.run_until_complete(self.proxy.create_on_disk())
        self.testvm1.netvm = self.proxy

        self.loop.run_until_complete(self.start_vm(self.testvm1))
        self.loop.run_until_complete(self.proxy.shutdown(force=True, wait=True))
        self.loop.run_until_complete(self.start_vm(self.proxy))
        # wait for it to settle down
        self.loop.run_until_complete(self.wait_for_session(self.proxy))
        self.assertEqual(self.run_cmd(self.testvm1, self.ping_ip), 0)

    def test_113_reattach_after_provider_kill(self):
        self.proxy = self.app.add_new_vm(qubes.vm.appvm.AppVM,
            name=self.make_vm_name('proxy'),
            label='red')
        self.proxy.provides_network = True
        self.proxy.netvm = self.testnetvm
        self.loop.run_until_complete(self.proxy.create_on_disk())
        self.testvm1.netvm = self.proxy

        self.loop.run_until_complete(self.start_vm(self.testvm1))
        self.loop.run_until_complete(self.proxy.kill())
        self.loop.run_until_complete(self.start_vm(self.proxy))
        self.assertEqual(self.run_cmd(self.testvm1, self.ping_ip), 0)

    def test_114_reattach_after_provider_crash(self):
        self.proxy = self.app.add_new_vm(qubes.vm.appvm.AppVM,
            name=self.make_vm_name('proxy'),
            label='red')
        self.proxy.provides_network = True
        self.proxy.netvm = self.testnetvm
        self.loop.run_until_complete(self.proxy.create_on_disk())
        self.testvm1.netvm = self.proxy

        self.loop.run_until_complete(self.start_vm(self.testvm1))
        p = self.loop.run_until_complete(self.proxy.run(
            'echo c > /proc/sysrq-trigger', user='root'))
        self.loop.run_until_complete(p.wait())
        timeout = 10
        while self.proxy.is_running():
            self.loop.run_until_complete(asyncio.sleep(1))
            timeout -= 1
            self.assertGreater(timeout, 0,
                'timeout waiting for crash cleanup')
        self.loop.run_until_complete(self.start_vm(self.proxy))
        self.assertEqual(self.run_cmd(self.testvm1, self.ping_ip), 0)

    def test_200_fake_ip_simple(self):
        '''Test hiding VM real IP

        :type self: qubes.tests.SystemTestCase | VMNetworkingMixin
        '''
        self.testvm1.features['net.fake-ip'] = '192.168.1.128'
        self.testvm1.features['net.fake-gateway'] = '192.168.1.1'
        self.testvm1.features['net.fake-netmask'] = '255.255.255.0'
        self.app.save()
        self.loop.run_until_complete(self.start_vm(self.testvm1))
        self.assertEqual(self.run_cmd(self.testvm1, self.ping_ip), 0)
        self.assertEqual(self.run_cmd(self.testvm1, self.ping_name), 0)

        try:
            (output, _) = self.loop.run_until_complete(
                self.testvm1.run_for_stdio(
                    'ip addr show dev eth0', user='root'))
        except subprocess.CalledProcessError:
            self.fail('ip addr show dev eth0 failed')

        output = output.decode()
        self.assertIn('192.168.1.128', output)
        self.assertNotIn(str(self.testvm1.ip), output)

        try:
            (output, _) = self.loop.run_until_complete(
                self.testvm1.run_for_stdio('ip route show', user='root'))
        except subprocess.CalledProcessError:
            self.fail('ip route show failed')

        output = output.decode()
        self.assertIn('192.168.1.1', output)
        self.assertNotIn(str(self.testvm1.netvm.ip), output)

    def test_201_fake_ip_without_gw(self):
        '''Test hiding VM real IP

        :type self: qubes.tests.SystemTestCase | VMNetworkingMixin
        '''
        self.testvm1.features['net.fake-ip'] = '192.168.1.128'
        self.app.save()
        self.loop.run_until_complete(self.start_vm(self.testvm1))
        self.assertEqual(self.run_cmd(self.testvm1, self.ping_ip), 0)
        self.assertEqual(self.run_cmd(self.testvm1, self.ping_name), 0)

        try:
            (output, _) = self.loop.run_until_complete(
                self.testvm1.run_for_stdio('ip addr show dev eth0',
                    user='root'))
        except subprocess.CalledProcessError:
            self.fail('ip addr show dev eth0 failed')

        output = output.decode()
        self.assertIn('192.168.1.128', output)
        self.assertNotIn(str(self.testvm1.ip), output)

    def test_202_fake_ip_firewall(self):
        '''Test hiding VM real IP, firewall

        :type self: qubes.tests.SystemTestCase | VMNetworkingMixin
        '''
        self.testvm1.features['net.fake-ip'] = '192.168.1.128'
        self.testvm1.features['net.fake-gateway'] = '192.168.1.1'
        self.testvm1.features['net.fake-netmask'] = '255.255.255.0'

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
            'socat TCP-LISTEN:1234,fork EXEC:/bin/uname'))

        try:
            self.assertEqual(self.run_cmd(self.proxy, self.ping_ip), 0,
                            "Ping by IP from ProxyVM failed")
            self.assertEqual(self.run_cmd(self.proxy, self.ping_name), 0,
                            "Ping by name from ProxyVM failed")
            self.assertEqual(self.run_cmd(self.testvm1, self.ping_ip), 0,
                            "Ping by IP should be allowed")
            self.assertEqual(self.run_cmd(self.testvm1, self.ping_name), 0,
                            "Ping by name should be allowed")
            client_cmd = "socat TCP:{}:1234 -".format(self.test_ip)
            self.assertNotEqual(self.run_cmd(self.testvm1, client_cmd), 0,
                            "TCP connection should be blocked")
        finally:
            server.terminate()
            self.loop.run_until_complete(server.wait())

    def test_203_fake_ip_inter_vm_allow(self):
        '''Access VM with "fake IP" from other VM (when firewall allows)

        :type self: qubes.tests.SystemTestCase | VMNetworkingMixin
        '''
        self.proxy = self.app.add_new_vm(qubes.vm.appvm.AppVM,
            name=self.make_vm_name('proxy'),
            label='red')
        self.loop.run_until_complete(self.proxy.create_on_disk())
        self.proxy.provides_network = True
        self.proxy.netvm = self.testnetvm
        self.testvm1.netvm = self.proxy
        self.testvm1.features['net.fake-ip'] = '192.168.1.128'
        self.testvm1.features['net.fake-gateway'] = '192.168.1.1'
        self.testvm1.features['net.fake-netmask'] = '255.255.255.0'

        self.testvm2 = self.app.add_new_vm(qubes.vm.appvm.AppVM,
            name=self.make_vm_name('vm2'),
            label='red')
        self.loop.run_until_complete(self.testvm2.create_on_disk())
        self.testvm2.netvm = self.proxy
        self.app.save()

        self.loop.run_until_complete(self.start_vm(self.testvm1))
        self.loop.run_until_complete(self.start_vm(self.testvm2))

        cmd = 'iptables -I FORWARD -s {} -d {} -j ACCEPT'.format(
            self.testvm2.ip, self.testvm1.ip)
        try:
            self.loop.run_until_complete(self.proxy.run_for_stdio(
                cmd, user='root'))
        except subprocess.CalledProcessError as e:
            raise AssertionError(
                '{} failed with: {}'.format(cmd, e.returncode)) from None

        try:
            cmd = 'iptables -I INPUT -s {} -j ACCEPT'.format(self.testvm2.ip)
            self.loop.run_until_complete(self.testvm1.run_for_stdio(
                cmd, user='root'))
        except subprocess.CalledProcessError as e:
            raise AssertionError(
                '{} failed with: {}'.format(cmd, e.returncode)) from None

        self.assertEqual(self.run_cmd(self.testvm2,
            self.ping_cmd.format(target=self.testvm1.ip)), 0)

        try:
            cmd = 'iptables -nvxL INPUT | grep {}'.format(self.testvm2.ip)
            (stdout, _) = self.loop.run_until_complete(
                self.testvm1.run_for_stdio(cmd, user='root'))
        except subprocess.CalledProcessError as e:
            raise AssertionError(
                '{} failed with {}'.format(cmd, e.returncode)) from None
        self.assertNotEqual(stdout.decode().split()[0], '0',
            'Packets didn\'t managed to the VM')

    def test_204_fake_ip_proxy(self):
        '''Test hiding VM real IP

        :type self: qubes.tests.SystemTestCase | VMNetworkingMixin
        '''
        self.proxy = self.app.add_new_vm(qubes.vm.appvm.AppVM,
            name=self.make_vm_name('proxy'),
            label='red')
        self.loop.run_until_complete(self.proxy.create_on_disk())
        self.proxy.provides_network = True
        self.proxy.netvm = self.testnetvm
        self.proxy.features['net.fake-ip'] = '192.168.1.128'
        self.proxy.features['net.fake-gateway'] = '192.168.1.1'
        self.proxy.features['net.fake-netmask'] = '255.255.255.0'
        self.testvm1.netvm = self.proxy
        self.app.save()
        self.loop.run_until_complete(self.start_vm(self.testvm1))

        self.assertEqual(self.run_cmd(self.proxy, self.ping_ip), 0)
        self.assertEqual(self.run_cmd(self.proxy, self.ping_name), 0)

        self.assertEqual(self.run_cmd(self.testvm1, self.ping_ip), 0)
        self.assertEqual(self.run_cmd(self.testvm1, self.ping_name), 0)

        try:
            (output, _) = self.loop.run_until_complete(
                self.proxy.run_for_stdio(
                    'ip addr show dev eth0', user='root'))
        except subprocess.CalledProcessError:
            self.fail('ip addr show dev eth0 failed')
        output = output.decode()
        self.assertIn('192.168.1.128', output)
        self.assertNotIn(str(self.testvm1.ip), output)

        try:
            (output, _) = self.loop.run_until_complete(
                self.proxy.run_for_stdio(
                    'ip route show', user='root'))
        except subprocess.CalledProcessError:
            self.fail('ip route show failed')
        output = output.decode()
        self.assertIn('192.168.1.1', output)
        self.assertNotIn(str(self.testvm1.netvm.ip), output)

        try:
            (output, _) = self.loop.run_until_complete(
                self.testvm1.run_for_stdio(
                    'ip addr show dev eth0', user='root'))
        except subprocess.CalledProcessError:
            self.fail('ip addr show dev eth0 failed')
        output = output.decode()
        self.assertNotIn('192.168.1.128', output)
        self.assertIn(str(self.testvm1.ip), output)

        try:
            (output, _) = self.loop.run_until_complete(
                self.testvm1.run_for_stdio(
                    'ip route show', user='root'))
        except subprocess.CalledProcessError:
            self.fail('ip route show failed')
        output = output.decode()
        self.assertIn('192.168.1.128', output)
        self.assertNotIn(str(self.proxy.ip), output)

    def test_210_custom_ip_simple(self):
        '''Custom AppVM IP

        :type self: qubes.tests.SystemTestCase | VMNetworkingMixin
        '''
        self.testvm1.ip = '192.168.1.1'
        self.app.save()
        self.loop.run_until_complete(self.start_vm(self.testvm1))
        self.assertEqual(self.run_cmd(self.testvm1, self.ping_ip), 0)
        self.assertEqual(self.run_cmd(self.testvm1, self.ping_name), 0)

    def test_211_custom_ip_proxy(self):
        '''Custom ProxyVM IP

        :type self: qubes.tests.SystemTestCase | VMNetworkingMixin
        '''
        self.proxy = self.app.add_new_vm(qubes.vm.appvm.AppVM,
            name=self.make_vm_name('proxy'),
            label='red')
        self.loop.run_until_complete(self.proxy.create_on_disk())
        self.proxy.provides_network = True
        self.proxy.netvm = self.testnetvm
        self.proxy.ip = '192.168.1.1'
        self.testvm1.netvm = self.proxy
        self.app.save()

        self.loop.run_until_complete(self.start_vm(self.testvm1))

        self.assertEqual(self.run_cmd(self.testvm1, self.ping_ip), 0)
        self.assertEqual(self.run_cmd(self.testvm1, self.ping_name), 0)

    def test_212_custom_ip_firewall(self):
        '''Custom VM IP and firewall

        :type self: qubes.tests.SystemTestCase | VMNetworkingMixin
        '''
        self.testvm1.ip = '192.168.1.1'

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
            'socat TCP-LISTEN:1234,fork EXEC:/bin/uname'))

        try:
            self.assertEqual(self.run_cmd(self.proxy, self.ping_ip), 0,
                            "Ping by IP from ProxyVM failed")
            self.assertEqual(self.run_cmd(self.proxy, self.ping_name), 0,
                            "Ping by name from ProxyVM failed")
            self.assertEqual(self.run_cmd(self.testvm1, self.ping_ip), 0,
                            "Ping by IP should be allowed")
            self.assertEqual(self.run_cmd(self.testvm1, self.ping_name), 0,
                            "Ping by name should be allowed")
            client_cmd = "socat TCP:{}:1234 -".format(self.test_ip)
            self.assertNotEqual(self.run_cmd(self.testvm1, client_cmd), 0,
                            "TCP connection should be blocked")
        finally:
            server.terminate()
            self.loop.run_until_complete(server.wait())



def create_testcases_for_templates():
    yield from qubes.tests.create_testcases_for_templates('VmNetworking',
        VmNetworkingMixin, qubes.tests.SystemTestCase,
        module=sys.modules[__name__])

def load_tests(loader, tests, pattern):
    tests.addTests(loader.loadTestsFromNames(
        create_testcases_for_templates()))
    return tests

qubes.tests.maybe_create_testcases_on_import(create_testcases_for_templates)
