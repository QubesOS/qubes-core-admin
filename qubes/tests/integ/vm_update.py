#
# The Qubes OS Project, https://www.qubes-os.org/
#
# Copyright (C) 2022 Piotr Bartman <prbartman@invisiblethingslab.com>
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
import contextlib
import os
import shutil
import subprocess
import sys
import tempfile

import qubes.vm


# noinspection PyAttributeOutsideInit,PyPep8Naming
class VmUpdatesMixin(object):
    """
    Tests for VM updates
    """

    # filled by load_tests
    template = None

    # made this way to work also when no package build tools are installed
    """
    $ cat test-pkg.spec:
    Name:		test-pkg
    Version:	1.0
    Release:	1%{?dist}
    Summary:	Test package

    Group:		System
    License:	GPL
    URL:		http://example.com/

    %description
    Test package

    %files

    %changelog
    $ rpmbuild -bb test-pkg.spec
    $ cat test-pkg-1.0-1.fc41.x86_64.rpm | gzip | base64
    $ cat test-pkg-1.1-1.fc41.x86_64.rpm | gzip | base64
    """
    RPM_PACKAGE_GZIP_BASE64 = [
        (
            b"H4sIAAAAAAAAA+2YW4scRRTHazKbZDWIK4pXAit5cAOpma7u6ulucbxkJ9kEQnbN5qrgUl"
            b"1VPdOmp7vp7jG7ElCCj0EEP4AvPghBQVAQ9MEHNQE/goh4g0RNog9KEJP19PRZNxt8MK/S"
            b"f6a76nfOqVOXrdmBc/ncla+aBNQodF7Q9GSfspYBTyA5I7epBtl8q+n1dy82sLuVkKkPoH"
            b"0S+29DOwWD7oJ2yz8ZSOMe5J0VNy9COwFPhPxLNZ6k1fjmVfS/iv5f0f8auKdFh/GAeYob"
            b"hun4piE9Q7kdbnBLKW7ahnB44NvMJY6yZCBt33J937IcpbRhMea7gbY9w7OUVNLUqsM0V6"
            b"7NNLMYNz1HO8I0mHIhQakt+vOvv3vlkx458w39fe5seO49MJ6+3WOsVatWrVq1atWqVatW"
            b"rVq1av0vNa6JrK6uvkHGNY0NdZNHCZl4CNqnyLiuMXEHxih4JjFmrU5S1k02IV9C3ob8E/"
            b"LdZL2OUua6H/ky8g7kK6SqqxjIV3E8R/4N/U8j/4H+HvI1zLcP+S/0zyNfR5bIN5DDiifu"
            b"Q06RH8D9nq32OPEgzv9O1Y7PqPR/hPxwxY3tyDNVvsYTmO94ZW/0MN8JjD+A7GO8j/Gq4u"
            b"azyBr5KHKA/DxyhPxCxfe+Wc3XXEb+Av2nkX+o5m+eQf4R4z9DvoT+CyXPkrV6HWEtg2C9"
            b"7jDYplMhT4q+3giD871HokSKaJDkBV6auYUDZHElL/SQDIoifbzd1stimEa6JZNhm0RhPF"
            b"omy25nqcPJv1QHW3kmW1k6XF/JWmcGBtEOxwLenTc/EB+F/sxsMkwzneda7Q0jfVAMdb6T"
            b"oK+09MI+5Fq3LYiVKBHj4HyfeEkvZDoIl29178+fywu1k1gto8UpI7zVKVcLbfm2W7zF3D"
            b"GaRqsqbpb3ZfKmgudNXTpvTtMgKpKuGBUJdANRUECa+C9qWeRg0ctSp0WYxAB9+GRaJpmi"
            b"fSlpfios5ECDIw1TPU2PiSiCd5xQONs0EmFMT2VJ3KeRiGHoMZ1lSdYNkmwIs+RajrKwWA"
            b"F7uoseWdo7f+jw/r0nlhbnjxya3bOL9m6xdK0qsrc0d2D/7tnjx5eeWVzcAxHzBxenaZ5q"
            b"mXfbozxrw1m14cjamVYDUWBDByJTOtaKSslgV3kBd4amWVLANpOM5kW50P+QR8Rx4sPGyj"
            b"TTdNjh8BKZHHSr6wBUjGLd7cNcWShhJpGvxHIA2ZNRTkfxqTBWtBB+VB4bLkNGIh+sLQZO"
            b"Ghwy2MDDIsqpCkUEhm4/HpV/NTjmZBgWNMjgZtE0CeNCZxC6Zo+0CDY6iUzDhLwM14cwDy"
            b"89xX2NvwgUUldfm8lREVCXCG5IR3EuTZebHY+JwPNs6bvcZaLjOqyjlGX7pul6zLNsRzs6"
            b"sB3uBQYzuGfYqsplWsrgpunzQAvTDRyHadcxHc5833IMxzN8SyrDtlxYsc87zLQs7ZoGTO"
            b"PbjjDL/0HVD8Pq6vWy8D0182H7Ohlsb5BNu7ds+/Tnj78ffjv15+bGl8NtZO5ofm31rfPv"
            b"79q6iTQfu0F2/A2I5aoB/RcAAA=="
        ),
        (
            b"H4sIAAAAAAAAA+2Yz4scRRTHazKbHxrEVYO/ILCSQ3YhNdNdXf1LnKjZTTaBkF2z+angUl"
            b"1dNdOmp7vp7jG7EkHEo4jgH+DFgyA5CAoBETyIEfwP9KKokEST6EWCmKyvp9+abPBgrtJf"
            b"prvq896rVz+2Zgfe1Y+ufdcmoFapipJmZ/rU7JjwaMlNco9qkc13m945f6mF3a2ETH4C7V"
            b"7sfwDtJAx6ANot/2QgrYeQZ2puX4J2Ap4Y+dd6PMnq8e3r6H8D/b+h/y1wTwWWYfuMC+3a"
            b"knOL+SqwVKC151vMsUMtHcNzLC2JNFzhO4bwueKG9pkMPS2V67i2zYwwUEy6Skht8kAFpq"
            b"e070jOmBJMM2WzwBovf4vy5xdf//78t+aVC5/vePjo3nkwnrvXY2zUqFGjRo0aNWrUqFGj"
            b"Ro0a/S81romsra29S8Y1jQ11k6cImXgC2mfJuK4xcR/GhPBsw5j1OklVN9mEfBl5O/IV5A"
            b"fJ7TpKletR5KvIu5CvkbquYiBfx/Ec+Xf0P4f8B/rnkG9gvoPIf6F/AfkmskS+hRzVPLED"
            b"OUN+DPf7dr3Hicdx/g/rdnxGlf8C8pM1t3YiT9f5Ws9gvlO1vTWH+U5j/GHkAOMDjA9rbr"
            b"+ArJBPIGvkl5Bj5JdrfuS9er72CvJX6D+H/FM9f/tN5J8x/kvky+j/uuJZsl6vI2bHJFiv"
            b"Owa2qUzIM6KvNsLg4tzuOJUiHqRFiZdmfvEwWVotSjUkg7LMnu521YoYZrHqyHTYJXGUjF"
            b"bIiucsO5z8S3WwU+Syk2fD2ytZ70zDIOpwLODdf+cD8XEUTM+mwyxXRaHCA1GsjoihKmYI"
            b"+irLXNSHXLdti2I1TsU4uDgoXlWLudLRyt3uQ8WLRRnOEKtjdDg1Ce84HWPcVm+7wzumN0"
            b"ZmdOriZnVftt1R8LyjSxfYFNVxmfbEqEyhq0VJAWkavKJkWYBFrUiVlVGaAPThkyuZ5iHt"
            b"S0mLs1EpBwocWZSpKXpSxDG8k5TC2WaxiBJ6Nk+TPo1FAkNPqjxP855O8yHMUig5yqNyFe"
            b"zZHnp8+cDC0WOHDpxeXlo4fnR2/x46d5elZ9WRc8vzhw/tmz11avn5paX9ELFwZGmKFpmS"
            b"Ra87KvIunFUXjqybq3AgSmzoQOShSlRIpTRhV0UJd4ZmeVrCNtOcFmW10P+QRyRJGsDGqj"
            b"RTdOhweIlcDnr1dQAqR4nq9WGuPJIwkyhWEzmA7OmooKPkbJSEtBRBXB0bLkPGohisLwZO"
            b"GhxSb+BhGRc0jEQMhl4/GVV/NTjmdBiVVOdws2iWRkmpcghdt8dK6I1OIrMoJa/B9SGmj5"
            b"ee4r7GXwQKqeuvzbZRqalHBDekG3IumceZ45tC+74tA497pnA813TC0LIDxjzf9C3bVa7S"
            b"tst9bZgG9w07rHMxKzQ4YwHXSjBPu66pPJe53AwCyzVc3wgsGRq25cGKA+6YzLKUxwyYJr"
            b"Bdwar/QfUPw9razarwPTn9afcmGexskU37tmz/4pfPfhz+MPnn5tY3w+1k/kRxY+39ix/v"
            b"2bqJtHffIrv+BlvCAWX9FwAA"
        ),
    ]

    """
    Minimal package generated by running dh_make on empty directory
    Then cat test-pkg_1.0-1_amd64.deb | gzip | base64
    Then cat test-pkg_1.1-1_amd64.deb | gzip | base64
    """
    DEB_PACKAGE_GZIP_BASE64 = [
        (
            b"H4sIACTXLlYAA1O0SSxKzrDjSklNykzM003KzEssqlRQUDA0MTG1NDQwNDVTUDBQAAEIa"
            b"WhgYGZioqBgogADCVxGegZcyfl5JUX5OXoliUV66VVE6DcwheuX7+ZgAAEW5rdXHb0PG4"
            b"iwf5j3WfMT6zWzzMuZgoE3jjYraNzbbFKWGms0SaRw/r2SV23WZ4IdP8preM4yqf0jt95"
            b"3c8qnacfNxJUkf9/w+/3X9ph2GEdgQdixrz/niHKKTnYXizf4oSC7tHOz2Zzq+/6vn8/7"
            b"ezQ7c1tmi7xZ3SGJ4yzhT2dcr7V+W3zM5ZPu/56PSv4Zdok+7Yv/V/6buWaKVlFkkV58S"
            b"N3GmLgnqzRmeZ3V3ymmurS5fGa85/LNx1bpZMin3S6dvXKqydp3ubP1vmyarJZb/qSh62"
            b"C8oIdxqm/BtvkGDza+On/Vfv2py7/0LV7VH+qR6a+bkKUbHXt5/SG187d+nps1a5PJfMO"
            b"i11dWcUe1HjwaW3Q5RHXn9LmcHy+tW9YcKf0768XVB1t3R0bKrzs5t9P+6r7rZ99svH10"
            b"+Q6F/o8tf1fO/32y+fWa14eifd+WxUy0jcxYH7N9/tUvmnUZL74pW32qLeuRU+ZwYGASa"
            b"GBgUWBgxM90ayy3VdmykkGDgYErJbEkERydFVWQmCMQo8aWZvAY/WteFRHFwMCYqXTPjI"
            b"lBkVEMGLsl+k8XP1D/z+gXyyDOvUemlnHqAVkvu0rRQ2fUFodkN3mtU9uwhqk8V+TqPEE"
            b"Nc7fzoQ4n71lqRs/7kbbT0+qOZuKH4r8mjzsc1k/YkCHN8Pjg48fbpE+teHa96LNcfu0V"
            b"5n2/Z2xa2KDvaCOx8cqBFxc514uZ3TmadXS+6cpzU7wSzq5SWfapJOD9n6wLXSwtlgxZh"
            b"xITzWW7buhx/bb291RcVlEfeC9K5hlrqunSzIMSZT7/Nqgc/qMvMNW227WI8ezB8mVuZh"
            b"0hERJSvysfburr4Dx0I9BW57UwR4+e1gxu49PcEt8sbK18Xpvt//Hj5UYm+Zc25q+T4xl"
            b"rJvxfVnh80oadq57OZxPaU1bbztv1yF365W4t45Yr+XrFzov237GVY1Zgf7NvE4+W2SuR"
            b"lQtLauR1TQ/mbOiIONYya6tU1jPGpWfk/i1+ttiXe3ZO14n0YOWggndznjGlGLyfVbBC6"
            b"MRP5aMM7aCco/s7sZqB8RlTQwADw8rnuT/sDHi7mUASjJFRAAbWwNLiAwAA"
        ),
        (
            b"H4sIAL05B1wCA1O0SSxKzrDjSklNykzM003KzEssqlRQUDA0NTG2NDc3NjdTUDBQAAEIa"
            b"WhgYGZioqBgogADCVxGegZcyfl5JUX5OXoliUV66VVE6De3gOuX7+ZgAAEW5rdXzmbdMR"
            b"BgSJj/VeQzQ+ztT/W+EVEnFraKOTlXh6+JXB8RbTRpzgWb2qdLX0+RmTRZcYlyxJutJsk"
            b"/pfsfq9yqWZJ4JVVS97jBPPnz1yviluw51b0q4tnrWemCU2a/17mTUBYX0XBC6nH8rvvZ"
            b"n/WP7nu40+Jlz7drPNLvCjULQkXOv677OV9s4bPsv5+tvCzPG8s57no479qV/5V/813Kh"
            b"Wy3Pbj4827Jq5v6W/wk7zL1/+zbfH6btVb/3Pm5EapukaJvdgfcape/JZZWe+mZ4+Grby"
            b"7UTaroPzyv9urC1W2MT9+F2bZtWJOyXfGo5dv7DGXJUzee+p930Od0j8QNceNHJffOTr2"
            b"kOJe93mWG+nPdLsG6fz++MV5h1OGr0N9yf3N2ydzQ5x/E9Aw/s9xzmOpULnKtsSZqc/rr"
            b"RQdf/Lu/ckKE9xU5VRuNehbzTr6789a+P2lt2zk5cFqe3N2289+j/hfH2X39/+nvc5vTW"
            b"a/+83pvWqY3e93JWYsmup693HzCOPBk0LI9O7PtiqawN9y8eaTV75DLLL2dNWqTLsTsOn"
            b"7wy0fTe5oLH//7eNf89Co3dRUHJmLRh20s/xhYJkoeYdBgYEhJLEkEJ4uKKkgKIJQyjI3"
            b"gKeOveVVEFAMDY6bSPTMmBkVGMWAqKdF/uviB+n/GwlgGce49MrWMUw/IetlVih46o7Y4"
            b"0uZe/t9lt85aMUrdWhjueTHRd1nr1uK830feH74vcPKU2pkbP4SZnta5PhC9dfPTqvv7f"
            b"n068XRDRDzLuv8Oa5p1L+02ZN127vp6mzSzzFqpLkmbwyl131J1xW58YlcxXSWs0PTbpT"
            b"z28ZUnE/e+NN93weAd40a/zzJ7+Re/v+R7+f3VBVFJCyZsv523ySJ12t7Nt5b8uBu8zuJ"
            b"2Laer//nZCkbXlxtYXvvA8+VSVsCRpo8BawtftKWyZBjkWa6/0X7qXfbF9reH/ro6S63Y"
            b"rCj8t8cltPIOj9H/8LyIxj6bMsZVVtu+ngj6MCNV5JXhOs07RXWxrb3xsqJMDRksx/5bO"
            b"bNtevXz2cdpzzI19Roede4NXxAyK9Dlrtp8JtELLNPWbBe9HfJlj1Hiv69erIFBnX/Pe1"
            b"4QnzLD+p2AiTc383/P+7sW3WoxnXra49iJKJeZy7gc9Z02S57qrvWW3day501VhsbPtfK"
            b"C5nyBG9qjr08E59KY1vUTGRg7mRsCGBimFa+3sTPg7WYCSTBGRgEAzEOeH04EAAA="
        ),
    ]

    ARCH_PACKAGE = [
        (
            b"pkgname=test-pkg\n"
            b"pkgver=1.0\n"
            b"pkgrel=1\n"
            b"arch=(any)\n"
            b'options=("!debug")\n'
        ),
        (
            b"pkgname=test-pkg\n"
            b"pkgver=1.1\n"
            b"pkgrel=1\n"
            b"arch=(any)\n"
            b'options=("!debug")\n'
        ),
    ]

    @classmethod
    def setUpClass(cls):
        super(VmUpdatesMixin, cls).setUpClass()
        cls.tmpdir = tempfile.mkdtemp()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmpdir)

    def run_cmd(self, vm, cmd, user="root"):
        """
        Run a command *cmd* in a *vm* as *user*. Return its return code.

        :type self: qubes.tests.SystemTestCase | VmUpdatesMixin
        :param qubes.vm.qubesvm.QubesVM vm: VM object to run command in
        :param str cmd: command to execute
        :param std user: user to execute command as
        :return int: command return code
        """
        try:
            self.loop.run_until_complete(vm.run_for_stdio(cmd))
        except subprocess.CalledProcessError as e:
            return e.returncode
        return 0

    def assertRunCommandReturnCode(self, vm, cmd, expected_returncode):
        p = self.loop.run_until_complete(
            vm.run(
                cmd, user="root", stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
        )
        (stdout, stderr) = self.loop.run_until_complete(p.communicate())
        self.assertIn(
            self.loop.run_until_complete(p.wait()),
            expected_returncode,
            "{}: {}\n{}".format(cmd, stdout, stderr),
        )

    def setUp(self):
        """
        :type self: qubes.tests.SystemTestCase | VmUpdatesMixin
        """
        if (
            not self.template.count("debian")
            and not self.template.count("fedora")
            and not self.template.count("archlinux")
        ):
            self.skipTest(
                "Template {} not supported by this test".format(self.template)
            )
        super(VmUpdatesMixin, self).setUp()

        self.update_cmd = None
        if self.template.count("debian"):
            self.update_cmd = (
                "set -o pipefail; apt-get update 2>&1 | "
                r"{ ! grep '^W:\|^E:'; }"
            )
            self.upgrade_cmd = "apt-get -V dist-upgrade -y"
            self.install_cmd = "apt-get install -y {}"
            self.install_test_cmd = "dpkg -l {}"
            self.upgrade_test_cmd = "dpkg -l {} | grep 1.1"
            self.ret_code_ok = [0]
        elif self.template.count("fedora"):
            cmd = "yum"
            try:
                # assume template name in form "fedora-XX-suffix"
                if int(self.template.split("-")[1]) > 21:
                    cmd = "dnf"
            except ValueError:
                pass
            self.update_cmd = "{cmd} clean all; {cmd} check-update".format(
                cmd=cmd
            )
            self.upgrade_cmd = "{cmd} upgrade -y".format(cmd=cmd)
            self.install_cmd = cmd + " install -y {}"
            self.install_test_cmd = "rpm -q {}"
            self.upgrade_test_cmd = "rpm -q {} | grep 1.1"
            self.ret_code_ok = [0, 100]
        elif self.template.count("archlinux"):
            self.update_cmd = "pacman -Syy"
            self.upgrade_cmd = "pacman -Syu --noconfirm"
            self.install_cmd = "pacman -Sy --noconfirm {}"
            self.install_test_cmd = "pacman -Q {}"
            self.upgrade_test_cmd = "pacman -Q {} | grep 1.1"
            self.ret_code_ok = [0]

        self.init_default_template(self.template)
        self.init_networking()
        self.testvm1 = self.app.add_new_vm(
            qubes.vm.appvm.AppVM, name=self.make_vm_name("vm1"), label="red"
        )
        self.loop.run_until_complete(self.testvm1.create_on_disk())
        self.repo_proc = None

        # template used for repo-hosting vm
        self.repo_template = self.app.default_template
        if self.template.count("minimal"):
            self.repo_template = self.host_app.default_template
            print(
                f"Using {self.repo_template!s} for repo hosting vm when "
                f"testing minimal template"
            )

    def tearDown(self):
        if self.repo_proc:
            self.repo_proc.terminate()
            self.loop.run_until_complete(self.repo_proc.wait())
        super().tearDown()

    def test_000_simple_update(self):
        """
        Just update repo.

        :type self: qubes.tests.SystemTestCase | VmUpdatesMixin
        """
        if self.template.count("minimal"):
            self.skipTest(
                "Template {} not supported by this test".format(self.template)
            )
        self.app.save()
        self.testvm1 = self.app.domains[self.testvm1.qid]
        self.loop.run_until_complete(self.testvm1.start())
        self.assertRunCommandReturnCode(
            self.testvm1, self.update_cmd, self.ret_code_ok
        )

    def create_repo_apt(self, version=0):
        """
        :type self: qubes.tests.SystemTestCase | VmUpdatesMixin
        :type version: int
        """
        pkg_file_name = "test-pkg_1.{}-1_amd64.deb".format(version)
        self.loop.run_until_complete(
            self.netvm_repo.run_for_stdio(
                """
            mkdir -p /tmp/apt-repo \
            && cd /tmp/apt-repo \
            && base64 -d | zcat > {}
            """.format(
                    pkg_file_name
                ),
                input=self.DEB_PACKAGE_GZIP_BASE64[version],
            )
        )
        # do not assume dpkg-scanpackage installed
        packages_path = "dists/test/main/binary-amd64/Packages"
        self.loop.run_until_complete(
            self.netvm_repo.run_for_stdio(
                """
            mkdir -p /tmp/apt-repo/dists/test/main/binary-amd64 \
            && cd /tmp/apt-repo \
            && cat > {packages} \
            && echo MD5sum: $(openssl md5 -r {pkg} | cut -f 1 -d ' ') \
                >> {packages} \
            && echo SHA1: $(openssl sha1 -r {pkg} | cut -f 1 -d ' ') \
                >> {packages} \
            && echo SHA256: $(openssl sha256 -r {pkg} | cut -f 1 -d ' ') \
                >> {packages} \
            && sed -i -e "s,@SIZE@,$(stat -c %s {pkg})," {packages} \
            && gzip < {packages} > {packages}.gz
            """.format(
                    pkg=pkg_file_name, packages=packages_path
                ),
                input="""\
Package: test-pkg
Version: 1.{version}-1
Architecture: amd64
Maintainer: unknown <user@host>
Installed-Size: 25
Filename: {pkg}
Size: @SIZE@
Section: unknown
Priority: optional
Description: Test package""".format(
                    pkg=pkg_file_name, version=version
                ).encode(
                    "utf-8"
                ),
            )
        )

        self.loop.run_until_complete(
            self.netvm_repo.run_for_stdio(
                """
            mkdir -p /tmp/apt-repo/dists/test \
            && cd /tmp/apt-repo/dists/test \
            && cat > Release \
            && echo '' $(sha256sum {p} | cut -f 1 -d ' ') $(stat -c %s {p}) {p}\
                >> Release \
            && echo '' $(sha256sum {z} | cut -f 1 -d ' ') $(stat -c %s {z}) {z}\
                >> Release
            """.format(
                    p="main/binary-amd64/Packages",
                    z="main/binary-amd64/Packages.gz",
                ),
                input=b"""\
Label: Test repo
Suite: test
Codename: test
Date: Tue, 27 Oct 2015 03:22:09 UTC
Architectures: amd64
Components: main
SHA256:
""",
            )
        )

    def create_repo_yum(self, version=0):
        """
        :type self: qubes.tests.SystemTestCase | VmUpdatesMixin
        :type version: int
        """
        pkg_file_name = "test-pkg-1.{}-1.fc41.x86_64.rpm".format(version)
        self.loop.run_until_complete(
            self.netvm_repo.run_for_stdio(
                """
            mkdir -p /tmp/yum-repo \
            && cd /tmp/yum-repo \
            && base64 -d | zcat > {}
            """.format(
                    pkg_file_name
                ),
                input=self.RPM_PACKAGE_GZIP_BASE64[version],
            )
        )

        # createrepo is installed by default in Fedora template
        self.loop.run_until_complete(
            self.netvm_repo.run_for_stdio("createrepo_c /tmp/yum-repo")
        )

    def create_repo_arch(self, version=0):
        """
        :type self: qubes.tests.SystemTestCase | VmUpdatesMixin
        :type version: int
        """
        self.loop.run_until_complete(
            self.netvm_repo.run_for_stdio(
                """mkdir -p /tmp/pkg \
                && cd /tmp/pkg \
                && cat > PKGBUILD \
                && makepkg""",
                input=self.ARCH_PACKAGE[version],
            )
        )
        pkg_file_name = "test-pkg-1.{}-1-any.pkg.tar.zst".format(version)
        self.loop.run_until_complete(
            self.netvm_repo.run_for_stdio(
                """
            mkdir -p /tmp/arch-repo \
            && cd /tmp/arch-repo \
            && cp /tmp/pkg/{0} ./ \
            && repo-add ./testrepo.db.tar.zst {0}
            """.format(
                    pkg_file_name
                ),
            )
        )

    def create_repo_and_serve(self):
        """
        :type self: qubes.tests.SystemTestCase | VmUpdatesMixin
        """
        if self.template.count("debian") or self.template.count("whonix"):
            self.create_repo_apt()
            self.repo_proc = self.loop.run_until_complete(
                self.netvm_repo.run(
                    "cd /tmp/apt-repo && python3 -m http.server 8080",
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            )
        elif self.template.count("fedora"):
            self.create_repo_yum()
            self.repo_proc = self.loop.run_until_complete(
                self.netvm_repo.run(
                    "cd /tmp/yum-repo && python3 -m http.server 8080",
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            )
        elif self.template.count("archlinux"):
            self.create_repo_arch()
            self.repo_proc = self.loop.run_until_complete(
                self.netvm_repo.run(
                    "cd /tmp/arch-repo && python3 -m http.server 8080",
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            )
        else:
            # not reachable...
            self.skipTest(
                "Template {} not supported by this test".format(self.template)
            )

        # wait for the repo to become reachable
        self.loop.run_until_complete(
            self.netvm_repo.run_for_stdio(
                "while ! curl http://localhost:8080/ >/dev/null; do sleep 0.5; done"
            )
        )

    def add_update_to_repo(self):
        """
        :type self: qubes.tests.SystemTestCase | VmUpdatesMixin
        """
        if self.template.count("debian") or self.template.count("whonix"):
            self.create_repo_apt(1)
        elif self.template.count("fedora"):
            self.create_repo_yum(1)
        elif self.template.count("archlinux"):
            self.create_repo_arch(1)

    def configure_test_repo(self):
        """
        Configure test repository in test-vm and disable rest of them.
        The critical part is to use "localhost" - this will work only when
        accessed through update proxy and this is exactly what we want to
        test here.

        :type self: qubes.tests.SystemTestCase | VmUpdatesMixin
        """

        if self.template.count("debian") or self.template.count("whonix"):
            self.loop.run_until_complete(
                self.testvm1.run_for_stdio(
                    "rm -f /etc/apt/sources.list.d/* &&"
                    "echo 'deb [trusted=yes] http://localhost:8080 test main' "
                    "> /etc/apt/sources.list",
                    user="root",
                )
            )
        elif self.template.count("fedora"):
            self.loop.run_until_complete(
                self.testvm1.run_for_stdio(
                    "rm -f /etc/yum.repos.d/*.repo &&"
                    "echo '[test]' > /etc/yum.repos.d/test.repo &&"
                    "echo 'name=Test repo' >> /etc/yum.repos.d/test.repo &&"
                    "echo 'gpgcheck=0' >> /etc/yum.repos.d/test.repo &&"
                    "echo 'baseurl=http://localhost:8080/'"
                    " >> /etc/yum.repos.d/test.repo",
                    user="root",
                )
            )
        elif self.template.count("archlinux"):
            self.loop.run_until_complete(
                self.testvm1.run_for_stdio(
                    "rm -f /etc/pacman.d/*.conf &&"
                    "echo '[testrepo]' > /etc/pacman.d/70-test.conf &&"
                    "echo 'SigLevel = Optional TrustAll'"
                    " >> /etc/pacman.d/70-test.conf &&"
                    "echo 'Server = http://localhost:8080/'"
                    " >> /etc/pacman.d/70-test.conf",
                    user="root",
                )
            )
        else:
            # not reachable...
            self.skipTest(
                "Template {} not supported by this test".format(self.template)
            )

    def start_vm_with_proxy_repo(self):
        """
        Create proxy VM and start test and proxy VMs with configured repo.

        :type self: qubes.tests.SystemTestCase | VmUpdatesMixin
        """
        self.netvm_repo = self.app.add_new_vm(
            qubes.vm.appvm.AppVM,
            name=self.make_vm_name("net"),
            label="red",
            template=self.repo_template,
        )
        self.netvm_repo.provides_network = True
        self.loop.run_until_complete(self.netvm_repo.create_on_disk())
        self.testvm1.netvm = None  # netvm is unnecessary
        self.netvm_repo.features["service.qubes-updates-proxy"] = True
        # TODO: consider also adding a test for the template itself
        self.testvm1.features["service.updates-proxy-setup"] = True
        self.app.save()

        # Setup test repo
        self.loop.run_until_complete(self.netvm_repo.start())
        self.create_repo_and_serve()

        # Configure local repo
        self.loop.run_until_complete(self.testvm1.start())
        self.configure_test_repo()

    def start_standalone_vm_with_repo(self):
        """
        Override test VM with StandaloneVM and start it with configured repo.

        :type self: qubes.tests.SystemTestCase | VmUpdatesMixin
        """
        self.testvm1 = self.app.add_new_vm(
            qubes.vm.standalonevm.StandaloneVM,
            name=self.make_vm_name("vm2"),
            label="red",
        )
        tpl = self.app.domains[self.template]
        self.testvm1.clone_properties(tpl)
        self.testvm1.features.update(tpl.features)
        self.loop.run_until_complete(self.testvm1.clone_disk_files(tpl))
        self.loop.run_until_complete(self.testvm1.start())
        self.netvm_repo = self.testvm1

        self.create_repo_and_serve()
        self.configure_test_repo()

    def install_test_package(self):
        """
        Update repo and install test package.

        :type self: qubes.tests.SystemTestCase | VmUpdatesMixin
        """
        # update repository metadata
        self.assertRunCommandReturnCode(
            self.testvm1, self.update_cmd, self.ret_code_ok
        )

        # install test package
        self.assertRunCommandReturnCode(
            self.testvm1, self.install_cmd.format("test-pkg"), self.ret_code_ok
        )

    def run_qubes_vm_update_and_assert(self, *, expected_ret_codes, options):
        """
        Run qubes-vm-update at dom0 and assert that return code as expected.

        :type self: qubes.tests.SystemTestCase | VmUpdatesMixin
        :type expected_ret_codes: int, tuple
        :type options: tuple
        """
        try:
            iter(expected_ret_codes)
        except TypeError:
            expected_ret_codes = (expected_ret_codes,)
        logpath = os.path.join(self.tmpdir, "vm-update-output.txt")
        with open(logpath, "w") as f_log:
            proc = self.loop.run_until_complete(
                asyncio.create_subprocess_exec(
                    "qubes-vm-update",
                    "--targets",
                    self.testvm1.name,
                    "--force-update",
                    *options,
                    stdout=f_log,
                    stderr=subprocess.STDOUT,
                )
            )
        self.loop.run_until_complete(proc.wait())
        if proc.returncode not in expected_ret_codes:
            with open(logpath) as f_log:
                self.fail(
                    "qubes-vm-update return unexpected code: "
                    f"{proc.returncode} in {expected_ret_codes}\n"
                    + f_log.read()
                )
        del proc

    def turn_off_repo(self):
        """
        Kill python process.

        :type self: qubes.tests.SystemTestCase | VmUpdatesMixin
        """
        self.loop.run_until_complete(
            self.netvm_repo.run_for_stdio(
                r"kill -9 `ps -ef | grep [h]ttp.server | awk '{print $2}'`",
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        )
        self.loop.run_until_complete(self.repo_proc.wait())
        self.repo_proc = None

    def update_via_proxy_qubes_vm_update_impl(
        self,
        method="direct",
        options=(),
        expected_ret_codes=None,
        break_repo=False,
        expect_updated=True,
    ):
        """
        Test both whether updates proxy works and whether is actually used
        by the qubes-vm-update

        :type self: qubes.tests.SystemTestCase | VmUpdatesMixin
        :type method: str
        :type options: tuple
        :type expected_ret_codes: tuple
        :type break_repo: bool
        :type: expect_updated: bool
        """
        if expected_ret_codes is None:
            expected_ret_codes = self.ret_code_ok

        self.start_vm_with_proxy_repo()

        with self.qrexec_policy(
            "qubes.UpdatesProxy",
            self.testvm1,
            "@default",
            action="allow target=" + self.netvm_repo.name,
        ):
            self.install_test_package()

            # verify if it was really installed
            self.assertRunCommandReturnCode(
                self.testvm1,
                self.install_test_cmd.format("test-pkg"),
                self.ret_code_ok,
            )

            self.add_update_to_repo()

            if break_repo:
                self.turn_off_repo()

            if method == "qubes-vm-update":
                self.run_qubes_vm_update_and_assert(
                    expected_ret_codes=expected_ret_codes, options=options
                )
            else:
                # update repository metadata
                self.assertRunCommandReturnCode(
                    self.testvm1, self.update_cmd, self.ret_code_ok
                )

                # install updates
                self.assertRunCommandReturnCode(
                    self.testvm1, self.upgrade_cmd, expected_ret_codes
                )

            # verify if it was really updated
            self.assertRunCommandReturnCode(
                self.testvm1,
                self.upgrade_test_cmd.format("test-pkg"),
                (0,) if expect_updated else (1,),
            )

    def test_010_update_via_proxy(self):
        """
        Test both whether updates proxy works and whether is actually used
        by the VM

        :type self: qubes.tests.SystemTestCase | VmUpdatesMixin
        """
        self.update_via_proxy_qubes_vm_update_impl()

    def upgrade_status_notify(self):
        """
        Run upgrades-status-notify at test vm.

        :type self: qubes.tests.SystemTestCase | VmUpdatesMixin
        """
        self.loop.run_until_complete(
            self.testvm1.run_for_stdio(
                "/usr/lib/qubes/upgrades-status-notify 2>/dev/console",
                user="root",
            )
        )

    def updates_available_notification_qubes_vm_update_impl(
        self, method="direct", options=(), expect_updated=True
    ):
        """
        Test if updates-available flags is updated.

        :type self: qubes.tests.SystemTestCase | VmUpdatesMixin
        :type method: str
        :type options: tuple
        :type expect_updated: bool
        """
        self.start_standalone_vm_with_repo()

        self.upgrade_status_notify()
        self.assertFalse(self.testvm1.features.get("updates-available", False))

        self.install_test_package()
        self.assertFalse(self.testvm1.features.get("updates-available", False))

        self.add_update_to_repo()
        # update repository metadata
        self.assertRunCommandReturnCode(
            self.testvm1, self.update_cmd, self.ret_code_ok
        )

        self.upgrade_status_notify()
        self.assertTrue(self.testvm1.features.get("updates-available", False))

        if method == "qubes-vm-update":
            self.run_qubes_vm_update_and_assert(
                expected_ret_codes=0, options=options
            )
        else:
            # install updates
            self.assertRunCommandReturnCode(
                self.testvm1, self.upgrade_cmd, self.ret_code_ok
            )

        self.assertFalse(self.testvm1.features.get("updates-available", False))

        # verify if it was really updated
        self.assertRunCommandReturnCode(
            self.testvm1,
            self.upgrade_test_cmd.format("test-pkg"),
            (0,) if expect_updated else (1,),
        )

    def test_020_updates_available_notification(self):
        """
        Test if updates-available flags is updated.

        :type self: qubes.tests.SystemTestCase | VmUpdatesMixin
        """
        self.updates_available_notification_qubes_vm_update_impl()

    def test_110_update_via_proxy_qubes_vm_update(self):
        self.update_via_proxy_qubes_vm_update_impl(
            method="qubes-vm-update", options=()
        )

    def test_111_update_via_proxy_qubes_vm_update_cli(self):
        self.update_via_proxy_qubes_vm_update_impl(
            method="qubes-vm-update", options=("--no-progress",)
        )

    def test_120_updates_available_notification_qubes_vm_update(self):
        self.updates_available_notification_qubes_vm_update_impl(
            method="qubes-vm-update", options=()
        )

    def test_121_updates_available_notification_qubes_vm_update_cli(self):
        self.updates_available_notification_qubes_vm_update_impl(
            method="qubes-vm-update", options=("--no-progress",)
        )

    def test_130_no_network_qubes_vm_update(self):
        expected_ret_codes = (23,)
        if self.template.count("archlinux"):
            # updater on Arch doesn't have separate metadata refresh step
            expected_ret_codes = (
                23,
                24,
            )
        self.update_via_proxy_qubes_vm_update_impl(
            method="qubes-vm-update",
            options=(),
            expected_ret_codes=expected_ret_codes,
            break_repo=True,
            expect_updated=False,
        )

    def test_131_no_network_qubes_vm_update_cli(self):
        expected_ret_codes = (23,)
        if self.template.count("archlinux"):
            # updater on Arch doesn't have separate metadata refresh step
            expected_ret_codes = (
                23,
                24,
            )
        self.update_via_proxy_qubes_vm_update_impl(
            method="qubes-vm-update",
            options=("--no-progress",),
            expected_ret_codes=expected_ret_codes,
            break_repo=True,
            expect_updated=False,
        )


def create_testcases_for_templates():
    yield from qubes.tests.create_testcases_for_templates(
        "VmUpdates",
        VmUpdatesMixin,
        qubes.tests.SystemTestCase,
        module=sys.modules[__name__],
    )


def load_tests(loader, tests, pattern):
    tests.addTests(loader.loadTestsFromNames(create_testcases_for_templates()))
    return tests


qubes.tests.maybe_create_testcases_on_import(create_testcases_for_templates)
