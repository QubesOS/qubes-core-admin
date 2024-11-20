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
    $ cat test-pkg-1.0-1.fc21.x86_64.rpm | gzip | base64
    $ cat test-pkg-1.1-1.fc21.x86_64.rpm | gzip | base64
    """
    RPM_PACKAGE_GZIP_BASE64 = [
        (
            b"H4sIAPzRLlYAA+2Y728URRjHn7ueUCkERKJVJDnTxLSxs7293o8WOER6ljYYrtKCLUSa3"
            b"bnZ64bd22VmTq8nr4wJbwxvjNHIG0x8oTHGGCHB8AcYE1/0lS80GgmQFCJU3wgB4ZjdfZ"
            b"q2xDe8NNlvMjfzmeeZH7tPbl98b35169cOUEpIJiTxT9SIrmVUs2hWh8dUAp54dOrM14s"
            b"JHK4D2DKl+j2qrVfjsuq3qEWbohjuAB2Lqk+p1o/8Z5QPmSi/YwnjezH+F8bLQZjqllW0"
            b"hvODRmFIL5hFk9JMXi/mi5ZuDleNwSEzP5wtmLnouNQnm3/6fndz7FLt9M/Hruj37gav4"
            b"tTjPnasWLFixYoVK1asWLFixYoV63+p0KNot9vnIPQc1vgYOwCSgXfxCoS+QzKHOVXVOj"
            b"Fn2ccIfI0k8nXkLuQbyJthxed4UrVnkG8i9yDfgsj3yCAv4foc8t+w1hf5B+Nl5Du43xj"
            b"yvxivIN9HpsgPkO2IU9uQfeRn8Xk/iJ4x1Y3nfxH1qecwfhH5+YgT25F7o/0SRdxvOppP"
            b"7MX9ZjB/DNnE/OOYX404uRGZIT+FbCFvQ3aQ8f0+/WF0XjJ8nyOw7H+BrmUA/a8pNZf2D"
            b"XrCqLG1cERbWHI8ajhznpBY9P0Tr8PkvJDMhTkp/Z0DA6xpuL7DNOq5A+DY9UYTmkOF2U"
            b"IO/sNt0wSnGvfdlZssD3rVIlLI9UUX37C6qXzHNntHPNfnTAhWHbUddtBwmegDjAUzZbu"
            b"m9lqZmzDmHc8Ik8WY8Tab4Myym4+Gx8V0qw8GtYyWIzrktEJwV9UHv3ktG471rAqHTmFQ"
            b"685V5uGqIalk06SWJr7tszR503Ac9cs493jJ8rhrSCIYbXBbzqt5v5+UZ0crh6bGR2dmJ"
            b"yuHD428VlLLLdakzJe2VxcKhFSFID73JKPS40RI7tXVCcQ3uOGWhPCJ2bAspiJ2i5Vy6n"
            b"jOqMerpEYpEe/Yks4xkU4Tt6BirmzUWanG6ozbFKhve9BsQRaLRTirzqk7hgUktXojKnf"
            b"n8jeg3X4QepP3i63po6oml+9t/CwJLya2Bn/ei6f7/4B3Ycdb0L3pt5Q5mNz16rWJ9fLk"
            b"vvOff/nxS7//8O2P2gvt7nDDnoV9L1du9N4+ucjl9u/8+a7dC5Nnvjlv9Ox5r+v9Cy0NE"
            b"m+c6rv60S/dZw98Gn6MNswcfQiWUvg3wBUAAA=="
        ),
        (
            b"H4sIAMY1B1wCA+2Y72scRRjH537U1MZorKLRVjgJSIKdvf11u3dq0jZJ0wRLL+1VvBRrn"
            b"J2dvVu6t7vd3bN3sS9ECr6RIkgR9JXQF5aiIk1L/gJF8EVe+KqiKLQQi03tmypojXO3zz"
            b"Vp8YW+3y/MPvOZ55lnZthhXjw3Lqx9n0FcqYiFEfaP17AkSLxZVJbQ/1QKbbl/6Mxnqyn"
            b"o9iE0uMTtOPTPcTvIJw1w+8DdDCj1KPBozJlVbrO8OcC/xvORH8/P3AT/2+D/DfynuTtH"
            b"FKtANKNo6KpKJIs3jSkl3VIkvSAWSiZTlCL3akhXZCKKKmPcaRRJqURFS2MlSTMsgyqMz"
            b"6RUp8SQFcmixZJpMlEWi0w1da3Eu3p3+1uW1saPHfpWOSvNXtruDVx4+A0+eAolSpQoUa"
            b"JEiRIlSpQoUaJEiRJBTWR9ff191K1p3FM3ySGUEbndjbp1jUwOYkzetkJMr07SqZukgX8"
            b"B7ge+DvwI2qijPMjbE8A3gIeB11BcVxGBb8J8FfgW+PcA3wb/FPAfkG8G+C/wl4HvAFPg"
            b"v4HtmLOPA/vAT8J534vPmB2C9T+NbfYp8C8DPx1zagfwSJwvpUO+ajye2gP55iF+BtiA+"
            b"Nch3ow5/TkwA74IbAFfBnaAl2N+7IN4vfQK8Ffg/w74arx++grwtTg+s7PDk6hXn0OSIC"
            b"Gozx3hYzmf0OOkxu6F1/oKlx2PEqfuhRFckv1zB1ClHUasgepR5L+Qz7MWafgOE6jXyCP"
            b"Hdpst1CpqC5qK/qUaKIQBFQK/sbGTXmeET8KaCgW7bZsbj3dsY2TSa/gBC0NmTtsOO0ga"
            b"LBxF4OuMTNk1nmtjbI60HY90g8MZ8iabC5hlt+53z4bVxVGkCKKgYgmpgiaIXdv5FgS52"
            b"5dUQY6P37kbWzcVNzd1cVnO4VoO+7bPcvhV4jj8y4LAC8YsL2iQCIeMNgM7avNxfxeeWp"
            b"guHz4yOz2/UCm/cnhy35jcG99/YHZislpd2Fup7OMR5YOVHLZYizI/sj035BBG/BdhP/A"
            b"iRiMvwGEUeC5fuxYw6gUmrlGKw5N2ROuMh4c+o+FYvhkGeX7wPD9/PmBmnURgcJ0EJnOZ"
            b"iSmV/kM4cV3PsN04uqGp/BM1XTZW4zkCm/L9kbDt0jrfk9cMcdM9absmjojhsI3NU4eE9"
            b"d4R+LG4g1qbGFHf9lBrEclwnTCs3r1iuOY2u/+jGVm4iCwiyXpJE61SkUq6RhVW0FVFpo"
            b"ZZ0oiu6ppuFSxSFBXTUOQCFRmhhElFQ9XNgiyJhbv/dnf8hnaeETR4R1+sHuX37+c/H/o"
            b"kjZ5Nbe88bMvv7voJvYWeOYaGBn7IGkr6xb3X5vqiExNL585/+NyPX3/5jbBzfaibcHhl"
            b"4vny9ZHfT6wG0Y6Lfrv/pZXKmS+WyPD4O/2nLy0KKHXo1OjVs1eGPn75o+5DvW3+6D9jd"
            b"bFaTBcAAA=="
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
        if not self.template.count("debian") and not self.template.count(
            "fedora"
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

        self.init_default_template(self.template)
        self.init_networking()
        self.testvm1 = self.app.add_new_vm(
            qubes.vm.appvm.AppVM, name=self.make_vm_name("vm1"), label="red"
        )
        self.loop.run_until_complete(self.testvm1.create_on_disk())
        self.repo_proc = None

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
        pkg_file_name = "test-pkg-1.{}-1.fc21.x86_64.rpm".format(version)
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

    def create_repo_and_serve(self):
        """
        :type self: qubes.tests.SystemTestCase | VmUpdatesMixin
        """
        if self.template.count("debian") or self.template.count("whonix"):
            self.create_repo_apt()
            self.repo_proc = self.loop.run_until_complete(
                self.netvm_repo.run(
                    "cd /tmp/apt-repo && python3 -m http.server 8080",
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            )
        elif self.template.count("fedora"):
            self.create_repo_yum()
            self.repo_proc = self.loop.run_until_complete(
                self.netvm_repo.run(
                    "cd /tmp/yum-repo && python3 -m http.server 8080",
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            )
        else:
            # not reachable...
            self.skipTest(
                "Template {} not supported by this test".format(self.template)
            )

    def add_update_to_repo(self):
        """
        :type self: qubes.tests.SystemTestCase | VmUpdatesMixin
        """
        if self.template.count("debian") or self.template.count("whonix"):
            self.create_repo_apt(1)
        elif self.template.count("fedora"):
            self.create_repo_yum(1)

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
            qubes.vm.appvm.AppVM, name=self.make_vm_name("net"), label="red"
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
        if self.template.count("minimal"):
            self.skipTest(
                "Template {} not supported by this test".format(self.template)
            )

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
                "/usr/lib/qubes/upgrades-status-notify",
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
        self.update_via_proxy_qubes_vm_update_impl(
            method="qubes-vm-update",
            options=(),
            expected_ret_codes=(23,),
            break_repo=True,
            expect_updated=False,
        )

    def test_131_no_network_qubes_vm_update_cli(self):
        self.update_via_proxy_qubes_vm_update_impl(
            method="qubes-vm-update",
            options=("--no-progress",),
            expected_ret_codes=(23,),
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
